#!/usr/bin/env bash
# smoke_test_natural_sciences.sh — Staging smoke coverage for the
# natural-sciences generation pipeline (GitHub issue #94).
#
# Layers probed:
#   1. FRONTEND — GET $BASE_URL/generate/natural_sciences returns 200 with
#      the SPA shell (any HTML that mentions the app is enough).
#   2. API      — GET $API_URL/api/schemas?subject=natural_sciences returns
#      200 and the JSON body carries the six PISA dimensions (情境,
#      情境子類別, 科學能力 with 6 entries, 題型 with 3 PISA values, and
#      non-empty 學習內容 / 學習表現 pools).
#   3. PROVIDER — authenticated GET $API_URL/api/generate?subject=natural_
#      sciences&grade=8&skip_verify=true&count=1 either streams SSE with
#      progress/result/done events OR returns a *controlled* provider error
#      (non-500, or 5xx with a clear JSON detail).  A hung stream or an
#      empty 500 body fails this layer.
#
# Every failure line is prefixed with FRONTEND / API / PROVIDER so a red
# check identifies the failing layer.
#
# Env vars (all optional):
#   BASE_URL          default https://examgen-staging.cpeng.me
#   API_URL           default $BASE_URL   (staging co-locates them; for
#                                          split local runs point this at
#                                          http://localhost:8000)
#   SMOKE_AUTH_TOKEN  bearer JWT for the generate check.  When unset the
#                     script runs the magic-link console flow against
#                     $API_URL/auth/magic-link and expects the backend to
#                     log the link (EMAIL_BACKEND=console).
#   SMOKE_EMAIL       default smoketest@smoke.local
#
# Usage:
#   BASE_URL=https://examgen-staging.cpeng.me \
#   SMOKE_AUTH_TOKEN=eyJhbGciOi... \
#   bash scripts/smoke_test_natural_sciences.sh
#
# Exit codes: 0 on green, 1 on any FAIL.

set -uo pipefail

###############################################################################
# Colours + counters
###############################################################################

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

PASS_COUNT=0
FAIL_COUNT=0

pass() {
  printf "  ${GREEN}PASS${RESET}  %s\n" "$1"
  PASS_COUNT=$(( PASS_COUNT + 1 ))
}

fail() {
  # $1 = layer label (FRONTEND / API / PROVIDER)
  # $2 = message
  printf "  ${RED}FAIL${RESET}  [%s] %s\n" "$1" "$2"
  FAIL_COUNT=$(( FAIL_COUNT + 1 ))
}

step() {
  printf "\n${BOLD}== %s ==${RESET}\n" "$1"
}

info() {
  printf "  ${YELLOW}INFO${RESET}  %s\n" "$1"
}

###############################################################################
# Config from env
###############################################################################

BASE_URL="${BASE_URL:-https://examgen-staging.cpeng.me}"
API_URL="${API_URL:-$BASE_URL}"
SMOKE_EMAIL="${SMOKE_EMAIL:-smoketest@smoke.local}"
SMOKE_AUTH_TOKEN="${SMOKE_AUTH_TOKEN:-}"

info "BASE_URL = $BASE_URL"
info "API_URL  = $API_URL"

###############################################################################
# Utility: wait for an HTTP endpoint to return the expected status code
###############################################################################

# Reserved for future readiness-wait steps (not used by the current checks).
wait_for_http() {
  local url="$1"
  local expected_code="${2:-200}"
  local max_attempts="${3:-30}"
  local attempt=0
  local code
  while (( attempt < max_attempts )); do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || true)
    if [[ "$code" == "$expected_code" ]]; then
      return 0
    fi
    attempt=$(( attempt + 1 ))
    sleep 2
  done
  return 1
}

###############################################################################
# Final summary trap
###############################################################################

summary() {
  echo ""
  printf "${BOLD}Results: ${GREEN}%d passed${RESET}  ${RED}%d failed${RESET}\n" \
    "$PASS_COUNT" "$FAIL_COUNT"
  if (( FAIL_COUNT > 0 )); then
    printf "${RED}%s${RESET}\n" "NS SMOKE TEST FAILED"
    exit 1
  fi
  printf "${GREEN}%s${RESET}\n" "NS SMOKE TEST PASSED"
  exit 0
}
trap summary EXIT

###############################################################################
# CHECK 1: FRONTEND — /generate/natural_sciences returns 200 with SPA shell
###############################################################################

step "CHECK 1 [FRONTEND]: GET $BASE_URL/generate/natural_sciences"

