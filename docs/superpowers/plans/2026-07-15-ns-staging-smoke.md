# Natural-Sciences Staging Smoke Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `scripts/smoke_test_natural_sciences.sh` — a shellcheck-clean, env-driven smoke test that exercises the three natural-sciences layers (frontend SPA route, `/api/schemas?subject=natural_sciences`, authenticated `/api/generate?subject=natural_sciences`) so regressions in NS routing, schema wiring, or generation reach-through fail loudly with a clear `FRONTEND` / `API` / `PROVIDER` layer label (GitHub issue #94).

**Architecture:** Pure Bash + `curl` + `python3` (for JSON assertions). No new Python modules. Mirrors the conventions in `scripts/smoke_test.sh`, `scripts/smoke_test_phase1.sh`, and `scripts/smoke_test_phase2.sh` (ANSI-colored `pass` / `fail` / `step` / `info` helpers, `PASS_COUNT`/`FAIL_COUNT`, non-zero exit when any check fails). Auth uses the magic-link console flow already exercised by `scripts/smoke_test_phase1.sh`, but is bypassed when `SMOKE_AUTH_TOKEN` is supplied (which is the expected staging-CI path). Defaults target `https://examgen-staging.cpeng.me`; every URL is env-overridable so local runs work.

**Tech Stack:** Bash 4+, `curl`, `python3` (json + sys — stdlib only), `shellcheck` (verification only — the container currently ships without shellcheck, so `shellcheck` steps are best-effort documented; the plan still enforces the shellcheck-clean requirement via the online CI check).

**Spec:** `docs/superpowers/specs/2026-07-15-ns-staging-smoke-design.md`

## Global Constraints

- Single new file: `scripts/smoke_test_natural_sciences.sh`. No changes to Python source, server routes, or web code.
- `set -uo pipefail` — matches `scripts/smoke_test.sh` (no `-e`, so individual checks can fail without aborting the script; the exit code is driven by `FAIL_COUNT`).
- Env-driven configuration, no committed secrets:
  - `BASE_URL` default `https://examgen-staging.cpeng.me` (frontend SPA + proxied API origin).
  - `API_URL` default `${BASE_URL}` (staging co-locates them; local runs can point this at `http://localhost:8000`).
  - `SMOKE_AUTH_TOKEN` optional — when set, used as `Authorization: Bearer <token>` for the generation check; when unset, the script executes the magic-link console flow (`SMOKE_EMAIL` default `smoketest@smoke.local`).
- **Every failure message starts with a layer prefix — `FRONTEND` / `API` / `PROVIDER` — so the failing layer is unambiguous.** Layer assignment:
  - `FRONTEND` — HTML shell probes (`GET /generate/natural_sciences`).
  - `API` — backend JSON endpoints (`/api/schemas`, `/auth/magic-link`, `/auth/verify`, `/auth/me`, non-controlled `/api/generate` HTTP failures).
  - `PROVIDER` — controlled `/api/generate` provider/configuration errors (SSE `event: error` with clear detail, or HTTP 4xx/5xx from the generate handler that is NOT 500-with-empty-body). Accepted as a *soft-pass* in this smoke test — LLM-provider hiccups must not fail the staging gate.
- Uses the existing `/api/generate` `skip_verify=true&count=1` shortcut (there is no `dry_run` query param on the endpoint — confirmed by `server/generate/routes.py:53` and `server/generate/models.py:26`).
- Schema-API assertions on `GET /api/schemas?subject=natural_sciences` must verify **all six PISA dimensions** the spec lists:
  1. `情境` contains `Personal`, `Local and national`, `Global` (three values; CSV row 2–4).
  2. `情境子類別` is a non-empty array.
  3. `科學能力` is a length-6 array containing all three ability codes plus all three 環境 codes (CSV row 62–67).
  4. `題型` contains the three PISA values `Simple multiple-choice`, `Complex multiple-choice`, `Constructed response` (CSV row 59–61).
  5. `學習內容` is a non-empty array.
  6. `學習表現` is a non-empty array.
- Script must be `shellcheck`-clean (no warnings, no `# shellcheck disable=…` unless justified inline).
- Script must be `chmod +x`.
- Exit codes: `0` when every check passes (including PROVIDER soft-passes), `1` when any `FAIL` was emitted.
- Working directory for all shell commands unless explicitly stated: `/workspace/exam-generation`.

---

### Task 1: Script skeleton — env-driven config, layer-prefixed helpers, exit trap

