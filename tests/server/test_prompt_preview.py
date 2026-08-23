from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from server.config import ServerConfig
from server.auth.dependencies import get_current_user
from server.generate.routes import router
from server.generate.models import GenerateParams
from server.generate.service import build_prompt_previews
from src.cli import generate_one as generate_math
from src.curriculum_context import load_curriculum_context
from src.data_loader import (
    get_grade_content,
    load_curriculum,
    load_intro_text,
    load_performance_standards,
)
from src.sampler import sample_params as sample_math
from src.natural_sciences.cli import generate_one as generate_natural_sciences
from src.natural_sciences.sampler import sample_params as sample_natural_sciences
from src.social_studies.cli import generate_one as generate_social_studies
from src.social_studies.sampler import sample_params as sample_social_studies


class _CapturingClient:
    def __init__(self, payload: dict) -> None:
        self.prompts: tuple[str, str] | None = None
        self.payload = payload

    def get_observer(self):
        return None

    def generate_json(self, system: str, user: str, **_kwargs):
        self.prompts = (system, user)
        return self.payload


class _CapturingSubClient:
    def __init__(self, prompts_by_idx: dict[int, tuple[str, str]], question_type: str) -> None:
        self.prompts_by_idx = prompts_by_idx
        self.question_type = question_type

    def set_observer(self, _observer) -> None:
        pass

    def generate_json(
        self,
        system: str,
        user: str,
        *,
        agent_override: str,
        **_kwargs,
    ):
        idx = int(agent_override.split("#", 1)[1])
        self.prompts_by_idx[idx] = (system, user)
        return {
            "序號": idx,
            "題型": self.question_type,
            "題目": f"第{idx}小題",
            "答案": "A",
            "答案解析": "解析",
            "出題概念": f"概念{idx}",
        }


def _math_state(config: ServerConfig) -> SimpleNamespace:
    curriculum = load_curriculum(config.data_dir / "curriculum" / "學習內容.json")
    return SimpleNamespace(
        curriculum=curriculum,
        performance=load_performance_standards(
            config.data_dir / "curriculum" / "學習表現.json"
        ),
        intro_text=load_intro_text(
            Path('Introduction to "學習表現" and "學習階段".md')
        ),
        grade_content={
            grade: get_grade_content(curriculum, grade) for grade in (7, 8, 9)
        },
        math_curriculum_context=load_curriculum_context(),
    )


def test_math_preview_is_byte_identical_to_submit_prompt() -> None:
    seed = 187
    config = ServerConfig(api_key="x", data_dir=Path("data"), creative_planning=False)
    app_state = _math_state(config)
    params = GenerateParams(
        subject="math", seed=seed, disable_reference_fewshot=True
    )

    preview = build_prompt_previews(params, config, app_state)[0]
    sampled = sample_math(grade_content=app_state.grade_content, seed=seed)
    capture = _CapturingClient(
        {
            "情境": ["個人"],
            "題型種類": "單一題",
            "題型": "選擇題",
            "數學思考": ["運用"],
            "學習內容": [{"編碼": "N-7-1", "說明": "測試"}],
            "題目": ["測試題目"],
            "正確解題分析": ["測試解析"],
        }
    )
    generate_math(
        config=config,
        client=capture,
        curriculum=app_state.curriculum,
        performance=app_state.performance,
        intro_text=app_state.intro_text,
        grade_content=app_state.grade_content,
        params=sampled,
        question_id="preview-equality",
        skip_verify=True,
        curriculum_context=app_state.math_curriculum_context,
    )

    assert capture.prompts is not None
    assert preview["system_prompt"] == capture.prompts[0]
    assert preview["user_prompt"] == capture.prompts[1]


def test_predrawn_fields_are_persisted_but_do_not_change_seed_pinned_preview() -> None:
    seed = 196
    config = ServerConfig(api_key="x", data_dir=Path("data"), creative_planning=False)
    app_state = _math_state(config)
    baseline = GenerateParams(
        subject="math",
        seed=seed,
        disable_reference_fewshot=True,
    )
    with_metadata = GenerateParams(
        subject="math",
        seed=seed,
        disable_reference_fewshot=True,
        predrawn_fields='["learning_content", "per_question_params[0].seed"]',
    )

    assert with_metadata.model_dump(mode="json")["predrawn_fields"] == (
        '["learning_content", "per_question_params[0].seed"]'
    )
    assert build_prompt_previews(baseline, config, app_state) == build_prompt_previews(
        with_metadata,
        config,
        app_state,
    )


