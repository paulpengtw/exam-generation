from __future__ import annotations

from pathlib import Path

from src.common.open_response_rubric import EXTRA_ITEMS_FIXED_SENTENCE
from src.config import Config


def _open_response_rubric() -> list[dict[str, object]]:
    return [
        {
            "code": "2",
            "規準說明": f"完整作答。{EXTRA_ITEMS_FIXED_SENTENCE}",
            "學生作答實例": ["完整回答"],
        },
        {
            "code": "1",
            "規準說明": "部分作答。",
            "學生作答實例": ["部分回答一", "部分回答二"],
        },
        {
            "code": "0",
            "規準說明": "錯誤作答。",
            "學生作答實例": ["錯誤回答"],
        },
    ]


def _prompt_requests_open_response(user: str) -> bool:
    return any(
        marker in user
        for marker in ("題型=開放式建構反應題", "題型=Constructed response")
    )


class _TextClient:
    def __init__(self, question_type: str, plan_count: int, observer=None) -> None:
        self.question_type = question_type
        self.plan_count = plan_count
        self.observer = observer

    def get_observer(self):
        return self.observer

    def generate_json(self, system, user, images=None, **kwargs):
        return {
            "核心問題": "測試核心問題",
            "文本": "測試文本",
            "取材來源": ["測試來源"],
            "subquestions": [
                {"序號": i, "題型": self.question_type, "出題概念": f"概念{i}"}
                for i in range(1, self.plan_count + 1)
            ],
        }


class _SubClient:
    def __init__(self, prompts_by_idx: dict[int, str] | None = None) -> None:
        self.prompts_by_idx = prompts_by_idx

    def set_observer(self, observer) -> None:
        pass

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        idx = int(agent_override.split("#", 1)[1])
        if self.prompts_by_idx is not None:
            self.prompts_by_idx[idx] = user
        concept = "" if "- **出題概念**：\n" in user else f"概念{idx}"
        response = {
            "序號": idx,
            "題型": "選擇題",
            "題目": f"第{idx}小題題目",
            "答案": "A",
            "答案解析": "解析",
            "出題概念": concept,
        }
        if _prompt_requests_open_response(user):
            response["評分規準"] = _open_response_rubric()
        return response


class _NaturalSubClient:
    def __init__(self, prompts_by_idx: dict[int, str] | None = None) -> None:
        self.prompts_by_idx = prompts_by_idx

    def set_observer(self, observer) -> None:
        pass

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        idx = int(agent_override.split("#", 1)[1])
        if self.prompts_by_idx is not None:
            self.prompts_by_idx[idx] = user
        concept = "" if "- **出題概念**：\n" in user else f"概念{idx}"
        response = {
            "序號": idx,
            "題型": "Simple multiple-choice",
            "題目": f"第{idx}小題題目",
            "答案": "A",
            "答案解析": "解析",
            "出題概念": concept,
        }
        if _prompt_requests_open_response(user):
            response["評分規準"] = _open_response_rubric()
        return response


class _PayloadSubClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def set_observer(self, observer) -> None:
        pass

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        idx = int(agent_override.split("#", 1)[1])
        return {"序號": idx, **self.payload}


def _config() -> Config:
    return Config(data_dir=Path("data"), subgen_max_concurrency=7, subgen_retries=0)


def test_社會領域_文本生成器計畫過長時截斷至指定小題數量() -> None:
    from src.social_studies.cli import generate_one
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=23, content_type="純文字", sub_question_count=3)

    question = generate_one(
        config=_config(),
        client=_TextClient("選擇題", plan_count=4),
        params=params,
        question_id="ss_truncate",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=_SubClient,
    )

    assert len(question.subquestions) == 3


def test_社會領域_公告截斷後的小題數量() -> None:
    from src.social_studies.cli import generate_one
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=23, content_type="純文字", sub_question_count=4)
    events: list[dict] = []

    generate_one(
        config=_config(),
        client=_TextClient("選擇題", plan_count=6, observer=events.append),
        params=params,
        question_id="ss_announce_truncated_count",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=_SubClient,
    )

    plan_events = [event for event in events if event.get("type") == "plan"]
    assert len(plan_events) == 1
    assert plan_events[0]["sub_question_total"] == 4


def test_社會領域_文本生成器計畫過短時以既有備援計畫補足小題() -> None:
    from src.social_studies.cli import generate_one
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=23, content_type="純文字", sub_question_count=3)

    question = generate_one(
        config=_config(),
        client=_TextClient("選擇題", plan_count=2),
        params=params,
        question_id="ss_pad",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=_SubClient,
    )

    assert len(question.subquestions) == 3
    assert question.subquestions[2].出題概念 == ""


