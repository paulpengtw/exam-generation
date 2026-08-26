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


def test_sample_params_derives_count_for_drawn_題組題_without_count() -> None:
    from src.sampler import sample_params

    params = sample_params(
        grade=8,
        seed=1,
        content_type="純文字",
        sub_question_count=None,
    )

    assert params.題型種類.value == "題組題"
    assert params.sub_question_count is not None
    assert 3 <= params.sub_question_count <= 7


def test_sample_params_derives_count_for_explicit_題組題_without_count() -> None:
    from src.sampler import sample_params
    from src.schemas import QuestionSetType

    params = sample_params(
        grade=8,
        seed=0,
        set_type=QuestionSetType("題組題"),
        content_type="純文字",
        sub_question_count=None,
    )

    assert params.sub_question_count is not None
    assert 3 <= params.sub_question_count <= 7


def test_sample_params_preserves_single_question_snapshot_without_count() -> None:
    from src.sampler import sample_params
    from src.schemas import SampledParams

    params = sample_params(
        grade=8,
        seed=8,
        content_type="純文字",
        sub_question_count=None,
    )
    expected = SampledParams(
        grade=8,
        seed=8,
        情境=["建築與藝術", "科學", "職業"],
        題型種類="單一題",
        題型="開放式建構反應題",
        數學思考=["形成", "運用", "詮釋評估"],
        學習內容=[
            {
                "編碼": "S-9-7",
                "說明": (
                    "點、直線與圓的關係：點與圓的位置關係（內部、圓上、外部）；"
                    "直線與圓的位置關係（不相交、相切、交於兩點）；"
                    "圓心與切點的連線垂直此切線（切線性質）；"
                    "圓心到弦的垂直線段（弦心距）垂直平分此弦。"
                ),
            },
            {
                "編碼": "F-8-1",
                "說明": (
                    "一次函數：透過對應關係認識函數（不要出現 \t\t\t\t\tf(x)  \t\t\t\t\t"
                    "的抽象型式）、常數函數（y=c）、一次函數（y=ax+b）。"
                ),
            },
        ],
        style="with_image",
        核心素養=["數-J-A2", "數-J-C1", "數-J-B1"],
        學習表現=[
            {
                "編碼": "f-IV-1",
                "說明": (
                    "理解常數函數和一次函數的意義，能描繪常數函數和一次函數的圖形，"
                    "並能運用到日常生活的情境解決問題。"
                ),
            },
            {
                "編碼": "s-IV-7",
                "說明": (
                    "理解畢氏定理與其逆敘述，並能應用於數學解題與日常生活的問題。"
                ),
            }
        ],
        題目內容類型="純文字",
        出題概念="",
        subject_filter=None,
        sub_question_count=None,
        text_word_limit=None,
        difficulty="medium",
    )

    assert params == expected


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
    params = sample_params(grade=8, seed=8, content_type="純文字")

    assert params.題型種類.value == "單一題"
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


def test_math_drawn_題組題_without_count_now_produces_a_real_題組(tmp_path) -> None:
    """A sampled 題組題 without an explicit count follows the shared 題組 pipeline."""
    from src.cli import generate_one
    from src.sampler import sample_params

    params = sample_params(
        grade=8,
        seed=1,
        content_type="純文字",
        sub_question_count=None,
    )
    sub_client_calls = 0

    def sub_client_factory():
        nonlocal sub_client_calls
        sub_client_calls += 1
        return _MathSubQuestionClient()

    question = generate_one(
        config=_config(tmp_path),
        client=_MathTextClient(plan_count=4),
        curriculum=[],
        performance={},
        intro_text="",
        grade_content={},
        params=params,
        question_id="math_flat_drawn_group",
        skip_verify=True,
        sub_client_factory=sub_client_factory,
    )

    assert sub_client_calls > 0
    assert question.subquestions
    assert len(question.subquestions) == params.sub_question_count
    assert question.題型種類.value == "題組題"


def test_math_no_題組題_item_has_empty_subquestions(tmp_path) -> None:
    from src.cli import generate_one
    from src.sampler import sample_params

    drawn_types = set()
    for seed in range(12):
        params = sample_params(
            grade=8,
            seed=seed,
            content_type="純文字",
            sub_question_count=None,
        )
        drawn_types.add(params.題型種類.value)
        if params.題型種類.value == "題組題":
            client = _MathTextClient(plan_count=params.sub_question_count or 4)
            sub_client_factory = _MathSubQuestionClient
        else:
            client = _MathFlatClient()
            sub_client_factory = None

        item = generate_one(
            config=_config(tmp_path),
            client=client,
            curriculum=[],
            performance={},
            intro_text="",
            grade_content={},
            params=params,
            question_id=f"math_seed_{seed}",
            skip_verify=True,
            sub_client_factory=sub_client_factory,
        )

        assert not (
            item.題型種類.value == "題組題" and item.subquestions == []
        ), f"seed {seed} produced an empty 題組"

    assert drawn_types == {"單一題", "題組題"}


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
