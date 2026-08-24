# Figure Rendering Policy

Owner: exam-generation. Status: authoritative — the three `src/**/context_builder.py`
modules cite this file. Related GitHub
issues: #108 (frontend TS renderer evaluation), #110 (routing policy).

## The rule

Every `chart_spec` on an `ExamQuestion` or `SubQuestion` MUST route to one of
the following renderers, chosen by the character of the figure — **not** by the
question's subject, grade, or 學習內容 code.

| Figure family | Examples | `render_mode` | Renderer |
| --- | --- | --- | --- |
| Precise / quantitative statistical charts | 直方圖, 盒鬚圖, 折線圖, 圓餅圖, 未來加入的任何座標軸帶刻度的統計圖 | `"chart"` | matplotlib (`src/renderer.py::render_chart`) |
| Illustrative figures — structured / semantic | 菜單, 情境卡, 廣告, 版面, 表單, 帶語意標註的表格 | `"html"` | LLM-HTML + Playwright (`src/renderer.py::_generate_html_via_llm` + `src/html_renderer.py`) |
| Illustrative figures — realistic diagram | 地圖 (含真實海岸線/經緯線), 實驗裝置, 生物模型/標籤圖, 需符合真實比例的幾何, 情境寫實圖 | `"gpt_image"` | OpenAI image API via `src/llm_client.py::generate_image` |

### Why this split

- Statistical charts have deterministic axes, tick labels, and derived
  aggregates (mean, median, quantiles). Rendering them via an LLM introduces
  drift between the numeric spec and the pixels a student reads. matplotlib
  is deterministic and cheap; keep it authoritative.
- Illustrative figures are open-ended — no fixed axes, arbitrary layout,
  domain-specific pictorial conventions (e.g. a museum menu, a bus route
  card). The HTML path lets the LLM invent layout details the schema does
  not encode; this is the correct trade-off for that family.

## Renderer selection matrix

> **Provisional (2026-07-18):** Derived from a 15-spec fidelity sample; revisit once
> the census gate (≥30 real production questions per subject) is met.

| Figure category | Default renderer | Rationale |
|---|---|---|
| Deterministic statistical chart (histogram/boxplot/line/pie, no domain overlays) | `render_mode: "chart"` (matplotlib) | Reproducibility; no LLM call |
| Table (any subject) | `render_mode: "html"` | HTML+Playwright captures titles, semantic highlights, inline units, footnotes |
| Chart with semantic overlays (projection dividers, threshold lines, domain-specific highlights, companion data tables) | `render_mode: "html"` | LLM-authored HTML/SVG reliably encodes semantic overlays gpt-image-2 flattens |
| Realistic diagram (map with real coastlines, lab apparatus, biology cell/organism, geometry that must match real-world proportions) | `render_mode: "gpt_image"` | 15-spec eval: 4/4 diagram_realistic wins for gpt-image-2; HTML+SVG reads as infographic |
| Structured pedagogical figure (menu, tree diagram, PISA two-panel) | Case-by-case; prefer `html` if figure needs semantic annotation hooks, `gpt_image` if textbook-atlas aesthetic is primary | Split 1-2 in 15-spec eval |

## Phase A outcome (issue #108)

The Phase A evaluation (`docs/figure-rendering-evaluation.md`) recorded a
**NO-GO (for now)** decision for adding a frontend TS renderer.

- **HYBRID (recorded 2026-07-18 by operator, provisional — census gate remains unmet)**:
  The 15-spec fidelity evaluation (see `docs/figure-rendering-evaluation.md`) showed the
  frontend TS renderer prototype produced usable output on only 2/15 illustrative specs and
  never won head-to-head. LLM-HTML+Playwright and gpt-image-2 tied 7-7 (+1 tie) but
  specialize on different figure categories: HTML wins tables and semantic-overlay charts
  (6/7 in the sample); gpt-image-2 wins realistic diagrams / maps / lab apparatus /
  biology (4/4). Decision: introduce category-based routing per the "Renderer selection
  matrix" section below, and do NOT ship `render_mode: "frontend_ts"` as originally
  planned in `docs/superpowers/plans/2026-07-18-frontend-ts-render-mode.md` (that plan is
  now superseded). The `>=30 questions per subject` census gate remains unmet
  (production has 2 records total on 2026-07-18); this decision is provisional and MUST
  be revisited once production accumulates ~30 real questions per subject. `"html"`
  remains permanently accepted as a legacy alias for already-generated questions;
  `"frontend_ts"` is NOT introduced.

## Gate evidence collection and re-evaluation (issue #110)

Two tools collect the evidence the NO-GO above requires. Both are safe to run
against staging or production data at any time.

1. **Production census** — classifies every `chart_spec` stored in
   `generation_records` (per-user history, `server/models.py`):

   ```bash
   DATABASE_URL=<staging-or-prod-url> uv run python scripts/census_chart_specs.py
   # gate-check mode (exit 1 while the gate is unmet):
   DATABASE_URL=<url> uv run python scripts/census_chart_specs.py --check
   ```

   The gate requires **>= 30 questions per subject** (math, social_studies,
   natural_sciences). Paste the emitted Markdown into
   `docs/figure-rendering-evaluation.md` under "Historical coverage".

