# Execution Logic: Waterfall Flow

Complete execution trace of `uv run python -m src.cli generate`, from first instruction to final output.

---

## Phase 1: Bootstrap & Configuration

**File: `src/cli.py`**

1. `main()` is called (line 181)
2. `parse_args()` parses CLI flags: `--grade`, `--style`, `--context`, `--set-type`, `--q-type`, `--count`, `--seed`, `--no-verify`, `--batch`, `--output`, `--dry-run`, `--env-file` (lines 39-65)
   - `--style` choices are built dynamically from `question_schemas.json` at import time (via `QuestionStyle` enum); accepts `nargs="+"` — multiple values define a random selection pool
   - `--q-type` accepts `nargs="+"` — multiple values define a random selection pool; single value forces that type
3. `Config.from_env(args.env_file)` loads configuration (line 188)

**File: `src/schema_loader.py`** (triggered at import of `src/schemas.py`)

- `load_schemas()` reads `question_schemas.json` (path from `QUESTION_SCHEMAS_PATH` env var, default: project root)
- `load_grades()` extracts `schemas["grades"]` — the integer list of allowed grades (e.g. `[7, 8, 9]`)
- `load_learning_stage()` extracts `schemas["學習階段"]` — the stage name injected into the system prompt (e.g. `"第四學習階段"`)
- `build_enums()` creates `QuestionContext`, `QuestionSetType`, `QuestionType`, `MathThinking`, `QuestionStyle` as dynamic `str`-mixin enums from the JSON values
- `build_instructions()` builds `{category: {value: instruction}}` dict for all 5 categories, used by `context_builder.py`. Only entries with non-empty `instruction` are included.

**File: `src/config.py`**

4. `Config.from_env()` reads `.env` file via `dotenv`, then pulls env vars (lines 22-36):
   - `LLM_API_KEY`, `LLM_BASE_URL` (endpoint)
   - `LLM_MODEL_PLAN` (default: `claude-sonnet-4-6`), `LLM_MODEL_EXECUTE` (default: `claude-sonnet-4-6`)
   - `LLM_RATE_LIMIT_DELAY` (default: `0`) — float seconds; if > 0, `llm_client.generate()` sleeps this long before every API call to avoid 429 rate-limit errors (llm_client.py:24-25)
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
10. Build grade content index: for each grade in `_GRADES` (loaded from `question_schemas.json["grades"]` at import), `get_grade_content(curriculum, grade)` extracts `LearningContentItem` objects (編碼 + 說明) from the curriculum (data_loader.py:23-35). Result: `{7: [...], 8: [...], 9: [...]}` by default (cli.py:204)

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
    - **grade**: `rng.choice(_GRADES)` — values from `question_schemas.json["grades"]` (line 35)
    - **情境**: `rng.randint(1, len(all_contexts))` → `rng.sample(all_contexts, count)` — 1-N items from `question_schemas.json["情境"]` (lines 38-41)
    - **題型種類**: `rng.choice(list(QuestionSetType))` — values from `question_schemas.json["題型種類"]` (line 41)
    - **題型**: `rng.choice(q_type)` if pool provided (via `--q-type`), else `rng.choice(list(QuestionType))` — pool accepts 1+ values; single value forces that type (line 52)
    - **數學思考**: `rng.sample(all_thinking, randint(1,3))` — values from `question_schemas.json["數學思考"]` (lines 47-49)
    - **學習內容**: `rng.sample(available_content, randint(1,3))` — 1-3 items from selected grade's curriculum (lines 52-56)
    - **style**: `rng.choice(style)` if pool provided (via `--style`), else `rng.choice(list(QuestionStyle))` — pool accepts 1+ values (line 67)
15. Returns `SampledParams` Pydantic model (lines 61-69)

### 4C. Prompt Construction (cli.py:241 -> generate_one lines 78-119)

**File: `src/context_builder.py`**

16. `build_system_prompt()` (lines 112-128) fills `SYSTEM_PROMPT_TEMPLATE` with:
    - `{curriculum_json}` — full K-12 curriculum as JSON string (via `get_full_curriculum_text`, data_loader.py:46-48)
    - `{performance_json}` — full performance standards as JSON string (via `get_full_performance_text`, data_loader.py:51-53)
    - `{intro_text}` — curriculum introduction markdown
    - `{learning_stage}` — from `question_schemas.json["學習階段"]` (e.g. `"第四學習階段"`)
    - `{grade_names}` — e.g. `"7年級、8年級、9年級"` built from `question_schemas.json["grades"]`
    - `{grade_range}` — e.g. `"7-9年級"` built from min/max of `question_schemas.json["grades"]`

