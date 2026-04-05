# exam-generation

CLI tool for generating Taiwan junior high school (7-9 grade) math exam questions using LLMs.

The system randomly samples question parameters (grade, type, context, learning content), assembles a structured prompt with few-shot examples, calls an LLM to generate the question, then runs a second verification pass. Output is JSON per question, with optional PNG images for chart/diagram-based questions.

## Architecture

```
graph TD
    A[Curriculum Data: 學習內容 + 學習表現] -->|full JSON injected| B(Sampler: random selection)
    B -->|grade / 題型 / 情境 / 學習內容| C{Context Builder}
    D[Few-shot Example DB] -->|matching examples| C
    C -->|assembled prompt| E[LLM: claude-sonnet-4-6 via OpenAI endpoint]
    E -->|generated question JSON| F[Verifier: independent solve pass]
    F -->|validated JSON| G[CLI Output: JSON + optional PNG]
```

### Key Principles

- **No RAG.** All curriculum data and few-shot examples are injected directly as context.
- **Randomness is script-side.** The program selects grade, question type, context, learning content — not the LLM.
- **Two-pass verification.** Sonnet generates, then Sonnet independently solves and flags errors.
- **OpenAI-compatible endpoint.** Uses the `openai` SDK for endpoint diversity. Opus plans, Sonnet executes.

## Project Structure

```
exam-generation/
├── data/
│   ├── curriculum/
│   │   ├── 學習內容.json          # Full K-12 math curriculum content (grades 1-12)
│   │   └── 學習表現.json          # Learning performance standards
│   ├── few_shot/
│   │   ├── text_only/             # Text-only question examples
│   │   ├── with_chart/            # Questions with chart descriptions
│   │   ├── with_image/            # Questions with image descriptions
│   │   └── creative_scenario/     # Creative real-world scenario examples
│   └── example_exams/
│       ├── 112P_Math.pdf          # Past exam: year 112
│       ├── 113P_Math.pdf          # Past exam: year 113
│       └── 114P_Math.pdf          # Past exam: year 114
├── src/
│   ├── __init__.py
│   ├── cli.py                     # CLI entry point
│   ├── config.py                  # Configuration & env management
│   ├── sampler.py                 # Random parameter selection
│   ├── context_builder.py         # Prompt assembly with few-shot injection
│   ├── llm_client.py              # OpenAI-compatible LLM client
│   ├── verifier.py                # Two-pass answer verification
│   ├── renderer.py                # matplotlib image generation
│   ├── schemas.py                 # Pydantic data models
│   └── data_loader.py             # Curriculum data loading & indexing
├── output/                        # Generated questions (gitignored)
├── IMPLEMENTATION_PLAN.md         # Planned refactors and known tech debt
├── CLAUDE.md                      # AI assistant conventions
├── README.md
├── pyproject.toml
└── .env.example
```

## Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for dependency management
- An API key for an OpenAI-compatible endpoint serving Claude models

### Install

```bash
# Clone the repo
git clone <repo-url>
cd exam-generation

# Install dependencies with uv
uv sync

# Copy and configure environment
cp .env.example .env
# Edit .env with your API key and endpoint
```

### Configuration

Environment variables (set in `.env` or export directly):

| Variable | Description | Default |
|---|---|---|
| `LLM_API_KEY` | API key for the OpenAI-compatible endpoint | (required) |
| `LLM_BASE_URL` | Base URL for the API endpoint | `https://api.anthropic.com/v1` |
| `LLM_MODEL_PLAN` | Model for planning tasks | `claude-opus-4-6` |
| `LLM_MODEL_EXECUTE` | Model for generation & verification | `claude-sonnet-4-6` |
| `OUTPUT_DIR` | Directory for generated output | `./output` |

## Usage

### Generate a single question

```bash
uv run python -m src.cli generate
```

### Generate with specific parameters

```bash
# Specify grade
uv run python -m src.cli generate --grade 8

# Specify question style
uv run python -m src.cli generate --style with_chart

# Specify question type
uv run python -m src.cli generate --題型 選擇題
```

### Batch generation

