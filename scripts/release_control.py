"""Inventory-driven release control for drain evidence (issue #741, task 8.3).

Usage
-----
::

    python scripts/release_control.py preflight      --inventory inventory.json [--max-age-seconds 15]
    python scripts/release_control.py drain-check    --inventory inventory.json [--timeout 120] [--max-age-seconds 15]
    python scripts/release_control.py pause-and-drain --inventory inventory.json
        [--timeout 120] [--reason "..."] [--max-age-seconds 15]
    python scripts/release_control.py compat-check   --inventory inventory.json --require-version 1 [--max-age-seconds 15]
    python scripts/release_control.py reopen         --inventory inventory.json [--require-version 1] [--max-age-seconds 15]
    python scripts/release_control.py readiness      --inventory inventory.json [--require-version 1] [--max-age-seconds 15]

Inventory JSON format
---------------------
::

    {
        "instances": [
            {"name": "backend-1", "url": "http://backend1", "token_env": "DRAIN_TOKEN_1"}
        ],
        "gateway": {"url": "http://gateway", "token_env": "GATEWAY_CONTROL_TOKEN"}
    }

Exit codes
----------
0  All checks passed.
1  One or more checks failed.
2  Reserved (not used; was timeout in earlier versions).
3  Timeout reached before drain completed (drain NOT established).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Inventory helpers
# ---------------------------------------------------------------------------


def _load_inventory(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def _drain_url(instance: dict) -> str:
    base = instance["url"].rstrip("/")
    return f"{base}/internal/drain"


def _drain_token(instance: dict) -> str:
    env = instance["token_env"]
    val = os.environ.get(env, "")
    if not val:
        raise RuntimeError(f"Environment variable {env!r} is not set or empty")
    return val


def _gateway_token(gateway: dict) -> str:
    env = gateway["token_env"]
    val = os.environ.get(env, "")
    if not val:
        raise RuntimeError(f"Environment variable {env!r} is not set or empty")
    return val


# ---------------------------------------------------------------------------
# Snapshot age check
# ---------------------------------------------------------------------------

_SENTINEL = object()


def _snapshot_age_seconds(snap: dict) -> float | None:
    """Return how old the snapshot's captured_at is in seconds, or None if missing/unparseable."""
    raw = snap.get("captured_at")
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return (datetime.now(UTC) - ts).total_seconds()
    except Exception:
        return None


def _check_snapshot_age(snap: dict, max_age: float) -> str | None:
    """Return 'stale' label if snap is older than max_age seconds, else None."""
    age = _snapshot_age_seconds(snap)
    if age is None:
        return "stale"
    if age > max_age:
        return "stale"
    return None


# ---------------------------------------------------------------------------
# Low-level fetch helpers
# ---------------------------------------------------------------------------


def _fetch_snapshot_classified(instance: dict) -> tuple[dict | None, str | None]:
    """Fetch and classify the drain snapshot for one instance.

    Returns (snapshot_dict, failure_label) where failure_label is one of:
      None          — success (snapshot_dict is valid)
      'unreachable' — connection error
      'uninstrumented' — 404 (drain endpoint not enabled)
      'unauthorized' — 403 (bad/missing token)
      'error:<N>'   — any other non-200 HTTP status
      'invalid-json' — response body is not valid JSON
      'unknown-shape' — JSON lacks required drain fields
    """
    try:
        token = _drain_token(instance)
    except RuntimeError as exc:
        print(f"  [ERROR] {exc}", file=sys.stderr)
        return None, "unreachable"
    try:
        r = httpx.get(
            _drain_url(instance),
            headers={"X-Drain-Token": token},
            timeout=10,
        )
    except httpx.HTTPError as exc:
        print(f"  [ERROR] {instance['name']}: connection failed: {exc}", file=sys.stderr)
        return None, "unreachable"

    if r.status_code == 404:
        return None, "uninstrumented"
    if r.status_code == 403:
        return None, "unauthorized"
    if r.status_code != 200:
        print(
            f"  [ERROR] {instance['name']}: HTTP {r.status_code}",
            file=sys.stderr,
        )
        return None, f"error:{r.status_code}"

    try:
        data = r.json()
    except Exception as exc:
        print(f"  [ERROR] {instance['name']}: invalid JSON: {exc}", file=sys.stderr)
        return None, "invalid-json"

    # Minimal shape check: must have instance_id and quiescent
    if not isinstance(data, dict) or "instance_id" not in data or "quiescent" not in data:
        return None, "unknown-shape"

    return data, None


def _fetch_snapshot(instance: dict) -> dict | None:
    """Return the drain snapshot dict, or None on any error (legacy helper)."""
    snap, _ = _fetch_snapshot_classified(instance)
    return snap


