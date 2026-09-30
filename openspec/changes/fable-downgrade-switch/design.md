## Context

See `proposal.md` for motivation and `specs/model-downgrade-switch/spec.md` for the behaviour contract. Line references are to commit `dd9e6b8`.

Observed in the code:

- Model ids reach a provider through two entry points in `src/llm_client.py`. `LLMClient._call()` (L740) serves `generate`, `generate_json`, `generate_with_image`, and therefore `plan()`. `LLMClient.generate_with_tools()` (L1230) resolves its own model and calls `self.client.messages.create` directly (L1308); it is the Anthropic web-search fact-check path. `generate_with_google_search()` (L1391) also bypasses `_call()` but always dispatches to the Gemini endpoint. `generate_image()` uses `IMAGE_MODEL` on a separate client.
- Model-dependent request options are built by `_provider_options(model, purpose, provider)` (L612): `_anthropic_output_kwargs(model)` gives `claude-opus-4-6` adaptive thinking and `max_tokens=16384` and every other Anthropic id `max_tokens=8192`; `_temperature_kwargs(model)` withholds temperature; `_effort_kwargs(purpose, provider)` reads effort from the tier, not from the model.
- `EFFORT_LEVELS` in `src/config.py` gives `claude-fable-5` five levels including `xhigh` and `claude-opus-4-6` four (`low`, `medium`, `high`, `max`). Admission validates effort against the requested model (`_check_effort_for_model`, `server/generate/routes.py` L215), so `xhigh` passes admission for a Fable request.
- `ExchangeRecorder` writes `model_used` from the `model` field of the `llm_request` event (`server/generate/exchange_recorder.py` L198, L212). `LLMExchange` has no spare column.
- Run parameters are stored as `params_json` from `params.model_dump(mode="json")` at `server/generate/routes.py` L497 and `server/generate/persistence.py` L358, L530, L569.
- `web/src/pages/HistoryDetail.tsx` shows `detail.params_json` as raw JSON (L394) and passes it unchanged as `prefillParams` when regenerating (L249). There is no dedicated model display.
- `SERVER_ONLY_GENERATE_FIELDS` does not exist on this branch; it exists only in the `.worktrees/908` lane.
- Callers outside `LLMClient` read the configured model string directly: the fact-check provider gate, and the `model` written into the verification trail and `QuestionMetadata.model`.
- Existing off-by-default boolean idiom: `DB_POOL_CHECKOUT_ATTRIBUTION` uses `.lower() in {"1", "true"}` (`server/db.py`).

Decided by the user: the substitute is `claude-opus-4-6`, Fable stays selectable and is silently substituted, and history records both models.

## Goals / Non-Goals

**Goals:**
- No provider request carries a Fable id while the switch is on, on any path.
- One definition of "which model runs for this id", used by dispatch and by every recorder.
- Zero behaviour and zero stored-byte change while the switch is off.

**Non-Goals:**
- A configurable substitute model. The target is one constant; a second variable can be added later without changing this design.
- Changing the allowed-models roster, the model dropdown, or admission.
- Adding `claude-fable-5-1` or `claude-opus-5-5` to the roster or to `EFFORT_LEVELS`.
- Substituting image-generation, Gemini, or OpenAI models.
- Backfilling old History records.
- Scripts under `scripts/` that build their own SDK clients.

## Decisions

### D1. One pure helper owns the substitution

Add to `src/config.py`:

- `Config.fable_downgrade: bool = False`, parsed in `Config.from_env()` as `os.environ.get("LLM_FABLE_DOWNGRADE", "").strip().lower() in {"1", "true"}`. `ServerConfig` inherits it.
- `FABLE_DOWNGRADE_TARGET = "claude-opus-4-6"`.
- `Config.dispatch_model(model: str) -> str`: returns the target when the switch is on and `"fable" in model.lower()`, otherwise `model`.
- `Config.dispatch_effort(requested_model: str, effort: str) -> str`: when `dispatch_model` changed the id and `effort` is not in `EFFORT_LEVELS[FABLE_DOWNGRADE_TARGET]`, returns `high`; otherwise `effort`.

*Why*: dispatch, recorders, and callers outside `LLMClient` all need the same answer, and all of them already hold the config.

*Alternative — normalise the four tier fields when the config is built* (in `from_env`, the per-request `dataclasses.replace`, and `LLMClient.__init__`): rejected. It erases the requested id before anything can record it, which contradicts the "record both" requirement, and needs three call sites kept in sync.

*Alternative — match by prefix `claude-fable`*: rejected. The request is "name contains `fable`", and a substring also covers proxy-prefixed ids.

### D2. Guard both dispatch entry points

In `_call()` and in `generate_with_tools()`, immediately after the model is resolved: keep `requested_model`, compute `model = self.config.dispatch_model(requested_model)`, and use `model` for `resolve_provider`, `_provider_options`, the SDK call, and the events. Log one WARNING per substituted call naming both ids.

