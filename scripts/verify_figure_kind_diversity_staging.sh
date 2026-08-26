#!/usr/bin/env bash
# Verify the original 社會領域 題組 image-shape against staging.
#
# The request deliberately asks for a 題幹 image and two 小題 images. The
# generated record is read back from /api/history so this checks persistence,
# not only the live SSE result.

set -uo pipefail

BASE_URL="${BASE_URL:-https://examgen-staging.cpeng.me}"
API_URL="${API_URL:-$BASE_URL}"
SMOKE_EMAIL="${SMOKE_EMAIL:-smoketest@smoke.local}"
SMOKE_AUTH_TOKEN="${SMOKE_AUTH_TOKEN:-}"
SEED="${SEED:-554}"
POLL_ATTEMPTS="${POLL_ATTEMPTS:-60}"
POLL_SECONDS="${POLL_SECONDS:-2}"
GEN_TIMEOUT="${GEN_TIMEOUT:-900}"
SCRIPT_DIR="$(dirname -- "${BASH_SOURCE[0]}")"

RESOLVE_TMP=$(mktemp)
RESOLVE_HDR=$(mktemp)
RESOLVED_PAYLOAD_TMP=$(mktemp)
RESOLVED_DRAWN_TMP=$(mktemp)
RESOLVED_QUERY_TMP=$(mktemp)
RESOLVED_FIELDS_TMP=$(mktemp)
GEN_TMP=$(mktemp)
GEN_HDR=$(mktemp)
RESULT_TMP=$(mktemp)
HISTORY_TMP=$(mktemp)
DETAIL_TMP=$(mktemp)
cleanup() {
  rm -f "$RESOLVE_TMP" "$RESOLVE_HDR" "$RESOLVED_PAYLOAD_TMP" \
    "$RESOLVED_DRAWN_TMP" "$RESOLVED_QUERY_TMP" "$RESOLVED_FIELDS_TMP" \
    "$GEN_TMP" "$GEN_HDR" "$RESULT_TMP" "$HISTORY_TMP" "$DETAIL_TMP"
}
trap cleanup EXIT

fail() {
  printf 'FAIL: %s\n' "$1"
  exit 1
}

parse_result_event() {
  python3 - "$1" "$2" <<'PY'
import json
import sys


source, destination = sys.argv[1:]
try:
    with open(source, encoding="utf-8") as fh:
        stream = fh.read()
except OSError as exc:
    raise SystemExit(f"could not read SSE stream: {exc}") from exc

# SSE permits CRLF, CR, or LF line endings. Normalize first so each blank line
# is a frame boundary, then apply the browser's data-field joining rule.
for frame in stream.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
    event_name = None
    data_lines = []
    for line in frame.split("\n"):
        if line.startswith("event:"):
            value = line[len("event:"):]
            event_name = value[1:] if value.startswith(" ") else value
        elif line.startswith("data:"):
            value = line[len("data:"):]
            data_lines.append(value[1:] if value.startswith(" ") else value)

    if event_name != "result":
        continue
    try:
        payload = json.loads("\n".join(data_lines))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"result event data is not valid JSON: {exc}") from exc
    try:
        with open(destination, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
    except OSError as exc:
        raise SystemExit(f"could not write result payload: {exc}") from exc
    raise SystemExit(0)

raise SystemExit("result event not found")
PY
}

if [[ "${1:-}" == '--selftest' ]]; then
  python3 - "$GEN_TMP" <<'PY'
import json
import re
import sys


def serialize_event(event):
    # Mirrors server/generate/routes.py:_serialize_event.
    data = event.get("data", "")
    if not isinstance(data, str):
        data = json.dumps(data, ensure_ascii=False)
    return {"event": event["event"], "data": data}


def encode_event(event, *, comment=None, event_id=None, retry=None):
    # Mirrors sse_starlette.sse.ServerSentEvent.encode() with its default CRLF.
    lines = []
    if comment is not None:
        for chunk in re.split(r"\r\n|\r|\n", str(comment)):
            lines.append(f": {chunk}\r\n")
    if event_id is not None:
        lines.append(f"id: {event_id}\r\n")
    lines.append(f"event: {event['event']}\r\n")
    if event["data"] is not None:
        for chunk in re.split(r"\r\n|\r|\n", str(event["data"])):
            lines.append(f"data: {chunk}\r\n")
    if retry is not None:
        lines.append(f"retry: {retry}\r\n")
    lines.append("\r\n")
    return "".join(lines)


