# Spec: 「圖片僅為示意，非完全等比例繪製」 disclaimer in all image prompts (issue #107)

## Why

No image-bearing prompt warns that rendered figures are illustrative. The generator LLM, verifier, and downstream solvers may treat sketched geometry as measurable (angles, lengths, proportions), producing ambiguous or unfair items. Repo-wide grep for the disclaimer phrase returns zero hits.

## Design

Append the exact string **「圖片僅為示意，非完全等比例繪製」** (verbatim, single source constant) to every prompt fragment that can cause an image to be rendered:

1. `src/context_builder.py` — `CONTENT_TYPE_INSTRUCTIONS["含圖片"]` and `["graphs/charts/tables"]`, plus the `render_mode: "html"` HTML-designer guidance block (instruct the HTML generator to place the disclaimer as a caption line inside the figure where layout allows).
2. `src/social_studies/context_builder.py` — same content-type blocks (global and per-小題 配置 rendering paths both flow through these constants).
3. `src/natural_sciences/context_builder.py` — same.
4. Verifier prompts (`src/verifier.py`, `src/social_studies/verifier.py`, `src/natural_sciences/verifier.py`): add one line telling the verifier the figure is 示意圖 — do not fail a question solely because the rendered figure is not to scale, but still fail on wrong data values/labels.

Implementation detail: define the phrase once per module as `IMAGE_DISCLAIMER = "圖片僅為示意，非完全等比例繪製"` (or a small shared constant in `src/common/`) and interpolate, so tests can import it.

## Testing

- For each subject: build a user prompt with content type 含圖片 and with graphs/charts/tables → assert the phrase is present; with 純文字 → absent.
- Assert the HTML-designer prompt for `render_mode: "html"` contains the phrase.
- Assert each verifier system prompt contains the not-to-scale leniency line.

## Out of scope

- Forcing the disclaimer into rendered question text (題目 array) — the prompt asks the model to caption figures, but we do not post-process outputs.
- Retroactive updates to already-generated questions.
