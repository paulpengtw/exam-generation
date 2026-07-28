from __future__ import annotations

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


def test_preview_never_constructs_an_llm_client(monkeypatch) -> None:
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

    previews = build_prompt_previews(
        GenerateParams(subject="math", seed=190),
        config,
        _math_state(config),
    )

    assert len(previews) == 1


def test_preview_route_uses_generate_auth_dependency() -> None:
    route = next(route for route in router.routes if route.path == "/api/generate/preview")

    dependencies = {dependency.call for dependency in route.dependant.dependencies}

    assert get_current_user in dependencies