def test_社會領域_公告補足後的小題數量() -> None:
    from src.social_studies.cli import generate_one
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=23, content_type="純文字", sub_question_count=5)
    events: list[dict] = []

    generate_one(
        config=_config(),
        client=_TextClient("選擇題", plan_count=2, observer=events.append),
        params=params,
        question_id="ss_announce_padded_count",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=_SubClient,
    )

    plan_events = [event for event in events if event.get("type") == "plan"]
    assert len(plan_events) == 1
    assert plan_events[0]["sub_question_total"] == 5


def test_社會領域_釘選題型寫入子題產生器提示詞() -> None:
    from src.social_studies.cli import generate_one
    from src.social_studies.sampler import sample_params

    params = sample_params(
        seed=23,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[{"question_type": "開放式建構反應題"}],
    )

    prompts_by_idx: dict[int, str] = {}
    generate_one(
        config=_config(),
        client=_TextClient("選擇題", plan_count=3),
        params=params,
        question_id="ss_pinned_type_prompt",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _SubClient(prompts_by_idx),
    )

    assert "- **題型**：開放式建構反應題" in prompts_by_idx[1]
    assert "- **題型**：選擇題" not in prompts_by_idx[1]


def test_社會領域_釘選題型覆寫子題產生器輸出() -> None:
    from src.social_studies.cli import generate_one
    from src.social_studies.sampler import sample_params

    params = sample_params(
        seed=23,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[{"question_type": "開放式建構反應題"}],
    )

    question = generate_one(
        config=_config(),
        client=_TextClient("選擇題", plan_count=3),
        params=params,
        question_id="ss_force_type",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=_SubClient,
    )

    assert question.subquestions[0].題型.value == "開放式建構反應題"


def test_社會領域_科目強制為取樣值() -> None:
    from src.social_studies.cli import generate_one
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import QuestionSubject

    params = sample_params(
        seed=23,
        content_type="純文字",
        sub_question_count=3,
        subject=[QuestionSubject("歷史")],
    )

    question = generate_one(
        config=_config(),
        client=_TextClient("選擇題", plan_count=3),
        params=params,
        question_id="ss_force_subject",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _PayloadSubClient({
            "科目": ["地理"],
            "題型": "選擇題",
            "題目": "測試題目",
            "答案": "A",
        }),
    )

    assert question.subquestions[0].科目 == ["歷史"]


def test_社會領域_科目強制不改動其他子題欄位() -> None:
    from src.social_studies.cli import generate_one
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import QuestionSubject

    params = sample_params(
        seed=23,
        content_type="純文字",
        sub_question_count=3,
        subject=[QuestionSubject("歷史")],
    )
    learning_content = [{"編碼": "歷Ka-Ⅳ-1", "說明": "歷史內容說明"}]
    learning_performance = [{"編碼": "社1b-Ⅳ-1", "說明": "學習表現說明"}]

    question = generate_one(
        config=_config(),
        client=_TextClient("選擇題", plan_count=3),
        params=params,
        question_id="ss_force_subject_fields",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _PayloadSubClient({
            "科目": ["地理"],
            "學習內容": learning_content,
            "學習表現": learning_performance,
            "題型": "選擇題",
            "題目": "應完整保留的題目",
            "答案": "應完整保留的答案",
        }),
    )

    subquestion = question.subquestions[0]
    assert subquestion.科目 == ["歷史"]
    assert [ref.model_dump() for ref in subquestion.學習內容] == learning_content
    assert [ref.model_dump() for ref in subquestion.學習表現] == learning_performance
    assert subquestion.題目 == "應完整保留的題目"
    assert subquestion.答案 == "應完整保留的答案"


def test_社會領域_空白題型將計畫寫入提示詞但保留子題產生器輸出() -> None:
    from src.social_studies.cli import generate_one
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import SubQuestionConfig

    params = sample_params(seed=23, content_type="純文字", sub_question_count=3)
    params = params.model_copy(
        update={
            "subquestion_configs": [
                SubQuestionConfig(),
                *params.subquestion_configs[1:],
            ],
        },
    )

    prompts_by_idx: dict[int, str] = {}
    question = generate_one(
        config=_config(),
        client=_TextClient("開放式建構反應題", plan_count=3),
        params=params,
        question_id="ss_blank_type",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _SubClient(prompts_by_idx),
    )

    assert "- **題型**：開放式建構反應題" in prompts_by_idx[1]
    assert question.subquestions[0].題型.value == "選擇題"


def test_社會領域_文本生成器計畫題型無效時不丟棄小題() -> None:
    from src.social_studies.cli import generate_one
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import SubQuestionConfig

    params = sample_params(seed=23, content_type="純文字", sub_question_count=3)
    params = params.model_copy(
        update={"subquestion_configs": [SubQuestionConfig() for _ in range(3)]},
    )

    question = generate_one(
        config=_config(),
        client=_TextClient("不是有效題型", plan_count=3),
        params=params,
        question_id="ss_invalid_plan_type",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=_SubClient,
    )

    assert len(question.subquestions) == 3
    assert question.subquestions[0].題型.value == "選擇題"


