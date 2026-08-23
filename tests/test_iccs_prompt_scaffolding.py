from __future__ import annotations

import json
from pathlib import Path

PROCESS_BUCKETS = (
    "Knowing–Defining and Describing",
    "Knowing–Illustrating with examples",
    "Reasoning and Applying–Interpret information",
    "Reasoning and Applying–Relate or Integrate",
)


def _domain_instruction_clauses(params) -> tuple[str, str]:
    from src.social_studies.schema_loader import build_instructions, load_schemas

    instruction = build_instructions(load_schemas())["內容領域"][params.內容領域.value]
    theme_clause = next(clause for clause in instruction.split("；") if "主題鏡頭" in clause)
    code_clause = next(clause for clause in instruction.split("；") if "公-開頭" in clause)
    return theme_clause, code_clause


def test_process_exemplar_loader_has_non_empty_entries_for_all_iccs_buckets() -> None:
    from src.social_studies.process_exemplar_loader import load_process_exemplars

    exemplars = load_process_exemplars()

    for bucket in PROCESS_BUCKETS:
        assert exemplars[bucket]
        assert all(
            entry["題幹"].strip()
            and entry["答案"].strip()
            and entry["rationale"].strip()
            for entry in exemplars[bucket]
        )


def test_process_exemplar_loader_returns_empty_for_unknown_bucket(tmp_path: Path) -> None:
    from src.social_studies.process_exemplar_loader import load_process_exemplars

    exemplars = load_process_exemplars(tmp_path)

    assert exemplars.get("not-a-real-process", []) == []


def test_process_exemplar_loader_discovers_new_keyed_file_without_code_change(
    tmp_path: Path,
) -> None:
    from src.social_studies.process_exemplar_loader import load_process_exemplars

    synthetic = {
        "Knowing–Defining and Describing": [
            {
                "題幹": "未來新增的題幹",
                "選項": {"A": "甲", "B": "乙"},
                "答案": "A",
                "rationale": "未來新增的設計說明",
            }
        ]
    }
    (tmp_path / "future.json").write_text(
        json.dumps(synthetic, ensure_ascii=False),
        encoding="utf-8",
    )

    exemplars = load_process_exemplars(tmp_path)

    assert exemplars["Knowing–Defining and Describing"] == synthetic[
        "Knowing–Defining and Describing"
    ]


def test_process_exemplar_loader_skips_entries_missing_required_fields(
    tmp_path: Path,
) -> None:
    from src.social_studies.process_exemplar_loader import load_process_exemplars

    bucket = "Knowing–Defining and Describing"
    valid = {
        "題幹": "有效題幹",
        "選項": {"A": "甲"},
        "答案": "A",
        "rationale": "有效設計說明",
    }
    payload = {
        bucket: [
            valid,
            {"題幹": "", "選項": {"A": "甲"}, "答案": "A", "rationale": "說明"},
            {"題幹": "題幹", "選項": {"A": "甲"}, "答案": "", "rationale": "說明"},
            {"題幹": "題幹", "選項": {"A": "甲"}, "答案": "A", "rationale": ""},
            {"題幹": "題幹", "選項": [], "答案": "A", "rationale": "說明"},
            {"題幹": ["錯誤型別"], "選項": {"A": "甲"}, "答案": "A", "rationale": "說明"},
        ]
    }
    (tmp_path / "malformed.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    exemplars = load_process_exemplars(tmp_path)

    assert exemplars[bucket] == [valid]


def test_process_exemplar_loader_fails_open_when_directory_cannot_be_read() -> None:
    from src.social_studies.process_exemplar_loader import (
        PROCESS_BUCKETS,
        load_process_exemplars,
    )

    class UnreadablePath:
        def is_file(self):
            raise OSError("permission denied")

    exemplars = load_process_exemplars(UnreadablePath())

    assert exemplars == {bucket: [] for bucket in PROCESS_BUCKETS}


def test_newly_built_social_prompts_do_not_expose_retired_reading_axes(tmp_path: Path) -> None:
    import random

    from src.social_studies.context_builder import (
        build_subquestion_system_prompt,
        build_subquestion_user_prompt,
        build_system_prompt,
        build_text_system_prompt,
        build_text_user_prompt,
        build_user_prompt,
    )
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=491, sub_question_count=3, content_type="純文字")
    user_prompt, _ = build_user_prompt(
        params,
        tmp_path,
        rng=random.Random(491),
        disable_reference_fewshot=True,
    )
    text_user_prompt, _ = build_text_user_prompt(
        params,
        tmp_path,
        rng=random.Random(491),
        disable_reference_fewshot=True,
    )
    enabled_text_user_prompt, _ = build_text_user_prompt(
        params,
        Path("data/social_studies/few_shot"),
        rng=random.Random(491),
    )
    sub_user_prompt, _ = build_subquestion_user_prompt(
        核心問題="測試核心問題",
        文本="測試文本",
        取材來源=["測試來源"],
        sq_plan={"序號": 1, "題型": "選擇題", "出題概念": "測試"},
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(491),
        cfg=params.subquestion_configs[0],
        disable_reference_fewshot=True,
    )

    for prompt in (
        build_system_prompt(),
        user_prompt,
        build_text_system_prompt(params=params),
        text_user_prompt,
        enabled_text_user_prompt,
        build_subquestion_system_prompt("第四學習階段"),
        sub_user_prompt,
    ):
        assert "閱讀歷程" not in prompt
        assert "文本形式" not in prompt
        assert "PISA閱讀" not in prompt


