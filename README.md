# exam-generation

LLM-driven generator for Taiwan math exam questions (default: grades 7-9, 第四學習階段; configurable via `question_schemas.json`), with full support for 108課綱 社會領域 (歷史/地理/公民與社會/跨科) question generation via the parallel `src/social_studies/` pipeline, and 108課綱 自然科學 (PISA-style scientific literacy framing) question generation via the parallel `src/natural_sciences/` pipeline. Ships with a CLI for local generation **and** a full web stack (FastAPI backend + React frontend + Postgres) for multi-user, browser-based use.

The system randomly samples question parameters (grade, type, context, learning content), assembles a structured prompt with few-shot examples, calls an LLM to generate the question, then runs a second verification pass. Output is JSON per question, with optional PNG images for chart/diagram-based questions.

> **Are you a teacher who just wants to deploy this so your school can use it?**
> Skip the rest of this README and follow **[DEPLOYMENT.md](DEPLOYMENT.md)** — a non-technical, browser-only walkthrough that takes you from zero to a live public URL with HTTPS.

## Architecture

```
graph TD
    A[Curriculum Data: 學習內容 + 學習表現] -->|full JSON injected| B(Sampler: random selection)
    B -->|grade / 題型 / 情境 / 學習內容| C{Context Builder}
    D[Few-shot Example DB] -->|matching examples| C
    C -->|assembled prompt| E["LLM: plan/verify claude-opus-4-6; execute gemini-3.1-pro-preview"]
    E -->|generated question JSON| F[Verifier: independent solve + correction loop]
    F -->|passed| G[Output: JSON + optional PNG]
    F -->|failed| H[Corrector: targeted fix]
    H --> F
```

### Runnable surfaces

The same core modules (`src/sampler.py`, `src/context_builder.py`, `src/llm_client.py`, `src/verifier.py`, `src/renderer.py`) are reused by three entry points. For the full web request lifecycle (click → SSE → queue → worker → render), see [`FLOW.md`](FLOW.md).

| Surface | Code | Use case |
|---|---|---|
| **CLI** | `src/cli.py` / `src/social_studies/cli.py` / `src/natural_sciences/cli.py` | Local batch generation, scripted pipelines, debugging prompts |
| **FastAPI backend** | `server/app.py` (port 8000) | HTTP API: auth, generation, SSE streaming, history |
| **React frontend** | `web/` (Vite + React 19, port 3000) | Browser UI for teachers; talks to the FastAPI backend |

### Image Rendering

Questions can include images, described by an `ImageSpec` on the generated question. Two render paths:

| `render_mode` | Renderer | Method |
|---|---|---|
| `"chart"` | `src/renderer.py` `render_chart()` | Deterministic matplotlib — `histogram`, `boxplot`, `line_chart`, `pie_chart` |
| `"html"` | `src/html_renderer.py` `PlaywrightRenderer` | `gemini-3.1-pro-preview` writes HTML/CSS/SVG → Playwright screenshots to PNG |

The `"html"` path handles geometry diagrams, coordinate planes, tables, and any non-statistical visual. Math and curriculum-subject generation accept an `image_generation_mode` parameter — set it to `gpt_image` to send the image spec to `IMAGE_MODEL` (default `gpt-image2`) and write the returned PNG directly, bypassing the Playwright and matplotlib paths. Social studies and natural sciences support both shared 題組 images (`question.chart_spec`) and per-小題 images (`subquestions[*].chart_spec`). The web UI exposes a main `圖片生成模式`; per-小題 rows can override it, or leave it blank to inherit the main mode. Generated `subquestions[*].image_generation_mode` is output metadata only and does not override the submitted renderer choice. The API/CLI default mode is `html`; the web form UI defaults to `gpt_image` (GPT 生圖). The entry point is `render_image()` in `src/renderer.py`, called from `generate_one()`.

### Key Principles

- **No RAG.** All curriculum data and few-shot examples are injected directly as context.
- **Randomness is script-side.** The program selects grade, question type, context, learning content — not the LLM.
- **Two-stage generation (社會 / 自然).** For social studies and natural sciences, question generation runs a two-stage pipeline: a **文本生成器** call produces the shared 核心問題, 文本, and 取材來源 plus an N-entry 子題 plan; then N **子題產生器** calls each write one full 子題 concurrently (`ThreadPoolExecutor`, capped by `SUBGEN_MAX_CONCURRENCY`, default 6). A 子題產生器 call that raises or returns unparseable output is retried with a fresh LLM call for that slot only, up to `SUBGEN_RETRIES` times (default 1), before the slot is dropped. The assembled 題組 then flows through image rendering → verification → correction unchanged. Math generation stays a single flat call.
- **Verify + correct loop.** `gemini-3.1-pro-preview` generates → `claude-opus-4-6` verifies → on failure, the 修正 tier (inheriting execute by default) applies a minimal targeted correction before another 驗證 pass (up to `max_retries` times). Only the wrong field changes; classification, metadata, and correct fields are preserved.
- **Per-request LLM provider dispatch.** The provider is resolved from the model id on each call: `claude-*` → Anthropic SDK (prompt caching, streaming, system param); `gemini-*` → Gemini via its OpenAI-compatible endpoint; `gpt-*/o-series` → OpenAI; unknown ids → Anthropic (proxy deployments). The defaults are `claude-opus-4-6` for planning and 驗證 and `gemini-3.1-pro-preview` for execution, all at `high` effort; 修正 inherits execution. Both `LLM_API_KEY` and `GEMINI_API_KEY` are required for this configuration.

## Project Structure

