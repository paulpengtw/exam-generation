# Multimodal Payload Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add regression tests that prove a chart image actually reaches the Anthropic SDK payload — both at the `_to_anthropic_content()` conversion boundary and at the `generate_with_image()` call site — and that every subject's verifier still threads `chart_image_path` through to the client (GitHub issue #106, required part (a) only).

**Architecture:** Tests-only change. A new `tests/test_llm_client_multimodal.py` covers two levels: (1) direct unit assertions on `_to_anthropic_content()` in `src/llm_client.py:123-140`, (2) an interception test that monkeypatches `Anthropic.messages.create` on an `LLMClient` instance to record the exact `messages` array reaching the SDK. Then `tests/test_social_studies_verifier.py` is extended with an image-threading assertion, and two new files (`tests/test_verifier.py` for math, `tests/test_natural_sciences_verifier.py` for NS) mirror the same `FakeClient` pattern already used for social studies.

**Tech Stack:** pytest 9 (via `uv run pytest`), Python 3.11+, existing `FakeClient` monkeypatch pattern in `tests/test_social_studies_verifier.py`, in-memory 1×1 PNG built via `base64.b64decode` (no fixture files).

**Spec:** `docs/superpowers/specs/2026-07-15-multimodal-payload-tests-design.md`

## Global Constraints

- Tests-only change. Do **not** modify `src/llm_client.py`, `src/verifier.py`, `src/social_studies/verifier.py`, or `src/natural_sciences/verifier.py`.
- Runtime self-verify / production assertions (issue #106 part (b)) are **out of scope** — YAGNI per the spec.
- gpt_image path tests are **out of scope** — different client method (`generate_image`), covered by `tests/test_renderer_image_generation.py`.
- Every test that needs binary PNG bytes must construct them in-test via `base64.b64decode` of a constant — no checked-in binary fixture files.
- The interception test must exercise `LLMClient.generate_with_image()` with the real conversion path (`_to_anthropic_content`), only replacing the outermost `Anthropic.messages.create` call. It must run with `llm_stream=False` and no observer so the non-streaming branch in `LLMClient._call` (`src/llm_client.py:302-312`) is used.
- The "silent-drop" guard test documents current behaviour — it must have an in-comment note that the drop is intentional today so any future change lands via a deliberate test edit.
- All `pytest` invocations run from `/workspace/exam-generation` via `uv run pytest -q <test_target>`.
- Every task ends with a commit.

---

### Task 1: Unit tests for `_to_anthropic_content()`

**Files:**
- Create: `tests/test_llm_client_multimodal.py`

**Interfaces:**
- Consumes: `src.llm_client._to_anthropic_content` (module-level function at `src/llm_client.py:123-140`).
- Produces: `tests/test_llm_client_multimodal.py` with two test functions used by later tasks as the file they extend.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_llm_client_multimodal.py`:

```python
"""Regression tests: chart image reaches the Anthropic SDK payload.

Covers GitHub issue #106 part (a): programmatic assertions that
`_to_anthropic_content` preserves image blocks and that
`generate_with_image` sends them to `Anthropic.messages.create`.
"""

from __future__ import annotations

import base64

from src.config import Config
from src.llm_client import LLMClient, _to_anthropic_content

# 1×1 transparent PNG (67 bytes) — built in-test, no binary fixture file.
_TINY_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
_TINY_PNG_B64 = base64.b64encode(_TINY_PNG_BYTES).decode("ascii")
_TINY_PNG_DATA_URL = f"data:image/png;base64,{_TINY_PNG_B64}"


def test_to_anthropic_content_preserves_text_then_image_block() -> None:
    """A mixed [text, image_url] list must yield [text, image(base64)] in order."""
    openai_style = [
        {"type": "text", "text": "請根據圖表判斷趨勢。"},
        {"type": "image_url", "image_url": {"url": _TINY_PNG_DATA_URL}},
    ]

    result = _to_anthropic_content(openai_style)

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0] == {"type": "text", "text": "請根據圖表判斷趨勢。"}
    assert result[1] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": _TINY_PNG_B64,
        },
    }


