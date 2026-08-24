"""Deterministic and prompt-level ICCS verifier checks."""

from __future__ import annotations

import json

import pytest

from src.social_studies.schemas import (
    DragDropSpec,
    DragItem,
    DropTarget,
    ExamQuestion,
    LearningContentRef,
    SliderSpec,
    SubQuestion,
    VerificationResult,
)
from src.social_studies.verifier import verify_question


class _FakeVerifierClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.system_prompt = ""
        self.user_prompt = ""

    def generate_with_image(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: str | None,
        purpose: str = "generate",
    ) -> str:
        assert image_path is None
        assert purpose == "verify"
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return json.dumps(self.payload, ensure_ascii=False)


def _passed_payload() -> dict:
    return {
        "my_answer": "A",
        "provided_answer": "A",
        "answer_match": True,
        "passed": True,
        "details": "LLM 判定可通過。",
    }


def _question(
    *,
    content_domain: str | None,
    subjects_and_codes: list[tuple[str, list[str]]],
    cognitive_processes: list[str | None] | None = None,
    top_level_processes: list[str] | None = None,
) -> ExamQuestion:
    process_values = cognitive_processes or [None] * len(subjects_and_codes)
    return ExamQuestion(
        id="iccs-verifier-check",
        核心問題="題組核心問題",
        文本="題組素材",
        內容領域=content_domain,
        認知歷程=top_level_processes or [],
        subquestions=[
            SubQuestion(
                序號=index,
                科目=[subject],
                學習內容=[LearningContentRef(編碼=code) for code in codes],
                認知歷程=process_values[index - 1],
                題型="選擇題",
                題目=f"第{index}題題目",
                答案="A",
            )
            for index, (subject, codes) in enumerate(subjects_and_codes, start=1)
        ],
        情境=["公共"],
        題型種類="題組題",
        題型="選擇題",
        閱讀歷程=["擷取訊息"],
        文本形式="連續文本—說明文",
    )


def test_civic_code_outside_declared_domain_forces_failure() -> None:
    client = _FakeVerifierClient(_passed_payload())
    question = _question(
        content_domain="Civic Participation",
        subjects_and_codes=[("公民與社會", ["公Ba-Ⅳ-1"])],
    )

    result = verify_question(client, question)

    assert result.passed is False
    assert "[內容領域檢核]" in result.details
    assert "公Ba-Ⅳ-1" in result.details
    assert "第1題" in result.details
    assert "Civic Participation" in result.details


def test_civic_code_inside_declared_domain_does_not_force_failure() -> None:
    client = _FakeVerifierClient(_passed_payload())
    question = _question(
        content_domain="Civic Participation",
        subjects_and_codes=[("公民與社會", ["公Ca-Ⅳ-2"])],
    )

    result = verify_question(client, question)

    assert result.passed is True
    assert "[內容領域檢核]" not in result.details


def test_domain_code_check_ignores_unmapped_and_non_civic_codes() -> None:
    client = _FakeVerifierClient(_passed_payload())
    question = _question(
        content_domain="Civic Participation",
        subjects_and_codes=[
            ("跨科", ["公ZZ-Ⅳ-9", "歷Aa-Ⅳ-1", "地Aa-Ⅳ-1", "社1b-Ⅳ-1"]),
        ],
    )

    result = verify_question(client, question)

    assert result.passed is True
    assert "[內容領域檢核]" not in result.details


def test_legacy_record_without_content_domain_skips_domain_code_check() -> None:
    client = _FakeVerifierClient(_passed_payload())
    question = _question(
        content_domain=None,
        subjects_and_codes=[("公民與社會", ["公Ba-Ⅳ-1"])],
    )

    result = verify_question(client, question)

    assert result.passed is True
    assert "[內容領域檢核]" not in result.details


