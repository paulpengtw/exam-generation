"""A correction preserves the entering 題組 snapshot or updates it atomically."""
from __future__ import annotations

from importlib import import_module

import pytest
from pydantic import ValidationError


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
    "ambiguous", "invalid_list", "empty", "bool_ordinal",
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


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences", "math"])
def test_omitted_subquestions_preserves_rows_but_accepts_valid_top_level_edit(subject):
    question = make_question(subject)
    before_rows = [row.model_dump(mode="json") for row in question.subquestions]
    candidate = question.model_dump(mode="json")
    candidate.pop("subquestions")
    candidate["題目"] = ["修正後題幹"]
    decisions = []

    prefix = "src" if subject == "math" else f"src.{subject}"
    correct_question = import_module(f"{prefix}.corrector").correct_question
    result = correct_question(
        CorrectionProvider(candidate), question, question.verification,
        on_decision=decisions.append,
    )

    assert result.題目 == ["修正後題幹"]
    assert [row.model_dump(mode="json") for row in result.subquestions] == before_rows
    assert len(decisions) == 1
    assert decisions[0].outcome == "accepted"
    assert decisions[0].reason is None


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences", "math"])
def test_repeated_ids_require_a_disambiguating_ordinal(subject):
    question = make_question(subject, (1, 2, 3))
    question.subquestions[1].id = question.subquestions[0].id
    candidate = question.model_dump(mode="json")
    candidate["subquestions"][1].pop("序號")
    candidate["subquestions"][1]["答案"] = "不應套用"
    before = question.model_dump(mode="json")
    decisions = []

    prefix = "src" if subject == "math" else f"src.{subject}"
    correct_question = import_module(f"{prefix}.corrector").correct_question
    result = correct_question(
        CorrectionProvider(candidate), question, question.verification,
        on_decision=decisions.append,
    )

    assert result.model_dump(mode="json") == before
    assert len(decisions) == 1
    assert decisions[0].outcome == "rejected"
    assert decisions[0].reason.code == "subquestion_identity_ambiguous"
    assert decisions[0].reason.path == "subquestions[1]"


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences", "math"])
def test_repeated_ids_are_valid_when_ordinal_pair_identifies_each_row(subject):
    question = make_question(subject, (1, 2, 3))
    question.subquestions[1].id = question.subquestions[0].id
    candidate = question.model_dump(mode="json")
    candidate["subquestions"][1]["答案"] = "修正後答案"
    decisions = []

    prefix = "src" if subject == "math" else f"src.{subject}"
    correct_question = import_module(f"{prefix}.corrector").correct_question
    result = correct_question(
        CorrectionProvider(candidate), question, question.verification,
        on_decision=decisions.append,
    )

    assert result.subquestions[1].答案 == "修正後答案"
    assert result.subquestions[0].答案 != "修正後答案"
    assert [decision.outcome for decision in decisions] == ["accepted"]


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences", "math"])
@pytest.mark.parametrize("identity_field,value", [("序號", "1"), ("id", "")])
def test_malformed_or_empty_identity_is_rejected(subject, identity_field, value):
    question = make_question(subject, (1, 2, 3))
    candidate = question.model_dump(mode="json")
    candidate["subquestions"][0][identity_field] = value
    decisions = []
    prefix = "src" if subject == "math" else f"src.{subject}"
    correct_question = import_module(f"{prefix}.corrector").correct_question

    result = correct_question(
        CorrectionProvider(candidate), question, question.verification,
        on_decision=decisions.append,
    )

    assert result.model_dump(mode="json") == question.model_dump(mode="json")
    assert len(decisions) == 1
    assert decisions[0].outcome == "rejected"
    assert decisions[0].reason.path == "subquestions[0]"


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences", "math"])
def test_repeated_ordinals_require_a_disambiguating_id(subject):
    question = make_question(subject, (1, 2, 3))
    question.subquestions[1].序號 = question.subquestions[0].序號
    candidate = question.model_dump(mode="json")
    candidate["subquestions"][1].pop("id")
    candidate["subquestions"][1]["答案"] = "不應套用"
    decisions = []
    prefix = "src" if subject == "math" else f"src.{subject}"
    correct_question = import_module(f"{prefix}.corrector").correct_question

    result = correct_question(
        CorrectionProvider(candidate), question, question.verification,
        on_decision=decisions.append,
    )

    assert result.model_dump(mode="json") == question.model_dump(mode="json")
    assert decisions[0].outcome == "rejected"
    assert decisions[0].reason.code == "subquestion_identity_ambiguous"


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences", "math"])
@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (None, "response_shape"),
        (ValueError("provider detail must not escape"), "response_unreadable"),
    ],
)
def test_decision_callback_reports_safe_provider_failure(subject, payload, expected_code):
    question = make_question(subject)
    decisions = []
    prefix = "src" if subject == "math" else f"src.{subject}"
    correct_question = import_module(f"{prefix}.corrector").correct_question

    result = correct_question(
        CorrectionProvider(payload), question, question.verification,
        on_decision=decisions.append,
    )

    assert result.model_dump(mode="json") == question.model_dump(mode="json")
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.outcome == "rejected"
    assert decision.reason.code == expected_code
    assert decision.reason.path == "$"
    assert "provider detail" not in decision.reason.message
    with pytest.raises(ValidationError):
        decision.outcome = "accepted"


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences", "math"])
def test_group_with_zero_survivors_cannot_gain_rows_but_accepts_top_level_edit(subject):
    question = make_question(subject, ())
    candidate = question.model_dump(mode="json")
    candidate["題目"] = ["修正後題幹"]
    decisions = []
    prefix = "src" if subject == "math" else f"src.{subject}"
    correct_question = import_module(f"{prefix}.corrector").correct_question

    result = correct_question(
        CorrectionProvider(candidate), question, question.verification,
        on_decision=decisions.append,
    )

    assert result.題目 == ["修正後題幹"]
    assert result.subquestions == []
    assert [decision.outcome for decision in decisions] == ["accepted"]

    empty_candidate = {"題目": ["再次修正"], "subquestions": []}
    empty_result = correct_question(
        CorrectionProvider(empty_candidate), question, question.verification,
        on_decision=decisions.append,
    )
    assert empty_result.題目 == ["再次修正"]
    assert empty_result.subquestions == []
    assert decisions[-1].outcome == "accepted"

    candidate["subquestions"] = [{"id": "new", "序號": 1, "題目": "新增"}]
    rejected = correct_question(
        CorrectionProvider(candidate), question, question.verification,
        on_decision=decisions.append,
    )

    assert rejected.model_dump(mode="json") == question.model_dump(mode="json")
    assert decisions[-1].outcome == "rejected"
    assert decisions[-1].reason.code == "subquestions_count"


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences", "math"])
def test_accepted_correction_is_detached_from_input_snapshot(subject):
    question = make_question(subject)
    question.subquestions[0]._plan_index = 41
    candidate = question.model_dump(mode="json")
    candidate["subquestions"][0]["答案"] = "修正後答案"
    prefix = "src" if subject == "math" else f"src.{subject}"
    correct_question = import_module(f"{prefix}.corrector").correct_question

    result = correct_question(CorrectionProvider(candidate), question, question.verification)
    result.subquestions[0].答案 = "後續呼叫端修改"
    result.subquestions[0].學習內容[0].說明 = "後續呼叫端修改釘選"
    result.subquestions[0]._plan_index = 99

    assert question.subquestions[0].答案 == "答案1"
    assert question.subquestions[0].學習內容[0].說明 == "釘選1"
    assert question.subquestions[0]._plan_index == 41


