## Why

`claude-fable-5` is in the built-in allowed-models roster, so any user can select it for any tier from the web form, and an operator can set it through `LLM_MODEL_*`. Fable costs $10 / $50 per MTok against $4 / $20 for the current Opus model (Anthropic models overview, fetched 2026-10-01). The operator needs a single switch that stops Fable spend immediately without breaking requests, removing options from the UI, or shipping new code.

Research: `docs/research/2026-10-01-block-fable-downgrade-to-opus.md`.

## What Changes

- Add a boolean backend variable `LLM_FABLE_DOWNGRADE` (off by default; `1` or `true` enables). It is set as a Railway variable on the backend service.
- When the switch is on, every LLM text call whose model id contains `fable` is dispatched to `claude-opus-4-6` instead. This holds for all four tiers (plan, execute, verify, correct), the HTML figure call, the web-search fact-check call, the modification flow, `/api/plan-core-questions`, and the three CLIs.
- The substitution is silent to the requester: no HTTP 422, no change to the allowed-models roster, no change to the model dropdown. A request naming a Fable model succeeds.
- Request options that depend on the model are computed for the model that actually runs. An effort value the substitute does not accept (`xhigh`) is lowered to `high`.
- Every record that names a model states both the requested model and the model that ran: per-call exchange rows, the run's stored parameters, and the History detail view.
- Each substitution is logged at WARNING level, without prompt content.
- When the switch is off, behaviour and stored bytes are unchanged.

## Capabilities

### New Capabilities
- `model-downgrade-switch`: an operator-controlled switch that substitutes an Opus-class model for any Fable model at dispatch, and the record of which model was requested versus which ran.

### Modified Capabilities

None. The existing specs (`generation-event-protocol`, `generation-release-control`, `per-question-live-progress`, `question-snapshot-export`) state no requirement about model selection.

## Impact

- **Code**: `src/config.py` (new field, env parsing, substitution and effort-clamp helpers), `src/llm_client.py` (both dispatch entry points), `server/generate/exchange_recorder.py`, the places that build `params_json` (`server/generate/routes.py`, `server/generate/persistence.py`), `web/src/pages/HistoryDetail.tsx` plus `web/src/i18n/messages.ts`.
- **API**: additive only. The `llm_request` / `llm_response` / `llm_failure` events and the exchanges endpoint gain a requested-model field; stored run parameters gain a `model_substitutions` entry. No field is removed or renamed.
- **Database**: no migration. The new data lives inside existing JSON columns.
- **Operations**: one new Railway variable on the backend service only; a change takes effect after the staged change is deployed. `DEPLOYMENT.md` and the README environment table gain the row.
- **Cost / quality**: with the switch on, Fable requests run on `claude-opus-4-6`, which the repo already sends with adaptive thinking and a 16,384-token output ceiling.
- **Not affected**: allowed-models roster, admission checks, image generation (`IMAGE_MODEL`), Gemini and OpenAI calls, the gateway and frontend services' configuration.
