"""Capture and analyse GET /api/generate SSE streams for issue #689.

Usage:
    python scripts/capture_sse_689.py --token TOKEN --out /tmp/cap689 --scenario control
    python scripts/capture_sse_689.py --token TOKEN --out /tmp/cap689 --scenario starve
    python scripts/capture_sse_689.py --selftest

The script records raw byte-level timing from the SSE stream, compares arrival
timestamps against the server-emitted ``ts`` fields in pipeline/stage events,
monitors /health latency during each run, and (with --scenario starve) attempts
to reproduce the renderer-pool starvation described in #689 by aborting two runs
that each hold a Playwright renderer, then timing how long run C takes to reach
pipeline_start.

Rate limits: staging allows 10 GET /api/generate per user per hour and 30
POST /api/generate/resolve per hour.  The ``control`` scenario issues 1 generate
request; ``starve`` issues 3.
"""

from __future__ import annotations

import argparse
import email.utils
import json
import os
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Query-string builder
# (mirrors the embedded Python in scripts/verify_figure_kind_diversity_staging.sh)
# ---------------------------------------------------------------------------

_FIELD_ORDER: list[tuple[str, str]] = [
    ("scalar", "subject"),
    ("scalar", "grade"),
    ("scalar", "content_type"),
    ("scalar", "set_type"),
    ("scalar", "count"),
    ("scalar", "skip_verify"),
    ("scalar", "disable_reference_fewshot"),
    ("scalar", "seed"),
    ("scalar", "max_retries"),
    ("scalar", "allow_duplicate_figure_kinds"),
    ("scalar", "image_generation_mode"),
    ("repeated", "style"),
    ("repeated", "context"),
    ("repeated", "q_type"),
    ("repeated", "subject_filter"),
    ("scalar", "content_domain"),
    ("scalar", "target_surface"),
    ("scalar", "passage"),
    ("repeated", "options"),
    ("scalar", "topic"),
    ("scalar", "core_question"),
    ("scalar", "sub_context"),
    ("repeated", "science_competency"),
    ("scalar", "reporting_scale"),
    ("repeated", "learning_performance"),
    ("repeated", "core_competency"),
    ("repeated", "math_thinking"),
    ("repeated", "learning_content"),
    ("scalar", "sub_question_count"),
    ("scalar", "question_word_limit"),
    ("scalar", "option_word_limit"),
    ("scalar", "text_word_limit"),
    ("json", "subquestion_configs"),
    ("json", "per_question_params"),
    ("repeated", "drawn"),
    ("scalar", "difficulty"),
    ("scalar", "model_plan"),
    ("scalar", "model_execute"),
    ("scalar", "model_verify"),
    ("scalar", "model_correct"),
    ("scalar", "effort_plan"),
    ("scalar", "effort_execute"),
    ("scalar", "effort_verify"),
    ("scalar", "effort_correct"),
    ("scalar", "coverage_mode"),
    ("scalar", "core_question_callback"),
]


def _compact(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def _scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, dict)):
        return _compact(v)
    return str(v)


def _json_field(name: str, v: Any) -> str:
    if name == "per_question_params" and isinstance(v, list):
        rows = []
        for row in v:
            if isinstance(row, dict):
                row = dict(row)
                cfg = row.get("subquestion_configs")
                if isinstance(cfg, (list, dict)):
                    row["subquestion_configs"] = _compact(cfg)
            rows.append(row)
        v = rows
    return v if isinstance(v, str) else _compact(v)


def build_generate_query(payload: dict, drawn: list[str]) -> list[tuple[str, str]]:
    """Return (name, raw-value) pairs for curl --data-urlencode, in wire field order.

    Reproduces the embedded Python in verify_figure_kind_diversity_staging.sh
    byte-for-byte in behaviour: same field_order, same scalar/repeated/json
    kinds, drawn is the de-duplicated union of payload["drawn"] and *drawn*.
    """
    p = dict(payload)
    prior = p.get("drawn")
    p["drawn"] = list(dict.fromkeys([*(prior if isinstance(prior, list) else []), *drawn]))
    pairs: list[tuple[str, str]] = []
    for kind, name in _FIELD_ORDER:
        v = p.get(name)
        if v is None:
            continue
        if kind == "repeated":
            items = v if isinstance(v, list) else [v]
            for item in items:
                pairs.append((name, _scalar(item)))
        elif kind == "json":
            pairs.append((name, _json_field(name, v)))
        else:
            pairs.append((name, _scalar(v)))
    return pairs


