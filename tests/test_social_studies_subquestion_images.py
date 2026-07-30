"""Social-studies 小題-image tests: real 子題產生器 call path.

Issue #321 migration: the original version of this file returned full
subquestion data from the *文本生成器* stub, triggering the
``use_embedded_subquestions`` shortcut in generation_core and bypassing
the ``build_subquestion_system/user_prompt`` → sub-client → parse pipeline
where the #319 image-contract bug lived.

Each test now:
  1. Supplies a *text* client whose ``generate_json`` returns a minimal
     text shell that carries only slot plans (序號 / 題型 / 出題概念).
  2. Passes a ``sub_client_factory`` so every per-小題 call goes through
     the real ``build_subquestion_system/user_prompt`` builder and then
     the injected sub client.

The ``_SchemaFaithfulSubClient`` used by tests 1, 3, and 4 emits
``chart_spec`` **only** when the system-prompt schema already lists it —
mirroring the behaviour of a real model that follows the output schema.
Reintroducing the #319 bug (stripping ``chart_spec`` from
``build_subquestion_system_prompt``) causes those tests to fail because
the sub client no longer returns ``chart_spec`` → the rendering pipeline
is skipped → the PNG assertions are not satisfied.
"""

from __future__ import annotations

from pathlib import Path

from server.config import ServerConfig
from server.generate.marshalling import question_to_event as _question_to_event
from src.config import Config
from src.social_studies.cli import generate_one
from src.social_studies.sampler import sample_params

# ---------------------------------------------------------------------------
# Text-shell stubs (返回 slot plans，不含完整 SubQuestion 資料)
# ---------------------------------------------------------------------------

_TEXT_SHELL_THREE_SLOTS = {
    "核心問題": "都市更新如何影響居民生活？",
    "文本": "某市正在推動都市更新，居民對公共設施與租金變化有不同看法。",
    "取材來源": ["測試資料"],
    "subquestions": [
        {"序號": 1, "題型": "選擇題", "出題概念": "判讀都市更新示意圖"},
        {"序號": 2, "題型": "選擇題", "出題概念": "概念二"},
        {"序號": 3, "題型": "選擇題", "出題概念": "概念三"},
    ],
    "題目": ["文本", "根據圖1，居民最可能關注哪一項變化？"],
    "正確解題分析": ["A。圖中標示公共設施增加。"],
}


class _FakeTextClient:
    """文本生成器 stub for tests 1, 3, and 4.

    Returns a minimal text shell (slot plans only).  Handles
    ``generate_image`` so that per-小題 PNG rendering can complete.
    """

    def get_observer(self):
        return None

    def generate_json(self, system, user, images=None, **kwargs):
        return _TEXT_SHELL_THREE_SLOTS

    def generate_image(self, _prompt: str, output_path) -> str:
        Path(output_path).write_bytes(b"subquestion-png")
        return str(output_path)


# ---------------------------------------------------------------------------
# Schema-faithful sub client (mutation-verify seam)
# ---------------------------------------------------------------------------


class _SchemaFaithfulSubClient:
    """子題產生器 stub: emits ``chart_spec`` only when the system-prompt
    schema explicitly lists it.

    This simulates a model that follows the output schema:

    * **Before** the #319 fix — ``build_subquestion_system_prompt`` omits
      ``chart_spec`` from its JSON example → ``"chart_spec" in system``
      is False → this client returns no ``chart_spec`` → no PNG rendered.
    * **After** the fix — the schema includes ``chart_spec`` →
      ``"chart_spec" in system`` is True → client returns it → PNG written.

    **Mutation-verify seam**: strip the ``chart_spec`` line from
    ``build_subquestion_system_prompt`` and tests 1, 3, and 4 turn red.
    """

    def set_observer(self, obs) -> None:
        pass

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        idx = int(agent_override.split("#")[1]) if agent_override else 1
        response: dict = {
            "序號": idx,
            "年級": 8,
            "科目": ["地理"],
            "核心素養": ["社-J-A2"],
            "學習內容": [{"編碼": "地Af-Ⅳ-3", "說明": "都市發展"}],
            "學習表現": [{"編碼": "社1b-Ⅳ-1", "說明": "解析社會現象"}],
            "出題概念": "判讀都市更新示意圖",
            "題型": "選擇題",
            "題目": "根據圖1，居民最可能關注哪一項變化？（A）甲（B）乙（C）丙（D）丁",
            "答案": "A",
            "答案解析": "圖中標示公共設施增加。",
            "評分規準": [],
        }
        # Only include chart_spec when the schema explicitly carries it.
        # The #319 fix added "chart_spec": null to the system-prompt
        # JSON example; stripping it makes this branch unreachable and
        # causes the PNG assertions below to fail (mutation-verify AC).
        if "chart_spec" in system:
            response["chart_spec"] = {
                "render_mode": "html",
                "title": "都市更新前後比較圖",
                "description": "左側為更新前街區，右側為更新後公共設施增加的街區。",
                "data": {"更新前": "老舊住宅", "更新後": "公園與捷運站"},
            }
        return response


# ---------------------------------------------------------------------------
# Clients for test 2: top-level repair path
# ---------------------------------------------------------------------------

_TEXT_SHELL_NO_CHART = {
    "核心問題": "都市更新如何影響居民生活？",
    "文本": "某市正在推動都市更新，居民對公共設施與租金變化有不同看法。",
    "取材來源": ["測試資料"],
    "subquestions": [
        {"序號": 1, "題型": "選擇題", "出題概念": "概念一"},
        {"序號": 2, "題型": "選擇題", "出題概念": "概念二"},
        {"序號": 3, "題型": "選擇題", "出題概念": "概念三"},
    ],
    "題目": ["文本", "根據文本，居民最可能關注哪一項變化？"],
    "正確解題分析": ["A。文本提到公共設施與租金變化。"],
}


