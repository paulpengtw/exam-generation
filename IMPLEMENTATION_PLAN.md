# Implementation Plan

## Known Tech Debt

- **Geometry renderer removed (completed):** `_render_geometry`, `_render_geometry_courtyard`, and `_render_geometry_shadow` were removed. All non-chart images now use `render_mode: "html"` — Sonnet generates a self-contained HTML/CSS/SVG document, which Playwright screenshots to PNG.
- **`ChartSpec` alias:** `src/schemas.py` exports `ChartSpec = ImageSpec` for backward compatibility with older LLM outputs. Remove once all few-shot examples use `image_spec`.

---

## Known design risks (math-shaped scaffolding)

`src/verifier.py` and `src/corrector.py` assume answer-match correctness (`my_answer == provided_answer`). PISA reading 開放式建構反應題 is rubric-scored (codes 2/1/0/9) — there is no single correct answer to match. `src/corrector.py` rewrites toward a single answer; rubric items need rubric-conformance editing instead. `數學思考` / `學習內容` enums and curriculum JSON are math-specific; reading uses `閱讀歷程` / `文本形式` with different cardinality and no K-12 curriculum lookup.

**Decision:** Ship 社會科 as a parallel forked codepath (`src/social_studies/`). Verifier/corrector reuse math code with the gap documented; fix with a `rubric_grade` scoring strategy once a live example fails. Defer the SubjectAdapter / tool-registry / two-LLM verifier refactor below until a third subject arrives (rule of three).

---

## Social studies context-injection parity gap

The shipped `src/social_studies/` codepath injects far less context into the
LLM payload than math, materially degrading generated-question quality.
Logged here as tracked tech debt — **social studies should receive an
equivalent level and coverage of context injection as math.**

### 1. Missing curriculum / cross-stage context ✅ RESOLVED

The math system prompt (`src/context_builder.py:34-46`) injects three live
reference documents:

| Slot | Source | Content |
|---|---|---|
| `{curriculum_json}` | `data/curriculum/學習內容.json` | Full K-12 學習內容 |
| `{performance_json}` | `data/curriculum/學習表現.json` | Full 學習表現, 第一–第五 |
| `{intro_text}` | `Introduction to "學習表現" and "學習階段".md` | 綱要 explanation |

**Resolution:** A CSV-driven curriculum injection layer has been shipped for
social studies. The social-studies system prompt
(`src/social_studies/context_builder.py`) now has a `## 課程綱要參考` section
that injects:

- **學習表現標準** — loaded from `data/social_studies/curriculum/learning_performance.csv`
  via `src/social_studies/data_loader.load_learning_performance()`
- **學習內容** — loaded from `data/social_studies/curriculum/learning_content.csv`
  via `src/social_studies/data_loader.load_learning_content()`

The schema itself (學習階段, grades, 6 parameter categories with `instruction`
strings) is now loaded from `schema_meta.csv` + `schema_parameters.csv` in the
same directory, replacing the deleted `social_studies_schemas.json`.

**Remaining gap:** the four curriculum CSVs ship empty. Until researchers at
NAER fill them, the system prompt shows a fallback notice
`（課程綱要資料待研究人員補充至 data/social_studies/curriculum/）`. The
*mechanism* is at parity with math; *content population* is still pending.
See `data/social_studies/csv_填寫指南.md` for the field-by-field filler guide.

### 2. `_HTML_SYSTEM_PROMPT` hardcoded to "math exam questions"

`src/renderer.py:361` — `_HTML_SYSTEM_PROMPT` reads "...visual designer for
Taiwanese junior high school **math** exam questions." This prompt is shared by
the social-studies `render_mode: "html"` image path (tables, maps, ads, forms,
digital-reading material). The math persona is a copy-paste leftover that biases
the designer LLM away from PISA non-continuous-text material and degrades those
visuals.

**Fix direction:** parametrize the HTML designer persona by subject (or
neutralize the wording). Aligns with the deferred `tools/html_tool.py`
"parametric HTML-via-LLM; per-tool system prompt" refactor below.