def test_iccs_prompt_anchors_each_assigned_process_and_civic_domain() -> None:
    client = _FakeVerifierClient(_passed_payload())
    question = _question(
        content_domain="Civic Participation",
        subjects_and_codes=[("公民與社會", ["公Ca-Ⅳ-2"])] * 4,
        cognitive_processes=[
            "Knowing–Defining and Describing",
            "Knowing–Illustrating with examples",
            "Reasoning and Applying–Interpret information",
            "Reasoning and Applying–Relate or Integrate",
        ],
    )

    verify_question(client, question)

    prompt = client.system_prompt
    assert "ICCS 認知歷程檢核" in prompt
    assert "第1題" in prompt
    assert "Knowing–Defining and Describing" in prompt
    assert "可辨識特徵" in prompt
    assert "Knowing–Illustrating with examples" in prompt
    assert "四個例子中選出正確例" in prompt
    assert "Reasoning and Applying–Interpret information" in prompt
    assert "資料＋概念" in prompt
    assert "Reasoning and Applying–Relate or Integrate" in prompt
    assert "跨科、跨冊別、跨單元、跨領域" in prompt
    assert "Civic Participation" in prompt
    assert "決策" in prompt
    assert "不得與宣告內容領域矛盾" in prompt


def test_history_theme_prompt_is_explicitly_advisory_only() -> None:
    client = _FakeVerifierClient(_passed_payload())
    question = _question(
        content_domain="Civic Participation",
        subjects_and_codes=[("歷史", ["歷Aa-Ⅳ-1"])],
    )

    verify_question(client, question)

    prompt = client.system_prompt
    assert "內容領域主題檢視（僅供參考）" in prompt
    assert "素材" in prompt
    assert "核心問題" in prompt
    assert "不得影響 pass/fail" in prompt
    assert "Civic Participation" in prompt
    assert "決策" in prompt


def test_legacy_record_prompt_contains_no_iccs_criteria() -> None:
    client = _FakeVerifierClient(_passed_payload())
    question = _question(
        content_domain=None,
        subjects_and_codes=[("公民與社會", ["公Ba-Ⅳ-1"])],
    )

    verify_question(client, question)

    prompt = f"{client.system_prompt}\n{client.user_prompt}"
    assert "ICCS 認知歷程檢核" not in prompt
    assert "ICCS 內容領域檢核" not in prompt
    assert "內容領域主題檢視（僅供參考）" not in prompt


def test_history_theme_assessment_is_advisory_and_does_not_change_pass() -> None:
    payload = _passed_payload()
    payload["details"] = "主題看似未連結宣告內容領域，但這只是主題檢視意見。"
    client = _FakeVerifierClient(payload)
    question = _question(
        content_domain="Civic Participation",
        subjects_and_codes=[("歷史", ["歷Aa-Ⅳ-1"])],
    )

    result = verify_question(client, question)

    assert result.passed is True
    assert "[內容領域主題檢視（僅供參考）]" in result.details
    assert "主題看似未連結" in result.details


def test_corrector_freezes_iccs_axes_on_existing_and_added_subquestions() -> None:
    first_process = "Knowing–Defining and Describing"
    attempted_process = "Knowing–Illustrating with examples"
    added_process = "Reasoning and Applying–Interpret information"
    question = _question(
        content_domain="Civic Participation",
        subjects_and_codes=[("公民與社會", ["公Ca-Ⅳ-2"])],
        cognitive_processes=[first_process],
        top_level_processes=[first_process],
    )

    class _FakeCorrectorClient:
        def generate_json(self, *_args: object, **_kwargs: object) -> dict:
            return {
                "內容領域": "Civic Principles",
                "認知歷程": [attempted_process],
                "subquestions": [
                    {
                        "認知歷程": attempted_process,
                        "題型": "選擇題",
                        "題目": "修正後題目",
                        "答案": "A",
                    },
                    {
                        "序號": 2,
                        "科目": ["公民與社會"],
                        "認知歷程": added_process,
                        "題型": "選擇題",
                        "題目": "模型新增題目",
                        "答案": "B",
                    },
                ],
            }

    from src.social_studies.corrector import correct_question

    corrected = correct_question(
        _FakeCorrectorClient(),
        question,
        VerificationResult(passed=False, answer_match=False, details="需要修正"),
    )

    assert corrected.內容領域 == "Civic Participation"
    assert corrected.認知歷程 == [first_process]
    assert corrected.subquestions[0].認知歷程 == first_process
    assert corrected.subquestions[1].認知歷程 is None


