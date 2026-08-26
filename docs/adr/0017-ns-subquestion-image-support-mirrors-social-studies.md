# natural sciences 小題 image support mirrors social studies

## Context

社會領域 already supports per-小題 visual material: a visual 小題 carries
its own `chart_spec`, uses `image_generation_mode` only to choose the
rendering backend, receives one repair attempt when a required spec is
missing, and degrades gracefully if repair or rendering cannot produce an
image. Issues #530 and #531 brought 自然科學 onto the same per-小題 image
path. The written policy must describe that path without treating NS as
top-level-image-only.

## Decision

自然科學 adopts the same per-小題 image contract as 社會領域.

- `SubQuestion` carries `chart_spec` and `image_generation_mode`. The NS
  子題 prompt echoes the configured `題目內容類型` and `圖片生成模式`.
- A configured `含圖片` or `graphs/charts/tables` 小題 must emit a non-null
  小題專用 `chart_spec`, with its `render_mode` selected by the figure
  family. A `純文字` 小題 has no image requirement.
- `image_generation_mode` is rendering-only. It selects `html` or
  `gpt_image` for a spec that exists; it does not force a spec or an image.
- `_NS_SPEC` supplies `ensure_visual_spec_fn` and
  `render_subquestion_images_fn`. After the 子題 are assembled, each missing
  required visual spec receives one repair attempt before non-null specs are
  rendered to the 小題 image path. A failed or unusable repair leaves the
  `chart_spec` absent and the 題組 continues without that image.

Issue #580 extends the layered figure-kind-diversity guarantee in ADR 0015 to
自然科學. NS now uses the same shared canonical vocabulary and policy helpers;
its `ImageSpec` and `SubQuestionConfig` carry the declaration/pin fields,
`SampledParams` carries the request-level duplicate kill-switch, and `_NS_SPEC`
wires declaration/collision enforcement and trail emission around rendering.
The guarantee remains free-text and degrade-never-block, so NS-specific genres
remain valid without changing the shared data file.

The end-to-end contract is exercised by
`tests/test_ns_subq_image_contract.py`; the missing-spec repair, pure-text and
mode-only guards, and graceful failure are exercised by
`tests/test_ns_subq_chart_spec_repair.py`.

## Consequences

Natural-sciences visual 小題 can now render independently and can carry their
own generated PNG in the same way as Social Studies. A missing required spec
may add one repair call for that 小題, but a failed repair is visible as a
missing image rather than a failed 題組. The renderer mode remains independent
of whether a visual spec is required, while the shared ADR 0015 declaration,
collision, and degrade-never-block policy applies to every NS visual spec that
reaches rendering.

## Explicitly Rejected Alternatives

Keeping NS as top-level-image-only was rejected because the NS schema,
subquestion prompt, rendering hook, and contract tests now support
`SubQuestion.chart_spec`. Treating `image_generation_mode` as an image
requirement was rejected because mode-only or `純文字` slots must not trigger
repair or rendering. Making a failed repair abort the 題組 was rejected in
favor of the existing graceful-degradation behavior.
