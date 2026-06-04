# CLAUDE.md

## Project Overview

This is a CLI-based exam question generator for Taiwan math (default: grades 7-9, 第四學習階段). Target 學習階段 and grade list are configurable in `question_schemas.json`. It uses LLMs via OpenAI-compatible endpoints to generate structured exam questions with optional chart/image output.

## Architecture Decisions

### No RAG
All curriculum data (學習內容.json, 學習表現.json) is injected directly into the LLM context. The full grades 1-12 curriculum is provided so the model can calibrate difficulty — understanding what students already know (grades 1-6) and what lies ahead (grades 10-12).

### Script-side randomness
The Python code handles all random selection (grade, 情境, 題型種類, 題型, 數學思考, 學習內容, question style). The LLM receives deterministic instructions — it does not choose these parameters itself.

### Verify + correct loop
1. First call (Sonnet): generates the question and solution.
2. Chart is rendered to PNG (if `chart_spec` present) — before verification so the verifier can see it.
3. Second call (Sonnet, multimodal): independently solves the question, inspects PNG, returns `VerificationResult` with `passed`, `answer_match`, `details`, `my_answer`, `provided_answer`, and optional `chart_verification`.
4. If `passed=False`, a correction pass sends the failed question + verifier feedback back to Sonnet for a minimal targeted fix (`src/corrector.py`). PNG re-renders only when `chart_spec` actually changes. Re-verify and loop up to `max_retries` (default 3, via `LLM_MAX_RETRIES` / `--max-retries`).

### OpenAI-compatible endpoint
Uses the `openai` Python SDK for endpoint flexibility. Model routing: `claude-opus-4-6` for planning, `claude-sonnet-4-6` for generation and verification.

### Web-ready design
All core modules (`sampler`, `context_builder`, `llm_client`, `verifier`, `renderer`) are standalone importable components. The CLI (`cli.py`) is a thin wrapper. Config comes from env vars. This allows future integration with FastAPI/Flask without refactoring.

### Social studies mode (parallel forked codepath)
`src/social_studies/` is a self-contained fork that generates **108課綱 社會領域素養導向 命題** (歷史/地理/公民與社會, 跨科題組). It reuses `llm_client`, `verifier`, `corrector`, and `renderer` but has its own sampler, context builder, schema loader, and data loader.

PISA-style tags (`閱讀歷程`, `文本形式`) are retained as secondary diversity axes to influence question design, but the primary framing is 108課綱, not PISA reading literacy.

Schema, curriculum, and few-shot data are **CSV-driven** for schema/few-shot; **JSON-driven** for curriculum. Files under `data/social_studies/` read at runtime:

| File | Purpose |
|---|---|
| `curriculum/schema_meta.csv` | 學習階段 label + grades list |
| `curriculum/schema_parameters.csv` | Allowed values + instructions for all 6 question parameter categories (includes 科目: 歷史/地理/公民與社會/跨科) |
| `curriculum/learning_performance.json` | 108課綱 社會領域 學習表現標準 (26 codes; ODT-sourced) → system prompt + sampler pool |
| `curriculum/learning_content.json` | 108課綱 社會領域 學習內容 (472 entries; ODT-sourced `對應學習表現`) → system prompt + sampler pool |
| `few_shot/few_shot_examples.csv` | Few-shot examples (long format, grouped by `範例編號`; one row per subquestion) |

CSVs are `utf-8-sig` (Excel BOM-tolerant); multi-value fields use `;` as separator. `範例_`-prefixed files in the same folders are reference examples for researchers — they are never loaded by the system. See `data/social_studies/csv_填寫指南.md` for the field-by-field filler guide.

**Sampler 科目 filter:** `_SUBJECT_TO_PREFIXES` in `curriculum_loader.py` maps each subject to its 科目 set. All subjects include `"社"` so the 16 cross-subject general 學習表現 codes (社1a/1b/2a/2b/2c/3a/3b/3c/3d-Ⅳ-*) are in every subject's pool — not only 跨科. This is per 108課綱 design where 社_* codes apply across all 社會領域 subjects. All subjects also include the empty-string `""` bucket so the 57 shared 學習內容 entries with `科目=""` appear in every subject's draw pool (parallel to the `社` bucket for 學習表現).

