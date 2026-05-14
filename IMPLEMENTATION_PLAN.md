# Implementation Plan

## Known Tech Debt

No active refactors planned. Current state:

- **Geometry renderer removed (completed):** `_render_geometry`, `_render_geometry_courtyard`, and `_render_geometry_shadow` were removed. All non-chart images now use `render_mode: "html"` — Sonnet generates a self-contained HTML/CSS/SVG document, which Playwright screenshots to PNG.
- **`ChartSpec` alias:** `src/schemas.py` exports `ChartSpec = ImageSpec` for backward compatibility with older LLM outputs. Remove once all few-shot examples use `image_spec`.
