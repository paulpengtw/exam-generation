"""#319 — 提示詞預覽 must show a 小題's image requirement on 發送前確認.

The 提示詞預覽 and the real 子題產生器 path share `build_subquestion_user_prompt`,
so this file verifies the shared builder rather than forking it: it asserts the
image contract is visible in the preview AND that the preview is still
byte-identical to what production sends for the same request.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from server.config import ServerConfig
from server.generate.models import GenerateParams
from server.generate.service import build_prompt_previews
from src.social_studies.cli import generate_one as generate_social_studies
from src.social_studies.sampler import sample_params as sample_social_studies

_IMAGE_CONTENT_TYPES = ("含圖片", "graphs/charts/tables")

_SUBQUESTION_CONFIGS = [
    {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
    {"content_type": "純文字"},
    {"content_type": "graphs/charts/tables"},
]


def _slot_config_line(user_prompt: str, 序號: int) -> str:
    """回傳 各小題配置 中描述這一小題的那一行；找不到時回傳空字串。"""
    for line in user_prompt.splitlines():
        if f"第{序號}小題" in line:
            return line
    return ""


class _CapturingClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def get_observer(self):
        return None

    def generate_json(self, _system: str, _user: str, **_kwargs):
        return self.payload

    def generate_image(self, _prompt: str, output_path: str | Path) -> str:
        Path(output_path).write_bytes(b"png")
        return str(output_path)


class _CapturingSubClient:
    def __init__(self, prompts_by_idx: dict[int, tuple[str, str]]) -> None:
        self.prompts_by_idx = prompts_by_idx

    def set_observer(self, _observer) -> None:
        pass

    def generate_json(self, system: str, user: str, *, agent_override: str, **_kwargs):
        idx = int(agent_override.split("#", 1)[1])
        self.prompts_by_idx[idx] = (system, user)
        return {
            "序號": idx,
            "題型": "選擇題",
            "題目": f"第{idx}小題",
            "答案": "A",
            "答案解析": "解析",
            "出題概念": f"概念{idx}",
        }


def test_提示詞預覽_shows_image_requirement_for_含圖片_小題(tmp_path: Path) -> None:
    """發送前確認 的 子題產生器 預覽必須顯示該小題的圖片需求，且與正式路徑逐字一致。"""
    seed = 191
    config = ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        creative_planning=False,
    )
    app_state = SimpleNamespace(ss_curriculum_context=None)
    params = GenerateParams(
        subject="social_studies",
        seed=seed,
        disable_reference_fewshot=True,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs="""[
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
            {"content_type": "純文字"},
            {"content_type": "graphs/charts/tables"}
        ]""",
    )

    previews = build_prompt_previews(params, config, app_state)
    sub_previews = {
        preview["subquestion_index"]: preview
        for preview in previews
        if "subquestion_index" in preview
    }
    assert set(sub_previews) == {1, 2, 3}

    # 第1小題（含圖片 + GPT 生圖）：預覽必須帶出該小題的圖片契約。
    slot_1 = sub_previews[1]
    line_1 = _slot_config_line(slot_1["user_prompt"], 1)
    assert "含圖片" in line_1, f"預覽的第1小題配置未帶出 題目內容類型：{line_1!r}"
    assert "gpt_image" in line_1, f"預覽的第1小題配置未帶出 image_generation_mode：{line_1!r}"
    assert "chart_spec" in slot_1["user_prompt"]
    assert "chart_spec" in slot_1["system_prompt"]

    # 第3小題（graphs/charts/tables）同樣需要圖片。
    line_3 = _slot_config_line(sub_previews[3]["user_prompt"], 3)
    assert "graphs/charts/tables" in line_3, f"預覽的第3小題配置未帶出 題目內容類型：{line_3!r}"

    # 第2小題（純文字）不得被要求輸出 chart_spec。
    line_2 = _slot_config_line(sub_previews[2]["user_prompt"], 2)
    assert "純文字" in line_2, f"預覽的第2小題配置未帶出 題目內容類型：{line_2!r}"
    assert not any(ct in line_2 for ct in _IMAGE_CONTENT_TYPES), (
        f"純文字 小題被標成需要圖片：{line_2!r}"
    )

    # 共用 builder：預覽與正式 子題產生器 prompt 必須逐字相同（不得分叉）。
    text_payload = {
        "核心問題": "真實核心問題",
        "文本": "真實文本",
        "取材來源": ["真實來源"],
        "subquestions": [
            {"序號": i, "題型": "選擇題", "出題概念": f"概念{i}"} for i in range(1, 4)
        ],
    }
    sampled = sample_social_studies(
        seed=seed,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[dict(cfg) for cfg in _SUBQUESTION_CONFIGS],
    )
    captured: dict[int, tuple[str, str]] = {}
    generate_social_studies(
        config=config,
        client=_CapturingClient(text_payload),
        params=sampled,
        question_id="preview-sub-generator-image",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _CapturingSubClient(captured),
    )

    assert set(captured) == {1, 2, 3}
    for idx, real_prompts in captured.items():
        preview = sub_previews[idx]
        substituted_user = (
            preview["user_prompt"]
            .replace("{{核心問題：由前一階段產生}}", text_payload["核心問題"])
            .replace("{{文本：由前一階段產生}}", text_payload["文本"])
            .replace("{{取材來源：由前一階段產生}}", text_payload["取材來源"][0])
            .replace("{{子題 plan：由前一階段產生}}", f"概念{idx}")
        )
        assert (preview["system_prompt"], substituted_user) == real_prompts