## Key Files

| File | Purpose |
|---|---|
| `data/curriculum/學習內容.json` | Full K-12 math curriculum content, 14 grade levels |
| `data/curriculum/學習表現.json` | Math learning performance standards by stage |
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
| `data/social_studies/few_shot/few_shot_examples.csv` | Social studies few-shot examples (long format grouped by 範例編號; one row per subquestion with all 108課綱 metadata columns) |
| `data/social_studies/csv_填寫指南.md` | zh-TW filler guide: field-by-field explanation of JSON + CSV files |
| `src/social_studies/schema_loader.py` | Builds social-studies schema dict from `schema_meta.csv` + `schema_parameters.csv` |
| `src/social_studies/curriculum_loader.py` | JSON loaders for `learning_content.json` / `learning_performance.json` + sampler helpers (`allowed_*`, `*_instructions`, `load_performance_intro`); `_SUBJECT_TO_PREFIXES` maps QuestionSubject values to code-prefix sets (all include `"社"` and `""` so cross-subject and shared entries appear in every pool) |
| `data/social_studies/curriculum/core_competencies.json` | 108課綱 核心素養 codes → sampler pool; loaded by `core_competency_loader.py` |
| `src/social_studies/core_competency_loader.py` | JSON loader + `allowed_core_competencies(data, stage, subject)` for 核心素養 sampler pool |
| `src/social_studies/data_loader.py` | Loads CSV few-shot examples (learning content/performance now via `curriculum_loader`) |
| `src/social_studies/context_builder.py` | Social studies prompt assembly; `## 課程綱要參考` block injected into system prompt |
| `src/social_studies/schemas.py` | Social studies Pydantic models: `ExamQuestion`, `SubQuestion`, `LearningContentRef`, `RubricEntry`, `QuestionSubject` (歷史/地理/公民與社會/跨科), `VerificationResult`, `ImageSpec` |
| `src/schemas.py` | Math Pydantic models defining question structure (enums loaded dynamically from `question_schemas.json` at import time); `ImageSpec` describes the image (`render_mode`, `chart_type`, etc.); includes `ChartVerificationResult` nested in `VerificationResult` |
| `src/sampler.py` | Random parameter selection logic |
| `src/context_builder.py` | Prompt assembly with few-shot injection |
| `src/llm_client.py` | OpenAI-compatible API client with model routing; `generate_with_image()` for multimodal (text + PNG) calls |
| `src/verifier.py` | Independent answer verification pass |
| `src/corrector.py` | Minimal targeted correction pass for failed-verification questions |
| `src/renderer.py` | matplotlib PNG generation for statistical charts (`render_mode: "chart"`) |
| `src/html_renderer.py` | Playwright HTML→PNG renderer (`render_mode: "html"`) |
| `IMPLEMENTATION_PLAN.md` | Planned refactors and known tech debt |
| `FLOW.md` | ASCII tree of web Generate request lifecycle (frontend click → SSE → queue → worker → result) |
| `LOGIC.md` | Full waterfall execution trace with file + line references |
| `src/data_loader.py` | Curriculum data loading and grade filtering |
| `src/config.py` | Environment variable configuration |
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
```

### Social studies question schema (108課綱)

```
核心問題: string — the essential question driving the 題組
文本: string — the passage / stimulus material
取材來源: array of strings — source citations
情境: 1+ of [個人, 公共, 職業, 教育]
題型種類: 題組題
題型: one of [選擇題, 封閉式建構反應題, 開放式建構反應題]
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
    題型: string
    題目: string (full question text including options)
    答案: string
    答案解析: string
    評分規準: list[RubricEntry] — for open-response items
      RubricEntry: {code: "2"|"1"|"0"|"0X", 規準說明: str, 學生作答實例: list[str]}
