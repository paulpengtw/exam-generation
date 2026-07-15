# Spec: Staging smoke coverage for natural sciences generation (issue #94)

## Why

Three smoke scripts exist (`scripts/smoke_test*.sh`) but none touch the natural-sciences route. NS regressions in routing, schema loading, or generation wiring only surface manually.

## Design

New `scripts/smoke_test_natural_sciences.sh`, following the existing scripts' conventions (env-driven base URL, no committed secrets):

1. **Frontend route:** `GET $BASE_URL/generate/natural_sciences` returns 200 with the app shell (distinguishes frontend routing failure).
2. **Schema API:** `GET $API_URL/api/schemas?subject=natural_sciences` returns 200 and the JSON contains the PISA dimensions: 情境 (Personal / Local-and-national / Global), 情境子類別, 科學能力 (6 values), 題型 (3 PISA values), plus non-empty 學習內容/學習表現 pools (distinguishes backend schema/data failure).
3. **Generation reach-through:** authenticated `GET /api/generate?subject=natural_sciences&...` with representative params and `dry_run` (if supported by the endpoint) or `skip_verify + count=1`; accept either a valid SSE result or a *controlled* provider/configuration error (non-500 with clear detail). Auth token comes from env (`SMOKE_AUTH_TOKEN`) or the magic-link console flow documented in the script header.
4. **Failure output:** each step prints `FRONTEND` / `API` / `PROVIDER` prefixes so a failure names the failing layer.

Defaults: `BASE_URL=https://examgen-staging.cpeng.me`, overridable for local runs.

## Testing

- Run the script against staging (manual/CI): exit 0 on healthy staging.
- `shellcheck scripts/smoke_test_natural_sciences.sh` clean.
- Simulate failure layers locally (wrong port) → correct layer prefix in output, non-zero exit.

## Out of scope

- Full pytest coverage of NS generation (covered by unit tests already).
- Scheduling/CI wiring for the script.
- Real-token secrets in the repo (env-only).