def test_社會領域_解析後的小題數量不由文本生成器決定() -> None:
    from src.social_studies.cli import generate_one
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=23, content_type="純文字", sub_question_count=4)

    question = generate_one(
        config=_config(),
        client=_TextClient("選擇題", plan_count=4),
        params=params,
        question_id="ss_llm_count",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=_SubClient,
    )

    assert len(question.subquestions) == 4


def test_社會領域_解析後在子題產生前公告固定小題數量() -> None:
    from src.social_studies.cli import generate_one
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=23, content_type="純文字", sub_question_count=4)
    events: list[dict] = []

    generate_one(
        config=_config(),
        client=_TextClient("選擇題", plan_count=4, observer=events.append),
        params=params,
        question_id="ss_announce_llm_count",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=_SubClient,
    )

    plan_events = [event for event in events if event.get("type") == "plan"]
    assert len(plan_events) == 1
    assert plan_events[0]["agent"] == "generator"
    assert plan_events[0]["sub_question_total"] == 4

    plan_index = events.index(plan_events[0])
    first_sub_generator_start = next(
        index
        for index, event in enumerate(events)
        if event.get("type") == "stage"
        and str(event.get("agent", "")).startswith("sub_generator#")
        and event.get("status") == "start"
    )
    assert plan_index < first_sub_generator_start


def test_自然科學_文本生成器計畫過長時截斷至指定小題數量() -> None:
    from src.natural_sciences.cli import generate_one
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=23, content_type="純文字", sub_question_count=3)

    question = generate_one(
        config=_config(),
        client=_TextClient("Simple multiple-choice", plan_count=4),
        params=params,
        question_id="ns_truncate",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=_NaturalSubClient,
    )

    assert len(question.subquestions) == 3


def test_自然科學_文本生成器計畫過短時以既有備援計畫補足小題() -> None:
    from src.natural_sciences.cli import generate_one
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=23, content_type="純文字", sub_question_count=3)

    question = generate_one(
        config=_config(),
        client=_TextClient("Simple multiple-choice", plan_count=2),
        params=params,
        question_id="ns_pad",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=_NaturalSubClient,
    )

    assert len(question.subquestions) == 3
    assert question.subquestions[2].出題概念 == ""


def test_自然科學_釘選題型寫入子題產生器提示詞() -> None:
    from src.natural_sciences.cli import generate_one
    from src.natural_sciences.sampler import sample_params

    params = sample_params(
        seed=23,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[{"question_type": "Constructed response"}],
    )

    prompts_by_idx: dict[int, str] = {}
    generate_one(
        config=_config(),
        client=_TextClient("Simple multiple-choice", plan_count=3),
        params=params,
        question_id="ns_pinned_type_prompt",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _NaturalSubClient(prompts_by_idx),
    )

    assert "- **題型**：Constructed response" in prompts_by_idx[1]
    assert "- **題型**：Simple multiple-choice" not in prompts_by_idx[1]


def test_自然科學_釘選題型覆寫子題產生器輸出() -> None:
    from src.natural_sciences.cli import generate_one
    from src.natural_sciences.sampler import sample_params

    params = sample_params(
        seed=23,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[{"question_type": "Constructed response"}],
    )

    question = generate_one(
        config=_config(),
        client=_TextClient("Simple multiple-choice", plan_count=3),
        params=params,
        question_id="ns_force_type",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=_NaturalSubClient,
    )

    assert question.subquestions[0].題型.value == "Constructed response"


def test_自然科學_科目強制為自然科學() -> None:
    from src.natural_sciences.cli import generate_one
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=23, content_type="純文字", sub_question_count=3)

    question = generate_one(
        config=_config(),
        client=_TextClient("Simple multiple-choice", plan_count=3),
        params=params,
        question_id="ns_force_subject",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _PayloadSubClient({
            "科目": ["生物"],
            "題型": "Simple multiple-choice",
            "題目": "測試題目",
            "答案": "A",
        }),
    )

    assert question.subquestions[0].科目 == ["自然科學"]


def test_自然科學_空白題型將計畫寫入提示詞但保留子題產生器輸出() -> None:
    from src.natural_sciences.cli import generate_one
    from src.natural_sciences.sampler import sample_params
    from src.natural_sciences.schemas import SubQuestionConfig

    params = sample_params(seed=23, content_type="純文字", sub_question_count=3)
    params = params.model_copy(
        update={
            "subquestion_configs": [
                SubQuestionConfig(),
                *params.subquestion_configs[1:],
            ],
        },
    )

    prompts_by_idx: dict[int, str] = {}
    question = generate_one(
        config=_config(),
        client=_TextClient("Constructed response", plan_count=3),
        params=params,
        question_id="ns_blank_type",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _NaturalSubClient(prompts_by_idx),
    )

    assert "- **題型**：Constructed response" in prompts_by_idx[1]
    assert question.subquestions[0].題型.value == "Simple multiple-choice"


