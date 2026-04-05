# Implementation Plan

## Geometry Renderer: Remove Hardcoded Patterns

**Status:** To be fixed  
**Priority:** Medium  
**File:** `src/renderer.py`

### Current Behavior

`_render_geometry()` (line ~275) uses a 3-tier approach:

1. **Hardcoded pattern matching** — checks `data` keys to dispatch to fixed renderers:
   - `"rectangle" in data and "triangle" in data` -> `_render_geometry_courtyard()` (lines ~298-338)
   - `"lamp_height" in data` -> `_render_geometry_shadow()` (lines ~341-370)
2. **LLM-assisted code generation** — `_render_geometry_via_llm()` calls Sonnet to write matplotlib code from `description` + `data`, then `exec()`s it
3. **Text fallback** — renders `description` as plain centered text (last resort)

### Problem

The hardcoded patterns are brittle:
- They only match two very specific `data` shapes (courtyard and shadow)
- They duplicate rendering logic that the LLM path handles generically
- Any new geometry type requires adding another hardcoded branch
- If the LLM's `chart_spec.data` structure drifts even slightly from the expected keys, it silently falls through to LLM or text fallback

### Planned Change

Remove `_render_geometry_courtyard()` and `_render_geometry_shadow()` entirely. Make `_render_geometry_via_llm()` the primary renderer for all geometry types when an LLM client is available.

New 2-tier flow:
1. **LLM-assisted rendering** (primary) — always used when `llm_client` is provided
2. **Text fallback** — only when no LLM client (e.g., `--dry-run` or offline mode)

### Functions to Remove

| Function | Lines | Reason |
|---|---|---|
| `_render_geometry_courtyard()` | ~298-338 | Replaced by LLM path |
| `_render_geometry_shadow()` | ~341-370 | Replaced by LLM path |

### Functions to Modify

| Function | Change |
|---|---|
| `_render_geometry()` | Remove hardcoded `if` branches, go straight to `_render_geometry_via_llm()` |

### Risks

- LLM-only path adds latency (one extra API call per geometry image)
- LLM-generated code may occasionally fail to exec — the text fallback still catches this
- Costs slightly more API tokens per geometry question

### Verification

After removing hardcoded patterns:
```bash
# Should still render geometry via LLM
uv run python -m src generate --style with_image

# Verify courtyard/shadow-like specs still render correctly through LLM path
# (use the chart_spec examples from data/few_shot/with_image/example_01.json)
```
