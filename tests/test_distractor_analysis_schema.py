"""Schema round-trip for the 誘答分析 field on math, SS, and NS."""

from __future__ import annotations

import json


def test_math_exam_question_accepts_and_defaults_distractor_analysis() -> None:
    from src.schemas import ExamQuestion

    q = ExamQuestion(
        情境=["個人"],
        題型種類="單一題",
        題型="選擇題",
        數學思考=["形成"],
        學習內容=[],
        題目=["Q?"],
        正確解題分析=["A"],
    )
    assert q.誘答分析 == {}

    dump = json.loads(q.model_dump_json())
    assert dump["誘答分析"] == {}

    q2 = ExamQuestion(
        情境=["個人"],
        題型種類="單一題",
        題型="選擇題",
        數學思考=["形成"],
        學習內容=[],
        題目=["Q?"],
        正確解題分析=["A"],
        誘答分析={"A": "正確答案：加權平均。", "B": "誤讀題意：忽略權重。"},
    )
    assert q2.誘答分析["B"] == "誤讀題意：忽略權重。"


def test_social_studies_subquestion_accepts_and_defaults_distractor_analysis() -> None:
    from src.social_studies.schemas import SubQuestion

    sq = SubQuestion(題型="選擇題", 題目="Q?")
    assert sq.誘答分析 == {}

    sq2 = SubQuestion(
        題型="選擇題",
        題目="Q?",
        誘答分析={"A": "正確答案：...", "C": "概念混淆"},
    )
    assert sq2.誘答分析["C"] == "概念混淆"


def test_natural_sciences_subquestion_accepts_and_defaults_distractor_analysis() -> None:
    from src.natural_sciences.schemas import SubQuestion

    sq = SubQuestion(題型="Simple multiple-choice", 題目="Q?")
    assert sq.誘答分析 == {}

    sq2 = SubQuestion(
        題型="Constructed response",
        題目="Q?",
        誘答分析={"常見錯誤": "誤以為 CO2 是主要污染物"},
    )
    assert sq2.誘答分析["常見錯誤"].startswith("誤以為")
