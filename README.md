# exam-generation

LLM-driven generator for Taiwan math exam questions (default: grades 7-9, 第四學習階段; configurable via `question_schemas.json`). Ships with a CLI for local generation **and** a full web stack (FastAPI backend + React frontend + Postgres) for multi-user, browser-based use.

The system randomly samples question parameters (grade, type, context, learning content), assembles a structured prompt with few-shot examples, calls an LLM to generate the question, then runs a second verification pass. Output is JSON per question, with optional PNG images for chart/diagram-based questions.

> **Are you a teacher who just wants to deploy this so your school can use it?**
> Skip the rest of this README and follow **[DEPLOYMENT.md](DEPLOYMENT.md)** — a non-technical, browser-only walkthrough that takes you from zero to a live public URL with HTTPS.

## Architecture

```
graph TD
    A[Curriculum Data: 學習內容 + 學習表現] -->|full JSON injected| B(Sampler: random selection)
    B -->|grade / 題型 / 情境 / 學習內容| C{Context Builder}
    D[Few-shot Example DB] -->|matching examples| C
    C -->|assembled prompt| E[LLM: claude-sonnet-4-6 via OpenAI endpoint]
    E -->|generated question JSON| F[Verifier: independent solve + correction loop]
    F -->|passed| G[Output: JSON + optional PNG]
    F -->|failed| H[Corrector: targeted fix]
    H --> F
```

### Runnable surfaces

The same core modules (`src/sampler.py`, `src/context_builder.py`, `src/llm_client.py`, `src/verifier.py`, `src/renderer.py`) are reused by three entry points. For the full web request lifecycle (click → SSE → queue → worker → render), see [`FLOW.md`](FLOW.md).

| Surface | Code | Use case |
|---|---|---|
| **CLI** | `src/cli.py` | Local batch generation, scripted pipelines, debugging prompts |
| **FastAPI backend** | `server/app.py` (port 8000) | HTTP API: auth, generation, SSE streaming, history |
| **React frontend** | `web/` (Vite + React 19, port 3000) | Browser UI for teachers; talks to the FastAPI backend |

### Image Rendering

Questions can include images, described by an `ImageSpec` on the generated question. Two render paths:

| `render_mode` | Renderer | Method |
|---|---|---|
| `"chart"` | `src/renderer.py` `render_chart()` | Deterministic matplotlib — `histogram`, `boxplot`, `line_chart`, `pie_chart` |
| `"html"` | `src/html_renderer.py` `PlaywrightRenderer` | Sonnet writes HTML/CSS/SVG → Playwright screenshots to PNG |

The `"html"` path handles geometry diagrams, coordinate planes, tables, and any non-statistical visual. For social studies web generation, users can alternatively select GPT image generation, which sends the same image spec to `IMAGE_MODEL` (default `gpt-image2`) and writes the returned PNG directly. The entry point is `render_image()` in `src/renderer.py`, called from `generate_one()` in `src/cli.py`.

### Key Principles

- **No RAG.** All curriculum data and few-shot examples are injected directly as context.
- **Randomness is script-side.** The program selects grade, question type, context, learning content — not the LLM.
- **Verify + correct loop.** Sonnet generates → Sonnet verifies → on failure, Sonnet applies a minimal targeted correction and re-verifies (up to `max_retries` times). Only the wrong field changes; classification, metadata, and correct fields are preserved.
- **OpenAI-compatible endpoint.** Uses the `openai` SDK for endpoint diversity. Opus plans, Sonnet executes.

## Project Structure

