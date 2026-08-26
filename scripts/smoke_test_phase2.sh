#!/usr/bin/env bash
# Phase 2 end-to-end SSE generation smoke test.
#
# Verifies the items in issue #11 (Phase 2.3 checklist):
#   - /api/generate streams SSE events with curl -N
#   - progress / result / done events appear
#   - result event contains valid ExamQuestion JSON (題目, 正確解題分析, ...)
#   - generation_log row is written with status="completed"
#   - two simultaneous requests are serialized by the semaphore (no error)
#   - --style with_chart returns image_base64 in the result event
#
# This script reuses the Phase 1 magic-link flow to obtain a JWT, then runs
# the Phase 2 SSE checks.
#
# Prereqs:
#   - Server running:  uvicorn server.app:create_app --factory --reload
#   - EMAIL_BACKEND=console (default) so the magic link prints to stdout
#   - LLM_API_KEY exported in the server's environment so generation can run
#
# Usage:
#   scripts/smoke_test_phase2.sh [BASE_URL] [EMAIL] [DB_PATH]
#
# DB_PATH defaults to ./exam_generation.db (sqlite). Override if your server
# uses a different path; pass an empty string to skip the DB check.

set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"
EMAIL="${2:-test@example.com}"
DB_PATH="${3:-exam_generation.db}"

pass() { printf "  \033[32mPASS\033[0m  %s\n" "$1"; }
fail() { printf "  \033[31mFAIL\033[0m  %s\n" "$1"; exit 1; }
step() { printf "\n\033[1m== %s ==\033[0m\n" "$1"; }
info() { printf "  %s\n" "$1"; }

TMPDIR_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_ROOT"' EXIT

############################################
# Phase 1: obtain JWT (mirrors smoke_test_phase1.sh)
############################################

step "Phase 1: GET /health"
body=$(curl -fsS "$BASE_URL/health")
info "$body"
[[ "$body" == *'"status"'*'"ok"'* ]] && pass "/health returns ok" || fail "/health did not return ok"

step "Phase 1: POST /auth/magic-link"
curl -fsS -X POST "$BASE_URL/auth/magic-link" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\"}" >/dev/null
pass "magic-link request accepted"
echo
echo "  Look at the server log for a line like:"
echo "    [ConsoleEmailSender] Magic link for $EMAIL: .../verify?token=<TOKEN>&email=..."
read -r -p "  Paste the raw token here: " TOKEN
[[ -n "$TOKEN" ]] || fail "no token provided"

