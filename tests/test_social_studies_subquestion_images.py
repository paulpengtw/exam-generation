"""社會領域 小題 圖片 的 pipeline 測試 —— 一律走真正的 子題產生器 階段（#321）。

Seam：`generate_one` 一律帶 `sub_client_factory`，所以 `generation_core` 的
embedded-小題 捷徑（`sub_client_factory is None` 且 `client is not None`
且 client 不是 `LLMClient`）不會被吃到。每一小題都是 子題產生器 自己寫出來的，
而不是從 文本生成器 的罐頭輸出直接解析——這正是這批測試原本的盲點：小題圖片契約
整段從 子題產生器 prompt 消失，這些測試卻照樣綠燈。

因此這裡的 子題產生器 替身是「忠實模型」：只有在自己收到的 prompt 真的要求時
才輸出小題層級 `chart_spec`。判斷依據是 prompt 的語意內容，不是任何為測試而設的
記號；四個訊號缺一不可（見 `_demands_own_chart_spec`）：輸出結構要有放圖的欄位、
規則書要說出「視覺類文本素材類型 → 本小題自帶 chart_spec」、本小題的 各小題配置
行要寫著需要圖片的 題目內容類型、而且這條規則要真的隨這一小題送出。少了任何一項，
真實模型都沒有理由畫圖，替身也就不畫。`image_generation_mode` 刻意不列為訊號——
它只決定「怎麼渲染」，不能單獨要求圖片。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from server.config import ServerConfig
from server.generate.marshalling import question_to_event as _question_to_event
from src.config import Config
from src.social_studies.cli import generate_one
from src.social_studies.sampler import sample_params

# 需要小題自帶 chart_spec 的 題目內容類型。
_IMAGE_CONTENT_TYPES = ("含圖片", "graphs/charts/tables")
_ALL_CONTENT_TYPES = (*_IMAGE_CONTENT_TYPES, "純文字")

_CORE_QUESTION = "都市更新如何影響居民生活？"
_PASSAGE = "某市正在推動都市更新，居民對公共設施與租金變化有不同看法。"

# 以空行切開的段落——prompt 的規則就是寫在這種段落裡。
_PARAGRAPH_SPLIT = re.compile(r"\n[ \t]*\n")
_JSON_FENCE = re.compile(r"```json\n(.*?)```", re.DOTALL)


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


def _output_schema_fields(system_prompt: str) -> set[str]:
    """子題產生器 system prompt 交代的輸出結構有哪些欄位。

    讀第一個能解析成 JSON 物件的 ```json 區塊——那就是「輸出必須是合法 JSON
    物件，格式如下」的骨架。模型只會填骨架上有的欄位，所以骨架沒有 `chart_spec`
    就等於沒有地方放這張圖。這裡看的是結構而不是字串出現與否：`chart_spec` 在
    別處被順帶提到，不代表輸出結構收得下它。
    """
    for block in _JSON_FENCE.findall(system_prompt):
        try:
            parsed = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return set(parsed)
    return set()


def _states_own_image_rule(prompt: str) -> bool:
    """prompt 是否真的說出「視覺類 文本素材類型 的小題要自帶 chart_spec」這條規則。

    忠實模型的讀法：規則必須把「需要圖片的 文本素材類型」與 `chart_spec` 綁在同一
    個段落裡，模型才知道那個欄位該在什麼條件下填。只比對這個語意連結，不比對逐字
    文案——規則怎麼改寫都行，整段被拿掉才算失去這個訊號。
    """
    return any(
        "chart_spec" in block and any(ct in block for ct in _IMAGE_CONTENT_TYPES)
        for block in _PARAGRAPH_SPLIT.split(prompt)
    )


def _demands_own_chart_spec(system_prompt: str, user_prompt: str, 序號: int) -> bool:
    """用「忠實模型」的讀法判斷這一小題是否被要求自帶 chart_spec。

    四個語意訊號缺一不可：

    1. 輸出結構提供 `chart_spec` 欄位——模型才有地方放這張圖。
    2. 規則書（system prompt）說出視覺類 文本素材類型 與 `chart_spec` 的關係——
       模型才知道這個欄位何時該填。
    3. 這一小題自己的 各小題配置 行寫的 題目內容類型 屬於需要圖片的類型——
       這是「這一題要圖」的判準。
    4. 這條規則確實隨這一小題的 user prompt 送出（各小題配置 的 小題圖片規則）——
       子題產生器 是一小題一次呼叫，規則沒跟著這一次送出就等於沒對它下過指示。
    """
    return (
        "chart_spec" in _output_schema_fields(system_prompt)
        and _states_own_image_rule(system_prompt)
        and _stated_content_type(user_prompt, 序號) in _IMAGE_CONTENT_TYPES
        and _states_own_image_rule(user_prompt)
    )


class _TextGeneratorFake:
    """文本生成器 替身，同時兼任小題圖片的圖片端點。

    `_render_subquestion_images` 把這個 client 直接當 `llm_client` 交給
    `render_image`，所以小題圖片是打在這裡的 `generate_image` 上。
    這裡只交出 文本 與 小題 規劃（序號 / 題型 / 出題概念），完整小題必須由
    子題產生器 寫出來。
    """

    def __init__(self, sub_question_count: int) -> None:
        self.sub_question_count = sub_question_count
        self.image_calls: list[str] = []

    def get_observer(self):
        return None

    def generate_json(self, _system: str, _user: str, **_kwargs) -> dict:
        return {
            "核心問題": _CORE_QUESTION,
            "文本": _PASSAGE,
            "取材來源": ["測試資料"],
            "subquestions": [
                {"序號": i, "題型": "選擇題", "出題概念": f"判讀都市更新示意圖{i}"}
                for i in range(1, self.sub_question_count + 1)
            ],
        }

    def generate_image(self, _prompt: str, output_path: str | Path) -> str:
        self.image_calls.append(Path(output_path).name)
        Path(output_path).write_bytes(b"subquestion-png")
        return str(output_path)


class _TopLevelRepairTextGeneratorFake:
    """文本生成器 替身，兼任 題組頂層 chart_spec 修補與圖片端點。

    分辨兩種呼叫的依據是語意的：修補呼叫會把已經產生好的草稿題組（含這裡自己
    寫出的 核心問題）交回來看，文本生成器 呼叫則還沒有 核心問題 可看。
    """

    def __init__(self) -> None:
        self.generate_json_calls = 0

    def get_observer(self):
        return None

    def generate_json(self, _system: str, user: str, **_kwargs) -> dict:
        self.generate_json_calls += 1
        if _CORE_QUESTION in user:
            # 收到草稿題組 → 這是 題組頂層 chart_spec 的修補呼叫。
            return {
                "chart_spec": {
                    "render_mode": "html",
                    "title": "都市更新公共設施示意圖",
                    "description": "呈現更新前後街區、公共設施增加與租金變化資訊。",
                    "data": {"更新前": "老舊住宅", "更新後": "公園、捷運站、租金上升"},
                }
            }
        return {
            "核心問題": _CORE_QUESTION,
            "文本": _PASSAGE,
            "取材來源": ["測試資料"],
            "subquestions": [
                {"序號": 1, "題型": "選擇題", "出題概念": "解析都市更新的影響"},
            ],
        }

    def generate_image(self, _prompt: str, output_path: str | Path) -> str:
        Path(output_path).write_bytes(b"parent-png")
        return str(output_path)


class _FaithfulSubGeneratorFake:
    """忠實遵守 prompt 的 子題產生器 替身。

    只在自己的 prompt 真的要求時才輸出小題層級 `chart_spec`，並把 prompt 上
    寫的 題目內容類型 照抄回來。若 子題產生器 prompt 沒帶小題圖片契約，這個
    替身就不會產出任何圖片——測試因此會紅。
    """

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
        out: dict = {
            "序號": 序號,
            "題型": "選擇題",
            "題目": f"根據圖{序號}，居民最可能關注哪一項變化？",
            "答案": "A",
            "答案解析": "圖中標示公共設施增加。",
            "出題概念": f"判讀都市更新示意圖{序號}",
            "評分規準": [],
        }
        stated_type = _stated_content_type(user, 序號)
        if "題目內容類型" in system and stated_type:
            out["題目內容類型"] = stated_type
        if _demands_own_chart_spec(system, user, 序號):
            out["chart_spec"] = {
                "render_mode": "html",
                "title": "都市更新前後比較圖",
                "description": "左側為更新前街區，右側為更新後公共設施增加的街區。",
                "data": {"更新前": "老舊住宅", "更新後": "公園與捷運站"},
            }
        return out


def _config(tmp_path: Path, slot_count: int) -> Config:
    return Config(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        subgen_max_concurrency=slot_count,
        subgen_retries=0,  # 不讓重試掩蓋替身模型的行為
    )


def test_social_studies_subquestion_chart_spec_renders_png(tmp_path: Path) -> None:
    """含圖片 小題：per-小題 圖片生成模式 勝過請求層級，並掛上該小題的 PNG。

    同時釘住「只有這一小題要圖」：圖片端點只被打一次（第1小題），未做 各小題配置
    的兄弟小題（第2、3小題）不得產生任何圖片。
    """
    params = sample_params(
        seed=1,
        content_type="純文字",  # 題組頂層純文字，排除 題組頂層 chart_spec 修補的干擾
        sub_question_count=3,
        subquestion_configs=[
            {
                "content_type": "含圖片",
                "image_generation_mode": "gpt_image",
                "instruction": "請聚焦在都市更新前後比較",
            },
        ],
    )

    text_client = _TextGeneratorFake(3)
    question = generate_one(
        config=_config(tmp_path, 3),
        client=text_client,
        params=params,
        question_id="ss_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="html",
        # 有 factory 才會走真正的 子題產生器 階段
        sub_client_factory=_FaithfulSubGeneratorFake,
    )

    assert not isinstance(question, str)
    assert question.subquestions[0].圖片 == "ss_test_sq1.png"
    assert question.subquestions[0].image_generation_mode == "gpt_image"
    assert question.subquestions[0].出題指示 == "請聚焦在都市更新前後比較"
    assert (tmp_path / "ss_test_sq1.png").read_bytes() == b"subquestion-png"

    # 圖片端點恰好被打一次，而且是為第1小題打的。
    assert text_client.image_calls == ["ss_test_sq1.png"], (
        f"圖片端點的呼叫不只第1小題：{text_client.image_calls}"
    )
    # 未做 各小題配置 的兄弟小題（純文字）不得帶 chart_spec 或圖片。
    for sub in question.subquestions[1:]:
        assert sub.chart_spec is None, f"第{sub.序號}小題不應帶 chart_spec"
        assert sub.圖片 is None, f"第{sub.序號}小題不應帶圖片"
    assert sorted(p.name for p in tmp_path.glob("*.png")) == ["ss_test_sq1.png"]


def test_global_image_content_type_repairs_and_renders_parent_png(tmp_path: Path) -> None:
    """題組頂層 含圖片 但 文本生成器 沒給 chart_spec 時，修補一次並渲染題組 PNG。"""
    params = sample_params(seed=1, content_type="含圖片")
    client = _TopLevelRepairTextGeneratorFake()

    question = generate_one(
        config=_config(tmp_path, 1),
        client=client,
        params=params,
        question_id="ss_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="gpt_image",
        sub_client_factory=_FaithfulSubGeneratorFake,
    )

    assert not isinstance(question, str)
    # 文本生成器 一次 + 題組頂層 chart_spec 修補一次；小題是打在 sub client 上的。
    assert client.generate_json_calls == 2
    assert question.chart_spec is not None
    assert question.圖片 == "ss_test.png"
    assert (tmp_path / "ss_test.png").read_bytes() == b"parent-png"

    payload = _question_to_event(
        question,
        ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
    )
    # 用 .get：欄位是 exclude_none 序列化的，缺圖時整個鍵會不見——直接索引只會
    # 得到 KeyError，讀不出「圖片沒掛上」這件事。
    assert payload.get("圖片") == "ss_test.png"
    assert payload.get("image_base64") == "cGFyZW50LXBuZw=="


def test_social_studies_subquestion_inherits_request_image_mode(tmp_path: Path) -> None:
    """per-小題 圖片生成模式 留空時，承襲請求層級的 gpt_image。

    請求層級就是 gpt_image，所以任何一個兄弟小題若被誤判為需要圖片，都會直接
    打在圖片端點上——這裡因此也是「圖片端點只被打一次」最靈敏的觀測點。
    """
    params = sample_params(
        seed=1,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "含圖片"},
        ],
    )

    text_client = _TextGeneratorFake(3)
    question = generate_one(
        config=_config(tmp_path, 3),
        client=text_client,
        params=params,
        question_id="ss_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="gpt_image",
        sub_client_factory=_FaithfulSubGeneratorFake,
    )

    assert not isinstance(question, str)
    assert question.subquestions[0].圖片 == "ss_test_sq1.png"
    assert question.subquestions[0].image_generation_mode == "gpt_image"
    assert (tmp_path / "ss_test_sq1.png").read_bytes() == b"subquestion-png"

    # 圖片端點恰好被打一次，而且是為做了 各小題配置 的第1小題打的。
    assert text_client.image_calls == ["ss_test_sq1.png"], (
        f"圖片端點的呼叫不只第1小題：{text_client.image_calls}"
    )


def test_subgen_subquestion_png_embedded_in_sse_payload(tmp_path: Path) -> None:
    """子題產生器 產出的小題 PNG 會被嵌進 SSE payload 的 subquestions[*]。

    名稱刻意與 tests/server/test_marshalling.py 的同名純序列化測試區隔，
    `pytest -k` 才選得到其中一個。
    """
    params = sample_params(
        seed=1,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
        ],
    )
    question = generate_one(
        config=_config(tmp_path, 3),
        client=_TextGeneratorFake(3),
        params=params,
        question_id="ss_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="html",
        sub_client_factory=_FaithfulSubGeneratorFake,
    )
    assert not isinstance(question, str)

    payload = _question_to_event(
        question,
        ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
    )

    assert payload["subquestions"][0].get("圖片") == "ss_test_sq1.png"
    assert payload["subquestions"][0].get("image_base64") == "c3VicXVlc3Rpb24tcG5n"