```
exam-generation/
├── data/
│   ├── curriculum/
│   │   ├── 學習內容.json          # Full K-12 math curriculum content (grades 1-12)
│   │   └── 學習表現.json          # Math learning performance standards
│   ├── few_shot/
│   │   ├── text_only/             # Text-only question examples
│   │   ├── with_chart/            # Questions with chart descriptions
│   │   ├── with_image/            # Questions with image descriptions
│   │   └── creative_scenario/     # Creative real-world scenario examples
│   ├── social_studies/
│   │   ├── curriculum/
│   │   │   ├── schema_meta.csv          # 學習階段 + grades (researcher-editable)
│   │   │   ├── schema_parameters.csv    # Parameter values + instructions (6 categories)
│   │   │   ├── learning_performance.csv # 學習表現標準 → system prompt
│   │   │   ├── learning_content.csv     # 學習內容 by grade → system prompt
│   │   │   └── 範例_*.csv               # Reference examples (never loaded)
│   │   ├── few_shot/
│   │   │   ├── few_shot_examples.csv    # Few-shot examples (long format, grouped by 範例編號)
│   │   │   ├── 範例_few_shot_examples.csv  # Reference example (never loaded)
│   │   │   └── {style}/                 # Legacy JSON few-shot (if any)
│   │   ├── example_exams/               # PISA/NAER reference exam PDFs
│   │   └── csv_填寫指南.md              # zh-TW filler guide for all 5 CSVs
│   └── example_exams/
│       ├── 112P_Math.pdf          # Past exam: year 112
│       ├── 113P_Math.pdf          # Past exam: year 113
│       └── 114P_Math.pdf          # Past exam: year 114
├── src/                           # Core engine (used by CLI + server)
│   ├── cli.py                     # CLI entry point
│   ├── config.py                  # Configuration & env management
│   ├── sampler.py                 # Random parameter selection
│   ├── context_builder.py         # Prompt assembly with few-shot injection
│   ├── llm_client.py              # OpenAI-compatible LLM client
│   ├── verifier.py                # Independent answer verification pass
│   ├── corrector.py               # Targeted correction pass for failed-verification questions
│   ├── renderer.py                # matplotlib PNG for chart questions (render_mode="chart")
│   ├── html_renderer.py           # Playwright HTML→PNG for image questions (render_mode="html")
│   ├── schemas.py                 # Pydantic data models (enums loaded from question_schemas.json)
│   ├── schema_loader.py           # Loads question_schemas.json and builds dynamic enums
│   ├── data_loader.py             # Curriculum data loading & indexing
│   └── social_studies/            # Social studies (PISA reading literacy) codepath
│       ├── schema_loader.py       # Builds schema dict from schema_meta.csv + schema_parameters.csv
│       ├── data_loader.py         # Loads learning_performance/content CSVs + few-shot CSV
│       ├── context_builder.py     # Prompt assembly; injects ## 課程綱要參考 into system prompt
│       ├── sampler.py             # Social studies parameter sampler
│       └── ...                    # verifier, corrector (reuse src/ equivalents)
├── server/                        # FastAPI backend
│   ├── app.py                     # Application factory (uvicorn entry: server.app:create_app)
│   ├── config.py                  # Server-only config (JWT, DB, CORS)
│   ├── db.py                      # Async SQLAlchemy session
│   ├── models.py                  # ORM models (users, generations, etc.)
│   ├── rate_limit.py              # slowapi limiter
│   ├── auth/                      # Sign-up, login, JWT
│   ├── generate/                  # Generation endpoints + SSE streaming
│   └── utility/                   # Health, schema, misc routes
├── web/                           # React + Vite + TypeScript frontend
│   ├── src/                       # Components, pages, stores
│   ├── nginx.conf                 # Static asset + API proxy config
│   └── Dockerfile                 # Multi-stage build → nginx:alpine
├── alembic/                       # Database migrations
├── tests/                         # Pytest suite
├── scripts/                       # One-off utility scripts
├── output/                        # CLI-generated questions (gitignored)
├── question_schemas.json          # User-editable: 學習階段, grades, and allowed values for all question parameters
├── docker-compose.yml             # db + backend + frontend for local full-stack run
├── Dockerfile.backend             # Backend image (Python 3.11 + Playwright)
├── IMPLEMENTATION_PLAN.md         # Planned refactors and known tech debt
├── DEPLOYMENT.md                  # Teacher-facing deployment walkthrough
├── CLAUDE.md                      # AI assistant conventions
├── FLOW.md                        # ASCII flow chart: web Generate request lifecycle
├── LOGIC.md                       # Full execution trace
├── README.md
├── pyproject.toml
└── .env.example
```

## Setup

### Option A: CLI only

Use this if you want to generate questions locally without running the web stack.

```bash
# Prerequisites: Python 3.11+ and uv (https://docs.astral.sh/uv/)

git clone <repo-url>
cd exam-generation

uv sync
cp .env.example .env
# Edit .env — at minimum, set LLM_API_KEY

uv run python -m src.cli generate
```