# ---------------------------------------------------------------------------
# Incremental SSE parser
# ---------------------------------------------------------------------------


class _SSEParser:
    """Stateful incremental SSE parser; call feed() once per raw line."""

    def __init__(self) -> None:
        self._event_name = ""
        self._data_lines: list[str] = []
        self.events: list[dict[str, Any]] = []
        self.pings: list[float] = []
        self.ts_deltas: list[tuple[str, str, float, float, float]] = []

    def feed(self, raw: bytes, arrival: float) -> None:
        line = raw.rstrip(b"\r\n")
        if not line:
            self._dispatch(arrival)
            return
        if line.startswith(b":"):
            comment = line.decode("utf-8", errors="replace")
            if ": ping" in comment:
                self.pings.append(arrival)
            return
        if line.startswith(b"event:"):
            val = line[len(b"event:"):].decode("utf-8", errors="replace")
            self._event_name = val[1:] if val.startswith(" ") else val
        elif line.startswith(b"data:"):
            val = line[len(b"data:"):].decode("utf-8", errors="replace")
            self._data_lines.append(val[1:] if val.startswith(" ") else val)

    def _dispatch(self, arrival: float) -> None:
        if not self._event_name and not self._data_lines:
            return
        data = "\n".join(self._data_lines)
        evt: dict[str, Any] = {"event": self._event_name, "data": data, "arrival": arrival}
        try:
            parsed = json.loads(data) if data else None
            if isinstance(parsed, dict):
                evt["parsed"] = parsed
                ts = parsed.get("ts")
                if isinstance(ts, (int, float)):
                    inner: str
                    if parsed.get("event_name"):
                        inner = str(parsed["event_name"])
                    elif parsed.get("agent"):
                        inner = (
                            f"{parsed.get('agent')}:{parsed.get('stage')}:{parsed.get('status')}"
                        )
                    else:
                        inner = ""
                    self.ts_deltas.append(
                        (self._event_name, inner, arrival, float(ts), arrival - float(ts))
                    )
        except (json.JSONDecodeError, ValueError):
            pass
        self.events.append(evt)
        self._event_name = ""
        self._data_lines = []


# ---------------------------------------------------------------------------
# Clock-skew estimate
# ---------------------------------------------------------------------------


def _estimate_skew(base_url: str) -> float:
    """Return mean (server_clock - local_clock) from 3 /health requests (1 s resolution)."""
    skews: list[float] = []
    for _ in range(3):
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=10) as resp:
                t_local = time.time()
                date_hdr = resp.headers.get("Date", "")
            if date_hdr:
                skews.append(email.utils.parsedate_to_datetime(date_hdr).timestamp() - t_local)
        except Exception:
            pass
        time.sleep(0.3)
    return statistics.mean(skews) if skews else float("nan")


# ---------------------------------------------------------------------------
# Background health-poll thread
# ---------------------------------------------------------------------------


def _health_poll(
    base_url: str,
    interval: float,
    stop: threading.Event,
    log_path: Path,
) -> None:
    with log_path.open("a", encoding="utf-8") as fh:
        while not stop.wait(interval):
            t0 = time.time()
            try:
                with urllib.request.urlopen(f"{base_url}/health", timeout=30) as r:
                    status = r.status
                latency = time.time() - t0
                fh.write(f"{t0:.6f}\t{latency:.4f}\t{status}\n")
            except Exception as exc:
                fh.write(f"{t0:.6f}\t{time.time() - t0:.4f}\tERR:{exc!s}\n")
            fh.flush()


# ---------------------------------------------------------------------------
# Single-run capture
# ---------------------------------------------------------------------------


