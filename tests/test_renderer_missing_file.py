"""Tests for issue #151: missing-file / empty-spec defensive handling.

Vertical slices (red → green order):
  Slice 1 — render_chart: empty pie spec returns None (no file written)
  Slice 2 — render_image: propagates None from render_chart
  Slice 3 — Verifiers: non-existent chart_image_path falls back to text-only,
             never raises FileNotFoundError; applied to all three subjects
  Slice 4 — Regression: empty-segments pie runs through render → verify with
             no uncaught exception
  Slice 5 — 圖片 guard: render_image returning None leaves 圖片 un-set
"""

from __future__ import annotations

import json
from pathlib import Path

from src.renderer import render_chart, render_image

# ---------------------------------------------------------------------------
# Shared FakeClient used by all verifier slices (matches established style)
# ---------------------------------------------------------------------------


class _FakeClient:
    """Records the last call to generate_with_image; returns a fixed payload."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.system_prompt: str = ""
        self.user_prompt: str = ""
        self.image_path: str | None = None

    def generate_with_image(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: str | None = None,
        purpose: str = "generate",
    ) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.image_path = image_path
        return json.dumps(self.payload, ensure_ascii=False)


_PASSING_PAYLOAD: dict = {
    "my_answer": "A",
    "provided_answer": "A",
    "answer_match": True,
    "passed": True,
    "details": "通過。",
}

_EMPTY_PIE_SPEC: dict = {
    "render_mode": "chart",
    "chart_type": "pie_chart",
    "title": "空圓形圖",
    "data": {"segments": []},
}

# ---------------------------------------------------------------------------
# Slice 1: render_chart with empty-segments pie → None
# ---------------------------------------------------------------------------


def test_render_chart_empty_pie_segments_returns_none(tmp_path: Path) -> None:
    """An empty-segments pie_chart spec must return None, not a path to a file
    that was never written."""
    result = render_chart(_EMPTY_PIE_SPEC, tmp_path / "out.png")
    assert result is None


def test_render_chart_empty_pie_does_not_create_file(tmp_path: Path) -> None:
    """No file must be written when the pie spec has no segments."""
    out = tmp_path / "out.png"
    render_chart(_EMPTY_PIE_SPEC, out)
    assert not out.exists()


def test_render_chart_non_empty_pie_still_works(tmp_path: Path) -> None:
    """Sanity: a well-formed pie spec must still write a file and return its path."""
    spec = {
        "chart_type": "pie_chart",
        "title": "正常圓形圖",
        "data": {
            "segments": [
                {"angle": 180, "label": "甲"},
                {"angle": 180, "label": "乙"},
            ]
        },
    }
    out = tmp_path / "pie.png"
    result = render_chart(spec, out)
    assert result == str(out)
    assert out.exists()


# ---------------------------------------------------------------------------
# Slice 2: render_image propagates None from empty-pie render_chart
# ---------------------------------------------------------------------------


def test_render_image_propagates_none_from_empty_pie(tmp_path: Path) -> None:
    """render_image must return None when the sub-renderer writes no file."""
    result = render_image(_EMPTY_PIE_SPEC, tmp_path / "out.png")
    assert result is None


def test_render_image_non_empty_pie_returns_path(tmp_path: Path) -> None:
    """Sanity: render_image must return the path when a file is actually written."""
    spec = {
        "render_mode": "chart",
        "chart_type": "pie_chart",
        "title": "正常圓形圖",
        "data": {
            "segments": [
                {"angle": 180, "label": "甲"},
                {"angle": 180, "label": "乙"},
            ]
        },
    }
    out = tmp_path / "pie.png"
    result = render_image(spec, out)
    assert result == str(out)
    assert out.exists()


# ---------------------------------------------------------------------------
# Slice 3a: Math verifier falls back to text-only on non-existent path
# ---------------------------------------------------------------------------


def _math_question():
    from src.schemas import ExamQuestion, LearningContentItem

    return ExamQuestion(
        id="math-missing-img",
        情境=["個人"],
        題型種類="單一題",
        題型="選擇題",
        數學思考=["形成"],
        學習內容=[LearningContentItem(編碼="N-7-1", 說明="整數")],
        題目=["下列哪個最大？(A)1 (B)2 (C)3 (D)4"],
        正確解題分析=["答案是D。"],
    )


def test_math_verifier_nonexistent_chart_path_falls_back_to_text_only(tmp_path: Path) -> None:
    """Math verify_question must not raise when chart_image_path points to a
    non-existent file; it must fall back to the text-only code path."""
    from src.verifier import verify_question

    missing = str(tmp_path / "never_written.png")
    client = _FakeClient(_PASSING_PAYLOAD)

    result = verify_question(client, _math_question(), chart_image_path=missing)

    # Fell back to text-only: client must receive image_path=None
    assert client.image_path is None
    # 「## 附圖」 must NOT appear when there is no readable image
    assert "## 附圖" not in client.user_prompt
    # Verification result must still be returned (no exception)
    assert result.passed is True


def test_math_verifier_existing_chart_path_still_threads_image(tmp_path: Path) -> None:
    """Sanity: math verify_question must still pass an existing file through to
    the client (regression guard — existing happy-path must not break)."""
    from src.verifier import verify_question

    png = tmp_path / "chart.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    client = _FakeClient(_PASSING_PAYLOAD)

    verify_question(client, _math_question(), chart_image_path=str(png))

    assert client.image_path == str(png)
    assert "## 附圖" in client.user_prompt


# ---------------------------------------------------------------------------
# Slice 3b: Social-studies verifier falls back to text-only on missing path
# ---------------------------------------------------------------------------


def _ss_question():
    from src.social_studies.schemas import ExamQuestion

    return ExamQuestion(
        id="ss-missing-img",
        情境=["公共"],
        題型種類="題組題",
        題型="選擇題",
        閱讀歷程=["擷取訊息"],
        文本形式="連續文本—說明文",
        題目=["閱讀後作答：作者立場為何？"],
        正確解題分析=["支持擴大公共運輸。"],
    )


def test_ss_verifier_nonexistent_chart_path_falls_back_to_plain_text(tmp_path: Path) -> None:
    """Social-studies verify_question must not raise when chart_image_path points
    to a non-existent file; it must fall back to text-only."""
    from src.social_studies.verifier import verify_question

    missing = str(tmp_path / "never_written.png")
    client = _FakeClient(_PASSING_PAYLOAD)

    result = verify_question(client, _ss_question(), chart_image_path=missing)

    assert client.image_path is None
    assert "## 附圖" not in client.user_prompt
    assert result.passed is True


def test_ss_verifier_existing_chart_path_still_threads_image(tmp_path: Path) -> None:
    """Sanity: social-studies verify_question must still pass an existing PNG through."""
    from src.social_studies.verifier import verify_question

    png = tmp_path / "chart.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    client = _FakeClient(_PASSING_PAYLOAD)

    verify_question(client, _ss_question(), chart_image_path=str(png))

    assert client.image_path == str(png)
    assert "## 附圖" in client.user_prompt


# ---------------------------------------------------------------------------
# Slice 3c: Natural-sciences verifier falls back to text-only on missing path
# ---------------------------------------------------------------------------


def _ns_question():
    from src.natural_sciences.schemas import ExamQuestion, LearningContentRef, SubQuestion

    return ExamQuestion(
        id="ns-missing-img",
        核心問題="水源氯離子變化原因。",
        文本="某地區颱風前後量測河川水氯離子濃度……",
        情境=["Local and national"],
        情境子類別="Environmental impact",
        題型種類="題組題",
        題型="Simple multiple-choice",
        科學能力=["能力一：以科學的角度解釋現象"],
        subquestions=[
            SubQuestion(
                序號=1,
                年級=8,
                科目=["自然科學"],
                科學能力=["能力一：以科學的角度解釋現象"],
                學習內容=[LearningContentRef(編碼="Ab-Ⅳ-1", 說明="範例")],
                學習表現=[LearningContentRef(編碼="tr-Ⅳ-1", 說明="範例")],
                題型="Simple multiple-choice",
                題目="下列何者最可能造成氯離子上升？(A) 海水入侵 (B) 大雨稀釋",
                答案="A",
                答案解析="颱風常帶來海水入侵。",
            )
        ],
    )


def test_ns_verifier_nonexistent_chart_path_falls_back_to_text_only(tmp_path: Path) -> None:
    """Natural-sciences verify_question must not raise when chart_image_path points
    to a non-existent file; it must fall back to text-only."""
    from src.natural_sciences.verifier import verify_question

    missing = str(tmp_path / "never_written.png")
    client = _FakeClient(_PASSING_PAYLOAD)

    result = verify_question(client, _ns_question(), chart_image_path=missing)

    assert client.image_path is None
    assert "## 附圖" not in client.user_prompt
    assert result.passed is True


def test_ns_verifier_existing_chart_path_still_threads_image(tmp_path: Path) -> None:
    """Sanity: natural-sciences verify_question must still pass an existing PNG through."""
    from src.natural_sciences.verifier import verify_question

    png = tmp_path / "chart.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    client = _FakeClient(_PASSING_PAYLOAD)

    verify_question(client, _ns_question(), chart_image_path=str(png))

    assert client.image_path == str(png)
    assert "## 附圖" in client.user_prompt


# ---------------------------------------------------------------------------
# Slice 4: Regression — empty pie → render → verify, no uncaught exception
# ---------------------------------------------------------------------------


def test_regression_empty_pie_render_then_verify_no_exception(tmp_path: Path) -> None:
    """Full path for issue #151: an empty-segments pie spec must not cause an
    uncaught exception when the result is passed through the verify pipeline."""
    from src.schemas import ExamQuestion, LearningContentItem
    from src.verifier import verify_question

    # Step 1: render returns None (no file written)
    rendered = render_image(_EMPTY_PIE_SPEC, tmp_path / "question.png")
    assert rendered is None

    # Step 2: chart_image_path stays None since nothing was rendered
    chart_image_path = rendered  # None

    # Step 3: verifier must handle chart_image_path=None without raising
    question = ExamQuestion(
        id="regression-empty-pie",
        情境=["個人"],
        題型種類="單一題",
        題型="選擇題",
        數學思考=["形成"],
        學習內容=[LearningContentItem(編碼="N-7-1", 說明="整數")],
        題目=["題目文字"],
        正確解題分析=["解析"],
    )
    client = _FakeClient(_PASSING_PAYLOAD)
    result = verify_question(client, question, chart_image_path=chart_image_path)

    assert result is not None
    assert client.image_path is None  # text-only path taken


# ---------------------------------------------------------------------------
# Slice 5: 圖片 guard — render_image returning None must leave 圖片 un-set
# ---------------------------------------------------------------------------


def test_圖片_not_set_when_render_returns_none(tmp_path: Path) -> None:
    """When render_image returns None (no file written), 圖片 must not be
    set on the question. This covers the 'if rendered:' guard in all CLI
    call sites (src/cli.py, src/social_studies/cli.py, src/natural_sciences/cli.py)
    via the renderer contract: None return → guard blocks the assignment."""
    from src.schemas import ExamQuestion, LearningContentItem

    question = ExamQuestion(
        id="no-file",
        情境=["個人"],
        題型種類="單一題",
        題型="選擇題",
        數學思考=["形成"],
        學習內容=[LearningContentItem(編碼="N-7-1", 說明="整數")],
        題目=["題目"],
        正確解題分析=["解析"],
    )
    assert question.圖片 is None  # initial state

    rendered = render_image(_EMPTY_PIE_SPEC, tmp_path / "q.png")
    if rendered:
        question.圖片 = "q.png"  # pragma: no cover — must not execute

    assert question.圖片 is None
