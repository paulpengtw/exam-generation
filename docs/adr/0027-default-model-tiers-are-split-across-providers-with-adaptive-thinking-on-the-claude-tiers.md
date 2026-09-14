# Default model tiers are split across providers with adaptive thinking on the Claude tiers

Fresh deployments split planning and 驗證 from execution so the same default model does not verify what it generated. The defaults are:

| Tier | Model | Effort |
|---|---|---|
| Plan | `claude-opus-4-6` | `high` |
| Execute | `gemini-3.1-pro-preview` | `high` |
| 驗證 (`model_verify` / `effort_verify`) | `claude-opus-4-6` | `high` |
| 修正 (`model_correct` / `effort_correct`) | Empty: inherit execute model | Empty: inherit execute effort |

Environment variables and per-request overrides keep their existing precedence. Only the unset environment case changes: an explicitly empty `LLM_MODEL_VERIFY=` or `LLM_EFFORT_VERIFY=` still means inherit the effective execute model or effort at call time, including after a per-request execute override. Empty 修正 model and effort keep the same inheritance rule. One shared set of eight constants in `src/config.py` supplies the dataclass defaults and environment fallbacks for both `Config` and `ServerConfig`; neither reader owns a separate set of tier defaults.

The built-in allowed roster is ordered `gemini-3.1-pro-preview`, `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-opus-5`, `claude-fable-5`, `claude-sonnet-5`. Membership and effort rosters are unchanged. Gemini's highest supported effort is `high`; the route validator rejects `xhigh` and `max` with HTTP 422. Opus 4.6 continues to support `low`, `medium`, `high`, and `max`, without `xhigh`.

Both provider keys are required on a fresh deploy: `GEMINI_API_KEY` for the execute tier and `LLM_API_KEY` for plan and 驗證. The existing provider-key admission guard returns HTTP 422 naming the field, model, and missing key: `"{field}: model '{model}' requires {env_name} to be set on the server"`.

The decision is for the Claude tiers to run adaptive thinking. Issue #758 delivers the thinking kwarg helper itself; this ADR records that decision, while issue #759 supplies the split model and effort defaults.

## Considered Options

**Keep a single-provider default** — Rejected because the selected split gives planning and independent 驗證 to Opus 4.6 while generation uses Gemini 3.1 Pro.

**Make `claude-opus-5` the default** — Rejected as out of scope: adopting it needs refusal handling. See `docs/research/2026-09-14-adopt-claude-opus-5.md`.

**Leave 驗證 inheriting execute** — Rejected as the default because the same model would verify what it generated. Operators can still explicitly choose inheritance by setting the verify model and effort to empty strings.

**Put defaults only in server config and let the CLI diverge** — Rejected because a fresh CLI run and fresh server deployment must use the same tier policy. The shared constants prevent reader drift.

## Consequences

Fresh deploys need two provider keys. Deployments with explicit model or effort settings retain them, and the existing 422 guard identifies whichever required key is missing.

Web form seeding of model and effort pickers from the `GET /api/models` defaults belongs to issue #760. This decision changes the backend defaults and advertised roster without changing the web form.

Opus 4.6 thinking at `high` spends output tokens that the old Sonnet thinking-off calls did not, increasing the token cost of planning and 驗證 when the #758 helper is in place.

Fact-check keeps keying off the effective 驗證 tier. `WEB_SEARCH_PROVIDER=anthropic` therefore works with the Claude 驗證 default; the optional pass remains subject to its existing current-events and provider gates.
