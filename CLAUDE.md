# CLAUDE.md

## Project Overview

This is a CLI-based exam question generator for Taiwan's junior high school math (grades 7-9, 第四學習階段). It uses LLMs via OpenAI-compatible endpoints to generate structured exam questions with optional chart/image output.

## Architecture Decisions

### No RAG
All curriculum data (學習內容.json, 學習表現.json) is injected directly into the LLM context. The full grades 1-12 curriculum is provided so the model can calibrate difficulty — understanding what students already know (grades 1-6) and what lies ahead (grades 10-12).

### Script-side randomness
The Python code handles all random selection (grade, 情境, 題型種類, 題型, 數學思考, 學習內容, question style). The LLM receives deterministic instructions — it does not choose these parameters itself.

### Two-pass verification
1. First call (Sonnet): generates the question and solution
2. Second call (Sonnet): independently solves the question and flags any discrepancies

### OpenAI-compatible endpoint
Uses the `openai` Python SDK for endpoint flexibility. Model routing: `claude-opus-4-6` for planning, `claude-sonnet-4-6` for generation and verification.

### Web-ready design
All core modules (`sampler`, `context_builder`, `llm_client`, `verifier`, `renderer`) are standalone importable components. The CLI (`cli.py`) is a thin wrapper. Config comes from env vars. This allows future integration with FastAPI/Flask without refactoring.

## Key Files

| File | Purpose |
|---|---|
| `data/curriculum/學習內容.json` | Full K-12 curriculum content, 14 grade levels |
| `data/curriculum/學習表現.json` | Learning performance standards by stage |
| `data/few_shot/` | Structured few-shot examples by question style |
| `data/example_exams/` | Past national exam PDFs (112-114) for reference |
| `question_schemas.json` | User-editable config: allowed values for 情境, 題型種類, 題型, 數學思考, question_style (with prompt instructions) |
| `src/schema_loader.py` | Loads `question_schemas.json` and builds dynamic str-enums; exposes `build_style_instructions()` |
| `src/schemas.py` | Pydantic models defining question structure (enums loaded dynamically from `question_schemas.json` at import time) |
| `src/sampler.py` | Random parameter selection logic |
| `src/context_builder.py` | Prompt assembly with few-shot injection |
| `src/llm_client.py` | OpenAI-compatible API client with model routing |
| `src/verifier.py` | Two-pass answer verification |
| `src/renderer.py` | matplotlib chart/diagram PNG generation (geometry uses LLM-assisted code gen) |
| `IMPLEMENTATION_PLAN.md` | Planned refactors and known tech debt |
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
情境: one of [個人, 社會時事, 科學, 職業, 建築與藝術, 數學文字情境]
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

Allowed values for all parameters come from `question_schemas.json` at the project root. Edit that file to add or remove options — no Python changes required. Override the path with `QUESTION_SCHEMAS_PATH` env var.

When randomly selecting parameters, respect these rules:
- **情境**: pick exactly one (from `question_schemas.json["情境"]`)
- **題型種類**: pick exactly one (from `question_schemas.json["題型種類"]`)
- **題型**: pick exactly one (from `question_schemas.json["題型"]`)
- **數學思考**: pick 1 to 3 (from `question_schemas.json["數學思考"]`)
- **學習內容**: pick 1 or more from the selected grade (can cross grades 7-9 for integrated questions)
- **Question style**: pick one from `question_schemas.json["question_style"][*].value` — determines which few-shot examples to inject and whether to generate images. Each style entry also carries an `instruction` string injected into the user prompt.

## Geometry Rendering Architecture

`src/renderer.py` handles geometry diagrams (`chart_type: "geometry"`) with a 3-tier approach:

1. **Hardcoded patterns** — two legacy matchers check for specific `data` keys:
   - `"rectangle" in data and "triangle" in data` -> courtyard diagram
   - `"lamp_height" in data` -> shadow diagram
2. **LLM-assisted code generation** (primary path) — Sonnet generates a matplotlib code snippet from `chart_spec.description` + `chart_spec.data`, which is `exec()`'d with `fig, ax, plt, np, patches, FONT_PROP` in scope
3. **Text fallback** — renders `description` as centered text (only if no LLM client)

**Planned change:** The hardcoded patterns in tier 1 are marked for removal in `IMPLEMENTATION_PLAN.md`. The LLM-assisted path handles all geometry types generically and should become the sole renderer. When modifying `_render_geometry()`, do not add new hardcoded pattern branches — let the LLM path handle it.

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