result_payload = {
    "id": "selftest-question-554",
    "題目": ["第一行", "第二行"],
    "text": "A line\nB line",
}
result_json = json.dumps(result_payload, ensure_ascii=False, indent=2)
frames = [
    encode_event(serialize_event({"event": "started", "data": ""})),
    encode_event(
        serialize_event({
            "event": "llm_content",
            "data": {"purpose": "generator", "text": "chunk one\nchunk two"},
        }),
        event_id="llm-1",
    ),
    ": ping - 1\r\n\r\n",
    encode_event(
        serialize_event({"event": "result", "data": result_json}),
        event_id="result-1",
        retry=1000,
    ),
    encode_event(serialize_event({"event": "done", "data": ""})),
    ": ping - 2\r\n\r\n",
]
with open(sys.argv[1], "w", encoding="utf-8", newline="") as fh:
    fh.write("".join(frames))
PY
  if ! parse_result_event "$GEN_TMP" "$RESULT_TMP"; then
    fail 'self-test result parser did not recover the fixture'
  fi
  QUESTION_ID=$(python3 - "$RESULT_TMP" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    print(json.load(fh).get("id", ""))
PY
  )
  [[ "$QUESTION_ID" == 'selftest-question-554' ]] \
    || fail "self-test recovered unexpected question id: ${QUESTION_ID:-<empty>}"
  printf 'PASS: SSE result self-test recovered question id: %s\n' "$QUESTION_ID"
  exit 0
fi

printf 'BASE_URL=%s\n' "$BASE_URL"
printf 'API_URL=%s\n' "$API_URL"
printf 'Scenario: social_studies, 題幹 + two 小題 images, gpt_image, count=1, seed=%s\n' "$SEED"

JWT="$SMOKE_AUTH_TOKEN"
if [[ -z "$JWT" ]]; then
  printf 'SMOKE_AUTH_TOKEN unset; requesting a console magic link for %s\n' "$SMOKE_EMAIL"
  ML_CODE=$(curl -sS -o /dev/null -w '%{http_code}' \
    -X POST "$API_URL/auth/magic-link" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$SMOKE_EMAIL\"}" \
    --max-time 15 2>/dev/null || true)
  [[ "$ML_CODE" == '200' ]] || fail "POST /auth/magic-link returned HTTP ${ML_CODE:-<none>}"
  read -r -p 'Paste the raw magic-link token (empty to abort): ' MAGIC_TOKEN
  [[ -n "$MAGIC_TOKEN" ]] || fail 'no magic-link token supplied'
  VERIFY_RESP=$(curl -fsS --get "$API_URL/auth/verify" \
    --data-urlencode "token=$MAGIC_TOKEN" \
    --data-urlencode "email=$SMOKE_EMAIL" \
    --max-time 15 2>/dev/null || true)
  JWT=$(printf '%s' "$VERIFY_RESP" | python3 -c \
    'import json, sys; print(json.load(sys.stdin).get("access_token", ""))' \
    2>/dev/null || true)
  [[ -n "$JWT" ]] || fail 'magic-link verification did not return access_token'
fi

SUBQUESTION_CONFIGS='[{"content_type":"含圖片"},{"content_type":"含圖片"},{}]'
PARTIAL_PAYLOAD=$(python3 - "$SEED" "$SUBQUESTION_CONFIGS" <<'PY'
import json
import sys

seed = int(sys.argv[1])
subquestion_configs = json.loads(sys.argv[2])
payload = {
    "subject": "social_studies",
    "grade": 8,
    "content_type": "含圖片",
    "image_generation_mode": "gpt_image",
    "sub_question_count": 3,
    "subquestion_configs": subquestion_configs,
    "count": 1,
    "seed": seed,
    "skip_verify": True,
    "redraws": {},
}
print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
PY
) || fail 'could not build the partial resolve payload'