def test_text_prompt_uses_subject_specific_content_domain_instruction(tmp_path: Path) -> None:
    import random

    from src.social_studies.context_builder import build_text_user_prompt
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import QuestionSubject

    history_subject = next(subject for subject in QuestionSubject if subject.value == "歷史")
    civic_subject = next(
        subject for subject in QuestionSubject if subject.value == "公民與社會"
    )
    history = sample_params(seed=491, subject=[history_subject], content_type="純文字")
    civic = sample_params(seed=491, subject=[civic_subject], content_type="純文字")

    history_prompt, _ = build_text_user_prompt(
        history,
        tmp_path,
        rng=random.Random(491),
        disable_reference_fewshot=True,
    )
    civic_prompt, _ = build_text_user_prompt(
        civic,
        tmp_path,
        rng=random.Random(491),
        disable_reference_fewshot=True,
    )
    history_clause, _ = _domain_instruction_clauses(history)
    _, civic_clause = _domain_instruction_clauses(civic)

    assert history.內容領域.value in history_prompt
    assert history_clause in history_prompt
    assert "公-開頭" not in history_prompt
    assert civic.內容領域.value in civic_prompt
    assert civic_clause in civic_prompt
    assert "主題鏡頭" not in civic_prompt


def test_subquestion_prompt_injects_assigned_process_design_guidance(tmp_path: Path) -> None:
    import random

    from src.social_studies.context_builder import build_subquestion_user_prompt
    from src.social_studies.sampler import sample_params
    from src.social_studies.schema_loader import build_instructions, load_schemas

    params = sample_params(seed=491, sub_question_count=3, content_type="純文字")
    assigned = params.subquestion_configs[0].認知歷程
    guidance = build_instructions(load_schemas())["認知歷程"][assigned]

    prompt, _ = build_subquestion_user_prompt(
        核心問題="測試核心問題",
        文本="測試文本",
        取材來源=["測試來源"],
        sq_plan={"序號": 1, "題型": "選擇題", "出題概念": "測試"},
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(491),
        cfg=params.subquestion_configs[0],
        disable_reference_fewshot=True,
    )

    assert f"- **內容領域**：{params.內容領域.value}" in prompt
    assert f"- **認知歷程**：{assigned}" in prompt
    assert guidance in prompt


def test_text_shell_keeps_sampled_reading_tags_when_model_omits_them(tmp_path: Path) -> None:
    from src.social_studies.cli import _parse_text_shell
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=491, content_type="純文字")
    question = _parse_text_shell(
        {"核心問題": "測試核心問題", "文本": "測試文本", "取材來源": []},
        "iccs-tag-guard",
        params,
        "test-model",
    )

    assert question.閱讀歷程 == [process.value for process in params.閱讀歷程]
    assert question.文本形式 == params.文本形式.value