2. **Live fidelity comparison** — renders every illustrative spec through the
   server path and reviews it side-by-side with the frontend TS prototype:

   ```bash
   DATABASE_URL=<url> uv run python scripts/build_fidelity_manifest.py --limit 12
   ```

   Then open `/fidelity-compare` in a frontend built with
   `VITE_ENABLE_FRONTEND_TS_RENDERER=1`, load `fidelity/manifest.json`, rate
   each pair (match / minor-diff / broken), and paste the exported Markdown
   into `docs/figure-rendering-evaluation.md` under "Fidelity". The measured
   fallback rate is the share of rows marked `fallback (PNG)`.

### Re-running Phase A

When the census gate is MET and the fidelity table holds measured verdicts,
the operator re-evaluates:

- **GO / HYBRID** — record the dated decision in this file (replacing the
  NO-GO bullet above), then execute Part B of
  `docs/superpowers/plans/2026-07-18-frontend-ts-render-mode.md` in its task
  order: this policy file first, then the context-builder docstrings, then the
  `CONTENT_TYPE_INSTRUCTIONS` tables, per the update rule this repo codifies.
- **NO-GO again** — record the dated decision in
  `docs/figure-rendering-evaluation.md` and leave `render_mode` unchanged.

The decision is made by a human operator, not by an agent: an agent may
prepare the evidence but must not self-declare GO.

## What each subject's prompt must instruct

The three prompt assemblers already encode this rule in their
`CONTENT_TYPE_INSTRUCTIONS` tables (`src/context_builder.py`,
`src/social_studies/context_builder.py`,
`src/natural_sciences/context_builder.py`). The table applies at the level
where the content type is configured: `題目內容類型` (or `文本素材類型` for
社會領域 全域), including a per-小題 configuration for 題組 subjects.

| 題目內容類型 | Instruction MUST direct the model to |
| --- | --- |
| `純文字` | Omit `chart_spec` entirely. |
| `含圖片` | Emit `chart_spec` with `render_mode: "gpt_image"` for realistic diagrams (maps, lab apparatus, biology, real-world-proportion geometry) and `render_mode: "html"` for structured/semantic content (menus, scenario cards, layouts, forms). |
| `graphs/charts/tables` | Emit `chart_spec` with `render_mode: "chart"` for statistical charts; `render_mode: "html"` for tables and semantic-overlay charts. |
| `customized` | Follow the user-supplied instruction verbatim; no default. |

For 社會領域 and 自然科學, a per-小題 `含圖片` or
`graphs/charts/tables` configuration therefore requires the 小題's own
`SubQuestion.chart_spec` to be non-null. 自然科學 now follows the same
per-小題 image contract as 社會領域: its schema carries both `chart_spec`
and `image_generation_mode`, and its 子題 prompt echoes the configured
content type and image mode while requiring the visual spec. The NS
`_NS_SPEC` wires one repair attempt per missing required 小題 spec before
rendering; an unusable or failed repair leaves that 小題 without an image and
does not abort the 題組. `image_generation_mode` selects the rendering
backend only—by itself it never requires an image, and a `純文字` 小題 does
not trigger the repair.

## Enforcement

- Figure-kind diversity across SS 題幹 and 小題 images is specified in [ADR 0015](adr/0015-figure-kind-diversity-is-a-layered-guarantee.md); it does not currently extend to NS (see [ADR 0017](adr/0017-ns-subquestion-image-support-mirrors-social-studies.md)).

- `tests/test_figure_rendering_policy.py::test_plain_text_bans_chart_spec`,
  `::test_illustrative_content_routes_to_gpt_image_or_html`, and
  `::test_quantitative_content_routes_to_chart_and_html_for_tables` assert the
  `CONTENT_TYPE_INSTRUCTIONS` strings for each of the three subjects contain
  the correct `render_mode: "…"` fragment.
- `tests/test_figure_rendering_policy.py::test_dispatch_chart_render_mode_uses_matplotlib`,
  `::test_dispatch_html_render_mode_uses_playwright`,
  `::test_dispatch_gpt_image_mode_bypasses_render_mode`, and
  `::test_dispatch_unknown_render_mode_returns_none` fixture-test that
  `render_image()` in `src/renderer.py` dispatches each ImageSpec to the
  intended renderer.
- `tests/test_figure_rendering_policy.py::test_dispatch_gpt_image_render_mode_calls_llm_generate_image`
  asserts `render_mode: "gpt_image"` routes to `LLMClient.generate_image()`.
- `tests/test_hybrid_routing_schema.py::test_imagespec_accepts_gpt_image_render_mode`
  asserts the schema Literal accepts `"gpt_image"` across all three subjects.
- `src/common/figure_policy.py` — pure validator: `validate_figure_routing` and `validate_question_figure_routing` enforce the policy table programmatically.
- `tests/test_figure_rendering_policy.py` — classification tests (appended section): given a parsed item, asserts `chart_spec.render_mode` matches declared `題目內容類型`; also checks instruction-string/validator consistency.

## Out of scope of this policy

- matplotlib improvements to individual chart renderers.
- Migrating already-generated questions to a different `render_mode`.
- Interactive (non-static) question features.