---

## Multi-subject architecture (deferred — see Known design risks above)

**Why:** ~70% of current code is math-bound (persona prompts, `數學思考` enum, `MathThinking` Pydantic field, chart-type allowlist, curriculum N/S/G/A/F/D/R codes, verifier persona). Extending cleanly requires a subject plugin layer rather than forking.

**User decisions logged:** subjects = 社會 + 自然; verifier = two-LLM disagreement; tool dispatch = LLM emits name from adapter-scoped allowlist; deployment = single binary `--subject` flag.

**Do not rewrite** (already generic):
- `src/llm_client.py` — OpenAI-compatible HTTP client
- `src/html_renderer.py` — Playwright HTML→PNG, no subject logic
- `src/data_loader.py` — generic JSON loaders; `get_grade_content` needs minor callback for non-`年級` curriculum shapes
- HTML-via-LLM mechanism in `renderer._generate_html_via_llm` — extract and parametrize on per-tool prompt instead of rewriting

Extend to **社會** (history/geography/civics) and **自然** (physics/chemistry/biology/earth science). Single binary, `--subject` flag.

### Target layout

```
src/
  core/                          # subject-agnostic
    llm_client.py                # unchanged
    config.py                    # add SUBJECT env / --subject
    schema_loader.py             # refactor: parametric on subject
    html_renderer.py             # unchanged
    pipeline.py                  # extracted generation loop from cli.py
    verifier.py                  # two-LLM disagreement strategy
    schemas_base.py              # generic ExamQuestion / SampledParams shells
  subjects/
    base.py                      # SubjectAdapter protocol
    math/adapter.py, prompts.py, parse.py
    social_studies/adapter.py, prompts.py, parse.py
    natural_science/adapter.py, prompts.py, parse.py
  tools/
    registry.py                  # tool_name -> renderer fn; adapter-scoped allowlist
    chart_matplotlib.py          # extracted from renderer.py
    html_tool.py                 # parametric HTML-via-LLM; per-tool system prompt
    prompts/                     # per-tool HTML system prompts
      geometry.md, source_quote.md, timeline.md, map.md,
      apparatus.md, circuit.md, bio_diagram.md, data_table.md, passage.md
  cli.py
schemas/
  math.json                      # = current question_schemas.json
  social_studies.json
  natural_science.json
data/
  math/{curriculum,few_shot,example_exams}/
  social_studies/{curriculum,few_shot,example_exams}/
  natural_science/{curriculum,few_shot,example_exams}/
```

### SubjectAdapter protocol (`src/subjects/base.py`)

```python
class SubjectAdapter(Protocol):
    name: str
    def taxonomy(self) -> Taxonomy: ...
    def curriculum(self) -> dict: ...
    def system_prompt(self, ctx) -> str: ...
    def user_prompt(self, params) -> str: ...
    def few_shot_loader(self, style: str) -> list[dict]: ...
    def allowed_tools(self) -> list[str]: ...
    def parse_question(self, raw: dict) -> ExamQuestion: ...
```

Tool dispatch: `image_spec.tool: str` replaces `render_mode` + `chart_type`. Adapter exposes its allowlist in the user prompt; registry routes to renderer.

### Per-subject tool allowlists

| Subject | Tools |
|---|---|
| math | `chart_matplotlib`, `geometry_html`, `data_table` |
| social_studies | `passage`, `chart_matplotlib`, `data_table`, `html_tool` (table/form/ad/map/diagram), `digital_reading_html` |
| natural_science | `apparatus`, `circuit`, `bio_diagram`, `data_table`, `chart_matplotlib`, `geometry_html` |

### Two-LLM disagreement verifier

1. Solve A — Sonnet temp=0.2 (multimodal if image)
2. Solve B — Sonnet temp=0.8 (independent phrasing)
3. Agree → `passed=True`
4. Disagree → Judge (Opus) decides; returns `VerificationResult{passed, agreement, answer_a, answer_b, judge_verdict?, details}`

### Schema evolution