### Option B: Full stack with docker-compose

Use this if you want the browser UI locally. Brings up Postgres, the FastAPI backend, and the React frontend.

```bash
# Prerequisites: Docker + docker-compose

cp .env.example .env
# Edit .env — set LLM_API_KEY, DB_PASSWORD, JWT_SECRET at minimum

docker-compose up --build
# Frontend: http://localhost:3000
# Backend API: http://localhost:8000
# Postgres: localhost:5432
```

The backend runs `alembic upgrade head` automatically on startup (see `server/app.py` lifespan), so no manual migration step is needed locally.

### Option C: Deploy to the public internet

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for a step-by-step guide aimed at non-technical users (Railway and Render, with custom domain + HTTPS).

### Configuration

Environment variables (set in `.env` or export directly):

| Variable | Used by | Description | Default |
|---|---|---|---|
| `LLM_API_KEY` | CLI + server | API key for the OpenAI-compatible endpoint | **(required)** |
| `LLM_BASE_URL` | CLI + server | Base URL for the API endpoint | `https://api.anthropic.com/v1` |
| `LLM_MODEL_PLAN` | CLI + server | Model for planning tasks | `claude-opus-4-6` |
| `LLM_MODEL_EXECUTE` | CLI + server | Model for generation & verification | `claude-sonnet-4-6` |
| `IMAGE_API_KEY` | CLI + server | API key for optional social-studies GPT image generation | — |
| `IMAGE_BASE_URL` | CLI + server | Base URL for the image generation endpoint | `https://api.openai.com/v1` |
| `IMAGE_MODEL` | CLI + server | Image generation model used when GPT image mode is selected | `gpt-image2` |
| `LLM_RATE_LIMIT_DELAY` | CLI + server | Seconds to wait before each API call (prevents 429 errors) | `0` |
| `LLM_MAX_RETRIES` | CLI + server | Max correction attempts when verification fails | `3` |
| `OUTPUT_DIR` | CLI | Directory for generated output | `./output` |
| `QUESTION_SCHEMAS_PATH` | CLI + server | Path to question parameter config JSON | `./question_schemas.json` |
| `SOCIAL_STUDIES_CURRICULUM_DIR` | CLI + server | Directory containing social-studies curriculum CSVs | `./data/social_studies/curriculum` |
| `DATABASE_URL` | server | Async SQLAlchemy database URL | `sqlite+aiosqlite:///./dev.db` |
| `DB_PASSWORD` | docker-compose | Password for the bundled Postgres service | `changeme` |
| `JWT_SECRET` | server | Secret used to sign auth tokens — must be a long random string | **(required for server)** |
| `FRONTEND_URL` | server | Frontend origin; controls CORS allowlist | `http://localhost:3000` |
| `EMAIL_BACKEND` | server | `ses` for AWS SES, `console` to log emails to stdout | `console` |
| `AWS_REGION` | server (if `EMAIL_BACKEND=ses`) | AWS region for SES | `us-east-1` |
| `SES_FROM_EMAIL` | server (if `EMAIL_BACKEND=ses`) | Verified SES sender address | — |
| `EMAIL_WHITELIST` | server | Comma-separated list of allowed magic-link recipients. Supports exact addresses and `*@domain` wildcards. Empty = allow all. | — (allow all) |

## CLI Usage

### Generate a single question

```bash
uv run python -m src.cli generate
```

### Generate with specific parameters

```bash
# Specify grade
uv run python -m src.cli generate --grade 8

# Specify question style (single value forces it)
uv run python -m src.cli generate --style with_chart

# Specify question type (single value forces it)
uv run python -m src.cli generate --q-type 選擇題

# Restrict to a subset — sampler picks randomly from the given values
uv run python -m src.cli generate --q-type 選擇題 封閉式建構反應題
uv run python -m src.cli generate --style chart_only text_only

# Combine both
uv run python -m src.cli generate --q-type 選擇題 是非題 --style with_chart creative_scenario
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

# Cap correction attempts when verification fails (default 3)
uv run python -m src.cli generate --max-retries 2
```

## Running the server and web app

### Backend only

```bash
uv sync --extra web
uv run uvicorn server.app:create_app --factory --reload --port 8000
```

