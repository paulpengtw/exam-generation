"""#320 — 小題 缺少必要的 chart_spec 時，補上一次 小題層級 的修補請求（社會領域）。

即使 子題產生器 的 prompt 已經帶著 #319 的小題圖片契約，模型仍可能漏掉某一道
小題自己的 `chart_spec`。當那一道小題的 各小題配置 要求圖片
（`含圖片` / `graphs/charts/tables`）時，必須像 題組頂層 的既有修補一樣，
向模型追問一次缺少的 `chart_spec`，圖片才會被渲染、payload 才會送到圖片端點。

Seam：社會領域 `generate_one` 一律帶 `sub_client_factory`，強制走真正的
子題產生器 階段（不吃 generation_core 的 embedded-小題 捷徑）。預設的 子題產生器
替身故意無視圖片指示、永不輸出 `chart_spec`，所以圖片只可能來自修補；另有依契約
自備 `chart_spec` 的替身與自報 `序號` 錯位的替身，各自驗修補「不該出手」的情形。

`題目內容類型`（各小題配置）決定「是否需要圖片」；`image_generation_mode`
只決定「怎麼渲染」，不能單獨觸發修補。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from src.config import Config
from src.social_studies.cli import generate_one
from src.social_studies.context_builder import SUBQUESTION_IMAGE_RULE
from src.social_studies.sampler import sample_params

_SLOT_COUNT = 3
_REPAIR_PNG_BYTES = b"repaired-sq-image-endpoint-png"

# 子題產生器 替身寫進小題的作答內容。修補請求的 payload 不得夾帶這些字串，
# 值刻意寫得夠特別，避免斷言誤中 文本 或 prompt 樣板裡的其他字。
_SUB_ANSWER = "(B) 沿岸聚落改採高架建築"
_SUB_ANSWER_RATIONALE = "整治後行水區退縮，唯有高架建築能同時保留居住與滯洪"
_SUB_RUBRIC_TEXT = "能指出整治前後行水區範圍差異者給滿分"
_SUB_DISTRACTOR_TEXT = "誤以為堤防加高即可完全免除淹水風險"

# 文本生成器 替身產出的 題組共用文本；修補請求必須帶著它。
_SHARED_文本 = "某流域近十年進行河川整治，沿岸聚落的土地利用與防洪風險同時改變。"


def _repair_target_序號(user_prompt: str) -> int | None:
    """修補請求指名的那一道小題；題組頂層的修補請求不指名小題，回傳 None。

    per-小題 的修補請求一定會寫出「第N小題」（見 小題修補 的 user 樣板），
    題組頂層 的則只談整個題組，因此這個回傳值就是「這是不是一次 per-小題 修補」。
    """
    hits = [n for n in range(1, _SLOT_COUNT + 1) if f"第{n}小題" in user_prompt]
    assert len(hits) <= 1, f"修補請求同時指到多道小題：{hits}"
    return hits[0] if hits else None


def _repaired_chart_spec(序號: int | None) -> dict:
    """模型在修補請求中回傳的 chart_spec（值由測試自己決定，便於驗證是否被採用）。"""
    對象 = f"第{序號}小題" if 序號 is not None else "題組頂層"
    return {
        "render_mode": "html",
        "title": f"{對象}補圖：河川整治前後土地利用對照",
        "description": "圖中才有的整治前後土地利用差異，是作答的必要資訊。",
        "data": {"整治前": "易淹水農地", "整治後": "堤防與河濱綠地"},
    }


def _repair_supplies_chart_spec(_system: str, user: str) -> dict:
    """配合修補的模型：為請求指名的那一道小題（或題組頂層）補上 chart_spec。"""
    return {"chart_spec": _repaired_chart_spec(_repair_target_序號(user))}


def _小題修補請求(text_client: _TextGeneratorFake) -> list[str]:
    """只挑出指名某一道小題的修補請求，排除合法的 題組頂層 修補。"""
    return [
        user
        for _system, user in text_client.repair_prompts
        if _repair_target_序號(user) is not None
    ]


def _defiant_題目(序號: int) -> str:
    """替身小題的題目。刻意不含「第N小題」字樣，這樣 `_repair_target_序號`
    才能單靠 prompt 樣板判斷一次修補是 per-小題 還是 題組頂層。"""
    return f"小題{序號}的題目（含選項）"


def _repair_raises(_system: str, _user: str) -> dict:
    raise RuntimeError("圖片規格修補端點暫時無法使用")


def _repair_returns_no_spec(_system: str, user: str) -> dict:
    """模型回應了，但沒有給出任何可用的 chart_spec。"""
    _repair_target_序號(user)
    return {"說明": "本小題不需要額外圖片"}


class _DefiantSubGeneratorFake:
    """無視小題圖片契約的 子題產生器 替身：永不輸出小題層級 `chart_spec`。

    也刻意不回填 `題目內容類型`，所以「這一道小題是否需要圖片」只能由
    各小題配置 判斷，不能靠模型自己的回答。
    """

    def set_observer(self, _observer) -> None:
        pass

    def generate_json(
        self,
        _system: str,
        _user: str,
        *,
        agent_override: str,
        **_kwargs,
    ) -> dict:
        序號 = int(agent_override.split("#", 1)[1])
        return {
            "序號": 序號,
            "題型": "選擇題",
            "題目": _defiant_題目(序號),
            "答案": _SUB_ANSWER,
            "答案解析": _SUB_ANSWER_RATIONALE,
            "出題概念": f"概念{序號}",
            "評分規準": [
                {"code": "A", "規準說明": _SUB_RUBRIC_TEXT, "學生作答實例": []},
            ],
            "誘答分析": {"C": _SUB_DISTRACTOR_TEXT},
        }


_MODEL_OWN_CHART_SPEC = {
    "render_mode": "html",
    "title": "子題產生器自備圖：整治後河濱分區使用示意",
    "description": "圖中才有的分區使用範圍，是本小題作答的必要資訊。",
    "data": {"堤內": "住宅與商業", "堤外": "滯洪與綠地"},
}


class _ObedientSubGeneratorFake(_DefiantSubGeneratorFake):
    """遵守 #319 小題圖片契約的 子題產生器 替身。

    prompt 附上 小題圖片規則 時（即該小題被要求自備圖片），就自己輸出 chart_spec。
    判斷依據是 prompt 本身，而不是測試寫死的 序號——這樣才真的在驗
    「prompt 端要求」與「修補端判定」是同一個判準。
    """

    def generate_json(
        self,
        system: str,
        user: str,
        *,
        agent_override: str,
        **kwargs,
    ) -> dict:
        sq = super().generate_json(
            system, user, agent_override=agent_override, **kwargs,
        )
        if SUBQUESTION_IMAGE_RULE in user:
            sq["chart_spec"] = dict(_MODEL_OWN_CHART_SPEC)
        return sq


# 子題產生器 把 序號 寫錯時的錯位對照：PLAN 索引 → 模型自報的 序號。
_SHIFTED_序號 = {1: 2, 2: 1, 3: 3}


def _slot_題目(plan_index: int) -> str:
    """標明這一道小題是由哪一格 各小題配置 產生的（PLAN 索引，非模型自報的 序號）。"""
    return f"由第{plan_index}格各小題配置產生的小題題目"


class _ShiftedSerialSubGeneratorFake(_DefiantSubGeneratorFake):
    """自報 序號 錯位的 子題產生器 替身（模型把兩道小題的 序號 對調）。

    小題內容仍標明它是由哪一格 各小題配置 產生的，
    用來驗證圖片需求跟著「建構時所用的那一格配置」走，而不是跟著模型自報的 序號 走。
    """

    def generate_json(
        self,
        system: str,
        user: str,
        *,
        agent_override: str,
        **kwargs,
    ) -> dict:
        plan_index = int(agent_override.split("#", 1)[1])
        sq = super().generate_json(
            system, user, agent_override=agent_override, **kwargs,
        )
        sq["序號"] = _SHIFTED_序號[plan_index]
        sq["題目"] = _slot_題目(plan_index)
        sq["出題概念"] = f"概念{plan_index}"
        return sq


class _TextGeneratorFake:
    """文本生成器 替身，同時兼任 小題 chart_spec 修補窗口與圖片端點。

    第一次 `generate_json` 是 文本生成器，之後的每一次都是圖片規格修補請求。
    題組頂層 預設為 純文字，所以題組頂層修補不會發生，修補請求都是小題層級的；
    把 題組頂層 改成 含圖片 的測試請用 `_小題修補請求` 挑出小題層級的那些。
    `_render_subquestion_images` 把這個 client 當成 `render_image` 的
    `llm_client`，所以小題圖片是打在這裡的 `generate_image` 上。
    """

    def __init__(self, repair: Callable[[str, str], dict]) -> None:
        self._repair = repair
        self._text_call_pending = True
        self.repair_prompts: list[tuple[str, str]] = []
        self.image_calls: list[str] = []

    def get_observer(self):
        return None

    def generate_json(self, system: str, user: str, **_kwargs) -> dict:
        if self._text_call_pending:
            self._text_call_pending = False
            return {
                "核心問題": "河川整治如何改變沿岸聚落的生活？",
                "文本": _SHARED_文本,
                "取材來源": ["社會領域測試素材"],
                "subquestions": [
                    {"序號": i, "題型": "選擇題", "出題概念": f"概念{i}"}
                    for i in range(1, _SLOT_COUNT + 1)
                ],
            }
        self.repair_prompts.append((system, user))
        return self._repair(system, user)

    def generate_image(self, _prompt: str, output_path: str | Path) -> str:
        self.image_calls.append(Path(output_path).name)
        Path(output_path).write_bytes(_REPAIR_PNG_BYTES)
        return str(output_path)


def _generate(
    tmp_path: Path,
    question_id: str,
    subquestion_configs: list[dict],
    *,
    repair: Callable[[str, str], dict] = _repair_supplies_chart_spec,
    image_generation_mode: str = "html",
    sub_client_factory: Callable[[], object] = _DefiantSubGeneratorFake,
    topic_content_type: str = "純文字",
) -> tuple[object, _TextGeneratorFake]:
    assert len(subquestion_configs) == _SLOT_COUNT
    config = Config(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        subgen_max_concurrency=_SLOT_COUNT,
        subgen_retries=0,  # 不讓重試掩蓋替身模型的行為
    )
    params = sample_params(
        seed=23,
        # 預設 題組頂層為純文字，排除 題組頂層 chart_spec 修補；
        # 需要重現「題組層級視覺類型」的測試才把它改成 含圖片。
        content_type=topic_content_type,
        sub_question_count=_SLOT_COUNT,
        subquestion_configs=subquestion_configs,
    )
    text_client = _TextGeneratorFake(repair)
    question = generate_one(
        config=config,
        client=text_client,
        params=params,
        question_id=question_id,
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode=image_generation_mode,
        # 有 factory 才會走真正的 子題產生器 階段
        sub_client_factory=sub_client_factory,
    )
    assert not isinstance(question, str)
    return question, text_client


def test_missing_required_小題_chart_spec_is_repaired_once_and_rendered(
    tmp_path: Path,
) -> None:
    """含圖片 小題 漏了 chart_spec：修補一次、採用回傳的 spec、圖片送到圖片端點。"""
    question, text_client = _generate(
        tmp_path,
        "ss320_repair",
        [
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
            {"content_type": "純文字"},
            {"content_type": "純文字"},
        ],
    )

    # 只有第1小題被配置圖片，所以只會有一次修補請求。
    assert len(text_client.repair_prompts) == 1, (
        f"修補次數不是一次：{len(text_client.repair_prompts)}"
    )
    system_prompt, user_prompt = text_client.repair_prompts[0]
    # 修補請求要指名這一道小題、帶出它的 題目內容類型 值，並要求 chart_spec 這個欄位。
    assert "第1小題" in user_prompt, f"修補請求未指名小題：{user_prompt!r}"
    assert "含圖片" in user_prompt, f"修補請求未帶出 題目內容類型：{user_prompt!r}"
    assert "chart_spec" in system_prompt + user_prompt, "修補請求未要求 chart_spec 欄位"

    by_序號 = {sub.序號: sub for sub in question.subquestions}
    assert len(by_序號) == _SLOT_COUNT

    # 修補回傳的 chart_spec 被採用到這一道小題身上。
    repaired = by_序號[1].chart_spec
    assert repaired is not None, "修補回傳的 chart_spec 未被採用"
    assert repaired.title == _repaired_chart_spec(1)["title"]
    assert repaired.description == _repaired_chart_spec(1)["description"]

    # 圖片被渲染並送到圖片端點，PNG 掛回這一道小題。
    assert text_client.image_calls == ["ss320_repair_sq1.png"]
    assert by_序號[1].圖片 == "ss320_repair_sq1.png"
    assert (tmp_path / "ss320_repair_sq1.png").read_bytes() == _REPAIR_PNG_BYTES

    # 未配置圖片的小題不受影響。
    for 序號 in (2, 3):
        assert by_序號[序號].chart_spec is None
        assert by_序號[序號].圖片 is None


def test_修補請求不得夾帶該小題的答案內容(tmp_path: Path) -> None:
    """修補請求只是要一張素材圖，payload 不得夾帶 答案 / 答案解析 / 評分規準 / 誘答分析。

    修補的 system prompt 自己就寫著「不要加入答案提示」，卻把整道小題（含答案）
    序列化送進 user prompt，等於一邊禁止一邊餵。圖片必須是作答的必要條件，
    模型看得到答案就會照答案回推圖片，反而讓圖片變成答案的插圖。
    """
    _question, text_client = _generate(
        tmp_path,
        "ss320_answer_leak",
        [
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
            {"content_type": "純文字"},
            {"content_type": "純文字"},
        ],
    )

    assert len(text_client.repair_prompts) == 1, (
        f"修補次數不是一次：{len(text_client.repair_prompts)}"
    )
    _system, user_prompt = text_client.repair_prompts[0]

    for 洩漏內容, 欄位 in (
        (_SUB_ANSWER, "答案"),
        (_SUB_ANSWER_RATIONALE, "答案解析"),
        (_SUB_RUBRIC_TEXT, "評分規準"),
        (_SUB_DISTRACTOR_TEXT, "誘答分析"),
    ):
        assert 洩漏內容 not in user_prompt, (
            f"修補請求夾帶了第1小題的{欄位}：{洩漏內容!r}"
        )
    assert "答案" not in user_prompt, f"修補請求仍帶著答案欄位：{user_prompt!r}"

    # 修補真正需要的資訊必須留著，否則模型無從設計這一小題專屬的素材。
    assert _defiant_題目(1) in user_prompt, "修補請求少了小題題目"
    assert "概念1" in user_prompt, "修補請求少了小題的出題概念"
    assert _SHARED_文本 in user_prompt, "修補請求少了題組共用文本"


def test_每個需要圖片的小題各修補一次(tmp_path: Path) -> None:
    """含圖片 與 graphs/charts/tables 兩種都會修補，且每道小題只追問一次。"""
    question, text_client = _generate(
        tmp_path,
        "ss320_both",
        [
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
            {"content_type": "純文字"},
            {"content_type": "graphs/charts/tables", "image_generation_mode": "gpt_image"},
        ],
    )

    repaired_序號 = [_repair_target_序號(user) for _system, user in text_client.repair_prompts]
    assert sorted(repaired_序號) == [1, 3], f"修補的小題不對：{repaired_序號}"

    # 每道小題各自帶出自己的 題目內容類型 值。
    prompts = {_repair_target_序號(user): user for _system, user in text_client.repair_prompts}
    assert "含圖片" in prompts[1]
    assert "graphs/charts/tables" in prompts[3]

    by_序號 = {sub.序號: sub for sub in question.subquestions}
    for 序號 in (1, 3):
        assert by_序號[序號].chart_spec is not None
        assert by_序號[序號].chart_spec.title == _repaired_chart_spec(序號)["title"]
        assert by_序號[序號].圖片 == f"ss320_both_sq{序號}.png"
    assert sorted(text_client.image_calls) == ["ss320_both_sq1.png", "ss320_both_sq3.png"]

    assert by_序號[2].chart_spec is None
    assert by_序號[2].圖片 is None


def test_子題產生器已依契約自備chart_spec時不再修補(tmp_path: Path) -> None:
    """子題產生器 依 #319 契約自備了 chart_spec：一次修補都不該發出，spec 也不得被蓋掉。

    修補是補缺口，不是覆寫。少了「已有 chart_spec 就跳過」這道關卡，
    每一道 含圖片 小題都會多打一次修補呼叫，還會把模型自己設計、與題幹相扣的
    素材換成修補回傳的版本。
    """
    question, text_client = _generate(
        tmp_path,
        "ss320_obedient",
        [
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
            {"content_type": "純文字"},
            {"content_type": "純文字"},
        ],
        sub_client_factory=_ObedientSubGeneratorFake,
    )

    by_序號 = {sub.序號: sub for sub in question.subquestions}
    own_spec = by_序號[1].chart_spec
    assert own_spec is not None, "子題產生器 自備的 chart_spec 沒有被採用"

    # 沒有缺口就沒有修補：一次都不該問。
    assert text_client.repair_prompts == [], (
        f"小題已自備 chart_spec，仍發出修補請求：{text_client.repair_prompts}"
    )

    # 模型自己的素材原封不動，沒有被修補版本換掉。
    assert own_spec.title == _MODEL_OWN_CHART_SPEC["title"], (
        f"模型自備的 chart_spec 被改寫：{own_spec.title!r}"
    )
    assert own_spec.description == _MODEL_OWN_CHART_SPEC["description"]
    assert own_spec.title != _repaired_chart_spec(1)["title"], (
        "測試前提不成立：自備與修補的 chart_spec 必須可區分"
    )

    # 圖片照樣渲染送到圖片端點，用的是模型自己的 spec。
    assert text_client.image_calls == ["ss320_obedient_sq1.png"]
    assert by_序號[1].圖片 == "ss320_obedient_sq1.png"
    for 序號 in (2, 3):
        assert by_序號[序號].chart_spec is None
        assert by_序號[序號].圖片 is None


def test_模型自報序號錯位時圖片需求仍跟著建構用的那一格配置(tmp_path: Path) -> None:
    """子題產生器 自報的 序號 錯位時，修補仍須沿用「建構這道小題時所用的那一格配置」。

    各小題配置 是在 parse 時依 PLAN 索引套用的（題型、學習內容都照那一格），
    修補若改用模型自報的 序號 去查 各小題配置，就會把甲格的題型配上乙格的圖片決定：
    被配置成 含圖片 的那一格產不出圖，反而是 純文字 的那一格被追問 chart_spec。
    """
    question, text_client = _generate(
        tmp_path,
        "ss320_shifted",
        [
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
            {"content_type": "純文字", "image_generation_mode": "gpt_image"},
            {"content_type": "純文字", "image_generation_mode": "gpt_image"},
        ],
        sub_client_factory=_ShiftedSerialSubGeneratorFake,
    )

    by_題目 = {sub.題目: sub for sub in question.subquestions}
    assert set(by_題目) == {_slot_題目(i) for i in (1, 2, 3)}, (
        f"小題內容遺失，無法辨認每道小題出自哪一格配置：{sorted(by_題目)}"
    )
    imaged = by_題目[_slot_題目(1)]  # 含圖片 那一格產生的小題
    assert imaged.序號 == _SHIFTED_序號[1], "替身沒有真的把 序號 寫錯，測試前提不成立"

    # 只追問一次，而且問的是 含圖片 那一格產生的小題。
    assert len(text_client.repair_prompts) == 1, (
        f"修補次數不是一次：{len(text_client.repair_prompts)}"
    )
    _system, user_prompt = text_client.repair_prompts[0]
    assert _slot_題目(1) in user_prompt, (
        f"修補請求問錯小題——payload 不是 含圖片 那一格產生的小題：{user_prompt!r}"
    )
    assert f"第{imaged.序號}小題" in user_prompt, "修補請求未以該小題自己的 序號 指名"

    # 圖片掛在 含圖片 那一格產生的小題身上，其餘小題不受影響。
    assert imaged.chart_spec is not None, "含圖片 那一格產生的小題沒有補到 chart_spec"
    assert imaged.圖片 == f"ss320_shifted_sq{imaged.序號}.png"
    assert text_client.image_calls == [f"ss320_shifted_sq{imaged.序號}.png"]
    for plan_index in (2, 3):
        other = by_題目[_slot_題目(plan_index)]
        assert other.chart_spec is None, (
            f"第{plan_index}格是 純文字，卻拿到 chart_spec"
        )
        assert other.圖片 is None


def test_純文字_小題_never_triggers_a_repair(tmp_path: Path) -> None:
    """純文字 小題 沒有圖片需求，不得追問 chart_spec。"""
    question, text_client = _generate(
        tmp_path,
        "ss320_text_only",
        [{"content_type": "純文字"} for _ in range(_SLOT_COUNT)],
    )

    assert text_client.repair_prompts == []
    assert text_client.image_calls == []
    assert len(question.subquestions) == _SLOT_COUNT
    for sub in question.subquestions:
        assert sub.chart_spec is None
        assert sub.圖片 is None
    assert not list(tmp_path.glob("*.png"))


def test_image_generation_mode_alone_never_triggers_a_repair(tmp_path: Path) -> None:
    """只設定 圖片生成模式 不構成圖片需求——mode 只決定渲染方式。"""
    question, text_client = _generate(
        tmp_path,
        "ss320_mode_only",
        [
            {"content_type": "純文字", "image_generation_mode": "gpt_image"}
            for _ in range(_SLOT_COUNT)
        ],
        image_generation_mode="gpt_image",
    )

    assert text_client.repair_prompts == []
    assert text_client.image_calls == []
    for sub in question.subquestions:
        assert sub.chart_spec is None
        assert sub.圖片 is None
    assert not list(tmp_path.glob("*.png"))


def test_題組含圖片但小題未指定時不得發出小題修補(tmp_path: Path) -> None:
    """題組頂層 含圖片、各小題只帶 預抽 的 學習內容 而未自報 題目內容類型：
    per-小題 的修補一次都不得發出。

    這是 UI 預設路徑（題組層級 含圖片 + 預抽 自動為每一格帶入 學習內容）。
    小題的圖片需求只能來自那一格自己明確設定的 題目內容類型，不從題組層級繼承；
    否則每個題組都會多打 N 次修補呼叫，並多出 N 張沒人要的圖。
    題組頂層 自己的 chart_spec 修補仍是合法的，因此只針對「指名某一小題」的修補斷言。
    """
    question, text_client = _generate(
        tmp_path,
        "ss320_inherit",
        [
            {"learning_content": ["歷Bb-Ⅳ-2"]},
            {"learning_content": ["歷Bb-Ⅳ-1"]},
            {"learning_content": ["歷Bb-Ⅳ-2"]},
        ],
        topic_content_type="含圖片",
    )

    小題修補 = _小題修補請求(text_client)
    assert 小題修補 == [], (
        f"小題繼承了題組層級的圖片需求，發出 {len(小題修補)} 次 per-小題 修補：{小題修補}"
    )

    # 題組頂層 的修補確實有發生，證明這個場景真的走到了視覺素材的路上。
    assert len(text_client.repair_prompts) == 1, (
        f"題組頂層修補未如預期發生：{text_client.repair_prompts}"
    )
    assert question.chart_spec is not None, "題組頂層 chart_spec 應由既有修補補上"

    # 圖片端點沒有任何 per-小題 payload，小題也沒有 chart_spec 或圖片。
    sq_image_calls = [name for name in text_client.image_calls if "_sq" in name]
    assert sq_image_calls == [], f"圖片端點收到意外的 per-小題 payload：{sq_image_calls}"
    assert len(question.subquestions) == _SLOT_COUNT
    for sub in question.subquestions:
        assert sub.chart_spec is None, f"第{sub.序號}小題不該有 chart_spec"
        assert sub.圖片 is None, f"第{sub.序號}小題不該有圖片"


def test_修補呼叫失敗時小題不帶圖片出貨且題組完成(tmp_path: Path) -> None:
    """修補呼叫拋錯：那道小題不帶圖片出貨，題組照樣完成，不得中斷。"""
    question, text_client = _generate(
        tmp_path,
        "ss320_repair_raises",
        [
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
            {"content_type": "純文字"},
            {"content_type": "純文字"},
        ],
        repair=_repair_raises,
    )

    # 只追問一次，失敗就不再重試。
    assert len(text_client.repair_prompts) == 1

    # 題組完整交付，缺圖的小題只是少了圖片。
    by_序號 = {sub.序號: sub for sub in question.subquestions}
    assert sorted(by_序號) == [1, 2, 3]
    assert by_序號[1].題目 == _defiant_題目(1)
    assert by_序號[1].chart_spec is None
    assert by_序號[1].圖片 is None
    assert text_client.image_calls == []
    assert not list(tmp_path.glob("*.png"))


def test_修補未給出可用_chart_spec_時小題不帶圖片出貨(tmp_path: Path) -> None:
    """修補回應了但沒有可用的 chart_spec：同樣降級，不掛圖也不中斷。"""
    question, text_client = _generate(
        tmp_path,
        "ss320_repair_empty",
        [
            {"content_type": "graphs/charts/tables", "image_generation_mode": "gpt_image"},
            {"content_type": "純文字"},
            {"content_type": "純文字"},
        ],
        repair=_repair_returns_no_spec,
    )

    assert len(text_client.repair_prompts) == 1

    by_序號 = {sub.序號: sub for sub in question.subquestions}
    assert sorted(by_序號) == [1, 2, 3]
    assert by_序號[1].chart_spec is None
    assert by_序號[1].圖片 is None
    assert text_client.image_calls == []
    assert not list(tmp_path.glob("*.png"))
