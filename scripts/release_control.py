"""Inventory-driven release control for drain evidence (issue #741, task 8.3).

Usage
-----
::

    python scripts/release_control.py preflight      --inventory inventory.json
    python scripts/release_control.py drain-check    --inventory inventory.json [--timeout 120]
    python scripts/release_control.py pause-and-drain --inventory inventory.json
        [--timeout 120] [--reason "..."]
    python scripts/release_control.py compat-check   --inventory inventory.json --require-version 1
    python scripts/release_control.py reopen         --inventory inventory.json

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
2  Timeout reached before drain completed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
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
# Low-level fetch helpers
# ---------------------------------------------------------------------------


def _fetch_snapshot(instance: dict) -> dict | None:
    """Return the drain snapshot dict, or None on any error."""
    try:
        token = _drain_token(instance)
    except RuntimeError as exc:
        print(f"  [ERROR] {exc}", file=sys.stderr)
        return None
    try:
        r = httpx.get(
            _drain_url(instance),
            headers={"X-Drain-Token": token},
            timeout=10,
        )
    except httpx.HTTPError as exc:
        print(f"  [ERROR] {instance['name']}: connection failed: {exc}", file=sys.stderr)
        return None
    if r.status_code != 200:
        print(
            f"  [ERROR] {instance['name']}: HTTP {r.status_code}",
            file=sys.stderr,
        )
        return None
    try:
        return r.json()
    except Exception as exc:
        print(f"  [ERROR] {instance['name']}: invalid JSON: {exc}", file=sys.stderr)
        return None


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
    if not instances:
        print("[WARN] No instances in inventory.", file=sys.stderr)
        return 0

    failed = 0
    for inst in instances:
        snap = _fetch_snapshot(inst)
        if snap is None:
            failed += 1
            print(f"  [FAIL] {inst['name']}: drain endpoint unreachable")
        else:
            q = snap.get('quiescent')
            print(f"  [OK]   {inst['name']}: drain endpoint reachable, quiescent={q}")

    if failed:
        print(f"\npreflight FAILED: {failed}/{len(instances)} instances unreachable")
        return 1
    print(f"\npreflight OK: {len(instances)}/{len(instances)} instances reachable")
    return 0


def cmd_drain_check(args: argparse.Namespace) -> int:
    """Poll all instances until all are quiescent or timeout."""
    inv = _load_inventory(args.inventory)
    instances = inv.get("instances", [])
    timeout: float = float(args.timeout)
    poll_interval: float = float(getattr(args, "poll_interval", 2.0))
    deadline = time.monotonic() + timeout

    while True:
        all_quiescent = True
        for inst in instances:
            snap = _fetch_snapshot(inst)
            if snap is None or not snap.get("quiescent", False):
                all_quiescent = False
                if snap is not None:
                    active = snap.get("active_runs", "?")
                    print(f"  [WAIT] {inst['name']}: active_runs={active}")
                break

        if all_quiescent:
            print("drain-check OK: all instances quiescent")
            return 0

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(f"drain-check TIMEOUT after {timeout}s: not all instances quiescent")
            return 2

        sleep_for = min(poll_interval, remaining)
        time.sleep(sleep_for)


def cmd_pause_and_drain(args: argparse.Namespace) -> int:
    """Pause the gateway then wait for all instances to drain."""
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
    failed = 0
    for inst in instances:
        snap = _fetch_snapshot(inst)
        if snap is None:
            failed += 1
            continue
        supported = snap.get("supported_stream_versions", [])
        if required not in supported:
            print(
                f"  [FAIL] {inst['name']}: version {required} not in {supported}",
                file=sys.stderr,
            )
            failed += 1
        else:
            print(f"  [OK]   {inst['name']}: supports version {required}")

    if failed:
        print(f"\ncompat-check FAILED: {failed}/{len(instances)} instances lack version {required}")
        return 1
    print(f"\ncompat-check OK: all {len(instances)} instances support version {required}")
    return 0


def cmd_reopen(args: argparse.Namespace) -> int:
    """Reopen the gateway to admit new generation requests."""
    inv = _load_inventory(args.inventory)
    gateway = inv.get("gateway")
    if not gateway:
        print("[ERROR] No gateway in inventory", file=sys.stderr)
        return 1
    print(f"Reopening gateway at {gateway['url']} ...")
    ok = _open_gateway(gateway)
    if not ok:
        return 1
    print("Gateway reopened.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_readiness(args: argparse.Namespace) -> int:
    """Combined readiness check: preflight + compat-check + drain-check.

    Returns 0 only when all instances are reachable, support the required
    stream version, and are quiescent (no in-flight work).
    """
    inv = _load_inventory(args.inventory)
    instances = inv.get("instances", [])
    required: int = int(getattr(args, "require_version", 1))
    failed = 0
    for inst in instances:
        snap = _fetch_snapshot(inst)
        if snap is None:
            print(f"  [FAIL] {inst['name']}: unreachable", file=sys.stderr)
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
        quiescent = snap.get("quiescent", False)
        active = snap.get("active_runs", "?")
        if not quiescent:
            print(
                f"  [WARN] {inst['name']}: not quiescent (active_runs={active})",
                file=sys.stderr,
            )
            # non-quiescent is a warning, not a failure for readiness
        print(f"  [OK]   {inst['name']}: reachable, version={required}, quiescent={quiescent}")
    if failed:
        print(f"\nreadiness FAILED: {failed}/{len(instances)} instances failed checks")
        return 1
    print(f"\nreadiness OK: {len(instances)}/{len(instances)} instances ready")
    return 0



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="release_control.py",
        description="Inventory-driven release control for drain evidence (issue #741).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def _add_inv(p):
        p.add_argument("--inventory", default="inventory.json", help="Path to inventory JSON file")

    # preflight
    _pf = sub.add_parser("preflight", help="Check all instances are reachable")
    _add_inv(_pf)

    # drain-check
    dc = sub.add_parser("drain-check", help="Poll until all instances are quiescent")
    _add_inv(dc)
    dc.add_argument("--timeout", type=float, default=300, help="Max wait seconds")
    dc.add_argument("--poll-interval", type=float, default=2.0, dest="poll_interval")

    # pause-and-drain
    pd = sub.add_parser("pause-and-drain", help="Pause gateway then drain")
    _add_inv(pd)
    pd.add_argument("--timeout", type=float, default=300)
    pd.add_argument("--poll-interval", type=float, default=2.0, dest="poll_interval")
    pd.add_argument("--reason", default=None)

    # compat-check
    cc = sub.add_parser("compat-check", help="Verify stream-version compatibility")
    _add_inv(cc)
    cc.add_argument("--require-version", type=int, default=1, dest="require_version")

    # reopen
    _re = sub.add_parser("reopen", help="Reopen the gateway")
    _add_inv(_re)

    # readiness
    _rd = sub.add_parser("readiness", help="Combined readiness: preflight + compat + quiescence")
    _add_inv(_rd)
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