Routes live in:
- `server/auth/routes.py` — sign-up, login, password reset
- `server/generate/routes.py` — question generation, SSE streaming
- `server/utility/routes.py` — health, schema introspection

Migrations run automatically on app startup via the FastAPI lifespan handler. To run them manually:

```bash
uv run alembic upgrade head
```

### Frontend only

```bash
cd web
npm install
npm run dev     # Vite dev server, default http://localhost:5173
npm run build   # Production build → web/dist
```

The production image (`web/Dockerfile`) builds the static bundle and serves it with `nginx:alpine` on port 80 (mapped to host `3000` by docker-compose). See `web/nginx.conf` for the backend proxy rules.

## Question Output Format

Each generated question produces a JSON file following this schema:

```json
{
  "id": "q_20260405_001",
  "情境": ["社會時事", "科學"],
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
    "answer_match": true,
    "details": "...",
    "my_answer": "...",
    "provided_answer": "...",
    "chart_verification": {
      "chart_data_match": true,
      "chart_labels_correct": true,
      "chart_details": "圖表數據與題目描述一致"
    }
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

For image-based questions, a corresponding PNG file is generated in the same output directory. `chart_verification` is only present when a chart image was rendered and sent to the verifier; it is omitted (`null`) for text-only questions.

### Image Rendering

Questions can specify an image via `image_spec` (or legacy `chart_spec`) in the LLM output. The `render_mode` field selects the renderer:

**`render_mode: "chart"`** — `render_chart()` in `src/renderer.py`:

| `chart_type` | Renderer | Output |
|---|---|---|
| `histogram` | Hardcoded matplotlib | Bar chart |
| `boxplot` | Hardcoded matplotlib | Five-number summary boxes |
| `line_chart` | Hardcoded matplotlib | Data points or function plot |
| `pie_chart` | Hardcoded matplotlib | Pie with angle labels |

**`render_mode: "html"`** — `_generate_html_via_llm()` in `src/renderer.py` asks Sonnet to write a self-contained HTML/CSS/SVG document from `description` + `data`; then `PlaywrightRenderer` in `src/html_renderer.py` screenshots it to PNG. Used for geometry diagrams, coordinate planes, tables, menus, and any non-statistical visual.

## Customizing Question Parameters

All allowed values for question parameters are defined in `question_schemas.json` at the project root. Edit this file to add, remove, or rename options — no Python changes required.

The file also specifies the target 學習階段 and grades:

```json
{
  "學習階段": "第四學習階段",
  "grades": [7, 8, 9],
  ...
}
```

All 5 question parameter categories use the same `{value, instruction}` object format:

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

### Social studies parameters

For social studies exam generation, all allowed parameter values live in the CSV files under `data/social_studies/curriculum/`:

| CSV | Controls |
|---|---|
| `schema_meta.csv` | 學習階段 label, target grades |
| `schema_parameters.csv` | Values + LLM instructions for 情境, 題型種類, 題型, 文本形式, 閱讀歷程, question_style |
| `learning_performance.csv` | 學習表現標準 injected into system prompt |
| `learning_content.csv` | 學習內容 by grade injected into system prompt |
| `few_shot/few_shot_examples.csv` | Few-shot examples injected into user prompt |

Changes take effect on the next run — no rebuild required. See **[`data/social_studies/csv_填寫指南.md`](data/social_studies/csv_填寫指南.md)** for the complete field-by-field guide (zh-TW). Reference files prefixed with `範例_` in the same folders demonstrate correct formatting but are never loaded by the system.

## Data Sources

### Curriculum Data (學習內容.json)

Complete grades 1-12 math curriculum from Taiwan's 十二年國民基本教育 curriculum guidelines. Contains 14 grade levels with structured learning content entries, each including:
- `編碼`: content code (e.g., `N-7-1`, `S-8-6`, `D-9-3`)
- `學習內容條目及說明`: description
- `備註`: teaching notes
- `對應學習表現`: mapped performance standards

The full file is injected as LLM context so the model understands prerequisite knowledge, target difficulty, and what lies beyond — the exact range is driven by `question_schemas.json`.

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

## Deployment

For step-by-step instructions aimed at non-technical users, follow **[DEPLOYMENT.md](DEPLOYMENT.md)**.

For developers, the short version:

| Target | Notes |
|---|---|
| **Railway** | Recommended for non-technical users. GitHub-connected, managed Postgres, automatic HTTPS, ~US$5/mo hobby plan. Auto-detects `Dockerfile.backend` and `web/Dockerfile`. |
| **Render** | Same model as Railway — GitHub-connected web services, free HTTPS. Add one Web Service per Dockerfile + a Postgres add-on. |
| **Self-hosted (VPS / school server)** | `docker-compose up -d` on any host with Docker. Put a reverse proxy (Caddy/Traefik) in front for TLS. |

In all cases the runtime configuration is identical to the env var table above. The backend exposes port `8000`; the frontend image exposes port `80` (proxies `/api` to the backend via `web/nginx.conf`).

## Execution Logic

Complete execution trace of `uv run python -m src.cli generate`, from first instruction to final output. See [`LOGIC.md`](LOGIC.md) for the full reference.

---

### Phase 1: Bootstrap & Configuration

**File: `src/cli.py`**

1. `main()` is called (line 215)
2. `parse_args()` parses CLI flags: `--grade`, `--style`, `--context`, `--set-type`, `--q-type`, `--count`, `--seed`, `--no-verify`, `--batch`, `--output`, `--dry-run`, `--env-file` (lines 43-70). `--style` and `--q-type` each accept one or more values (`nargs="+"`) — multiple values define a random selection pool.
3. `Config.from_env(args.env_file)` loads configuration (line 222)

**File: `src/config.py`**

4. `Config.from_env()` reads `.env` file via `dotenv`, then pulls env vars (lines 22-36):
   - `LLM_API_KEY`, `LLM_BASE_URL` (endpoint)
   - `LLM_MODEL_PLAN` (default: `claude-opus-4-6`), `LLM_MODEL_EXECUTE` (default: `claude-sonnet-4-6`)
   - `LLM_RATE_LIMIT_DELAY` (default: `0`) — seconds slept before every `generate()` call to avoid 429 errors
   - `OUTPUT_DIR` (default: `./output`), `DATA_DIR` (default: `./data`)
5. `config.validate()` ensures `LLM_API_KEY` is set (line 227 -> config.py:38-41)

**File: `src/cli.py`**

6. `config.output_dir.mkdir(parents=True, exist_ok=True)` ensures output directory exists (line 230)

---

### Phase 2: Data Loading

**File: `src/cli.py` lines 233-238, calling into `src/data_loader.py`**

7. `load_curriculum(data_dir / "curriculum" / "學習內容.json")` -> reads full K-12 curriculum JSON array (14 grade objects) (data_loader.py:11-14)
8. `load_performance_standards(data_dir / "curriculum" / "學習表現.json")` -> reads learning performance standards (data_loader.py:17-20)
9. `load_intro_text(Path("Introduction to \"學習表現\" and \"學習階段\".md"))` -> reads curriculum intro markdown (data_loader.py:59-63)
10. Build grade content index: for each grade in `question_schemas.json["grades"]`, `get_grade_content(curriculum, grade)` extracts `LearningContentItem` objects (編碼 + 說明) (data_loader.py:23-35). Result: `{7: [...], 8: [...], 9: [...]}` (cli.py:238)

---

### Phase 3: LLM Client Initialization

**File: `src/cli.py` line 207, `src/llm_client.py`**

11. `LLMClient(config)` creates an `OpenAI(api_key=..., base_url=...)` client (llm_client.py:19-24). Skipped if `--dry-run`.
    `PlaywrightRenderer` also started here once and reused across all questions (cli.py:245-253).

---

### Phase 4: Generation Loop

**File: `src/cli.py` lines 269-310**

For each question `i` in `range(args.count)`:

#### 4A. Seed & RNG Setup (lines 270-271)

12. If `--seed` provided: `seed = base_seed + i`, else `seed = None`
13. Seed passed to `sample_params()` which creates its own `random.Random(seed)` — deterministic if seeded

#### 4B. Parameter Sampling (lines 273-281)

**File: `src/sampler.py`**

14. `sample_params()` randomly selects (or uses CLI overrides for) each parameter (lines 21-77):
    - **grade**: `rng.choice(_GRADES)` — values from `question_schemas.json["grades"]` (line 38)
    - **情境**: `rng.randint(1, len(all_contexts))` → `rng.sample(all_contexts, count)` — 1-N options (lines 41-46)
    - **題型種類**: `rng.choice(list(QuestionSetType))` — 單一題 or 題組題 (line 49)
    - **題型**: `rng.choice(list(QuestionType))` — one of 4 options (line 52)
    - **數學思考**: `rng.sample(all_thinking, randint(1,3))` — 1-3 of [形成, 運用, 詮釋評估] (lines 55-57)
    - **學習內容**: `rng.sample(available_content, randint(1,3))` — 1-3 items from selected grade's curriculum (lines 60-64)
    - **style**: `rng.choice(list(QuestionStyle))` — one of [text_only, with_chart, with_image, creative_scenario] (line 67)
15. Returns `SampledParams` Pydantic model (lines 69-77)

#### 4C. Prompt Construction (cli.py:241 -> generate_one lines 78-119)

**File: `src/context_builder.py`**

16. `build_system_prompt()` (lines 131-150) fills `SYSTEM_PROMPT_TEMPLATE` (lines 23-130) with:
    - `{curriculum_json}` — full K-12 curriculum as JSON string (via `get_full_curriculum_text`, data_loader.py:49-51)
    - `{performance_json}` — full performance standards as JSON string (via `get_full_performance_text`, data_loader.py:54-56)
    - `{intro_text}` — curriculum introduction markdown

17. `build_user_prompt()` (lines 153-230) fills `USER_PROMPT_TEMPLATE` with:
    - Sampled parameters (grade, 情境, 題型種類, 題型, 數學思考, 學習內容)
    - `{style_instruction}` — looked up from `_INSTRUCTIONS` dict (context_builder.py:14, schema-driven via `build_instructions()`)
    - `{few_shot_examples}` — assembled via steps 18-20 below

#### 4D. Few-Shot Example Injection (context_builder.py:142-162)

**File: `src/data_loader.py` lines 63-72, then `src/context_builder.py` lines 142-162**

18. `load_few_shot_examples(few_shot_dir, style)` (data_loader.py:66-75):
    - Resolves path: `data/few_shot/{style}/` (e.g. `data/few_shot/with_chart/`)
    - `sorted(style_dir.glob("*.json"))` — loads ALL JSON files in alphabetical order
    - Each file is parsed as a JSON object or array and appended to the list

19. Flatten (context_builder.py:199-205): if any loaded file is a JSON array, each element is extracted. Single objects kept as-is. This creates a flat pool of individual examples.

20. Random selection (context_builder.py:208-209): `rng.sample(flat_examples, min(2, len(pool)))` picks 1-2 examples from the pool. Each is formatted as a markdown code block with `### 範例 {i}` header.