def capture_run(
    name: str,
    base_url: str,
    token: str,
    query_pairs: list[tuple[str, str]],
    out: Path,
    http: str = "2",
    gen_timeout: int = 1500,
    abort_on_stage: str | None = "image_agent:render_image:start",
    abort_after: float | None = 240.0,
    health_interval: float = 1.0,
    skew: float = float("nan"),
) -> dict[str, Any]:
    """Stream one GET /api/generate request, recording frame timing and events.

    Returns a summary dict; also writes
      <out>/<name>.frames.log   raw-line arrival log (repr-encoded)
      <out>/<name>.headers      curl -D response headers
      <out>/<name>.health.log   /health poll log (if health_interval > 0)
      <out>/<name>.summary.json copy of the returned summary
    """
    out.mkdir(parents=True, exist_ok=True)
    headers_path = out / f"{name}.headers"
    frames_path = out / f"{name}.frames.log"
    health_path = out / f"{name}.health.log"

    http_flag = "--http2" if http == "2" else "--http1.1"
    cmd = [
        "curl", "-N", "-sS", http_flag,
        "-D", str(headers_path),
        "-H", f"Authorization: Bearer {token}",
        "-H", "Accept: text/event-stream",
        "--max-time", str(gen_timeout),
        "-w", "\n__CURL_META__ http_version=%{http_version} time_total=%{time_total}\n",
        "--get",
    ]
    for k, v in query_pairs:
        cmd += ["--data-urlencode", f"{k}={v}"]
    cmd.append(f"{base_url}/api/generate")

    sse = _SSEParser()
    t_start = time.time()
    t_first_byte: float | None = None
    t_started: float | None = None
    t_pipeline_start: float | None = None
    aborted_at: float | None = None
    abort_trigger: str | None = None
    curl_meta: str | None = None
    terminal = "disconnect"
    line_times: list[float] = []

    stop_health = threading.Event()
    if health_interval > 0:
        threading.Thread(
            target=_health_poll,
            args=(base_url, health_interval, stop_health, health_path),
            daemon=True,
        ).start()

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    frames_fh = frames_path.open("ab")
    try:
        for raw in proc.stdout:
            t_arr = time.time()
            line_times.append(t_arr)
            if t_first_byte is None:
                t_first_byte = t_arr
            if b"__CURL_META__" in raw:
                curl_meta = raw.decode("utf-8", errors="replace").strip()
                continue
            frames_fh.write(f"{t_arr:.6f}\t{raw!r}\n".encode())
            sse.feed(raw, t_arr)
            if not sse.events:
                continue
            last = sse.events[-1]
            ev, parsed = last["event"], last.get("parsed") or {}
            if ev == "started" and t_started is None:
                t_started = t_arr
            if (
                ev == "pipeline"
                and isinstance(parsed, dict)
                and parsed.get("event_name") == "pipeline_start"
                and t_pipeline_start is None
            ):
                t_pipeline_start = t_arr
            if ev in ("done", "error"):
                terminal = "done" if ev == "done" else f"error:{parsed.get('message', '')[:120]}"
                break
            if abort_on_stage and ev == "stage" and isinstance(parsed, dict):
                sig = f"{parsed.get('agent')}:{parsed.get('stage')}:{parsed.get('status')}"
                if sig == abort_on_stage:
                    proc.kill()
                    aborted_at, abort_trigger = t_arr, f"stage:{sig}"
                    terminal = f"aborted-by-script:{abort_trigger}"
                    break
            if abort_after and (t_arr - t_start) > abort_after and aborted_at is None:
                proc.kill()
                aborted_at = time.time()
                abort_trigger = f"abort_after:{abort_after}s"
                terminal = f"aborted-by-script:{abort_trigger}"
                break
    finally:
        frames_fh.close()
        stop_health.set()
        proc.wait()

    t_end = time.time()
    curl_stderr = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", errors="replace")
    curl_rc = proc.returncode

    gaps = [line_times[i + 1] - line_times[i] for i in range(len(line_times) - 1)]
    ping_ivs = [sse.pings[i + 1] - sse.pings[i] for i in range(len(sse.pings) - 1)]
    deltas = [d[4] for d in sse.ts_deltas]
    top5 = sorted(sse.ts_deltas, key=lambda x: abs(x[4]), reverse=True)[:5]

    max_h_lat, max_h_epoch, max_h_in_win = 0.0, 0.0, False
    if health_path.exists():
        for ln in health_path.read_text(encoding="utf-8").splitlines():
            parts = ln.split("\t")
            if len(parts) >= 2:
                try:
                    ep, lat = float(parts[0]), float(parts[1])
                    if lat > max_h_lat:
                        max_h_lat, max_h_epoch = lat, ep
                        max_h_in_win = bool(
                            t_started and t_pipeline_start
                            and t_started <= ep <= t_pipeline_start
                        )
                except ValueError:
                    pass

    http_status: str | None = None
    try:
        first_line = headers_path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        parts = first_line.split()
        http_status = parts[1] if len(parts) >= 2 else None
    except Exception:
        pass

    def _meta(key: str) -> str | None:
        if not curl_meta:
            return None
        for part in curl_meta.split():
            if part.startswith(f"{key}="):
                return part[len(f"{key}="):]
        return None

    summary: dict[str, Any] = {
        "run": name,
        "request_start_epoch": t_start,
        "request_start_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_start)),
        "http_status": http_status,
        "http_version": _meta("http_version"),
        "seconds_to_first_byte": round(t_first_byte - t_start, 3) if t_first_byte else None,
        "seconds_to_started": round(t_started - t_start, 3) if t_started else None,
        "seconds_to_pipeline_start": (
            round(t_pipeline_start - t_start, 3) if t_pipeline_start else None
        ),
        "gap_started_to_pipeline_start": (
            round(t_pipeline_start - t_started, 3)
            if t_started and t_pipeline_start
            else None
        ),
        "total_duration_s": round(t_end - t_start, 3),
        "ping_count": len(sse.pings),
        "max_ping_interval_s": round(max(ping_ivs), 3) if ping_ivs else None,
        "median_ping_interval_s": round(statistics.median(ping_ivs), 3) if ping_ivs else None,
        "longest_gap_s": round(max(gaps), 3) if gaps else None,
        "arrival_ts_delta_min": round(min(deltas), 3) if deltas else None,
        "arrival_ts_delta_median": round(statistics.median(deltas), 3) if deltas else None,
        "arrival_ts_delta_max": round(max(deltas), 3) if deltas else None,
        "top5_ts_deltas": [
            {"event": t[0], "inner": t[1], "arrival": t[2], "ts": t[3], "delta": round(t[4], 3)}
            for t in top5
        ],
        "first_15_events": [
            {
                "event": e["event"],
                "inner": (e.get("parsed") or {}).get("event_name"),
                "arrival_offset_s": round(e["arrival"] - t_start, 3),
            }
            for e in sse.events[:15]
        ],
        "pipeline_events": [
            {
                "event_name": (e.get("parsed") or {}).get("event_name"),
                "arrival_offset_s": round(e["arrival"] - t_start, 3),
            }
            for e in sse.events
            if e["event"] == "pipeline"
        ],
        "event_counts": {
            ev: sum(1 for e in sse.events if e["event"] == ev)
            for ev in dict.fromkeys(e["event"] for e in sse.events)
        },
        "terminal": terminal,
        "curl_exit_code": curl_rc,
        "curl_stderr": curl_stderr[:2000],
        "max_health_latency_s": round(max_h_lat, 3),
        "max_health_latency_epoch": max_h_epoch or None,
        "max_health_in_started_pipeline_window": max_h_in_win,
        "clock_skew_s": round(skew, 3) if skew == skew else None,  # NaN check
        "aborted_at": aborted_at,
        "abort_trigger": abort_trigger,
    }

    summary_path = out / f"{name}.summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


