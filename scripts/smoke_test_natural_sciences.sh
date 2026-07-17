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
# Checks are appended by later tasks
###############################################################################
