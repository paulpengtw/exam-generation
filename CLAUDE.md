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
`src/social_studies/` is a self-contained fork that generates PISA reading-literacy (社會科閱讀素養) exam items. It reuses `llm_client`, `verifier`, `corrector`, and `renderer` but has its own sampler, context builder, schema loader, and data loader.

Schema, curriculum, and few-shot data are **CSV-driven** — no JSON, no rebuild. All five CSV files under `data/social_studies/` are read at runtime on every run:

| CSV | Purpose |
|---|---|
| `curriculum/schema_meta.csv` | 學習階段 label + grades list |
| `curriculum/schema_parameters.csv` | Allowed values + instructions for all 6 question parameter categories |
| `curriculum/learning_performance.csv` | 學習表現標準 → injected into system prompt `## 課程綱要參考` |
| `curriculum/learning_content.csv` | 學習內容 by grade → same section |
| `few_shot/few_shot_examples.csv` | Few-shot examples (long format, grouped by `範例編號`) |

CSVs are `utf-8-sig` (Excel BOM-tolerant); multi-value fields use `;` as separator. `範例_`-prefixed files in the same folders are reference examples for researchers — they are never loaded by the system. See `data/social_studies/csv_填寫指南.md` for the field-by-field filler guide.

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
| `data/social_studies/curriculum/learning_performance.csv` | Social studies 學習表現標準 → system prompt |
| `data/social_studies/curriculum/learning_content.csv` | Social studies 學習內容 by grade → system prompt |
| `data/social_studies/few_shot/few_shot_examples.csv` | Social studies few-shot examples (long format grouped by 範例編號) |
| `data/social_studies/csv_填寫指南.md` | zh-TW filler guide: field-by-field explanation of all 5 CSVs |
| `src/social_studies/schema_loader.py` | Builds social-studies schema dict from `schema_meta.csv` + `schema_parameters.csv` |
| `src/social_studies/data_loader.py` | Loads `learning_performance.csv`, `learning_content.csv`, and CSV few-shot examples |
| `src/social_studies/context_builder.py` | Social studies prompt assembly; `## 課程綱要參考` block injected into system prompt |
| `src/schemas.py` | Pydantic models defining question structure (enums loaded dynamically from `question_schemas.json` at import time); `ImageSpec` describes the image (`render_mode`, `chart_type`, etc.); includes `ChartVerificationResult` nested in `VerificationResult` |
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