def _build_channel2_subquestion_prompt(params, few_shot_dir: Path, rng) -> str:
    from src.social_studies.context_builder import build_subquestion_user_prompt

    prompt, _ = build_subquestion_user_prompt(
        核心問題="測試核心問題",
        文本="測試文本",
        取材來源=["測試來源"],
        sq_plan={"序號": 1, "題型": "選擇題", "出題概念": "測試"},
        params=params,
        few_shot_dir=few_shot_dir,
        rng=rng,
        cfg=params.subquestion_configs[0],
    )
    return prompt


def test_subquestion_prompt_injects_one_matching_channel2_exemplar(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import random

    import src.social_studies.context_builder as context_builder
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=491, sub_question_count=3, content_type="純文字")
    bucket = params.subquestion_configs[0].認知歷程
    exemplar = {
        "題幹": "Channel 2 sentinel stem",
        "選項": {"A": "甲", "B": "乙"},
        "答案": "A",
        "rationale": "Channel 2 sentinel rationale",
    }
    monkeypatch.setattr(
        context_builder,
        "load_process_exemplars",
        lambda: {bucket: [exemplar]},
        raising=False,
    )

    prompt = _build_channel2_subquestion_prompt(params, tmp_path, random.Random(17))

    assert "Channel 2 sentinel stem" in prompt
    assert "Channel 2 sentinel rationale" in prompt
    assert "（A）甲" in prompt
    assert "- **答案**：A" in prompt


def test_subquestion_prompt_degrades_to_instruction_only_for_keyless_bucket(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import random

    import src.social_studies.context_builder as context_builder
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=491, sub_question_count=3, content_type="純文字")
    monkeypatch.setattr(context_builder, "load_process_exemplars", lambda: {}, raising=False)

    prompt = _build_channel2_subquestion_prompt(params, tmp_path, random.Random(17))

    assert "認知歷程設計指引" in prompt
    assert "Channel 2" not in prompt


def test_disable_reference_fewshot_skips_channel2_loader(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import random

    import src.social_studies.context_builder as context_builder
    from src.social_studies.context_builder import build_subquestion_user_prompt
    from src.social_studies.sampler import sample_params

    called = False

    def fail_if_called():
        nonlocal called
        called = True
        raise AssertionError("Channel 2 loader must be skipped when references are disabled")

    monkeypatch.setattr(context_builder, "load_process_exemplars", fail_if_called, raising=False)
    params = sample_params(seed=491, sub_question_count=3, content_type="純文字")

    prompt, _ = build_subquestion_user_prompt(
        核心問題="測試核心問題",
        文本="測試文本",
        取材來源=["測試來源"],
        sq_plan={"序號": 1, "題型": "選擇題", "出題概念": "測試"},
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(17),
        cfg=params.subquestion_configs[0],
        disable_reference_fewshot=True,
    )

    assert not called
    assert "Channel 2" not in prompt


def test_channel2_exemplar_choice_is_seed_deterministic(tmp_path: Path, monkeypatch) -> None:
    import random

    import src.social_studies.context_builder as context_builder
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=491, sub_question_count=3, content_type="純文字")
    bucket = params.subquestion_configs[0].認知歷程
    exemplars = [
        {
            "題幹": "Channel 2 deterministic A",
            "選項": {"A": "甲"},
            "答案": "A",
            "rationale": "rationale A",
        },
        {
            "題幹": "Channel 2 deterministic B",
            "選項": {"A": "乙"},
            "答案": "A",
            "rationale": "rationale B",
        },
    ]
    monkeypatch.setattr(
        context_builder,
        "load_process_exemplars",
        lambda: {bucket: exemplars},
        raising=False,
    )

    first = _build_channel2_subquestion_prompt(params, tmp_path, random.Random(23))
    second = _build_channel2_subquestion_prompt(params, tmp_path, random.Random(23))

    assert first == second
    assert "Channel 2 deterministic" in first