def test_social_studies_preview_is_byte_identical_to_text_generator_prompt() -> None:
    seed = 188
    config = ServerConfig(api_key="x", data_dir=Path("data"), creative_planning=False)
    app_state = SimpleNamespace(ss_curriculum_context=None)
    params = GenerateParams(
        subject="social_studies",
        seed=seed,
        disable_reference_fewshot=False,
        content_type="純文字",
    )

    preview = build_prompt_previews(params, config, app_state)[0]
    sampled = sample_social_studies(seed=seed, content_type="純文字")
    capture = _CapturingClient(
        {
            "核心問題": "測試核心問題",
            "文本": "測試文本",
            "取材來源": ["測試來源"],
            "subquestions": [],
        }
    )
    generate_social_studies(
        config=config,
        client=capture,
        params=sampled,
        question_id="preview-equality",
        skip_verify=True,
    )

    assert capture.prompts is not None
    assert preview["system_prompt"] == capture.prompts[0]
    assert preview["user_prompt"] == capture.prompts[1]


def test_balanced_batch_preview_shows_the_spread_instruction_in_every_question() -> None:
    config = ServerConfig(api_key="x", data_dir=Path("data"), creative_planning=False)
    app_state = SimpleNamespace(ss_curriculum_context=None)
    params = GenerateParams(
        subject="social_studies",
        count=3,
        coverage_mode="balanced",
        seed=193,
    )

    previews = build_prompt_previews(params, config, app_state)
    text_previews = [
        preview for preview in previews if "subquestion_index" not in preview
    ]

    assert len(text_previews) == 3
    assert all(
        "## 出題模式：均衡" in preview["user_prompt"]
        for preview in text_previews
    )


def test_random_batch_preview_omits_the_spread_instruction() -> None:
    config = ServerConfig(api_key="x", data_dir=Path("data"), creative_planning=False)
    app_state = SimpleNamespace(ss_curriculum_context=None)
    params = GenerateParams(
        subject="social_studies",
        count=3,
        coverage_mode="random",
        seed=194,
    )

    previews = build_prompt_previews(params, config, app_state)
    text_previews = [
        preview for preview in previews if "subquestion_index" not in preview
    ]

    assert len(text_previews) == 3
    assert all(
        "## 出題模式：均衡" not in preview["user_prompt"]
        for preview in text_previews
    )


def test_count_one_preview_omits_the_spread_instruction_even_under_balanced() -> None:
    config = ServerConfig(api_key="x", data_dir=Path("data"), creative_planning=False)
    app_state = SimpleNamespace(ss_curriculum_context=None)
    params = GenerateParams(
        subject="social_studies",
        count=1,
        coverage_mode="balanced",
        seed=195,
    )

    previews = build_prompt_previews(params, config, app_state)
    text_previews = [
        preview for preview in previews if "subquestion_index" not in preview
    ]

    assert len(text_previews) == 1
    assert "## 出題模式：均衡" not in text_previews[0]["user_prompt"]


def test_social_studies_sub_generator_previews_are_byte_identical_after_placeholder_substitution() -> None:
    seed = 191
    config = ServerConfig(api_key="x", data_dir=Path("data"), creative_planning=False)
    app_state = SimpleNamespace(ss_curriculum_context=None)
    params = GenerateParams(
        subject="social_studies",
        seed=seed,
        disable_reference_fewshot=True,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs="""[
            {
                "question_type": "開放式建構反應題",
                "instruction": "逐字保留這項出題指示",
                "question_word_limit": 42,
                "option_word_limit": 17,
                "learning_content": ["歷Ka-Ⅳ-1"],
                "learning_performance": ["社1b-Ⅳ-1"]
            }
        ]""",
    )
    text_payload = {
        "核心問題": "真實核心問題",
        "文本": "真實文本",
        "取材來源": ["真實來源"],
        "subquestions": [
            {"序號": i, "題型": "選擇題", "出題概念": f"概念{i}"}
            for i in range(1, 4)
        ],
    }

    previews = build_prompt_previews(params, config, app_state)
    sampled = sample_social_studies(
        seed=seed,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[
            {
                "question_type": "開放式建構反應題",
                "instruction": "逐字保留這項出題指示",
                "question_word_limit": 42,
                "option_word_limit": 17,
                "learning_content": ["歷Ka-Ⅳ-1"],
                "learning_performance": ["社1b-Ⅳ-1"],
            }
        ],
    )
    captured: dict[int, tuple[str, str]] = {}
    generate_social_studies(
        config=config,
        client=_CapturingClient(text_payload),
        params=sampled,
        question_id="preview-sub-generator-equality",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _CapturingSubClient(captured, "選擇題"),
    )

    sub_previews = {
        preview["subquestion_index"]: preview
        for preview in previews
        if "subquestion_index" in preview
    }
    assert set(sub_previews) == {1, 2, 3}
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
    assert "## 各小題配置" in sub_previews[1]["user_prompt"]
    assert "逐字保留這項出題指示" in sub_previews[1]["user_prompt"]
    assert "42" in sub_previews[1]["user_prompt"]
    assert "17" in sub_previews[1]["user_prompt"]
    assert "歷Ka-Ⅳ-1" in sub_previews[1]["user_prompt"]
    assert "社1b-Ⅳ-1" in sub_previews[1]["user_prompt"]