curl -sS -D "$RESOLVE_HDR" -o "$RESOLVE_TMP" \
  --max-time 30 \
  -X POST "$API_URL/api/generate/resolve" \
  -H "Authorization: Bearer $JWT" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json' \
  -d "$PARTIAL_PAYLOAD" \
  2>/dev/null || true

RESOLVE_STATUS=$(awk 'NR == 1 {print $2; exit}' "$RESOLVE_HDR" 2>/dev/null || true)
if [[ "$RESOLVE_STATUS" != '200' ]]; then
  printf 'POST /api/generate/resolve returned HTTP %s\n' "${RESOLVE_STATUS:-<none>}"
  printf 'Resolve response body:\n'
  cat "$RESOLVE_TMP"
  printf '\n'
  fail "POST /api/generate/resolve returned HTTP ${RESOLVE_STATUS:-<none>}"
fi

if ! python3 - "$RESOLVE_TMP" "$RESOLVED_PAYLOAD_TMP" "$RESOLVED_DRAWN_TMP" \
  "$RESOLVED_QUERY_TMP" "$RESOLVED_FIELDS_TMP" <<'PY'
import json
import sys


response_path, payload_path, drawn_path, query_path, fields_path = sys.argv[1:]
try:
    response = json.load(open(response_path, encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"resolve response is not valid JSON: {exc}") from exc

payload = response.get("payload")
drawn = response.get("drawn")
if not isinstance(payload, dict):
    raise SystemExit("resolve response payload is not an object")
if not isinstance(drawn, list) or any(not isinstance(path, str) for path in drawn):
    raise SystemExit("resolve response drawn is not a list of strings")


def compact_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def scalar_text(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return compact_json(value)
    return str(value)


def encoded_json_field(name, value):
    if name == "per_question_params" and isinstance(value, list):
        rows = []
        for row in value:
            if isinstance(row, dict):
                row = dict(row)
                configs = row.get("subquestion_configs")
                if isinstance(configs, (list, dict)):
                    row["subquestion_configs"] = compact_json(configs)
            rows.append(row)
        value = rows
    return value if isinstance(value, str) else compact_json(value)


# Keep the web fields in step with web/src/hooks/useGenerate.ts:buildQueryString;
# the two route-only scalar fields are included when a completed payload carries
# them. Ordinary arrays use repeated query keys; the two JSON-string route fields
# are encoded as one compact JSON value.
field_order = [
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

# The browser carries resolver provenance into the final generation request.
payload_for_query = dict(payload)
prior_drawn = payload_for_query.get("drawn")
if isinstance(prior_drawn, list):
    payload_for_query["drawn"] = list(dict.fromkeys([*prior_drawn, *drawn]))
else:
    payload_for_query["drawn"] = drawn

query_pairs = []
fields_used = []


def add_pair(name, value):
    if value is None:
        return
    query_pairs.append(f"{name}={value}")
    if name not in fields_used:
        fields_used.append(name)


for kind, name in field_order:
    if name not in payload_for_query:
        continue
    value = payload_for_query[name]
    if value is None:
        continue
    if kind == "repeated":
        values = value if isinstance(value, list) else [value]
        for item in values:
            add_pair(name, scalar_text(item))
    elif kind == "json":
        add_pair(name, encoded_json_field(name, value))
    else:
        add_pair(name, scalar_text(value))

with open(payload_path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
with open(drawn_path, "w", encoding="utf-8") as fh:
    json.dump(drawn, fh, ensure_ascii=False, separators=(",", ":"))
with open(query_path, "wb") as fh:
    for pair in query_pairs:
        fh.write(pair.encode("utf-8") + b"\0")
with open(fields_path, "w", encoding="utf-8") as fh:
    fh.write("\n".join(fields_used))
PY
then
  fail 'resolve response did not contain a usable payload and drawn list'
fi

printf 'Resolved payload: '
cat "$RESOLVED_PAYLOAD_TMP"
printf '\n'
printf 'Drawn: '
cat "$RESOLVED_DRAWN_TMP"
printf '\n'
printf 'GET query fields: '
if [[ -s "$RESOLVED_FIELDS_TMP" ]]; then
  tr '\n' ' ' <"$RESOLVED_FIELDS_TMP"
  printf '\n'
else
  printf '<none>\n'
fi

QUERY_ARGS=()
while IFS= read -r -d '' QUERY_ARG; do
  QUERY_ARGS+=(--data-urlencode "$QUERY_ARG")
done <"$RESOLVED_QUERY_TMP"

GEN_STARTED=$SECONDS
curl -N -sS -D "$GEN_HDR" -o "$GEN_TMP" \
  --max-time "$GEN_TIMEOUT" \
  -H "Authorization: Bearer $JWT" \
  -H 'Accept: text/event-stream' \
  --get \
  "${QUERY_ARGS[@]}" \
  "$API_URL/api/generate" \
  2>/dev/null || true
GEN_ELAPSED=$((SECONDS - GEN_STARTED))

HTTP_STATUS=$(awk 'NR == 1 {print $2; exit}' "$GEN_HDR" 2>/dev/null || true)
if ! parse_result_event "$GEN_TMP" "$RESULT_TMP"; then
  printf 'Generation HTTP status: %s\n' "${HTTP_STATUS:-<none>}"
  printf 'SSE event counts:\n'
  EVENT_COUNTS=$(awk '
    /^event: / {
      name = $0
      sub(/^event: /, "", name)
      sub(/\r$/, "", name)
      counts[name]++
    }
    END {
      for (name in counts) printf "%s\t%d\n", name, counts[name]
    }
  ' "$GEN_TMP" 2>/dev/null | sort)
  if [[ -n "$EVENT_COUNTS" ]]; then
    while IFS=$'\t' read -r event_name event_count; do
      [[ -n "$event_name" ]] || continue
      printf '  event: %s (%s)\n' "$event_name" "$event_count"
    done <<<"$EVENT_COUNTS"
  else
    printf '  <none>\n'
  fi
  if awk '
    {
      line = $0
      sub(/\r$/, "", line)
      if (line == "event: error") found = 1
    }
    END { exit found ? 0 : 1 }
  ' "$GEN_TMP"; then
    printf 'First event: error (verbatim):\n'
    python3 - "$GEN_TMP" <<'PY'
import sys

with open(sys.argv[1], encoding="utf-8", errors="replace", newline="") as fh:
    lines = fh.readlines()
for index, line in enumerate(lines):
    if line.rstrip("\r\n") != "event: error":
        continue
    end = index + 1
    while end < len(lines):
        if lines[end].rstrip("\r\n") == "":
            end += 1
            break
        end += 1
    for frame_line in lines[index:end]:
        output = frame_line.rstrip("\r\n")
        if output.startswith("data:"):
            output = output[:200]
        sys.stdout.write(output + "\n")
    break
PY
    printf '\n'
  else
    printf 'Last 20 lines of stream (verbatim):\n'
    python3 - "$GEN_TMP" <<'PY'
import sys

with open(sys.argv[1], encoding="utf-8", errors="replace", newline="") as fh:
    lines = fh.readlines()
for line in lines[-20:]:
    output = line.rstrip("\r\n")
    if output.startswith("data:"):
        output = output[:200]
    sys.stdout.write(output + "\n")
PY
    printf '\n'
  fi
  printf 'Generation elapsed: %ss\n' "$GEN_ELAPSED"
  fail 'generation stream contained no result event'
fi

[[ "$HTTP_STATUS" == '200' ]] || fail "GET /api/generate returned HTTP ${HTTP_STATUS:-<none>}"
printf 'Generation elapsed: %ss\n' "$GEN_ELAPSED"

[[ -s "$RESULT_TMP" ]] || fail 'generation stream contained no result event'

QUESTION_ID=$(python3 - "$RESULT_TMP" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(payload.get("id", ""))
PY
)
[[ -n "$QUESTION_ID" ]] || fail 'result event did not contain a question id'

RECORD_ID=''
for ((attempt = 1; attempt <= POLL_ATTEMPTS; attempt++)); do
  curl -fsS --get "$API_URL/api/history" \
    -H "Authorization: Bearer $JWT" \
    --data-urlencode 'subject=social_studies' \
    --data-urlencode 'limit=20' \
    --max-time 15 -o "$HISTORY_TMP" 2>/dev/null || true
  RECORD_ID=$(python3 - "$HISTORY_TMP" "$QUESTION_ID" <<'PY'
import json
import sys

try:
    items = json.load(open(sys.argv[1], encoding="utf-8")).get("items", [])
except (OSError, json.JSONDecodeError):
    items = []
for item in items:
    if item.get("question_id") == sys.argv[2] and item.get("status") == "completed":
        print(item.get("id", ""))
        break
PY
  )
  [[ -n "$RECORD_ID" ]] && break
  sleep "$POLL_SECONDS"
done
[[ -n "$RECORD_ID" ]] || fail "completed history record for $QUESTION_ID did not appear"
printf 'PASS: completed record found: %s\n' "$RECORD_ID"

curl -fsS "$API_URL/api/history/$RECORD_ID" \
  -H "Authorization: Bearer $JWT" \
  --max-time 30 -o "$DETAIL_TMP" 2>/dev/null \
  || fail "GET /api/history/$RECORD_ID failed"

python3 - "$DETAIL_TMP" "$SCRIPT_DIR/.." <<'PY'
import json
import sys
from pathlib import Path

detail = json.load(open(sys.argv[1], encoding="utf-8"))
question = detail.get("question_json") or {}
trail = detail.get("figure_policy_trail")
vocabulary_path = Path(sys.argv[2]) / "data" / "social_studies" / "figure_kinds.json"
try:
    vocabulary = json.loads(vocabulary_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    vocabulary = {}
canonical = {
    value.casefold(): value
    for value in vocabulary.get("canonical", [])
    if isinstance(value, str) and value.strip()
}
aliases = {}
for canonical_label, values in vocabulary.get("aliases", {}).items():
    target = canonical.get(str(canonical_label).strip().casefold())
    if target is None:
        continue
    for value in values if isinstance(values, list) else []:
        if isinstance(value, str) and value.strip():
            aliases[value.strip().casefold()] = target


def effective_kind(spec):
    if not isinstance(spec, dict):
        return ""
    value = spec.get("figure_kind")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if spec.get("render_mode") == "chart":
        value = spec.get("chart_type")
        if isinstance(value, str):
            return value.strip()
    return ""


def normalize(value):
    key = value.strip().casefold()
    return canonical.get(key, aliases.get(key, key))


figures = []
if isinstance(question.get("chart_spec"), dict):
    figures.append(("題幹", question["chart_spec"]))
for position, subquestion in enumerate(question.get("subquestions") or [], start=1):
    if isinstance(subquestion, dict) and isinstance(subquestion.get("chart_spec"), dict):
        label = f"小題 {subquestion.get('序號', position)}"
        figures.append((label, subquestion["chart_spec"]))

normalized = []
for label, spec in figures:
    kind = effective_kind(spec)
    normalized_kind = normalize(kind) if kind else ""
    normalized.append(normalized_kind)
    print(f"{label}: 圖像種類={kind or '<empty>'} (normalized={normalized_kind or '<empty>'})")

distinct = bool(figures) and all(normalized) and len(normalized) == len(set(normalized))
print(f"{'PASS' if distinct else 'FAIL'}: pairwise distinctness")

if not isinstance(trail, list) or not trail:
    print("FAIL: figure-policy trail is empty or missing")
    raise SystemExit(1)
print(f"Figure-policy trail: {len(trail)} entries")
for entry in trail:
    if not isinstance(entry, dict):
        print(f"  {entry!r}")
        continue
    label = entry.get("label") or entry.get("target") or (
        f"{entry.get('left', '?')} -> {entry.get('right', '?')}"
    )
    reason = entry.get("message") or entry.get("error") or entry.get("effective_figure_kind", "")
    print(f"  {entry.get('kind', '?')}: {label}; reason={reason or '<none>'}")

raise SystemExit(0 if distinct else 1)
PY
