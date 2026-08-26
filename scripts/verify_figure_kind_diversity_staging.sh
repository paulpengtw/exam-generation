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

GEN_TMP=$(mktemp)
GEN_HDR=$(mktemp)
RESULT_TMP=$(mktemp)
HISTORY_TMP=$(mktemp)
DETAIL_TMP=$(mktemp)
cleanup() {
  rm -f "$GEN_TMP" "$GEN_HDR" "$RESULT_TMP" "$HISTORY_TMP" "$DETAIL_TMP"
}
trap cleanup EXIT

fail() {
  printf 'FAIL: %s\n' "$1"
  exit 1
}

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
curl -N -sS -D "$GEN_HDR" -o "$GEN_TMP" \
  --max-time "$GEN_TIMEOUT" \
  -H "Authorization: Bearer $JWT" \
  -H 'Accept: text/event-stream' \
  --get "$API_URL/api/generate" \
  --data-urlencode 'subject=social_studies' \
  --data-urlencode 'grade=8' \
  --data-urlencode 'content_type=含圖片' \
  --data-urlencode 'image_generation_mode=gpt_image' \
  --data-urlencode 'sub_question_count=3' \
  --data-urlencode "subquestion_configs=$SUBQUESTION_CONFIGS" \
  --data-urlencode 'count=1' \
  --data-urlencode "seed=$SEED" \
  --data-urlencode 'skip_verify=true' \
  2>/dev/null || true

HTTP_STATUS=$(awk 'NR == 1 {print $2; exit}' "$GEN_HDR" 2>/dev/null || true)
[[ "$HTTP_STATUS" == '200' ]] || fail "GET /api/generate returned HTTP ${HTTP_STATUS:-<none>}"

python3 - "$GEN_TMP" "$RESULT_TMP" <<'PY'
import json
import sys

source, destination = sys.argv[1:]
lines = open(source, encoding="utf-8").read().splitlines()
for index, line in enumerate(lines):
    if line.strip() != "event: result":
        continue
    for data_line in lines[index + 1:]:
        if data_line.startswith("data: "):
            payload = json.loads(data_line[6:])
            with open(destination, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            raise SystemExit(0)
raise SystemExit("result event not found")
PY
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