```
exam-generation/
├── data/
│   ├── curriculum/
│   │   ├── 學習內容.json          # Full K-12 math curriculum content (grades 1-12, legacy source)
│   │   └── 學習表現.json          # Math learning performance standards (legacy source)
│   ├── math/
│   │   └── curriculum/
│   │       ├── learning_content.json         # Reshaped math 學習內容 (288 entries, 5 學習階段)
│   │       ├── learning_performance.json     # Reshaped math 學習表現 (131 entries)
│   │       ├── core_competencies.json        # 27 數-E/J/U-A1..C3 核心素養 codes
│   │       └── learning_performance_intro.md # Math 學習表現 framework intro
│   ├── few_shot/
│   │   ├── text_only/             # Text-only question examples
│   │   ├── with_chart/            # Questions with chart descriptions
│   │   ├── with_image/            # Questions with image descriptions
│   │   └── creative_scenario/     # Creative real-world scenario examples
│   ├── social_studies/
│   │   ├── curriculum/
│   │   │   ├── schema_meta.csv              # 學習階段 + grades (researcher-editable)
│   │   │   ├── schema_parameters.csv        # Parameter values + instructions (6 categories)
│   │   │   ├── learning_content.json        # 108課綱 學習內容 (472 entries, 學習階段 二–五; ODT-sourced 對應學習表現)
│   │   │   ├── learning_performance.json    # 108課綱 學習表現標準 (26 codes; ODT-sourced 對應學習內容)
│   │   │   ├── learning_performance_intro.md # NAER 學習表現 framework chapter → system prompt
│   │   │   ├── core_competencies.json       # 108課綱 核心素養 codes → sampler pool
│   │   │   └── 範例_*.csv                   # Reference examples (never loaded)
│   │   ├── few_shot/
│   │   │   ├── few_shot_examples.csv        # Few-shot examples (long format, grouped by 範例編號; header-only — Channel-1 corpus retired in #542, awaiting ICCS-native content from #544)
│   │   │   ├── 範例_few_shot_examples.csv   # Reference example (never loaded)
│   │   │   ├── *.json                       # JSON few-shot examples filtered by embedded style
│   │   │   └── images/                      # Images attached to CSV few-shot examples
│   │   ├── example_exams/               # PISA/NAER reference exam PDFs
│   │   └── csv_填寫指南.md              # zh-TW filler guide for JSON curriculum files + CSVs
│   ├── natural_sciences/
│   │   ├── curriculum/
│   │   │   ├── schema_meta.csv              # 學習階段 + grades (researcher-editable)
│   │   │   ├── schema_parameters.csv        # Parameter values + instructions (情境/情境子類別/題型/科學能力/題目內容類型 with parent-child column for 情境子類別)
│   │   │   ├── learning_content.json        # 108課綱 自然科學 學習內容 (757 entries) + 跨科概念 taxonomy (48 entries)
│   │   │   ├── learning_performance.json    # 108課綱 自然科學 學習表現 (99 entries; stages 二–五)
│   │   │   ├── core_competencies.json       # 108課綱 自然科學 核心素養 (9 entries)
│   │   │   └── converted/課綱各項指標列表.xlsx # Canonical workbook used by the build script
│   │   └── few_shot/
│   │       ├── Simple-multiple-choice/      # JSON few-shot examples for 單選題
│   │       ├── Complex-multiple-choice/     # JSON few-shot examples for 複選題
│   │       └── Constructed-response/        # JSON few-shot examples for 建構反應題
│   └── example_exams/
│       ├── 112P_Math.pdf          # Past exam: year 112
│       ├── 113P_Math.pdf          # Past exam: year 113
│       └── 114P_Math.pdf          # Past exam: year 114
├── src/                           # Core engine (used by CLI + server)
│   ├── common/                    # Subject-agnostic loaders shared by math + social studies
│   │   ├── curriculum_loader.py   # 學習內容 / 學習表現 JSON loaders + allowed_* filters (parameterized by data_dir + 科目→prefix map)
│   │   ├── core_competency_loader.py # 核心素養 JSON loader + build_core_competency_enum + allowed_competencies(stage)
│   │   └── planner.py             # Subject-agnostic 核心問題 planner (callers supply prompt templates)
│   ├── cli.py                     # CLI entry point
│   ├── config.py                  # Configuration & env management
│   ├── sampler.py                 # Curriculum-aware math sampler (學習內容/學習表現/核心素養/題目內容類型/subject_filter); owns _MATH_SUBJECT_TO_PREFIXES + grade_to_learning_stage()
│   ├── context_builder.py         # Prompt assembly with curriculum injection + few-shot; CONTENT_TYPE_INSTRUCTIONS dict
│   ├── llm_client.py              # OpenAI-compatible LLM client
│   ├── verifier.py                # Independent answer verification pass (math; stricter "明確錯誤" stance)
│   ├── corrector.py               # Targeted correction pass; frozen fields incl. 核心素養/學習內容/學習表現/出題概念/題目內容類型
│   ├── renderer.py                # matplotlib PNG for chart questions (render_mode="chart")
│   ├── html_renderer.py           # Playwright HTML→PNG for image questions (render_mode="html")
│   ├── schemas.py                 # Math Pydantic models incl. CoreCompetency enum (27 數-* codes) and QuestionSubject (數與量/代數/幾何/統計與機率/跨領域)
│   ├── schema_loader.py           # Loads question_schemas.json and builds dynamic enums
│   ├── planner.py                 # Math planner shim — wraps src.common.planner with 數學領域 prompts
│   ├── data_loader.py             # Curriculum data loading + CSV-driven few-shot loader (image-manifest aware, with per-style JSON fallback)
│   └── social_studies/            # Social studies (108課綱 社會領域素養導向) codepath
│       ├── schemas.py             # ExamQuestion, SubQuestion, SubQuestionConfig, RubricEntry, LearningContentRef, QuestionSubject
│       ├── schema_loader.py       # Builds schema dict from schema_meta.csv + schema_parameters.csv
│       ├── curriculum_loader.py   # Shim over src.common.curriculum_loader (owns _SUBJECT_TO_PREFIXES + 社會 data dir)
│       ├── core_competency_loader.py # Shim over src.common.core_competency_loader
│       ├── planner.py             # Shim over src.common.planner with 社會領域 prompts
│       ├── data_loader.py         # Loads few-shot CSV (learning content/performance via curriculum_loader shim)
│       ├── context_builder.py     # Prompt assembly; injects ## 課程綱要參考, ## 指定條件, and per-小題 configs
│       ├── sampler.py             # Picks grade, 科目, per-小題 題型, 學習內容_pool, 學習表現_pool, 核心素養, per-小題 configs
│       └── ...                    # verifier, corrector (reuse src/ equivalents)
│   └── natural_sciences/          # Natural sciences (108課綱 自然科學 + PISA Scientific Literacy) codepath
│       ├── schemas.py             # ExamQuestion (with subquestions[]), SubQuestion (科學能力 replaces 核心素養; 出題指示 field), SubQuestionConfig (per-小題 overrides: question_type/instruction/content_type/image_generation_mode/word limits/LC/LP), ScienceCompetency (6 codes: 能力一/二/三 + 環境能力一/二/三), QuestionSubContext (PISA sub-context parented to 情境). No QuestionSubject — 科目 is fixed as 自然科學.
│       ├── schema_loader.py       # Builds schema dict from schema_meta.csv + schema_parameters.csv; handles parent column on 情境子類別
│       ├── curriculum_loader.py   # Shim over src.common.curriculum_loader; overrides allowed_learning_content/performance to skip subject filtering (科目 is fixed)
│       ├── core_competency_loader.py # Shim over src.common.core_competency_loader; NaturalCoreCompetency enum, prefix "自"
│       ├── planner.py             # Shim over src.common.planner with PISA-Science prompt template
│       ├── sampler.py             # Picks grade, 情境 + 情境子類別 (parent-child constrained), 題型, 科學能力 (1–2 of 6), 學習表現 (1–2), 學習內容 (1–3 preferentially derived from chosen 學習表現 via 對應學習內容); no 科目 buckets. Accepts sub_question_count (3-7), question_word_limit, option_word_limit, subquestion_configs — resolves per-小題 SubQuestionConfig rows with random q_type fill and LC/LP backfill (parallel to social studies).
│       ├── context_builder.py     # PISA-Science prompt assembly; injects 跨科概念 taxonomy + ## 課程綱要參考 block into system prompt
│       ├── data_loader.py         # Hybrid few-shot loader: folder-per-題型 JSON (Simple/Complex-multiple-choice/Constructed-response) + optional CSV
│       ├── verifier.py            # Explicit "寬鬆通過、只攔重大問題" stance — more lenient than math's "明確錯誤"
│       └── corrector.py           # Frozen fields: 學習內容/學習表現/科學能力/出題概念/科目/年級; minimal targeted correction
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
├── scripts/
│   ├── connect_curriculum_from_odt.py  # One-shot ODT importer: populates 對應學習表現/對應學習內容 cross-links in the two JSON files
│   ├── build_math_curriculum.py        # Reproducibly emits data/math/curriculum/* from legacy data/curriculum/* + social_studies core_competencies template
│   └── ...                            # Other one-off utility scripts
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

bash scripts/setup.sh   # installs all extras (fastapi, sqlalchemy, …) + Playwright Chromium binary
cp .env.example .env
# Edit .env — at minimum, set LLM_API_KEY and GEMINI_API_KEY

uv run python -m src.cli generate
```

