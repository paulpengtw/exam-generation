# Research: Core Question (核心問題) Planner Model Selector

**Date:** 2026-09-30
**Commit researched:** `689784739c9eb77ed522e8c0114ca6961670314d`
**Goal:** Inform an implementer who wants to add a model selector to the 核心問題 generator,
defaulting to Gemini.

---

## Summary

The 核心問題 generator is implemented end-to-end and already half-supports per-request model
overrides. The backend `PlanCoreQuestionsRequest` Pydantic model already accepts `model_plan`
(nullable, validated against the server allowlist). The gap is entirely on the frontend:
the TypeScript `PlanCoreQuestionsRequest` interface does not declare `model_plan`, the
`CoreQuestionPicker` component has no `modelPlan` prop, and neither call site in `ParamForm.tsx`
passes the value through.

Gemini is already wired end-to-end: `gemini-3.1-pro-preview` is the default **execute** model
and is first in the built-in allowlist. The Gemini API key (`GEMINI_API_KEY`) is already a
required config value in production. The Anthropic SDK and OpenAI SDK (used in OpenAI-compat
mode for Gemini) are both pinned dependencies.

A model selector for the picker therefore requires three frontend changes and zero backend
changes. The default model question is the primary open question: whether the picker should
default to Gemini at the component level (overriding the server's `defaults.plan` for this
surface only) or whether the server default `LLM_MODEL_PLAN` should be changed to a Gemini
model for the whole application.

---

## 1. Current implementation (request path)

### 1.1 UI component

[`web/src/components/CoreQuestionPicker.tsx`](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/web/src/components/CoreQuestionPicker.tsx)

The component accepts: `topic`, `subject`, `subjectFilter`, `grade`, `onPick`, `onClear`,
`pickedValue`. It does **not** accept a `modelPlan` prop.

The planner call (lines 36–44):

```typescript
const feedback = useActionFeedback({
  action: (signal: AbortSignal) => planCoreQuestions({
    topic,
    subject,
    subject_filter: subjectFilter ? [subjectFilter] : undefined,
    grade,
  }, signal),
  ...
```

No `model_plan` is passed. The server therefore always uses its configured default (`LLM_MODEL_PLAN`).

### 1.2 Render site in ParamForm