# ---------------------------------------------------------------------------
# Coverage check: duplicate instance_ids
# ---------------------------------------------------------------------------


def _check_coverage(snapshots: list[dict], inventory_count: int) -> str | None:
    """Return error string if duplicate instance_ids are detected, else None."""
    ids = [s["instance_id"] for s in snapshots]
    if len(set(ids)) < len(ids) or len(set(ids)) < inventory_count:
        return (
            "coverage: duplicate instance identity — "
            "random load-balancer sampling is not full coverage"
        )
    return None


# ---------------------------------------------------------------------------
# Validate a snapshot against evidence rules
# ---------------------------------------------------------------------------


def _validate_snapshot(
    snap: dict,
    inst_name: str,
    max_age: float,
) -> str | None:
    """Return a failure label if the snapshot fails an evidence rule, else None.

    Checks (in order): stale, nonzero counters, integrity_errors.
    """
    stale = _check_snapshot_age(snap, max_age)
    if stale:
        return "stale"
    if snap.get("integrity_errors", 0) > 0:
        return "integrity-errors"
    if not snap.get("quiescent", False):
        return "busy"
    return None


# ---------------------------------------------------------------------------
# Gateway control
# ---------------------------------------------------------------------------


def _pause_gateway(gateway: dict, reason: str | None = None) -> bool:
    """POST to gateway admission endpoint to pause. Returns True on success."""
    try:
        token = _gateway_token(gateway)
    except RuntimeError as exc:
        print(f"  [ERROR] {exc}", file=sys.stderr)
        return False
    url = gateway["url"].rstrip("/") + "/gateway/admission"
    body: dict[str, Any] = {"state": "paused"}
    if reason:
        body["reason"] = reason
    try:
        r = httpx.post(
            url,
            json=body,
            headers={"X-Gateway-Control-Token": token},
            timeout=10,
        )
    except httpx.HTTPError as exc:
        print(f"  [ERROR] gateway pause failed: {exc}", file=sys.stderr)
        return False
    if r.status_code != 200:
        print(f"  [ERROR] gateway pause returned HTTP {r.status_code}", file=sys.stderr)
        return False
    data = r.json()
    if data.get("state") != "paused":
        print(f"  [ERROR] gateway reported unexpected state: {data}", file=sys.stderr)
        return False
    return True


def _open_gateway(gateway: dict) -> bool:
    """POST to gateway admission endpoint to open. Returns True on success."""
    try:
        token = _gateway_token(gateway)
    except RuntimeError as exc:
        print(f"  [ERROR] {exc}", file=sys.stderr)
        return False
    url = gateway["url"].rstrip("/") + "/gateway/admission"
    try:
        r = httpx.post(
            url,
            json={"state": "open"},
            headers={"X-Gateway-Control-Token": token},
            timeout=10,
        )
    except httpx.HTTPError as exc:
        print(f"  [ERROR] gateway open failed: {exc}", file=sys.stderr)
        return False
    if r.status_code != 200:
        print(f"  [ERROR] gateway open returned HTTP {r.status_code}", file=sys.stderr)
        return False
    return True


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------


def cmd_preflight(args: argparse.Namespace) -> int:
    """Check that all instances are reachable and drain endpoint is responding."""
    inv = _load_inventory(args.inventory)
    instances = inv.get("instances", [])
    max_age: float = float(getattr(args, "max_age_seconds", 15))
    if not instances:
        print("[WARN] No instances in inventory.", file=sys.stderr)
        return 0

    failed = 0
    good_snaps: list[dict] = []
    for inst in instances:
        snap, label = _fetch_snapshot_classified(inst)
        if label is not None:
            failed += 1
            print(f"  [FAIL] {inst['name']}: {label}")
            continue
        assert snap is not None
        age_label = _check_snapshot_age(snap, max_age)
        if age_label:
            failed += 1
            print(f"  [FAIL] {inst['name']}: stale")
            continue
        good_snaps.append(snap)
        q = snap.get("quiescent")
        print(f"  [OK]   {inst['name']}: drain endpoint reachable, quiescent={q}")

    if good_snaps:
        dup = _check_coverage(good_snaps, len(instances))
        if dup:
            print(f"  [FAIL] {dup}")
            failed += 1

    if failed:
        print(f"\npreflight FAILED: {failed}/{len(instances)} instances failed")
        return 1
    print(f"\npreflight OK: {len(instances)}/{len(instances)} instances reachable")
    return 0


