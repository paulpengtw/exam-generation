from __future__ import annotations

import json
from pathlib import Path


def _flat_math_question():
    from src.cli import _parse_question
    from src.sampler import sample_params

    params = sample_params(grade=8, seed=0)
    return _parse_question(
        {
            "題目": ["若 x=2，求 3x。"],
            "正確解題分析": ["3×2=6。"],
        },
        "flat-q",
        params,
        "test-model",
    )


def test_math_subquestion_has_the_decided_fields_without_a_rubric() -> None:
    from src.schemas import LearningContentItem, QuestionType, SubQuestion

    subquestion = SubQuestion(
        id="q1-01",
        序號=1,
        年級=8,
        題型=next(iter(QuestionType)),
        題目="一個完整的數學小題",
        答案="A",
        答案解析="計算與推理",
        誘答分析={"A": "正確答案：A"},
        學習內容=[LearningContentItem(編碼="N-8-1", 說明="二次方根")],
        學習表現=[LearningContentItem(編碼="n-Ⅳ-1", 說明="理解與應用")],
        出題概念="評量學生能否運用二次方根",
    )

    assert subquestion.id == "q1-01"
    assert subquestion.答案 == "A"
    assert "評分規準" not in type(subquestion).model_fields


def test_flat_math_serialization_omits_empty_group_fields(tmp_path) -> None:
    from server.config import ServerConfig
    from server.generate.marshalling import question_to_event

    question = _flat_math_question()
    group_fields = {"文本", "核心問題", "取材來源", "subquestions"}

    assert group_fields.isdisjoint(question.model_dump(exclude_none=True))
    payload = question_to_event(
        question,
        ServerConfig(api_key="test", data_dir=tmp_path, output_dir=tmp_path),
    )

    assert group_fields.isdisjoint(payload)


def test_existing_flat_fixture_round_trips_without_group_fields() -> None:
    from src.schemas import ExamQuestion

    fixture = json.loads(
        (Path("data/few_shot/text_only/example_01.json")).read_text(encoding="utf-8")
    )[0]["question"]
    fixture["情境"] = [fixture["情境"]]
    question = ExamQuestion.model_validate(
        {
            **fixture,
            "id": "fixture-q",
            "metadata": None,
        }
    )

    wire = json.loads(question.model_dump_json(exclude_none=True))
    restored = ExamQuestion.model_validate(wire)

    assert json.loads(restored.model_dump_json(exclude_none=True)) == wire
    assert not {"文本", "核心問題", "取材來源", "subquestions"} & wire.keys()