**Files:**
- Create: `scripts/smoke_test_natural_sciences.sh`

**Interfaces:**
- Consumes: env vars `BASE_URL`, `API_URL`, `SMOKE_AUTH_TOKEN`, `SMOKE_EMAIL`.
- Produces: helpers used by every later task — `pass "<msg>"`, `fail "<LAYER>" "<msg>"`, `step "<title>"`, `info "<msg>"`, `wait_for_http URL CODE`, and global counters `PASS_COUNT` / `FAIL_COUNT`.

- [ ] **Step 1: Create the initial script file**

Create `scripts/smoke_test_natural_sciences.sh` with the following exact contents:

```bash
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
    printf "${RED}NS SMOKE TEST FAILED${RESET}\n"
    exit 1
  fi
  printf "${GREEN}NS SMOKE TEST PASSED${RESET}\n"
  exit 0
}
trap summary EXIT

###############################################################################
# Checks are appended by later tasks
###############################################################################
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x /workspace/exam-generation/scripts/smoke_test_natural_sciences.sh
```

- [ ] **Step 3: Verify it runs cleanly with no checks yet**

Run: `bash /workspace/exam-generation/scripts/smoke_test_natural_sciences.sh`

Expected output ends with `NS SMOKE TEST PASSED` and exit code `0` (0 passed / 0 failed — the trap succeeds because `FAIL_COUNT` is still `0`).

- [ ] **Step 4: Verify shellcheck-clean (best-effort — shellcheck may be absent in this container; run the online copy if local is missing)**

Run: `command -v shellcheck && shellcheck /workspace/exam-generation/scripts/smoke_test_natural_sciences.sh || echo "shellcheck not installed locally — must pass on CI/host with shellcheck available"`

Expected: either exits 0 with no output (clean), or prints the "not installed" hint. If shellcheck IS present and reports warnings, fix them before committing.

- [ ] **Step 5: Commit**

```bash
cd /workspace/exam-generation
git add scripts/smoke_test_natural_sciences.sh
git commit -m "chore(smoke): add natural-sciences smoke-test skeleton (#94)"
```

---

### Task 2: FRONTEND layer — SPA route probe

**Files:**
- Modify: `scripts/smoke_test_natural_sciences.sh` (append the CHECK 1 block after the "Checks are appended by later tasks" marker)

**Interfaces:**
- Consumes: `BASE_URL`, `pass`, `fail`, `step`, `info` from Task 1.
- Produces: after this task the script performs one HTTP probe and prints either a green PASS or `FAIL [FRONTEND] …`.

- [ ] **Step 1: Add the CHECK 1 block**

Append to `scripts/smoke_test_natural_sciences.sh` (replace the trailing marker comment `# Checks are appended by later tasks` with this block plus a fresh marker):

```bash
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
# Checks are appended by later tasks
###############################################################################
```

- [ ] **Step 2: Verify the check passes when the URL is reachable (happy-path smoke)**

Run: `BASE_URL=https://examgen-staging.cpeng.me bash /workspace/exam-generation/scripts/smoke_test_natural_sciences.sh` (or any known-good deployment).

Expected: `PASS  FRONTEND: /generate/natural_sciences serves the SPA shell` and `NS SMOKE TEST PASSED`.

If staging is unreachable from the dev container, run against a local `npm run dev` instead: `BASE_URL=http://localhost:5173 bash scripts/smoke_test_natural_sciences.sh` and expect the same PASS.

- [ ] **Step 3: Verify the check fails with the FRONTEND prefix when the URL is bad**

Run: `BASE_URL=http://127.0.0.1:1 bash /workspace/exam-generation/scripts/smoke_test_natural_sciences.sh`

Expected output contains a line matching `FAIL  [FRONTEND] GET /generate/natural_sciences returned HTTP 000 (expected 200)` and exits `1` with `NS SMOKE TEST FAILED`.

- [ ] **Step 4: Commit**

```bash
cd /workspace/exam-generation
git add scripts/smoke_test_natural_sciences.sh
git commit -m "feat(smoke): add FRONTEND check for /generate/natural_sciences (#94)"
```

---

### Task 3: API layer — `/api/schemas?subject=natural_sciences` structural check