```python
class ExamQuestion(BaseModel):
    subject: str
    題目: list[str]
    正確解題分析: list[str]
    image_spec: ImageSpec | None
    metadata: dict   # subject-specific: 數學思考 / 探究能力 / 史料類型 / ...
```

### Files to modify

| File | Change |
|---|---|
| `src/schemas.py` | Split → `core/schemas_base.py` + `subjects/*/parse.py`; remove `MathThinking` from base |
| `src/schema_loader.py` | Parametric on subject; load `schemas/{subject}.json`; drop fixed 5-tuple |
| `src/context_builder.py` | Split → `subjects/*/prompts.py` |
| `src/sampler.py` | Merge into `core/pipeline.py`; generic sample-over-taxonomy |
| `src/renderer.py` | Split → `tools/chart_matplotlib.py` + `tools/html_tool.py` + `tools/registry.py` |
| `src/verifier.py` | Rewrite → `core/verifier.py`; two-LLM disagreement; drop math persona |
| `src/cli.py` | Add `--subject`; dispatch to adapter |
| `src/config.py` | Add `SUBJECT` env (default `math`) |
| `question_schemas.json` | Move → `schemas/math.json` |
| `data/curriculum/` | Move → `data/math/curriculum/`; same for `few_shot/`, `example_exams/` |
| `server/routes/generate.py` | Accept `subject` request param |

### New taxonomy files (seed content)

**`schemas/social_studies.json`** (PISA 閱讀素養 taxonomy)
- `學習階段`: 第四學習階段, `grades`: [7, 8, 9]
- `情境`: 個人 / 公共 / 職業 / 教育
- `題型種類`: 題組題 (PISA 一律題組設計)
- `題型`: 選擇題 / 封閉式建構反應題 / 開放式建構反應題
- `文本形式`: 連續文本 (敘事/說明/記敘/論述/指南) + 非連續文本 (圖表/表格/圖解/地圖/表單/廣告)
- `閱讀歷程`: 擷取訊息 / 形成廣泛理解 / 發展解釋 / 省思與評鑑文本內容 / 省思與評鑑文本形式
- `question_style`: text_only, with_non_continuous_text, mixed_text, digital_reading
- 試題比重: 擷取 25% / 統整解釋 50% / 省思評鑑 25%; 連續:非連續 ≈ 2:1
- Sampler: 情境 1+, 文本形式 1 (or 1-2 for mixed_text), 閱讀歷程 1-2; 題型種類 forced to 題組題
- Full per-value `instruction` strings stored in the JSON file itself (source: user-supplied spec)

**`schemas/natural_science.json`**
- `領域`: [物理, 化學, 生物, 地球科學]
- `情境`: [日常生活, 實驗探究, 自然現象, 科技應用, 環境永續]
- `探究能力`: [想像創造, 推理論證, 批判思辨, 建立模型]
- `question_style`: [text_only, with_apparatus, with_circuit, with_diagram, with_data_table, with_chart]

### Migration phases

1. **Refactor (math unchanged)** — extract `core/pipeline.py`, introduce `SubjectAdapter`, wrap math. Verify same output for same seed.
2. **Tool registry** — split `renderer.py`; convert `render_mode` → `tool`. Math unchanged.
3. **Two-LLM verifier** — swap verifier; A/B test on math.
4. **社會 adapter (PISA reading)** — taxonomy + prompts + 5-10 few-shot per style (text_only, with_non_continuous_text, mixed_text, digital_reading). Curriculum source: 國民中學閱讀素養指標 + PISA framework (no K-12 curriculum JSON like math).
5. **自然 adapter** — same as phase 4.
6. **Server** — thread `subject` through request schema.

### Verification

```bash
# Phase 1-3: math output identical for same seed
uv run python -m src.cli generate --subject math --count 5 --seed 42

# Phase 4
uv run python -m src.cli generate --subject social_studies --count 3

# Phase 5
uv run python -m src.cli generate --subject natural_science --count 3 --style with_circuit

# Lint + tests
uv run ruff check src/
uv run pytest
```