### Option B: Full stack with docker-compose

Use this if you want the browser UI locally. Brings up Postgres, the FastAPI backend, and the React frontend.

```bash
# Prerequisites: Docker + docker-compose

cp .env.example .env
# Edit .env — set LLM_API_KEY, GEMINI_API_KEY, DB_PASSWORD, JWT_SECRET at minimum

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
| `GEMINI_API_KEY` | CLI + server | Required for the default configuration, together with `LLM_API_KEY`: Gemini API key for the execute tier | — |
| `GEMINI_BASE_URL` | CLI + server | Base URL for the Gemini OpenAI-compatible endpoint | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `OPENAI_API_KEY` | CLI + server | API key for OpenAI models — required when using a `gpt-*` or o-series model | — |
| `OPENAI_BASE_URL` | CLI + server | Base URL for the OpenAI endpoint | `https://api.openai.com/v1` |
| `LLM_API_KEY` | CLI + server | Required for the default configuration, together with `GEMINI_API_KEY`: Anthropic API key for the plan and 驗證 tiers, and for Anthropic web-search fact-check | — |
| `LLM_BASE_URL` | CLI + server | Base URL for the Anthropic endpoint | `https://api.anthropic.com/v1` |
| `LLM_MODEL_PLAN` | CLI + server | Model for planning tasks | `claude-opus-4-6` |
| `LLM_MODEL_EXECUTE` | CLI + server | Model for generation | `gemini-3.1-pro-preview` |
| `LLM_MODEL_VERIFY` | CLI + server | 驗證模型; explicitly empty = follow the execute model at call time | `claude-opus-4-6` |
| `LLM_MODEL_CORRECT` | CLI + server | 修正模型; empty = follow the execute model at call time | (empty) |
| `LLM_EFFORT_PLAN` | CLI + server | Planning effort | `high` |
| `LLM_EFFORT_EXECUTE` | CLI + server | Execution effort | `high` |
| `LLM_EFFORT_VERIFY` | CLI + server | 驗證 effort; explicitly empty = inherit execute effort at call time | `high` |
| `LLM_EFFORT_CORRECT` | CLI + server | 修正 effort; empty = inherit execute effort at call time | (empty) |
| `IMAGE_API_KEY` | CLI + server | API key for optional GPT image generation (used by math, social studies, and natural sciences when `image_generation_mode=gpt_image`) | — |
| `IMAGE_BASE_URL` | CLI + server | Base URL for the image generation endpoint | `https://api.openai.com/v1` |
| `IMAGE_MODEL` | CLI + server | Image generation model used when GPT image mode is selected | `gpt-image2` |
| `LLM_RATE_LIMIT_DELAY` | CLI + server | Seconds to wait before each API call (prevents 429 errors) | `0` |
| `LLM_MAX_RETRIES` | CLI + server | Max correction attempts when verification fails | `3` |
| `LLM_TEMPERATURE` | CLI + server | Sampling temperature forwarded to the API; unset = provider default; ignored for `claude-opus-4-6` because adaptive thinking is enabled, and for models that reject sampling params (claude-opus-5, claude-sonnet-5, claude-fable-5, claude-opus-4-7, claude-opus-4-8 and dated variants) | (unset) |
| `SUBGEN_MAX_CONCURRENCY` | CLI + server | Max concurrent 子題產生器 LLM calls per 題組 (SS/NS only) | `6` |
| `SUBGEN_RETRIES` | CLI + server | Extra fresh-call attempts for a failed/unparseable 子題產生器 slot before that 子題 is dropped (SS/NS only; `0` = drop on first failure) | `1` |
| `OUTPUT_DIR` | CLI | Directory for generated output | `./output` |
| `QUESTION_SCHEMAS_PATH` | CLI + server | Path to question parameter config JSON | `./question_schemas.json` |
| `SOCIAL_STUDIES_CURRICULUM_DIR` | CLI + server | Directory containing social-studies curriculum CSVs | `./data/social_studies/curriculum` |
| `MATH_CURRICULUM_DIR` | server | Directory containing reshaped math curriculum JSON (learning_content, learning_performance, core_competencies, learning_performance_intro.md) | `./data/math/curriculum` |
| `NATURAL_SCIENCES_CURRICULUM_DIR` | CLI + server | Directory containing natural-sciences curriculum CSVs + JSON files | `./data/natural_sciences/curriculum` |
| `DATABASE_URL` | server | Async SQLAlchemy database URL | `sqlite+aiosqlite:///./dev.db` |
| `DB_PASSWORD` | docker-compose | Password for the bundled Postgres service | `changeme` |
| `JWT_SECRET` | server | Secret used to sign auth tokens — must be a long random string | **(required for server)** |
| `JWT_EXPIRE_DAYS` | server | Login token lifetime in days | `7` |
| `SESSION_RENEWAL_THRESHOLD_MINUTES` | server | Minutes of token lifetime remaining that trigger session renewal | `360` |
| `FRONTEND_URL` | server | Frontend origin; controls CORS allowlist | `http://localhost:3000` |
| `EMAIL_BACKEND` | server | `ses` for AWS SES, `console` to log emails to stdout | `console` |
| `AWS_REGION` | server (if `EMAIL_BACKEND=ses`) | AWS region for SES | `us-east-1` |
| `SES_FROM_EMAIL` | server (if `EMAIL_BACKEND=ses`) | Verified SES sender address | — |
| `EMAIL_WHITELIST` | server | Comma-separated list of allowed magic-link recipients. Supports exact addresses and `*@domain` wildcards. Empty = allow all. | — (allow all) |