```

Rubric scoring codes: `2` (full credit), `1` (partial), `0` (incorrect), `0X` (no response).

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

## Sampler Constraints

**Math:** Allowed values for all parameters come from `question_schemas.json` at the project root. Edit that file to add or remove options — no Python changes required. Override the path with `QUESTION_SCHEMAS_PATH` env var.

**Social studies:** Allowed values come from `data/social_studies/curriculum/schema_parameters.csv` (`類別,value,instruction`). Override the directory with `SOCIAL_STUDIES_CURRICULUM_DIR` env var.

The file has two top-level scalar/array fields:
- **`學習階段`**: string injected into the system prompt (e.g. `"第四學習階段"`)
- **`grades`**: integer array of allowed grade levels (e.g. `[7, 8, 9]`) — drives CLI `--grade` choices, sampler selection, grade content index, and system prompt grade range text

Social studies sampler picks: grade, 情境, 題型種類 (always 題組題), 題型, 文本形式, 閱讀歷程, **科目** (歷史/地理/公民與社會/跨科), **核心素養** (1–3 codes from `core_competencies.json`), **學習內容_pool** (1–3 codes from `learning_content.json` filtered by 學習階段 + 科目), **學習表現_pool** (1–2 codes from `learning_performance.json` filtered similarly), and question_style. Use `--subject` to override 科目 via CLI; `--learning-content`, `--learning-performance`, `--core-competency` to override the curriculum pools. Use `--grade`, `--style`, `--q-type`, etc. as with math. The web Generate form exposes the same 科目 override as a `subject_filter` dropdown (全部 / 歷史 / 地理 / 公民與社會 / 跨科); selecting 全部 omits the filter and lets the sampler pick randomly — this maps to the `subject=None` default on `ss_sample_params`. The `subject_filter` query param on `GET /api/generate` accepts a list of values identical to the CLI `--subject` pool.

When randomly selecting parameters, respect these rules:
- **grade**: pick one from `question_schemas.json["grades"]`
- **情境**: pick 1 to N (from `question_schemas.json["情境"]`) — multi-select, same pattern as 數學思考
- **題型種類**: pick exactly one (from `question_schemas.json["題型種類"]`)
- **題型**: pick exactly one (from `question_schemas.json["題型"]`)
- **數學思考**: pick 1 to 3 (from `question_schemas.json["數學思考"]`)
- **學習內容**: pick 1 or more from the selected grade (can cross configured grades for integrated questions)
- **Question style**: pick one from `question_schemas.json["question_style"][*].value` — determines which few-shot examples to inject and whether to generate images.

All 5 categories share the same `{value, instruction}` object format. A non-empty `instruction` on any entry is injected into the LLM user prompt: style instructions land under `## 題目風格`; instructions for 情境, 題型種類, 題型, and 數學思考 land under `## 條件補充說明` (section omitted if all instructions are empty).

## Image Rendering Architecture

Images are described by `ImageSpec` (field `chart_spec` on `ExamQuestion`). The `render_mode` field determines the rendering path:

1. **`render_mode: "chart"`** — `render_chart()` in `src/renderer.py` dispatches to hardcoded matplotlib renderers for the 4 supported statistical chart types: `histogram`, `boxplot`, `line_chart`, `pie_chart`. Deterministic; no LLM call required.

2. **`render_mode: "html"`** — `render_image()` calls `_generate_html_via_llm()` (Sonnet generates a self-contained HTML/CSS/SVG document from `description` + `data`), then `PlaywrightRenderer.render()` in `src/html_renderer.py` screenshots it to PNG. Used for geometry diagrams, tables, menus, and any non-chart visual.

Orthogonal to `render_mode`, the caller-controlled `image_generation_mode` kwarg on `render_image()` selects the rendering backend:

- `"html"` (default) — use the path described above (matplotlib for `render_mode: "chart"`, Playwright for `render_mode: "html"`).
- `"gpt_image"` — bypass both deterministic paths and send the image spec to `LLMClient.generate_image()` (model from `IMAGE_MODEL`, default `gpt-image2`). Requires `IMAGE_API_KEY`; falls back to `None` (no image) on failure rather than to the Playwright path.

Both math (`src/cli.py`) and social studies (`src/social_studies/cli.py`) thread `image_generation_mode` from the CLI flag `--image-generation-mode` and the HTTP query param of the same name through to the two `render_image()` call sites (initial render and post-correction re-render).

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