**Files:**
- Modify: `scripts/smoke_test_natural_sciences.sh` (append the CHECK 2 block after Task 2's block)

**Interfaces:**
- Consumes: `API_URL`, `pass`, `fail`, `step`, `info` from Task 1.
- Produces: JSON structural assertion over six PISA dimensions returned by the backend schema route.

- [ ] **Step 1: Add the CHECK 2 block**

Append to `scripts/smoke_test_natural_sciences.sh` (before the trailing marker):

```bash
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
```

Then append a fresh `# Checks are appended by later tasks` marker line below.

- [ ] **Step 2: Verify the check passes against staging (happy path)**

Run: `BASE_URL=https://examgen-staging.cpeng.me bash /workspace/exam-generation/scripts/smoke_test_natural_sciences.sh`

Expected: `PASS  API: /api/schemas returns all six PISA dimensions` with an `INFO` line reporting `情境=3 情境子類別=<N> 科學能力=6 題型=3 學習內容=<N> 學習表現=<N>` where the counts are all positive.

- [ ] **Step 3: Verify the check fails with the API prefix when the backend is wrong**

Run: `BASE_URL=https://examgen-staging.cpeng.me API_URL=http://127.0.0.1:1 bash /workspace/exam-generation/scripts/smoke_test_natural_sciences.sh`

Expected: FRONTEND passes, then `FAIL  [API] GET /api/schemas?subject=natural_sciences returned HTTP 000 (expected 200)` and the summary reports `1 failed`.

- [ ] **Step 4: Commit**

```bash
cd /workspace/exam-generation
git add scripts/smoke_test_natural_sciences.sh
git commit -m "feat(smoke): add API check for /api/schemas natural_sciences PISA dimensions (#94)"
```

---

### Task 4: PROVIDER layer — authenticated `/api/generate` reach-through

**Files:**
- Modify: `scripts/smoke_test_natural_sciences.sh` (append the CHECK 3 block after Task 3's block)

**Interfaces:**
- Consumes: `API_URL`, `SMOKE_AUTH_TOKEN`, `SMOKE_EMAIL`, `pass`, `fail`, `step`, `info` from Task 1.
- Produces: an SSE stream sampled to a temp file; asserts that either (a) `event: result` + `event: done` were emitted, or (b) a controlled error surfaces via `event: error` / non-500 HTTP with a JSON detail.

- [ ] **Step 1: Add the CHECK 3 block**

Append to `scripts/smoke_test_natural_sciences.sh` (before the trailing marker):

```bash
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
```

Note: this task keeps the earlier `# Checks are appended by later tasks` marker in place at the bottom of the file — no new marker is added, because CHECK 3 is the last check.

- [ ] **Step 2: Verify the check passes when auth works and the generator streams successfully**

Run (against a healthy staging with a valid token):

```bash
SMOKE_AUTH_TOKEN=eyJhbGciOi... \
BASE_URL=https://examgen-staging.cpeng.me \
bash /workspace/exam-generation/scripts/smoke_test_natural_sciences.sh
```

Expected: three PASS lines (FRONTEND, API, PROVIDER) and `NS SMOKE TEST PASSED`.

- [ ] **Step 3: Verify the check fails with the PROVIDER prefix when the generator is unreachable**

Run:

```bash
SMOKE_AUTH_TOKEN=obviously-fake-token \
BASE_URL=https://examgen-staging.cpeng.me \
API_URL=http://127.0.0.1:1 \
bash /workspace/exam-generation/scripts/smoke_test_natural_sciences.sh
```

Expected: FRONTEND passes, API fails on the schema probe with `[API]`, PROVIDER fails on the generate probe with `[PROVIDER] /api/generate produced no HTTP response` (or `[API] … auth or rate-limit problem` if the localhost:1 socket happens to answer). Summary reports at least one failure with the correct layer labels.

- [ ] **Step 4: Verify the soft-pass path when the provider returns a controlled error**

If a staging deployment with a deliberately-invalid `LLM_API_KEY` is available, run the happy-path command from Step 2 against it. Expected: FRONTEND + API PASS, then `PASS  PROVIDER: /api/generate returned a controlled error (soft-pass)` with an `INFO error data: …` line quoting the provider's message.

If no such deployment is available, this step is documented rather than executed; note the expected behaviour in the commit message.

- [ ] **Step 5: Commit**

```bash
cd /workspace/exam-generation
git add scripts/smoke_test_natural_sciences.sh
git commit -m "feat(smoke): add PROVIDER check for authenticated NS /api/generate (#94)"
```

---

### Task 5: Documentation — pointer from CLAUDE.md + `scripts/` README breadcrumb

**Files:**
- Modify: `CLAUDE.md` (append a one-line entry under the "Common Commands" section, adjacent to the other smoke-test references)

**Interfaces:**
- Consumes: nothing.
- Produces: a discoverability hook so future agents find the new smoke test without grepping.

- [ ] **Step 1: Confirm the current "Common Commands" section anchor**

Run: `grep -n "^## Common Commands" /workspace/exam-generation/CLAUDE.md`

Expected: exactly one match. Note the line number reported (used in the next step to describe where the addition lands).

- [ ] **Step 2: Append the smoke-test note directly under the existing `uv run ruff check src/` line**

Modify `CLAUDE.md` — after the existing code block that ends with `uv run ruff check src/` inside the `## Common Commands` section, add a new subsection:

```markdown
### Staging smoke tests

```bash
# End-to-end staging smoke tests (env-driven; no committed secrets).
bash scripts/smoke_test.sh                          # Full docker-compose auth+generate
BASE_URL=https://examgen-staging.cpeng.me \
  bash scripts/smoke_test_natural_sciences.sh       # Natural-sciences layer probe (issue #94)
```

Each script prints `FRONTEND` / `API` / `PROVIDER` layer prefixes on failure so
red output names the failing layer.
```

- [ ] **Step 3: Verify the addition renders and grep finds it**

Run: `grep -n "smoke_test_natural_sciences.sh" /workspace/exam-generation/CLAUDE.md`

Expected: at least one match, and the match is inside the `## Common Commands` section (line number should be greater than the `## Common Commands` header line noted in Step 1).

- [ ] **Step 4: Commit**

```bash
cd /workspace/exam-generation
git add CLAUDE.md
git commit -m "docs: reference natural-sciences smoke test in CLAUDE.md (#94)"
```

---

### Task 6: Final verification — full run + shellcheck sweep

**Files:** none (verification only).

**Interfaces:**
- Consumes: `scripts/smoke_test_natural_sciences.sh` as built by Tasks 1–4.

- [ ] **Step 1: Happy-path run against staging**

Run:

```bash
SMOKE_AUTH_TOKEN=<real staging JWT> \
BASE_URL=https://examgen-staging.cpeng.me \
bash /workspace/exam-generation/scripts/smoke_test_natural_sciences.sh
```

Expected: three green PASS lines (FRONTEND / API / PROVIDER), the `情境=3 情境子類別=… 科學能力=6 題型=3 學習內容=… 學習表現=…` info line, and `NS SMOKE TEST PASSED` with exit code `0`.

- [ ] **Step 2: Layer-isolation runs (each should fail with exactly one prefix)**

Run three variants, one per layer:

```bash
# FRONTEND failure — bad SPA host, good API host
BASE_URL=http://127.0.0.1:1 \
API_URL=https://examgen-staging.cpeng.me \
SMOKE_AUTH_TOKEN=<real staging JWT> \
bash /workspace/exam-generation/scripts/smoke_test_natural_sciences.sh || true

# API failure — good SPA host, bad API host
BASE_URL=https://examgen-staging.cpeng.me \
API_URL=http://127.0.0.1:1 \
SMOKE_AUTH_TOKEN=<real staging JWT> \
bash /workspace/exam-generation/scripts/smoke_test_natural_sciences.sh || true

# PROVIDER failure — everything good but auth token fake, so the generate
# call reaches the endpoint and produces a controlled 401 → API layer
# (this is intentional — a fake JWT is an API-layer failure, not a
# provider failure; a real PROVIDER failure needs a staging deploy with
# broken LLM creds, and is exercised in Task 4 Step 4).
```

Expected: each run exits non-zero with `NS SMOKE TEST FAILED`, and the failing layer prefix in the output matches the layer the operator broke. In particular, the FRONTEND run must not print a spurious `[API]` failure (schema probe still succeeds because `API_URL` is healthy).

- [ ] **Step 3: shellcheck sweep**

Run: `shellcheck /workspace/exam-generation/scripts/smoke_test_natural_sciences.sh`

Expected: exits `0` with no output. If `shellcheck` is not installed locally, run this step on the branch's CI job or on the host (`nix run nixpkgs#shellcheck -- scripts/smoke_test_natural_sciences.sh` also works). Any warning must be fixed by rewriting the offending line — do not add blanket `# shellcheck disable=…` comments.

- [ ] **Step 4: No further commit — this task is verification only**

If any of Steps 1–3 fail, return to the relevant earlier task, fix, and re-run this task. Do not merge until Step 3 is clean.