def test_natural_sciences_preview_is_byte_identical_to_text_generator_prompt() -> None:
    seed = 189
    config = ServerConfig(api_key="x", data_dir=Path("data"), creative_planning=False)
    app_state = SimpleNamespace(ns_curriculum_context=None)
    params = GenerateParams(subject="natural_sciences", seed=seed)

    preview = build_prompt_previews(params, config, app_state)[0]
    sampled = sample_natural_sciences(seed=seed)
    capture = _CapturingClient(
        {
            "核心問題": "測試核心問題",
            "文本": "測試文本",
            "取材來源": ["測試來源"],
            "subquestions": [],
        }
    )
    generate_natural_sciences(
        config=config,
        client=capture,
        params=sampled,
        question_id="preview-equality",
        skip_verify=True,
    )

    assert capture.prompts is not None
    assert preview["system_prompt"] == capture.prompts[0]
    assert preview["user_prompt"] == capture.prompts[1]


def test_natural_sciences_preview_with_reporting_scale_is_byte_identical() -> None:
    """Preview byte-identity holds when a 題組-level reporting_scale is supplied."""
    seed = 189
    config = ServerConfig(api_key="x", data_dir=Path("data"), creative_planning=False)
    app_state = SimpleNamespace(ns_curriculum_context=None)
    params = GenerateParams(subject="natural_sciences", seed=seed, reporting_scale="6")

    preview = build_prompt_previews(params, config, app_state)[0]
    sampled = sample_natural_sciences(seed=seed, reporting_scale="6")
    capture = _CapturingClient(
        {
            "核心問題": "測試核心問題",
            "文本": "測試文本",
            "取材來源": ["測試來源"],
            "subquestions": [],
        }
    )
    generate_natural_sciences(
        config=config,
        client=capture,
        params=sampled,
        question_id="preview-rs-equality",
        skip_verify=True,
    )

    assert capture.prompts is not None
    assert preview["system_prompt"] == capture.prompts[0]
    assert preview["user_prompt"] == capture.prompts[1]


def test_natural_sciences_sub_generator_previews_are_byte_identical_after_placeholder_substitution() -> None:
    seed = 192
    config = ServerConfig(api_key="x", data_dir=Path("data"), creative_planning=False)
    app_state = SimpleNamespace(ns_curriculum_context=None)
    slot_config = {
        "question_type": "Constructed response",
        "instruction": "逐字保留自然科學出題指示",
        "question_word_limit": 43,
        "option_word_limit": 18,
        "learning_content": ["INa-Ⅳ-1"],
        "learning_performance": ["pe-Ⅳ-1"],
    }
    params = GenerateParams(
        subject="natural_sciences",
        seed=seed,
        disable_reference_fewshot=True,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=f"[{json.dumps(slot_config, ensure_ascii=False)}]",
    )
    text_payload = {
        "核心問題": "真實自然科學核心問題",
        "文本": "真實自然科學文本",
        "取材來源": ["真實自然科學來源"],
        "subquestions": [
            {
                "序號": i,
                "題型": "Simple multiple-choice",
                "出題概念": f"自然概念{i}",
            }
            for i in range(1, 4)
        ],
    }

    previews = build_prompt_previews(params, config, app_state)
    sampled = sample_natural_sciences(
        seed=seed,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[slot_config],
    )
    captured: dict[int, tuple[str, str]] = {}
    generate_natural_sciences(
        config=config,
        client=_CapturingClient(text_payload),
        params=sampled,
        question_id="preview-natural-sub-generator-equality",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _CapturingSubClient(
            captured,
            "Simple multiple-choice",
        ),
    )

    sub_previews = {
        preview["subquestion_index"]: preview
        for preview in previews
        if "subquestion_index" in preview
    }
    assert set(sub_previews) == {1, 2, 3}
    for idx, real_prompts in captured.items():
        preview = sub_previews[idx]
        substituted_user = (
            preview["user_prompt"]
            .replace("{{核心問題：由前一階段產生}}", text_payload["核心問題"])
            .replace("{{文本：由前一階段產生}}", text_payload["文本"])
            .replace("{{取材來源：由前一階段產生}}", text_payload["取材來源"][0])
            .replace("{{子題 plan：由前一階段產生}}", f"自然概念{idx}")
        )
        assert (preview["system_prompt"], substituted_user) == real_prompts
    assert "## 各小題配置" in sub_previews[1]["user_prompt"]
    assert "逐字保留自然科學出題指示" in sub_previews[1]["user_prompt"]
    assert "43" in sub_previews[1]["user_prompt"]
    assert "18" in sub_previews[1]["user_prompt"]
    assert "INa-Ⅳ-1" in sub_previews[1]["user_prompt"]
    assert "pe-Ⅳ-1" in sub_previews[1]["user_prompt"]


