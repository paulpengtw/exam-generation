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
│   ├── schemas.py                 # Pydantic data models (enums loaded from question_schemas.json)
│   ├── schema_loader.py           # Loads question_schemas.json and builds dynamic enums
│   └── data_loader.py             # Curriculum data loading & indexing
├── output/                        # Generated questions (gitignored)
├── question_schemas.json          # User-editable: allowed values for all question parameters
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
| `QUESTION_SCHEMAS_PATH` | Path to question parameter config JSON | `./question_schemas.json` |

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

## Customizing Question Parameters

All allowed values for question parameters are defined in `question_schemas.json` at the project root. Edit this file to add, remove, or rename options — no Python changes required.

All 5 categories use the same `{value, instruction}` object format:

```json
{
  "情境": [
    {"value": "個人", "instruction": ""},
    {"value": "社會時事", "instruction": "以近期新聞或社會議題為背景..."}
  ],
  "題型種類": [{"value": "單一題", "instruction": ""}, ...],
  "題型": [{"value": "選擇題", "instruction": ""}, ...],
  "數學思考": [{"value": "形成", "instruction": ""}, ...],
  "question_style": [
    {"value": "text_only", "instruction": "這是純文字題目..."},
    ...
  ]
}
```

- **`value`**: the parameter value used for sampling and CLI overrides.
- **`instruction`**: optional guidance injected into the LLM prompt when this value is selected. Leave empty (`""`) to omit. Style instructions land under `## 題目風格`; instructions for the other four categories land under `## 條件補充說明` (section omitted entirely if all are empty).
- **Adding a new `question_style`**: also create `data/few_shot/{value}/` with example JSON files.

To use an alternate config file: `QUESTION_SCHEMAS_PATH=/path/to/config.json uv run python -m src.cli generate`

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

## Execution Logic

Complete execution trace of `uv run python -m src.cli generate`, from first instruction to final output. See [`LOGIC.md`](LOGIC.md) for the full reference.

---

### Phase 1: Bootstrap & Configuration

**File: `src/cli.py`**

1. `main()` is called (line 181)
2. `parse_args()` parses CLI flags: `--grade`, `--style`, `--context`, `--set-type`, `--q-type`, `--count`, `--seed`, `--no-verify`, `--batch`, `--output`, `--dry-run`, `--env-file` (lines 39-65)
3. `Config.from_env(args.env_file)` loads configuration (line 188)

**File: `src/config.py`**

4. `Config.from_env()` reads `.env` file via `dotenv`, then pulls env vars (lines 22-36):
   - `LLM_API_KEY`, `LLM_BASE_URL` (endpoint)
   - `LLM_MODEL_PLAN` (default: `claude-opus-4-6`), `LLM_MODEL_EXECUTE` (default: `claude-sonnet-4-6`)
   - `OUTPUT_DIR` (default: `./output`), `DATA_DIR` (default: `./data`)
5. `config.validate()` ensures `LLM_API_KEY` is set (line 193 -> config.py:38-41)

**File: `src/cli.py`**

6. `config.output_dir.mkdir(parents=True, exist_ok=True)` ensures output directory exists (line 196)

---

### Phase 2: Data Loading

**File: `src/cli.py` lines 199-204, calling into `src/data_loader.py`**

7. `load_curriculum(data_dir / "curriculum" / "學習內容.json")` -> reads full K-12 curriculum JSON array (14 grade objects) (data_loader.py:11-14)
8. `load_performance_standards(data_dir / "curriculum" / "學習表現.json")` -> reads learning performance standards (data_loader.py:17-19)
9. `load_intro_text(Path("Introduction to \"學習表現\" and \"學習階段\".md"))` -> reads curriculum intro markdown (data_loader.py:56-60)
10. Build grade content index: for each grade in (7, 8, 9), `get_grade_content(curriculum, grade)` extracts `LearningContentItem` objects (編碼 + 說明) (data_loader.py:23-35). Result: `{7: [...], 8: [...], 9: [...]}` (cli.py:204)

---

### Phase 3: LLM Client Initialization

**File: `src/cli.py` line 207, `src/llm_client.py`**

11. `LLMClient(config)` creates an `OpenAI(api_key=..., base_url=...)` client (llm_client.py:16-21). Skipped if `--dry-run`.

---

### Phase 4: Generation Loop

**File: `src/cli.py` lines 216-278**