## CLI Usage

### Resolve before generation

All three CLIs resolve their sampling pins before generation. The `resolve`
subcommand prints one JSON object, `{"payload": ..., "drawn": [...]}`, without
constructing an LLM client; `generate` prints the same resolved record to
stdout before it calls the generator, then passes every resolved value into the
existing sampler fill. With `--dry-run`, the record is wrapped in
`--- BEGIN RESOLVED PAYLOAD ---` / `--- END RESOLVED PAYLOAD ---` before the
prompt preview; normal generation logs and saved-question notices remain on
stderr.

```bash
# Math
uv run python -m src.cli resolve --seed 42 --grade 8
uv run python -m src.cli generate --seed 42 --grade 8

# Social studies (`subject_filter` is the printed payload field)
uv run python -m src.social_studies.cli resolve --seed 42 --grade 8 --subject 歷史
uv run python -m src.social_studies.cli generate --seed 42 --grade 8 --subject 歷史

# Natural sciences (`sub_context` is the printed payload field)
uv run python -m src.natural_sciences.cli resolve --seed 42 --grade 8
uv run python -m src.natural_sciences.cli generate --seed 42 --grade 8
```

The resolve commands accept the same subject-specific parameter/pin flags as
their `generate` commands. For `--count > 1`, each record is resolved with the
same `seed + index` rule used by the resolver.

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

### Curriculum-aware overrides (108課綱)

The math sampler now picks 核心素養, 學習表現, 題目內容類型, and an optional 科目 focus alongside the legacy parameters. Each can be overridden from the CLI:

```bash
# Focus on a single 科目 strand (數與量 / 代數 / 幾何 / 統計與機率 / 跨領域)
uv run python -m src.cli generate --subject-filter 代數

# Override 核心素養 codes (one or more 數-E/J/U-A1..C3 values)
uv run python -m src.cli generate --core-competency 數-J-A2 數-J-B1

# Override 學習內容 / 學習表現 codes
uv run python -m src.cli generate --learning-content A-7-1 A-7-3
uv run python -m src.cli generate --learning-performance a-IV-2

# Pick a specific 題目內容類型 (純文字 / 含圖片 / graphs/charts/tables / customized)
uv run python -m src.cli generate --content-type 純文字

# Seed the question with user-supplied 主題 / 題幹 / 選項 / 核心問題
uv run python -m src.cli generate --topic "二次函數的應用" --core-question "如何用二次函數模型化拋體運動？"
uv run python -m src.cli generate --passage "..." --options "(A)..." "(B)..." "(C)..." "(D)..."

# Image generation mode (html / gpt_image — see IMAGE_MODEL env var)
uv run python -m src.cli generate --image-generation-mode html

# Composite example
uv run python -m src.cli generate \
  --subject-filter 代數 --core-competency 數-J-A2 \
  --content-type 純文字 --topic "二次函數的應用" --count 1
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

### Social studies (108課綱 社會領域素養導向)

```bash
# Generate one 題組 (subject sampled randomly)
uv run python -m src.social_studies.cli generate

# Restrict 科目 to a subset — sampler picks randomly from given values
uv run python -m src.social_studies.cli generate --subject 歷史 地理

# Force a single subject + grade
uv run python -m src.social_studies.cli generate --subject 公民與社會 --grade 9

# Cross-subject 題組
uv run python -m src.social_studies.cli generate --subject 跨科

# Web UI equivalent: 科目 dropdown on the social-studies Generate form
# Options: 全部（隨機）/ 歷史 / 地理 / 公民與社會 / 跨科
# Selecting 全部 omits the filter; sampler picks one subject randomly per question.
# Maps to GET /api/generate?subject_filter=歷史 (or omitted for 全部).

# Social-studies parent items are always 題組題. The web/API controls
# per-小題 behavior through:
# sub_question_count=3..7 and subquestion_configs=[{question_type,
# instruction, question_word_limit, option_word_limit, content_type,
# image_generation_mode}, ...].
# Blank/missing question_type values are sampled randomly per 小題.
# instruction is persisted as subquestions[*].出題指示 and guides that 小題. Explicit per-小題 `learning_content` and `learning_performance` arrays are injected into that 子題's prompt with a hard must-use constraint and are forced verbatim into the output SubQuestion, overriding whatever the LLM writes; empty arrays fall back to the global sampled pool.
# content_type=含圖片 or graphs/charts/tables asks the model for a per-小題
# chart_spec; image_generation_mode only chooses html vs gpt_image rendering.
# These are web/API-only today; there are no dedicated CLI flags for them.

# Override sampled 學習內容 codes (1–3 values)
uv run python -m src.social_studies.cli generate --learning-content 歷Ka-Ⅳ-1 地Aa-Ⅳ-2

# Override sampled 學習表現 codes (1–2 values)
uv run python -m src.social_studies.cli generate --learning-performance 社1b-Ⅳ-1

