# Execution Logic: Waterfall Flow

Complete execution trace of `uv run python -m src.cli generate`, from first instruction to final output.

---

## Phase 1: Bootstrap & Configuration

**File: `src/cli.py`**

1. `main()` is called (line 181)
2. `parse_args()` parses CLI flags: `--grade`, `--style`, `--context`, `--set-type`, `--q-type`, `--count`, `--seed`, `--no-verify`, `--batch`, `--output`, `--dry-run`, `--env-file` (lines 39-65)
   - `--style` choices are built dynamically from `question_schemas.json` at import time (via `QuestionStyle` enum)
3. `Config.from_env(args.env_file)` loads configuration (line 188)

**File: `src/schema_loader.py`** (triggered at import of `src/schemas.py`)

- `load_schemas()` reads `question_schemas.json` (path from `QUESTION_SCHEMAS_PATH` env var, default: project root)
- `build_enums()` creates `QuestionContext`, `QuestionSetType`, `QuestionType`, `MathThinking`, `QuestionStyle` as dynamic `str`-mixin enums from the JSON values
- `build_style_instructions()` builds `{style_value: instruction}` dict used by `context_builder.py`

**File: `src/config.py`**

4. `Config.from_env()` reads `.env` file via `dotenv`, then pulls env vars (lines 22-36):
   - `LLM_API_KEY`, `LLM_BASE_URL` (endpoint)
   - `LLM_MODEL_PLAN` (default: `claude-opus-4-6`), `LLM_MODEL_EXECUTE` (default: `claude-sonnet-4-6`)
   - `OUTPUT_DIR` (default: `./output`), `DATA_DIR` (default: `./data`)
5. `config.validate()` ensures `LLM_API_KEY` is set (line 193 -> config.py:38-41)

**File: `src/cli.py`**

6. `config.output_dir.mkdir(parents=True, exist_ok=True)` ensures output directory exists (line 196)

---

## Phase 2: Data Loading

**File: `src/cli.py` lines 199-204, calling into `src/data_loader.py`**

7. `load_curriculum(data_dir / "curriculum" / "學習內容.json")` -> reads full K-12 curriculum JSON array (14 grade objects) (data_loader.py:11-14)
8. `load_performance_standards(data_dir / "curriculum" / "學習表現.json")` -> reads learning performance standards (data_loader.py:17-19)
9. `load_intro_text(Path("Introduction to \"學習表現\" and \"學習階段\".md"))` -> reads curriculum intro markdown (data_loader.py:56-60)
10. Build grade content index: for each grade in (7, 8, 9), `get_grade_content(curriculum, grade)` extracts `LearningContentItem` objects (編碼 + 說明) from the curriculum (data_loader.py:23-35). Result: `{7: [...], 8: [...], 9: [...]}` (cli.py:204)

---

## Phase 3: LLM Client Initialization

**File: `src/cli.py` line 207, `src/llm_client.py`**

11. `LLMClient(config)` creates an `OpenAI(api_key=..., base_url=...)` client (llm_client.py:16-21). Skipped if `--dry-run`.

---

## Phase 4: Generation Loop

**File: `src/cli.py` lines 216-278**

For each question `i` in `range(args.count)`:

### 4A. Seed & RNG Setup (lines 221-222)

12. If `--seed` provided: `seed = base_seed + i`, else `seed = None`
13. `rng = random.Random(seed)` — deterministic if seeded

### 4B. Parameter Sampling (lines 224-232)

**File: `src/sampler.py`**

14. `sample_params()` randomly selects (or uses CLI overrides for) each parameter (lines 18-69). All enum values are loaded from `question_schemas.json` at startup:
    - **grade**: `rng.choice([7, 8, 9])` (line 35)
    - **情境**: `rng.choice(list(QuestionContext))` — values from `question_schemas.json["情境"]` (line 38)
    - **題型種類**: `rng.choice(list(QuestionSetType))` — values from `question_schemas.json["題型種類"]` (line 41)
    - **題型**: `rng.choice(list(QuestionType))` — values from `question_schemas.json["題型"]` (line 44)
    - **數學思考**: `rng.sample(all_thinking, randint(1,3))` — values from `question_schemas.json["數學思考"]` (lines 47-49)
    - **學習內容**: `rng.sample(available_content, randint(1,3))` — 1-3 items from selected grade's curriculum (lines 52-56)
    - **style**: `rng.choice(list(QuestionStyle))` — values from `question_schemas.json["question_style"][*].value` (line 59)
15. Returns `SampledParams` Pydantic model (lines 61-69)

### 4C. Prompt Construction (cli.py:241 -> generate_one lines 78-119)

**File: `src/context_builder.py`**