17. `build_user_prompt()` fills `USER_PROMPT_TEMPLATE` with:
    - Sampled parameters (grade, 情境, 題型種類, 題型, 數學思考, 學習內容)
    - `{param_instructions}` — optional `## 條件補充說明` block. For each selected value of 情境, 題型種類, 題型, and each 數學思考 item, `_INSTRUCTIONS[category][value]` is looked up from the module-level dict (built via `schema_loader.build_instructions()` from `question_schemas.json`). Only non-empty instructions are emitted; if none exist the block is omitted entirely.
    - `{style_instruction}` — `_INSTRUCTIONS["question_style"][params.style.value]` → injected under `## 題目風格` heading. Full data flow: `question_schemas.json["question_style"][*].instruction` → `build_instructions()` → `_INSTRUCTIONS` dict → lookup by style value → LLM payload.
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

## Phase 5: Chart Rendering + Verification (Two-Pass)

Chart rendering now happens **before** verification (both inside `generate_one()`), so the verifier can inspect the rendered image via a multimodal LLM call.

### 5A. Chart Rendering

**File: `src/cli.py` inside `generate_one()`, `src/renderer.py`**

24. If `question.chart_spec` exists, `render_chart(spec, img_path, llm_client)` is called:

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
    - **Tier 2 — LLM-assisted** (lines 290-293): `_render_geometry_via_llm()` (lines 405-464) sends geometry description to Sonnet, gets matplotlib code back, `exec()`s it — **this is the second LLM call (geometry only)**
    - **Tier 3 — Text fallback** (lines 296-303): renders description as centered text on blank canvas

29. All renderers save PNG via `fig.savefig(output_path, dpi=150)` and `plt.close(fig)`
30. On success: `question.圖片 = "{question_id}.png"`, `chart_image_path` = absolute path string

### 5B. Verification

**File: `src/cli.py` inside `generate_one()`, `src/verifier.py`**

31. If `--no-verify` not set, `verify_question(client, question, chart_image_path)` is called:
    - Formats question text and solution into `VERIFICATION_USER_TEMPLATE`
    - If `chart_image_path` is set, appends chart-check instruction to user prompt
    - Calls `client.generate_with_image(VERIFICATION_SYSTEM_PROMPT, user_prompt, image_path=chart_image_path)` — **this is the third LLM call** (second if no chart). When image is provided, the user message is a multimodal content list: `[{type: text, text: ...}, {type: image_url, image_url: {url: "data:image/png;base64,..."}}]`
    - Parses JSON response into `VerificationResult(passed, answer_match, details, chart_verification)`:
      - `chart_verification: ChartVerificationResult | None` — present only when chart image was sent; holds `{chart_data_match, chart_labels_correct, chart_details}`
    - On parse failure: returns `VerificationResult(passed=False)`
32. Result attached to `question.verification`

---

## Phase 6: Output

**File: `src/cli.py` lines 269-290**

### Single mode (default):

33. For each question: write `{question_id}.json` to output dir
    - `question.model_dump_json(indent=2, exclude_none=True)` serializes the Pydantic model

### Batch mode (`--batch`):

34. After all questions: write `batch_{timestamp}.json` containing a JSON array of all questions

---

## Summary: LLM Calls Per Question

| # | Purpose | Model | File | Line |
|---|---|---|---|---|
| 1 | Generate question JSON | Sonnet (`model_execute`) | llm_client.py | 26-35 |
| 2 | Generate geometry matplotlib code (only if `chart_type="geometry"` and no hardcoded match) | Sonnet (`model_execute`) | renderer.py | 426-429 |
| 3 | Verify question + chart image (multimodal when chart present) | Sonnet (`model_execute`) | verifier.py, `generate_with_image()` | — |

## Summary: Randomness Points

| What | How | File | Line |
|---|---|---|---|
| Grade | `rng.choice(_GRADES)` from `question_schemas.json["grades"]` | sampler.py | 35 |
| 情境 | `rng.sample(all, randint(1, len))` | sampler.py | 38-41 |
| 題型種類 | `rng.choice(list(QuestionSetType))` | sampler.py | 41 |
| 題型 | `rng.choice(list(QuestionType))` | sampler.py | 44 |
| 數學思考 | `rng.sample(all, randint(1,3))` | sampler.py | 47-49 |
| 學習內容 | `rng.sample(grade_items, randint(1,3))` | sampler.py | 52-56 |
| Style | `rng.choice(list(QuestionStyle))` | sampler.py | 59 |
| Few-shot examples | `rng.sample(flat_pool, min(2,len))` | context_builder.py | 154-155 |

All randomness is seeded from a single `random.Random(seed)` per question — fully reproducible when `--seed` is provided.
