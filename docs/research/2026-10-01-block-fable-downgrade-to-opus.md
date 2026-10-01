# Research: Blocking Fable Model Requests with Opus-grade Downgrade

**Date:** 2026-10-01
**HEAD SHA:** dd9e6b82b5df874bb958cc6a778d41ab37c4a776
**Repo:** https://github.com/paulpengtw/exam-generation/tree/dd9e6b82b5df874bb958cc6a778d41ab37c4a776

---

## Answer

**Yes, a single boolean Railway variable can intercept every fable LLM call and substitute an
Opus model.** The minimal complete seam is a dual guard:
(1) `LLMClient._call()` in `src/llm_client.py` — covers every routine text-generation path
(plan, execute, verify, correct, HTML image renderer); and
(2) `LLMClient.generate_with_tools()` — which dispatches directly to
`self.client.messages.create()` at line 1308 **without going through `_call()`**, and is the
Anthropic web-search path used by `fact_check_question()`.
`generate_with_google_search()` (line 1418) also bypasses `_call()`, but its model string
is gated by the fact-check provider check before it is ever reached with a fable id.

A guard only in `_call()` is insufficient when `WEB_SEARCH_PROVIDER=anthropic` and a
fable model is configured as the verify tier.

`LLMClient.plan()` does **not** need a separate guard: it calls `generate()` which calls
`_call()`, so the `_call()` guard covers it.

Details, trade-offs, and open questions follow.

---

## 1. Every path by which a model id reaches a provider call

### 1.1 Environment-level defaults

