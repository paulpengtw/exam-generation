# Spec: Figure rendering — TS renderer evaluation + routing policy (issues #108 + #110, joint)

## Why

Routing *classification* already exists (`render_mode: "chart"` → matplotlib; `"html"` → LLM-HTML + Playwright), but the illustrative branch's execution end is server-side Playwright, and no policy doc or enforcement test codifies which figure type goes where. #108 asks whether a frontend TypeScript renderer should replace the Playwright path; #110 asks to codify the routing rule. Joint spec because #110's final enum/instructions depend on #108's outcome.

## Design

### Phase A — evaluation (#108)

Prototype a TS/SVG renderer in the web app that consumes the existing `chart_spec` JSON (`description` + `data`) for **illustrative** figures and renders client-side — starting with the 2–3 most common illustrative shapes observed in generated output (tables, simple geometry, scenario cards). Deliberately small: one `FigureRenderer.tsx` component behind a dev-only toggle, no charting library unless the prototype proves one necessary.

Evaluate against the current LLM-HTML + Playwright path on:

- **Fidelity** — side-by-side renders of ~10 real generated `chart_spec`s.
- **Latency/cost** — client render (no LLM call, no Playwright) vs current LLM call + screenshot.
- **Coverage** — fraction of real specs the deterministic TS component can express without an LLM (the free-form `description` field is the risk).
- **Export** — ODT export and the verifier both need a PNG; client-side rendering must still produce one (e.g. SVG→PNG serialization) or those flows keep the server path.

Outcome is a **go / no-go / hybrid decision** recorded in the policy doc. Note the likely result is *hybrid*: verifier + ODT keep server-side PNGs, so TS rendering mainly buys interactive display.

### Phase B — routing policy (#110)

Regardless of Phase A's outcome:

- `docs/figure-rendering-policy.md`: the rule — precise/quantitative statistical charts (histogram, boxplot, line, pie, and future numeric-axis charts) → matplotlib `render_mode:"chart"`; illustrative figures (geometry sketches, tables, menus, scenario diagrams) → the illustrative path (`render_mode:"html"` today; `"frontend_ts"` if Phase A says go), with examples per category.
- Top-of-file docstrings in the three `context_builder.py` files pointing at the policy doc.
- Classification test: for prompts built with 題目內容類型 = graphs/charts/tables vs 含圖片, assert the prompt instructions direct the LLM to the correct `render_mode`; plus a fixture-based test that sample `ImageSpec`s dispatch to the intended renderer in `render_image()`.

If Phase A is a go: add `"frontend_ts"` to the `render_mode` enum (schemas + `server/utility/routes.py`), update `CONTENT_TYPE_INSTRUCTIONS` to emit it for illustrative content, and keep `"html"` accepted as a legacy alias for already-generated questions.

## Error handling

`frontend_ts` specs the TS component cannot express fall back to the server HTML path (spec unchanged, renderer fallback), logged for coverage tracking.

## Testing

Phase A: component renders the fixture specs (Vitest snapshot); coverage script over historical specs. Phase B: classification/dispatch tests above; policy doc linked from CLAUDE.md.

## Out of scope

Matplotlib improvements; migrating already-generated questions; interactive (non-static) question features beyond rendering.