def test_same_confirmation_payload_builds_byte_identical_prompts_with_few_shots() -> None:
    config = ServerConfig(api_key="x", data_dir=Path("data"), creative_planning=False)
    app_state = _math_state(config)
    params = GenerateParams(
        subject="math",
        count=1,
        seed=10,
        per_question_params='[{"seed": 185}]',
        disable_reference_fewshot=False,
    )

    first = build_prompt_previews(params, config, app_state)[0]
    second = build_prompt_previews(params, config, app_state)[0]
    sampled = sample_math(grade_content=app_state.grade_content, seed=185)
    capture = _CapturingClient(
        {
            "情境": ["個人"],
            "題型種類": "單一題",
            "題型": "選擇題",
            "數學思考": ["運用"],
            "學習內容": [{"編碼": "N-7-1", "說明": "測試"}],
            "題目": ["測試題目"],
            "正確解題分析": ["測試解析"],
        }
    )
    generate_math(
        config=config,
        client=capture,
        curriculum=app_state.curriculum,
        performance=app_state.performance,
        intro_text=app_state.intro_text,
        grade_content=app_state.grade_content,
        params=sampled,
        question_id="confirmation-payload-replay",
        skip_verify=True,
        curriculum_context=app_state.math_curriculum_context,
    )

    assert (
        first["system_prompt"].encode(),
        first["user_prompt"].encode(),
    ) == (
        second["system_prompt"].encode(),
        second["user_prompt"].encode(),
    )
    assert capture.prompts == (
        first["system_prompt"],
        first["user_prompt"],
    )
    assert "### 範例 1：" in first["user_prompt"]


def test_preview_never_constructs_an_llm_client_for_any_subject(monkeypatch) -> None:
    def forbidden_client(*_args, **_kwargs):
        raise AssertionError("preview must not construct an LLM client")

    for binding in (
        "server.generate.service.LLMClient",
        "src.cli.LLMClient",
        "src.common.generation_core.LLMClient",
        "src.social_studies.cli.LLMClient",
        "src.natural_sciences.cli.LLMClient",
    ):
        monkeypatch.setattr(binding, forbidden_client)
    config = ServerConfig(api_key="x", data_dir=Path("data"), creative_planning=False)

    cases = (
        (GenerateParams(subject="math", seed=190), _math_state(config)),
        (
            GenerateParams(
                subject="social_studies",
                seed=190,
                content_type="純文字",
                sub_question_count=3,
            ),
            SimpleNamespace(ss_curriculum_context=None),
        ),
        (
            GenerateParams(
                subject="natural_sciences",
                seed=190,
                sub_question_count=3,
            ),
            SimpleNamespace(ns_curriculum_context=None),
        ),
    )

    previews_by_subject = {
        params.subject: build_prompt_previews(params, config, app_state)
        for params, app_state in cases
    }

    assert len(previews_by_subject["math"]) == 1
    assert all(
        "subquestion_index" not in preview
        for preview in previews_by_subject["math"]
    )
    assert len(previews_by_subject["social_studies"]) == 4
    assert len(previews_by_subject["natural_sciences"]) == 4


def test_preview_route_uses_generate_auth_dependency() -> None:
    route = next(route for route in router.routes if route.path == "/api/generate/preview")

    dependencies = {dependency.call for dependency in route.dependant.dependencies}

    assert get_current_user in dependencies