def cmd_drain_check(args: argparse.Namespace) -> int:
    """Poll all instances until all are quiescent or timeout.

    Exits 0 on success, 3 on timeout (drain NOT established).
    """
    inv = _load_inventory(args.inventory)
    instances = inv.get("instances", [])
    timeout: float = float(args.timeout)
    poll_interval: float = float(getattr(args, "poll_interval", 2.0))
    max_age: float = float(getattr(args, "max_age_seconds", 15))
    deadline = time.monotonic() + timeout

    while True:
        all_ok = True
        good_snaps: list[dict] = []
        for inst in instances:
            snap, label = _fetch_snapshot_classified(inst)
            if label is not None:
                all_ok = False
                print(f"  [FAIL] {inst['name']}: {label}")
                continue
            assert snap is not None
            fail_label = _validate_snapshot(snap, inst["name"], max_age)
            if fail_label:
                all_ok = False
                active = snap.get("active_runs", "?")
                print(f"  [WAIT] {inst['name']}: {fail_label} (active_runs={active})")
            else:
                good_snaps.append(snap)

        if all_ok and good_snaps:
            dup = _check_coverage(good_snaps, len(instances))
            if dup:
                all_ok = False
                print(f"  [FAIL] {dup}")

        if all_ok:
            print("drain-check OK: all instances quiescent")
            return 0

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(
                f"drain NOT established (timeout is not evidence); gate remains paused"
            )
            return 3

        sleep_for = min(poll_interval, remaining)
        time.sleep(sleep_for)


def cmd_pause_and_drain(args: argparse.Namespace) -> int:
    """Pause the gateway then wait for all instances to drain.

    Never calls open after a drain timeout.
    """
    inv = _load_inventory(args.inventory)
    gateway = inv.get("gateway")
    if not gateway:
        print("[ERROR] No gateway in inventory", file=sys.stderr)
        return 1

    reason = getattr(args, "reason", None)
    print(f"Pausing gateway at {gateway['url']} ...")
    ok = _pause_gateway(gateway, reason=reason)
    if not ok:
        return 1
    print("Gateway paused. Waiting for drain ...")
    return cmd_drain_check(args)


def cmd_compat_check(args: argparse.Namespace) -> int:
    """Verify all instances support the required stream version."""
    inv = _load_inventory(args.inventory)
    instances = inv.get("instances", [])
    required: int = int(args.require_version)
    max_age: float = float(getattr(args, "max_age_seconds", 15))
    failed = 0
    good_snaps: list[dict] = []
    for inst in instances:
        snap, label = _fetch_snapshot_classified(inst)
        if label is not None:
            failed += 1
            print(f"  [FAIL] {inst['name']}: {label}", file=sys.stderr)
            continue
        assert snap is not None
        age_label = _check_snapshot_age(snap, max_age)
        if age_label:
            failed += 1
            print(f"  [FAIL] {inst['name']}: stale", file=sys.stderr)
            continue
        good_snaps.append(snap)
        supported = snap.get("supported_stream_versions", [])
        if required not in supported:
            print(
                f"  [FAIL] {inst['name']}: version {required} not in {supported}",
                file=sys.stderr,
            )
            failed += 1
        else:
            print(f"  [OK]   {inst['name']}: supports version {required}")

    if good_snaps and not failed:
        dup = _check_coverage(good_snaps, len(instances))
        if dup:
            print(f"  [FAIL] {dup}", file=sys.stderr)
            failed += 1

    if failed:
        print(f"\ncompat-check FAILED: {failed}/{len(instances)} instances failed")
        return 1
    print(f"\ncompat-check OK: all {len(instances)} instances support version {required}")
    return 0


def cmd_reopen(args: argparse.Namespace) -> int:
    """Reopen the gateway — runs drain-check + compat-check first; opens only if both pass."""
    inv = _load_inventory(args.inventory)
    gateway = inv.get("gateway")
    if not gateway:
        print("[ERROR] No gateway in inventory", file=sys.stderr)
        return 1

    # 1. drain-check
    print("Running drain-check before reopen ...")
    dc_rc = cmd_drain_check(args)
    if dc_rc != 0:
        print("reopen ABORTED: drain-check failed; gateway remains paused.")
        return dc_rc

    # 2. compat-check (if require_version is present)
    if hasattr(args, "require_version") and args.require_version is not None:
        print("Running compat-check before reopen ...")
        cc_rc = cmd_compat_check(args)
        if cc_rc != 0:
            print("reopen ABORTED: compat-check failed; gateway remains paused.")
            return cc_rc

    # 3. open
    print(f"Reopening gateway at {gateway['url']} ...")
    ok = _open_gateway(gateway)
    if not ok:
        return 1
    print("Gateway reopened.")
    return 0


