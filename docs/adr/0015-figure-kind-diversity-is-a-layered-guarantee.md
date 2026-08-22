# figure-kind diversity is a layered guarantee

## Context

The supervisor requires every social-studies 題組 to use distinct 圖像種類 across
the shared 題幹 image and all 小題 images. Both `ExamQuestion` and each
`SubQuestion` can carry an image spec, and the images are rendered separately.
The concrete figure type must therefore be comparable across renderers: an HTML
chart with semantic overlays and a matplotlib chart of the same chart family
have the same 圖像種類. Rendered pixels are not a validation input.

## Decision

We use a layered guarantee: prompts declare the `figure_kind` field and steer
the model toward a small canonical vocabulary; the parsed specs are then
validated deterministically; and each detected collision receives one targeted
repair call with the already-used kinds listed as forbidden. The validator
compares normalized kinds (strip and casefold), uses `chart_type` as the
effective fallback for empty `figure_kind` on `render_mode: "chart"` specs,
and treats an empty kind as incomparable.

`figure_kind` remains free text so new genres never make Pydantic parsing fail.
The canonical labels live in a JSON data file and guide prompts and
normalization rather than acting as a strict enum. Repairs prefer unpinned
specs; when both colliders are unpinned, a later 小題 is preferred over the
題幹 and an earlier 小題. A per-小題 pin is forced onto its resulting spec,
never becomes a repair target, and two pinned 小題 may intentionally share a
kind. If a pinned 小題 collides with the 題幹, the 題幹 yields and is re-rendered
to its existing PNG filename after repair. A request-level
`allow_duplicate_figure_kinds` kill-switch skips validation and removes the
hard prompt prohibition.

If one repair still leaves a collision, the duplicate image ships and a warning
is emitted to stderr and the rendering observer; images are never silently
dropped.

## Consequences

The guarantee is robust to model omissions and renderer changes, while the
free-text boundary keeps the schema forward-compatible. A repair can add one
more generation call per collision, and a 題幹 repair can re-render an image that
was already produced. The fallback warning makes unresolved model or service
failures visible without turning generation into an all-or-nothing operation.

## Explicitly Rejected Alternatives

Prompt-only steering, as used for the advisory diversity hint in ADR 0007, is
not sufficient for a supervisor-level guarantee. A strict enum would make new
figure genres brittle at the parsing boundary. An LLM judge comparing image
semantics would be nondeterministic, more expensive, and would validate pixels
or model interpretations rather than the declared specs. Dropping a duplicate
image would make a valid 小題 lose required visual material, so unresolved
duplicates are shipped with a warning instead.