#### 4E. LLM Generation Call (cli.py:106)

**File: `src/llm_client.py`**

21. `client.generate_json(system_prompt, user_prompt)` (llm_client.py:70-73):
    - Calls `generate()` (lines 26-40): `openai.chat.completions.create()` with `model=model_execute` (Sonnet), `temperature=0.7`, `max_tokens=8192`
    - Messages: `[{"role": "system", ...}, {"role": "user", ...}]`
22. `extract_json(raw)` (llm_client.py:76-93) parses LLM text response:
    - First tries: regex for ` ```json ... ``` ` code block (line 79-81)
    - Then tries: raw text starting with `{` or `[` (lines 84-86)
    - Then tries: first `{...}` substring (lines 88-91)
    - Raises `ValueError` if all fail

#### 4F. Response Parsing (cli.py:115)

**File: `src/cli.py` lines 145-212**

23. `_parse_question(raw_json, question_id, params, model)` (cli.py:145-212) converts raw dict to `ExamQuestion`:
    - **學習內容** (lines 153-166): handles both dict and string formats, splits on `：`
    - **image_spec / chart_spec** (lines 171-194): handles both `image_spec` (new) and `chart_spec` (legacy) field names; parsed into `ImageSpec` Pydantic model
    - Returns `ExamQuestion` with all fields + `QuestionMetadata` (grade, style, model, seed)

