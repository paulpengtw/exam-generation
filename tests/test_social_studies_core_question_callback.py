from __future__ import annotations

import inspect
import random
from pathlib import Path
from types import SimpleNamespace

from src.config import Config
from src.social_studies.context_builder import (
    build_subquestion_user_prompt,
    build_text_user_prompt,
    build_user_prompt,
)
from src.social_studies.sampler import sample_params

_PRE_CHANGE_TEXT_REPLACEMENT = (
    """\
6. 選擇題計分使用 0/1（答對 1 分、答錯 0 分）；開放式建構反應題依每題專屬評分指引使用 0..N。
7. `題目` 陣列（舊版格式）：第一個元素放文本素材，其後每個元素放一道小題完整文字。
8. `正確解題分析` 陣列（舊版格式）：每個元素對應一道小題的答案與說明。
9. 只輸出 JSON 格式的結果。
""",
    (
        "6. `subquestions` 陣列中每筆只需提供 `序號`、`題型` 與 `出題概念`；"
        "不要輸出題目文字、答案或評分規準。\n"
        "7. 只輸出 JSON 格式的結果。\n"
    ),
)


def _pre_change_text_prompt(params, few_shot_dir: Path) -> str:
    prompt, _ = build_user_prompt(
        params=params,
        few_shot_dir=few_shot_dir,
        rng=random.Random(17),
        disable_reference_fewshot=True,
    )
    return prompt.replace(*_PRE_CHANGE_TEXT_REPLACEMENT)


def test_text_prompt_defaults_to_core_question_callback(tmp_path: Path) -> None:
    params = sample_params(seed=17, sub_question_count=3)

    prompt, _ = build_text_user_prompt(
        params,
        tmp_path,
        rng=random.Random(17),
        disable_reference_fewshot=True,
    )

    assert "## 回扣核心問題" in prompt
    assert "最後規劃的小題" in prompt
    assert "明確要求學生回應本題組自己的「核心問題」" in prompt
    assert "整合前面各小題" in prompt


def test_text_prompt_opt_out_is_byte_identical_to_pre_change_output(tmp_path: Path) -> None:
    params = sample_params(seed=17, sub_question_count=3)

    prompt, _ = build_text_user_prompt(
        params,
        tmp_path,
        rng=random.Random(17),
        disable_reference_fewshot=True,
        core_question_callback=False,
    )

    assert prompt == _pre_change_text_prompt(params, tmp_path)
    assert "## 回扣核心問題" not in prompt


def test_only_last_subquestion_gets_callback_instruction(tmp_path: Path) -> None:
    params = sample_params(seed=23, sub_question_count=3)
    common = {
        "核心問題": "本題組的核心問題",
        "文本": "本題組的共用文本",
        "取材來源": ["測試來源"],
        "params": params,
        "few_shot_dir": tmp_path,
        "disable_reference_fewshot": True,
    }

    first, _ = build_subquestion_user_prompt(
        **common,
        sq_plan={"序號": 1, "題型": "選擇題", "出題概念": "前題"},
        core_question_callback=True,
        is_last=False,
    )
    last, _ = build_subquestion_user_prompt(
        **common,
        sq_plan={"序號": 3, "題型": "選擇題", "出題概念": "統整題"},
        core_question_callback=True,
        is_last=True,
    )

    assert "## 回扣核心問題" not in first
    assert "## 回扣核心問題" in last
    assert "本小題是本題組最後一小題" in last
    assert "明確要求學生回應本題組自己的「核心問題」" in last
    assert "整合前面各小題" in last


def test_subquestion_opt_out_preserves_the_pre_change_prompt_bytes(
    tmp_path: Path,
) -> None:
    params = sample_params(seed=23, sub_question_count=3)
    common = {
        "核心問題": "本題組的核心問題",
        "文本": "本題組的共用文本",
        "取材來源": ["測試來源"],
        "params": params,
        "few_shot_dir": tmp_path,
        "disable_reference_fewshot": True,
        "sq_plan": {"序號": 3, "題型": "選擇題", "出題概念": "統整題"},
    }

    baseline, _ = build_subquestion_user_prompt(**common)
    opt_out, _ = build_subquestion_user_prompt(
        **common,
        core_question_callback=False,
        is_last=True,
    )

    assert opt_out == baseline
    assert "## 回扣核心問題" not in opt_out


def test_last_slot_callback_composes_with_explicit_subquestion_config(
    tmp_path: Path,
) -> None:
    params = sample_params(
        seed=23,
        sub_question_count=3,
        subquestion_configs=[
            {},
            {},
            {
                "instruction": "請比較兩項政策的影響",
                "learning_content": ["歷Ka-Ⅳ-1"],
                "learning_performance": ["社1b-Ⅳ-1"],
            },
        ],
    )

    prompt, _ = build_subquestion_user_prompt(
        核心問題="本題組的核心問題",
        文本="本題組的共用文本",
        取材來源=["測試來源"],
        sq_plan={"序號": 3, "題型": "選擇題", "出題概念": "統整題"},
        params=params,
        few_shot_dir=tmp_path,
        cfg=params.subquestion_configs[2],
        disable_reference_fewshot=True,
        core_question_callback=True,
        is_last=True,
    )

    assert "出題指示=請比較兩項政策的影響" in prompt
    assert "歷Ka-Ⅳ-1" in prompt
    assert "社1b-Ⅳ-1" in prompt
    assert "## 回扣核心問題" in prompt
    assert "明確要求學生回應本題組自己的「核心問題」" in prompt


