"""Tests for issue #944: QuestionMetadata.model and verification-trail entries
use the dispatched model (config.dispatch_model) rather than the raw configured
model string when LLM_FABLE_DOWNGRADE is on.

TDD: written first; they FAIL until the dispatch_model wraps are added to the
call sites in src/cli.py (math flat) and src/common/generation_core.py (grouped
math / social-studies / natural-sciences).

One test per subject pipeline (metadata) plus one trail test.

Design note: metadata and verification_trail are stripped from the v2 content
signature (CLAUDE.md), so adding dispatch_model here changes no content revision.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from src.config import FABLE_DOWNGRADE_TARGET, Config

# ---------------------------------------------------------------------------
# Shared fake LLM client utilities
# ---------------------------------------------------------------------------


class _FakeMainClient:
    """Fake text-generator client; returns hard-coded JSON on each call."""

    def __init__(self, text_response: dict[str, Any]) -> None:
        self._text = text_response

    def get_observer(self) -> None:
        return None

    def generate_json(self, _system: str, _user: str, **_kwargs: Any) -> dict[str, Any]:
        return self._text

    def generate_image(self, _prompt: str, output_path: Path) -> str:
        output_path.write_bytes(b"png")
        return str(output_path)


class _FakeSubClient:
    """Fake per-subquestion client; returns a minimal subquestion JSON."""

    def __init__(self, subq_fn=None) -> None:
        self._subq_fn = subq_fn or (lambda idx: _minimal_subq(idx))

    def set_observer(self, _obs: Any) -> None:
        pass

    def generate_json(
        self,
        _system: str,
        _user: str,
        *,
        agent_override: str = "",
        **_kwargs: Any,
    ) -> dict[str, Any]:
        try:
            index = int(agent_override.split("#")[1]) if "#" in agent_override else 1
        except (IndexError, ValueError):
            index = 1
        return self._subq_fn(index)


def _minimal_ss_subq(index: int = 1) -> dict[str, Any]:
    return {
        "序號": index,
        "年級": 8,
        "科目": ["地理"],
        "核心素養": ["社-J-A2"],
        "學習內容": [{"編碼": "地Af-Ⅳ-3", "說明": "都市"}],
        "學習表現": [{"編碼": "社1b-Ⅳ-1", "說明": "解析"}],
        "出題概念": "概念",
        "題型": "選擇題",
        "題目": "根據文本，以下何者正確？（A）甲（B）乙（C）丙（D）丁",
        "答案": "A",
        "答案解析": "解析",
        "評分規準": [],
    }


def _minimal_ns_subq(index: int = 1) -> dict[str, Any]:
    return {
        "序號": index,
        "年級": 8,
        "科目": ["自然科學"],
        "科學能力": ["能力一"],
        "核心素養": [],
        "學習內容": [{"編碼": "INc-IV-1", "說明": "細胞"}],
        "學習表現": [{"編碼": "tr-IV-1", "說明": "推理"}],
        "出題概念": "概念",
        "題型": "Simple-multiple-choice",
        "題目": "根據文本，以下何者正確？（A）甲（B）乙（C）丙（D）丁",
        "答案": "A",
        "答案解析": "解析",
        "評分規準": [],
    }


def _minimal_subq(index: int = 1) -> dict[str, Any]:
    return _minimal_ss_subq(index)


def _fable_config(tmp_path: Path) -> Config:
    return Config(
        api_key="test-only",
        model_execute="claude-fable-5",
        model_verify="claude-fable-5",
        model_plan="claude-fable-5",
        model_correct="",
        effort_execute="high",
        effort_verify="high",
        effort_plan="high",
        effort_correct="",
        rate_limit_delay=0,
        llm_stream=False,
        fable_downgrade=True,
        output_dir=tmp_path,
        data_dir=Path("data"),
    )


def _non_fable_config(tmp_path: Path) -> Config:
    return Config(
        api_key="test-only",
        model_execute="claude-opus-4-6",
        model_verify="claude-opus-4-6",
        model_plan="claude-opus-4-6",
        model_correct="",
        effort_execute="high",
        effort_verify="high",
        effort_plan="high",
        effort_correct="",
        rate_limit_delay=0,
        llm_stream=False,
        fable_downgrade=False,
        output_dir=tmp_path,
        data_dir=Path("data"),
    )


# ---------------------------------------------------------------------------
# Math flat pipeline: generate_one without sub_question_count
# ---------------------------------------------------------------------------


def _math_flat_raw() -> dict[str, Any]:
    return {
        "情境": ["個人"],
        "題型種類": "單一題",
        "題型": "選擇題",
        "數學思考": ["形成"],
        "學習內容": [{"編碼": "N-7-1", "說明": "整數"}],
        "題目": ["計算 1+1", "(A) 2  (B) 3"],
        "正確解題分析": ["答案 A"],
        "核心素養": [],
        "學習表現": [],
    }


def _make_math_params():
    """Build minimal math SampledParams (no sub_question_count)."""
    from src.schema_loader import load_schemas
    schemas = load_schemas()
    from src.schemas import (
        MathThinking,
        QuestionContext,
        QuestionSetType,
        QuestionStyle,
        QuestionType,
        SampledParams,
    )
    return SampledParams(
        grade=7,
        情境=[QuestionContext("個人")],
        題型種類=QuestionSetType("單一題"),
        題型=QuestionType("選擇題"),
        數學思考=[MathThinking("形成")],
        學習內容=[{"編碼": "N-7-1", "說明": "整數"}],
        style=QuestionStyle(schemas["question_style"][0]["value"]),
    )


def test_math_flat_metadata_model_dispatched_when_fable_downgrade_on(tmp_path: Path) -> None:
    """math flat: metadata.model names the dispatched (Opus 4.6) model, not Fable."""
    from src.cli import generate_one
    from src.schemas import ExamQuestion

    config = _fable_config(tmp_path)
    # sanity check — verify the dispatch mapping
    assert config.dispatch_model("claude-fable-5") == FABLE_DOWNGRADE_TARGET

    client = _FakeMainClient(_math_flat_raw())
    params = _make_math_params()

    result = generate_one(
        config=config,
        client=client,
        curriculum=[],
        performance={},
        intro_text="",
        grade_content={7: []},
        params=params,
        question_id="q_math_flat_001",
        skip_verify=True,
        disable_reference_fewshot=True,
    )

    assert isinstance(result, ExamQuestion)
    assert result.metadata is not None
    # Before fix: metadata.model == "claude-fable-5" → assertion FAILS
    # After fix:  metadata.model == "claude-opus-4-6" → assertion PASSES
    assert result.metadata.model == FABLE_DOWNGRADE_TARGET, (
        f"Expected metadata.model={FABLE_DOWNGRADE_TARGET!r}, "
        f"got {result.metadata.model!r}"
    )


def test_math_flat_metadata_model_unchanged_when_fable_downgrade_off(tmp_path: Path) -> None:
    """math flat: metadata.model stays the configured model when switch is off."""
    from src.cli import generate_one
    from src.schemas import ExamQuestion

    config = _non_fable_config(tmp_path)
    client = _FakeMainClient(_math_flat_raw())
    params = _make_math_params()

    result = generate_one(
        config=config,
        client=client,
        curriculum=[],
        performance={},
        intro_text="",
        grade_content={7: []},
        params=params,
        question_id="q_math_flat_002",
        skip_verify=True,
        disable_reference_fewshot=True,
    )

    assert isinstance(result, ExamQuestion)
    assert result.metadata is not None
    assert result.metadata.model == "claude-opus-4-6"


# ---------------------------------------------------------------------------
# Social studies pipeline: generate_one via generation_core
# ---------------------------------------------------------------------------


def _ss_text_raw() -> dict[str, Any]:
    return {
        "核心問題": "什麼是民主？",
        "文本": "民主是一種政治制度。",
        "取材來源": ["教科書"],
        "subquestions": [
            {"序號": 1, "題型": "選擇題", "出題概念": "概念一"},
            {"序號": 2, "題型": "選擇題", "出題概念": "概念二"},
            {"序號": 3, "題型": "選擇題", "出題概念": "概念三"},
        ],
    }


def test_ss_metadata_model_dispatched_when_fable_downgrade_on(tmp_path: Path) -> None:
    """social studies: metadata.model names the dispatched model, not Fable."""
    from src.social_studies.cli import generate_one
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import ExamQuestion

    config = _fable_config(tmp_path)

    main_client = _FakeMainClient(_ss_text_raw())
    params = sample_params(seed=123, sub_question_count=3)
    sub_client = _FakeSubClient(_minimal_ss_subq)

    result = generate_one(
        config=config,
        client=main_client,
        params=params,
        question_id="q_ss_001",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: sub_client,
    )

    assert isinstance(result, ExamQuestion)
    assert result.metadata is not None
    # Before fix: metadata.model == "claude-fable-5" → FAILS
    # After fix:  metadata.model == "claude-opus-4-6" → PASSES
    assert result.metadata.model == FABLE_DOWNGRADE_TARGET, (
        f"Expected {FABLE_DOWNGRADE_TARGET!r}, got {result.metadata.model!r}"
    )


def test_ss_metadata_model_unchanged_when_fable_downgrade_off(tmp_path: Path) -> None:
    """social studies: metadata.model stays the configured model when switch is off."""
    from src.social_studies.cli import generate_one
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import ExamQuestion

    config = _non_fable_config(tmp_path)

    main_client = _FakeMainClient(_ss_text_raw())
    params = sample_params(seed=123, sub_question_count=3)
    sub_client = _FakeSubClient(_minimal_ss_subq)

    result = generate_one(
        config=config,
        client=main_client,
        params=params,
        question_id="q_ss_002",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: sub_client,
    )

    assert isinstance(result, ExamQuestion)
    assert result.metadata is not None
    assert result.metadata.model == "claude-opus-4-6"


# ---------------------------------------------------------------------------
# Natural sciences pipeline: generate_one via generation_core
# ---------------------------------------------------------------------------


def _ns_text_raw() -> dict[str, Any]:
    return {
        "核心問題": "什麼是光合作用？",
        "文本": "植物通過光合作用將陽光轉化為能量。",
        "取材來源": ["教科書"],
        "subquestions": [
            {"序號": 1, "題型": "Simple-multiple-choice", "出題概念": "概念一"},
            {"序號": 2, "題型": "Simple-multiple-choice", "出題概念": "概念二"},
            {"序號": 3, "題型": "Simple-multiple-choice", "出題概念": "概念三"},
        ],
    }


def test_ns_metadata_model_dispatched_when_fable_downgrade_on(tmp_path: Path) -> None:
    """natural sciences: metadata.model names the dispatched model, not Fable."""
    from src.natural_sciences.cli import generate_one
    from src.natural_sciences.sampler import sample_params
    from src.natural_sciences.schemas import ExamQuestion

    config = _fable_config(tmp_path)

    main_client = _FakeMainClient(_ns_text_raw())
    params = sample_params(seed=456, sub_question_count=3)
    sub_client = _FakeSubClient(_minimal_ns_subq)

    result = generate_one(
        config=config,
        client=main_client,
        params=params,
        question_id="q_ns_001",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: sub_client,
    )

    assert isinstance(result, ExamQuestion)
    assert result.metadata is not None
    # Before fix: metadata.model == "claude-fable-5" → FAILS
    # After fix:  metadata.model == "claude-opus-4-6" → PASSES
    assert result.metadata.model == FABLE_DOWNGRADE_TARGET, (
        f"Expected {FABLE_DOWNGRADE_TARGET!r}, got {result.metadata.model!r}"
    )


def test_ns_metadata_model_unchanged_when_fable_downgrade_off(tmp_path: Path) -> None:
    """natural sciences: metadata.model stays the configured model when switch is off."""
    from src.natural_sciences.cli import generate_one
    from src.natural_sciences.sampler import sample_params
    from src.natural_sciences.schemas import ExamQuestion

    config = _non_fable_config(tmp_path)

    main_client = _FakeMainClient(_ns_text_raw())
    params = sample_params(seed=456, sub_question_count=3)
    sub_client = _FakeSubClient(_minimal_ns_subq)

    result = generate_one(
        config=config,
        client=main_client,
        params=params,
        question_id="q_ns_002",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: sub_client,
    )

    assert isinstance(result, ExamQuestion)
    assert result.metadata is not None
    assert result.metadata.model == "claude-opus-4-6"


# ---------------------------------------------------------------------------
# Verification trail: model field uses dispatched model
# ---------------------------------------------------------------------------


def _make_fake_verification_result() -> SimpleNamespace:
    return SimpleNamespace(
        passed=True,
        details="ok",
        my_answer="A",
        provided_answer="A",
        answer_match=True,
        chart_verification=None,
    )


def test_verification_trail_uses_dispatched_verify_model() -> None:
    """_emit_trail in generation_core.py uses dispatch_model for trail entries."""
    from src.common import generation_core
    from src.common.verification_trail import VerificationTrailEntry

    config = Config(
        api_key="test-only",
        model_execute="claude-fable-5",
        model_verify="claude-fable-5",
        model_plan="claude-fable-5",
        model_correct="",
        effort_execute="high",
        effort_verify="high",
        effort_plan="high",
        effort_correct="",
        rate_limit_delay=0,
        llm_stream=False,
        fable_downgrade=True,
    )

    entries: list[Any] = []

    def capture(entry: Any) -> None:
        entries.append(entry)

    result = _make_fake_verification_result()
    # The call site in generation_core.py should pass config.dispatch_model(...)
    # This test verifies the correct dispatched model ends up in the trail entry.
    verify_model_raw = config.model_verify or config.model_execute
    verify_model_dispatched = config.dispatch_model(verify_model_raw)
    assert verify_model_dispatched == FABLE_DOWNGRADE_TARGET

    generation_core._emit_trail(capture, "q_trail_001", result, verify_model_dispatched)

    assert len(entries) == 1
    assert isinstance(entries[0], VerificationTrailEntry)
    assert entries[0].model == FABLE_DOWNGRADE_TARGET


def test_verification_trail_model_unchanged_when_switch_off() -> None:
    """When switch is off, _emit_trail produces trail with the configured model."""
    from src.common import generation_core
    from src.common.verification_trail import VerificationTrailEntry

    config = Config(
        api_key="test-only",
        model_execute="claude-opus-4-6",
        model_verify="claude-opus-4-6",
        model_plan="claude-opus-4-6",
        model_correct="",
        effort_execute="high",
        effort_verify="high",
        effort_plan="high",
        effort_correct="",
        rate_limit_delay=0,
        llm_stream=False,
        fable_downgrade=False,
    )

    entries: list[Any] = []

    def capture(entry: Any) -> None:
        entries.append(entry)

    result = _make_fake_verification_result()
    verify_model = config.dispatch_model(config.model_verify or config.model_execute)
    assert verify_model == "claude-opus-4-6"

    generation_core._emit_trail(capture, "q_trail_002", result, verify_model)

    assert len(entries) == 1
    assert isinstance(entries[0], VerificationTrailEntry)
    assert entries[0].model == "claude-opus-4-6"