FRONT_TMP=$(mktemp)
FRONT_CODE=$(curl -s -o "$FRONT_TMP" -w "%{http_code}" --max-time 10 \
  "$BASE_URL/generate/natural_sciences" 2>/dev/null || true)

if [[ "$FRONT_CODE" != "200" ]]; then
  fail "FRONTEND" "GET /generate/natural_sciences returned HTTP $FRONT_CODE (expected 200)"
elif ! grep -qi '<div id="root"\|<title' "$FRONT_TMP"; then
  fail "FRONTEND" "GET /generate/natural_sciences returned 200 but body does not look like the SPA shell (missing <div id=\"root\"> or <title>)"
  info "First 200 bytes of response:"
  head -c 200 "$FRONT_TMP" || true
  echo ""
else
  pass "FRONTEND: /generate/natural_sciences serves the SPA shell"
fi

rm -f "$FRONT_TMP"

###############################################################################
# CHECK 2: API — /api/schemas?subject=natural_sciences carries PISA dimensions
###############################################################################

step "CHECK 2 [API]: GET $API_URL/api/schemas?subject=natural_sciences"

SCHEMA_TMP=$(mktemp)
SCHEMA_CODE=$(curl -s -o "$SCHEMA_TMP" -w "%{http_code}" --max-time 15 \
  "$API_URL/api/schemas?subject=natural_sciences" 2>/dev/null || true)

if [[ "$SCHEMA_CODE" != "200" ]]; then
  fail "API" "GET /api/schemas?subject=natural_sciences returned HTTP $SCHEMA_CODE (expected 200)"
  info "First 200 bytes of response:"
  head -c 200 "$SCHEMA_TMP" || true
  echo ""
else
  SCHEMA_REPORT=$(python3 - "$SCHEMA_TMP" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)

def values(cat):
    entries = data.get(cat) or []
    out = []
    for entry in entries:
        if isinstance(entry, dict) and "value" in entry:
            out.append(entry["value"])
        elif isinstance(entry, str):
            out.append(entry)
    return out

errors = []

context_vals = values("情境")
for expected in ("Personal", "Local and national", "Global"):
    if expected not in context_vals:
        errors.append(f"情境 missing '{expected}' (got {context_vals!r})")

subctx_vals = values("情境子類別")
if not subctx_vals:
    errors.append("情境子類別 is empty")

cap_vals = values("科學能力")
if len(cap_vals) != 6:
    errors.append(f"科學能力 has {len(cap_vals)} entries, expected 6")
required_cap_prefixes = ("能力一", "能力二", "能力三",
                         "環境能力一", "環境能力二", "環境能力三")
for prefix in required_cap_prefixes:
    if not any(v.startswith(prefix) for v in cap_vals):
        errors.append(f"科學能力 missing entry starting with '{prefix}' (got {cap_vals!r})")

qtype_vals = values("題型")
for expected in ("Simple multiple-choice",
                 "Complex multiple-choice",
                 "Constructed response"):
    if expected not in qtype_vals:
        errors.append(f"題型 missing '{expected}' (got {qtype_vals!r})")

lc_vals = values("學習內容")
if not lc_vals:
    errors.append("學習內容 pool is empty")

lp_vals = values("學習表現")
if not lp_vals:
    errors.append("學習表現 pool is empty")

if errors:
    print("FAIL")
    for e in errors:
        print(e)
else:
    print("OK")
    print(f"情境={len(context_vals)} 情境子類別={len(subctx_vals)} "
          f"科學能力={len(cap_vals)} 題型={len(qtype_vals)} "
          f"學習內容={len(lc_vals)} 學習表現={len(lp_vals)}")
PY
)
  SCHEMA_STATUS=$(echo "$SCHEMA_REPORT" | head -1)
  if [[ "$SCHEMA_STATUS" == "OK" ]]; then
    pass "API: /api/schemas returns all six PISA dimensions"
    info "$(echo "$SCHEMA_REPORT" | tail -1)"
  else
    fail "API" "/api/schemas payload is missing PISA fields:"
    echo "$SCHEMA_REPORT" | tail -n +2 | while IFS= read -r line; do
      info "  $line"
    done
  fi
fi

rm -f "$SCHEMA_TMP"

###############################################################################
# CHECK 3: PROVIDER — authenticated /api/generate?subject=natural_sciences
#                     reaches the natural-sciences generator
###############################################################################

step "CHECK 3 [PROVIDER]: authenticated GET /api/generate?subject=natural_sciences"

JWT="$SMOKE_AUTH_TOKEN"