class _TextClient:
    def __init__(self, plan_count: int) -> None:
        self.plan_count = plan_count

    def get_observer(self):
        return None

    def generate_json(self, _system, _user, images=None, **_kwargs):
        del images
        return {
            "核心問題": "本題組的核心問題",
            "文本": "本題組的共用文本",
            "取材來源": ["測試來源"],
            "subquestions": [
                {"序號": i, "題型": "選擇題", "出題概念": f"概念{i}"}
                for i in range(1, self.plan_count + 1)
            ],
        }


class _SubClient:
    def __init__(self, prompts_by_idx: dict[int, str]) -> None:
        self.prompts_by_idx = prompts_by_idx

    def set_observer(self, _observer) -> None:
        pass

    def generate_json(self, _system, user, images=None, agent_override=None, **_kwargs):
        del images
        idx = int(agent_override.split("#", 1)[1])
        self.prompts_by_idx[idx] = user
        return {
            "序號": idx,
            "題型": "選擇題",
            "題目": f"第{idx}小題",
            "答案": "A",
            "答案解析": "解析",
            "出題概念": f"概念{idx}",
        }


def _capture_resolved_subquestion_prompts(
    plan_count: int,
    sub_question_count: int,
    *,
    core_question_callback: bool = True,
) -> dict[int, str]:
    from src.social_studies.cli import generate_one

    params = sample_params(
        seed=31,
        content_type="純文字",
        sub_question_count=sub_question_count,
    )
    prompts_by_idx: dict[int, str] = {}
    generate_one(
        config=Config(
            data_dir=Path("data"),
            subgen_max_concurrency=7,
            subgen_retries=0,
        ),
        client=_TextClient(plan_count),
        params=params,
        question_id=f"ss_callback_{plan_count}_{sub_question_count}",
        skip_verify=True,
        disable_reference_fewshot=True,
        core_question_callback=core_question_callback,
        sub_client_factory=lambda: _SubClient(prompts_by_idx),
    )
    return prompts_by_idx


def test_truncation_marks_the_resolved_final_subquestion_only() -> None:
    prompts = _capture_resolved_subquestion_prompts(plan_count=4, sub_question_count=3)

    assert set(prompts) == {1, 2, 3}
    assert all("## 回扣核心問題" not in prompts[i] for i in (1, 2))
    assert "## 回扣核心問題" in prompts[3]


def test_padding_marks_the_padded_resolved_final_subquestion() -> None:
    prompts = _capture_resolved_subquestion_prompts(plan_count=2, sub_question_count=3)

    assert set(prompts) == {1, 2, 3}
    assert all("## 回扣核心問題" not in prompts[i] for i in (1, 2))
    assert "## 回扣核心問題" in prompts[3]


def test_resolved_final_subquestion_callback_can_be_disabled() -> None:
    prompts = _capture_resolved_subquestion_prompts(
        plan_count=2,
        sub_question_count=3,
        core_question_callback=False,
    )

    assert all("## 回扣核心問題" not in prompt for prompt in prompts.values())


def test_generate_params_defaults_callback_on_and_accepts_explicit_off() -> None:
    from server.generate.models import GenerateParams

    assert GenerateParams(subject="social_studies").core_question_callback is True
    assert (
        GenerateParams(
            subject="social_studies",
            core_question_callback=False,
        ).core_question_callback
        is False
    )


def test_generate_route_declares_callback_query_parameter() -> None:
    from server.generate.routes import generate_endpoint

    assert "core_question_callback" in inspect.signature(generate_endpoint).parameters


def test_social_studies_prompt_preview_reflects_requested_callback_state() -> None:
    from server.config import ServerConfig
    from server.generate.models import GenerateParams
    from server.generate.service import build_prompt_previews

    config = ServerConfig(api_key="x", data_dir=Path("data"), creative_planning=False)
    app_state = SimpleNamespace(ss_curriculum_context=None)

    previews_by_state = {}
    for enabled in (True, False):
        params = GenerateParams(
            subject="social_studies",
            seed=41,
            content_type="純文字",
            sub_question_count=3,
            disable_reference_fewshot=True,
            core_question_callback=enabled,
        )
        previews_by_state[enabled] = build_prompt_previews(params, config, app_state)

    for enabled, previews in previews_by_state.items():
        text_preview = next(item for item in previews if "subquestion_index" not in item)
        sub_previews = {
            item["subquestion_index"]: item
            for item in previews
            if "subquestion_index" in item
        }
        assert ("## 回扣核心問題" in text_preview["user_prompt"]) is enabled
        assert "## 回扣核心問題" not in sub_previews[1]["user_prompt"]
        assert "## 回扣核心問題" not in sub_previews[2]["user_prompt"]
        assert ("## 回扣核心問題" in sub_previews[3]["user_prompt"]) is enabled


def test_callback_toggle_does_not_change_seeded_social_studies_sampling() -> None:
    from server.generate.models import GenerateParams
    from server.generate.service import _sample_worker_params
    from server.generate.subjects import SUBJECTS

    spec = SUBJECTS["social_studies"]
    common = {
        "subject": "social_studies",
        "seed": 73,
        "content_type": "純文字",
        "sub_question_count": 3,
    }
    params_on = GenerateParams(**common, core_question_callback=True)
    params_off = GenerateParams(**common, core_question_callback=False)
    app_state = SimpleNamespace(ss_curriculum_context=None)
    overrides_on = spec.coerce_overrides(params_on, app_state)
    overrides_off = spec.coerce_overrides(params_off, app_state)

    sampled_on = _sample_worker_params(
        0, params_on, spec, overrides_on, None, app_state=app_state
    )
    sampled_off = _sample_worker_params(
        0, params_off, spec, overrides_off, None, app_state=app_state
    )

    assert sampled_on.model_dump() == sampled_off.model_dump()
