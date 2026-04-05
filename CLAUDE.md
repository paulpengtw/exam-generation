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
| `src/schemas.py` | Pydantic models defining question structure |
| `src/sampler.py` | Random parameter selection logic |
| `src/context_builder.py` | Prompt assembly with few-shot injection |
| `src/llm_client.py` | OpenAI-compatible API client with model routing |
| `src/verifier.py` | Two-pass answer verification |
| `src/renderer.py` | matplotlib chart/diagram PNG generation (geometry uses LLM-assisted code gen) |
| `IMPLEMENTATION_PLAN.md` | Planned refactors and known tech debt |
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

When randomly selecting parameters, respect these rules:
- **情境**: pick exactly one
- **題型種類**: pick exactly one
- **題型**: pick exactly one
- **數學思考**: pick 1 to 3 (can repeat: 形成, 運用, 詮釋評估)
- **學習內容**: pick 1 or more from the selected grade (can cross grades 7-9 for integrated questions)
- **Question style**: pick one of [text_only, with_chart, with_image, creative_scenario] — determines which few-shot examples to inject and whether to generate images

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