def test_自然科學_文本生成器計畫題型無效時不丟棄小題() -> None:
    from src.natural_sciences.cli import generate_one
    from src.natural_sciences.sampler import sample_params
    from src.natural_sciences.schemas import SubQuestionConfig

    params = sample_params(seed=23, content_type="純文字", sub_question_count=3)
    params = params.model_copy(
        update={"subquestion_configs": [SubQuestionConfig() for _ in range(3)]},
    )

    question = generate_one(
        config=_config(),
        client=_TextClient("Not a valid question type", plan_count=3),
        params=params,
        question_id="ns_invalid_plan_type",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=_NaturalSubClient,
    )

    assert len(question.subquestions) == 3
    assert question.subquestions[0].題型.value == "Simple multiple-choice"


def test_自然科學_解析後的小題數量不由文本生成器決定() -> None:
    from src.natural_sciences.cli import generate_one
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=23, content_type="純文字", sub_question_count=4)

    question = generate_one(
        config=_config(),
        client=_TextClient("Simple multiple-choice", plan_count=4),
        params=params,
        question_id="ns_llm_count",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=_NaturalSubClient,
    )

    assert len(question.subquestions) == 4


def test_自然科學_固定小題身份覆寫模型編號並保留逐題釘選欄位() -> None:
    from src.natural_sciences.cli import generate_one
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=745, content_type="純文字", sub_question_count=3)
    question = generate_one(
        config=_config(),
        client=_TextClient("Simple multiple-choice", plan_count=3),
        params=params,
        question_id="ns_fixed_identity",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _PayloadSubClient({
            "id": "model-owned-id",
            "序號": 99,
            "科目": ["生物"],
            "題型": "Simple multiple-choice",
            "題目": "固定身份測試",
            "答案": "A",
        }),
    )

    assert [sub.id for sub in question.subquestions] == [
        "ns_fixed_identity-sq001",
        "ns_fixed_identity-sq002",
        "ns_fixed_identity-sq003",
    ]
    assert [sub.序號 for sub in question.subquestions] == [1, 2, 3]
    assert [sub._plan_index for sub in question.subquestions] == [1, 2, 3]
    assert all(sub.科目 == ["自然科學"] for sub in question.subquestions)


def test_數學題組_固定小題身份覆寫模型編號() -> None:
    from src.cli import generate_one
    from src.sampler import sample_params
    from src.schemas import QuestionContext, QuestionSetType, QuestionType

    params = sample_params(
        grade=8,
        context=[QuestionContext("個人")],
        set_type=QuestionSetType("題組題"),
        q_type=[QuestionType("選擇題")],
        seed=745,
        math_thinking=None,
        learning_content=["A-7-7"],
        learning_performance=["s-IV-12"],
        content_type="純文字",
        sub_question_count=3,
    )
    question = generate_one(
        config=_config(),
        client=_TextClient("選擇題", plan_count=3),
        curriculum=[],
        performance={},
        intro_text="",
        grade_content={},
        params=params,
        question_id="math_fixed_identity",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _PayloadSubClient({
            "id": "model-owned-id",
            "序號": 99,
            "題型": "選擇題",
            "題目": "固定身份測試",
            "答案": "A",
        }),
    )

    assert [sub.id for sub in question.subquestions] == [
        "math_fixed_identity-sq001",
        "math_fixed_identity-sq002",
        "math_fixed_identity-sq003",
    ]
    assert [sub.序號 for sub in question.subquestions] == [1, 2, 3]
    assert [sub._plan_index for sub in question.subquestions] == [1, 2, 3]


def test_數學單一題_不建立虛構小題身份或計畫() -> None:
    from src.cli import generate_one
    from src.sampler import sample_params
    from src.schemas import QuestionContext, QuestionSetType, QuestionType

    events: list[dict] = []
    params = sample_params(
        grade=8,
        context=[QuestionContext("個人")],
        set_type=QuestionSetType("單一題"),
        q_type=[QuestionType("選擇題")],
        seed=745,
        learning_content=["A-7-7"],
        learning_performance=["s-IV-12"],
        content_type="純文字",
    )
    question = generate_one(
        config=_config(),
        client=_TextClient("選擇題", plan_count=3, observer=events.append),
        curriculum=[],
        performance={},
        intro_text="",
        grade_content={},
        params=params,
        question_id="math_flat_identity",
        skip_verify=True,
        disable_reference_fewshot=True,
    )

    assert question.subquestions == []
    assert not any(event.get("type") == "plan" for event in events)