def _interaction_question(
    interaction: DragDropSpec | SliderSpec, question_type: str
) -> ExamQuestion:
    return ExamQuestion(
        id="interaction-verifier-check",
        核心問題="互動題組核心問題",
        文本="互動題組素材",
        subquestions=[
            SubQuestion(
                序號=1,
                科目=["地理"],
                題型=question_type,
                題目="請操作互動元件。",
                答案="人類可讀答案",
                interaction=interaction,
            )
        ],
        情境=["教育"],
        題型種類="題組題",
        題型=question_type,
        閱讀歷程=["擷取訊息"],
        文本形式="連續文本—說明文",
    )


def test_interaction_verifier_rejects_unmapped_draggable_id() -> None:
    spec = DragDropSpec(
        draggables=[DragItem(id="d1", label="甲"), DragItem(id="d2", label="乙")],
        targets=[DropTarget(id="t1", label="目標")],
        correct_mapping={"d1": "t1"},
    )

    result = verify_question(
        _FakeVerifierClient(_passed_payload()),
        _interaction_question(spec, "拖放題"),
    )

    assert result.passed is False
    assert "[互動規格檢核]" in result.details
    assert "d2" in result.details


def test_interaction_verifier_rejects_unknown_target_and_total_capacity() -> None:
    spec = DragDropSpec(
        draggables=[DragItem(id="d1", label="甲"), DragItem(id="d2", label="乙")],
        targets=[DropTarget(id="t1", label="目標", capacity=1)],
        correct_mapping={"d1": "missing", "d2": "t1"},
    )

    result = verify_question(
        _FakeVerifierClient(_passed_payload()),
        _interaction_question(spec, "拖放題"),
    )

    assert result.passed is False
    assert "missing" in result.details
    assert "capacity" in result.details


def test_interaction_verifier_rejects_target_over_capacity() -> None:
    spec = DragDropSpec(
        draggables=[
            DragItem(id="d1", label="甲"),
            DragItem(id="d2", label="乙"),
            DragItem(id="d3", label="丙"),
        ],
        targets=[
            DropTarget(id="t1", label="小容量目標", capacity=1),
            DropTarget(id="t2", label="大容量目標", capacity=2),
        ],
        correct_mapping={"d1": "t1", "d2": "t1", "d3": "t2"},
    )

    result = verify_question(
        _FakeVerifierClient(_passed_payload()),
        _interaction_question(spec, "拖放題"),
    )

    assert result.passed is False
    assert "t1" in result.details
    assert "capacity" in result.details


def test_valid_drag_drop_interaction_does_not_change_llm_pass() -> None:
    spec = DragDropSpec(
        draggables=[DragItem(id="d1", label="甲"), DragItem(id="d2", label="乙")],
        targets=[DropTarget(id="t1", label="左"), DropTarget(id="t2", label="右")],
        correct_mapping={"d1": "t1", "d2": "t2"},
    )

    result = verify_question(
        _FakeVerifierClient(_passed_payload()),
        _interaction_question(spec, "拖放題"),
    )

    assert result.passed is True
    assert "[互動規格檢核]" not in result.details


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("min", 10),
        ("max", 0),
        ("step", 0),
        ("correct_value", 11),
        ("tolerance", -1),
        ("tolerance", 10),
    ],
)
def test_interaction_verifier_rejects_invalid_slider_spec(field: str, value: float) -> None:
    values = {
        "min": 0,
        "max": 10,
        "step": 1,
        "correct_value": 5,
        "tolerance": 1,
    }
    values[field] = value
    spec = SliderSpec(**values)

    result = verify_question(
        _FakeVerifierClient(_passed_payload()),
        _interaction_question(spec, "滑桿題"),
    )

    assert result.passed is False
    assert "[互動規格檢核]" in result.details
    assert field in result.details