# ---------------------------------------------------------------------------
# Scenario helpers
# ---------------------------------------------------------------------------

_SUBQ = [{"content_type": "含圖片"}, {"content_type": "含圖片"}, {}]

_PARTIAL_PAYLOAD = {
    "subject": "social_studies",
    "grade": 8,
    "content_type": "含圖片",
    "image_generation_mode": "gpt_image",
    "sub_question_count": 3,
    "subquestion_configs": _SUBQ,
    "count": 1,
    "skip_verify": True,
    "redraws": {},
}


def _resolve(base_url: str, token: str, seed: int) -> tuple[dict, list[str]]:
    payload = dict(_PARTIAL_PAYLOAD, seed=seed)
    body = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(
        f"{base_url}/api/generate/resolve",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data["payload"], data["drawn"]


def _print_summary(s: dict[str, Any]) -> None:
    print(f"  run={s['run']}  status={s['http_status']}  terminal={s['terminal']}")
    print(f"  started={s['seconds_to_started']}s  pipeline_start={s['seconds_to_pipeline_start']}s"
          f"  gap={s['gap_started_to_pipeline_start']}s  total={s['total_duration_s']}s")
    print(f"  pings={s['ping_count']}  max_health_lat={s['max_health_latency_s']}s"
          f"  in_window={s['max_health_in_started_pipeline_window']}")


def run_control(
    base_url: str,
    token: str,
    out: Path,
    seed: int,
    http: str,
    gen_timeout: int,
    health_interval: float,
    skew: float,
) -> None:
    print("\nScenario: control (1 generate request)")
    payload, drawn = _resolve(base_url, token, seed)
    pairs = build_generate_query(payload, drawn)
    s = capture_run(
        "control",
        base_url,
        token,
        pairs,
        out,
        http=http,
        gen_timeout=gen_timeout,
        abort_on_stage=None,
        abort_after=None,
        health_interval=health_interval,
        skew=skew,
    )
    _print_summary(s)


def run_starve(
    base_url: str,
    token: str,
    out: Path,
    seed: int,
    http: str,
    gen_timeout: int,
    abort_on_stage: str,
    abort_after: float,
    health_interval: float,
    skew: float,
) -> None:
    print("\nScenario: starve (3 generate requests)")
    payload, drawn = _resolve(base_url, token, seed)
    pairs = build_generate_query(payload, drawn)

    summaries: list[dict[str, Any]] = [{}] * 2
    errors: list[Exception | None] = [None, None]

    def _run_ab(idx: int) -> None:
        try:
            summaries[idx] = capture_run(
                f"starve_{chr(65 + idx)}",
                base_url, token, pairs, out,
                http=http, gen_timeout=gen_timeout,
                abort_on_stage=abort_on_stage,
                abort_after=abort_after,
                health_interval=0.0,  # health poll only on run C
                skew=skew,
            )
        except Exception as exc:
            errors[idx] = exc

    t_a = threading.Thread(target=_run_ab, args=(0,))
    t_b = threading.Thread(target=_run_ab, args=(1,))
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    for i, (s, err) in enumerate(zip(summaries, errors)):
        if err:
            print(f"  run {chr(65 + i)} ERROR: {err}")
        else:
            _print_summary(s)

    print("\nBoth A and B aborted; starting run C (health poll on, no abort)...")
    s_c = capture_run(
        "starve_C",
        base_url, token, pairs, out,
        http=http, gen_timeout=gen_timeout,
        abort_on_stage=None,
        abort_after=None,
        health_interval=health_interval,
        skew=skew,
    )
    _print_summary(s_c)

    print("\n=== Starvation result ===")
    for i, s in enumerate(summaries):
        print(f"  Run {chr(65 + i)} aborted at offset {s.get('aborted_at', '?')}"
              f" trigger={s.get('abort_trigger')}")
    print(f"  Run C gap started→pipeline_start: {s_c['gap_started_to_pipeline_start']}s")

    try:
        req = urllib.request.Request(
            f"{base_url}/api/history?limit=10&subject=social_studies",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            hist = json.loads(resp.read())
        (out / "history.json").write_text(
            json.dumps(hist, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print("\nRecent history:")
        for item in (hist.get("items") or hist if isinstance(hist, list) else [])[:10]:
            preview = str(item.get("question_json") or "")[:60]
            print(f"  {item.get('id')} {item.get('status')} {item.get('created_at')} "
                  f"err={item.get('error')} preview={preview!r}")
    except Exception as exc:
        print(f"  history fetch failed: {exc}")


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def selftest() -> None:
    """Verify the SSE parser and build_generate_query against inline fixtures."""
    FIXTURE = (
        b"event: started\r\ndata: \r\n\r\n"
        b": ping - 1\r\n\r\n"
        b'event: stage\r\ndata: {"agent":"img_agent","stage":"render","status":"start"'
        b',"ts":1000.5}\r\n\r\n'
        b'event: pipeline\r\ndata: {"event_name":"pipeline_start","ts":1001.0,'
        b'"total":1}\r\n\r\n'
        b"event: multi\r\ndata: line1\r\ndata: line2\r\n\r\n"
        b"event: done\r\ndata: \r\n\r\n"
    )

    parser = _SSEParser()
    t0 = 1700000000.0
    for i, raw in enumerate(FIXTURE.split(b"\r\n")):
        parser.feed(raw + b"\r\n", t0 + i * 0.1)

    ev_names = [e["event"] for e in parser.events]
    assert ev_names == ["started", "stage", "pipeline", "multi", "done"], (
        f"parsed event sequence wrong: {ev_names}"
    )
    assert len(parser.pings) == 1, f"expected exactly 1 ping; got {parser.pings}"

    multi = next(e for e in parser.events if e["event"] == "multi")
    assert multi["data"] == "line1\nline2", f"multi-line data wrong: {multi['data']!r}"

    assert len(parser.ts_deltas) == 2, f"expected 2 ts_deltas; got {len(parser.ts_deltas)}"
    stage_delta = next(d for d in parser.ts_deltas if d[0] == "stage")
    assert stage_delta[1] == "img_agent:render:start", f"inner name wrong: {stage_delta[1]}"
    pipeline_delta = next(d for d in parser.ts_deltas if d[0] == "pipeline")
    assert pipeline_delta[1] == "pipeline_start", f"inner name wrong: {pipeline_delta[1]}"

    # build_generate_query
    bpayload = {
        "subject": "social_studies",
        "grade": 8,
        "skip_verify": True,
        "drawn": ["img1"],
        "subquestion_configs": [{"content_type": "含圖片"}],
    }
    bdrawn = ["img2"]
    pairs = build_generate_query(bpayload, bdrawn)
    pair_map: dict[str, list[str]] = {}
    for k, v in pairs:
        pair_map.setdefault(k, []).append(v)
    assert pair_map.get("subject") == ["social_studies"], pair_map
    assert pair_map.get("grade") == ["8"], pair_map
    assert pair_map.get("skip_verify") == ["true"], pair_map
    assert pair_map.get("drawn") == ["img1", "img2"], f"drawn wrong: {pair_map.get('drawn')}"
    sq = pair_map.get("subquestion_configs", [])
    assert sq and "含圖片" in sq[0], f"subquestion_configs wrong: {sq}"

    # Verify field order: subject before grade before skip_verify before subquestion_configs
    keys = [k for k, _ in pairs]
    assert keys.index("subject") < keys.index("grade"), "field order wrong"
    assert keys.index("grade") < keys.index("skip_verify"), "field order wrong"
    assert keys.index("skip_verify") < keys.index("subquestion_configs"), "field order wrong"
    assert keys.index("subquestion_configs") < keys.index("drawn"), "field order wrong"

    print("PASS")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--base-url", default="https://examgen-staging.cpeng.me")
    ap.add_argument("--token", default=os.environ.get("STAGING_BEARER_TOKEN", ""))
    ap.add_argument("--out", type=Path)
    ap.add_argument("--http", choices=["2", "1.1"], default="2")
    ap.add_argument("--scenario", choices=["control", "starve"], default="control")
    ap.add_argument("--seed", type=int, default=554)
    ap.add_argument("--gen-timeout", type=int, default=1500)
    ap.add_argument("--abort-on-stage", default="image_agent:render_image:start")
    ap.add_argument("--abort-after", type=float, default=240.0)
    ap.add_argument("--health-poll", type=float, default=1.0)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()

    if not args.token:
        ap.error("--token or STAGING_BEARER_TOKEN env var is required")
    if not args.out:
        ap.error("--out is required")

    n_requests = 1 if args.scenario == "control" else 3
    print(f"Scenario: {args.scenario}  ({n_requests} generate request(s))")
    print(f"Rate-limit note: staging allows 10 GET /api/generate per user per hour; "
          f"this scenario will issue {n_requests}.")

    args.out.mkdir(parents=True, exist_ok=True)
    skew = _estimate_skew(args.base_url)
    print(f"Clock skew estimate (server - local): {skew:.1f}s")

    if args.scenario == "control":
        run_control(
            args.base_url, args.token, args.out, args.seed,
            args.http, args.gen_timeout, args.health_poll, skew,
        )
    else:
        run_starve(
            args.base_url, args.token, args.out, args.seed,
            args.http, args.gen_timeout, args.abort_on_stage,
            args.abort_after, args.health_poll, skew,
        )


if __name__ == "__main__":
    main()
