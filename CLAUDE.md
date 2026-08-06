# CLAUDE.md

## Project Overview

This is a CLI-based exam question generator for Taiwan math (default: grades 7-9, 第四學習階段), 108課綱 社會領域 (歷史/地理/公民與社會/跨科), and 108課綱 自然科學 (PISA-style scientific literacy framing). Math target 學習階段 and grade list are configurable in `question_schemas.json`. It uses LLMs via OpenAI-compatible endpoints to generate structured exam questions with optional chart/image output.

## Architecture Decisions

### No RAG
All curriculum data (學習內容.json, 學習表現.json) is injected directly into the LLM context. The full grades 1-12 curriculum is provided so the model can calibrate difficulty — understanding what students already know (grades 1-6) and what lies ahead (grades 10-12).

### Script-side randomness
The Python code handles all random selection (grade, 情境, 題型種類, 題型, 數學思考, 學習內容, 學習表現, 核心素養, 題目內容類型, subject_filter, question style; social-studies parent items are fixed as 題組題, can receive web/API per-小題 `question_type`, `instruction`, `learning_content`, and `learning_performance` constraints — empty per-小題 LC/LP fields fall back to the global sampled pool; explicit per-小題 LC/LP selections are injected into that 子題's prompt with a hard must-use instruction and are forced verbatim into the output SubQuestion (overriding the LLM's choice) — sample blank question types per 小題, and persist instructions as `subquestions[*].出題指示`; natural sciences also adds 情境子類別, 科學能力, and (parallel to social studies) per-小題 SubQuestionConfig support with sub_question_count, subquestion_configs, question_word_limit, option_word_limit — blank 題型 slots are filled from the PISA-Science 題型 pool). After each 子題產生器 response is parsed, `科目` is a 強制值: 社會領域 uses the sampled `params.科目`, while 自然科學 always uses `自然科學`, overriding any conflicting LLM value. An explicitly supplied 情境子類別 is 釘選: if 情境 is omitted its parent constrains the 情境 draw, while an explicitly incompatible 情境/情境子類別 pair is rejected during request validation. The LLM receives deterministic instructions — it does not choose these parameters itself.

### Batch-level prompt dedup (issue #111)

When a batch generates `count > 1` questions, each subject's batch loop accumulates a `list[PriorScope]` of already-accepted siblings (`{核心問題 | 出題概念, 學習內容 codes}`) and passes it to the next question's user prompt via a new optional `prior_scopes` keyword on `build_user_prompt` (math) / `build_text_user_prompt` (社會/自然). The LLM sees a short `## 已生成題目（請避免相似範圍）` block listing up to the 10 most recent siblings so it varies angle/題材 even when learning-content codes overlap. Empty list → section omitted → count=1 prompts are byte-identical to today. Extractor helpers and formatter live in `src/common/batch_dedup.py`. The server's `generate_question_stream` shares one `threading.Lock`-guarded list across concurrent workers — best-effort dedup consistent with the concurrent worker design. Embedding-similarity retry (Phase 2) is out of scope.

### Web confirmation dialog pre-draw
The web form always shows both 學習內容 and 學習表現 in the confirmation step before submission. If the user made no manual selection, the frontend pre-draws a random subset (1–3 items for 學習內容, 1–2 for 學習表現) from the available pool before displaying the confirmation screen. This happens regardless of 出題模式: 出題模式 never suppresses or alters the 預抽. What is shown is exactly what will be sent to the backend — no further randomness happens on the backend for those fields when they are present.

For 社會領域 and 自然科學 requests that specify `sub_question_count`, the
frontend also pre-draws per-小題 學習內容 (1–3) and 學習表現 (1–2) from
the currently-active global pool whenever a 子題's per-小題 selection is
empty. The drawn codes appear in the confirmation screen under a
"各小題配置" section (one card per 小題) and are sent to the backend as
`subquestion_configs[*].learning_content` / `learning_performance`.
Explicit per-小題 selections are preserved verbatim and never
overwritten. Empty global pools disable per-小題 auto-draw for that
field, in which case the backend's `or global pool` prompt-build
fallback still applies at generation time.

數學也 exposes request-level `sub_question_count` and the 題組文本
`text_word_limit` in the web form. Its 發送前確認 shows those canonical
top-level values, but it does not pre-draw or submit `subquestion_configs`.

### 出題模式 is a prompt-level hint

`coverage_mode` remains an accepted request parameter but affects no mechanical draw. For 均衡 with `count > 1`, each question's 文本生成器 user prompt gains one `## 出題模式：均衡` instruction asking the model to spread 題型 and 取材角度 across the batch and avoid scopes listed in the `已生成題目` block from issue #111. 隨機 injects nothing, and `count = 1` prompts remain byte-identical. Response metadata reports the requested mode as `coverage_mode_used`.

### Verify + correct loop
1. First call (execute model): generates the question and solution. **For math without `sub_question_count`,** this remains one call producing the full flat question. **For math with `sub_question_count`,** the shared core runs a **文本生成器** call for the shared 核心問題/文本/取材來源 and an N-entry 小題 plan, then N concurrent **子題產生器** calls each write one complete 小題. **For social studies and natural sciences,** this is also a two-stage pipeline: a **文本生成器** call produces the shared 核心問題/文本/取材來源 plus an N-entry 子題 plan, then N concurrent **子題產生器** calls each write one complete 子題 (via `ThreadPoolExecutor`, capped by `SUBGEN_MAX_CONCURRENCY`, default 6; failed/unparseable 子題 calls get up to `SUBGEN_RETRIES` fresh retries, default 1, before the slot is dropped); the assembled 題組 then enters the verify/correct loop.
2. Chart/image specs are rendered to PNG before verification so the verifier can see them. Math and natural sciences render top-level `chart_spec`; social studies also renders `subquestions[*].chart_spec` to per-小題 PNGs.
3. Second call (execute model, multimodal): independently solves the question, inspects PNG, returns `VerificationResult` with `passed`, `answer_match`, `details`, `my_answer`, `provided_answer`, and optional `chart_verification`.
4. If `passed=False`, a correction pass sends the failed question + verifier feedback back to the execute model for a minimal targeted fix (`src/corrector.py`). PNG re-renders only when `chart_spec` actually changes. Re-verify and loop up to `max_retries` (default 3, via `LLM_MAX_RETRIES` / `--max-retries`).

### Fact-check pass (social studies only)

