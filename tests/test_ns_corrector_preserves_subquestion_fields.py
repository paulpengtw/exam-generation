"""NS corrector must preserve 出題指示 and reporting_scale across correction passes.

Issue #278: _ns_rebuild_subquestion() silently dropped two declared SubQuestion fields:
  - 出題指示 (str | None)
  - reporting_scale (str | None)

Tests drive the public entrypoint correct_question() via a fake model client and observe
the fields on the returned 題組's 小題.  _ns_rebuild_subquestion is never called directly.
"""

from __future__ import annotations

from src.natural_sciences.corrector import correct_question
from src.natural_sciences.schemas import (
    ExamQuestion,
    LearningContentRef,
    QuestionSetType,
    QuestionSubContext,
    QuestionType,
    RubricEntry,
    SubQuestion,
    VerificationResult,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _verification() -> VerificationResult:
    return VerificationResult(passed=False, answer_match=False, details="needs fix")


def _make_question(subquestions: list[SubQuestion]) -> ExamQuestion:
    return ExamQuestion(
        id="ns-test",
        情境=[],
        情境子類別=next(iter(QuestionSubContext)),
        題型種類=next(iter(QuestionSetType)),
        題型=next(iter(QuestionType)),
        subquestions=subquestions,
    )


class _FakeCorrectClient:
    """Fake LLM client that returns a pre-baked corrected subquestion list."""

    def __init__(self, raw_subquestions: list[dict]) -> None:
        self._raw = raw_subquestions

    def generate_json(self, *_args: object, **_kwargs: object) -> dict:
        return {"subquestions": self._raw}


def _q_type_value() -> str:
    return next(iter(QuestionType)).value


# ---------------------------------------------------------------------------
# Test 1: 出題指示 is preserved through a body-only correction
# ---------------------------------------------------------------------------

def test_ns_corrector_preserves_出題指示_through_body_correction() -> None:
    """小題 carrying 出題指示 keeps it when the model returns only corrected body fields."""
    original_sq = SubQuestion(
        id="ns-test-01",
        序號=1,
        年級=8,
        科目=["自然科學"],
        出題概念="力學概念",
        出題指示="請以實驗數據判讀出題",
        題型=next(iter(QuestionType)),
        題目="原始題目",
        答案="A",
    )
    question = _make_question([original_sq])

    # Fake client returns a corrected body but does NOT include 出題指示
    fake_client = _FakeCorrectClient([
        {
            "序號": 1,
            "年級": 8,
            "科目": ["自然科學"],
            "出題概念": "力學概念",
            "題型": _q_type_value(),
            "題目": "修正後題目",
            "答案": "B",
            "答案解析": "修正後解析",
            "評分規準": [],
        }
    ])

    corrected = correct_question(fake_client, question, _verification())

    assert corrected.subquestions[0].出題指示 == "請以實驗數據判讀出題"


# ---------------------------------------------------------------------------
# Test 2: reporting_scale is preserved through a body-only correction
# ---------------------------------------------------------------------------

def test_ns_corrector_preserves_reporting_scale_through_body_correction() -> None:
    """小題 carrying reporting_scale keeps it when the model returns only corrected body fields."""
    original_sq = SubQuestion(
        id="ns-test-01",
        序號=1,
        年級=8,
        科目=["自然科學"],
        出題概念="力學概念",
        reporting_scale="RSC-3",
        題型=next(iter(QuestionType)),
        題目="原始題目",
        答案="A",
    )
    question = _make_question([original_sq])

    # Fake client returns a corrected body but does NOT include reporting_scale
    fake_client = _FakeCorrectClient([
        {
            "序號": 1,
            "年級": 8,
            "科目": ["自然科學"],
            "出題概念": "力學概念",
            "題型": _q_type_value(),
            "題目": "修正後題目",
            "答案": "B",
            "答案解析": "修正後解析",
            "評分規準": [],
        }
    ])

    corrected = correct_question(fake_client, question, _verification())

    assert corrected.subquestions[0].reporting_scale == "RSC-3"


# ---------------------------------------------------------------------------
# Test 3: Frozen semantics — original wins when model returns different values
# ---------------------------------------------------------------------------

def test_ns_corrector_freezes_出題指示_and_reporting_scale() -> None:
    """Original 出題指示 and reporting_scale win even when the model returns different values."""
    original_sq = SubQuestion(
        id="ns-test-01",
        序號=1,
        年級=8,
        科目=["自然科學"],
        出題概念="光學概念",
        出題指示="請以實驗數據判讀出題",
        reporting_scale="RSC-2",
        題型=next(iter(QuestionType)),
        題目="原始題目",
        答案="A",
    )
    question = _make_question([original_sq])

    # Fake client attempts to overwrite BOTH frozen fields with different values
    fake_client = _FakeCorrectClient([
        {
            "序號": 1,
            "年級": 8,
            "科目": ["自然科學"],
            "出題概念": "光學概念",
            "出題指示": "錯誤覆寫的指示",       # different — should be ignored
            "reporting_scale": "RSC-WRONG",     # different — should be ignored
            "題型": _q_type_value(),
            "題目": "修正後題目",
            "答案": "B",
            "答案解析": "修正後解析",
            "評分規準": [],
        }
    ])

    corrected = correct_question(fake_client, question, _verification())

    assert corrected.subquestions[0].出題指示 == "請以實驗數據判讀出題"
    assert corrected.subquestions[0].reporting_scale == "RSC-2"


# ---------------------------------------------------------------------------
# Test 4: Model-added 小題 (no original counterpart) takes model's values
# ---------------------------------------------------------------------------

def test_ns_corrector_model_added_subquestion_takes_model_出題指示_and_reporting_scale() -> None:
    """A 小題 the model adds with no original counterpart takes both values from model output."""
    original_sq = SubQuestion(
        id="ns-test-01",
        序號=1,
        年級=8,
        科目=["自然科學"],
        出題概念="力學概念",
        題型=next(iter(QuestionType)),
        題目="原始題目",
        答案="A",
    )
    question = _make_question([original_sq])

    q_type_val = _q_type_value()
    # Fake client returns 2 subquestions; the second is model-added (no original at idx=1)
    fake_client = _FakeCorrectClient([
        {
            "序號": 1,
            "年級": 8,
            "科目": ["自然科學"],
            "出題概念": "力學概念",
            "題型": q_type_val,
            "題目": "修正後題目",
            "答案": "B",
            "答案解析": "修正後解析",
            "評分規準": [],
        },
        {
            "id": "ns-test-02",
            "序號": 2,
            "年級": 8,
            "科目": ["自然科學"],
            "出題概念": "模型新增概念",
            "出題指示": "請比較兩種物質的物理性質",
            "reporting_scale": "RSC-1",
            "題型": q_type_val,
            "題目": "模型新增題目",
            "答案": "C",
            "答案解析": "模型新增解析",
            "評分規準": [],
        },
    ])

    corrected = correct_question(fake_client, question, _verification())

    assert len(corrected.subquestions) == 2
    assert corrected.subquestions[1].出題指示 == "請比較兩種物質的物理性質"
    assert corrected.subquestions[1].reporting_scale == "RSC-1"


# ---------------------------------------------------------------------------
# Test 5: Structural guard — rebuild must cover every declared model field
# ---------------------------------------------------------------------------

def test_ns_rebuild_covers_all_subquestion_model_fields() -> None:
    """Every field in NS SubQuestion.model_fields must survive the correction rebuild.

    This guard is intentionally a single completeness assertion.  Adding a new
    field to SubQuestion without updating _ns_rebuild_subquestion causes this
    test to fail red.

    Mechanism: set unique sentinel values on every field of the original 小題,
    mirror them in sq_raw for the mutable fields, run correct_question(), and
    verify the rebuilt 小題 preserves every sentinel value.
    """
    q_type = next(iter(QuestionType))

    sentinels: dict = {
        "id": "SENTINEL-ID",
        "序號": 42,
        "年級": 9,
        "科目": ["自然科學"],
        "科學能力": ["能力一"],
        "核心素養": ["自-J-A1"],
        "學習內容": [LearningContentRef(編碼="INc-IV-1", 說明="哨兵")],
        "學習表現": [LearningContentRef(編碼="tr-IV-1", 說明="哨兵")],
        "出題概念": "SENTINEL-出題概念",
        "出題指示": "SENTINEL-出題指示",
        "reporting_scale": "SENTINEL-reporting_scale",
        "題型": q_type,
        "題目": "SENTINEL-題目",
        "答案": "SENTINEL-答案",
        "答案解析": "SENTINEL-答案解析",
        "評分規準": [RubricEntry(code="2", 規準說明="SENTINEL", 學生作答實例=[])],
        "誘答分析": {"A": "SENTINEL"},
    }

    original_sq = SubQuestion(**sentinels)

    # sq_raw carries sentinel values for all fields so mutable fields also round-trip
    sq_raw: dict = {
        "id": sentinels["id"],
        "序號": sentinels["序號"],
        "年級": sentinels["年級"],
        "科目": sentinels["科目"],
        "科學能力": sentinels["科學能力"],
        "核心素養": sentinels["核心素養"],
        "學習內容": [{"編碼": r.編碼, "說明": r.說明} for r in sentinels["學習內容"]],
        "學習表現": [{"編碼": r.編碼, "說明": r.說明} for r in sentinels["學習表現"]],
        "出題概念": sentinels["出題概念"],
        "出題指示": sentinels["出題指示"],
        "reporting_scale": sentinels["reporting_scale"],
        "題型": q_type.value,
        "題目": sentinels["題目"],
        "答案": sentinels["答案"],
        "答案解析": sentinels["答案解析"],
        "評分規準": [{"code": "2", "規準說明": "SENTINEL", "學生作答實例": []}],
        "誘答分析": sentinels["誘答分析"],
    }

    question = _make_question([original_sq])
    fake_client = _FakeCorrectClient([sq_raw])

    corrected = correct_question(fake_client, question, _verification())
    rebuilt = corrected.subquestions[0]

    mismatched = [
        fname
        for fname in SubQuestion.model_fields
        if getattr(rebuilt, fname) != sentinels[fname]
    ]
    assert not mismatched, (
        f"_ns_rebuild_subquestion dropped or lost these SubQuestion fields: {mismatched}"
    )


def test_ss_rebuild_covers_all_subquestion_model_fields() -> None:
    """Every field in SS SubQuestion.model_fields must survive the correction rebuild.

    Must pass today without any changes to SS.  Adding a new field to SS
    SubQuestion without updating _ss_rebuild_subquestion causes this test to
    fail red.
    """
    from src.social_studies.corrector import correct_question as ss_correct_question
    from src.social_studies.schemas import (
        ExamQuestion as SSExamQuestion,
    )
    from src.social_studies.schemas import (
        LearningContentRef as SSLearningContentRef,
    )
    from src.social_studies.schemas import (
        QuestionSetType as SSQuestionSetType,
    )
    from src.social_studies.schemas import (
        QuestionType as SSQuestionType,
    )
    from src.social_studies.schemas import (
        RubricEntry as SSRubricEntry,
    )
    from src.social_studies.schemas import (
        SubQuestion as SSSubQuestion,
    )
    from src.social_studies.schemas import (
        VerificationResult as SSVerificationResult,
    )

    ss_q_type = next(iter(SSQuestionType))

    sentinels: dict = {
        "id": "SENTINEL-SS-ID",
        "序號": 42,
        "年級": 9,
        "科目": ["地理"],
        "核心素養": ["社-J-A2"],
        "學習內容": [SSLearningContentRef(編碼="地Bc-IV-1", 說明="哨兵")],
        "學習表現": [SSLearningContentRef(編碼="社1b-IV-1", 說明="哨兵")],
        "出題概念": "SENTINEL-SS-出題概念",
        "出題指示": "SENTINEL-SS-出題指示",
        "認知歷程": "Knowing–Defining and Describing",
        "題型": ss_q_type,
        "題目": "SENTINEL-SS-題目",
        "答案": "SENTINEL-SS-答案",
        "答案解析": "SENTINEL-SS-答案解析",
        "評分規準": [SSRubricEntry(code="2", 規準說明="SENTINEL-SS", 學生作答實例=[])],
        "誘答分析": {"A": "SENTINEL-SS"},
        "題目內容類型": "SENTINEL-SS-content-type",
        "image_generation_mode": "html",
        "圖片": "sentinel.png",
        "chart_spec": None,
        "interaction": None,
    }

    original_sq = SSSubQuestion(**sentinels)

    # sq_raw for SS mutable fields; frozen fields (出題指示, 認知歷程, 圖片,
    # chart_spec, image_generation_mode, 題目內容類型) must come from original, not sq_raw.
    sq_raw: dict = {
        "id": sentinels["id"],
        "序號": sentinels["序號"],
        "年級": sentinels["年級"],
        "科目": sentinels["科目"],
        "核心素養": sentinels["核心素養"],
        "學習內容": [{"編碼": r.編碼, "說明": r.說明} for r in sentinels["學習內容"]],
        "學習表現": [{"編碼": r.編碼, "說明": r.說明} for r in sentinels["學習表現"]],
        "出題概念": sentinels["出題概念"],
        # 出題指示 intentionally omitted from sq_raw — frozen from original
        "題型": ss_q_type.value,
        "題目": sentinels["題目"],
        "答案": sentinels["答案"],
        "答案解析": sentinels["答案解析"],
        "評分規準": [{"code": "2", "規準說明": "SENTINEL-SS", "學生作答實例": []}],
        "誘答分析": sentinels["誘答分析"],
    }

    ss_question = SSExamQuestion(
        id="ss-guard",
        情境=["公共"],
        題型種類=next(iter(SSQuestionSetType)),
        題型=ss_q_type,
        subquestions=[original_sq],
    )
    ss_verification = SSVerificationResult(
        passed=False, answer_match=False, details="fix needed"
    )

    class _SSFakeClient:
        def generate_json(self, *_: object, **__: object) -> dict:
            return {"subquestions": [sq_raw]}

    corrected_ss = ss_correct_question(_SSFakeClient(), ss_question, ss_verification)
    rebuilt_ss = corrected_ss.subquestions[0]

    mismatched = [
        fname
        for fname in SSSubQuestion.model_fields
        if getattr(rebuilt_ss, fname) != sentinels[fname]
    ]
    assert not mismatched, (
        f"_ss_rebuild_subquestion dropped or lost these SubQuestion fields: {mismatched}"
    )