def test_to_anthropic_content_silently_drops_unknown_part_types() -> None:
    """Current behaviour: unknown content-part shapes are dropped silently.

    This test documents that today's implementation drops any part whose
    `type` is not "text" or "image_url" (see src/llm_client.py:128-140).
    If someone changes that behaviour, this assertion will fail and force
    a deliberate update — that's the guard.
    """
    openai_style = [
        {"type": "text", "text": "before"},
        {"type": "tool_use", "id": "call_1", "name": "x", "input": {}},
        {"type": "image_url", "image_url": {"url": _TINY_PNG_DATA_URL}},
    ]

    result = _to_anthropic_content(openai_style)

    # tool_use dropped; text and image survive.
    assert [p["type"] for p in result] == ["text", "image"]
    assert result[0]["text"] == "before"
    assert result[1]["source"]["data"] == _TINY_PNG_B64
```

- [ ] **Step 2: Run tests to verify they fail if the function regresses**

Because these tests target existing behaviour of `_to_anthropic_content()`, they should **pass** on the current tree — the "failing test" step for this task is: temporarily break `_to_anthropic_content` locally (e.g. return `[result[0]]` to drop images) to confirm the tests catch it, then revert. Run this now to confirm the tests pass against the untouched source:

Run: `uv run pytest -q tests/test_llm_client_multimodal.py::test_to_anthropic_content_preserves_text_then_image_block tests/test_llm_client_multimodal.py::test_to_anthropic_content_silently_drops_unknown_part_types`
Expected: PASS — 2 tests green. (These are regression sentinels — they fail only if `_to_anthropic_content` starts dropping images.)

- [ ] **Step 3: Sanity-check the failure mode (manual)**

Temporarily edit `src/llm_client.py` line 138–139 to `continue` inside the `image_url` branch (dropping the image), rerun the command from Step 2, and confirm `test_to_anthropic_content_preserves_text_then_image_block` fails with an assertion on `len(result) == 2`. Then revert the edit. **Do not commit the temporary edit.**

- [ ] **Step 4: Commit**

```bash
git add tests/test_llm_client_multimodal.py
git commit -m "test(llm_client): guard _to_anthropic_content against image-block drops (#106)"
```

---

### Task 2: Interception test for `generate_with_image()`

**Files:**
- Modify: `tests/test_llm_client_multimodal.py` (append new test)

**Interfaces:**
- Consumes: `src.llm_client.LLMClient`, `src.config.Config`; the constant `_TINY_PNG_BYTES` / `_TINY_PNG_B64` already defined in Task 1.
- Produces: A recorded `messages` array captured from `Anthropic.messages.create` for later inspection — the actual assertion is inline.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_llm_client_multimodal.py`:

```python
class _FakeAnthropicUsage:
    input_tokens = 10
    output_tokens = 5
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _FakeAnthropicTextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeAnthropicResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeAnthropicTextBlock(text)]
        self.usage = _FakeAnthropicUsage()


class _RecorderMessages:
    """Stands in for `Anthropic.messages`; records `create` kwargs."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs) -> _FakeAnthropicResponse:
        self.calls.append(kwargs)
        return _FakeAnthropicResponse('{"ok": true}')


def test_generate_with_image_sends_base64_image_block_to_sdk(tmp_path) -> None:
    """End-to-end: `generate_with_image` must place a base64 image block into
    the `messages` array reaching `Anthropic.messages.create`."""
    png_path = tmp_path / "chart.png"
    png_path.write_bytes(_TINY_PNG_BYTES)

    # Non-streaming path: no observer + llm_stream=False -> messages.create is used.
    client = LLMClient(Config(api_key="test-key", llm_stream=False))
    recorder = _RecorderMessages()
    client.client.messages = recorder  # type: ignore[assignment]

    client.generate_with_image(
        system="you are a verifier",
        user="請看下方圖表並回答。",
        image_path=png_path,
        purpose="verify",
    )

    assert len(recorder.calls) == 1
    call = recorder.calls[0]

    # System is a cache-controlled block, not part of `messages`.
    assert call["system"] == [
        {
            "type": "text",
            "text": "you are a verifier",
            "cache_control": {"type": "ephemeral"},
        }
    ]

    messages = call["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"

    user_content = messages[0]["content"]
    assert isinstance(user_content, list)
    image_blocks = [p for p in user_content if p.get("type") == "image"]
    text_blocks = [p for p in user_content if p.get("type") == "text"]

    assert len(image_blocks) == 1, "exactly one image block must reach the SDK"
    assert len(text_blocks) == 1
    assert text_blocks[0]["text"] == "請看下方圖表並回答。"

    source = image_blocks[0]["source"]
    assert source["type"] == "base64"
    assert source["media_type"] == "image/png"
    assert source["data"] == _TINY_PNG_B64
    assert len(source["data"]) > 0
```

