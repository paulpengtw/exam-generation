## 1. Switch and substitution helpers

- [ ] 1.1 Write failing tests in a new `tests/test_fable_downgrade_config.py` for `LLM_FABLE_DOWNGRADE` parsing (unset, `1`, `true`, `TRUE`, ` 1 `, `0`, `false`, `yes`, empty) and verify they fail because `Config.fable_downgrade` does not exist
- [ ] 1.2 Add `fable_downgrade: bool = False`, its `from_env` parsing, and `FABLE_DOWNGRADE_TARGET` to `src/config.py`; verify 1.1 passes and that `ServerConfig.from_env()` exposes the same field
- [ ] 1.3 Add tests then implement `Config.dispatch_model` (switch off → unchanged; `claude-fable-5`, `claude-fable-5-1`, `claude-fable-5-20250901` → target; `claude-opus-5`, `claude-sonnet-5`, `gemini-3.1-pro-preview` → unchanged); verify the tests pass
- [ ] 1.4 Add tests then implement `Config.dispatch_effort` (`xhigh` → `high` only when substituted; `low`/`medium`/`high`/`max` unchanged; non-Fable model with `xhigh` unchanged); verify the tests pass

## 2. Dispatch guards

- [ ] 2.1 Write failing tests in a new `tests/test_fable_downgrade_dispatch.py` that drive `LLMClient.generate`, `generate_json`, `generate_with_image`, and `plan` with a fake Anthropic client and assert the SDK receives `model="claude-opus-4-6"`, adaptive thinking, and `max_tokens=16384` when the switch is on and the requested id is `claude-fable-5`
- [ ] 2.2 Apply `dispatch_model` in `LLMClient._call()` and pass the requested id to `_effort_kwargs` so `dispatch_effort` applies; verify 2.1 passes, including an `xhigh` → `high` case and a `max` → `max` case
- [ ] 2.3 Write a failing test, then apply the same guard in `LLMClient.generate_with_tools()`; verify the web-search request names `claude-opus-4-6` when the verify tier is a Fable model
- [ ] 2.4 Emit one WARNING per substituted call naming both ids; verify with `caplog` that the entry exists and contains no prompt text
- [ ] 2.5 Add a switch-off regression test asserting the SDK kwargs and emitted events for a `claude-fable-5` call are equal to those captured before the guard; verify it passes
- [ ] 2.6 Add a guard-coverage test that scans `src/llm_client.py` for SDK dispatch calls (`messages.create`, `messages.stream`, `chat.completions.create`, `images.generate`) and fails when a site is neither guarded nor on an explicit exemption list; verify it passes and fails when a guard is removed

## 3. Recording the requested and ran models

- [ ] 3.1 Add `requested_model` to `llm_request`, `llm_response`, and `llm_failure` events only when it differs from `model`; verify with tests for both the substituted and the unsubstituted case
- [ ] 3.2 Copy `requested_model` into `request_body` in `server/generate/exchange_recorder.py`; verify a recorder test shows `model_used == "claude-opus-4-6"` and `request_body["requested_model"] == "claude-fable-5"`, and that an unsubstituted exchange has no such key
- [ ] 3.3 Implement `model_substitutions(params, config)` using the same effective-tier resolution as `_check_generation_admission`; verify unit tests for per-request Fable, env-configured Fable, inherited verify/correct tiers, and the empty result
- [ ] 3.4 Add the `model_substitutions` key at each `params_json` build site (`server/generate/routes.py`, `server/generate/persistence.py`) only when non-empty; verify a server test stores the key for a Fable run with the switch on and stores byte-identical `params_json` with the switch off
- [ ] 3.5 Pass the `model` written into `QuestionMetadata.model` and the verification trail through `config.dispatch_model` in the math, social-studies, and natural-sciences pipelines; verify a test per pipeline shows the ran model when substituted and the unchanged model otherwise

## 4. Admission and roster stay unchanged

- [ ] 4.1 Add server tests with the switch on: the models endpoint returns the same list in the same order, and a generation request naming `claude-fable-5` with effort `xhigh` is admitted without HTTP 422; verify both pass without changing admission code

## 5. History detail

- [ ] 5.1 Add zh-TW and en-US messages for the substitution notice in `web/src/i18n/messages.ts`; verify the i18n key-parity test passes
- [ ] 5.2 Render the notice in `web/src/pages/HistoryDetail.tsx` listing each substituted tier as requested → ran; verify a component test shows it for a record with `model_substitutions` and shows nothing for a record without it
- [ ] 5.3 Drop `model_substitutions` from `prefillParams` on regenerate; verify a component test shows the prefilled request keeps the requested Fable id and has no `model_substitutions` key

## 6. Documentation

- [ ] 6.1 Add the `LLM_FABLE_DOWNGRADE` row to the backend variables table in `DEPLOYMENT.md` and to the README environment table, stating that a Railway variable change applies only after the staged change is deployed; verify both tables render and name the backend service only
- [ ] 6.2 Add a short section to `CLAUDE.md` under the LLM provider section describing the switch, the fixed target, the two guarded entry points, and the recording rule; verify it matches `design.md`

## 7. Verification

- [ ] 7.1 Run `choom -n 500 -- uv run pytest tests/test_fable_downgrade_config.py tests/test_fable_downgrade_dispatch.py tests/test_llm_effort.py tests/test_llm_adaptive_thinking.py tests/test_llm_temperature.py tests/test_llm_client_generate_with_tools.py tests/test_generation_sampler_allowlist.py` and verify all pass
- [ ] 7.2 Run `choom -n 500 -- uv run pytest tests/server` and `choom -n 500 -- npm --prefix web test`, one lane at a time, and verify all pass
- [ ] 7.3 Run `uv run ruff check src/ server/` and verify it is clean
- [ ] 7.4 Run `openspec validate fable-downgrade-switch --strict` and verify it reports no errors
