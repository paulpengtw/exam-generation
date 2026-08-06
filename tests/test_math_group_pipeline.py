from __future__ import annotations

from pathlib import Path

from src.config import Config


class _MathTextClient:
    def __init__(self, plan_count: int) -> None:
        self.plan_count = plan_count

    def get_observer(self):
        return None

    def generate_json(self, system, user, images=None, **kwargs):
        return {
            "核心問題": "哪一個方案較划算？",
            "文本": "方案甲每件 10 元，方案乙每件 12 元。",
            "取材來源": ["試算資料"],
            "subquestions": [
                {"序號": i, "題型": "選擇題", "出題概念": f"概念{i}"}
                for i in range(1, self.plan_count + 1)
            ],
        }


class _MathSubQuestionClient:
    def set_observer(self, observer) -> None:
        pass

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        index = int(agent_override.split("#", 1)[1])
        concept = "" if "- **出題概念**：\n" in user else f"概念{index}"
        return {
            "序號": index,
            "年級": 8,
            "題型": "選擇題",
            "題目": f"第{index}小題題目",
            "答案": "A",
            "答案解析": "依文本計算。",
            "誘答分析": {},
            "學習內容": [],
            "學習表現": [],
            "出題概念": concept,
        }


class _MathFlatClient:
    def get_observer(self):
        return None

    def generate_json(self, system, user, images=None, **kwargs):
        return {
            "情境": ["個人"],
            "題型種類": "單一題",
            "題型": "選擇題",
            "數學思考": ["運用"],
            "學習內容": [],
            "題目": ["若 x=2，求 3x。"],
            "正確解題分析": ["3×2=6。"],
        }


def _config(tmp_path: Path) -> Config:
    return Config(
        data_dir=Path("data"),
        output_dir=tmp_path,
        subgen_max_concurrency=4,
        subgen_retries=0,
    )


def test_math_opt_in_generation_returns_the_requested_four_subquestions(tmp_path) -> None:
    from src.cli import generate_one
    from src.sampler import sample_params

    params = sample_params(
        grade=8,
        seed=23,
        content_type="純文字",
        sub_question_count=4,
    )
    question = generate_one(
        config=_config(tmp_path),
        client=_MathTextClient(plan_count=4),
        curriculum=[],
        performance={},
        intro_text="",
        grade_content={},
        params=params,
        question_id="math_group",
        skip_verify=True,
        sub_client_factory=_MathSubQuestionClient,
    )

    assert len(question.subquestions) == 4
    assert [sub.序號 for sub in question.subquestions] == [1, 2, 3, 4]
    assert question.核心問題 == "哪一個方案較划算？"
    assert question.文本 == "方案甲每件 10 元，方案乙每件 12 元。"


def test_math_text_generator_plan_is_truncated_to_the_forced_count(tmp_path) -> None:
    from src.cli import generate_one
    from src.sampler import sample_params

    params = sample_params(
        grade=8,
        seed=23,
        content_type="純文字",
        sub_question_count=4,
    )
    question = generate_one(
        config=_config(tmp_path),
        client=_MathTextClient(plan_count=6),
        curriculum=[],
        performance={},
        intro_text="",
        grade_content={},
        params=params,
        question_id="math_group_truncate",
        skip_verify=True,
        sub_client_factory=_MathSubQuestionClient,
    )

    assert len(question.subquestions) == 4
    assert [sub.出題概念 for sub in question.subquestions] == [
        "概念1",
        "概念2",
        "概念3",
        "概念4",
    ]


def test_math_text_generator_plan_is_padded_to_the_forced_count(tmp_path) -> None:
    from src.cli import generate_one
    from src.sampler import sample_params

    params = sample_params(
        grade=8,
        seed=23,
        content_type="純文字",
        sub_question_count=4,
    )
    question = generate_one(
        config=_config(tmp_path),
        client=_MathTextClient(plan_count=2),
        curriculum=[],
        performance={},
        intro_text="",
        grade_content={},
        params=params,
        question_id="math_group_pad",
        skip_verify=True,
        sub_client_factory=_MathSubQuestionClient,
    )

    assert len(question.subquestions) == 4
    assert [sub.出題概念 for sub in question.subquestions] == [
        "概念1",
        "概念2",
        "",
        "",
    ]


def test_math_without_sub_question_count_never_enters_the_shared_core(
    tmp_path,
    monkeypatch,
) -> None:
    import src.cli as math_cli
    from src.cli import generate_one
    from src.sampler import sample_params

    def fail_if_called(*args, **kwargs):
        raise AssertionError("flat math generation must not enter the shared core")

    monkeypatch.setattr(math_cli, "generate_one_core", fail_if_called)
    params = sample_params(grade=8, seed=23, content_type="純文字")
    question = generate_one(
        config=_config(tmp_path),
        client=_MathFlatClient(),
        curriculum=[],
        performance={},
        intro_text="",
        grade_content={},
        params=params,
        question_id="math_flat",
        skip_verify=True,
    )

    assert question.題目 == ["若 x=2，求 3x。"]
    assert question.subquestions == []


def test_math_flat_path_runs_when_drawn_題組題_but_no_sub_question_count(
    tmp_path,
    monkeypatch,
) -> None:
    """The opt-in boundary is sub_question_count, not the drawn 題型種類. A drawn 題組題 alone
    does not produce a 題組 — this is deliberate and leaves the drawn-題組題 half of the schema
    contradiction open (filed as a follow-up issue)."""
    import src.cli as math_cli
    from src.cli import generate_one
    from src.sampler import sample_params

    def fail_if_called(*args, **kwargs):
        raise AssertionError("flat math generation must not enter the shared core")

    monkeypatch.setattr(math_cli, "generate_one_core", fail_if_called)
    params = sample_params(
        grade=8,
        seed=0,
        content_type="純文字",
        sub_question_count=None,
    )

    assert params.sub_question_count is None
    assert params.題型種類.value == "題組題"
    question = generate_one(
        config=_config(tmp_path),
        client=_MathFlatClient(),
        curriculum=[],
        performance={},
        intro_text="",
        grade_content={},
        params=params,
        question_id="math_flat_drawn_group",
        skip_verify=True,
    )

    assert question.subquestions == []


def test_math_group_prompt_preview_uses_the_text_generator_prompt(tmp_path) -> None:
    from src.cli import build_generation_prompts
    from src.sampler import sample_params

    params = sample_params(
        grade=8,
        seed=23,
        content_type="純文字",
        sub_question_count=4,
    )

    system_prompt, user_prompt, images = build_generation_prompts(
        _config(tmp_path),
        params,
    )

    assert images == []
    assert "核心問題" in system_prompt
    assert "小題數量" in user_prompt
    assert "4" in user_prompt