- [ ] **Step 2: Run test to verify it passes against current source**

Run: `uv run pytest -q tests/test_llm_client_multimodal.py::test_generate_with_image_sends_base64_image_block_to_sdk`
Expected: PASS — the recorder captures exactly one image block, base64-encoded.

- [ ] **Step 3: Sanity-check the failure mode (manual)**

Temporarily edit `src/llm_client.py` line 138–139 so the `image_url` branch does not append to `result`. Rerun the command from Step 2 and confirm the test fails with `assert len(image_blocks) == 1`. Revert the edit; do not commit.

- [ ] **Step 4: Commit**

```bash
git add tests/test_llm_client_multimodal.py
git commit -m "test(llm_client): assert generate_with_image reaches SDK with image block (#106)"
```

---

### Task 3: Extend social-studies verifier test with image-threading assertion

**Files:**
- Modify: `tests/test_social_studies_verifier.py:11-22, 66-82`

**Interfaces:**
- Consumes: existing `FakeClient` and `_question()` helpers in the same file; `src.social_studies.verifier.verify_question`.
- Produces: One new test `test_verify_question_threads_chart_image_path_and_prompts_附圖` used only by this task.

- [ ] **Step 1: Write the failing test**

Append at the bottom of `tests/test_social_studies_verifier.py` (after `test_verify_question_preserves_clear_failure`):

```python
def test_verify_question_threads_chart_image_path_and_prompts_附圖(tmp_path) -> None:
    """When a chart image path is provided, verify_question must:
       (a) pass it through as `image_path` to the client, and
       (b) inject the 「## 附圖」 section into the user prompt."""
    png_path = tmp_path / "chart.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n")  # bytes irrelevant; FakeClient does not read

    client = FakeClient(
        {
            "my_answer": "作者支持擴大公共運輸。",
            "provided_answer": "作者支持擴大公共運輸。",
            "answer_match": True,
            "passed": True,
            "details": "素材圖片與文本一致。",
            "chart_verification": {
                "chart_data_match": True,
                "chart_labels_correct": True,
                "chart_details": "圖表標籤與題目描述一致。",
            },
        }
    )

    result = verify_question(client, _question(), chart_image_path=str(png_path))

    assert client.image_path == str(png_path)
    assert "## 附圖" in client.user_prompt
    assert result.chart_verification is not None
    assert result.chart_verification.chart_data_match is True
```

- [ ] **Step 2: Run test to verify it passes against current source**

Run: `uv run pytest -q tests/test_social_studies_verifier.py::test_verify_question_threads_chart_image_path_and_prompts_附圖`
Expected: PASS — the existing verifier already threads `chart_image_path` and appends `## 附圖`; this test locks that behaviour in.

- [ ] **Step 3: Sanity-check the failure mode (manual)**

Temporarily edit `src/social_studies/verifier.py:123-125` and remove the `image_path=chart_image_path` kwarg (pass `None`). Rerun Step 2 and confirm the test fails on `assert client.image_path == str(png_path)`. Revert; do not commit.

- [ ] **Step 4: Commit**

```bash
git add tests/test_social_studies_verifier.py
git commit -m "test(social_studies): assert verifier threads chart_image_path + 附圖 (#106)"
```

---

### Task 4: Math verifier — add minimal `FakeClient` test file

**Files:**
- Create: `tests/test_verifier.py`

**Interfaces:**
- Consumes: `src.verifier.verify_question`, `src.schemas.ExamQuestion`. No existing math verifier test file — the spec allows adding a minimal one.
- Produces: `tests/test_verifier.py` with one test asserting image-threading + `## 附圖` for math.

- [ ] **Step 1: Write the failing test**

Create `tests/test_verifier.py`:

```python
"""Tests for the math verifier's multimodal payload wiring."""

from __future__ import annotations

import json

from src.schemas import ExamQuestion, LearningContentItem
from src.verifier import verify_question


class FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.system_prompt = ""
        self.user_prompt = ""
        self.image_path: str | None = None

    def generate_with_image(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: str | None,
        purpose: str = "generate",
    ) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.image_path = image_path
        return json.dumps(self.payload, ensure_ascii=False)


def _math_question() -> ExamQuestion:
    return ExamQuestion(
        id="math-test",
        情境=["個人"],
        題型種類="單一題",
        題型="選擇題",
        數學思考=["形成"],
        學習內容=[LearningContentItem(編碼="N-7-1", 說明="整數的加減乘除")],
        題目=["下列哪一個數字最大？(A) 1 (B) 2 (C) 3 (D) 4"],
        正確解題分析=["最大的是 4，故選 D。"],
    )


def test_math_verifier_threads_chart_image_path_and_prompts_附圖(tmp_path) -> None:
    """When chart_image_path is given, the math verifier must pass it to the
    client and inject the 「## 附圖」 section into the user prompt."""
    png_path = tmp_path / "chart.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    client = FakeClient(
        {
            "my_answer": "D",
            "provided_answer": "D",
            "answer_match": True,
            "passed": True,
            "details": "答案一致，圖表無誤。",
            "chart_verification": {
                "chart_data_match": True,
                "chart_labels_correct": True,
                "chart_details": "圖表資料與題目一致。",
            },
        }
    )

    result = verify_question(client, _math_question(), chart_image_path=str(png_path))

    assert client.image_path == str(png_path)
    assert "## 附圖" in client.user_prompt
    assert result.passed is True
    assert result.chart_verification is not None
    assert result.chart_verification.chart_data_match is True


def test_math_verifier_omits_附圖_when_no_image(tmp_path) -> None:
    """Without a chart_image_path, the client must be called with image_path=None
    and 「## 附圖」 must not appear in the user prompt."""
    client = FakeClient(
        {
            "my_answer": "D",
            "provided_answer": "D",
            "answer_match": True,
            "passed": True,
            "details": "無圖題，答案正確。",
        }
    )

    result = verify_question(client, _math_question())

    assert client.image_path is None
    assert "## 附圖" not in client.user_prompt
    assert result.passed is True
```

- [ ] **Step 2: Run tests to verify they pass against current source**

Run: `uv run pytest -q tests/test_verifier.py`
Expected: PASS — 2 tests green. Locks the math verifier's chart_image_path threading.

- [ ] **Step 3: Sanity-check the failure mode (manual)**

Temporarily edit `src/verifier.py:100-102` and remove the `image_path=chart_image_path` kwarg (pass `None`). Rerun Step 2 and confirm `test_math_verifier_threads_chart_image_path_and_prompts_附圖` fails on the `client.image_path` assertion. Revert; do not commit.

- [ ] **Step 4: Commit**

```bash
git add tests/test_verifier.py
git commit -m "test(math): add verifier chart_image_path threading regression (#106)"
```

---

### Task 5: Natural-sciences verifier — add minimal `FakeClient` test file

**Files:**
- Create: `tests/test_natural_sciences_verifier.py`

**Interfaces:**
- Consumes: `src.natural_sciences.verifier.verify_question`, `src.natural_sciences.schemas.ExamQuestion` / `SubQuestion` / `LearningContentRef`. No existing NS verifier test file — the spec allows adding a minimal one.
- Produces: `tests/test_natural_sciences_verifier.py` with one test asserting image-threading + `## 附圖` for natural sciences.

- [ ] **Step 1: Write the failing test**

Create `tests/test_natural_sciences_verifier.py`:

