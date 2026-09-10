# The image_spec fallback ladder lives in one shared, never-raising parser

The same three-rung fallback ladder — direct construction, chart-mode repair, HTML-mode fallback — was hand-copied into four sites across two subject CLI modules: `_parse_text_shell` (social studies and natural sciences), `_parse_image_spec` (social studies), and `_parse_subquestion_image_spec` (natural sciences).  Each copy differed in two ways: the unguarded `_parse_text_shell` copies raised on rung-2 failure instead of returning `None`, and the social studies `_parse_text_shell` copy forgot to carry the `html` field in the HTML rung.

We decide that **the ladder collapses onto one function, `parse_image_spec(raw_spec, model_cls) -> model | None`, in `src/common/image_spec_parsing.py`**, shared by both subjects.  Every former ladder site now calls this function; every subject-scoped duplicate is removed.  The math/legacy `src/cli.py` has its own inline copy and is out of scope for this change — it is left untouched and noted here for a future cleanup ticket.

## Rung semantics

1. **Direct construction** (`model_cls(**raw_spec)`): succeeds for all valid payloads and, after the field coercers added in #630 and #631, for any payload whose only problems are wrong-typed `data`, `labels`, `title`, `description`, or `figure_kind`.
2. **Chart-mode repair** (tried only when `chart_type` is present): forces `render_mode="chart"` to recover from a bad `render_mode`.  If `chart_type` is also invalid, the function returns `None` and does **not** attempt the HTML rung — a model that explicitly supplied an invalid chart type should not be silently converted into an HTML spec.
3. **HTML-mode fallback** (tried only when no `chart_type` is present): forces `render_mode="html"` and preserves the `html` field, which the old `_parse_text_shell` ladder forgot to carry.

If all applicable rungs fail, or if `raw_spec` is not a dict, the function returns `None` without re-raising.

## Why the ladder earns its complexity

The ladder repairs exactly one class of real LLM failure: a bad `render_mode` (observed as `"pdf"` in a Sentry event preceding #630).  All other field-type errors are now absorbed by the Pydantic coercers.  If the coercers are ever extended to cover `render_mode` (e.g., mapping unknown strings to `"html"`), the fallback ladder could be removed entirely.

## Consequences

- `src/common/image_spec_parsing.py` is the single authoritative location for the ladder; a change to fallback semantics requires editing only that file.
- The function takes the model class as a parameter so the two subjects' distinct `ImageSpec` definitions remain independent.
- `_parse_image_spec` (social studies) and `_parse_subquestion_image_spec` (natural sciences) are kept as thin wrappers around `parse_image_spec` to preserve the call sites that hold a reference to them (e.g., `_ns_build_vs_repair` and `_ss_repair_figure_kind`).
- The math/legacy `src/cli.py` ladder is a known duplicate; it is left alone until a dedicated cleanup ticket addresses the math subject's image-spec handling.
