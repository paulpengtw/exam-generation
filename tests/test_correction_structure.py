"""A correction preserves the entering 題組 snapshot or updates it atomically."""
from __future__ import annotations

from importlib import import_module

import pytest


def make_question(subject: str, ordinals: tuple[int, ...] = (1, 2, 3, 4, 5)):
    prefix = "src" if subject == "math" else f"src.{subject}"
    schemas = import_module(f"{prefix}.schemas")
    question_type = "Simple multiple-choice" if subject == "natural_sciences" else "選擇題"
    data = {
        "id": "q-806",
        "核心問題": "如何比較資料？",
        "文本": "原始共享文本",
        "題型種類": "題組題",
        "題型": question_type,
        "情境": [],
        "題目": ["原始題幹"],
        "正確解題分析": ["原始分析"],
        "subquestions": [
            {
                "id": f"q-806-{number}",
                "序號": number,
                "年級": 8,
                "題型": question_type,
                "題目": f"原始第{number}小題",
                "答案": f"答案{number}",
                "答案解析": f"解析{number}",
                "學習內容": [{"編碼": f"N-7-{number}", "說明": f"釘選{number}"}],
                "出題概念": f"概念{number}",
                "出題指示": f"指示{number}",
                "圖片": f"q-806-{number}.png",
                "image_generation_mode": "html",
            }
            for number in ordinals
        ],
        "verification": {
            "passed": False,
            "answer_match": False,
            "details": "第三小題的答案需要修正",
        },
        "metadata": {"grade": 8, "model": "controlled", "seed": 401183334, "style": "text_only"},
    }
    if subject == "math":
        data.update(數學思考=["運用"], 學習內容=[])
    return schemas.ExamQuestion.model_validate(data)


class CorrectionProvider:
    def __init__(self, payload):
        self.payload = payload
        self.events = []

    def get_observer(self):
        return self.events.append

    def generate_json(self, *_args, **_kwargs):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def correct(subject: str, question, payload):
    prefix = "src" if subject == "math" else f"src.{subject}"
    correct_question = import_module(f"{prefix}.corrector").correct_question
    return correct_question(CorrectionProvider(payload), question, question.verification)


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences", "math"])
@pytest.mark.parametrize("missing_index", [0, 2, 4], ids=["first", "middle", "last"])
def test_five_to_four_correction_preserves_the_complete_previous_snapshot(subject, missing_index):
    question = make_question(subject)
    before = question.model_dump(mode="json")
    candidate = question.model_dump(mode="json")
    candidate["文本"] = "拒絕的共享文本"
    candidate["subquestions"].pop(missing_index)
    candidate["subquestions"][2]["答案"] = "不應移給第三小題"

    result = correct(subject, question, candidate)

    assert result.model_dump(mode="json") == before
    assert question.model_dump(mode="json") == before


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences", "math"])
@pytest.mark.parametrize("defect", [
    "extra", "duplicate", "changed_id", "changed_ordinal", "reordered", "non_object",
    "ambiguous", "missing_list", "invalid_list", "empty", "bool_ordinal",
])
def test_invalid_structure_rejects_all_candidate_content(subject, defect):
    question = make_question(subject)
    before = question.model_dump(mode="json")
    candidate = question.model_dump(mode="json")
    candidate["文本"] = "拒絕的文本"
    candidate["題目"] = ["拒絕的題幹"]
    candidate["正確解題分析"] = ["拒絕的分析"]
    rows = candidate["subquestions"]
    rows[0]["答案"] = "拒絕的答案"
    if defect == "extra":
        rows.append({**rows[-1], "id": "extra", "序號": 6})
    elif defect == "duplicate":
        rows[2] = rows[1].copy()
    elif defect == "changed_id":
        rows[2]["id"] = "unknown"
    elif defect == "changed_ordinal":
        rows[2]["序號"] = 99
    elif defect == "reordered":
        rows[0], rows[1] = rows[1], rows[0]
    elif defect == "non_object":
        rows[2] = "broken"
    elif defect == "ambiguous":
        rows[2].pop("id")
        rows[2].pop("序號")
    elif defect == "missing_list":
        candidate.pop("subquestions")
    elif defect == "invalid_list":
        candidate["subquestions"] = "broken"
    elif defect == "empty":
        candidate["subquestions"] = []
    elif defect == "bool_ordinal":
        rows[0]["序號"] = True

    result = correct(subject, question, candidate)

    assert result.model_dump(mode="json") == before
    assert question.model_dump(mode="json") == before


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences", "math"])
@pytest.mark.parametrize("field,value", [
    ("題目", None), ("答案", ["invalid"]), ("答案解析", {"invalid": True}),
    ("誘答分析", {"A": ["invalid"]}),
])
def test_invalid_editable_row_data_rejects_the_complete_correction(subject, field, value):
    question = make_question(subject)
    before = question.model_dump(mode="json")
    candidate = question.model_dump(mode="json")
    candidate["文本"] = "拒絕的文本"
    candidate["題目"] = ["拒絕的題幹"]
    candidate["subquestions"][0]["答案"] = "拒絕的答案"
    candidate["subquestions"][2][field] = value

    result = correct(subject, question, candidate)

    assert result.model_dump(mode="json") == before


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences"])
@pytest.mark.parametrize("key", ["評分規準", "評分標準"])
@pytest.mark.parametrize("rubric", [
    "invalid", ["invalid"], [{"code": "2", "規準說明": []}],
    [{"code": {"invalid": True}, "規準說明": "不應套用"}],
])
def test_malformed_rubric_rejects_the_complete_correction(subject, key, rubric):
    question = make_question(subject)
    before = question.model_dump(mode="json")
    candidate = question.model_dump(mode="json")
    candidate["文本"] = "拒絕的文本"
    candidate["subquestions"][2]["答案"] = "拒絕的答案"
    candidate["subquestions"][2][key] = rubric

    result = correct(subject, question, candidate)

    assert result.model_dump(mode="json") == before


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences", "math"])
@pytest.mark.parametrize("ordinals", [(1, 2, 3, 4, 5), (1, 3, 5)], ids=["complete", "partial"])
@pytest.mark.parametrize("identity", ["both", "id", "ordinal"])
def test_valid_correction_updates_the_intended_row_and_preserves_frozen_fields(
    subject, ordinals, identity,
):
    question = make_question(subject, ordinals)
    before = question.model_dump(mode="json")
    candidate = question.model_dump(mode="json")
    for row in candidate["subquestions"]:
        if identity == "id":
            row.pop("序號")
        elif identity == "ordinal":
            row.pop("id")
        row.update({
            "年級": 12, "學習內容": [], "學習表現": [], "出題概念": "不應取代釘選",
            "出題指示": "不應取代指示", "圖片": "wrong.png", "image_generation_mode": "gpt_image",
        })
        if row.get("id") == "q-806-3" or row.get("序號") == 3:
            row.update({"題目": "修正後第三小題", "答案": "B", "答案解析": "修正後解析"})
    expected = question.model_dump(mode="json")
    expected["verification"] = None
    for row in expected["subquestions"]:
        if row["id"] == "q-806-3":
            row.update({"題目": "修正後第三小題", "答案": "B", "答案解析": "修正後解析"})

    result = correct(subject, question, candidate)

    assert result.model_dump(mode="json") == expected
    assert question.model_dump(mode="json") == before


