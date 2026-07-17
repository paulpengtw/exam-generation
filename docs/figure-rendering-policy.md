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
| Illustrative figures | 幾何示意圖, 座標平面, 數線, 表格, 菜單, 廣告, 海報, 情境卡, 流程圖 | `"html"` (or `"frontend_ts"` — see below) | LLM-HTML + Playwright (`src/renderer.py::_generate_html_via_llm` + `src/html_renderer.py`) |

### Why this split

- Statistical charts have deterministic axes, tick labels, and derived
  aggregates (mean, median, quantiles). Rendering them via an LLM introduces
  drift between the numeric spec and the pixels a student reads. matplotlib
  is deterministic and cheap; keep it authoritative.
- Illustrative figures are open-ended — no fixed axes, arbitrary layout,
  domain-specific pictorial conventions (e.g. a museum menu, a bus route
  card). The HTML path lets the LLM invent layout details the schema does
  not encode; this is the correct trade-off for that family.

## Phase A outcome (issue #108)

The Phase A evaluation (`docs/figure-rendering-evaluation.md`) recorded a
**NO-GO (for now)** decision for adding a frontend TS renderer.

- **NO-GO (for now)**: `render_mode` stays `Literal["chart", "html"]` as the
  shipped default. Task 10 of the plan (extending `render_mode` with
  `"frontend_ts"`) is deferred pending production evidence. The frontend TS
  prototype remains behind `VITE_ENABLE_FRONTEND_TS_RENDERER` for continued
  experimentation. A full GO (triggering Task 10) requires both a production
  census (≥30 questions per subject) and a live fidelity comparison with
  measured fallback rates. When that evidence is collected, re-run Phase A;
  if the outcome is GO or HYBRID, Task 10 extends `render_mode` with
  `"frontend_ts"` for illustrative figures whose display can be done
  client-side. Verifier and ODT export would still consume the server-side
  PNG, so illustrative specs would also keep producing one — the frontend TS
  renderer replaces the on-page `<img>` display only. `"html"` remains
  permanently accepted as a legacy alias for already-generated questions.

## What each subject's prompt must instruct

The three prompt assemblers already encode this rule in their
`CONTENT_TYPE_INSTRUCTIONS` tables (`src/context_builder.py`,
`src/social_studies/context_builder.py`,
`src/natural_sciences/context_builder.py`). Concretely, given
`題目內容類型` (or `文本素材類型` for 社會領域 全域):

| 題目內容類型 | Instruction MUST direct the model to |
| --- | --- |
| `純文字` | Omit `chart_spec` entirely. |
| `含圖片` | Emit `chart_spec` with `render_mode: "html"` (illustrative path). |
| `graphs/charts/tables` | Emit `chart_spec` with `render_mode: "chart"` when a listed statistical chart applies; otherwise `render_mode: "html"` for tables. |
| `customized` | Follow the user-supplied instruction verbatim; no default. |

## Enforcement

- `tests/test_figure_rendering_policy.py::test_prompt_routes_illustrative_to_html`
  and `::test_prompt_routes_quantitative_to_chart` assert the
  `CONTENT_TYPE_INSTRUCTIONS` strings for each of the three subjects contain
  the correct `render_mode:"…"` fragment.
- `tests/test_figure_rendering_policy.py::test_dispatch_matches_render_mode`
  fixture-tests that `render_image()` in `src/renderer.py` dispatches each
  ImageSpec to the intended renderer.

## Out of scope of this policy

- matplotlib improvements to individual chart renderers.
- Migrating already-generated questions to a different `render_mode`.
- Interactive (non-static) question features.