class _RepairTopLevelImageClient:
    """文本生成器 + repair client for test 2.

    Call 1 (text generation): returns a text shell WITHOUT a top-level
    ``chart_spec`` — deliberately omitted so that
    ``_ensure_top_level_visual_spec`` fires.
    Call 2 (repair via ``_ensure_top_level_visual_spec``): returns the
    ``chart_spec`` block.
    Sub-question generation is handled separately by ``sub_client_factory``.
    """

    def __init__(self) -> None:
        self.generate_json_calls = 0

    def get_observer(self):
        return None

    def generate_json(self, *_args, **_kwargs):
        self.generate_json_calls += 1
        if self.generate_json_calls == 1:
            return _TEXT_SHELL_NO_CHART
        # Second call: top-level repair response
        return {
            "chart_spec": {
                "render_mode": "html",
                "title": "都市更新公共設施示意圖",
                "description": "呈現更新前後街區、公共設施增加與租金變化資訊。",
                "data": {"更新前": "老舊住宅", "更新後": "公園、捷運站、租金上升"},
            }
        }

    def generate_image(self, _prompt: str, output_path) -> str:
        Path(output_path).write_bytes(b"parent-png")
        return str(output_path)


class _PlainSubClient:
    """Simple 子題產生器 stub for test 2.

    Returns plain subquestions without ``chart_spec`` — test 2 is about
    the top-level repair path, not per-小題 images.
    """

    def set_observer(self, obs) -> None:
        pass

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        idx = int(agent_override.split("#")[1]) if agent_override else 1
        return {
            "序號": idx,
            "年級": 8,
            "科目": ["地理"],
            "核心素養": ["社-J-A2"],
            "學習內容": [{"編碼": "地Af-Ⅳ-3", "說明": "都市發展"}],
            "學習表現": [{"編碼": "社1b-Ⅳ-1", "說明": "解析社會現象"}],
            "出題概念": "概念",
            "題型": "選擇題",
            "題目": "根據文本，居民最可能關注哪一項變化？（A）甲（B）乙（C）丙（D）丁",
            "答案": "A",
            "答案解析": "文本提到公共設施與租金變化。",
            "評分規準": [],
        }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_social_studies_subquestion_chart_spec_renders_png(tmp_path: Path) -> None:
    """子題產生器 returns chart_spec → PNG rendered for the 含圖片 slot (#321)."""
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    params = sample_params(
        seed=1,
        sub_question_count=3,
        subquestion_configs=[
            {
                "content_type": "含圖片",
                "image_generation_mode": "gpt_image",
                "instruction": "請聚焦在都市更新前後比較",
            },
        ],
    )

    question = generate_one(
        config=config,
        client=_FakeTextClient(),
        params=params,
        question_id="ss_test",
        skip_verify=True,
        image_generation_mode="html",
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _SchemaFaithfulSubClient(),
    )

    assert not isinstance(question, str)
    assert question.subquestions[0].圖片 == "ss_test_sq1.png"
    assert question.subquestions[0].image_generation_mode == "gpt_image"
    assert question.subquestions[0].出題指示 == "請聚焦在都市更新前後比較"
    assert (tmp_path / "ss_test_sq1.png").read_bytes() == b"subquestion-png"


def test_global_image_content_type_repairs_and_renders_parent_png(tmp_path: Path) -> None:
    """Missing top-level chart_spec triggers repair; result PNG is embedded (#321)."""
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    params = sample_params(seed=1, content_type="含圖片")
    client = _RepairTopLevelImageClient()

    question = generate_one(
        config=config,
        client=client,
        params=params,
        question_id="ss_test",
        skip_verify=True,
        image_generation_mode="gpt_image",
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _PlainSubClient(),
    )

    assert not isinstance(question, str)
    assert client.generate_json_calls == 2
    assert question.chart_spec is not None
    assert question.圖片 == "ss_test.png"
    assert (tmp_path / "ss_test.png").read_bytes() == b"parent-png"

    payload = _question_to_event(
        question,
        ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
    )
    assert payload["圖片"] == "ss_test.png"
    assert payload["image_base64"] == "cGFyZW50LXBuZw=="


def test_social_studies_subquestion_inherits_request_image_mode(tmp_path: Path) -> None:
    """No per-小題 image mode → request-level gpt_image is inherited (#321)."""
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    params = sample_params(
        seed=1,
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "含圖片"},
        ],
    )

    question = generate_one(
        config=config,
        client=_FakeTextClient(),
        params=params,
        question_id="ss_test",
        skip_verify=True,
        image_generation_mode="gpt_image",
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _SchemaFaithfulSubClient(),
    )

    assert not isinstance(question, str)
    assert question.subquestions[0].圖片 == "ss_test_sq1.png"
    assert question.subquestions[0].image_generation_mode == "gpt_image"
    assert (tmp_path / "ss_test_sq1.png").read_bytes() == b"subquestion-png"


def test_question_to_event_embeds_subquestion_png(tmp_path: Path) -> None:
    """Server marshalling base64-encodes the per-小題 PNG (#321)."""
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    params = sample_params(
        seed=1,
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
        ],
    )
    question = generate_one(
        config=config,
        client=_FakeTextClient(),
        params=params,
        question_id="ss_test",
        skip_verify=True,
        image_generation_mode="html",
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _SchemaFaithfulSubClient(),
    )
    assert not isinstance(question, str)

    payload = _question_to_event(
        question,
        ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
    )

    assert payload["subquestions"][0]["圖片"] == "ss_test_sq1.png"
    assert payload["subquestions"][0]["image_base64"] == "c3VicXVlc3Rpb24tcG5n"