@pytest.mark.parametrize("subject,field,value", [
    (subject, field, value)
    for subject in ("social_studies", "natural_sciences", "math")
    for field, value in [
        ("題目", [None]), ("正確解題分析", [42]), ("題目", "invalid"),
        ("正確解題分析", None), ("文本", []),
    ]
    if not (subject == "math" and field == "文本")  # Math 文本 is frozen.
])
def test_invalid_shared_content_rejects_otherwise_valid_rows(subject, field, value):
    question = make_question(subject)
    before = question.model_dump(mode="json")
    candidate = question.model_dump(mode="json")
    candidate[field] = value
    candidate["subquestions"][2]["答案"] = "不應套用"

    result = correct(subject, question, candidate)

    assert result.model_dump(mode="json") == before


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences", "math"])
@pytest.mark.parametrize("field", ["image_spec", "chart_spec"])
@pytest.mark.parametrize("value", [[], {"render_mode": "invalid"}])
def test_invalid_shared_image_rejects_otherwise_valid_rows(subject, field, value):
    question = make_question(subject)
    before = question.model_dump(mode="json")
    candidate = question.model_dump(mode="json")
    candidate[field] = value
    candidate["subquestions"][2]["答案"] = "不應套用"

    result = correct(subject, question, candidate)

    assert result.model_dump(mode="json") == before


@pytest.mark.parametrize("value", [[], {"A": ["invalid"]}])
def test_invalid_math_distractor_analysis_rejects_otherwise_valid_rows(value):
    question = make_question("math")
    before = question.model_dump(mode="json")
    candidate = question.model_dump(mode="json")
    candidate["誘答分析"] = value
    candidate["subquestions"][2]["答案"] = "不應套用"

    result = correct("math", question, candidate)

    assert result.model_dump(mode="json") == before


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences", "math"])
@pytest.mark.parametrize("payload", [None, ["invalid"], ValueError("invalid provider JSON")])
def test_unreadable_correction_reports_rejection_and_keeps_previous_snapshot(subject, payload):
    question = make_question(subject)
    before = question.model_dump(mode="json")
    provider = CorrectionProvider(payload)
    prefix = "src" if subject == "math" else f"src.{subject}"
    correct_question = import_module(f"{prefix}.corrector").correct_question

    result = correct_question(provider, question, question.verification)

    assert result.model_dump(mode="json") == before
    assert len(provider.events) == 1
    diagnostic = provider.events[0]
    assert diagnostic["agent"] == "corrector"
    assert diagnostic["status"] == "error"
    assert diagnostic["code"] == "correction_rejected"
    assert diagnostic["message"]
