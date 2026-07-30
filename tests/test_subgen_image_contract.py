"""#319 — 子題產生器 prompt 必須帶著小題層級的圖片契約（含圖片 / chart_spec / GPT 生圖）。

Seam：社會領域 `generate_one` 一律帶 `sub_client_factory`，強制走真正的
子題產生器 階段（不吃 generation_core 的 embedded-小題 捷徑），所以這裡攔到的
prompt 就是正式環境送出的那一份。

`題目內容類型` 決定「是否需要圖片」（`含圖片` / `graphs/charts/tables` 需要，
`純文字` 禁止）；`image_generation_mode` 只決定「怎麼渲染」，不能單獨要求圖片
——與 文本生成器 的 小題圖片規則 一致。
"""

from __future__ import annotations

from pathlib import Path

from src.config import Config
from src.social_studies.cli import generate_one
from src.social_studies.context_builder import SUBQUESTION_IMAGE_RULE
from src.social_studies.sampler import sample_params

# 需要小題自帶 chart_spec 的 題目內容類型。
_IMAGE_CONTENT_TYPES = ("含圖片", "graphs/charts/tables")
_ALL_CONTENT_TYPES = (*_IMAGE_CONTENT_TYPES, "純文字")


def _slot_config_line(user_prompt: str, 序號: int) -> str:
    """回傳 各小題配置 中描述這一小題的那一行；找不到時回傳空字串。"""
    for line in user_prompt.splitlines():
        if f"第{序號}小題" in line:
            return line
    return ""


def _stated_content_type(user_prompt: str, 序號: int) -> str | None:
    """這一小題的配置行上寫的 題目內容類型 值。"""
    line = _slot_config_line(user_prompt, 序號)
    return next((ct for ct in _ALL_CONTENT_TYPES if ct in line), None)


def _demands_own_chart_spec(system_prompt: str, user_prompt: str, 序號: int) -> bool:
    """用「忠實模型」的讀法判斷這一小題是否被要求自帶 chart_spec。

    兩個語意訊號都必須成立：

    1. 輸出結構提供 `chart_spec` 欄位，模型才有地方放這張圖；
    2. 這一小題自己的 各小題配置 行寫的 題目內容類型 屬於需要圖片的類型。

    `image_generation_mode` 刻意不列為訊號——它只選渲染方式。
    """
    if "chart_spec" not in system_prompt and "chart_spec" not in user_prompt:
        return False
    return _stated_content_type(user_prompt, 序號) in _IMAGE_CONTENT_TYPES


class _TextGeneratorFake:
    """文本生成器 替身，同時兼任圖片端點。

    `_render_subquestion_images` 把這個 client 直接交給 `render_image`
    當 `llm_client`，所以小題圖片是打在這裡的 `generate_image` 上。
    """

    def __init__(self, sub_question_count: int) -> None:
        self.sub_question_count = sub_question_count
        self.image_calls: list[str] = []

    def get_observer(self):
        return None

    def generate_json(self, _system: str, _user: str, **_kwargs) -> dict:
        return {
            "核心問題": "河川整治如何改變沿岸聚落的生活？",
            "文本": "某流域近十年進行河川整治，沿岸聚落的土地利用與防洪風險同時改變。",
            "取材來源": ["社會領域測試素材"],
            "subquestions": [
                {"序號": i, "題型": "選擇題", "出題概念": f"概念{i}"}
                for i in range(1, self.sub_question_count + 1)
            ],
        }

    def generate_image(self, _prompt: str, output_path: str | Path) -> str:
        self.image_calls.append(Path(output_path).name)
        Path(output_path).write_bytes(b"sq-image-endpoint-png")
        return str(output_path)


class _FaithfulSubGeneratorFake:
    """忠實遵守 prompt 的 子題產生器 替身。

    只在自己的 prompt 真的要求時才輸出小題層級 `chart_spec`，並把 prompt 上
    寫的 題目內容類型 / image_generation_mode 值照抄回來。判斷依據是 prompt
    的語意內容（輸出結構欄位 + 本小題配置行），不是任何為測試而設的記號。
    """

    def __init__(self, captured: dict[int, tuple[str, str]]) -> None:
        self.captured = captured

    def set_observer(self, _observer) -> None:
        pass

    def generate_json(
        self,
        system: str,
        user: str,
        *,
        agent_override: str,
        **_kwargs,
    ) -> dict:
        序號 = int(agent_override.split("#", 1)[1])
        self.captured[序號] = (system, user)
        line = _slot_config_line(user, 序號)
        out: dict = {
            "序號": 序號,
            "題型": "選擇題",
            "題目": f"第{序號}小題題目（含選項）",
            "答案": "A",
            "答案解析": "解析",
            "出題概念": f"概念{序號}",
            "評分規準": [],
        }
        stated_type = _stated_content_type(user, 序號)
        if "題目內容類型" in system and stated_type:
            out["題目內容類型"] = stated_type
        if "image_generation_mode" in system and "gpt_image" in line:
            out["image_generation_mode"] = "gpt_image"
        if _demands_own_chart_spec(system, user, 序號):
            out["chart_spec"] = {
                "render_mode": "html",
                "title": f"第{序號}小題專屬素材",
                "description": "本小題作答必須讀取此素材中才有的資訊。",
                "data": {"整治前": "易淹水農地", "整治後": "堤防與河濱綠地"},
            }
        return out