---

### Phase 5: Image Rendering + Verification + Correction Loop

Image rendering happens **before** verification inside `generate_one()` so the verifier can inspect the image.

**File: `src/cli.py` inside `generate_one()` (lines 117-132), `src/renderer.py`**

24. If `question.chart_spec` exists, `render_image(spec, img_path, question_text, html_renderer, llm_client)` (renderer.py:271) is called. Dispatches by `render_mode`:

**File: `src/renderer.py`**

| `render_mode` | Path | Lines |
|---|---|---|
| `"chart"` | `render_chart()` → `_render_histogram/boxplot/line_chart/pie_chart()` | 50-71 |
| `"html"` | `_generate_html_via_llm()` (LLM call #2) → `html_renderer.render()` | 271-308 |

25. On render success: `question.圖片 = "{question_id}.png"`, `chart_image_path` = absolute PNG path

**File: `src/cli.py` inside `generate_one()`, `src/verifier.py`**

26. If `--no-verify` not set, `verify_question(client, question, chart_image_path)` is called (verifier.py) — **LLM call #3**:
    - Formats question text and solution into `VERIFICATION_USER_TEMPLATE`
    - Sends to LLM via `client.generate_with_image()` — text + optional base64 PNG in a multimodal message
    - Parses JSON response into `VerificationResult(passed, answer_match, details, my_answer, provided_answer, chart_verification)` where `chart_verification: ChartVerificationResult | None` holds `{chart_data_match, chart_labels_correct, chart_details}`
    - On parse failure: returns `VerificationResult(passed=False)`
27. Result attached to `question.verification`

#### 5B. Correction loop (`src/cli.py` `generate_with_corrections()`, `src/corrector.py`)

28. If `verification.passed=False` and retries remain, `correct_question(client, question, verification, chart_image_path)` (`src/corrector.py`) sends the failed question JSON + verifier's `details` (+ `my_answer`/`provided_answer` + optional `chart_verification`) back to Sonnet — multimodal if a PNG exists and chart verification failed. Returns a new `ExamQuestion` with only `題目`, `正確解題分析`, and `chart_spec` mutable; all classification and metadata fields are restored from the original.
29. If `chart_spec` actually changed (`!=` compare), re-render the PNG. Otherwise reuse the existing PNG.
30. Re-verify (**LLM call #3** again). Loop up to `max_retries` total correction passes (default 3, overridable via `--max-retries` / `LLM_MAX_RETRIES`).

---

### Phase 6: Output

**File: `src/cli.py` lines 313-330**

#### Single mode (default):

31. For each question: write `{question_id}.json` to output dir (lines 315-320)
    - `question.model_dump_json(indent=2, exclude_none=True)` serializes the Pydantic model

#### Batch mode (`--batch`):

32. After all questions: write `batch_{timestamp}.json` containing a JSON array of all questions (lines 323-330)

---

### LLM Calls Per Question

| # | Purpose | Model | File | Line |
|---|---|---|---|---|
| 1 | Generate question JSON | Sonnet (`model_execute`) | llm_client.py | 26-40 |
| 2 | Generate HTML image (only when `render_mode="html"`) | Sonnet (`model_execute`) | renderer.py | 343 |
| 3 | Verify question + image (multimodal) | Sonnet (`model_execute`) | verifier.py (`generate_with_image`) | — |
| 4 | Correction (when verification fails; multimodal if chart was the issue) | Sonnet (`model_execute`) | corrector.py | — |

Calls 3 + 4 may repeat up to `max_retries` times (default 3).

### Randomness Points

| What | How | File | Line |
|---|---|---|---|
| Grade | `rng.choice(_GRADES)` from `question_schemas.json` | sampler.py | 38 |
| 情境 | `rng.sample(all, randint(1, len))` | sampler.py | 41-46 |
| 題型種類 | `rng.choice(list(QuestionSetType))` | sampler.py | 49 |
| 題型 | `rng.choice(list(QuestionType))` | sampler.py | 52 |
| 數學思考 | `rng.sample(all, randint(1,3))` | sampler.py | 55-57 |
| 學習內容 | `rng.sample(grade_items, randint(1,3))` | sampler.py | 60-64 |
| Style | `rng.choice(list(QuestionStyle))` | sampler.py | 67 |
| Few-shot examples | `rng.sample(flat_pool, min(2,len))` | context_builder.py | 208-209 |

All randomness is seeded from a single `random.Random(seed)` per question — fully reproducible when `--seed` is provided.

## License

TBD