if [[ -z "$JWT" ]]; then
  info "SMOKE_AUTH_TOKEN unset — running magic-link console flow against $API_URL"

  ML_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$API_URL/auth/magic-link" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$SMOKE_EMAIL\"}" \
    --max-time 10 2>/dev/null || true)
  if [[ "$ML_CODE" != "200" ]]; then
    fail "API" "POST /auth/magic-link returned HTTP $ML_CODE (expected 200)"
    info "PROVIDER check skipped — no JWT obtained"
  else
    info "magic-link accepted for $SMOKE_EMAIL"
    echo "  Look at the backend log for a line like:"
    echo "    [ConsoleEmailSender] Magic link for $SMOKE_EMAIL: .../verify?token=<TOKEN>&email=..."
    read -r -p "  Paste the raw token here (empty to skip PROVIDER check): " MAGIC_TOKEN
    if [[ -n "$MAGIC_TOKEN" ]]; then
      VERIFY_RESP=$(curl -fsS \
        "$API_URL/auth/verify?token=${MAGIC_TOKEN}&email=${SMOKE_EMAIL}" \
        --max-time 10 2>/dev/null || true)
      JWT=$(printf '%s' "$VERIFY_RESP" | python3 -c \
        'import json,sys; print(json.load(sys.stdin).get("access_token",""))' \
        2>/dev/null || true)
      if [[ -z "$JWT" ]]; then
        fail "API" "GET /auth/verify did not return an access_token (response: $VERIFY_RESP)"
      fi
    else
      info "no token supplied — skipping PROVIDER check"
    fi
  fi
fi

if [[ -n "$JWT" ]]; then
  GEN_URL="$API_URL/api/generate?subject=natural_sciences&grade=8&skip_verify=true&count=1"
  GEN_TMP=$(mktemp)
  GEN_HDR=$(mktemp)

  # -N: no buffering (SSE);  -D: dump headers so we can read the status line
  # separately from the streamed body.
  curl -N -s -o "$GEN_TMP" -D "$GEN_HDR" \
    --max-time 90 \
    -H "Authorization: Bearer $JWT" \
    -H "Accept: text/event-stream" \
    "$GEN_URL" 2>/dev/null || true

  GEN_STATUS=$(awk 'NR==1{print $2}' "$GEN_HDR" 2>/dev/null || true)
  info "HTTP status = ${GEN_STATUS:-<none>}, body = $(wc -l <"$GEN_TMP") lines"

  HAS_RESULT=false
  HAS_DONE=false
  HAS_ERROR=false
  grep -q "^event: result$" "$GEN_TMP" && HAS_RESULT=true
  grep -q "^event: done$"   "$GEN_TMP" && HAS_DONE=true
  grep -q "^event: error$"  "$GEN_TMP" && HAS_ERROR=true

  if $HAS_RESULT && $HAS_DONE; then
    pass "PROVIDER: /api/generate streamed result + done for subject=natural_sciences"
  elif $HAS_ERROR; then
    # Controlled provider error — soft pass.  The stream reached the generator
    # and the generator surfaced a structured error (LLM key missing, provider
    # rate-limited, etc.).  Print the error detail for the operator.
    ERR_LINE=$(grep -A1 "^event: error$" "$GEN_TMP" | grep "^data:" | head -1 || true)
    pass "PROVIDER: /api/generate returned a controlled error (soft-pass)"
    info "error data: ${ERR_LINE#data:}"
  elif [[ "$GEN_STATUS" == "429" || "$GEN_STATUS" == "401" || "$GEN_STATUS" == "403" ]]; then
    fail "API" "/api/generate returned HTTP $GEN_STATUS — auth or rate-limit problem, not a provider issue"
  elif [[ -z "$GEN_STATUS" || "$GEN_STATUS" == "000" ]]; then
    fail "PROVIDER" "/api/generate produced no HTTP response (network / timeout)"
  elif [[ "$GEN_STATUS" == "5"* ]]; then
    if [[ -s "$GEN_TMP" ]] && python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$GEN_TMP" 2>/dev/null; then
      pass "PROVIDER: /api/generate returned HTTP $GEN_STATUS with structured JSON detail (soft-pass)"
      info "body: $(head -c 200 "$GEN_TMP")"
    else
      fail "PROVIDER" "/api/generate returned HTTP $GEN_STATUS with an empty or non-JSON body"
      info "body: $(head -c 200 "$GEN_TMP")"
    fi
  else
    fail "PROVIDER" "/api/generate returned HTTP $GEN_STATUS but no SSE result/done event"
    info "body head: $(head -c 200 "$GEN_TMP")"
  fi

  rm -f "$GEN_TMP" "$GEN_HDR"
fi

###############################################################################
# Checks are appended by later tasks
###############################################################################