For each question `i` in `range(args.count)`:

#### 4A. Seed & RNG Setup (lines 221-222)

12. If `--seed` provided: `seed = base_seed + i`, else `seed = None`
13. `rng = random.Random(seed)` — deterministic if seeded

#### 4B. Parameter Sampling (lines 224-232)

**File: `src/sampler.py`**

14. `sample_params()` randomly selects (or uses CLI overrides for) each parameter (lines 18-69):
    - **grade**: `rng.choice([7, 8, 9])` (line 35)
    - **情境**: `rng.choice(list(QuestionContext))` — one of 6 options (line 38)
    - **題型種類**: `rng.choice(list(QuestionSetType))` — 單一題 or 題組題 (line 41)
    - **題型**: `rng.choice(list(QuestionType))` — one of 4 options (line 44)
    - **數學思考**: `rng.sample(all_thinking, randint(1,3))` — 1-3 of [形成, 運用, 詮釋評估] (lines 47-49)
    - **學習內容**: `rng.sample(available_content, randint(1,3))` — 1-3 items from selected grade's curriculum (lines 52-56)
    - **style**: `rng.choice(list(QuestionStyle))` — one of [text_only, with_chart, with_image, creative_scenario] (line 59)
15. Returns `SampledParams` Pydantic model (lines 61-69)

#### 4C. Prompt Construction (cli.py:241 -> generate_one lines 78-119)

**File: `src/context_builder.py`**

16. `build_system_prompt()` (lines 108-118) fills `SYSTEM_PROMPT_TEMPLATE` (lines 12-66) with:
    - `{curriculum_json}` — full K-12 curriculum as JSON string (via `get_full_curriculum_text`, data_loader.py:46-48)
    - `{performance_json}` — full performance standards as JSON string (via `get_full_performance_text`, data_loader.py:51-53)
    - `{intro_text}` — curriculum introduction markdown

17. `build_user_prompt()` (lines 121-173) fills `USER_PROMPT_TEMPLATE` (lines 68-98) with:
    - Sampled parameters (grade, 情境, 題型種類, 題型, 數學思考, 學習內容)
    - `{style_instruction}` — looked up from `STYLE_INSTRUCTIONS` dict (lines 100-105)
    - `{few_shot_examples}` — assembled via steps 18-20 below

#### 4D. Few-Shot Example Injection (context_builder.py:142-162)

**File: `src/data_loader.py` lines 63-72, then `src/context_builder.py` lines 142-162**

18. `load_few_shot_examples(few_shot_dir, style)` (data_loader.py:63-72):
    - Resolves path: `data/few_shot/{style}/` (e.g. `data/few_shot/with_chart/`)
    - `sorted(style_dir.glob("*.json"))` — loads ALL JSON files in alphabetical order
    - Each file is parsed as a JSON object or array and appended to the list

19. Flatten (context_builder.py:146-151): if any loaded file is a JSON array, each element is extracted. Single objects kept as-is. This creates a flat pool of individual examples.

20. Random selection (context_builder.py:154-155): `rng.sample(flat_examples, min(2, len(pool)))` picks 1-2 examples from the pool. Each is formatted as a markdown code block with `### 範例 {i}` header.

#### 4E. LLM Generation Call (cli.py:106)

**File: `src/llm_client.py`**

21. `client.generate_json(system_prompt, user_prompt)` (llm_client.py:41-44):
    - Calls `generate()` (lines 23-35): `openai.chat.completions.create()` with `model=model_execute` (Sonnet), `temperature=0.7`, `max_tokens=8192`
    - Messages: `[{"role": "system", ...}, {"role": "user", ...}]`
22. `extract_json(raw)` (llm_client.py:47-64) parses LLM text response:
    - First tries: regex for ` ```json ... ``` ` code block (line 50-52)
    - Then tries: raw text starting with `{` or `[` (lines 55-57)
    - Then tries: first `{...}` substring (lines 60-62)
    - Raises `ValueError` if all fail

#### 4F. Response Parsing (cli.py:109)

**File: `src/cli.py` lines 122-178**

23. `_parse_question(raw_json, question_id, params, model)` converts raw dict to `ExamQuestion`:
    - **學習內容** (lines 130-143): handles both dict and string formats, splits on `：`
    - **chart_spec** (lines 149-160): if present, parsed into `ChartSpec` Pydantic model
    - Returns `ExamQuestion` with all fields + `QuestionMetadata` (grade, style, model, seed)