step "Phase 1: GET /auth/verify"
verify=$(curl -fsS "$BASE_URL/auth/verify?token=$TOKEN&email=$EMAIL")
JWT=$(printf '%s' "$verify" | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
[[ -n "$JWT" ]] && pass "received JWT" || fail "no access_token in response"

AUTH_HEADER="Authorization: Bearer $JWT"
MATH_QUERY_BASE="subject=math&seed=41&grade=8&context=%E5%80%8B%E4%BA%BA&set_type=%E5%96%AE%E4%B8%80%E9%A1%8C&q_type=%E9%81%B8%E6%93%87%E9%A1%8C&math_thinking=%E5%BD%A2%E6%88%90&learning_content=A-7-7&learning_performance=s-IV-12&core_competency=%E6%95%B8-J-A2&content_type=%E7%B4%94%E6%96%87%E5%AD%97&skip_verify=true&count=1"

############################################
# Phase 2 helpers
############################################

# Stream the SSE response to a file and return when `event: done` is seen
# (or on stream close). Uses curl -N with --max-time as a safety net.
stream_sse() {
  local url="$1"
  local out="$2"
  curl -N -fsS --max-time 180 -H "$AUTH_HEADER" "$url" >"$out" || true
}

# Extract the `data:` payload following the first `event: <name>` line.
extract_event_data() {
  local file="$1"
  local name="$2"
  python3 - "$file" "$name" <<'PY'
import sys
path, name = sys.argv[1], sys.argv[2]
buf_event = None
data_lines = []
with open(path, encoding="utf-8") as f:
    for line in f:
        line = line.rstrip("\n")
        if line.startswith("event:"):
            if buf_event == name and data_lines:
                print("\n".join(data_lines))
                sys.exit(0)
            buf_event = line.split(":", 1)[1].strip()
            data_lines = []
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif line == "":
            if buf_event == name and data_lines:
                print("\n".join(data_lines))
                sys.exit(0)
            buf_event = None
            data_lines = []
if buf_event == name and data_lines:
    print("\n".join(data_lines))
PY
}

count_events() {
  local file="$1"
  local name="$2"
  grep -c "^event: ${name}$" "$file" || true
}

############################################
# Phase 2 checks
############################################

step "Phase 2: SSE basic stream (text_only, skip_verify=true)"
SSE_OUT="$TMPDIR_ROOT/sse_basic.log"
stream_sse "$BASE_URL/api/generate?$MATH_QUERY_BASE&style=text_only" "$SSE_OUT"

[[ -s "$SSE_OUT" ]] || fail "SSE stream produced no output"
pass "stream produced output ($(wc -l <"$SSE_OUT") lines)"

n_progress=$(count_events "$SSE_OUT" progress)
[[ "$n_progress" -ge 1 ]] && pass "progress events present ($n_progress)" \
  || fail "no progress events in stream"

n_result=$(count_events "$SSE_OUT" result)
[[ "$n_result" -ge 1 ]] && pass "result event present" \
  || fail "no result event in stream"

n_done=$(count_events "$SSE_OUT" done)
[[ "$n_done" -ge 1 ]] && pass "done event closes stream" \
  || fail "no done event in stream"

step "Phase 2: result payload is a valid ExamQuestion"
RESULT_JSON=$(extract_event_data "$SSE_OUT" result)
[[ -n "$RESULT_JSON" ]] || fail "could not extract result payload"
echo "$RESULT_JSON" | python3 -c '
import json, sys
obj = json.loads(sys.stdin.read())
for k in ("題目", "正確解題分析"):
    assert k in obj, f"missing field: {k}"
assert isinstance(obj["題目"], list) and obj["題目"], "題目 must be a non-empty list"
assert isinstance(obj["正確解題分析"], list) and obj["正確解題分析"], "正確解題分析 must be a non-empty list"
print("ok")
' >/dev/null && pass "result JSON has 題目 and 正確解題分析" \
  || fail "result payload failed schema check"

step "Phase 2: generation_log row written with status=completed"
if [[ -z "$DB_PATH" ]]; then
  info "DB_PATH empty, skipping DB check"
elif [[ ! -f "$DB_PATH" ]]; then
  info "DB file '$DB_PATH' not found, skipping (override with arg 3)"
else
  status=$(python3 - "$DB_PATH" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
row = conn.execute(
    "SELECT status FROM generation_log ORDER BY id DESC LIMIT 1"
).fetchone()
print(row[0] if row else "")
PY
)
  [[ "$status" == "completed" ]] && pass "latest generation_log.status = completed" \
    || fail "expected status=completed, got '$status'"
fi

step "Phase 2: two simultaneous requests are serialized (semaphore)"
A_OUT="$TMPDIR_ROOT/sse_a.log"
B_OUT="$TMPDIR_ROOT/sse_b.log"
stream_sse "$BASE_URL/api/generate?$MATH_QUERY_BASE&style=text_only" "$A_OUT" &
PID_A=$!
# small offset so the second request truly arrives while A holds the lock
sleep 0.5
stream_sse "$BASE_URL/api/generate?$MATH_QUERY_BASE&style=text_only" "$B_OUT" &
PID_B=$!
wait "$PID_A" "$PID_B"

for f in "$A_OUT" "$B_OUT"; do
  grep -q "^event: error$" "$f" && fail "concurrent request errored: $f"
  grep -q "^event: done$"  "$f" || fail "concurrent request missing done: $f"
  grep -q "^event: result$" "$f" || fail "concurrent request missing result: $f"
done
pass "both concurrent requests completed without error"

step "Phase 2: style=with_chart returns image_base64"
CHART_OUT="$TMPDIR_ROOT/sse_chart.log"
stream_sse "$BASE_URL/api/generate?$MATH_QUERY_BASE&style=with_chart" "$CHART_OUT"
grep -q "^event: result$" "$CHART_OUT" || fail "with_chart: no result event"
CHART_JSON=$(extract_event_data "$CHART_OUT" result)
echo "$CHART_JSON" | python3 -c '
import json, sys, base64
obj = json.loads(sys.stdin.read())
assert "image_base64" in obj, "image_base64 missing from result"
b = base64.b64decode(obj["image_base64"], validate=True)
assert b[:8] == b"\x89PNG\r\n\x1a\n", "image_base64 is not a PNG"
print("ok")
' >/dev/null && pass "with_chart result includes valid PNG image_base64" \
  || fail "with_chart result missing or invalid image_base64"

printf "\n\033[1;32mAll Phase 2 SSE generation checks passed.\033[0m\n"
