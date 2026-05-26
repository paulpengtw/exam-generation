# Implementation Plan

## Known Tech Debt

- **Geometry renderer removed (completed):** `_render_geometry`, `_render_geometry_courtyard`, and `_render_geometry_shadow` were removed. All non-chart images now use `render_mode: "html"` — Sonnet generates a self-contained HTML/CSS/SVG document, which Playwright screenshots to PNG.
- **`ChartSpec` alias:** `src/schemas.py` exports `ChartSpec = ImageSpec` for backward compatibility with older LLM outputs. Remove once all few-shot examples use `image_spec`.

---

## Known design risks (math-shaped scaffolding)

`src/verifier.py` and `src/corrector.py` assume answer-match correctness (`my_answer == provided_answer`). 108課綱 社會領域 開放式建構反應題 is rubric-scored (codes 2/1/0/0X) — there is no single correct answer to match. `src/corrector.py` rewrites toward a single answer; rubric items need rubric-conformance editing instead. `數學思考` / `學習內容` enums and curriculum JSON are math-specific; social studies uses `閱讀歷程` / `文本形式` with different cardinality and a CSV-driven curriculum.

✅ **Structured rubric model resolved:** `RubricEntry(code, 規準說明, 學生作答實例)` is now a first-class Pydantic model in `src/social_studies/schemas.py`. Per-subquestion `評分規準` is populated in both the few-shot CSV and LLM output parsing.

✅ **Scoring code convention resolved:** Social studies uses `0X` (未作答) not `9`. `schema_parameters.csv` now documents the correct `2/1/0/0X` convention. `src/social_studies/corrector.py` preserves rubric entries correctly across correction passes.

✅ **Cross-subject 題組 partially resolved:** `SubQuestion` carries per-row `科目` (list) and `年級` fields; a single 題組 can span 歷史/地理/公民與社會 subquestions at different grade levels.

**Decision:** Ship 社會科 as a parallel forked codepath (`src/social_studies/`). Verifier/corrector reuse math code with the gap documented. Defer the SubjectAdapter / tool-registry / two-LLM verifier refactor below until a third subject arrives (rule of three).

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

✅ **CSV population resolved (2026-05-26):** The curriculum CSVs are now seeded with codes extracted from six NAER reference 題組 (黃馨瑩 2021, NAER-2019-041-A-1-1-E1-10):

- `learning_content.csv` — 25 學習內容 codes: 歷Ka/Kb/Kc/La-Ⅳ, 地Aa/Ab/Ac/Ad/Af-Ⅳ, 公Ba/Bb/Bc/Bd/Be-Ⅳ
- `learning_performance.csv` — 14 學習表現 codes: 歷1a/2a/2b-Ⅳ, 地1a/1b/2a/2b-Ⅳ, 公1a/1b/2a/2b-Ⅳ, 社1b/3b-Ⅳ
- `few_shot/few_shot_examples.csv` — seeded with the 1918年流感 3-subquestion 題組 (complete with `評分規準`)

See `data/social_studies/csv_填寫指南.md` for the field-by-field filler guide for adding more codes.

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

## Migrate `學習內容` and `學習表現` from CSV to JSON ✅ RESOLVED (2026-05-26)

**Motivation:** `核心素養` was just migrated to `data/social_studies/curriculum/core_competencies.json` + `src/social_studies/core_competency_loader.py`, enabling the sampler to randomly draw codes uniformly and independent of the prompt-fill CSV pipeline. `學習內容` and `學習表現` remain CSV-only (`learning_content.csv`, `learning_performance.csv`) and are only used for system-prompt injection text — the sampler cannot draw individual 編碼 entries to constrain a 題組. Migrating them to the same JSON pattern lets the sampler pick a small subset of codes the same way it now picks 核心素養.

### Target layout

**Resolution (2026-05-26):** Both CSVs migrated to JSON. `curriculum_loader.py` provides JSON loaders + sampler helpers. Sampler picks 學習內容 1-3 / 學習表現 1-2 codes filtered by 學習階段 + 科目 prefix and stores them in `SampledParams.學習內容_pool` / `學習表現_pool`. The official 學習表現 framework explanation (構面/項目/編碼規則 + full 條目 list) from the NAER odt is saved as `learning_performance_intro.md` and injected as a `### 學習表現架構說明` block in the system prompt. User prompt `## 指定條件` now shows `- **指定學習內容**` and `- **指定學習表現**` with per-code descriptions. CLI flags `--learning-content` and `--learning-performance` allow override. Old CSVs deleted; CSV loaders removed from `data_loader.py`.

Two new files in `data/social_studies/curriculum/`:

- **`learning_content.json`** — top-level `學習階段_to_grades` (`{"第四學習階段": [7,8,9], …}`) plus a flat `學習內容` array of `{value, 學習階段, 年級, 科目, 條目說明, 備註, 對應學習表現[]}` entries. `value` = `編碼`; `科目` inferred from first character of 編碼 prefix (歷/地/公).
- **`learning_performance.json`** — top-level `學習階段_to_grades` (same lookup) plus a flat `學習表現` array of `{value, 學習階段, 科目, 說明}` entries. `value` = `編碼`; `科目` inferred from prefix (社/歷/地/公).

### Loader module

New `src/social_studies/curriculum_loader.py` (same pattern as `core_competency_loader.py`):

- `load_learning_content(path?) -> dict` — env override `SOCIAL_STUDIES_LEARNING_CONTENT_PATH`.
- `load_learning_performance(path?) -> dict` — env override `SOCIAL_STUDIES_LEARNING_PERFORMANCE_PATH`.
- `allowed_learning_content(data, learning_stage, subject?) -> list[dict]` — filter by 學習階段; optionally by 科目 prefix (e.g. `"歷"` → only `歷*` codes; `"跨科"` → all). Returns list of entry dicts.
- `allowed_learning_performance(data, learning_stage, subject?) -> list[dict]` — same filter logic.
- `content_instructions(data) / performance_instructions(data) -> dict[str, str]` — `{value: 條目說明 / 說明}` for prompt補充 injection.

### Sampler wiring (`src/social_studies/sampler.py`)

- New params: `learning_content: list[str] | None = None` (cardinality 1–3), `learning_performance: list[str] | None = None` (cardinality 1–2).
- Pool filtered by `_LEARNING_STAGE` and the sampled `params.科目` — a 歷史 題組 draws only `歷` codes; 跨科 draws across all three subject prefixes.
- Both picks added to `SampledParams` as `學習內容_pool: list[...]` and `學習表現_pool: list[...]` (distinct from per-`SubQuestion` `學習內容: list[LearningContentRef]` which is LLM-emitted).

### Prompt wiring (`src/social_studies/context_builder.py`)

- Replace `data_loader.load_learning_content` / `load_learning_performance` imports with the new JSON loaders.
- Keep the full `## 課程綱要參考` system-prompt injection (LLM ground truth), but add the sampled subset to the **user prompt** under `## 指定條件`:
  - `- **指定學習內容**：{codes}` with per-code補充 lines.
  - `- **指定學習表現**：{codes}` with per-code補充 lines.
- Add `## 重要提醒` bullet: "各小題的 `學習內容` / `學習表現` 應優先使用上述指定代號；如題組設計需引入其他課綱代號，仍以 `## 課程綱要參考` 中列出者為限。"

### CSV rollback

After JSON files are authoritative, delete `learning_content.csv` and `learning_performance.csv`; remove the two CSV loaders from `src/social_studies/data_loader.py` (keep the few-shot CSV loader — unrelated). `csv_填寫指南.md` to be rewritten describing the JSON shape. Alternatively, keep CSVs as a researcher input format and add `scripts/csv_to_curriculum_json.py` as a build step — TBD.

### CLI additions

- `--learning-content` (nargs="+") and `--learning-performance` (nargs="+") override flags, mirroring `--core-competency`.

### Verification (post-execution)

```bash
uv run python -c "
from src.social_studies.curriculum_loader import load_learning_content, allowed_learning_content
d = load_learning_content()
print(len(d['學習內容']))  # expect current CSV row count
print(len(allowed_learning_content(d, '第四學習階段', '歷')))  # 歷史 codes only
"
uv run python -m src.social_studies.cli generate --dry-run --seed 0
# expect: '**指定學習內容**：…' and '**指定學習表現**：…' in user prompt
```

---

## 108課綱 社會領域 re-framing (completed 2026-05-26)

`src/social_studies/` was re-framed from PISA reading literacy to **108課綱
社會領域素養導向 命題** (歷史/地理/公民與社會, 跨科題組). PISA-style tags
(`閱讀歷程`, `文本形式`) are retained as secondary diversity axes only.

### Schema additions (`src/social_studies/schemas.py`)

| New type | Purpose |
|---|---|
| `LearningContentRef` | `{編碼, 說明}` pair for 學習內容 and 學習表現 references |
| `RubricEntry` | `{code, 規準說明, 學生作答實例}` — rubric row; codes are `2/1/0/0X` |
| `SubQuestion` | Per-subquestion: `id`, `序號`, `年級`, `科目`, `核心素養`, `學習內容`, `學習表現`, `出題概念`, `題型`, `題目`, `答案`, `答案解析`, `評分規準` |
| `QuestionSubject` | Enum: `歷史 / 地理 / 公民與社會 / 跨科` |

`ExamQuestion` gained first-class fields: `核心問題`, `文本`, `取材來源`, `subquestions`.

### Data population

See "Social studies context-injection parity gap § CSV population resolved" above.

### CLI addition

`--subject` flag added to `src/social_studies/cli.py`; sampler picks `科目` from
`QuestionSubject`; multiple values define a random pool.

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
