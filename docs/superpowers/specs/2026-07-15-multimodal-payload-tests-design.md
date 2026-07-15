# Spec: Assert image block reaches Anthropic SDK call in multimodal tests (issue #106)

## Why

The multimodal pipeline (verifier/corrector image attachment) has no programmatic assertion that the image actually reaches the SDK payload. `_to_anthropic_content()` in `src/llm_client.py` silently drops unknown content-part shapes, so a refactor could make charts disappear from prompts while all tests stay green.

## Decision

Implement the issue's required part (a) — payload assertion tests — only. Runtime self-verify (part b) is out of scope (YAGNI; tests cover the regression risk).

## Design

New `tests/test_llm_client_multimodal.py`:

1. **Unit — `_to_anthropic_content()`:** feed a mixed `[{"type":"text",...}, {"type":"image_url","image_url":{"url":"data:image/png;base64,<tiny-png>"}}]` list; assert the output contains `{"type":"image","source":{"type":"base64","media_type":"image/png","data":<payload>}}` alongside the text block, in order.
2. **Unit — silent-drop guard:** an unknown part type is dropped today; assert current behavior explicitly (documented in the test) so any change is deliberate.
3. **Interception — `generate_with_image()`:** monkeypatch the SDK client's `messages.create` (or the streaming equivalent actually used) with a recorder returning a canned response; call `generate_with_image(..., image_path=<1×1 PNG tmp file>)`; assert the recorded `messages` array contains exactly one `image` block with `source.type == "base64"` and non-empty `data`.
4. **Verifier wiring:** extend `tests/test_social_studies_verifier.py`'s `FakeClient` flow — when `chart_image_path` is provided, assert the fake receives a non-None `image_path` and the prompt contains 「## 附圖」; mirror for math and natural-sciences verifiers if their fakes exist (add minimal ones if not).

Use a checked-in 1×1 transparent PNG built in-test via `base64.b64decode` of a constant — no binary fixture files.

## Testing

The spec *is* tests; acceptance = new tests fail if `_to_anthropic_content` drops the image block or if verifier stops threading `chart_image_path`.

## Out of scope

- Runtime self-verify/assertions in production code.
- gpt_image generation path tests (different client method).
