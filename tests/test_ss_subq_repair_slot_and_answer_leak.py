"""Follow-up to #320: PLAN 索引查配置與修補提示不外洩答案。

DEFECT 1: 各小題配置 依 sub.序號（模型自報）查找，但 cfg 建構時用的是 PLAN 索引。
  模型錯位回傳 序號 時，含圖片槽位被跳過，純文字槽位被誤修補。
  修補：在 _parse_subquestion 記錄 _plan_index，_ss_render_subquestion_images
  改用 _plan_index 查 sq_visual_content_types。

DEFECT 2: 修補提示把 答案/答案解析/評分規準/誘答分析 夾帶進 sq_json，
  違反 system prompt 的「不要加入答案提示」。
  修補：extend exclude set。

BLIND SPOT 3: 子題產生器 自備 chart_spec 時的早出條件（#320 guard）未有測試釘住。
  子題產生器遵守含圖片合約自備 chart_spec → 應零修補呼叫且不覆寫原值。
"""

from __future__ import annotations

import json
from pathlib import Path

from src.config import Config
from src.social_studies.cli import generate_one
from src.social_studies.sampler import sample_params
from src.social_studies.schemas import ExamQuestion

# ---------------------------------------------------------------------------
# Shared text-shell (same shape as existing tests)
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

# ---------------------------------------------------------------------------
# Fake main client: text shell on first call; records repair calls thereafter
# ---------------------------------------------------------------------------


class _MainClientRecordingRepairs:
    """主客戶端：第一次呼叫回傳文本殼；後續呼叫視為修補請求並記錄。"""

    def __init__(self) -> None:
        self._call_count = 0
        self.repair_calls: list[tuple[str, str]] = []

    def get_observer(self):
        return None

    def generate_json(self, system, user, images=None, **kwargs):
        self._call_count += 1
        if self._call_count == 1:
            return _TEXT_SHELL_THREE_SLOTS
        self.repair_calls.append((system, user))
        return {
            "chart_spec": {
                "render_mode": "html",
                "title": "修補圖",
                "description": "修補後的小題示意圖。",
                "data": {},
            }
        }

    def generate_image(self, prompt: str, output_path) -> str:
        Path(output_path).write_bytes(b"repair-png-data")
        return str(output_path)


# ---------------------------------------------------------------------------
# Sub-client: shifts 序號 so plan_index 1 gets 序號=2 and vice versa
# ---------------------------------------------------------------------------


class _SerialNumShiftingSubClient:
    """子題產生器假體：故意錯位 序號（計畫槽位1→序號2；槽位2→序號1）。

    不回傳 chart_spec，以觸發修補流程，讓我們能觀察修補是否對到正確槽位。
    """

    def set_observer(self, obs) -> None:
        pass

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        idx = int(agent_override.split("#")[1]) if agent_override else 1
        # 計畫槽位 1 → 序號 2；計畫槽位 2 → 序號 1；其餘不變
        seq_num = {1: 2, 2: 1}.get(idx, idx)
        return {
            "序號": seq_num,
            "年級": 8,
            "科目": ["地理"],
            "核心素養": ["社-J-A2"],
            "學習內容": [{"編碼": "地Af-Ⅳ-3", "說明": "都市發展"}],
            "學習表現": [{"編碼": "社1b-⅔-1", "說明": "解析"}],
            "出題概念": f"計畫槽位{idx}的概念",
            "題型": "選擇題",
            "題目": "題目（A）甲（B）乙（C）丙（D）丁",
            "答案": "A",
            "答案解析": "解析",
            "評分規準": [],
        }


# ---------------------------------------------------------------------------
# DEFECT 1 — 修補依計畫索引查配置，不依模型自報序號
# ---------------------------------------------------------------------------


def test_repair_targets_plan_slot_not_model_reported_seq_num(tmp_path: Path) -> None:
    """含圖片計畫槽位（plan_index=1）的修補即使模型回傳 序號=2 也必須命中該槽位。

    RED（修補前）：
      sq_visual_content_types = {1: "含圖片"}，以 sub.序號 查找。
      question.subquestions[0] 對應計畫槽位1，但模型回傳 序號=2。
      sq_visual_content_types.get(2) = None → 含圖片槽位被跳過，不觸發修補。
      question.subquestions[0].chart_spec is None → 斷言失敗。

    GREEN（修補後）：
      _parse_subquestion 記錄 _plan_index=1。
      _ss_render_subquestion_images 以 _plan_index 查找 → 正確觸發修補。
      question.subquestions[0].chart_spec is not None → 通過。
    """
    params = sample_params(
        seed=1,
        content_type="純文字",  # 頂層不觸發頂層修補
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
            {},
            {},
        ],
    )
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    main_client = _MainClientRecordingRepairs()

    question = generate_one(
        config=config,
        client=main_client,
        params=params,
        question_id="slot_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _SerialNumShiftingSubClient(),
        image_generation_mode="gpt_image",
    )

    assert isinstance(question, ExamQuestion)
    # subquestions 按計畫索引排序：[0] = 計畫槽位1（含圖片），[1] = 計畫槽位2（純文字）
    plan_slot_1 = question.subquestions[0]
    plan_slot_2 = question.subquestions[1]

    assert plan_slot_1.chart_spec is not None, (
        "計畫槽位1（含圖片）應被修補取得 chart_spec，"
        f"但 chart_spec={plan_slot_1.chart_spec!r}，"
        f"修補呼叫數={len(main_client.repair_calls)}"
    )
    assert plan_slot_2.chart_spec is None, (
        "計畫槽位2（純文字）不應被誤修補，"
        f"但 chart_spec={plan_slot_2.chart_spec!r}"
    )
    assert len(main_client.repair_calls) == 1, (
        f"應恰好一次修補呼叫，實際 {len(main_client.repair_calls)} 次"
    )