`generate_with_google_search()` gets no guard: it only ever talks to the Gemini endpoint. `generate_image()` gets no guard: it never uses a Claude id.

*Why both*: a guard only in `_call()` leaves the Anthropic fact-check on Fable whenever the verify tier is a Fable model.

*Alternative — a single guard in `_model_for_purpose()`*: rejected. `plan()` and callers that pass `model=` explicitly do not go through it.

### D3. Options follow the dispatched id; effort is clamped

Because D2 passes the dispatched id into `_provider_options`, a substituted call gets the `claude-opus-4-6` thinking and output-ceiling options and the same temperature handling with no further change. `_effort_kwargs` receives the requested model so it can apply `dispatch_effort`; `xhigh` becomes `high`.

*Why `high` and not `max`*: `high` is the nearest level at or below `xhigh` in the target's roster. Rounding up to `max` would raise cost on a switch whose purpose is to lower it.

*Why clamp at dispatch and not at admission*: the spec requires that a Fable request keep passing admission unchanged, and the CLIs have no admission step.

### D4. Recording the pair

- **Events**: `llm_request`, `llm_response`, and `llm_failure` keep `model` = dispatched id and gain `requested_model` only when the two differ. An absent field means no substitution, so switch-off events are byte-identical.
- **Exchanges**: `ExchangeRecorder` keeps `model_used` from `model` and copies `requested_model` into `request_body` when present. No migration.
- **Run parameters**: one helper, `model_substitutions(params, config) -> dict`, returns a mapping from tier name (`plan`, `execute`, `verify`, `correct`) to `{"requested": ..., "ran": ...}` for each tier whose effective model is substituted, using the same effective-tier resolution as `_check_generation_admission`. Each `params_json` build site adds the key `model_substitutions` only when the mapping is non-empty. The requested `model_*` fields are left untouched.
- **Question metadata and verification trail**: the `model` strings written by the three pipelines are passed through `config.dispatch_model(...)` so they name the model that ran. The requested id stays available from `params_json`.
- **History detail**: the raw parameters view already shows the new key. Add a short localized notice (zh-TW and en-US) above it listing each substituted tier as requested → ran. When regenerating, drop `model_substitutions` from `prefillParams` so the prefilled request carries the originally requested models and nothing else. Records without the key render exactly as today.

*Alternative — new database columns*: rejected. The JSON columns already carry this kind of provenance; a migration buys nothing.

*Alternative — overwrite the `model_*` fields in `params_json` with the dispatched id*: rejected. It loses the requested value and would make regenerate-from-History silently pin Opus after the switch is turned off.

*Alternative — reuse `SERVER_ONLY_GENERATE_FIELDS`*: not available on this branch. If the `.worktrees/908` lane lands first, `model_substitutions` is not a `GenerateParams` field and needs no entry there.

### D5. Callers that read the model outside `LLMClient`

The fact-check provider gate compares `resolve_provider(effective_verify_model)` with `WEB_SEARCH_PROVIDER`. Fable and the target are both Anthropic, so the gate's outcome does not change; it stays on the requested id. No other SDK use exists under `src/` or `server/` outside `LLMClient`.

## Risks / Trade-offs

- [A user selects Fable and gets Opus 4.6 output with no notice at generation time] → accepted by the user's decision; History detail and exchange records show the pair.
- [`claude-opus-4-6` is listed as a legacy model on Anthropic's models page] → it is the repo's default plan and verify model, so its key and parameter handling are already exercised; the target is a single constant if it must change.
- [Substituted calls use a 16,384-token ceiling shared with thinking, versus 8,192 without thinking for Fable] → this is the repo's existing, tested `claude-opus-4-6` profile; no new parameter combination is introduced.
- [A dispatch path added to `LLMClient` later bypasses the guard] → a test enumerates the SDK dispatch sites in `src/llm_client.py` and fails when a new one appears without a guard or an explicit exemption.
- [Old clients ignore `requested_model`] → additive field; no contract break.
- [The `.worktrees/908` lane moves the `params_json` build into `server/generate/run.py`] → the helper in D4 is a single function; the merge adds one call at the new site.

## Migration Plan

1. Deploy the code with `LLM_FABLE_DOWNGRADE` unset: no behaviour change.
2. To enable, add `LLM_FABLE_DOWNGRADE=1` on the Railway **backend** service and deploy the staged change. Railway applies variable changes only through a deploy; there is no hot reload.
3. Confirm with a run that names Fable: the backend log shows the WARNING line and the run's exchanges show `model_used = claude-opus-4-6`.
4. Rollback: remove the variable or set it to `0` and deploy the staged change. No data cleanup is needed; records written while the switch was on keep their substitution entries.

## Open Questions

- Whether the Anthropic API itself would accept `xhigh` for `claude-opus-4-6`. Not needed: D3 never sends it.