## Execution Logic

Complete waterfall trace of `uv run python -m src.cli generate`. Full reference: [`LOGIC.md`](LOGIC.md). For the web request lifecycle (SSE queue, worker thread, DB logging), see [`FLOW.md`](FLOW.md).

### Phase 1: Bootstrap & Configuration (`src/cli.py`, `src/config.py`)
1. `main()` → `parse_args()` (cli.py:215, 43-70)
2. `Config.from_env()` reads `.env` + env vars: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_PLAN/EXECUTE`, `LLM_RATE_LIMIT_DELAY`, `OUTPUT_DIR`, `DATA_DIR` (config.py:22-36)
3. `config.validate()` ensures `LLM_API_KEY` present (cli.py:227)
4. `output_dir.mkdir()` (cli.py:230)

### Phase 2: Data Loading (`src/data_loader.py`, cli.py:233-238)
5. `load_curriculum()` — full K-12 JSON array (data_loader.py:11-14)
6. `load_performance_standards()` — performance standards (data_loader.py:17-20)
7. `load_intro_text()` — curriculum intro markdown (data_loader.py:59-63)
8. Build grade content index `{g: [...] for g in _GRADES}` via `get_grade_content()` (data_loader.py:23-35); `_GRADES` from `question_schemas.json["grades"]`

### Phase 3: LLM Client Init (`src/llm_client.py`, cli.py:241)
9. `LLMClient(config)` wraps `OpenAI(api_key, base_url)` (llm_client.py:19-24). Skipped if `--dry-run`.
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

1. If `question.chart_spec` exists: `render_image(spec, path, question_text, html_renderer, llm_client)` (renderer.py:271) dispatches by `render_mode`:
   - `"chart"` → `render_chart()` (renderer.py:50-71): `histogram/boxplot/line_chart/pie_chart` → hardcoded matplotlib
   - `"html"` → LLM call #2: `_generate_html_via_llm()` (renderer.py:343) asks Sonnet to write HTML/CSS/SVG; then `html_renderer.render()` (html_renderer.py) screenshots via Playwright
2. LLM call #3: `verify_question(client, question, chart_image_path)` — sends question + solution + optional PNG via `client.generate_with_image()` (multimodal). Returns `VerificationResult{passed, answer_match, details, my_answer, provided_answer, chart_verification}` where `chart_verification: ChartVerificationResult | None` holds `{chart_data_match, chart_labels_correct, chart_details}` (verifier.py)
3. If `passed=False` and retries remain: `correct_question(client, question, verification, chart_image_path)` (corrector.py) sends the failed question JSON + verifier feedback to Sonnet (multimodal if chart failed + PNG exists). Only `題目`, `正確解題分析`, and `chart_spec` are mutable; all other fields are restored from the original. Re-render PNG only if `chart_spec` changed. Re-verify and loop up to `max_retries` times.

### Phase 7: Output (cli.py:313-330)
- Default: `{question_id}.json` per question (`model_dump_json`, cli.py:315-320)
- `--batch`: single `batch_{timestamp}.json` array (cli.py:323-330)

### LLM Calls Summary

| # | Purpose | Model | File:Line |
|---|---|---|---|
| 1 | Generate question | Sonnet | llm_client.py:26-40 |
| 2 | Generate HTML image (only when `render_mode="html"`) | Sonnet | renderer.py:343 |
| 3 | Verify answer + image (multimodal) | Sonnet | verifier.py (`generate_with_image`) |
| 4 | Correction (when verification fails; multimodal if chart failed) | Sonnet | corrector.py |

Calls 3 + 4 may repeat up to `max_retries` times (default 3, via `LLM_MAX_RETRIES` / `--max-retries`).

### Randomness Summary

All RNG is `random.Random(seed)` per question. Points: grade from `_GRADES` (sampler.py:38), 情境 (41-46), 題型種類 (49), 題型 (52), 數學思考 (55-57), 學習內容 (60-64), style (67), few-shot pick (context_builder.py:208-209).