def _generate(
    tmp_path: Path,
    question_id: str,
    subquestion_configs: list[dict],
    captured: dict[int, tuple[str, str]],
    *,
    image_generation_mode: str = "html",
    topic_content_type: str = "純文字",
) -> tuple[object, _TextGeneratorFake]:
    config = Config(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        subgen_max_concurrency=len(subquestion_configs),
        subgen_retries=0,  # 不讓重試掩蓋替身模型的行為
    )
    params = sample_params(
        seed=23,
        content_type=topic_content_type,
        sub_question_count=len(subquestion_configs),
        subquestion_configs=subquestion_configs,
    )
    text_client = _TextGeneratorFake(len(subquestion_configs))
    question = generate_one(
        config=config,
        client=text_client,
        params=params,
        question_id=question_id,
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode=image_generation_mode,
        # 有 factory 才會走真正的 子題產生器 階段
        sub_client_factory=lambda: _FaithfulSubGeneratorFake(captured),
    )
    assert not isinstance(question, str)
    return question, text_client


def test_子題產生器_prompt_states_小題_image_contract(tmp_path: Path) -> None:
    """含圖片 / graphs/charts/tables 的小題，prompt 必須要求該小題自帶 chart_spec。"""
    captured: dict[int, tuple[str, str]] = {}
    _generate(
        tmp_path,
        "ss319_prompt",
        [
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
            {"content_type": "純文字"},
            {"content_type": "graphs/charts/tables", "image_generation_mode": "gpt_image"},
        ],
        captured,
    )

    system_prompt, user_prompt = captured[1]

    # 輸出結構要有欄位承載小題層級的圖片契約，模型才有地方放。
    for field in ("chart_spec", "題目內容類型", "image_generation_mode"):
        assert field in system_prompt, f"子題產生器 輸出結構缺少 {field}"

    # 本小題自己的 各小題配置 行必須帶出提交的 題目內容類型 與 圖片生成模式 值。
    line = _slot_config_line(user_prompt, 1)
    assert "含圖片" in line, f"第1小題配置未帶出 題目內容類型：{line!r}"
    assert "gpt_image" in line, f"第1小題配置未帶出 image_generation_mode：{line!r}"

    # 圖片需求要寫在這一小題自己的 user prompt，不能只留在 文本生成器。
    assert "chart_spec" in user_prompt
    assert _demands_own_chart_spec(system_prompt, user_prompt, 1)

    # graphs/charts/tables 同樣是需要圖片的 題目內容類型。
    system_prompt_3, user_prompt_3 = captured[3]
    line_3 = _slot_config_line(user_prompt_3, 3)
    assert "graphs/charts/tables" in line_3, f"第3小題配置未帶出 題目內容類型：{line_3!r}"
    assert "chart_spec" in user_prompt_3
    assert _demands_own_chart_spec(system_prompt_3, user_prompt_3, 3)


def test_含圖片_小題_reaches_image_endpoint_and_attaches_png(tmp_path: Path) -> None:
    """忠實模型下，配置圖片的小題會打到圖片端點並掛上該小題的 PNG。"""
    captured: dict[int, tuple[str, str]] = {}
    question, text_client = _generate(
        tmp_path,
        "ss319_e2e",
        [
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
            {"content_type": "純文字"},
            {"content_type": "graphs/charts/tables", "image_generation_mode": "gpt_image"},
        ],
        captured,
    )

    assert sorted(text_client.image_calls) == ["ss319_e2e_sq1.png", "ss319_e2e_sq3.png"]

    by_序號 = {sub.序號: sub for sub in question.subquestions}
    assert by_序號[1].題目內容類型 == "含圖片"
    assert by_序號[1].chart_spec is not None
    assert by_序號[1].圖片 == "ss319_e2e_sq1.png"
    assert (tmp_path / "ss319_e2e_sq1.png").read_bytes() == b"sq-image-endpoint-png"

    assert by_序號[3].題目內容類型 == "graphs/charts/tables"
    assert by_序號[3].圖片 == "ss319_e2e_sq3.png"

    # 未配置圖片的小題兩者皆無。
    assert by_序號[2].chart_spec is None
    assert by_序號[2].圖片 is None