def cmd_readiness(args: argparse.Namespace) -> int:
    """Combined readiness check: preflight + compat-check + drain-check.

    Returns 0 only when all instances are reachable, support the required
    stream version, and are quiescent (no in-flight work).
    """
    inv = _load_inventory(args.inventory)
    instances = inv.get("instances", [])
    required: int = int(getattr(args, "require_version", 1))
    max_age: float = float(getattr(args, "max_age_seconds", 15))
    failed = 0
    good_snaps: list[dict] = []
    for inst in instances:
        snap, label = _fetch_snapshot_classified(inst)
        if label is not None:
            print(f"  [FAIL] {inst['name']}: {label}", file=sys.stderr)
            failed += 1
            continue
        assert snap is not None
        age_label = _check_snapshot_age(snap, max_age)
        if age_label:
            print(f"  [FAIL] {inst['name']}: stale", file=sys.stderr)
            failed += 1
            continue
        supported = snap.get("supported_stream_versions", [])
        if required not in supported:
            print(
                f"  [FAIL] {inst['name']}: version {required} not in {supported}",
                file=sys.stderr,
            )
            failed += 1
            continue
        if snap.get("integrity_errors", 0) > 0:
            print(
                f"  [FAIL] {inst['name']}: integrity-errors={snap['integrity_errors']}",
                file=sys.stderr,
            )
            failed += 1
            continue
        good_snaps.append(snap)
        quiescent = snap.get("quiescent", False)
        active = snap.get("active_runs", "?")
        if not quiescent:
            print(
                f"  [WARN] {inst['name']}: not quiescent (active_runs={active})",
                file=sys.stderr,
            )
            # non-quiescent is a warning, not a failure for readiness
        print(f"  [OK]   {inst['name']}: reachable, version={required}, quiescent={quiescent}")

    if good_snaps and not failed:
        dup = _check_coverage(good_snaps, len(instances))
        if dup:
            print(f"  [FAIL] {dup}", file=sys.stderr)
            failed += 1

    if failed:
        print(f"\nreadiness FAILED: {failed}/{len(instances)} instances failed checks")
        return 1
    print(f"\nreadiness OK: {len(instances)}/{len(instances)} instances ready")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="release_control.py",
        description="Inventory-driven release control for drain evidence (issue #741).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def _add_inv(p: argparse.ArgumentParser) -> None:
        p.add_argument("--inventory", default="inventory.json", help="Path to inventory JSON file")

    def _add_age(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--max-age-seconds", type=float, default=15, dest="max_age_seconds",
            help="Reject snapshots older than this many seconds (default 15)",
        )

    # preflight
    _pf = sub.add_parser("preflight", help="Check all instances are reachable")
    _add_inv(_pf)
    _add_age(_pf)

    # drain-check
    dc = sub.add_parser("drain-check", help="Poll until all instances are quiescent")
    _add_inv(dc)
    _add_age(dc)
    dc.add_argument("--timeout", type=float, default=300, help="Max wait seconds")
    dc.add_argument("--poll-interval", type=float, default=2.0, dest="poll_interval")

    # pause-and-drain
    pd = sub.add_parser("pause-and-drain", help="Pause gateway then drain")
    _add_inv(pd)
    _add_age(pd)
    pd.add_argument("--timeout", type=float, default=300)
    pd.add_argument("--poll-interval", type=float, default=2.0, dest="poll_interval")
    pd.add_argument("--reason", default=None)

    # compat-check
    cc = sub.add_parser("compat-check", help="Verify stream-version compatibility")
    _add_inv(cc)
    _add_age(cc)
    cc.add_argument("--require-version", type=int, default=1, dest="require_version")

    # reopen
    _re = sub.add_parser("reopen", help="Reopen the gateway (drain-check + compat-check first)")
    _add_inv(_re)
    _add_age(_re)
    _re.add_argument("--timeout", type=float, default=300)
    _re.add_argument("--poll-interval", type=float, default=2.0, dest="poll_interval")
    _re.add_argument(
        "--require-version", type=int, default=None, dest="require_version",
        help="Require this stream version on all instances before reopening",
    )

    # readiness
    _rd = sub.add_parser("readiness", help="Combined readiness: preflight + compat + quiescence")
    _add_inv(_rd)
    _add_age(_rd)
    _rd.add_argument("--require-version", type=int, default=1, dest="require_version")

    args = parser.parse_args(argv)
    _DISPATCH = {
        "preflight": cmd_preflight,
        "drain-check": cmd_drain_check,
        "pause-and-drain": cmd_pause_and_drain,
        "compat-check": cmd_compat_check,
        "reopen": cmd_reopen,
        "readiness": cmd_readiness,
    }
    return _DISPATCH[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