16. `build_system_prompt()` (lines 108-118) fills `SYSTEM_PROMPT_TEMPLATE` (lines 12-66) with:
    - `{curriculum_json}` — full K-12 curriculum as JSON string (via `get_full_curriculum_text`, data_loader.py:46-48)
    - `{performance_json}` — full performance standards as JSON string (via `get_full_performance_text`, data_loader.py:51-53)
    - `{intro_text}` — curriculum introduction markdown

17. `build_user_prompt()` (lines 121-173) fills `USER_PROMPT_TEMPLATE` (lines 68-98) with:
    - Sampled parameters (grade, 情境, 題型種類, 題型, 數學思考, 學習內容)
    - `{style_instruction}` — looked up from `_STYLE_INSTRUCTIONS[params.style.value]`; this dict is built from `question_schemas.json["question_style"]` at module import time
    - `{few_shot_examples}` — assembled via steps 18-20 below

### 4D. Few-Shot Example Injection (context_builder.py:142-162)

**File: `src/data_loader.py` line 63-72, then `src/context_builder.py` lines 142-162**

18. `load_few_shot_examples(few_shot_dir, style)` (data_loader.py:63-72):
    - Resolves path: `data/few_shot/{style}/` (e.g. `data/few_shot/with_chart/`)
    - `sorted(style_dir.glob("*.json"))` — loads ALL JSON files in alphabetical order
    - Each file is parsed as a JSON object or array and appended to the list

19. Flatten (context_builder.py:146-151): if any loaded file is a JSON array, each element is extracted. Single objects kept as-is. This creates a flat pool of individual examples.

20. Random selection (context_builder.py:154-155): `rng.sample(flat_examples, min(2, len(pool)))` picks 1-2 examples from the pool. Each is formatted as a markdown code block with `### 範例 {i}` header.

### 4E. LLM Generation Call (cli.py:106)

**File: `src/llm_client.py`**

21. `client.generate_json(system_prompt, user_prompt)` (llm_client.py:41-44):
    - Calls `generate()` (lines 23-35): `openai.chat.completions.create()` with `model=model_execute` (Sonnet), `temperature=0.7`, `max_tokens=8192`
    - Messages: `[{"role": "system", ...}, {"role": "user", ...}]`
22. `extract_json(raw)` (llm_client.py:47-64) parses LLM text response:
    - First tries: regex for ````json ... ``` `` code block (line 50-52)
    - Then tries: raw text starting with `{` or `[` (lines 55-57)
    - Then tries: first `{...}` substring (lines 60-62)
    - Raises `ValueError` if all fail

### 4F. Response Parsing (cli.py:109)

**File: `src/cli.py` lines 122-178**

23. `_parse_question(raw_json, question_id, params, model)` converts raw dict to `ExamQuestion`:
    - **學習內容** (lines 130-143): handles both dict and string formats, splits on `：`
    - **chart_spec** (lines 149-160): if present, parsed into `ChartSpec` Pydantic model
    - Returns `ExamQuestion` with all fields + `QuestionMetadata` (grade, style, model, seed)

---

## Phase 5: Verification (Two-Pass)

**File: `src/cli.py` lines 112-117, `src/verifier.py`**

24. If `--no-verify` not set, `verify_question(client, question)` is called (verifier.py:50-74):
    - Formats question text and solution into `VERIFICATION_USER_TEMPLATE` (lines 37-47)
    - Sends to LLM with `VERIFICATION_SYSTEM_PROMPT` (lines 10-35) — asks model to independently solve, then compare
    - Uses `client.generate()` (same Sonnet model) — **this is the second LLM call** (line 62)
    - Parses JSON response into `VerificationResult` (passed, answer_match, details) (lines 64-68)
    - On parse failure: returns `VerificationResult(passed=False)` (lines 69-74)
25. Result attached to `question.verification` (cli.py:115)

---

## Phase 6: Chart/Image Rendering

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

## Phase 7: Output

**File: `src/cli.py` lines 269-290**

### Single mode (default):

31. For each question: write `{question_id}.json` to output dir (lines 272-278)
    - `question.model_dump_json(indent=2, exclude_none=True)` serializes the Pydantic model

### Batch mode (`--batch`):

32. After all questions: write `batch_{timestamp}.json` containing a JSON array of all questions (lines 281-288)

---

## Summary: LLM Calls Per Question

| # | Purpose | Model | File | Line |
|---|---|---|---|---|
| 1 | Generate question JSON | Sonnet (`model_execute`) | llm_client.py | 26-35 |
| 2 | Verify question (independent solve) | Sonnet (`model_execute`) | verifier.py | 62 |
| 3 | Generate geometry matplotlib code (only if `chart_type="geometry"` and no hardcoded match) | Sonnet (`model_execute`) | renderer.py | 426-429 |

## Summary: Randomness Points

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