# Override 核心素養 codes
uv run python -m src.social_studies.cli generate --core-competency 社-J-A2

# Pass 文本出題指示 to guide the 文本生成器 for every 題組 (blank behaves like omission)
uv run python -m src.social_studies.cli generate --text-instruction "請聚焦地方自治中的證據比較"

# Batch, seeded
uv run python -m src.social_studies.cli generate --count 5 --seed 1 --batch
```

Most math CLI flags (`--grade`, `--q-type`, `--count`, `--seed`, `--no-verify`, `--max-retries`, `--batch`, `--dry-run`, `--output`) work identically for social studies. Social-studies parent items are fixed as 題組題; in the web UI, 題型 is configured per 小題 through `subquestion_configs[].question_type` instead of top-level `q_type`. Social studies does not use `--style`.

Math now supports the same curriculum-aware parameter surface (`--subject-filter`, `--core-competency`, `--learning-content`, `--learning-performance`, `--content-type`, `--topic`, `--passage`, `--options`, `--core-question`) — see [Curriculum-aware overrides](#curriculum-aware-overrides-108課綱) above.

### Natural sciences (108課綱 自然科學 PISA框架)

```bash
# Generate one 題組 (PISA-Science format)
uv run python -m src.natural_sciences generate

# Specify grade (default pool: [7, 8, 9])
uv run python -m src.natural_sciences generate --grade 8

# Restrict 題型 — sampler picks from the given pool
uv run python -m src.natural_sciences generate --q-type Simple-multiple-choice Complex-multiple-choice

# Override PISA-Science 科學能力 pool (1–2 of 能力一/二/三 + 環境能力一/二/三)
uv run python -m src.natural_sciences generate --science-competency 能力一 環境能力二

# Pin 情境 (PISA: Personal / Local-and-national / Global)
uv run python -m src.natural_sciences generate --context Personal

# Override 情境子類別 (must be a child of the chosen 情境)
uv run python -m src.natural_sciences generate --sub-context 健康

# Override 學習內容 / 學習表現 codes
uv run python -m src.natural_sciences generate --learning-content INc-IV-1 INc-IV-2
uv run python -m src.natural_sciences generate --learning-performance tr-IV-1

# Pass 文本出題指示 to guide the 文本生成器 for every 題組 (blank behaves like omission)
uv run python -m src.natural_sciences generate --text-instruction "請聚焦電磁波的能量傳遞概念"