Complete waterfall trace of `uv run python -m src.cli generate`. Full reference: [`LOGIC.md`](LOGIC.md).

### Phase 1: Bootstrap & Configuration (`src/cli.py`, `src/config.py`)
1. `main()` → `parse_args()` (cli.py:181, 39-65)
2. `Config.from_env()` reads `.env` + env vars: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_PLAN/EXECUTE`, `OUTPUT_DIR`, `DATA_DIR` (config.py:22-36)
3. `config.validate()` ensures `LLM_API_KEY` present (cli.py:193)
4. `output_dir.mkdir()` (cli.py:196)

### Phase 2: Data Loading (`src/data_loader.py`, cli.py:199-204)
5. `load_curriculum()` — full K-12 JSON array (data_loader.py:11-14)
6. `load_performance_standards()` — performance standards (data_loader.py:17-19)
7. `load_intro_text()` — curriculum intro markdown (data_loader.py:56-60)
8. Build `{7: [...], 8: [...], 9: [...]}` grade content index via `get_grade_content()` (data_loader.py:23-35)

### Phase 3: LLM Client Init (`src/llm_client.py`, cli.py:207)
9. `LLMClient(config)` wraps `OpenAI(api_key, base_url)` (llm_client.py:16-21). Skipped if `--dry-run`.

### Phase 4: Generation Loop (`src/cli.py` lines 216-278)

For each question:

**4A. Seed** — `rng = random.Random(seed)` (cli.py:221-222)

**4B. Sampling** (`src/sampler.py:18-69`) — `sample_params()` randomly picks grade, 情境, 題型種類, 題型, 數學思考 (1-3), 學習內容 (1-3), style. Enum values come from `question_schemas.json` via `src/schema_loader.py`. All overridable via CLI.

**4C. Prompt build** (`src/context_builder.py`) —
- `build_system_prompt()`: injects full curriculum JSON + performance JSON + intro text (lines 108-118)
- `build_user_prompt()`: injects sampled params + style instruction + few-shot examples (lines 121-173). Style instruction looked up from `_STYLE_INSTRUCTIONS` (built from `question_schemas.json["question_style"]` at import time)

**4D. Few-shot injection** —
- `load_few_shot_examples(few_shot_dir, style)` loads ALL `*.json` from `data/few_shot/{style}/` alphabetically (data_loader.py:63-72)
- Flatten arrays; `rng.sample(pool, min(2, len))` picks 1-2 examples (context_builder.py:144-155)

**4E. LLM call #1** — `client.generate_json()` → `openai.chat.completions.create()`, Sonnet, temp=0.7, max_tokens=8192 (llm_client.py:41-44, 23-35)

**4F. JSON extraction** — `extract_json()` tries: markdown code block → raw `{` → brute regex (llm_client.py:47-64)

**4G. Parse** — `_parse_question()` builds `ExamQuestion` + `QuestionMetadata` (cli.py:122-178)

### Phase 5: Verification (`src/verifier.py`, cli.py:112-117)
LLM call #2: `verify_question()` sends question + solution, Sonnet independently solves and returns `VerificationResult{passed, answer_match, details}` (verifier.py:50-74)

### Phase 6: Chart Rendering (`src/renderer.py`, cli.py:262-267)
`render_chart()` dispatches by `chart_type` (lines 50-75):
- `histogram/boxplot/line_chart/pie_chart` — hardcoded matplotlib
- `geometry` — 3-tier: hardcoded patterns (lines 282-287) → LLM call #3 `exec()`'d matplotlib code (lines 290-293, 405-464) → text fallback (lines 296-303)

### Phase 7: Output (cli.py:269-290)
- Default: `{question_id}.json` per question (`model_dump_json`, cli.py:272-278)
- `--batch`: single `batch_{timestamp}.json` array (cli.py:281-288)

### LLM Calls Summary

| # | Purpose | Model | File:Line |
|---|---|---|---|
| 1 | Generate question | Sonnet | llm_client.py:26-35 |
| 2 | Verify answer | Sonnet | verifier.py:62 |
| 3 | Geometry code gen (conditional) | Sonnet | renderer.py:426-429 |

### Randomness Summary

All RNG is `random.Random(seed)` per question. Points: grade (sampler.py:35), 情境 (38), 題型種類 (41), 題型 (44), 數學思考 (47-49), 學習內容 (52-56), style (59), few-shot pick (context_builder.py:154-155).