def test_image_generation_mode_alone_does_not_require_a_小題_image(tmp_path: Path) -> None:
    """純文字 + GPT 生圖：圖片生成模式只決定渲染方式，不能單獨要求圖片。

    與 文本生成器 的 小題圖片規則 一致——mode 不是圖片需求。
    """
    captured: dict[int, tuple[str, str]] = {}
    question, text_client = _generate(
        tmp_path,
        "ss319_mode_only",
        [
            {"content_type": "純文字", "image_generation_mode": "gpt_image"},
            {"content_type": "純文字", "image_generation_mode": "gpt_image"},
            {"content_type": "純文字", "image_generation_mode": "gpt_image"},
        ],
        captured,
        image_generation_mode="gpt_image",
    )

    # prompt 端：本小題配置仍是 純文字，且不得被要求輸出 chart_spec。
    system_prompt, user_prompt = captured[1]
    line = _slot_config_line(user_prompt, 1)
    assert "純文字" in line, f"第1小題配置未帶出 題目內容類型：{line!r}"
    assert not any(ct in line for ct in _IMAGE_CONTENT_TYPES), (
        f"純文字 小題被標成需要圖片：{line!r}"
    )
    assert "gpt_image" in line, f"第1小題配置未帶出 image_generation_mode：{line!r}"
    assert not _demands_own_chart_spec(system_prompt, user_prompt, 1)
    # 確認 user prompt 不含小題圖片規則——此斷言能捕捉「誤對 純文字 slot 附加規則」
    # 的實作錯誤，彌補 _demands_own_chart_spec 只看配置行而漏判此行的空白。
    assert SUBQUESTION_IMAGE_RULE not in user_prompt, (
        "純文字 小題的 user prompt 不得含有 小題圖片規則"
    )

    # 行為端：沒有圖片端點呼叫，也沒有任何小題圖片。
    assert text_client.image_calls == []
    for sub in question.subquestions:
        assert sub.chart_spec is None
        assert sub.圖片 is None
    assert not list(tmp_path.glob("*.png"))


def test_題組含圖片_但小題未指定_不得繼承圖片需求(tmp_path: Path) -> None:
    """題組頂層 題目內容類型=含圖片，各小題未明確設定 content_type 時，
    子題產生器 prompt 不得向這些小題施加圖片需求。

    預抽（釘選）場景：學習內容已先行抽出並掛到各小題配置，
    但小題本身的 content_type 未明確指定 → 繼承的含圖片不應傳入子題 prompt。

    驗收標準（per issue #319）：
    - 各小題 prompt 的配置行不得出現需要圖片的 文本素材類型（含圖片 / graphs/charts/tables）。
    - 各小題 prompt 不得附加 小題圖片規則（即不要求該小題輸出 chart_spec）。
    - 圖片端點不收到任何 per-小題 payload（無 *_sqN.png 呼叫）。
    - 所有小題的 chart_spec 與 圖片 均為 None。
    """
    # 各小題只帶 learning_content（預抽結果），不帶 content_type——真實 UI 預設路徑。
    captured: dict[int, tuple[str, str]] = {}
    question, text_client = _generate(
        tmp_path,
        "ss319_inherit",
        [
            {"learning_content": ["歷Bb-Ⅳ-2"]},
            {"learning_content": ["歷Bb-Ⅳ-1"]},
            {"learning_content": ["歷Bb-Ⅳ-2"]},
        ],
        captured,
        topic_content_type="含圖片",  # 題組頂層 含圖片，重現缺陷
    )

    for 序號 in (1, 2, 3):
        system_prompt, user_prompt = captured[序號]
        config_line = _slot_config_line(user_prompt, 序號)

        # prompt 不得對這一小題聲明需要圖片的 文本素材類型。
        assert not any(ct in config_line for ct in _IMAGE_CONTENT_TYPES), (
            f"第{序號}小題配置行繼承了題組層級的圖片需求：{config_line!r}"
        )

        # prompt 不得要求這一小題自帶 chart_spec。
        assert not _demands_own_chart_spec(system_prompt, user_prompt, 序號), (
            f"第{序號}小題的 prompt 要求輸出 chart_spec，但該小題未明確設定 content_type"
        )

    # 圖片端點不得收到任何 per-小題 payload。
    sq_image_calls = [c for c in text_client.image_calls if "_sq" in c]
    assert sq_image_calls == [], (
        f"圖片端點收到意外的 per-小題 payload：{sq_image_calls}"
    )

    # 所有小題均無 chart_spec 與 圖片。
    by_序號 = {sub.序號: sub for sub in question.subquestions}
    for 序號 in (1, 2, 3):
        assert by_序號[序號].chart_spec is None, f"第{序號}小題不應帶 chart_spec"
        assert by_序號[序號].圖片 is None, f"第{序號}小題不應帶圖片"
