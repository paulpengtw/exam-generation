# Frontend TS Renderer — Phase A Evaluation (issue #108)

## Scope

Prototype: `web/src/components/FigureRenderer.tsx` covering three illustrative
shapes — tables, simple SVG geometry, scenario cards. Gated behind
`VITE_ENABLE_FRONTEND_TS_RENDERER`. Compared against the current LLM-HTML +
Playwright path. Live browser side-by-side testing was not possible in this
environment (headless dev container, no operator screenshots); all findings below
are either measured from the codebase or **reasoned-from-architecture** (labeled
explicitly).

## Historical coverage

Output of `uv run python scripts/analyze_chart_spec_coverage.py output/`:

> **Unmeasured.** The `output/` directory is empty in this repository — no
> previously generated questions are committed. The coverage script
> (`scripts/analyze_chart_spec_coverage.py`) ran successfully and found 0 JSON
> files to classify. Additionally, the few-shot corpora nest specs under a top-level
> `question` key that the census script intentionally does not unwrap; those
> entries are also excluded from counts.
>
> **Conclusion:** No production distribution is available. All coverage claims in
> this evaluation are architectural inferences, not measured percentages. A
> meaningful census requires generating ≥30 questions per subject and re-running
> the script.

| Metric | Value | Source |
| --- | --- | --- |
| JSON files scanned | 0 | measured |
| chart_spec occurrences found | 0 | measured |
| render_mode: "chart" | — | unmeasured |
| render_mode: "html" | — | unmeasured |
| render_mode: "frontend_ts" | — | unmeasured (enum not yet shipped) |

## Fidelity (side-by-side of real specs)

Live fidelity testing was **not performed** — the dev container is headless and no
operator browser session was available to supply screenshots. The following table
summarises what can be inferred from reading the prototype source:

| # | 題目內容類型 | shape | TS render | server PNG | verdict |
| --- | --- | --- | --- | --- | --- |
| 1 | 含圖片 | table | renders via `<table>` DOM | Playwright PNG | **reasoned: match** for simple grids |
| 2 | 含圖片 | simple-geometry | renders SVG inline | Playwright PNG | **reasoned: match** for supported primitives |
| 3 | 含圖片 | scenario-card | renders styled `<div>` | Playwright PNG | **reasoned: match** for text-card layouts |
| 4 | 含圖片 | any other shape | returns `null` + logs `[figure-renderer-fallback]` | Playwright PNG | **broken** (falls back; no TS display) |
| 5 | graphs/charts/tables | histogram / boxplot / line / pie | not covered by TS prototype | matplotlib PNG | **reasoned: match** (quantitative path unchanged) |

No verdicts above are based on observed pixel output. They are annotated
**reasoned** to distinguish them from measured results.

## Latency

- **LLM-HTML + Playwright path** (reasoned-from-architecture): each illustrative
  render incurs one Sonnet HTML-generation LLM call (~1–3 s at p50 under normal
  API latency) plus a Playwright screenshot (~0.5–1 s). Total round-trip typically
  3–5 s per illustrative `chart_spec`. No live measurement was taken.
- **Frontend TS path** (reasoned-from-architecture): zero LLM calls, zero server
  round-trips beyond the initial JSON payload. Time-to-visible is bounded by
  React render time, typically < 50 ms. Applies only to the three supported shapes;
  unsupported shapes still pay the full server cost via the fallback.

No DevTools Performance measurements are available for this evaluation cycle.

## Cost

Every illustrative render in the current path incurs one Sonnet HTML-image call
(see `src/renderer.py::_generate_html_via_llm`). The TS path incurs zero for the
three supported shapes. At current prototype coverage (3 shapes, unknown share of
production traffic), estimated savings are **unmeasured**. A meaningful estimate
requires a production census (see Historical coverage above).

## Coverage

- Total illustrative specs observed in production output: **0** (empty `output/`).
- TS component coverage by shape: table / simple-geometry / scenario-card → 3 shapes
  supported; all other shapes → fallback (`[figure-renderer-fallback]` log line).
- Fallback rate: **unmeasured** (no production distribution available).
- The prototype is display-only (verifier and ODT export continue to consume the
  server-side PNG `image_base64` regardless of this flag).

## Export constraint

Verifier and ODT export both consume the server-side PNG (`image_base64`).
Even in the "go" outcome, the server path stays for those flows — TS
rendering only affects on-page display.

## Decision

**NO-GO (for now)** — No production distribution exists (empty `output/`, few-shot
corpora not unwrapped by the census), and no live fidelity comparison was
possible in the headless container. Under these conditions a GO is unjustified.
The prototype's three supported shapes have no correctness risk (they are
display-only behind a flag), so the prototype remains in-tree behind
`VITE_ENABLE_FRONTEND_TS_RENDERER` for continued experimentation. However, Task 10
of the plan (extending `render_mode` with `"frontend_ts"`) is deferred. A full GO
requires a production census (≥30 questions per subject) and a live fidelity
comparison with measured fallback rates. When those conditions are met, re-run
Phase A; if the outcome is GO or HYBRID, Task 10 extends the `render_mode` enum
with `"frontend_ts"` and updates `CONTENT_TYPE_INSTRUCTIONS`; the `"html"` value
remains a permanent legacy alias.

**Gate tooling (added 2026-07-18, issue #110 Part A):** the census now reads
production `generation_records` via `scripts/census_chart_specs.py` (`--check`
exits 1 while any subject is below 30 questions), and the live fidelity
comparison is performed with `scripts/build_fidelity_manifest.py` plus the
web `/fidelity-compare` page. Replace the "Unmeasured" blocks above with the
Markdown those tools emit when re-running Phase A.