Optional web-search fact-check runs after the teacher verify pass for
時事-flagged social-studies questions (issue #104). Enable by setting
`WEB_SEARCH_PROVIDER=anthropic`, `gemini`, or `none` (default `none` — opt-in)
and optionally `WEB_SEARCH_MAX_USES=N` (default `5`). The gate is keyed to the
effective 驗證模型 (`model_verify` or, when empty, `model_execute`); the
configured provider must match that model's provider or the pass is skipped.
Anthropic uses its native `web_search_20250305` server tool, while Gemini uses
Google grounding through its OpenAI-compatible endpoint. The fact-check call
uses the 驗證 tier because `fact_check` belongs to `_VERIFY_PURPOSES`, and
therefore also uses `effort_verify` (falling back to `effort_execute`). When
enabled, `src/social_studies/verifier.py::verify_question` calls
`src/social_studies/fact_check.py::fact_check_question` only when
`is_current_events(question)` is True (heuristic: any subquestion's 學習內容
編碼 starts with `公`, or `核心問題`/`文本` matches `近年|最近|今年|去年|本屆|
現任|當前`). A definitive negative (`fact_check.verified is False`) forces
`passed=False` and appends issues to `details` so the existing correction
loop sees them. Any failure — provider disabled, provider/model mismatch,
endpoint rejection, malformed JSON, or exhausted iterations — fails open:
`fact_check=None` and the teacher verdict is unchanged.

### 自然科學 measures Reporting Scale, not 難度
自然科學 uses Reporting Scale — the PISA Science proficiency scale (levels 1c, 1b, 1a, 2, 3, 4, 5, 6) — as its per-小題 demand signal. 數學 and 社會領域 use 難度 (easy / medium / hard). The two signals never overlap across subjects.

**Precedence for 自然科學:** an explicit per-小題 Reporting Scale overrides the 題組-level value; when neither is set, the slot draws independently at random. The 題組-level value is only a default-filler and is absent when the user leaves the field 隨機.

**What each prompt stage receives:**
- 文本生成器 user prompt — the 題組-level target stated with its single PISA level descriptor verbatim in English (## 目標報告等級 block, only when a 題組-level value is set), plus the resolved per-小題 levels in the 各小題配置 block. The eight-level calibration reference is deliberately NOT included here (~8.5K chars; the planner needs its target, not the whole scale).
- 子題產生器 user prompt — the full eight-level PISA calibration reference verbatim plus the 小題's own target level, so the model writes to one specific level with the whole scale for calibration.
- Verifier — receives neither 難度 nor Reporting Scale; it concentrates on answer correctness and 課綱代碼 validity.
- Corrector — level assignment is frozen through all correction retries; the corrector may not alter it.

**Output:** resolved per-小題 levels are recorded in `metadata.reporting_scales` in 序號 order; slots that were dropped or unresolved leave no entry.

### LLM provider is selected per-request from the model id

`resolve_provider(model)` in `src/llm_client.py` maps each call to a provider at call time: `gemini-*` → Gemini via its OpenAI-compatible endpoint (OpenAI SDK, `GEMINI_API_KEY` / `GEMINI_BASE_URL`); `gpt-*/o-series` → OpenAI SDK (`OPENAI_API_KEY` / `OPENAI_BASE_URL`); `claude-*` → Anthropic SDK (prompt caching, streaming, `system` param, `LLM_API_KEY` / `LLM_BASE_URL`); unknown ids → Anthropic (proxy deployments). The code default is `claude-sonnet-4-6` for planning, generation, and verification (`model_plan` and `model_execute`); it now heads the built-in `_DEFAULT_MODELS_ALLOWED` roster. Effort translation: Anthropic uses `extra_body.output_config.effort`; Gemini/OpenAI use `reasoning_effort` (low/medium/high only — other values are dropped with a one-time WARNING). Temperature is withheld from `gemini-3.x`, `gpt-5.x`, and o-series models. OpenAI provider gets `max_completion_tokens` instead of `max_tokens`. A missing provider key returns HTTP 422 naming the env var. Fact-check is provider-general: Anthropic uses `web_search_20250305` and Gemini uses Google grounding; `fact_check_question` silently returns `None` (fail-open) when `WEB_SEARCH_PROVIDER` is disabled or does not match the effective 驗證模型 (`model_verify` or `model_execute`). The call itself resolves through the 驗證 tier and uses `effort_verify`. Image generation (IMAGE\_API\_KEY / IMAGE\_BASE\_URL / IMAGE\_MODEL, `gpt-image2`) is unchanged — Gemini image generation is future work. Known gaps: #338 (UI effort fields dropped before reaching server), #346 (planner purpose string never matches `"plan"` so plan calls get `effort_execute`).

### Web-ready design
All core modules (`sampler`, `context_builder`, `llm_client`, `verifier`, `renderer`) are standalone importable components. The CLI (`cli.py`) is a thin wrapper. Config comes from env vars. This allows future integration with FastAPI/Flask without refactoring.

### Shared loaders, three subject pipelines
Math (`src/*.py`), social studies (`src/social_studies/*.py`), and natural sciences (`src/natural_sciences/*.py`) are three parallel question-generation pipelines that share their curriculum-loading core. The subject-agnostic loaders live in `src/common/`: Social studies and natural sciences `generate_one` now run a **文本生成器 → N parallel 子題產生器** pipeline; math's `generate_one` keeps its original single-call structure when `sub_question_count` is absent and uses the shared **文本生成器 → N 子題產生器** core when it is present.

- `src/common/curriculum_loader.py` — JSON loaders + `allowed_learning_content` / `allowed_learning_performance` filters, parameterized by `data_dir` and a `subject_to_prefixes` map.
- `src/common/core_competency_loader.py` — JSON loader + `build_core_competency_enum` + `allowed_competencies(stage)`.
- `src/common/planner.py` — subject-agnostic 核心問題 generator; callers pass their own system/user prompt templates.

Each subject package wraps these with its own data directory and prefix map:

- **Math** uses `data/math/curriculum/` and `_MATH_SUBJECT_TO_PREFIXES` (in `src/sampler.py`): 數與量={N,n}, 代數={A,F,R,a,f,r}, 幾何={S,G,s,g}, 統計與機率={D,P,d,p}, 跨領域=all. Subject prompts live in `src/planner.py` (數學領域命題教師).
- **Social studies** uses `data/social_studies/curriculum/` and `_SUBJECT_TO_PREFIXES` (in `src/social_studies/curriculum_loader.py`). The `src/social_studies/{curriculum_loader, core_competency_loader, planner}.py` modules are thin shims over `src.common.*`.
- **Natural sciences** uses `data/natural_sciences/curriculum/`, subject_prefix `"自"` (in `src/natural_sciences/core_competency_loader.py`). Unlike the other two subjects, natural sciences has **no per-subject bucketing** — `科目` is fixed as `"自然科學"` on all subquestions, and `src/natural_sciences/curriculum_loader.py` overrides `allowed_learning_content` / `allowed_learning_performance` to skip the subject filter entirely. Subject prompts live in `src/natural_sciences/planner.py` (PISA-Science scientific literacy template). The `src/natural_sciences/{curriculum_loader, core_competency_loader, planner}.py` modules are thin shims over `src.common.*`.

Math keeps its byte-identical single-call flat output when `sub_question_count` is absent. When `sub_question_count` is present, it pins `題型種類=題組題` and opts into the shared `src/common/generation_core.py` **文本生成器 → N 子題產生器** pipeline; the shared core truncates or pads the plan so exactly the requested number of 小題 is generated. Social studies and natural sciences both use a 題組 structure with `subquestions[]` and rubric entries. Social-studies parent items are fixed as 題組題; social studies keeps `閱讀歷程` and `文本形式` (PISA reading literacy axes), supports mixed `subquestions[*].題型`, and can inject per-小題 題型, 出題指示, count/word-limit/content/image constraints from the web/API. Natural sciences replaces `核心素養` with `科學能力` (6 entries: 能力一/二/三 + 環境能力一/二/三) and adds `情境子類別` (a PISA sub-context parented to the top-level 情境). Natural sciences now also supports per-小題 SubQuestionConfig (question_type, instruction, LC/LP overrides, word limits, content_type, image_generation_mode) and sub_question_count — parallel to social studies. The natural sciences verifier uses the lenient "寬鬆通過、只攔重大問題" stance, distinct from math's strict "明確錯誤" stance.

PISA-style tags (`閱讀歷程`, `文本形式`) are retained on social studies as secondary diversity axes to influence question design, but the primary framing is 108課綱, not PISA reading literacy.

Schema, curriculum, and few-shot data are **CSV-driven** for schema/few-shot; **JSON-driven** for curriculum. Files under `data/social_studies/` read at runtime:

| File | Purpose |
|---|---|
| `curriculum/schema_meta.csv` | 學習階段 label + grades list |
| `curriculum/schema_parameters.csv` | Allowed values + instructions for all 6 question parameter categories (includes 科目: 歷史/地理/公民與社會/跨科) |
| `curriculum/learning_performance.json` | 108課綱 社會領域 學習表現標準 (26 codes; ODT-sourced) → system prompt + sampler pool |
| `curriculum/learning_content.json` | 108課綱 社會領域 學習內容 (472 entries; ODT-sourced `對應學習表現`) → system prompt + sampler pool |
| `few_shot/few_shot_examples.csv` | Few-shot examples (long format, grouped by `範例編號`; one row per subquestion; includes mixed `小題題型` groups covering 選擇題 / 封閉式建構反應題 / 開放式建構反應題) |

CSVs are `utf-8-sig` (Excel BOM-tolerant); multi-value fields use `;` as separator. `範例_`-prefixed files in the same folders are reference examples for researchers — they are never loaded by the system. See `data/social_studies/csv_填寫指南.md` for the field-by-field filler guide.

**Sampler 科目 filter:** `_SUBJECT_TO_PREFIXES` in `curriculum_loader.py` maps each subject to its 科目 set. All subjects include `"社"` so the 16 cross-subject general 學習表現 codes (社1a/1b/2a/2b/2c/3a/3b/3c/3d-Ⅳ-*) are in every subject's pool — not only 跨科. This is per 108課綱 design where 社_* codes apply across all 社會領域 subjects. All subjects also include the empty-string `""` bucket so the 57 shared 學習內容 entries with `科目=""` appear in every subject's draw pool (parallel to the `社` bucket for 學習表現).

### Natural sciences curriculum data
`data/natural_sciences/curriculum/` contains 108課綱 自然科學領域 curriculum assets. The JSON files are generated from the canonical source `converted/課綱各項指標列表.xlsx` via `python3 scripts/build_natural_sciences_curriculum.py`. The CSV files are researcher-editable, mirroring the social-studies layout.

| File | Purpose |
|---|---|
| `curriculum/schema_meta.csv` | 學習階段 label + grades list (runtime-editable) |
| `curriculum/schema_parameters.csv` | Parameter values + instructions for 情境, 情境子類別, 題型種類, 題型, 科學能力, 題目內容類型. 情境子類別 rows carry a `parent` column linking each sub-context to its parent 情境 value. |
| `curriculum/learning_content.json` | Top-level `學習階段_to_grades`, `跨科概念` taxonomy (48 entries), and `學習內容` (757 entries). |
| `curriculum/learning_performance.json` | `學習表現` standards (99 entries) plus `學習階段_to_grades`. |
| `curriculum/core_competencies.json` | 自然科學領域 核心素養 (9 entries). |

Natural-sciences JSON shapes:

- `跨科概念`: `課題`, `跨科概念`, `主題`, `次主題`.
- `學習內容`: `value`, `學習階段`, `科目`, `條目說明`, `備註`, `對應學習表現`.
- `學習表現`: `value`, `學習階段`, `科目`, `構面`, `項目`, `說明`, `對應學習內容`.

Stage mapping is shared across the two files: 第二學習階段 grades 3-4, 第三 5-6, 第四 7-9, 第五 10-12. High-school 學習內容 uses `科目` buckets `生物`, `物理`, `化學`, `地球科學`; earlier-stage shared rows use `科目=""`.

**Sampler 科目 filter:** Natural sciences deliberately does NOT bucket by 科目 (生物/物理/化學/地球科學) at the sampler level, unlike social studies. `科目` is fixed at `"自然科學"` on every subquestion. `src/natural_sciences/curriculum_loader.py` overrides `allowed_learning_content` / `allowed_learning_performance` to omit the subject parameter and return the full stage pool.

Few-shot examples live under `data/natural_sciences/few_shot/` in one folder per 題型:

| Folder | 題型 |
|---|---|
| `Simple-multiple-choice/` | PISA 單選 |
| `Complex-multiple-choice/` | PISA 複選 |
| `Constructed-response/` | PISA 建構反應題 |

Each folder accepts `*.json` files (flat pool, parallel to math's `data/few_shot/{style}/`) or a `few_shot_examples.csv` (parallel to social studies). The repo ships a pool of JSON examples across these folders (count it with `ls data/natural_sciences/few_shot/*/*.json | wc -l`). The data loader (`src/natural_sciences/data_loader.py`) falls back to scanning all subdirectories when `q_type` is unknown.

## Key Files

| File | Purpose |
|---|---|
| `data/curriculum/學習內容.json` | Full K-12 math curriculum content, 14 grade levels (legacy source for `data_loader.py`) |
| `data/curriculum/學習表現.json` | Math learning performance standards by stage (legacy source) |
| `data/math/curriculum/learning_content.json` | Reshaped math 學習內容 (288 entries across 5 學習階段; row shape `{value, 學習階段, 科目, 條目說明, 對應學習表現}`; `科目` is a single-letter strand prefix N/A/F/R/S/G/D/P). Loaded via `src.common.curriculum_loader`. |
| `data/math/curriculum/learning_performance.json` | Reshaped math 學習表現 (131 entries; row shape `{value, 學習階段, 科目, 說明}`). Loaded via `src.common.curriculum_loader`. |
| `data/math/curriculum/core_competencies.json` | 108課綱 數學領域 核心素養 (27 codes 數-E/J/U-A1..C3, synthesized from social studies' template with `值` rewritten from 社- to 數-). |
| `data/math/curriculum/learning_performance_intro.md` | Math 學習表現 framework intro → injected into system prompt. |
| `scripts/build_math_curriculum.py` | Reproducible builder: emits the four `data/math/curriculum/` files from `data/curriculum/{學習內容,學習表現}.json` + the social studies core_competencies template. |
| `src/common/curriculum_loader.py` | Subject-agnostic JSON loaders + `allowed_learning_content/performance(data, stage, *, subject, subject_to_prefixes)` filters. |
| `src/common/core_competency_loader.py` | Subject-agnostic 核心素養 loader + `build_core_competency_enum` + `allowed_competencies(data, stage)`. |
| `src/common/planner.py` | Subject-agnostic `plan_core_questions()`; callers pass their own system/user prompt templates. |
| `src/planner.py` | Math planner shim — wraps `src.common.planner.plan_core_questions` with a 資深108課綱數學領域命題教師 system prompt asking for 3 candidate 核心問題 covering 代數 / 幾何 / 統計三大面向. |
| `data/few_shot/` | Math few-shot examples by question style |
| `data/example_exams/` | Past national exam PDFs (112-114) for reference |
| `question_schemas.json` | Math user-editable config: `"學習階段"` (string), `"grades"` (int array), and all 5 question parameter categories using `[{value, instruction}]` objects. Non-empty `instruction` fields are injected into the LLM prompt. |
| `src/schema_loader.py` | Loads `question_schemas.json`, exposes `load_grades()` / `load_learning_stage()`, builds dynamic str-enums via `build_enums()`, and builds `{category: {value: instruction}}` lookup via `build_instructions()` |
| `data/social_studies/curriculum/schema_meta.csv` | Social studies 學習階段 + grades (runtime-editable) |
| `data/social_studies/curriculum/schema_parameters.csv` | Social studies parameter values + instructions (6 categories) |
| `data/social_studies/curriculum/learning_performance.json` | Social studies 學習表現標準 JSON (26 codes; 科目/構面/項目 metadata + bidirectional `對應學習內容` field populated from ODT 呼應表) → system prompt + sampler pool |
| `data/social_studies/curriculum/learning_performance_intro.md` | Official NAER 學習表現 framework chapter (構面/項目/編碼規則 + full 條目) → system prompt `### 學習表現架構說明` |
| `data/social_studies/curriculum/learning_content.json` | Social studies 學習內容 JSON (472 entries spanning 學習階段 二/三/四/五; `對應學習表現` populated from ODT 呼應表 — 55 entries mapped at 第四學習階段) → system prompt + sampler pool |
| `scripts/connect_curriculum_from_odt.py` | One-shot importer: reads the official 社會領域學習重點與核心素養呼應表 (ODT) and overwrites `對應學習表現` in `learning_content.json` and `對應學習內容` in `learning_performance.json`; also appends any perf codes referenced in the ODT but missing from the JSON. Re-run if NAER publishes an updated 呼應表. |
| `data/natural_sciences/curriculum/learning_content.json` | Natural sciences 學習內容 JSON (757 entries) plus top-level `跨科概念` taxonomy (48 entries), generated from the canonical converted workbook. |
| `data/natural_sciences/curriculum/learning_performance.json` | Natural sciences 學習表現 JSON (99 entries; stages 二/三/四/五). |
| `scripts/build_natural_sciences_curriculum.py` | Rebuilds natural-sciences `learning_content.json`, `learning_performance.json`, and `core_competencies.json` from `converted/課綱各項指標列表.xlsx`. |
| `data/social_studies/few_shot/few_shot_examples.csv` | Social studies few-shot examples (long format grouped by 範例編號; one row per subquestion with all 108課綱 metadata columns; checked-in examples demonstrate mixed per-小題 題型) |
| `data/social_studies/csv_填寫指南.md` | zh-TW filler guide: field-by-field explanation of JSON + CSV files |
| `src/social_studies/schema_loader.py` | Builds social-studies schema dict from `schema_meta.csv` + `schema_parameters.csv` |
| `src/social_studies/curriculum_loader.py` | Thin shim over `src.common.curriculum_loader`. Owns `_SUBJECT_TO_PREFIXES` (歷史/地理/公民與社會/跨科, all include `"社"` and `""`) and the `data/social_studies/curriculum/` default path. Adds `*_instructions` / `load_performance_intro` helpers on top of the shared loader. |
| `data/social_studies/curriculum/core_competencies.json` | 108課綱 社會領域 核心素養 codes → sampler pool; loaded via `src.common.core_competency_loader` through the shim. |
| `src/social_studies/core_competency_loader.py` | Thin shim over `src.common.core_competency_loader`; adds `allowed_core_competencies(data, stage, subject)` for 核心素養 sampler pool. |
| `src/social_studies/planner.py` | Thin shim over `src.common.planner.plan_core_questions`; provides the 社會領域 system/user templates. |
| `src/social_studies/data_loader.py` | Loads CSV few-shot examples (learning content/performance now via `curriculum_loader`) |
| `src/social_studies/context_builder.py` | Social studies prompt assembly; `## 課程綱要參考` block injected into system prompt; renders `## 各小題配置` when web/API per-小題 constraints are provided; adds `build_text_system/user_prompt` (文本生成器 stage) and `build_subquestion_system/user_prompt` (per-子題 stage); `build_text_user_prompt` and `build_subquestion_user_prompt` accept `disable_reference_fewshot: bool = False`; original `build_system/user_prompt` retained for correction passes; `build_subquestion_user_prompt` accepts an optional `cfg: SubQuestionConfig` for per-slot LC/LP; explicit codes use hard "不得替換或新增" wording; public `LC_INSTRUCTIONS`/`LP_INSTRUCTIONS` aliases exported. |
| `src/social_studies/sampler.py` | Picks grade, 科目, per-小題 題型, 學習內容_pool, 學習表現_pool, 核心素養, per-小題 configs. Per-小題 SubQuestionConfig.learning_content/performance are preserved as the raw user selection (not pre-merged with the global pool); fallback to the global pool happens at prompt-build time. |
| `src/social_studies/schemas.py` | Social studies Pydantic models: `ExamQuestion`, `SubQuestion`, `SubQuestionConfig`, `LearningContentRef`, `RubricEntry`, `QuestionSubject` (歷史/地理/公民與社會/跨科), `VerificationResult`, `ImageSpec`. `SubQuestionConfig` includes optional per-小題 `question_type`, `instruction`, `learning_content: list[str]`, `learning_performance: list[str]` (empty = global pool fallback), content/image mode, and word-limit controls; `SubQuestion` includes optional persisted `出題指示`, per-小題 `題目內容類型`, `image_generation_mode`, `圖片`, and `chart_spec`. |
| `src/natural_sciences/cli.py` | CLI entry point (no `--subject` flag; adds `--science-competency` and `--sub-context`; 題型 choices: Simple/Complex-multiple-choice/Constructed-response); `generate_one` runs 文本生成器 → N parallel 子題產生器 stages via `ThreadPoolExecutor`; helpers `_parse_text_shell` / `_parse_subquestion`; optional `sub_client_factory` for test injection |
| `src/social_studies/cli.py` | CLI entry point for 108課綱 社會領域 generation; `generate_one` runs 文本生成器 → N parallel 子題產生器 stages via `ThreadPoolExecutor`; helpers `_parse_text_shell` / `_parse_subquestion`; optional `sub_client_factory` for test injection |
| `src/natural_sciences/schema_loader.py` | Builds schema dict from `schema_meta.csv` + `schema_parameters.csv`; handles `parent` column on `情境子類別` rows to build the parent-child map used by the sampler |
| `src/natural_sciences/curriculum_loader.py` | Thin shim over `src.common.curriculum_loader`; overrides `allowed_learning_content` / `allowed_learning_performance` to skip subject filtering (科目 is fixed as 自然科學). Owns `grade_to_learning_stage` (grades 3-12 → 學習階段 二/三/四/五; NS has no 第一 stage) and `relevant_cross_concepts` (narrows the 48-entry 跨科概念 taxonomy to the concept groups matching 學習內容-code prefixes; full-taxonomy fallback on empty/unknown codes) |
| `src/natural_sciences/core_competency_loader.py` | Thin shim over `src.common.core_competency_loader`; `NaturalCoreCompetency` enum, subject_prefix `"自"` |
| `src/natural_sciences/planner.py` | Thin shim over `src.common.planner.plan_core_questions`; PISA-Science prompt template (自然科學領域命題教師) |
| `src/natural_sciences/sampler.py` | PISA-Science sampler: picks grade (學習階段 derived per-question via `grade_to_learning_stage`, so grades 10-12 draw 第五學習階段 pools), 情境 + 情境子類別 (parent-child constrained), 題型, 科學能力 (1–2 of 6: 能力一/二/三 + 環境能力一/二/三), 學習表現 (1–2), 學習內容 (1–3 preferentially derived from chosen 學習表現 via `對應學習內容`). No 科目 buckets. Accepts sub_question_count (3-7), question_word_limit, option_word_limit, subquestion_configs — resolves per-小題 SubQuestionConfig rows with random q_type fill (parallel to social studies); per-小題 LC/LP are preserved as raw user selections and not pre-filled with the global pool. |
| `src/natural_sciences/schemas.py` | Pydantic models: `ExamQuestion` (subquestions[], 科學能力, 情境子類別, no 核心素養 at top level), `SubQuestion` (科學能力 replaces 社會領域 核心素養; 科目 fixed as 自然科學), `ScienceCompetency` (6-member enum), `QuestionSubContext`. No `QuestionSubject` enum. Now includes `SubQuestionConfig` (per-小題 overrides: question_type/instruction/content_type/image_generation_mode/word limits/LC/LP) and `出題指示` on `SubQuestion` — parallel to social studies. |
| `src/natural_sciences/data_loader.py` | Hybrid few-shot loader: scans `data/natural_sciences/few_shot/{q_type}/` for `*.json` and optional `few_shot_examples.csv`; falls back to all subdirs when q_type unknown. Example count is not pinned here — see `data/natural_sciences/few_shot/`. |
| `src/natural_sciences/context_builder.py` | PISA-Science prompt assembly; `curriculum_texts(learning_stage, lc_codes)` builds the `## 課程綱要參考` block (學習內容 + 學習表現 filtered to the grade-derived 學習階段; 跨科概念 narrowed to the sampled codes' concept groups with full-taxonomy fallback), injected into the system prompt; adds `build_text_system/user_prompt` and `build_subquestion_system/user_prompt` for the two-stage pipeline; `build_text_user_prompt` and `build_subquestion_user_prompt` accept `disable_reference_fewshot: bool = False`; original builders retained; `build_subquestion_user_prompt` accepts an optional `cfg: SubQuestionConfig` for per-slot LC/LP; explicit codes use hard "不得替換或新增" wording; public `LC_INSTRUCTIONS`/`LP_INSTRUCTIONS` aliases exported. |
| `src/natural_sciences/curriculum_codes.py` | Deterministic 學習內容/學習表現 code validation (issue #92): normalized lookup over the NS curriculum JSON (Unicode Ⅰ–Ⅴ ↔ ASCII roman-numeral spellings), `canonical_lc/lp`, `repair_lc/lp_refs` (canonicalize valid codes, drop unknown, fall back to the sampled pool), `validate_question_codes`. Parse-time repair runs in `cli.py` `_parse_subquestion`/`_parse_question` (cfg-pinned per-小題 codes stay verbatim); the verifier appends `[課綱代碼檢核]` issues to details and forces `passed=False` on unknown/missing codes; the corrector keeps its metadata freeze but canonicalizes codes on LLM-added subquestions. |
| `src/natural_sciences/verifier.py` | Explicit "寬鬆通過、只攔重大問題" stance — more lenient than math's "明確錯誤"; otherwise parallel architecture (multimodal when chart PNG present) Deterministic `[課綱代碼檢核]` check (issue #92) rejects unknown/missing 學習內容/學習表現 codes regardless of the LLM verdict.  |
| `src/natural_sciences/corrector.py` | Frozen fields: `學習內容/學習表現/科學能力/出題概念/科目/年級`; minimal targeted correction (parallel to social studies corrector) |
| `data/natural_sciences/curriculum/schema_meta.csv` | Natural sciences 學習階段 + grades (runtime-editable) |
| `data/natural_sciences/curriculum/schema_parameters.csv` | Natural sciences parameter values + instructions (情境/情境子類別/題型/科學能力/題目內容類型; `parent` column on 情境子類別) |
| `src/schemas.py` | Math Pydantic models (enums loaded dynamically from `question_schemas.json` at import time). `ExamQuestion` has optional 核心素養 (list[str]), 學習表現 (list[LearningContentItem]), 題目內容類型 (str \| None), 出題概念 (str). `SampledParams` mirrors these plus `subject_filter`. New enums: `CoreCompetency` (27 數-E/J/U-A1..C3 codes built via `src.common.core_competency_loader.build_core_competency_enum`) and `QuestionSubject` (數與量/代數/幾何/統計與機率/跨領域). `ImageSpec` describes the image; `ChartVerificationResult` is nested in `VerificationResult`. |
| `src/sampler.py` | Curriculum-aware math sampler. Loads `data/math/curriculum/` via `src.common.*`. Owns `_MATH_SUBJECT_TO_PREFIXES` (科目→prefix-letter map) and `grade_to_learning_stage(grade)` helper. Samples 核心素養 (1–3), 學習表現 (1–3), 題目內容類型 (1 of 純文字 / 含圖片 / graphs/charts/tables / customized), and optional `subject_filter` alongside the existing 情境/題型種類/題型/數學思考/學習內容/style draws. |
| `src/context_builder.py` | Math prompt assembly. Injects curriculum context (`## 課程綱要參考`) into the system prompt — same pattern as social studies. `build_user_prompt` accepts `user_topic`, `user_passage`, `user_options`, `user_core_question` overrides and returns `(prompt, few_shot_images)`. `CONTENT_TYPE_INSTRUCTIONS` maps the 4 題目內容類型 values to per-prompt instructions. |
| `src/llm_client.py` | OpenAI-compatible API client with model routing; `generate_with_image()` for multimodal (text + PNG) calls; `generate_json(..., agent_override=str)` stamps per-子題 agent ids (`sub_generator#i`) on all streamed events; `emit_stage(obs, agent, stage, status)` emits stage-lifecycle events |
| `src/verifier.py` | Independent answer verification pass |
| `src/corrector.py` | Minimal targeted correction pass for failed-verification questions |
| `src/renderer.py` | matplotlib PNG generation for statistical charts (`render_mode: "chart"`) |
| `src/html_renderer.py` | Playwright HTML→PNG renderer (`render_mode: "html"`) |
| `IMPLEMENTATION_PLAN.md` | Planned refactors and known tech debt |
| `FLOW.md` | ASCII tree of web Generate request lifecycle (frontend click → SSE → queue → worker → result) |
| `LOGIC.md` | Full waterfall execution trace with file + line references |
| `src/data_loader.py` | Curriculum data loading + grade filtering (legacy `data/curriculum/*.json` paths) and the CSV-driven few-shot loader with image-manifest support (`data/few_shot/few_shot_examples.csv` + `images/<id>/manifest.json`), with fallback to per-style JSON. No rubric parsing (math has no 評分規準). |
| `src/verifier.py` (math) | Independent answer verification pass. Module-level `_CURRICULUM_PREFIX` (~93 KB curriculum context) mirrors social studies. Keeps math's stricter "明確錯誤" verification stance — NOT loosened to social studies' "寬鬆通過". |
| `src/corrector.py` (math) | Targeted correction pass. Frozen-fields list extended with 核心素養, 學習內容, 學習表現, 出題概念, 題目內容類型 (alongside existing 情境/題型種類/題型/數學思考). |
| `server/generate/routes.py` `/api/plan-core-questions` | Branches on `body.subject` (`"math"` \| `"social_studies"` \| `"natural_sciences"`, default `"social_studies"`). Math derives `learning_stage` from `body.grade` via `src.sampler.grade_to_learning_stage`. Natural sciences uses `src.natural_sciences.planner.plan_core_questions`. |
| `server/generate/exchange_recorder.py` | `ExchangeRecorder` observer — buffers `llm_request` events per-agent and writes one `LLMExchange` row on the matching `llm_response`. Thread-safe (parallel `sub_generator#i` workers share one recorder). Persistence failures log a warning and never raise. |
| `server/models.py` `LLMExchange` | New table `llm_exchanges` (FK → `generation_logs.id`, indexed). Columns: `id`, `generation_log_id`, `exchange_order`, `agent`, `purpose`, `request_body`, `response_body`, `model_used`, `prompt_tokens`, `completion_tokens`, `created_at`. |
| `server/generate/routes.py` `/api/generation-logs/{id}/exchanges` | Auth-guarded GET; returns the LLM exchanges owned by the caller, ordered by `exchange_order`. Returns 404 for other users' logs (existence-hiding). |
| `server/app.py` `prune_expired_llm_exchanges` | Startup helper that deletes `llm_exchanges` rows older than `LLM_EXCHANGE_RETENTION_DAYS` (default 30). `0` disables persistence entirely — the recorder is not attached at request time and pruning is skipped. |
| `server/generate/models.py` `GenerateParams` | Accepts all three subjects. NS-specific fields: `sub_context: str \| None`, `science_competency: list[str] \| None`. Per-小題 fields (social studies and natural sciences): `sub_question_count` (3-7), `question_word_limit`, `option_word_limit`, and `subquestion_configs` JSON string; each row may include `question_type`, `instruction`, `learning_content`, and `learning_performance` (empty lists fall back to the global sampled pool), with blank question types sampled per 小題 (PISA-Science pool for NS). `disable_reference_fewshot: bool = False` (SS/NS only; when true, skips `load_few_shot_example_groups` in both 文本生成器 and 子題產生器 stages and falls back to the 暫無範例 string). `subject` is plain `str` (accepts `"natural_sciences"`). `PlanCoreQuestionsRequest.subject` is `Literal["math", "social_studies", "natural_sciences"]`. |
| `server/utility/routes.py` `/api/schemas?subject=...` | `subject=math` augments base math schema with `科目` (4 strands), `題目內容類型` (4 entries), and `學習表現` filtered by 學習階段. `subject=natural_sciences` builds schema from `schema_parameters.csv` + curriculum JSON (PISA-Science dimensions: 情境/情境子類別/科學能力/題型/題目內容類型 with 學習表現 and 學習內容 pools). |
| `server/config.py` `ServerConfig.math_curriculum_dir` | Env `MATH_CURRICULUM_DIR`, parallel to `social_studies_curriculum_dir`. `natural_sciences_curriculum_dir` env `NATURAL_SCIENCES_CURRICULUM_DIR` added alongside. |
| `src/config.py` | Environment variable configuration; `subgen_max_concurrency` (env `SUBGEN_MAX_CONCURRENCY`, default 6) caps parallel 子題產生器 calls; `subgen_retries` (env `SUBGEN_RETRIES`, default 1) bounds per-子題 fresh-call retries before a failed slot is dropped |
| `src/cli.py` | CLI entry point (argparse) |

## Code Conventions

- **Language**: Python 3.11+, managed with `uv`
- **Type hints**: Use throughout, Pydantic for data validation
- **Naming**: snake_case for Python. Chinese field names in JSON output match the exam schema (情境, 題型, etc.)
- **Config**: All secrets and endpoints via environment variables, never hardcoded
- **Output schema**: Must match the structure in `test-item.json.example` — the Chinese field names are intentional and required
- **Imports**: Use absolute imports from `src.` package

## Exam Question Schema

### Math question schema

The output JSON follows this structure (Chinese keys are required):

```
情境: 1+ of [個人, 社會時事, 科學, 職業, 建築與藝術, 數學文字情境]
題型種類: one of [單一題, 題組題]
題型: one of [選擇題, 是非題, 封閉式建構反應題, 開放式建構反應題]
數學思考: 1-3 of [形成, 運用, 詮釋評估]
學習內容: 1+ entries with {編碼, 說明} — a single question can span multiple items
題目: array of strings (question text, options, etc.)
正確解題分析: array of strings (step-by-step solution)

# Optional curriculum-aware fields (Phase 3+):
核心素養: list[str]                          # e.g. ["數-J-A2"] (codes only)
學習表現: list[{編碼, 說明}]
題目內容類型: str | None                     # 純文字 / 含圖片 / graphs/charts/tables / customized
出題概念: str

# Optional 題組 fields; emitted only when sub_question_count is supplied:
核心問題: str
文本: str
取材來源: list[str]
subquestions: list[SubQuestion]               # exactly sub_question_count entries
  SubQuestion: {id, 序號, 年級, 題型, 題目, 答案, 答案解析, 誘答分析,
                學習內容, 學習表現, 出題概念}  # math has no 評分規準
```

### Social studies question schema (108課綱)

```
核心問題: string — the essential question driving the 題組
文本: string — the passage / stimulus material
取材來源: array of strings — source citations
情境: 1+ of [個人, 公共, 職業, 教育]
題型種類: 題組題
題型: one of [選擇題, 封閉式建構反應題, 開放式建構反應題] — legacy/top-level primary type; subquestions may vary
閱讀歷程: 1-2 of [擷取訊息, 形成廣泛理解, 發展解釋, 省思與評鑑文本內容, 省思與評鑑文本形式]
文本形式: one of [連續文本, 非連續文本, 混合文本]
題目: array of strings (legacy flat format — kept for compatibility)
正確解題分析: array of strings (legacy)
subquestions: array of SubQuestion objects (primary format)
  SubQuestion:
    id: string
    序號: int
    年級: int
    科目: list[str] — e.g. ["地理"] or ["歷史", "公民與社會"]
    核心素養: list[str] — e.g. ["社-J-A2"]
    學習內容: list[{編碼, 說明}] — 108課綱 codes e.g. 歷Ka-Ⅳ-1
    學習表現: list[{編碼, 說明}] — e.g. 社1b-Ⅳ-1
    出題概念: string
    出題指示: str | None — submitted per-小題 instruction persisted from subquestion_configs[].instruction
    題型: string
    題目內容類型: str | None — per-小題 content/stimulus type when configured
    image_generation_mode: "html" | "gpt_image" | None — per-小題 renderer override; not an image requirement by itself
    圖片: str | None — rendered per-小題 PNG filename, e.g. {question_id}_sq1.png
    chart_spec: ImageSpec | None — use here when a visual belongs only to this 小題
    題目: string (full question text including options)
    答案: string
    答案解析: string
    評分規準: list[RubricEntry] — for open-response items
      RubricEntry: {code: "2"|"1"|"0"|"0X", 規準說明: str, 學生作答實例: list[str]}
```

Rubric scoring codes: `2` (full credit), `1` (partial), `0` (incorrect), `0X` (no response).

### Natural sciences question schema (108課綱 自然科學 + PISA)

```
核心問題: string — the essential question driving the 題組
文本: string — the passage / stimulus material
取材來源: array of strings — source citations
情境: 1+ of [Personal, Local-and-national, Global] (PISA-Science contexts)
情境子類別: string | None — PISA sub-context (e.g. 健康, 自然資源, 環境品質); must be a child of the chosen 情境
題型種類: 題組題
題型: one of [Simple-multiple-choice, Complex-multiple-choice, Constructed-response]
科學能力: list[str] — 1–2 of [能力一, 能力二, 能力三, 環境能力一, 環境能力二, 環境能力三]
題目內容類型: str | None
subquestions: array of SubQuestion objects
  SubQuestion:
    id: string
    序號: int
    年級: int
    科目: list[str] — fixed as ["自然科學"] (no 生物/物理/化學/地球科學 branching at question level)
    科學能力: list[str] — per-subquestion capability codes
    核心素養: list[str] — present but not actively sampled (legacy field, typically empty)
    學習內容: list[{編碼, 說明}] — 108課綱 codes e.g. INc-IV-1
    學習表現: list[{編碼, 說明}] — e.g. tr-IV-1
    出題概念: string
    題型: string
    題目: string (full question text including options)
    答案: string
    答案解析: string
    評分規準: list[RubricEntry] — for Constructed-response items
      RubricEntry: {code: "2"|"1"|"0"|"0X", 規準說明: str, 學生作答實例: list[str]}
```

Rubric scoring codes follow the same 2/1/0/0X convention as social studies.

## Curriculum Data Structure

`學習內容.json` is a JSON array of 14 objects, one per grade. Each grade has:
```json
{
  "年級": "7年級",
  "學習內容": [
    {
      "編碼": "N-7-1",
      "學習內容條目及說明": "...",
      "備註": "...",
      "對應學習表現": [{"對應學習表現": "n-IV-1"}]
    }
  ]
}
```

Content codes follow the pattern `{Category}-{Grade}-{Number}`:
- N: 數與量 (Number & Quantity)
- S: 空間與形狀 (Space & Shape)
- G: 坐標幾何 (Coordinate Geometry, grade 8-9 only)
- A: 代數 (Algebra)
- F: 函數 (Function)
- D: 資料與不確定性 (Data & Uncertainty)
- R: 關係 (Relations, elementary only)

### `data/math/curriculum/` (reshaped, used by the shared loader)

The Phase 2 build materializes these four files for the `src.common.*` loaders. Row shape parallels social studies' files:

| File | Shape / size |
|---|---|
| `learning_content.json` | 288 entries across 5 學習階段; rows `{value, 學習階段, 科目, 條目說明, 備註, 對應學習表現}`. `科目` is a single-letter strand prefix N / A / F / R / S / G / D / P (capital = junior/senior high curriculum table, lowercase = 學習表現 codes). |
| `learning_performance.json` | 131 entries; rows `{value, 學習階段, 科目, 說明}`. |
| `core_competencies.json` | 27 數-E/J/U-A1..C3 codes synthesized from the social studies template with `value` rewritten from 社- to 數-. Same outer shape (`學習階段_to_stage`, `面向`, `項目`, `核心素養`). |
| `learning_performance_intro.md` | NAER framework chapter, injected as `### 學習表現架構說明` in the math system prompt. |

All four files are rebuilt reproducibly by `scripts/build_math_curriculum.py` from `data/curriculum/{學習內容,學習表現}.json` (the legacy K-12 sources) plus the social studies core_competencies template.

## Sampler Constraints

**Math:** Allowed values for all parameters come from `question_schemas.json` at the project root. Edit that file to add or remove options — no Python changes required. Override the path with `QUESTION_SCHEMAS_PATH` env var.

**Social studies:** Allowed values come from `data/social_studies/curriculum/schema_parameters.csv` (`類別,value,instruction`). Override the directory with `SOCIAL_STUDIES_CURRICULUM_DIR` env var.

The file has two top-level scalar/array fields:
- **`學習階段`**: string injected into the system prompt (e.g. `"第四學習階段"`)
- **`grades`**: integer array of allowed grade levels (e.g. `[7, 8, 9]`) — drives CLI `--grade` choices, sampler selection, grade content index, and system prompt grade range text

Social studies sampler picks: grade, 情境, 題型種類 (always 題組題), 文本形式, 閱讀歷程, **科目** (歷史/地理/公民與社會/跨科), **核心素養** (1–3 codes from `core_competencies.json`), **學習內容_pool** (1–3 codes from `learning_content.json` filtered by 學習階段 + 科目), **學習表現_pool** (1–2 codes from `learning_performance.json` filtered similarly), optional `sub_question_count` (3–7), and optional per-小題 `SubQuestionConfig` rows. When `sub_question_count` is set, the 文本生成器 plan is truncated when longer and padded with the existing fallback plan when shorter, so exactly that many 小題 are generated. A submitted `subquestion_configs[].question_type` is a 強制值: it replaces a conflicting plan 題型 in both the 子題產生器 prompt and parsed output; a blank row falls back to the plan 題型. Omitting `sub_question_count` preserves the 文本生成器-decided count without truncation or padding. Submitted `subquestion_configs[].learning_content` and `learning_performance` are preserved as-is (not merged with the global pool by the sampler); the per-小題 prompt builder applies the `or global pool` fallback at prompt-build time when a slot's list is empty. If `sub_question_count` is unset, `--q-type` keeps the legacy global pool behavior. Use `--subject` to override 科目 via CLI; `--learning-content`, `--learning-performance`, `--core-competency` to override the curriculum pools. Social studies does not use `--style`. The web Generate form exposes the same 科目 override as a `subject_filter` dropdown (全部 / 歷史 / 地理 / 公民與社會 / 跨科); selecting 全部 omits the filter and lets the sampler pick randomly — this maps to the `subject=None` default on `ss_sample_params`. The `subject_filter` query param on `GET /api/generate` accepts a list of values identical to the CLI `--subject` pool.

Social-studies web/API per-小題 controls are encoded as `subquestion_configs`, a JSON array string accepted by `GET /api/generate`. Each row can include `question_type`, `instruction`, `question_word_limit`, `option_word_limit`, `content_type`, and `image_generation_mode`; malformed JSON is ignored with a warning. Batch-wide 預抽 values use `per_question_params`, also a JSON array string accepted by `GET /api/generate`, containing exactly `count` parameter objects. Object `i` is merged onto worker `i` before that subject's registry sampler runs, so supplied values are 釘選 and are not re-sampled. Unlike `subquestion_configs`, malformed JSON, a non-array/non-object shape, an unknown or invalid parameter, or an array length different from `count` is rejected at request validation with HTTP 422. Omitting `per_question_params` preserves the legacy sampling path. `question_type` values are one of 選擇題 / 封閉式建構反應題 / 開放式建構反應題; blank or missing values are sampled randomly per 小題 by the backend. `instruction` is injected into `## 各小題配置`, persisted as `subquestions[*].出題指示`, and preserved during correction retries. The social-studies web form does not send top-level `q_type`; it sets 題型 on each 小題 row because the parent is already fixed as 題組題. **Global 學習表現/學習內容 UI:** The global 學習表現 and 學習內容 selectors default to `SearchPicker` (搜尋模式; searchable text input + autocomplete dropdown filtered by subject/grade); a "切換勾選模式" button next to each label switches both sections to the checkbox grid and "切換搜尋模式" reverts — this is a UI-only preference; the backend receives the same arrays either way. **Per-子題 LC/LP UI:** The per-小題 學習表現 and 學習內容 pickers within 子題設定 always use `SearchPicker`, which searches the full available curriculum pool (not limited to the global selection); an empty per-小題 selection means "inherit the global sampled pool" (backend default). When codes are explicitly selected, the per-小題 prompt uses a hard "本小題務必使用下列指定學習內容/學習表現，不得替換或新增" instruction, and the parsed output SubQuestion.學習內容/學習表現 is forced to those exact codes (overriding LLM output). `content_type=含圖片` or `graphs/charts/tables` asks the model to emit that 小題's own `chart_spec`. `image_generation_mode` only selects the renderer backend (`html` or `gpt_image`); it does not require an image by itself. A blank per-小題 image mode inherits the main/request-level `image_generation_mode`, which the social-studies web form labels as `圖片生成模式`. Renderer precedence is submitted per-小題 mode → submitted main mode; generated `subquestions[*].image_generation_mode` is metadata and is overwritten with the effective renderer before output. If `sub_question_count` is unset, the prompt keeps the existing 3–7 LLM-decided behavior. If no per-小題 config is supplied, existing global/default word-limit behavior remains backward compatible. Natural sciences uses the same `subquestion_configs` encoding and 子題設定 web panel; PISA-Science 題型 values replace the social-studies 題型 enum. The top-level 文本字數限制（題組文本建議值）is available in the 社會領域/自然科學 and 數學 web forms; 數學 only uses it on the opt-in 題組 path. 數學的 `text_word_limit` is a request-level 建議值 and is never mechanically truncated after generation. Math does not send `subquestion_configs`. A math request that combines `text_word_limit` with non-empty `user_passage`（釘選的使用者文本）is rejected with HTTP 422 before unsupported-field validation; the web form disables the input, omits the value, and 發送前確認 shows only values that will be sent. The top-level 選項字數限制 remains math-only.

When randomly selecting parameters, respect these rules:
- **grade**: pick one from `question_schemas.json["grades"]`. `grade_to_learning_stage(grade)` in `src/sampler.py` maps the chosen grade to a 108課綱 學習階段 (一/二/三/四/五).
- **情境**: pick 1 to N (from `question_schemas.json["情境"]`) — multi-select, same pattern as 數學思考
- **題型種類**: pick exactly one (from `question_schemas.json["題型種類"]`)
- **題型**: pick exactly one (from `question_schemas.json["題型"]`)
- **數學思考**: pick 1 to 3 (from `question_schemas.json["數學思考"]`)
- **學習內容**: pick 1–3 entries from `data/math/curriculum/learning_content.json` filtered by 學習階段 + (optional) 科目. The 科目→prefix map lives in `_MATH_SUBJECT_TO_PREFIXES` in `src/sampler.py`.
- **學習表現**: pick 1–3 entries from `data/math/curriculum/learning_performance.json`, filtered identically.
- **核心素養**: pick 1–3 codes from `data/math/curriculum/core_competencies.json` for the selected 學習階段 (數-E-* / 數-J-* / 數-U-*).
- **題目內容類型**: pick exactly one of 純文字 / 含圖片 / graphs/charts/tables (customized is never picked randomly — it's a manual override).
- **subject_filter**: optional 科目 focus (數與量 / 代數 / 幾何 / 統計與機率 / 跨領域); when set, restricts the 學習內容 and 學習表現 draw pools by prefix.
- **Question style**: pick one from `question_schemas.json["question_style"][*].value` — determines which few-shot examples to inject and whether to generate images.

CLI overrides: `--subject-filter`, `--core-competency`, `--learning-content`, `--learning-performance`, `--content-type`, `--topic`, `--passage`, `--options`, `--core-question`, `--image-generation-mode` (in addition to the legacy `--grade`, `--style`, `--q-type`, `--context`, `--set-type` flags).

All 5 categories share the same `{value, instruction}` object format. A non-empty `instruction` on any entry is injected into the LLM user prompt: style instructions land under `## 題目風格`; instructions for 情境, 題型種類, 題型, and 數學思考 land under `## 條件補充說明` (section omitted if all instructions are empty).

**Natural sciences:** Allowed values come from `data/natural_sciences/curriculum/schema_parameters.csv` (categories: 情境, 情境子類別, 題型種類, 題型, 科學能力, 題目內容類型). Override the directory with `NATURAL_SCIENCES_CURRICULUM_DIR`.

Natural sciences sampler picks: grade (from `schema_meta.csv`), **情境** (1 from [Personal / Local-and-national / Global]), **情境子類別** (1 from the sub-contexts whose `parent` matches the chosen 情境), **題型種類** (always 題組題), **題型** (Simple-multiple-choice / Complex-multiple-choice / Constructed-response), **科學能力** (1–2 of 6: 能力一/二/三 + 環境能力一/二/三), **題目內容類型** (1 of 純文字 / 含圖片 / graphs/charts/tables; customized is never random), **學習表現_pool** (1–2 codes from `learning_performance.json` filtered by the 學習階段 derived from the sampled grade via `grade_to_learning_stage` — grades 7-9 → 第四學習階段, 10-12 → 第五學習階段), **學習內容_pool** (1–3 codes: first tries to derive from chosen 學習表現 codes' `對應學習內容` cross-links, then falls back to the full stage pool). There is no `--subject` flag and no 科目 bucketing.

CLI overrides: `--science-competency`, `--sub-context`, `--learning-content`, `--learning-performance`, `--content-type`, `--image-generation-mode`, `--grade`, `--q-type`, `--count`, `--batch`, `--seed`, `--no-verify`, `--max-retries`, `--output`, `--dry-run`. No `--style` flag (few-shot examples are keyed by 題型 folder, not style).

## Image Rendering Architecture

Images are described by `ImageSpec` (field `chart_spec` on `ExamQuestion`). The `render_mode` field determines the rendering path:

1. **`render_mode: "chart"`** — `render_chart()` in `src/renderer.py` dispatches to hardcoded matplotlib renderers for the 4 supported statistical chart types: `histogram`, `boxplot`, `line_chart`, `pie_chart`. Deterministic; no LLM call required.

2. **`render_mode: "html"`** — `render_image()` calls `_generate_html_via_llm()` (Sonnet generates a self-contained HTML/CSS/SVG document from `description` + `data`), then `PlaywrightRenderer.render()` in `src/html_renderer.py` screenshots it to PNG. Used for geometry diagrams, tables, menus, and any non-chart visual.

> **Routing rule:** which `render_mode` value the prompt asks the model to emit is codified in [`docs/figure-rendering-policy.md`](docs/figure-rendering-policy.md). Every `src/**/context_builder.py` module cites that doc from its top-level docstring — update the policy first, then the docstrings, then the `CONTENT_TYPE_INSTRUCTIONS` tables.

Orthogonal to `render_mode`, the caller-controlled `image_generation_mode` kwarg on `render_image()` selects the rendering backend:

- `"html"` (default) — use the path described above (matplotlib for `render_mode: "chart"`, Playwright for `render_mode: "html"`).
- `"gpt_image"` — bypass both deterministic paths and send the image spec to `LLMClient.generate_image()` (model from `IMAGE_MODEL`, default `gpt-image2`). Requires `IMAGE_API_KEY`; falls back to `None` (no image) on failure rather than to the Playwright path.
> **UI default vs. API/CLI default:** The web form UI defaults `image_generation_mode` to `gpt_image`; the API and CLI still default to `html`.

Math (`src/cli.py`), social studies (`src/social_studies/cli.py`), and natural sciences (`src/natural_sciences/cli.py`) all thread `image_generation_mode` from the CLI flag `--image-generation-mode` and the HTTP query param of the same name through to `render_image()`. Social-studies web rows can also send per-小題 `image_generation_mode` inside `subquestion_configs`; that value overrides the renderer only for that 小題, while the request-level `image_generation_mode` remains the fallback. The renderer does not trust model-emitted per-小題 image modes over submitted settings.

Social studies has two image locations:
- Top-level `question.chart_spec` renders to `{question_id}.png` and is stored as `question.圖片`.
- Per-小題 `subquestions[*].chart_spec` renders to `{question_id}_sq{序號}.png` and is stored as `subquestions[*].圖片`. `server/generate/service.py` embeds those PNGs as `subquestions[*].image_base64`; the React card displays them inline and ODT export inserts them near the matching 小題.

The entry point is always `render_image()` (`src/renderer.py:271`), called from `generate_one()` in `src/cli.py`.

## Common Commands

```bash
# Install dependencies
uv sync

# Run the CLI
uv run python -m src.cli generate

# Run tests
uv run pytest

# Lint
uv run ruff check src/
```

### Environment Variables

- `LLM_EXCHANGE_RETENTION_DAYS` (default `30`) — window in days for retaining `llm_exchanges` rows. Set to `0` to disable persistence entirely (no rows written, no pruning).

### Staging smoke tests

```bash
# End-to-end staging smoke tests (env-driven; no committed secrets).
bash scripts/smoke_test.sh                          # Full docker-compose auth+generate
BASE_URL=https://examgen-staging.cpeng.me \
  bash scripts/smoke_test_natural_sciences.sh       # Natural-sciences layer probe (issue #94)
```

Each script prints `FRONTEND` / `API` / `PROVIDER` layer prefixes on failure so
red output names the failing layer.

## Execution Logic

Complete waterfall trace of `uv run python -m src.cli generate`. Full reference: [`LOGIC.md`](LOGIC.md). For the web request lifecycle (SSE queue, worker thread, DB logging), see [`FLOW.md`](FLOW.md).

### Phase 1: Bootstrap & Configuration (`src/cli.py`, `src/config.py`)
1. `main()` → `parse_args()` (cli.py:215, 43-70)
2. `Config.from_env()` reads `.env` + env vars: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_PLAN/EXECUTE`, `LLM_RATE_LIMIT_DELAY`, `OUTPUT_DIR`, `DATA_DIR`, `SUBGEN_MAX_CONCURRENCY` (config.py:22-36)
3. `config.validate()` ensures `LLM_API_KEY` present (cli.py:227)
4. `output_dir.mkdir()` (cli.py:230)

### Phase 2: Data Loading (`src/data_loader.py`, cli.py:233-238)
5. `load_curriculum()` — full K-12 JSON array (data_loader.py:11-14)
6. `load_performance_standards()` — performance standards (data_loader.py:17-20)
7. `load_intro_text()` — curriculum intro markdown (data_loader.py:59-63)
8. Build grade content index `{g: [...] for g in _GRADES}` via `get_grade_content()` (data_loader.py:23-35); `_GRADES` from `question_schemas.json["grades"]`

### Phase 3: LLM Client Init (`src/llm_client.py`, cli.py:241)
9. `LLMClient(config)` initialises an `Anthropic` client (for `claude-*` calls) eagerly and lazily constructs `OpenAI` compat clients for Gemini/OpenAI providers on first use (`src/llm_client.py` `LLMClient.__init__`). Skipped if `--dry-run`.
   Playwright renderer also started here once and reused across questions (cli.py:245-253).

### Phase 4: Generation Loop (`src/cli.py` lines 269-310)

For each question:

**4A. Seed** — `seed = base_seed + i` if seeded; `rng` not used directly here (seed passed to `sample_params`)

**4B. Sampling** (`src/sampler.py:21-77`) — `sample_params()` randomly picks grade (line 38), 情境 (41-46), 題型種類 (49), 題型 (52), 數學思考 1-3 (55-57), 學習內容 1-3 (60-64), style (67). Enum values come from `question_schemas.json` via `src/schema_loader.py`. All overridable via CLI. `--q-type` and `--style` each accept one or more values (`nargs="+"`): a single value forces it; multiple values define a pool and the sampler picks one randomly per question.

**4C. Prompt build** (`src/context_builder.py`) —
- `build_system_prompt()`: injects full curriculum JSON + performance JSON + intro text (lines 131-150)
- `build_user_prompt()`: injects sampled params + per-param instructions + style instruction + few-shot examples (lines 153-230). All instructions come from `_INSTRUCTIONS` (built via `schema_loader.build_instructions()` at module import, line 14). Non-empty instructions for 情境/題型種類/題型/數學思考 appear under `## 條件補充說明`; style instruction appears under `## 題目風格`. Both sections are omitted if empty.

**4D. Few-shot injection** —
- `load_few_shot_examples(few_shot_dir, style)` loads ALL `*.json` from `data/few_shot/{style}/` alphabetically (data_loader.py:66-75)
- Flatten arrays; `rng.sample(pool, min(2, len))` picks 1-2 examples (context_builder.py:208-209)

**4E. LLM call #1** — `client.generate_json()` → `openai.chat.completions.create()`, Sonnet, temp=0.7, max_tokens=8192 (llm_client.py:70-73, 26-40)

**4F. JSON extraction** — `extract_json()` tries: markdown code block → raw `{` → brute regex (llm_client.py:76-93)

**4G. Parse** — `_parse_question()` builds `ExamQuestion` + `QuestionMetadata` (cli.py:145-212); handles both `image_spec` (new) and `chart_spec` (legacy) field names from LLM output

### Phase 5: Image Rendering + Verification + Correction Loop (`src/renderer.py`, `src/html_renderer.py`, `src/verifier.py`, `src/corrector.py`, cli.py inside `generate_with_corrections`)
Image rendering happens **before** verification so the verifier can see the PNG.

1. If `question.chart_spec` exists: `render_image(spec, path, question_text, html_renderer, llm_client)` (renderer.py:271) first checks effective `image_generation_mode`; `gpt_image` sends the spec to `LLMClient.generate_image()`, while `html` dispatches by `render_mode`:
   - `"chart"` → `render_chart()` (renderer.py:50-71): `histogram/boxplot/line_chart/pie_chart` → hardcoded matplotlib
   - `"html"` → LLM call #2: `_generate_html_via_llm()` (renderer.py:343) asks Sonnet to write HTML/CSS/SVG; then `html_renderer.render()` (html_renderer.py) screenshots via Playwright
2. For social studies, `_render_subquestion_images()` also renders each `subquestions[*].chart_spec` before verification, using submitted per-小題 `image_generation_mode` when present and otherwise the request-level fallback.
3. LLM call #3: `verify_question(client, question, chart_image_path)` — sends question + solution + optional PNG via `client.generate_with_image()` (multimodal). Returns `VerificationResult{passed, answer_match, details, my_answer, provided_answer, chart_verification}` where `chart_verification: ChartVerificationResult | None` holds `{chart_data_match, chart_labels_correct, chart_details}` (verifier.py)
4. If `passed=False` and retries remain: `correct_question(client, question, verification, chart_image_path)` (corrector.py) sends the failed question JSON + verifier feedback to Sonnet (multimodal if chart failed + PNG exists). Only `題目`, `正確解題分析`, and `chart_spec` are mutable; all other fields are restored from the original. Re-render PNG only if `chart_spec` changed. Re-verify and loop up to `max_retries` times.

### Phase 7: Output (cli.py:313-330)
- Default: `{question_id}.json` per question (`model_dump_json`, cli.py:315-320)
- `--batch`: single `batch_{timestamp}.json` array (cli.py:323-330)

### LLM Calls Summary

| # | Purpose | Model | File |
|---|---|---|---|
| 0 | Plan 核心問題 candidates (optional; only when called via `/api/plan-core-questions` or upstream of CLI `--core-question`) | `model_plan` | `src/planner.py` + `src/common/planner.py` |
| 1 | Generate question | `model_execute` | `src/llm_client.py` |
| 2 | Generate HTML image (only when `render_mode="html"`) | `model_execute` | `src/renderer.py` |
| 3 | Verify answer + image (multimodal) | `model_execute` | `src/verifier.py` |
| 4 | Correction (when verification fails; multimodal if chart failed) | `model_execute` | `src/corrector.py` |
> **Social studies & natural sciences:** Call #1 is replaced by a 文本生成器 call (agent `generator`) + N concurrent 子題產生器 calls (agents `sub_generator#1`…`sub_generator#N`), each on its own `LLMClient` instance. Calls #2–4 (image/verify/correct) are unchanged.

Calls 3 + 4 may repeat up to `max_retries` times (default 3, via `LLM_MAX_RETRIES` / `--max-retries`).

### Randomness Summary

All RNG is `random.Random(seed)` per question. Points: grade from `_GRADES` (sampler.py:38), 情境 (41-46), 題型種類 (49), 題型 (52), 數學思考 (55-57), 學習內容 (60-64), style (67), few-shot pick (context_builder.py:208-209).

## Agent skills

### Issue tracker

Issues live in GitHub Issues at `paulpengtw/exam-generation`, via the `gh` CLI. See `docs/agents/issue-tracker.md`. Issues are closed when the resolving PR merges to `staging` (close manually — `Closes #N` only auto-fires on `main`); see the close convention in that doc.

### Triage labels

Default five-role vocabulary, label string equals role name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.
