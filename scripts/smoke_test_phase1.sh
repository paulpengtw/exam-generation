#!/usr/bin/env bash
# Phase 1 end-to-end auth smoke test.
#
# Prereqs:
#   - Server running:  uvicorn server.app:create_app --factory --reload
#   - EMAIL_BACKEND=console (default) so the magic link is printed to the server's stdout.
#
# Usage:
#   scripts/smoke_test_phase1.sh [BASE_URL] [EMAIL]
#
# After /auth/magic-link returns, paste the raw token printed in the server log
# at the prompt; the script will then verify and call /auth/me.

set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000}"
EMAIL="${2:-test@example.com}"

pass() { printf "  \033[32mPASS\033[0m  %s\n" "$1"; }
fail() { printf "  \033[31mFAIL\033[0m  %s\n" "$1"; exit 1; }
step() { printf "\n\033[1m== %s ==\033[0m\n" "$1"; }

step "GET /health"
body=$(curl -fsS "$BASE_URL/health")
echo "  $body"
[[ "$body" == *'"status"'*'"ok"'* ]] && pass "/health returns ok" || fail "/health did not return ok"

step "GET /api/schemas"
schemas=$(curl -fsS "$BASE_URL/api/schemas")
[[ "$schemas" == *'學習階段'* && "$schemas" == *'grades'* ]] \
  && pass "/api/schemas returns question_schemas.json" \
  || fail "/api/schemas missing expected keys"

step "GET /auth/me without token"
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/auth/me")
[[ "$code" == "401" ]] && pass "unauthenticated /auth/me -> 401" || fail "expected 401, got $code"

step "POST /auth/magic-link"
resp=$(curl -fsS -X POST "$BASE_URL/auth/magic-link" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\"}")
echo "  $resp"
pass "magic-link request accepted"
echo
echo "  Look at the server log for a line like:"
echo "    [ConsoleEmailSender] Magic link for $EMAIL: .../auth/verify?token=<TOKEN>"
read -r -p "  Paste the raw token here: " TOKEN
[[ -n "$TOKEN" ]] || fail "no token provided"

step "GET /auth/verify"
verify=$(curl -fsS "$BASE_URL/auth/verify?token=$TOKEN&email=$EMAIL")
echo "  $verify"
JWT=$(printf '%s' "$verify" | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
[[ -n "$JWT" ]] && pass "received JWT" || fail "no access_token in response"

step "GET /auth/me with Bearer"
me=$(curl -fsS "$BASE_URL/auth/me" -H "Authorization: Bearer $JWT")
echo "  $me"
[[ "$me" == *"$EMAIL"* ]] && pass "/auth/me returns user info" || fail "/auth/me missing email"

printf "\n\033[1;32mAll Phase 1 auth checks passed.\033[0m\n"
