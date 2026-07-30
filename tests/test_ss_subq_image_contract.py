"""Issue #319: 子題產生器 prompts must carry the 小題 image contract.

TDD red → green: two tests at the sub_client_factory seam.

Test 1 (prompt-contract): the captured system+user prompts for a 含圖片+gpt_image
slot must explicitly state the image requirement and chart_spec obligation.

Test 2 (symptom): a model that faithfully returns chart_spec only when the schema
mentions it must cause an image-endpoint call and attach a PNG to that subquestion.
"""

from __future__ import annotations

from pathlib import Path

from src.config import Config
from src.social_studies.cli import generate_one
from src.social_studies.sampler import sample_params
from src.social_studies.schemas import ExamQuestion

# ---------------------------------------------------------------------------
# Shared text-generator stub
# ---------------------------------------------------------------------------

_TEXT_SHELL_THREE_SLOTS = {
    "核心問題": "測試核心問題",
    "文本": "測試文本素材",
    "取材來源": ["測試來源"],
    "subquestions": [
        {"序號": 1, "題型": "選擇題", "出題概念": "概念一"},
        {"序號": 2, "題型": "選擇題", "出題概念": "概念二"},
        {"序號": 3, "題型": "選擇題", "出題概念": "概念三"},
    ],
}


class _FakeTextClient:
    """Stand-in for the 文本生成器 stage; returns a single-slot text shell.

    Also handles generate_image so that rendered PNGs can be written to disk.
    """

    def get_observer(self):
        return None

    def generate_json(self, system, user, images=None, **kwargs):
        return _TEXT_SHELL_THREE_SLOTS

    def generate_image(self, prompt: str, output_path) -> str:
        Path(output_path).write_bytes(b"fake-png-data")
        return str(output_path)


# ---------------------------------------------------------------------------
# Test 1 — Prompt contract
# ---------------------------------------------------------------------------


class _CapturingSubClient:
    """Records the system+user prompts for slot 1 (the 含圖片 slot) specifically.

    All three parallel 子題產生器 calls share the same client instance, so we
    capture only the first slot's prompts (which carry the image config).
    """

    def __init__(self) -> None:
        self.captured_system: str = ""
        self.captured_user: str = ""

    def set_observer(self, obs) -> None:
        pass

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        idx = int(agent_override.split("#")[1]) if agent_override else 1
        if idx == 1:
            # Slot 1 is the 含圖片 slot — capture its prompts for assertions
            self.captured_system = system
            self.captured_user = user
        # Return a minimal valid 小題 so the pipeline completes
        return {
            "序號": idx,
            "年級": 8,
            "科目": ["地理"],
            "核心素養": ["社-J-A2"],
            "學習內容": [{"編碼": "地Af-Ⅳ-3", "說明": "都市發展"}],
            "學習表現": [{"編碼": "社1b-Ⅳ-1", "說明": "解析"}],
            "出題概念": "概念",
            "題型": "選擇題",
            "題目": "題目（A）甲（B）乙（C）丙（D）丁",
            "答案": "A",
            "答案解析": "解析",
            "評分規準": [],
        }


def test_subq_prompt_states_image_contract(tmp_path: Path) -> None:
    """子題產生器 system+user prompts must name 含圖片 / chart_spec / gpt_image (#319).

    RED before fix:
    - build_subquestion_system_prompt schema omits chart_spec / 題目內容類型 /
      image_generation_mode.
    - build_subquestion_user_prompt config line omits content_type /
      image_generation_mode from 各小題配置.
    """
    capture = _CapturingSubClient()

    params = sample_params(
        seed=1,
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
            {},
            {},
        ],
    )
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))

    generate_one(
        config=config,
        client=_FakeTextClient(),
        params=params,
        question_id="contract_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: capture,
    )

    combined = capture.captured_system + "\n" + capture.captured_user
    assert "含圖片" in combined, (
        "子題產生器 prompts must state the 題目內容類型 value 含圖片; "
        f"first 800 chars of combined prompt:\n{combined[:800]}"
    )
    assert "chart_spec" in combined, (
        "子題產生器 prompts must name the chart_spec output field; "
        f"first 800 chars of combined prompt:\n{combined[:800]}"
    )
    assert "gpt_image" in combined, (
        "子題產生器 prompts must echo the image_generation_mode; "
        f"first 800 chars of combined prompt:\n{combined[:800]}"
    )


# ---------------------------------------------------------------------------
# Test 2 — Symptom: image endpoint reached when model follows fixed schema
# ---------------------------------------------------------------------------


class _SchemaFaithfulSubClient:
    """Only returns chart_spec when the system prompt schema explicitly mentions it.

    Mimics a real model that follows the output schema: if 'chart_spec' does not
    appear in the system prompt, the model will not output it.  Before the fix the
    system prompt schema omits chart_spec → client returns no chart_spec → no PNG.
    After the fix the schema includes chart_spec → client returns it → PNG written.
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
            "學習表現": [{"編碼": "社1b-Ⅳ-1", "說明": "解析"}],
            "出題概念": "概念",
            "題型": "選擇題",
            "題目": "根據圖1，以下何者正確？（A）甲（B）乙（C）丙（D）丁",
            "答案": "A",
            "答案解析": "解析",
            "評分規準": [],
        }
        # Faithfully follow what the schema says: only emit chart_spec when the
        # system prompt schema lists it (and the user prompt mentions 含圖片).
        if "chart_spec" in system and "含圖片" in (system + user):
            response["chart_spec"] = {
                "render_mode": "html",
                "title": "測試用圖",
                "description": "一張測試用圖片，請在下緣加上 caption。",
                "data": {},
            }
        return response


def test_含圖片_slot_produces_png_when_model_follows_schema(tmp_path: Path) -> None:
    """A 含圖片+gpt_image slot produces a PNG when the model follows the prompt schema (#319).

    RED before fix: system prompt omits chart_spec in its schema → the
    schema-faithful model omits chart_spec → _render_subquestion_images skips
    the slot (if not sub.chart_spec: continue) → no PNG written → assertions fail.

    GREEN after fix: system prompt schema includes chart_spec → model returns it
    → rendering pipeline calls generate_image → PNG written.
    """
    params = sample_params(
        seed=1,
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
            {},
            {},
        ],
    )
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))

    question = generate_one(
        config=config,
        client=_FakeTextClient(),
        params=params,
        question_id="symptom_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _SchemaFaithfulSubClient(),
        image_generation_mode="gpt_image",
    )

    assert isinstance(question, ExamQuestion)
    sq = question.subquestions[0]
    assert sq.chart_spec is not None, (
        "subquestion must carry a chart_spec when the model follows the fixed schema"
    )
    assert sq.圖片 is not None, (
        "subquestion PNG filename must be set after rendering"
    )
    assert (tmp_path / "symptom_test_sq1.png").exists(), (
        "PNG file must be written to disk for the 含圖片 小題"
    )