---

### Phase 5: Verification (Two-Pass)

**File: `src/cli.py` lines 112-117, `src/verifier.py`**

24. If `--no-verify` not set, `verify_question(client, question)` is called (verifier.py:50-74):
    - Formats question text and solution into `VERIFICATION_USER_TEMPLATE` (lines 37-47)
    - Sends to LLM with `VERIFICATION_SYSTEM_PROMPT` (lines 10-35) — asks model to independently solve, then compare
    - Uses `client.generate()` (same Sonnet model) — **this is the second LLM call** (line 62)
    - Parses JSON response into `VerificationResult` (passed, answer_match, details) (lines 64-68)
    - On parse failure: returns `VerificationResult(passed=False)` (lines 69-74)
25. Result attached to `question.verification` (cli.py:115)

---

### Phase 6: Chart/Image Rendering

**File: `src/cli.py` lines 262-267, `src/renderer.py`**

26. If `question.chart_spec` exists, `render_chart(spec, img_path, llm_client)` is called (cli.py:265)

**File: `src/renderer.py`**

27. `render_chart()` (lines 50-75) dispatches by `chart_type`:

| chart_type | Handler | Lines |
|---|---|---|
| `"histogram"` | `_render_histogram()` | 78-113 |
| `"boxplot"` | `_render_boxplot()` | 116-182 |
| `"line_chart"` | `_render_line_chart()` | 185-232 |
| `"pie_chart"` | `_render_pie_chart()` | 235-272 |
| `"geometry"` | `_render_geometry()` | 275-303 |

28. For `"geometry"`, `_render_geometry()` uses a 3-tier approach (lines 275-303):
    - **Tier 1 — Hardcoded patterns** (lines 282-287): checks `data` keys for `"rectangle"+"triangle"` or `"lamp_height"` -> calls `_render_geometry_courtyard()` or `_render_geometry_shadow()`
    - **Tier 2 — LLM-assisted** (lines 290-293): `_render_geometry_via_llm()` (lines 405-464) sends geometry description to Sonnet, gets matplotlib code back, `exec()`s it — **this is a potential third LLM call**
    - **Tier 3 — Text fallback** (lines 296-303): renders description as centered text on blank canvas

29. All renderers save PNG via `fig.savefig(output_path, dpi=150)` and `plt.close(fig)`
30. On success, `question.圖片 = "{question_id}.png"` (cli.py:267)

---

### Phase 7: Output

**File: `src/cli.py` lines 269-290**

#### Single mode (default):

31. For each question: write `{question_id}.json` to output dir (lines 272-278)
    - `question.model_dump_json(indent=2, exclude_none=True)` serializes the Pydantic model

#### Batch mode (`--batch`):

32. After all questions: write `batch_{timestamp}.json` containing a JSON array of all questions (lines 281-288)

---

### LLM Calls Per Question

| # | Purpose | Model | File | Line |
|---|---|---|---|---|
| 1 | Generate question JSON | Sonnet (`model_execute`) | llm_client.py | 26-35 |
| 2 | Verify question (independent solve) | Sonnet (`model_execute`) | verifier.py | 62 |
| 3 | Generate geometry matplotlib code (only if `chart_type="geometry"` and no hardcoded match) | Sonnet (`model_execute`) | renderer.py | 426-429 |

### Randomness Points

| What | How | File | Line |
|---|---|---|---|
| Grade (7/8/9) | `rng.choice([7,8,9])` | sampler.py | 35 |
| 情境 | `rng.choice(list(QuestionContext))` | sampler.py | 38 |
| 題型種類 | `rng.choice(list(QuestionSetType))` | sampler.py | 41 |
| 題型 | `rng.choice(list(QuestionType))` | sampler.py | 44 |
| 數學思考 | `rng.sample(all, randint(1,3))` | sampler.py | 47-49 |
| 學習內容 | `rng.sample(grade_items, randint(1,3))` | sampler.py | 52-56 |
| Style | `rng.choice(list(QuestionStyle))` | sampler.py | 59 |
| Few-shot examples | `rng.sample(flat_pool, min(2,len))` | context_builder.py | 154-155 |

All randomness is seeded from a single `random.Random(seed)` per question — fully reproducible when `--seed` is provided.

## License

TBD