# ---------------------------------------------------------------------------
# DEFECT 2 — 修補提示不外洩 答案/答案解析/評分規準/誘答分析
# ---------------------------------------------------------------------------


class _IgnoringSubClient:
    """子題產生器假體：回傳含答案的完整小題，但不含 chart_spec。"""

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
            "學習表現": [{"編碼": "社1b-Ⅳ-1", "說明": "解析"}],
            "出題概念": "概念",
            "題型": "選擇題",
            "題目": "題目（A）甲（B）乙（C）丙（D）丁",
            "答案": "A",
            "答案解析": "故正確答案為A",
            "評分規準": [{"code": "1", "規準說明": "選A得1分", "學生作答實例": []}],
            "誘答分析": {"B": "此選項測試學生對乙的理解"},
        }


def test_repair_prompt_excludes_answer_fields(tmp_path: Path) -> None:
    """修補提示的 sq_json 不得包含 答案/答案解析/評分規準/誘答分析。

    RED（修補前）：
      exclude={"圖片"} 僅排除圖片欄位；
      修補用 sq_json 包含 "答案": "A" 等欄位 → 斷言失敗。

    GREEN（修補後）：
      exclude={"圖片", "答案", "答案解析", "評分規準", "誘答分析"}；
      解析修補提示中的 JSON → 四個欄位均不存在 → 通過。
    """
    params = sample_params(
        seed=1,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
            {},
            {},
        ],
    )
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    main_client = _MainClientRecordingRepairs()

    generate_one(
        config=config,
        client=main_client,
        params=params,
        question_id="leak_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _IgnoringSubClient(),
        image_generation_mode="gpt_image",
    )

    assert len(main_client.repair_calls) == 1, (
        f"期望恰好一次修補呼叫，實際 {len(main_client.repair_calls)} 次"
    )
    _system, user_prompt = main_client.repair_calls[0]

    # 從 user_prompt 解析出 sq_json 段落，檢查不含答案欄位
    marker_start = "```json\n"
    marker_end = "\n```"
    start = user_prompt.index(marker_start) + len(marker_start)
    end = user_prompt.index(marker_end, start)
    sq_data = json.loads(user_prompt[start:end])

    assert "答案" not in sq_data, (
        f"修補提示不得夾帶「答案」，但 sq_data 含有 答案={sq_data.get('答案')!r}"
    )
    assert "答案解析" not in sq_data, (
        f"修補提示不得夾帶「答案解析」，但 sq_data 含有 答案解析={sq_data.get('答案解析')!r}"
    )
    assert "評分規準" not in sq_data, (
        "修補提示不得夾帶「評分規準」"
    )
    assert "誘答分析" not in sq_data, (
        "修補提示不得夾帶「誘答分析」"
    )


# ---------------------------------------------------------------------------
# BLIND SPOT 3 — 子題自備 chart_spec 時早出，不重複修補
# ---------------------------------------------------------------------------


class _ObedientSubClient:
    """子題產生器假體：計畫槽位1自備合法 chart_spec（遵守含圖片合約）。"""

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
        if idx == 1:
            # 含圖片計畫槽位1：子題產生器自備 chart_spec
            response["chart_spec"] = {
                "render_mode": "html",
                "title": "子題自備圖片",
                "description": "測試用圖，子題產生器自行提供。",
                "data": {},
            }
        return response


def test_model_chart_spec_not_overwritten_and_no_repair_call(tmp_path: Path) -> None:
    """子題產生器自備 chart_spec 時，不得觸發修補且不得覆寫原值（#320 早出守衛）。

    此測試初次執行應綠燈（守衛已存在）。
    以下「突變＋失敗」注解記錄了其把關能力：
      刪除 _ensure_subquestion_visual_spec 中 `sub.chart_spec or` 條件 →
      修補被觸發 → main_client.repair_calls 非空或 chart_spec.title 被覆寫 →
      斷言失敗；git restore 後恢復綠燈。
    """
    params = sample_params(
        seed=1,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
            {},
            {},
        ],
    )
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    main_client = _MainClientRecordingRepairs()

    question = generate_one(
        config=config,
        client=main_client,
        params=params,
        question_id="early_out_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _ObedientSubClient(),
        image_generation_mode="gpt_image",
    )

    assert isinstance(question, ExamQuestion)
    assert main_client.repair_calls == [], (
        "子題產生器自備 chart_spec 時不應觸發修補呼叫，"
        f"但記錄到 {len(main_client.repair_calls)} 次修補"
    )
    sq = question.subquestions[0]
    assert sq.chart_spec is not None, "子題自備的 chart_spec 必須保留"
    assert sq.chart_spec.title == "子題自備圖片", (
        f"chart_spec.title 被覆寫或遺失，實際值={sq.chart_spec.title!r}"
    )