```bash
# Generate 10 questions
uv run python -m src.cli generate --count 10

# Batch output as a single JSON array
uv run python -m src.cli generate --count 5 --batch
```

### Other options

```bash
# Set random seed for reproducibility
uv run python -m src.cli generate --seed 42

# Skip verification pass
uv run python -m src.cli generate --no-verify

# Specify output directory
uv run python -m src.cli generate --output ./my_output

# Dry run: show assembled prompt without calling LLM
uv run python -m src.cli generate --dry-run
```

## Question Output Format

Each generated question produces a JSON file following this schema:

```json
{
  "id": "q_20260405_001",
  "情境": "社會時事",
  "題型種類": "單一題",
  "題型": "選擇題",
  "數學思考": ["運用", "詮釋評估"],
  "學習內容": [
    {
      "編碼": "D-7-1",
      "說明": "統計圖表：..."
    }
  ],
  "題目": ["..."],
  "正確解題分析": ["..."],
  "圖片": "q_20260405_001.png",
  "verification": {
    "passed": true,
    "details": "..."
  },
  "metadata": {
    "grade": 7,
    "style": "with_chart",
    "model": "claude-sonnet-4-6",
    "generated_at": "2026-04-05T10:30:00Z",
    "seed": 42
  }
}
```

For image-based questions, a corresponding PNG file is generated in the same output directory.

### Image Rendering

The renderer (`src/renderer.py`) supports these chart types:

| Type | Renderer | Method |
|---|---|---|
| `histogram` | Hardcoded matplotlib | Direct bar chart |
| `boxplot` | Hardcoded matplotlib | Five-number summary boxes |
| `line_chart` | Hardcoded matplotlib | Data points or function plot |
| `pie_chart` | Hardcoded matplotlib | Pie/spinner with angle labels |
| `geometry` | **LLM-assisted** | Sonnet generates matplotlib code from `description` + `data`, then `exec()`'d |

For geometry diagrams, the LLM writes a self-contained matplotlib code snippet based on the `chart_spec.description` and `chart_spec.data` fields. This handles arbitrary geometry (L-shapes, triangles, coordinate planes, etc.) without needing hardcoded patterns for each type.

> **Note:** Two legacy hardcoded geometry patterns (courtyard, shadow) still exist in the code. These are marked for removal in `IMPLEMENTATION_PLAN.md` — they will be replaced by the LLM-assisted path in a future refactor.

## Data Sources

### Curriculum Data (學習內容.json)

Complete grades 1-12 math curriculum from Taiwan's 十二年國民基本教育 curriculum guidelines. Contains 14 grade levels with structured learning content entries, each including:
- `編碼`: content code (e.g., `N-7-1`, `S-8-6`, `D-9-3`)
- `學習內容條目及說明`: description
- `備註`: teaching notes
- `對應學習表現`: mapped performance standards

The full file is injected as LLM context so the model understands prerequisite knowledge (grades 1-6), target difficulty (grades 7-9), and what lies beyond (grades 10-12).

### Learning Performance Standards (學習表現.json)

Performance standards organized by learning stage (第一~第五學習階段), describing what students should be able to demonstrate at each level.

### Few-shot Examples

Structured examples converted from the Claude Desktop proof-of-concept, organized by question style:
- **text_only**: Pure text questions (e.g., arithmetic, algebra, sequences)
- **with_chart**: Questions involving statistical charts (histogram, boxplot, line chart)
- **with_image**: Questions involving geometric diagrams or visual elements
- **creative_scenario**: Real-world context questions (menus, stock prices, delivery plans)

### Past Exams

PDF files of actual national exam question sets (years 112-114) for reference style and difficulty calibration.

## Development

### Running tests

```bash
uv run pytest
```

### Code style

```bash
uv run ruff check src/
uv run ruff format src/
```

### Future: Web hosting

The project is designed with modular components (`sampler`, `context_builder`, `llm_client`, `verifier`, `renderer`) that can be imported directly by a web framework (FastAPI, Flask). The CLI is a thin wrapper around these components. Configuration loads from environment variables, making it container/cloud-ready.

## License

TBD
