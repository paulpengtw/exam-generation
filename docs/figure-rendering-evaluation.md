# Frontend TS Renderer — Phase A Evaluation (issue #108)

## Scope

Prototype: `web/src/components/FigureRenderer.tsx` covering three illustrative
shapes — tables, simple SVG geometry, scenario cards. Gated behind
`VITE_ENABLE_FRONTEND_TS_RENDERER`. Compared against the current LLM-HTML +
Playwright path. Live browser side-by-side testing was not possible in this
environment (headless dev container, no operator screenshots); all findings below
are either measured from the codebase or **reasoned-from-architecture** (labeled
explicitly).

## Historical coverage (2026-07-18 provisional)

The census gate for this evaluation (>=30 real production questions per subject in the DB) was **not met** — production currently contains 2 questions total. In lieu of a census, we ran a **15-spec fidelity comparison** drawn from few-shot examples (7 math, 5 social studies, 3 hand-crafted natural sciences). This sample is small, table-heavy (4/15), and NS is hand-crafted rather than production-observed. Treat every number below as directional evidence, not a locked baseline. The full census gate should be revisited once production accumulates ~30 questions per subject.

Category distribution of the 15-spec sample:

| Category | Count | Notes |
|---|---|---|
| Table | 4 | Schedule, poll results, reservoir readings, material properties |
| Chart | 4 | Stock line, side-by-side score tables, multi-series aging line, histogram |
| Realistic diagram | 4 | Courtyard geometry, Falklands iceberg map, distillation apparatus, plant cell |
| Structured other | 3 | Menu, PISA two-panel with animal timeline, labour tree |

## Fidelity (three-way, 15 specs)

Each spec was rendered by three pipelines: (a) the frontend TS renderer prototype from PR #141, (b) the existing LLM-HTML + Playwright pipeline, and (c) gpt-image-2 with 3 candidate images per spec (best-of-3 selected). Quality was scored 1-5 by a rubric focused on spec fidelity, print-exam legibility, and textbook idiom.

| Renderer | Produced output | matches_spec (of produced) | Avg quality | Head-to-head wins |
|---|---|---|---|---|
| Frontend TS | 2/15 (13%) | 2/2 | 2.0 | 0 |
| LLM-HTML + Playwright | 15/15 (100%) | 15/15 | 4.27 | 7 |
| gpt-image-2 (best-of-3) | 15/15 (100%) | 15/15 | 4.47 | 7 (+1 tie with HTML) |

**Category-conditioned wins:**

| Category | HTML wins | GPT wins | Tie | TS wins |
|---|---|---|---|---|
| Table (n=4) | 3 | 0 | 1 | 0 |
| Chart (n=4) | 3 | 1 | 0 | 0 |
| Realistic diagram (n=4) | 0 | 4 | 0 | 0 |
| Structured other (n=3) | 1 | 2 | 0 | 0 |

Where **HTML wins:** it consistently adds domain-specific semantic overlays that gpt-image-2 does not reliably reproduce — the 2020 推估值 vertical divider with dashed post-2020 projection segments on the multi-series aging chart, red highlights on 2021/5/31 drought values in the reservoir table, inline (%) header suffixes, the ※ ratio-meaning footnote, styled shaded headers, the week separator + companion data table on the stock chart, and compact side-by-side table layouts sized for exam print.

Where **gpt-image-2 wins:** it delivers textbook-atlas fidelity that HTML rendering does not currently achieve — realistic Patagonia and South Georgia coastlines with graticule on the Falklands map, correct distillation geometry (thermometer inserted through stopper, inclined water-cooled condenser, alcohol lamp under tripod) for the lab apparatus, cleanly labelled biology diagrams with balanced organelle placement, correctly proportioned geometry with legends citing ∠C=90°, and textbook-idiomatic histograms with arrow-tipped axes and filled bars. HTML in these categories reads as a stylized infographic (thermometer floating above flask, condenser as flat colored bar, coastline shapes reduced to schematic outlines, clipped/overlapping labels).

**TS renderer status:** fell back to a placeholder on 13/15 specs. The two specs where it produced output were (i) the menu spec, where it dumped raw description text into a beige rounded box with no menu structure (quality 1), and (ii) the NS material-properties data table, where it rendered a functional but visually plain table with no title/footnote/hierarchy (quality 3). It never won a head-to-head comparison.

## Decision (provisional; supersede after census gate is met)

Given the 7-7 head-to-head split between HTML and gpt-image-2 with a clear category signal, and given that TS never won and rendered on only 13% of specs, the routing decision is **hybrid, not TS-first**:

1. **Tables and charts with semantic overlays** → `render_mode: "html"` (existing Playwright pipeline). HTML wins 6/8 in these categories on the strength of semantic annotations, compact print layouts, and title/footnote handling that gpt-image-2 does not reliably reproduce.
2. **Realistic diagrams, maps, lab apparatus, biology, real-world-proportioned geometry** → `image_generation_mode: "gpt_image"` default. gpt-image-2 wins 4/4 diagram_realistic + 2/3 structured_other, with textbook-atlas fidelity that the HTML+SVG path does not currently deliver.
3. **Deterministic statistical charts** (histogram, boxplot, line, pie without domain overlays) → `render_mode: "chart"` (matplotlib) remains the default for reproducibility; fall through to gpt_image only if the prompt explicitly requests a textbook aesthetic (as with the histogram spec where GPT c1 clearly beat matplotlib-style HTML).
4. **Frontend TS renderer track** (docs/superpowers/plans/2026-07-18-frontend-ts-render-mode.md, Part B) — **do not proceed as planned**. The evidence does not justify shipping a `render_mode: "frontend_ts"` for illustrative content. Options: close the plan, or heavily re-scope it to only the simple-table category where TS was at least functional (quality 3) and even then HTML dominated by ~2 points.

Confidence: **medium-low**. The 15-spec sample is well under the >=30-per-subject census gate, table-heavy, and NS is hand-crafted. The direction (HTML for tables/overlays, gpt_image for realistic diagrams, TS not viable) is robust across the sample but the exact thresholds should be revisited once production accumulates ~30 questions per subject.