# Batch, seeded
uv run python -m src.natural_sciences generate --count 5 --seed 1 --batch
```

**Natural sciences vs social studies differences:**

- No `--subject` flag — `科目` is fixed as `自然科學` on all subquestions (no 生物/物理/化學/地球科學 buckets). The sampler draws 學習內容 and 學習表現 without subject filtering.
- `--science-competency` replaces `--core-competency`. There is no separate `--core-competency` override.
- `--sub-context` is a single value and must be a valid child of the chosen `--context` (the parent-child relationship is defined in `schema_parameters.csv`).
- 題型 values are PISA-aligned: `Simple-multiple-choice`, `Complex-multiple-choice`, `Constructed-response`.
- 學習內容 pool is preferentially derived from the chosen 學習表現 codes' `對應學習內容` cross-links, then falls back to the full stage pool.
- 社會領域 reads 學習階段 once at import from `schema_meta.csv` (currently 第四學習階段, grades 7–9), rather than deriving it from the sampled 年級 as 數學 and 自然科學 do. All 26 shipped 社會領域 學習表現 entries cover only 第四學習階段, so per-grade derivation would currently be a no-op and would yield an empty 學習表現 pool if the grade range were widened to 10–12. If that data is ever extended, update `schema_meta.csv` and switch to per-grade derivation. `src/social_studies/context_builder.py` reads the same module-level stage into the prompt, so it and `src/social_studies/sampler.py` must be updated in lockstep.
- The verifier uses a lenient "寬鬆通過、只攔重大問題" stance (distinct from math's strict "明確錯誤").

Most flags work identically to social studies: `--grade`, `--q-type`, `--count`, `--seed`, `--no-verify`, `--max-retries`, `--batch`, `--dry-run`, `--output`, `--content-type`, `--image-generation-mode`, `--text-instruction` (sets the 文本出題指示 for every 題組; blank behaves like omission). Natural sciences does not use `--style`.

Natural-sciences parent items are 題組題 with 3–7 subquestions. Per-小題 configuration (sub_question_count, subquestion_configs with question_type / instruction / learning_content / learning_performance / word limits / content_type / image_generation_mode; explicit per-小題 learning_content/learning_performance are forced into the output SubQuestion verbatim) is web/API-only — there are no dedicated CLI flags. The 子題設定 panel in the web form works identically for natural sciences and social studies. Blank per-小題 question_type values are sampled randomly; instruction is persisted as subquestions[*].出題指示. Top-level 文本字數限制 (passage word-count hint) is available on all subjects; top-level 選項字數限制 (per-option A–D limits) is math-only.

## Running the server and web app

### Backend only

```bash
uv sync --extra web
uv run uvicorn server.app:create_app --factory --reload --port 8000
```

### Staging smoke test

Set `BASE_URL` (and `SMOKE_AUTH_TOKEN`, or use the existing magic-link prompt), then run `bash scripts/verify_figure_kind_diversity_staging.sh`.
The script resolves the fixed 社會領域 image scenario first, submits the completed payload, waits for its persisted history record, and reports each 圖像種類, pairwise PASS/FAIL, and the figure-policy trail.

Routes live in:
- `server/auth/routes.py` — sign-up, login, password reset
- `server/generate/routes.py` — question generation, SSE streaming. `POST /api/plan-core-questions` branches on `body.subject` (`"math"` | `"social_studies"` | `"natural_sciences"`, default `"social_studies"`); math derives `learning_stage` from `body.grade` via `src.sampler.grade_to_learning_stage`. `GenerateParams` accepts curriculum-aware fields (`subject_filter`, `core_competency`, `learning_content`, `learning_performance`, `content_type`, `topic`, `passage`, `options`, `core_question`, `sub_context`, `science_competency`, `disable_reference_fewshot` (bool, default false, social studies + natural sciences only)) plus per-小題 fields shared by social studies and natural sciences (`sub_question_count`, `question_word_limit`, `option_word_limit`, `subquestion_configs`). `subquestion_configs` may include `question_type`, `instruction`, `learning_content`, and `learning_performance`; missing question types are randomly sampled per 小題, instructions are persisted as `subquestions[*].出題指示`, and empty LC/LP arrays fall back to the global sampled pool. Natural sciences accepts the same subquestion_configs fields; blank question_type slots are filled from the PISA-Science 題型 pool. All three subjects share the same request model.
- `server/utility/routes.py` — health, schema introspection. `GET /api/schemas?subject=math` augments the base math schema file with `科目` (4 strands), `題目內容類型` (4 entries), and `學習表現` filtered by `學習階段` (from `data/math/curriculum/learning_performance.json`). `subject=natural_sciences` builds schema from `schema_parameters.csv` + `learning_performance.json` + `learning_content.json` (PISA-Science dimensions: 情境/情境子類別/科學能力/題型/題目內容類型).

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

For image-based questions, a corresponding PNG file is generated in the same output directory. Social-studies and natural-sciences per-小題 images use filenames like `{question_id}_sq{序號}.png`; SSE result payloads embed these as `subquestions[*].image_base64`, and the web UI / ODT export render them inline with the matching 小題. `chart_verification` is only present when a chart image was rendered and sent to the verifier; it is omitted (`null`) for text-only questions.

Social studies and natural sciences use a 題組 shape with `subquestions[]`. For social studies, the parent item is locked as 題組題 and the top-level `題型` is a legacy/primary value, while each `subquestions[*].題型` may vary independently. The web UI sets social-studies 題型 on each 小題 row; blank rows are sampled randomly by the backend. Per-小題 free-text instructions are persisted as `subquestions[*].出題指示`. Social-studies and natural-sciences subquestions can include per-小題 `題目內容類型`, `image_generation_mode`, `chart_spec`, `圖片`, and `image_base64` when the prompt or web/API row config asks for visual material. For social studies and natural sciences, `subquestions[]` is populated by N parallel 子題產生器 LLM calls (one per 子題); the assembled question then proceeds through image rendering, verification, and correction as usual.

### Image Rendering

Questions can specify an image via `image_spec` (or legacy `chart_spec`) in the LLM output. The submitted `image_generation_mode` is checked first: `gpt_image` sends the spec directly to the image API, while `html` uses `render_mode` to select the renderer:

**`render_mode: "chart"`** — `render_chart()` in `src/renderer.py`:

| `chart_type` | Renderer | Output |
|---|---|---|
| `histogram` | Hardcoded matplotlib | Bar chart |
| `boxplot` | Hardcoded matplotlib | Five-number summary boxes |
| `line_chart` | Hardcoded matplotlib | Data points or function plot |
| `pie_chart` | Hardcoded matplotlib | Pie with angle labels |

**`render_mode: "html"`** — `_generate_html_via_llm()` in `src/renderer.py` asks `gemini-3.1-pro-preview` to write a self-contained HTML/CSS/SVG document from `description` + `data`; then `PlaywrightRenderer` in `src/html_renderer.py` screenshots it to PNG. Used for geometry diagrams, coordinate planes, tables, menus, and any non-statistical visual.

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

For social studies exam generation, parameter schemas live in CSVs; curriculum data (學習內容, 學習表現, 核心素養) lives in JSON files — all under `data/social_studies/curriculum/`:

| File | Controls |
|---|---|
| `schema_meta.csv` | 學習階段 label, target grades |
| `schema_parameters.csv` | Values + LLM instructions for 情境, 題型種類, 題型, 文本形式, 閱讀歷程, 科目 (歷史/地理/公民與社會/跨科). Rubric scoring uses `2/1/0/0X` convention (`0X` = 未作答). |
| `learning_content.json` | 108課綱 社會領域 學習內容 — 472 entries spanning 學習階段 二–五 (55 entries mapped at 第四學習階段; 57 shared entries have `科目=""` and appear in every subject's pool). `對應學習表現` cross-links populated from official NAER ODT 呼應表. Sampler draws 1–3 codes per 題組 filtered by 學習階段 + 科目; injected into `## 指定條件` (user prompt) and `## 課程綱要參考` (system prompt). |
| `learning_performance.json` | 108課綱 社會領域 學習表現標準 — 26 codes (歷/地/公/社 prefixes); `對應學習內容` cross-links from ODT. Sampler draws 1–2 codes per 題組; same injection pattern as 學習內容. |
| `learning_performance_intro.md` | Official NAER 學習表現 framework chapter (構面/項目/編碼規則 + full 條目 list) → injected as `### 學習表現架構說明` in system prompt. |
| `core_competencies.json` | 108課綱 核心素養 codes → sampler pool; override with `--core-competency`. |
| `few_shot/few_shot_examples.csv` | Few-shot examples injected into user prompt (long format, one row per subquestion; columns include `小題序號`, `小題年級`, `小題科目`, `核心素養`, `學習內容`, `學習表現`, `出題概念`, `小題題型`, `答案`, `答案解析`, `評分規準`). Header-only as of #542 (PISA-era rows retired); awaiting ICCS-native content from #544. |