`src/config.py::Config.from_env()` — [lines 94–131](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/config.py#L94-L131) — reads `LLM_MODEL_PLAN`, `LLM_MODEL_EXECUTE`, `LLM_MODEL_VERIFY`, `LLM_MODEL_CORRECT` and stores them in `Config.model_plan / model_execute / model_verify / model_correct`.

`server/config.py::ServerConfig.from_env()` — [lines 84–196](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/config.py#L84-L196) — `ServerConfig` extends `Config` ([`server/config.py` line 49](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/config.py#L49)) and additionally builds `llm_models_allowed` from `_DEFAULT_MODELS_ALLOWED`:

```python
_DEFAULT_MODELS_ALLOWED: tuple[str, ...] = (
    "gemini-3.1-pro-preview",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-opus-5",
    "claude-fable-5",       # <-- fable is in the built-in roster
    "claude-sonnet-5",
)
```
[`server/config.py` lines 38–45](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/config.py#L38-L45)

Any `LLM_MODEL_*` env var that names a configured tier model is appended to
`llm_models_allowed` even when `LLM_MODELS_ALLOWED` is empty
([`server/config.py` lines 182–195](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/config.py#L182-L195)).

### 1.2 Per-request model overrides (API)

`GET /api/generate` and `POST /api/generate` both accept query / body fields
`model_plan`, `model_execute`, `model_verify`, `model_correct`.
[`server/generate/routes.py` lines 332–339](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/generate/routes.py#L332-L339)

`POST /api/plan-core-questions` accepts `model_plan`, `model_execute`.
[`server/generate/models.py` lines 343–359](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/generate/models.py#L343-L359)

Note: `/api/plan-core-questions` calls `_check_model_allowed` (lines 613–614), then creates
a fresh `SrcConfig.from_env()` at line 624 (not the server config), applies
`dataclasses.replace` at lines 625–630, and passes `LLMClient(src_config)` at line 631.
Because `SrcConfig` is `src.config.Config`, it reads env vars including the new `LLM_FABLE_DOWNGRADE`
field from `from_env()`. The rewrite is covered if it lives in `_call()` + `generate_with_tools()`.

### 1.3 Admission gate (generation only)

`_check_generation_admission(params, config)` — [`server/generate/routes.py` lines 448–482](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/generate/routes.py#L448-L482) — validates all four per-request model fields against `config.llm_models_allowed`, then resolves effective tiers:

```python
effective_plan_model    = params.model_plan    or config.model_plan
effective_execute_model = params.model_execute or config.model_execute
effective_verify_model  = params.model_verify  or config.model_verify  or effective_execute_model
effective_correct_model = params.model_correct or config.model_correct or effective_execute_model
```

### 1.4 Config merge in service.py (generation only)

`service.py::_setup_run_context()` — [lines 276–286](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/generate/service.py#L276-L286) — builds a per-request `client_config` via `dataclasses.replace(config, model_execute=..., model_plan=..., ...)`. This `Config` object is what `LLMClient` receives for normal generation.

### 1.5 Modification flow

`server/generate/modification_routes.py` — [line 435](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/generate/modification_routes.py#L435) — uses `client_factory = getattr(request.app.state, "modification_client_factory", None) or LLMClient`.

`server/generate/modification_service.py` — [line 315](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/generate/modification_service.py#L315) — `client = factory(config)` where `config` is `ServerConfig` (which extends `Config`). **No `dataclasses.replace` per-request model override occurs in the modification flow.** The modification flow uses the server's global config directly (env-var models). A rewrite at `_call()` + `generate_with_tools()` covers modification automatically.

### 1.6 `LLMClient` tier resolution

`LLMClient._model_for_purpose(purpose)` — [`src/llm_client.py` lines 543–555](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/llm_client.py#L543-L555) — returns the appropriate model for verify/correct/execute purposes.

`LLMClient.plan()` — [lines 1064–1079](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/llm_client.py#L1064-L1079) — passes `self.config.model_plan` to `generate()`. `generate()` calls `_call()`. A rewrite at `_call()` covers this path without any guard needed in `plan()`.

`LLMClient.generate()` — [lines 1003–1035](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/llm_client.py#L1003-L1035): resolves `model = model or self._model_for_purpose(purpose)` then calls `_call()`.

`LLMClient.generate_json()` — [lines 1081–1159](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/llm_client.py#L1081-L1159): calls `_call()`.

`LLMClient.generate_with_image()` — [lines 1037–1062](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/llm_client.py#L1037-L1062): delegates to `generate()` which calls `_call()`.

### 1.7 All SDK dispatch sites (complete enumeration)

There are **seven** sites in `src/llm_client.py` where the Anthropic or OpenAI-compat SDK
is called directly with a model string. Which entry function owns each:

| Line | SDK call | Entry function | Reaches `_call()`? |
|------|----------|----------------|-------------------|
| 658 | `self.client.messages.stream(model=model, ...)` | `_generate_streaming()` | Yes — called from `_call()` |
| 840 | `self.client.messages.create(model=model, ...)` | `_anthropic_call()` | Yes — called from `_call()` |
| 888 | `oc.chat.completions.create(model=model, ...)` | `_openai_compat_streaming()` | Yes — called from `_call()` |
| 985 | `oc.chat.completions.create(model=model, ...)` | `_openai_compat_call()` | Yes — called from `_call()` |
| **1308** | `self.client.messages.create(model=call_model, ...)` | **`generate_with_tools()`** | **No — dispatches directly** |
| **1418** | `oc.chat.completions.create(model=call_model, ...)` | **`generate_with_google_search()`** | **No — dispatches directly** |
| 1194 | `self._image_client.images.generate(model=..., ...)` | `generate_image()` | No — uses `IMAGE_MODEL`/gpt-image2, never a Claude model |

Lines 658, 840, 888, and 985 are all leaf calls from within `_call()`. A guard at the top of `_call()` covers all four. Lines 1308 and 1418 are independent dispatch paths that bypass `_call()` entirely.

### 1.8 HTML renderer

`src/renderer.py::_generate_html_via_llm()` — [line 524](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/renderer.py#L524) — calls `llm_client.generate(...)` with `purpose="html_image"`. Routes through `generate()` → `_call()`. Covered by the `_call()` guard.

### 1.9 Fact-check path

`src/social_studies/fact_check.py::fact_check_question()` — [lines 143–185](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/social_studies/fact_check.py#L143-L185) — resolves `effective_verify_model = model_verify or model_execute`, checks the provider gate, then:

- If `WEB_SEARCH_PROVIDER=anthropic` and provider matches: calls `client.generate_with_tools()`.
  This path **dispatches at line 1308, bypassing `_call()`**. If `model_verify=claude-fable-5`
  and only `_call()` is guarded, this call reaches the Anthropic SDK with an unmodified fable id.
  A guard is required in `generate_with_tools()` too.

- If `WEB_SEARCH_PROVIDER=gemini` and provider matches: calls `client.generate_with_google_search()`.
  The provider gate checks `resolve_provider(effective_verify_model) != "gemini"`. Since
  `resolve_provider("claude-fable-5")` returns `"anthropic"`, the check fails and the gemini
  path is **never reached with a fable model id**. No guard is needed in `generate_with_google_search()`
  for fable specifically.

### 1.10 Three CLIs

`src/cli.py`, `src/social_studies/cli.py`, `src/natural_sciences/cli.py` all call `Config.from_env()` and pass the resulting `Config` to `LLMClient`. They offer no `--model-execute` flag; the only model source is the environment. A rewrite at `LLMClient._call()` + `generate_with_tools()` covers these automatically.

### 1.11 Frontend model list

`GET /api/models` — [`server/utility/routes.py` lines 20–43](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/utility/routes.py#L20-L43) — returns `config.llm_models_allowed` verbatim. The web form's model selectors in `ParamForm.tsx` and `CoreQuestionPicker.tsx` are populated from this list. If `claude-fable-5` is in the allowlist (it is by default), users can currently select it. A backend-only rewrite leaves fable visible in the UI dropdown but transparently substitutes it — which may confuse users. See section 3 (side effects) and section 8 (open questions).

### 1.12 SDK use outside `LLMClient`

Grep over `src/` and `server/` for direct Anthropic or OpenAI SDK calls outside `llm_client.py` returns no results. `LLMClient` is the sole SDK integration point.

---

## 2. Where a rewrite could go and trade-offs

### Option A — `_call()` + `generate_with_tools()` (recommended)

Add `_rewrite_model(self, model: str) -> str` and call it at the top of both `_call()` and
`generate_with_tools()`.

**Covers:** every text-generation path including all three CLIs, API, HTML image renderer,
Anthropic fact-check (`generate_with_tools()`), all four tiers, and the modification flow.

**Does not cover:** `generate_with_google_search()` — but a fable model is unreachable there
(provider gate blocks it; see §1.9). `generate_image()` — uses `IMAGE_MODEL`/`gpt-image2`, not Claude.

**Two-file footprint**: `_rewrite_model()` added once to `LLMClient`, guard called in two methods.

**Model-dependent code that uses the rewritten id (correctly):**
- `resolve_provider(model)` — both fable and opus are `"anthropic"`, no behavioral difference.
- `_anthropic_output_kwargs(model)` — called inside `_call()`. With the rewrite in place, receives the substituted model id. See section 3 for the `max_tokens` / thinking difference between `claude-opus-4-6` and other targets.
- `_accepts_sampling(model)` / `_temperature_kwargs(model)` — both fable and any Opus target are in `_SAMPLING_REJECT_PREFIXES` or `_ADAPTIVE_THINKING_MODELS`, so temperature is withheld for all. No difference.
- `_effort_kwargs(purpose, provider)` — provider is `"anthropic"` for both; effort is wrapped in `extra_body.output_config.effort`. No dispatch difference.
- All emitted observer events (`llm_request`, `llm_response`) carry the substituted model id — so `ExchangeRecorder.model_used` records the model that actually ran.

**Records that see the original (un-rewritten) model:**
- `params_json` on `GenerationLog` — [persisted before workers start](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/generate/routes.py#L495-L502) from `params.model_dump()`, which contains the raw request fields.
- `params_json` on `GenerationRecord` — [line 359](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/generate/persistence.py#L359) also comes from `params.model_dump()`.
- `verify_model` field in the verification trail — reads from `Config.model_verify` before `_call()` sees the rewrite; shows the original fable string.

This creates a split: `params_json` says "fable was requested" but `LLMExchange.model_used` says "opus ran." Mitigation: `WARNING` log per substitution, and optionally apply Option B as well.

### Option B — Config normalization at `service.py` + `_call()` + `generate_with_tools()`

Apply the rewrite at three points:
1. `service.py::_setup_run_context()` at the `dataclasses.replace` step for the tier fields — [lines 276–286](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/generate/service.py#L276-L286).
2. Keep the `_call()` guard as a fallback for CLI, modification, and plan-core-questions paths.
3. Keep the `generate_with_tools()` guard for the Anthropic fact-check path.

**Advantage:** `params_json` on `GenerationRecord` and the verification trail field would reflect the substituted model id for web-API generation requests. **Disadvantage:** `GenerationLog.params_json` is persisted from `params` before `_setup_run_context`, so it still shows the original model. Three places to maintain.

### Option C — Normalize at `LLMClient.__init__()`

Rewrite the four `Config` tier fields once at `LLMClient.__init__()`. All downstream code
(including `generate_with_tools()`, `generate_with_google_search()`, verification trail,
observer events) sees the substituted id from the start.

**Covers:** everything, including the verification trail `config.model_verify` read.

**Caveat 1:** Gemini fact-check would be broken if `model_verify=claude-fable-5`. After
rewriting `model_verify` to `claude-opus-5`, the provider gate (`resolve_provider("claude-opus-5")
== "anthropic"` ≠ `"gemini"`) would cause fact-check to be silently skipped. In practice this
is likely harmless (fact-check gate already blocks fable→Gemini paths), but it is a behavior
change worth noting.

**Caveat 2:** `Config` is a `dataclass` and may be shared; mutating at `__init__` time requires
`dataclasses.replace` on a copy to avoid modifying the shared server config.

**Trade-off:** most complete coverage, but broadest behavioral change (Gemini fact-check side
effect) and one more construction-time side effect to track.

### Option D — Allowlist-based blocking (422, no downgrade)

Remove `"claude-fable-5"` from `_DEFAULT_MODELS_ALLOWED`. **This blocks, not downgrades.**
Does not cover:
- `LLM_MODEL_*` env vars set to a fable id (always appended to allowlist regardless).
- CLI calls (no 422 gate).

Option D is not a substitute for A/B/C when env-var–configured models are in scope.

---

## 3. Side effects of a silent rewrite

| Affected location | What it sees | Effect of rewrite (Option A) |
|---|---|---|
| `_anthropic_output_kwargs(model)` in `_call()` | Substituted model id | **Critical**: `claude-opus-4-6` gets `{"thinking": {"type": "adaptive"}, "max_tokens": 16384}` ([`src/llm_client.py` lines 41–45](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/llm_client.py#L41-L45)). Other opus models get `{"max_tokens": 8192}`. Fable-5 gets `{"max_tokens": 8192}` today. Targeting opus-4-6 changes output token ceiling from 8192 → 16384 and adds `thinking`. Per Anthropic docs (fetched 2026-10-01): both current Fable and Opus models have adaptive thinking always on and 128K max output; the repo's `_ADAPTIVE_THINKING_MODELS` is pinned to `claude-opus-4-6` only and does not yet reflect this. |
| `_accepts_sampling(model)` | Substituted model id | No behavioral difference: fable, opus-4-6, opus-5 all reject temperature (via `_SAMPLING_REJECT_PREFIXES` at lines 48–60 or `_ADAPTIVE_THINKING_MODELS` at line 38). |
| `_effort_kwargs(purpose, provider)` | Substituted model id | Both fable and opus are `"anthropic"`, same dispatch. No difference for effort encoding. |
| Effort level compatibility | Substituted model id | **Important**: `EFFORT_LEVELS["claude-fable-5"] = FIVE_EFFORT_LEVELS` (includes `xhigh`/`max`). `EFFORT_LEVELS["claude-opus-4-6"] = FOUR_EFFORT_LEVELS` (no `xhigh`). If a caller submits `effort_execute=xhigh` (valid for fable, passes the pre-dispatch check), and the rewrite targets `claude-opus-4-6`, the Anthropic API receives `xhigh` for an opus-4-6 call. Whether that is accepted is not verified by this research. Targeting `claude-opus-5` (which also has `FIVE_EFFORT_LEVELS`) avoids this gap. [`src/config.py` lines 37–44](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/src/config.py#L37-L44) |
| `generate_with_tools()` in Anthropic fact-check | Substituted model id (after guard added) | Correct: `_call()` alone would miss this path; with the Option A dual guard it is covered. |
| `LLMExchange.model_used` in the DB | Substituted model id (from `llm_request` event) | Correct: records the model that actually ran. [`server/generate/exchange_recorder.py` line 212](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/server/generate/exchange_recorder.py#L212) |
| `GenerationLog.params_json` | Original request params | Shows fable was requested. Honest about intent; misleading about execution. Mitigate with a WARNING log at substitution time. |
| `GenerationRecord.params_json` | Original request params | Same gap as above. History UI shows original fable model unless Option B is also applied. |
| `verify_model` field in verification trail | `config.model_verify` from `Config` (unrewritten in Option A) | Shows the original fable model. Mitigate with WARNING log; resolved by Option B/C. |
| fact_check provider match | `resolve_provider(effective_verify_model)` — uses string from `Config.model_verify` | If `model_verify=claude-fable-5`, the provider check passes (both fable and any Anthropic web-search provider are `"anthropic"`), and inside the call the `generate_with_tools()` guard substitutes. No breakage when targeting any Opus model. |

---

## 4. Whether fable is currently reachable

**Fable is reachable in this repo today** via three paths:

1. **env var**: setting `LLM_MODEL_EXECUTE=claude-fable-5` (or any of the four tier vars) uses fable as the default model. Confirmed in `DEPLOYMENT.md` lines 142–149 (table of `LLM_MODEL_*` vars with Railway examples).
2. **per-request API param**: `claude-fable-5` is in `_DEFAULT_MODELS_ALLOWED`, so a request with `model_execute=claude-fable-5` passes `_check_model_allowed` without any extra configuration.
3. **web form UI**: `GET /api/models` returns the full `llm_models_allowed` list including `claude-fable-5`. The model selector in `ParamForm.tsx` populates from that list; `claude-fable-5` appears as a selectable option.

The switch is **not** a guard against future/env-configured use only — it is a live-traffic control.

**Note on `claude-fable-5-1`**: per Anthropic's models overview page (fetched 2026-10-01), the current fable model API ID is `claude-fable-5-1`; `claude-fable-5` is listed as legacy but still available. The repo's `_DEFAULT_MODELS_ALLOWED` contains only `"claude-fable-5"`, not `"claude-fable-5-1"`. A request with `model_execute=claude-fable-5-1` would be blocked by `_check_model_allowed` today unless the operator explicitly adds it to `LLM_MODELS_ALLOWED`. The `"fable" in model` substring check in `_rewrite_model()` would also catch `claude-fable-5-1` proactively if it were ever added to the allowlist.

Dated variants like `claude-fable-5-20250901` (seen in [`tests/test_llm_temperature.py` lines 55–56](https://github.com/paulpengtw/exam-generation/blob/dd9e6b82b5df874bb958cc6a778d41ab37c4a776/tests/test_llm_temperature.py#L55-L56)) are **not** in `_DEFAULT_MODELS_ALLOWED` and would be blocked by `_check_model_allowed` today.

---

## 5. Anthropic API facts

**Source**: Anthropic models overview page at `https://platform.claude.com/docs/en/models/overview`, fetched 2026-10-01.

| Parameter | Claude Fable 5.1 (current) | Claude Fable 5 (legacy) | Claude Opus 5.5 (current) | Claude Opus 4.6 |
|---|---|---|---|---|
| Claude API ID | `claude-fable-5-1` | `claude-fable-5` | `claude-opus-5-5` | `claude-opus-4-6` |
| Thinking | Adaptive (always on) | Adaptive (always on) | Adaptive (always on) | Adaptive (repo pins to `{"type":"adaptive"}`) |
| Effort default | `high` | — | `medium` | — |
| Max output (sync) | 128K tokens | 8K (repo's `max_tokens=8192`) | 128K tokens | 16384 (repo's adaptive ceiling) |
| Context window | 1M tokens | — | 1M tokens | — |
| Pricing | $10 / $50 per MTok (input/output) | — | $4 / $20 per MTok | — |
| `EFFORT_LEVELS` in repo | `FIVE_EFFORT_LEVELS` (`src/config.py:39`) | `FIVE_EFFORT_LEVELS` | `FIVE_EFFORT_LEVELS` | `FOUR_EFFORT_LEVELS` (no xhigh) |
| Temperature rejected | Yes (`_SAMPLING_REJECT_PREFIXES:51`) | Yes (`_SAMPLING_REJECT_PREFIXES:51`) | Yes (`_SAMPLING_REJECT_PREFIXES:49`) | Yes (`_ADAPTIVE_THINKING_MODELS:38`) |

**Mismatch between repo and live docs**: the repo's `_ADAPTIVE_THINKING_MODELS` is pinned to `{"claude-opus-4-6"}` only. Current fable and opus models have adaptive thinking always on but `_anthropic_output_kwargs()` sends `max_tokens: 8192` for them. The Anthropic API may accept 128K output for these models now; the repo under-requests. This is a pre-existing gap unrelated to the fable downgrade feature.

**Effort compatibility conclusion**: targeting `claude-opus-5` or `claude-opus-5-5` is safer than `claude-opus-4-6` because both share `FIVE_EFFORT_LEVELS` with fable. No effort value valid for fable would become invalid after the rewrite. Targeting `claude-opus-4-6` introduces a potential 400 if any request arrives with `effort=xhigh`.

---

## 6. Railway and env-var idiom

**Source**: Railway variables guide at `https://docs.railway.com/guides/variables`, fetched 2026-10-01.

**Variable delivery**: Railway variables are environment variables injected at container start. A change to a service variable creates a set of staged changes that **must be reviewed and deployed** before taking effect — variable changes trigger an automatic redeploy. There is no hot-reload; the new value is not available to a running process until the container restarts.

**Sealed variables**: provided to builds and deployments but never visible in the Railway UI. Not provided via `railway variables` or `railway run` CLI. Relevant if the variable should not be inspectable by team members.

**Which services need the variable**: only the **backend** service, since `LLMClient` lives in Python and is used by both the web server and the CLI (which only runs inside the backend container or a developer machine). The gateway service does not make LLM calls. The frontend service does not know about model ids at generation time.

**Existing boolean parsing idioms in this repo**:

| Variable | Parsing idiom | File |
|---|---|---|
| `LLM_STREAM` | `not in ("0", "false", "False")` — truthy by default | `src/config.py:114` |
| `CREATIVE_PLANNING` | `not in ("0", "false", "False", "")` — truthy by default | `src/config.py:123` |
| `DB_POOL_CHECKOUT_ATTRIBUTION` | `.lower() in {"1", "true"}` — falsy by default | `server/db.py:58` |
| `GATEWAY_FOLLOW_FRONTEND` | `.strip() == "1"` — falsy by default | `gateway/__main__.py:44` |

The switch should default to **off** (falsy), so `os.environ.get("LLM_FABLE_DOWNGRADE", "").strip() in {"1", "true"}` matches the `DB_POOL_CHECKOUT_ATTRIBUTION` idiom and is explicit about the enabled value. Store it in `Config` (and `ServerConfig` via inheritance) as a `bool` field with default `False`, parsed in `Config.from_env()`. The `src/config.py` location is correct since CLI and server both read from there.

---

## 7. Recommendation

**Recommended seam**: dual guard — `LLMClient._call()` and `LLMClient.generate_with_tools()` — both in `src/llm_client.py`. Add `_rewrite_model(self, model: str) -> str` as a private method and call it at the top of each method body.

**Suggested variable name**: `LLM_FABLE_DOWNGRADE` — follows the `LLM_*` prefix used for every other LLM knob in this repo. Add `fable_downgrade: bool = False` to `Config` in `src/config.py`.

**Suggested second variable for the target**: `LLM_FABLE_DOWNGRADE_TARGET` — defaults to `claude-opus-5` (same `FIVE_EFFORT_LEVELS` as fable, avoids the `xhigh` mismatch risk with opus-4-6). Add `fable_downgrade_target: str = "claude-opus-5"` to `Config`.

**Rewrite logic** (pseudo-code, not a code change):
```python
def _rewrite_model(self, model: str) -> str:
    if self.config.fable_downgrade and "fable" in model:
        target = self.config.fable_downgrade_target or "claude-opus-5"
        logger.warning("LLM_FABLE_DOWNGRADE: rewriting %r → %r", model, target)
        return target
    return model
```

**What to log**: a WARNING per call (one-time suppression is not needed here since the deployment intent is deliberate and operators should see confirmation in logs). Do not log the full prompt.

**What to record**: `LLMExchange.model_used` will automatically record the substituted model since the rewrite precedes the `llm_request` event emission. `params_json` (on `GenerationLog` and `GenerationRecord`) will retain the original requested model. If that split is unacceptable, also apply the rewrite in `service.py::_setup_run_context()` at the `dataclasses.replace` step — but note `GenerationLog.params_json` is persisted from the pre-service params and cannot be retroactively rewritten without additional work.

**Tests that would pin the behavior**:
- `test_fable_downgrade_covered_by_call()` — verify that `_call()` with a fable model id and `fable_downgrade=True` dispatches to the target opus id; fable id unchanged when `fable_downgrade=False`.
- `test_fable_downgrade_covered_by_generate_with_tools()` — verify that `generate_with_tools()` with a fable model id and `fable_downgrade=True` dispatches to the target opus id.
- `test_fable_downgrade_covers_plan_path()` — verify that `LLMClient.plan()` also dispatches the substituted id (it calls `generate()` which calls `_call()`).
- `test_fable_downgrade_covers_dated_variant()` — `"claude-fable-5-20250901"` is rewritten.
- `test_fable_downgrade_target_env_var()` — `LLM_FABLE_DOWNGRADE_TARGET=claude-opus-4-6` changes the substitution destination.
- `test_fable_downgrade_warning_emitted()` — a `WARNING` log line is emitted when a rewrite occurs.
- `test_fable_downgrade_google_search_not_needed()` — with `WEB_SEARCH_PROVIDER=gemini` and `model_verify=claude-fable-5`, the provider gate (`resolve_provider("claude-fable-5") == "anthropic"` ≠ `"gemini"`) skips fact-check before `generate_with_google_search()` is reached; `_rewrite_model()` is never invoked on that path.

---

## 8. Open questions for the user

1. **Which opus target?** `claude-opus-5` avoids the `xhigh`-effort gap but has a different `max_tokens` / thinking profile than `claude-opus-4-6`. Do you want a fixed second variable, or should the target always be the configured `LLM_MODEL_VERIFY` (which is `claude-opus-4-6` by default)?

2. **UI model list**: with only a backend rewrite, the web form dropdown still shows `claude-fable-5` as a selectable option. Should `claude-fable-5` be removed from `_DEFAULT_MODELS_ALLOWED` (so it no longer appears in the UI or gets accepted via per-request params), or should the dropdown continue to allow it (with the silent substitution behind the scenes)?

3. **`params_json` honesty**: do you want history records to show the substituted model or the originally requested fable model? If substituted, also apply the rewrite in `service.py::_setup_run_context()`.

4. **Scope**: `_DEFAULT_MODELS_ALLOWED` uses `"claude-fable-5"` (legacy id). The current API id `"claude-fable-5-1"` is not in the allowlist and would be blocked by the admission gate before reaching `_call()`. Do you want the rewrite to cover any future dated variants proactively (`"fable" in model` substring check), or only exact-match `"claude-fable-5"`?

5. **Effort level behavior after rewrite to opus-4-6**: if any existing requests or configs use `effort=xhigh`, targeting opus-4-6 could produce a 400 from the Anthropic API. Verify before choosing opus-4-6 as the default target.

---

## Appendix: What changed in this document (v2, 2026-10-01)

**Corrected**:
- Answer paragraph: removed the erroneous claim of a "symmetric guard in `LLMClient.plan()`"; `plan()` calls `generate()` → `_call()`, no separate guard needed.
- §1.6 renamed to §1.7 and rewritten to enumerate all 7 SDK dispatch sites with their owning entry function and whether they reach `_call()`. Lines 1308 and 1418 bypass `_call()`.
- §1.8 (fact-check): corrected "both eventually call `_call()`" — `generate_with_tools()` at line 1308 dispatches directly without going through `_call()`. The `generate_with_google_search()` path is unreachable with a fable model id due to the provider gate.
- §2 Option A: updated from "`_call()` only" to dual guard `_call()` + `generate_with_tools()`. Added Options C and D.
- §3 table: added row for `generate_with_tools()` coverage gap under `_call()`-only guard.
- §7 recommendation: updated recommended seam to the dual guard.
- Added `test_fable_downgrade_covered_by_generate_with_tools()` and `test_fable_downgrade_google_search_not_needed()` to the test list.

**Added**:
- §1.5: modification flow — no `dataclasses.replace` per-request override; uses `ServerConfig` directly; covered by Option A.
- §1.12: grep result — no Anthropic/OpenAI SDK use outside `LLMClient`.
- Updated §5: live Anthropic API facts fetched from `platform.claude.com/docs/en/models/overview` 2026-10-01, including `claude-fable-5-1` current ID, `claude-opus-5-5` current ID, effort defaults, max output, pricing.
- Updated §6: live Railway variable delivery facts from `docs.railway.com/guides/variables` 2026-10-01 (staged deploy required, no hot-reload, sealed variable option).
- Note on `claude-fable-5-1` not being in the current allowlist.

**Unverified items still outstanding**:
- Whether the Anthropic API accepts `effort=xhigh` for `claude-opus-4-6` at the wire level (the repo's `EFFORT_LEVELS` excludes it, but the API behavior on receipt is untested).
- Whether `max_tokens: 16384` vs the documented 128K ceiling for current fable/opus models causes silent truncation or an API error — the repo under-requests; no evidence it causes failures.