def test_flat_math_correction_keeps_legacy_serialization_without_group_fields():
    question = make_question("math", ())
    question.題型種類 = type(question.題型種類)("單一題")
    question.文本 = ""
    question.核心問題 = ""
    correct_question = import_module("src.corrector").correct_question
    decisions = []

    result = correct_question(
        CorrectionProvider({"題目": ["修正後題目"], "正確解題分析": ["修正後解析"]}),
        question, question.verification, on_decision=decisions.append,
    )

    serialized = result.model_dump(mode="json")
    assert serialized["題目"] == ["修正後題目"]
    assert serialized["正確解題分析"] == ["修正後解析"]
    assert serialized["題型種類"] == "單一題"
    assert {"subquestions", "文本", "核心問題", "取材來源"}.isdisjoint(serialized)
    assert result.verification is None
    assert [decision.outcome for decision in decisions] == ["accepted"]


def test_math_actual_rows_remain_protected_despite_legacy_flat_label():
    question = make_question("math", (1, 3, 5))
    question.題型種類 = type(question.題型種類)("單一題")
    candidate = question.model_dump(mode="json")
    candidate["subquestions"].pop(1)
    candidate["題目"] = ["不可套用的題目"]

    result = correct("math", question, candidate)

    assert result.model_dump(mode="json") == question.model_dump(mode="json")