The social-studies web form labels the top-level `content_type` as `文本素材類型` and exposes a main `圖片生成模式`. The web form defaults `文本素材類型` to `含圖片` (if present in the subject's schema, else the first available entry), and `圖片生成模式` to `gpt_image` (GPT 生圖). These are UI-only defaults — the API and CLI still default `image_generation_mode` to `html`. Social-studies parent items are always 題組題; when users set `子題數量` (3–7), the form sends `subquestion_configs` as a JSON array string so each 小題 can carry its own `question_type`, `instruction`, `learning_content`, `learning_performance`, 題目字數限制, 選項字數限制, 題目內容類型, and 圖片產生方式. Per-小題 `learning_content` and `learning_performance` are picked via a `SearchPicker` in the web UI — a searchable text input + autocomplete dropdown that searches the full available curriculum pool (filtered by subject and grade, not limited to globally-selected items); an empty per-小題 selection means "use the global sampled pool" (backend default). When non-empty, the codes are forced exactly into the output SubQuestion.學習內容/學習表現 (overriding LLM output), with 說明 populated from the curriculum instruction maps. The global 學習表現 and 學習內容 selectors default to `SearchPicker` (搜尋模式); a "切換勾選模式" button switches both to the checkbox grid and "切換搜尋模式" reverts — backend payload is identical either way. Blank per-小題 `question_type` values are sampled randomly by the backend. Per-小題 `instruction` is injected into the prompt and persisted as `subquestions[*].出題指示`; correction retries preserve it as frozen metadata. Per-小題 `content_type` controls whether visual material is required: `含圖片` and `graphs/charts/tables` ask the model to output that 小題's own `chart_spec`. Per-小題 `image_generation_mode` only selects the renderer backend (`html` vs `gpt_image`); by itself it does not require an image, and a blank value inherits the main/request-level image mode. Renderer precedence is submitted per-小題 mode → submitted main mode; model-emitted `image_generation_mode` is preserved in output only after being normalized to the effective renderer. Malformed `subquestion_configs` JSON is ignored by the backend with a warning. Natural sciences uses the same 子題設定 web panel and subquestion_configs encoding; 題型 values are PISA-aligned (Simple-multiple-choice / Complex-multiple-choice / Constructed-response). The top-level 文本字數限制 field (passage / 題組文本 word-count hint) is shown and sent for all three subjects; the top-level 選項字數限制 (per-option A–D) is shown and sent for math only — for 題組 subjects (SS + NS), per-小題 word limits live in the 子題設定 panel.

**Cross-subject 學習表現:** `社_*` codes (社1a/1b/2a/2b/2c/3a/3b/3c/3d-Ⅳ-*) are general 社會領域 standards that apply across all subjects — they appear in every subject's sampler pool, not only 跨科. This follows 108課綱 design.

**Re-populating curriculum JSON from NAER:** Run `scripts/connect_curriculum_from_odt.py` whenever NAER publishes an updated 呼應表. It reads the official ODT and overwrites `對應學習表現` / `對應學習內容` in the two JSON files.

Changes take effect on the next run — no rebuild required. See **[`data/social_studies/csv_填寫指南.md`](data/social_studies/csv_填寫指南.md)** for the field-by-field guide (zh-TW). Reference files prefixed with `範例_` in the same folders demonstrate correct formatting but are never loaded by the system.

### Natural sciences curriculum data

Natural-sciences curriculum assets live under `data/natural_sciences/curriculum/`. The JSON files are generated from `converted/課綱各項指標列表.xlsx` with `python3 scripts/build_natural_sciences_curriculum.py`. The CSV files are researcher-editable, paralleling the social-studies layout.

| File | Contains |
|---|---|
| `schema_meta.csv` | 學習階段 label + grades list (researcher-editable) |
| `schema_parameters.csv` | Parameter values + instructions for 情境, 情境子類別, 題型種類, 題型, 科學能力, 題目內容類型. 情境子類別 rows include a `parent` column linking each sub-context to its parent 情境 value. |
| `learning_content.json` | `學習階段_to_grades`, top-level `跨科概念` taxonomy (48 entries), and `學習內容` (757 entries). Each content row has `value`, `學習階段`, `科目`, `條目說明`, `備註`, `對應學習表現`. |
| `learning_performance.json` | `學習階段_to_grades` and `學習表現` (99 entries). Each performance row has `value`, `學習階段`, `科目`, `構面`, `項目`, `說明`, `對應學習內容`. |
| `core_competencies.json` | 自然科學領域 核心素養 (9 entries). |

The stage map covers 第二學習階段 grades 3-4, 第三 5-6, 第四 7-9, and 第五 10-12. High-school learning content is bucketed by `科目` (`生物`, `物理`, `化學`, `地球科學`); earlier-stage shared rows use an empty `科目`.

**Sampler 科目 handling:** Unlike social studies which filters by 科目 buckets (歷史/地理/公民與社會), natural sciences deliberately skips subject filtering — `科目` is fixed as `"自然科學"` on all subquestions. The `allowed_learning_content` / `allowed_learning_performance` helpers in `src/natural_sciences/curriculum_loader.py` override the shared-loader signature to omit the subject parameter. This is intentional: the natural sciences 108課綱 treats all content strands (生物/物理/化學/地球科學) as a single integrated domain for the 第四學習階段 sampler pool.

Few-shot examples live under `data/natural_sciences/few_shot/`, organized into one folder per 題型: `Simple-multiple-choice/`, `Complex-multiple-choice/`, `Constructed-response/`. Each folder accepts JSON files (parallel to the math `data/few_shot/{style}/` layout) or a `few_shot_examples.csv` (parallel to social studies). The repo currently includes 28 JSON examples across these folders.

Natural sciences is a fully runnable third pipeline (CLI + web), parallel to social studies. See [Natural sciences CLI](#natural-sciences-108課綱-自然科學-pisa框架) above for the CLI surface.

## Data Sources

### Curriculum Data (學習內容.json)

Complete grades 1-12 math curriculum from Taiwan's 十二年國民基本教育 curriculum guidelines. Contains 14 grade levels with structured learning content entries, each including:
- `編碼`: content code (e.g., `N-7-1`, `S-8-6`, `D-9-3`)
- `學習內容條目及說明`: description
- `備註`: teaching notes
- `對應學習表現`: mapped performance standards

The full file is injected as LLM context so the model understands prerequisite knowledge, target difficulty, and what lies beyond — the exact range is driven by `question_schemas.json`.

`data/curriculum/{學習內容,學習表現}.json` remain the legacy K-12 sources read by `src/data_loader.py` for system-prompt curriculum injection.

### Math 108課綱 reshaped curriculum (`data/math/curriculum/`)

For curriculum-aware sampling (核心素養, 學習表現, 學習內容, 科目 filtering), the math pipeline uses a reshaped set of JSON files mirroring the social-studies layout. Loaded via the shared `src.common.curriculum_loader` / `src.common.core_competency_loader`:

| File | Contents |
|---|---|
| `learning_content.json` | 288 entries across 5 學習階段. Row shape `{value, 學習階段, 科目, 條目說明, 備註, 對應學習表現}`. `科目` is a single-letter strand prefix N / A / F / R / S / G / D / P (mapped by `_MATH_SUBJECT_TO_PREFIXES` in `src/sampler.py`: 數與量={N,n}, 代數={A,F,R,a,f,r}, 幾何={S,G,s,g}, 統計與機率={D,P,d,p}). |
| `learning_performance.json` | 131 entries; row shape `{value, 學習階段, 科目, 說明}`. |
| `core_competencies.json` | 27 數-E/J/U-A1..C3 codes (synthesized from the social studies template with `value` rewritten from 社- to 數-). |
| `learning_performance_intro.md` | NAER framework chapter injected as `### 學習表現架構說明` in the math system prompt. |

These four files are rebuilt reproducibly by `scripts/build_math_curriculum.py` from the legacy `data/curriculum/{學習內容,學習表現}.json` sources + the social studies core_competencies template. Re-run if the upstream curriculum data changes.

### Learning Performance Standards (學習表現.json)

Performance standards organized by learning stage (第一~第五學習階段), describing what students should be able to demonstrate at each level.

### Few-shot Examples

**Math** (`data/few_shot/`): JSON files organized by question style:
- **text_only**: Pure text questions (e.g., arithmetic, algebra, sequences)
- **with_chart**: Questions involving statistical charts (histogram, boxplot, line chart)
- **with_image**: Questions involving geometric diagrams or visual elements
- **creative_scenario**: Real-world context questions (menus, stock prices, delivery plans)

**Social studies** (`data/social_studies/few_shot/`): each root-level JSON file is one few-shot sampling group; `few_shot_examples.csv` is a long-format CSV, one row per subquestion, grouped by `範例編號`. Key CSV columns beyond the base set: `小題序號`, `小題年級`, `小題科目`, `核心素養`, `學習內容`, `學習表現`, `出題概念`, `小題題型`, `答案`, `答案解析`, `評分規準` (JSON-encoded rubric array with codes `2/1/0/0X`). The CSV is header-only as of #542 (legacy PISA-era rows retired); awaiting ICCS-native content from #544. Reference: `data/social_studies/csv_填寫指南.md`.

> **想新增一則 few-shot 範例？** 三個科目的目錄結構、每個題型的必要欄位、隱性失敗
> （例如 `chart_spec` JSON 格式錯誤會被靜默丟棄）以及「一行指令確認 loader 有讀到你的範例」
> 都彙整在 **[`docs/ADDING_SAMPLES.md`](docs/ADDING_SAMPLES.md)** (zh-TW)。加入或修改
> 範例後**下一次執行即生效**，無須重啟服務或重新 build。

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
   - `LLM_API_KEY`, `LLM_BASE_URL` (Anthropic); `GEMINI_API_KEY`, `GEMINI_BASE_URL` (Gemini); both keys required for the defaults
   - `LLM_MODEL_PLAN` / `LLM_MODEL_VERIFY` (default: `claude-opus-4-6`), `LLM_MODEL_EXECUTE` (default: `gemini-3.1-pro-preview`); plan/execute/verify effort defaults to `high`. `LLM_MODEL_CORRECT` / `LLM_EFFORT_CORRECT` default to empty (inherit execute); explicitly empty verify model/effort also inherit execute at call time
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

11. `LLMClient(config)` initialises an `Anthropic` client (for `claude-*` calls) and lazily constructs `OpenAI` compat clients for Gemini/OpenAI providers on first use (`src/llm_client.py` `LLMClient.__init__`). Skipped if `--dry-run`.
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
    - Calls `generate()` (lines 26-40): `openai.chat.completions.create()` with `model=model_execute` (`gemini-3.1-pro-preview`), `temperature=0.7`, `max_tokens=8192`
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

24. If `question.chart_spec` exists, `render_image(spec, img_path, question_text, html_renderer, llm_client)` (renderer.py:271) is called. `image_generation_mode=gpt_image` uses the image API first; otherwise `render_mode` selects the renderer:

**File: `src/renderer.py`**

| Effective mode | Path | Lines |
|---|---|---|
| `gpt_image` | `LLMClient.generate_image()` | renderer.py:271 |
| `html` + `render_mode="chart"` | `render_chart()` → `_render_histogram/boxplot/line_chart/pie_chart()` | 50-71 |
| `html` + `render_mode="html"` | `_generate_html_via_llm()` (LLM call #2) → `html_renderer.render()` | 271-308 |

25. On render success: `question.圖片 = "{question_id}.png"`, `chart_image_path` = absolute PNG path. Social-studies and natural-sciences `subquestions[*].chart_spec` entries are rendered by their subject CLI to `{question_id}_sq{序號}.png`; the subquestion stores `圖片`, and `server/generate/service.py` embeds the PNG as `subquestions[*].image_base64` for the React card and ODT export.

**File: `src/cli.py` inside `generate_one()`, `src/verifier.py`**

26. If `--no-verify` not set, `verify_question(client, question, chart_image_path)` is called (verifier.py) — **LLM call #3**:
    - Formats question text and solution into `VERIFICATION_USER_TEMPLATE`
    - Sends to LLM via `client.generate_with_image()` — text + optional base64 PNG in a multimodal message
    - Parses JSON response into `VerificationResult(passed, answer_match, details, my_answer, provided_answer, chart_verification)` where `chart_verification: ChartVerificationResult | None` holds `{chart_data_match, chart_labels_correct, chart_details}`
    - On parse failure: returns `VerificationResult(passed=False)`
27. Result attached to `question.verification`

#### 5B. Correction loop (`src/cli.py` `generate_with_corrections()`, `src/corrector.py`)

28. If `verification.passed=False` and retries remain, `correct_question(client, question, verification, chart_image_path)` (`src/corrector.py`) sends the failed question JSON + verifier's `details` (+ `my_answer`/`provided_answer` + optional `chart_verification`) back to `gemini-3.1-pro-preview` — multimodal if a PNG exists and chart verification failed. Returns a new `ExamQuestion` with only `題目`, `正確解題分析`, and `chart_spec` mutable; all classification and metadata fields are restored from the original.
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

| # | Purpose | Model | File |
|---|---|---|---|
| 1 | Generate question JSON | `model_execute` | `src/llm_client.py` |
| 2 | Generate HTML image (only when `render_mode="html"`) | `model_execute` | `src/renderer.py` |
| 3 | Verify question + image (multimodal) | `model_verify` | `src/verifier.py` |
| 4 | Correction (when verification fails; multimodal if chart was the issue) | `model_correct` (inherits execute) | `src/corrector.py` |

> **Social studies & natural sciences only:** Call #1 is replaced by a two-stage pipeline — one **文本生成器** call (agent: `generator`) produces the shared passage and 子題 plan, followed by N concurrent **子題產生器** calls (agents: `sub_generator#1` … `sub_generator#N`, each writing one complete 子題). Calls #2–4 (image rendering, verification, correction) are unchanged and operate on the fully-assembled 題組.

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