[`web/src/components/ParamForm.tsx` lines 5270–5278](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/web/src/components/ParamForm.tsx#L5270-L5278)

```tsx
<CoreQuestionPicker
  topic={topic}
  subject={subject}
  subjectFilter={subjectFilter || undefined}
  grade={grade !== "" ? grade : undefined}
  onPick={(q) => setField("coreQuestion", q)}
  onClear={() => setField("coreQuestion", null)}
  pickedValue={coreQuestion}
/>
```

No `modelPlan` prop is threaded through.

### 1.3 Auto-planner call in confirmation flow

[`web/src/components/ParamForm.tsx` lines 1990–1994](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/web/src/components/ParamForm.tsx#L1990-L1994)

```typescript
void planCoreQuestions({
  topic: latestParams.topic ?? "",
  subject,
  subject_filter: pendingSubjectFilter,
  grade: latestParams.grade,
}).then(...)
```

This is a second call site — triggered automatically during the confirmation flow, not from
the button in `CoreQuestionPicker`. It also does not pass `model_plan`. **An implementer must
update both call sites.**

### 1.4 Frontend API interface

[`web/src/api/client.ts` lines 167–172](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/web/src/api/client.ts#L167-L172)

```typescript
export interface PlanCoreQuestionsRequest {
  topic: string;
  subject?: string;
  subject_filter?: string[];
  grade?: number;
}
```

`model_plan` is absent. This interface must be extended.

### 1.5 Backend API route

[`server/generate/routes.py` lines 604–665](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/server/generate/routes.py#L604-L665)

`POST /api/plan-core-questions` → `plan_core_questions_endpoint`. The endpoint:
1. Validates `body.model_plan` against `config.llm_models_allowed` via `_check_model_allowed` (line 613).
2. Resolves `effective_plan_model = body.model_plan or config.model_plan` (line 616).
3. Validates effort against the resolved model's roster (line 618).
4. Checks provider key for the resolved model (line 619).
5. Calls `asyncio.to_thread(spec.plan_core_questions, client, body.topic, ...)` (line 637–645).

### 1.6 Backend request model

[`server/generate/models.py` lines 343–359](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/server/generate/models.py#L343-L359)

```python
class PlanCoreQuestionsRequest(BaseModel):
    topic: str
    subject_filter: list[str] | None = None
    grade: int | None = None
    subject: Literal["math", "social_studies", "natural_sciences"] = "social_studies"
    model_plan: str | None = None
    model_execute: str | None = None
    effort_plan: str | None = None
```

**The backend seam already exists and is complete.** `model_plan` is accepted and forwarded
correctly to the LLM client.

### 1.7 LLM client model dispatch

[`src/llm_client.py` lines 543–555](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/src/llm_client.py#L543-L555)

```python
def _model_for_purpose(self, purpose: str) -> str:
    if purpose in _VERIFY_PURPOSES:
        return self.config.model_verify or self.config.model_execute
    if purpose in _CORRECT_PURPOSES:
        return self.config.model_correct or self.config.model_execute
    return self.config.model_execute
```

[`src/llm_client.py` lines 1064–1079](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/src/llm_client.py#L1064-L1079)

`LLMClient.plan()` calls `self.generate()` with `model=self.config.model_plan`. Plan purposes
(`"plan_core_questions"`) are **not** in `_VERIFY_PURPOSES` or `_CORRECT_PURPOSES`, so
`_model_for_purpose` returns `model_execute` for them — but `plan()` bypasses
`_model_for_purpose` and passes `model_plan` explicitly. The planner always uses `model_plan`,
never `model_execute`.

### 1.8 Provider routing for Gemini

[`src/llm_client.py` lines 96–101](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/src/llm_client.py#L96-L101)

```python
def resolve_provider(model: str) -> Provider:
    if model.startswith("gemini-"):
        return "gemini"
    if model.startswith("gpt-") or _OPENAI_O_SERIES_RE.match(model):
        return "openai"
    return "anthropic"
```

Any model ID starting with `gemini-` is dispatched through the OpenAI-compat client pointed
at `GEMINI_BASE_URL`.

---

## 2. Existing model-selection patterns in the repo

### 2.1 Main generation form model selector

[`web/src/components/ParamForm.tsx` lines 6003–6050](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/web/src/components/ParamForm.tsx#L6003-L6050)

`ParamForm` already renders `<select>` dropdowns for `model_plan` and `model_execute`. The
pattern:

1. `models` is fetched once from `GET /api/models` via `getAvailableModels()` (defined at
   [`web/src/api/client.ts` lines 273–282](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/web/src/api/client.ts#L273-L282)).
2. The select element shows `"Default (claude-opus-4-6)"` when value is `""`, followed by
   each model in `models.allowed`.
3. The `value` is stored in `fields.modelPlan` / `fields.modelExecute`.
4. localStorage is used for persistence:
   [`ParamForm.tsx` lines 1625–1626](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/web/src/components/ParamForm.tsx#L1625-L1626)
   and lines 2359–2362.
5. Selected model is included in the POST body as `model_plan?: string` (omitted when empty).

The `AvailableModels` interface returned by `/api/models`:

```typescript
export interface AvailableModels {
  allowed: string[];
  effort?: Record<string, string[]>;
  defaults: { plan: string; execute: string; verify: string; correct: string; ... };
}
```

The `defaults.plan` value is the server's configured `model_plan` (e.g., `"claude-opus-4-6"`).

### 2.2 Server-side allowlist and check

[`server/generate/routes.py` lines 203–212](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/server/generate/routes.py#L203-L212)

```python
def _check_model_allowed(model: str | None, config: ServerConfig, field: str) -> None:
    if not model:
        return
    if model not in config.llm_models_allowed:
        raise HTTPException(status_code=422, ...)
```

Any model submitted in `model_plan` must appear in `llm_models_allowed`. The default roster:

[`server/config.py` lines 38–45](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/server/config.py#L38-L45)

```python
_DEFAULT_MODELS_ALLOWED: tuple[str, ...] = (
    "gemini-3.1-pro-preview",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-opus-5",
    "claude-fable-5",
    "claude-sonnet-5",
)
```

`gemini-3.1-pro-preview` is first in the built-in roster. **No allowlist change is needed**
to use Gemini as the picker's default.

---

## 3. Gemini support today

### 3.1 SDK dependency

[`pyproject.toml` line 9](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/pyproject.toml#L9):
`"openai>=1.0"`. Locked version per `uv.lock`: **openai 2.30.0**.

There is **no native Google AI SDK** (`google-generativeai` or `google-genai`). Gemini is
accessed entirely via its OpenAI-compatible endpoint.

### 3.2 Client setup

[`src/llm_client.py` lines 623–633](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/src/llm_client.py#L623-L633)

```python
def _openai_compat_client(self, provider: str) -> OpenAI:
    key_attr, env_name, url_attr = _PROVIDER_ENV[provider]
    api_key = getattr(self.config, key_attr)
    if not api_key:
        raise ValueError(f"{env_name} is required to call {provider} models.")
    base_url = getattr(self.config, url_attr)
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=self.config.llm_timeout_seconds)
```

[`src/llm_client.py` lines 90–93](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/src/llm_client.py#L90-L93)

```python
_PROVIDER_ENV: dict[str, tuple[str, str, str]] = {
    "gemini": ("gemini_api_key", "GEMINI_API_KEY", "gemini_base_url"),
    ...
}
```

### 3.3 Environment variables

- `GEMINI_API_KEY` — required when any `gemini-*` model is used. Missing key raises HTTP 422
  via `_check_provider_key_for_model`.
- `GEMINI_BASE_URL` — defaults to `https://generativelanguage.googleapis.com/v1beta/openai/`
  ([`src/config.py` line 63](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/src/config.py#L63)).

### 3.4 Gemini model IDs referenced in the codebase

- `gemini-3.1-pro-preview` — used as `DEFAULT_MODEL_EXECUTE`
  ([`src/config.py` line 13](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/src/config.py#L13))
  and first in `_DEFAULT_MODELS_ALLOWED`.
- `gemini-3.x` — listed in `_SAMPLING_REJECT_PREFIXES`
  ([`src/llm_client.py` line 56](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/src/llm_client.py#L56)):
  temperature is withheld for these models.
- Effort translation for Gemini: `reasoning_effort` with values `"low"`, `"medium"`, `"high"`.
  Three-level roster defined in `EFFORT_LEVELS`:
  [`src/config.py` lines 43–44](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/src/config.py#L43-L44).

### 3.5 Sampling and token ceiling differences vs. Anthropic

- **System prompt**: The OpenAI-compat path passes `system` as the first element in the
  `messages` array (role `"system"`), not using the Anthropic `system` parameter.
- **Prompt caching**: Not used for Gemini (only Anthropic SDK path uses `cache_control`).
- **max_tokens**: `_max_tokens_kwargs("gemini")` returns `{"max_tokens": 8192}` — same as
  Anthropic execute tier. No adaptive thinking overhead for Gemini.
- **Temperature**: Withheld for `gemini-3.x` models (sampling reject list).
- **Effort**: `reasoning_effort` for Gemini accepts `"low"`, `"medium"`, `"high"` only.
  The current `DEFAULT_EFFORT_PLAN = "high"` is compatible.
- **JSON mode / structured output**: Not used in the planner path. `plan_core_questions`
  returns a JSON array parsed from free-form text via `_parse_candidates` in
  [`src/common/planner.py`](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/src/common/planner.py).
  No Pydantic forced-output or OpenAI response format is applied — the same parser works for
  both providers.
- **Streaming**: Used when an observer is set (`self._observer and self.config.llm_stream`).
  For Gemini, streaming uses `stream=True` + `stream_options={"include_usage": True}` via
  `_openai_compat_streaming`.

---

## 4. Official-doc findings

**Caution — unverified against live docs.** The research below is inferred from codebase
references only; the implementer must confirm against current official sources before shipping.

The repo accesses Gemini via its OpenAI-compatible endpoint. The relevant official references
are:

- Google's OpenAI compatibility guide for the Gemini API:
  `https://ai.google.dev/gemini-api/docs/openai` (not accessed during this research).
- The OpenAI Python SDK changelog for breaking changes between the locked version (2.30.0)
  and any upgrade target: `https://github.com/openai/openai-python/blob/main/CHANGELOG.md`
  (not accessed).

**What needs live verification before implementing:**

1. Whether `gemini-3.1-pro-preview` is a currently valid model ID on the Gemini OpenAI-compat
   endpoint. The ID is already used by the codebase for `model_execute` and would be a
   reasonable picker default, but the implementer should confirm it is still valid or choose
   a stable alias (e.g., `gemini-2.0-flash`, `gemini-1.5-pro`, etc.).
   **Marked as unverified — do not assume this ID is correct.**

2. Whether `reasoning_effort` is supported on the planned model. Gemini's reasoning_effort
   support on the OpenAI-compat surface varies by model generation.

3. Response shape differences already handled: the codebase's `_openai_compat_call` and
   `_openai_compat_streaming` paths cover both Gemini and OpenAI, so no additional adapter
   work is needed for the planner call.

---

## 5. Proposed change surface

### 5.1 Files that must change

| File | Change | Notes |
|---|---|---|
| `web/src/api/client.ts` | Add `model_plan?: string` to `PlanCoreQuestionsRequest` interface (line 167) | Server already accepts it |
| `web/src/components/CoreQuestionPicker.tsx` | Add `modelPlan?: string` prop; pass it as `model_plan` in the `planCoreQuestions()` call (line 37) | |
| `web/src/components/ParamForm.tsx` (render site) | Pass `modelPlan={...}` to `<CoreQuestionPicker>` (line 5270) | |
| `web/src/components/ParamForm.tsx` (auto-planner) | Pass `model_plan: ...` to the direct `planCoreQuestions()` call in the confirmation flow (line 1990) | Second call site — easy to miss |

### 5.2 No backend changes required

The backend seam is complete:
- `PlanCoreQuestionsRequest.model_plan` already exists and is validated.
- The allowlist already includes `gemini-3.1-pro-preview`.
- The provider routing and API key check already work for Gemini models.

### 5.3 Gemini default approach — two options

**Option A — Component-level default (frontend only).**
`CoreQuestionPicker` defaults `modelPlan` to `"gemini-3.1-pro-preview"` (or another Gemini
model) when the prop is not supplied. `ParamForm` passes `modelPlan` from `fields.modelPlan`
when set, falling back to the Gemini string. This means the picker uses Gemini by default
regardless of `LLM_MODEL_PLAN`, while the rest of generation still uses the server default.
Requires no env-var change; may cause surprise when the overall plan model differs.

**Option B — Server default change.**
Set `LLM_MODEL_PLAN` to a Gemini model ID in the deployment environment. Both the picker
and the batch-planner (context angles, etc.) then default to Gemini. The frontend selector
continues to show the server's `models.defaults.plan`. Cleaner consistency; requires an
operator deploy change and `GEMINI_API_KEY` to be present (it already is in the default
config).

### 5.4 Validation gate already present

Any `model_plan` submitted from the frontend is checked against `config.llm_models_allowed`
at the route level. No additional server-side validation is needed.

### 5.5 Effort field

`PlanCoreQuestionsRequest` also has `effort_plan?: str`. The Gemini three-level roster
(`low`, `medium`, `high`) is already defined. If the implementer wants an effort selector
alongside the model selector, the same pattern applies. For a minimal implementation, omit
it and let the server default (`"high"`) apply.

### 5.6 Persistence consideration

`ParamForm` persists `model_plan` and `model_execute` to `localStorage` (keys `"model_plan"`,
`"model_execute"`). If a standalone picker-model preference is desired, a separate key
(e.g., `"planner_model"`) should be used to avoid conflating the picker preference with the
full generation preference. Alternatively, reusing the same `model_plan` key is simpler and
keeps the two surfaces in sync.

---

## 6. Tests that exist and would need attention

### 6.1 Backend

[`tests/server/test_plan_core_questions_routes.py`](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/tests/server/test_plan_core_questions_routes.py)
(580 lines)

- `test_plan_core_questions_forwards_model_plan_override` (line 518) — verifies that a
  submitted `model_plan` reaches `LLMClient.config.model_plan`.
- Line 579 also verifies that `model_execute` is correctly `gemini-3.1-pro-preview` by
  default.
- There is no dedicated test for submitting a `gemini-*` model_plan; the implementer should
  add one (or verify the existing monkeypatch fixture covers Gemini IDs).

### 6.2 Frontend

[`web/src/components/CoreQuestionPicker.test.tsx`](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/web/src/components/CoreQuestionPicker.test.tsx)

Mocks `planCoreQuestions` from `../api/client`. No test currently checks that a `modelPlan`
prop is forwarded to the mock. New tests are needed to:
1. Verify that when `modelPlan` is set, `planCoreQuestions` is called with `model_plan`.
2. Verify that when `modelPlan` is absent, `model_plan` is omitted (or uses the desired
   Gemini default, depending on which option is chosen).

---

## 7. Open questions

1. **Which Gemini model ID is "the default"?** `gemini-3.1-pro-preview` is the ID already in
   the codebase; the implementer must verify it is a currently valid, stable ID on the
   Gemini OpenAI-compat endpoint. If the model is in preview, a more stable alias may be
   preferable.

2. **Component default or server default (Option A vs. B above)?** Option A isolates the
   change to the frontend; Option B is a coherent server config change. The user has not
   specified.

3. **Is a per-request model selector (UI dropdown) needed, or just a changed default?**
   The backend and the main form already support a dropdown. Adding one to
   `CoreQuestionPicker` follows the same `<select>` + `models.allowed` pattern. If the
   only goal is "make it default to Gemini with no UI", only the prop default (Option A) or
   env var (Option B) is needed — no new UI component.

4. **Should `effort_plan` also be exposed in the picker's selector?** It would be consistent
   with the main form's UX but adds complexity. Gemini caps at `"high"`, which is already
   the server default, so the user may not need to override effort.

5. **Selector scope: per-request or persisted?** The main form persists `model_plan` to
   `localStorage`. The picker could either read that persisted value (coupling them) or keep
   its own stored preference.

6. **i18n label for picker model selector.** Labels `"params.model_plan_label"` (English:
   `"Planner model"`) and `"params.model_default_option"` (English: `"Default"`) already
   exist in
   [`web/src/i18n/messages.ts`](https://github.com/paulpengtw/exam-generation/blob/689784739c9eb77ed522e8c0114ca6961670314d/web/src/i18n/messages.ts).
   They are reusable if a dropdown is added to `CoreQuestionPicker`.

7. **Does the auto-planner (confirmation flow, line 1990 in `ParamForm.tsx`) need the same
   default?** It runs without user interaction, so if a component-level default is chosen,
   the implementer must decide whether the confirmation-flow call should also use Gemini.