```python
"""Tests for the natural-sciences verifier's multimodal payload wiring."""

from __future__ import annotations

import json

from src.natural_sciences.schemas import (
    ExamQuestion,
    LearningContentRef,
    SubQuestion,
)
from src.natural_sciences.verifier import verify_question


class FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.system_prompt = ""
        self.user_prompt = ""
        self.image_path: str | None = None

    def generate_with_image(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: str | None,
        purpose: str = "generate",
    ) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.image_path = image_path
        return json.dumps(self.payload, ensure_ascii=False)


def _ns_question() -> ExamQuestion:
    return ExamQuestion(
        id="ns-test",
        核心問題="某地區水源氯離子濃度變化的原因為何？",
        文本="某地區在颱風前後量測河川水的氯離子濃度……",
        情境=["Local and national"],
        情境子類別="Natural resources",
        題型種類="題組題",
        題型="Simple multiple-choice",
        科學能力=["能力一：以科學的角度解釋現象"],
        subquestions=[
            SubQuestion(
                序號=1,
                年級=8,
                科目=["自然科學"],
                科學能力=["能力一：以科學的角度解釋現象"],
                學習內容=[LearningContentRef(編碼="INc-Ⅳ-1", 說明="範例學習內容")],
                學習表現=[LearningContentRef(編碼="tr-Ⅳ-1", 說明="範例學習表現")],
                題型="Simple multiple-choice",
                題目="下列何者最可能造成氯離子濃度上升？(A) 海水入侵 (B) 大雨稀釋",
                答案="A",
                答案解析="颱風常帶來海水入侵造成氯離子上升。",
            )
        ],
    )


def test_ns_verifier_threads_chart_image_path_and_prompts_附圖(tmp_path) -> None:
    """When chart_image_path is given, the NS verifier must pass it to the
    client and inject the 「## 附圖」 section into the user prompt."""
    png_path = tmp_path / "chart.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    client = FakeClient(
        {
            "my_answer": "A",
            "provided_answer": "A",
            "answer_match": True,
            "passed": True,
            "details": "圖表資料支持答案。",
            "chart_verification": {
                "chart_data_match": True,
                "chart_labels_correct": True,
                "chart_details": "圖表標籤與題目一致。",
            },
        }
    )

    result = verify_question(client, _ns_question(), chart_image_path=str(png_path))

    assert client.image_path == str(png_path)
    assert "## 附圖" in client.user_prompt
    assert result.passed is True
    assert result.chart_verification is not None
    assert result.chart_verification.chart_data_match is True


def test_ns_verifier_omits_附圖_when_no_image() -> None:
    """Without a chart_image_path, the client must be called with image_path=None
    and 「## 附圖」 must not appear in the user prompt."""
    client = FakeClient(
        {
            "my_answer": "A",
            "provided_answer": "A",
            "answer_match": True,
            "passed": True,
            "details": "無圖題，答案正確。",
        }
    )

    result = verify_question(client, _ns_question())

    assert client.image_path is None
    assert "## 附圖" not in client.user_prompt
    assert result.passed is True
```

- [ ] **Step 2: Run tests to verify they pass against current source**

Run: `uv run pytest -q tests/test_natural_sciences_verifier.py`
Expected: PASS — 2 tests green. Locks the NS verifier's chart_image_path threading.

- [ ] **Step 3: Sanity-check the failure mode (manual)**

Temporarily edit `src/natural_sciences/verifier.py:131-136` and drop the `image_path=chart_image_path` kwarg (pass `None`). Rerun Step 2 and confirm `test_ns_verifier_threads_chart_image_path_and_prompts_附圖` fails on the `client.image_path` assertion. Revert; do not commit.

- [ ] **Step 4: Commit**

```bash
git add tests/test_natural_sciences_verifier.py
git commit -m "test(natural_sciences): add verifier chart_image_path threading regression (#106)"
```

---

### Task 6: Full-suite verification

**Files:** none (verification only).

**Interfaces:**
- Consumes: every test file created / edited in Tasks 1–5.
- Produces: proof that the additions do not break any pre-existing test.

- [ ] **Step 1: Run the full pytest suite**

Run: `uv run pytest -q`
Expected: PASS — every test in `tests/` (including the pre-existing `tests/test_social_studies_verifier.py`, `tests/test_social_studies_corrector.py`, `tests/server/*`, `tests/test_renderer_image_generation.py`, and the four new/extended files) is green.

- [ ] **Step 2: Confirm the two new files and one extended file are recognized**

Run: `uv run pytest -q --collect-only tests/test_llm_client_multimodal.py tests/test_verifier.py tests/test_natural_sciences_verifier.py tests/test_social_studies_verifier.py | tail -20`
Expected: The four multimodal tests from Task 1+2 (`test_to_anthropic_content_preserves_text_then_image_block`, `test_to_anthropic_content_silently_drops_unknown_part_types`, `test_generate_with_image_sends_base64_image_block_to_sdk`), the new social-studies test (`test_verify_question_threads_chart_image_path_and_prompts_附圖`), the two math tests, and the two NS tests all appear in the collection output.

- [ ] **Step 3: No commit for this task** (verification only — every artefact was already committed in its owning task).
