"""Tests for GitHub issue #374: 驗證模型 (LLM_MODEL_VERIFY) and 修正模型 (LLM_MODEL_CORRECT).

Written test-first per TDD convention: all tests must FAIL (red) before implementation.
After implementation all tests must pass (green).

Run:
    export PATH="$HOME/.local/bin:$PATH" && uv run pytest tests/test_model_tiers_verify_correct.py -v

Study tests/test_llm_effort.py and tests/test_llm_client_openai_compat.py for stubbing style.
"""
from __future__ import annotations

import dataclasses
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

# ── imports that will FAIL until implementation (confirming RED) ───────────────
# EFFORT_LEVELS / DEFAULT_EFFORT_LEVELS must move to src.config (issue #374 §4).
from src.config import Config, EFFORT_LEVELS, DEFAULT_EFFORT_LEVELS  # noqa: E402

# _VERIFY_PURPOSES, _CORRECT_PURPOSES, and _warned_tier_effort_drops are new.
from src.llm_client import (  # noqa: E402
    LLMClient,
    _VERIFY_PURPOSES,
    _CORRECT_PURPOSES,
    _warned_tier_effort_drops,
)
from server.config import ServerConfig  # noqa: E402

# ── pipeline-test subject imports ─────────────────────────────────────────────
from src.verifier import verify_question as math_verify
from src.corrector import correct_question as math_correct
from src.schemas import (
    ExamQuestion as MathExamQuestion,
    LearningContentItem,
    QuestionContext as MathCtx,
    QuestionSetType as MathSetType,
    QuestionType as MathQType,
    MathThinking,
    VerificationResult as MathVerifResult,
    ChartVerificationResult as MathChartVerif,
)

from src.social_studies.verifier import verify_question as ss_verify
from src.social_studies.corrector import correct_question as ss_correct
from src.social_studies.schemas import (
    ExamQuestion as SSExamQuestion,
    SubQuestion as SSSubQuestion,
    QuestionContext as SSCtx,
    QuestionSetType as SSSetType,
    QuestionType as SSQType,
    ReadingProcess,
    TextForm,
    VerificationResult as SSVerifResult,
    ChartVerificationResult as SSChartVerif,
)

from src.natural_sciences.verifier import verify_question as ns_verify
from src.natural_sciences.corrector import correct_question as ns_correct
from src.natural_sciences.schemas import (
    ExamQuestion as NSExamQuestion,
    SubQuestion as NSSubQuestion,
    QuestionContext as NSCtx,
    QuestionSubContext as NSSubCtx,
    QuestionSetType as NSSetType,
    QuestionType as NSQType,
    VerificationResult as NSVerifResult,
    ChartVerificationResult as NSChartVerif,
)

# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

# Verification result JSON that all three verifiers can parse successfully.
_VERIFY_RESPONSE = (
    '{"passed": true, "answer_match": true, "details": "ok",'
    ' "my_answer": "", "provided_answer": ""}'
)


class _FakeMessagesAPI:
    """Records Anthropic messages.create() calls without hitting the network.

    Mirrors the recorder in tests/test_llm_effort.py.
    """

    def __init__(self, response_text: str = _VERIFY_RESPONSE) -> None:
        self.calls: list[dict] = []
        self._response_text = response_text

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content_block = SimpleNamespace(text=self._response_text)
        usage = SimpleNamespace(
            input_tokens=1,
            output_tokens=1,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        return SimpleNamespace(
            content=[content_block],
            stop_reason="end_turn",
            usage=usage,
        )


def _make_tier_client(
    model_execute: str = "claude-sonnet-4-6",
    model_verify: str = "",
    model_correct: str = "",
    effort_execute: str = "medium",
    response_text: str = _VERIFY_RESPONSE,
) -> tuple[LLMClient, _FakeMessagesAPI]:
    """Build a non-streaming Anthropic LLMClient with tier model config and a recorder."""
    cfg = Config(
        api_key="x",
        llm_stream=False,
        model_execute=model_execute,
        model_verify=model_verify,
        model_correct=model_correct,
        effort_execute=effort_execute,
    )
    client = LLMClient(cfg)
    fake = _FakeMessagesAPI(response_text=response_text)
    client.client = SimpleNamespace(messages=fake)
    return client, fake


def _make_math_question() -> MathExamQuestion:
    return MathExamQuestion(
        情境=[next(iter(MathCtx))],
        題型種類=next(iter(MathSetType)),
        題型=next(iter(MathQType)),
        數學思考=[next(iter(MathThinking))],
        學習內容=[LearningContentItem(編碼="N-7-1", 說明="整數")],
        題目=["下列何者正確？"],
        正確解題分析=["答案是 A。"],
    )


def _make_ss_question() -> SSExamQuestion:
    sq = SSSubQuestion(
        序號=1,
        年級=8,
        科目=["歷史"],
        題型=next(iter(SSQType)),
        題目="請回答：",
        答案="A",
    )
    return SSExamQuestion(
        情境=[next(iter(SSCtx))],
        題型種類=next(iter(SSSetType)),
        題型=next(iter(SSQType)),
        閱讀歷程=[next(iter(ReadingProcess))],
        文本形式=next(iter(TextForm)),
        subquestions=[sq],
    )


def _make_ns_question() -> NSExamQuestion:
    sq = NSSubQuestion(
        序號=1,
        年級=8,
        科目=["自然科學"],
        題型=next(iter(NSQType)),
        題目="請回答：",
        答案="A",
    )
    return NSExamQuestion(
        情境=[next(iter(NSCtx))],
        情境子類別=next(iter(NSSubCtx)),
        題型種類=next(iter(NSSetType)),
        題型=next(iter(NSQType)),
        subquestions=[sq],
    )


@pytest.fixture(autouse=False)
def reset_warned_tier_effort_drops():
    """Clear _warned_tier_effort_drops before and after each test.

    Mirrors reset_warned_effort_drops in tests/test_llm_client_openai_compat.py.
    """
    _warned_tier_effort_drops.clear()
    yield
    _warned_tier_effort_drops.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Config defaults and env vars
# ─────────────────────────────────────────────────────────────────────────────


def test_src_config_model_verify_default_empty() -> None:
    """model_verify must default to '' (empty), not the execute model."""
    assert Config().model_verify == ""


def test_src_config_model_correct_default_empty() -> None:
    """model_correct must default to '' (empty), not the execute model."""
    assert Config().model_correct == ""


def test_src_config_model_verify_from_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL_VERIFY", "claude-opus-5")
    monkeypatch.delenv("LLM_MODEL_CORRECT", raising=False)
    cfg = Config.from_env()
    assert cfg.model_verify == "claude-opus-5"


def test_src_config_model_correct_from_env(monkeypatch) -> None:
    monkeypatch.delenv("LLM_MODEL_VERIFY", raising=False)
    monkeypatch.setenv("LLM_MODEL_CORRECT", "claude-fable-5")
    cfg = Config.from_env()
    assert cfg.model_correct == "claude-fable-5"


def test_src_config_both_tier_models_from_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL_VERIFY", "claude-opus-5")
    monkeypatch.setenv("LLM_MODEL_CORRECT", "claude-fable-5")
    cfg = Config.from_env()
    assert cfg.model_verify == "claude-opus-5"
    assert cfg.model_correct == "claude-fable-5"


def test_server_config_model_verify_default_empty() -> None:
    """ServerConfig also exposes model_verify with empty default."""
    cfg = ServerConfig(api_key="x", jwt_secret="s")
    assert cfg.model_verify == ""


def test_server_config_model_correct_default_empty() -> None:
    """ServerConfig also exposes model_correct with empty default."""
    cfg = ServerConfig(api_key="x", jwt_secret="s")
    assert cfg.model_correct == ""


def test_server_config_model_verify_from_env(tmp_path) -> None:
    env = {"LLM_API_KEY": "x", "JWT_SECRET": "s", "LLM_MODEL_VERIFY": "claude-opus-5"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.model_verify == "claude-opus-5"


def test_server_config_model_correct_from_env(tmp_path) -> None:
    env = {"LLM_API_KEY": "x", "JWT_SECRET": "s", "LLM_MODEL_CORRECT": "claude-fable-5"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert cfg.model_correct == "claude-fable-5"


def test_server_config_allowlist_includes_verify_model(tmp_path) -> None:
    """LLM_MODEL_VERIFY is appended to llm_models_allowed (roster §2 in issue)."""
    env = {
        "LLM_API_KEY": "x",
        "JWT_SECRET": "s",
        "LLM_MODEL_VERIFY": "claude-opus-5",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert "claude-opus-5" in cfg.llm_models_allowed


def test_server_config_allowlist_includes_correct_model(tmp_path) -> None:
    """LLM_MODEL_CORRECT is appended to llm_models_allowed (roster §2 in issue)."""
    env = {
        "LLM_API_KEY": "x",
        "JWT_SECRET": "s",
        "LLM_MODEL_CORRECT": "claude-fable-5",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    assert "claude-fable-5" in cfg.llm_models_allowed


def test_server_config_allowlist_empty_tier_models_not_appended(tmp_path) -> None:
    """Empty (unset) tier models must NOT be appended to llm_models_allowed."""
    env = {"LLM_API_KEY": "x", "JWT_SECRET": "s"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    # Empty string should never appear in the allowlist tuple
    assert "" not in cfg.llm_models_allowed


# ─────────────────────────────────────────────────────────────────────────────
# 2. Exact purpose-string matching pin (regression pin against #346-style mismatch)
# ─────────────────────────────────────────────────────────────────────────────


def test_verify_purpose_set_contains_exactly_verify() -> None:
    """_VERIFY_PURPOSES must contain the exact string 'verify'.

    Pin against a #346-style silent mismatch: if the purpose string sent by
    src/verifier.py ('verify') is not in _VERIFY_PURPOSES (e.g. due to a
    typo like 'verification'), the tier silently degrades to the execute model.
    """
    assert "verify" in _VERIFY_PURPOSES


def test_correct_purpose_set_contains_exactly_correct() -> None:
    """_CORRECT_PURPOSES must contain the exact string 'correct'."""
    assert "correct" in _CORRECT_PURPOSES


def test_verify_purpose_routes_to_tier_model_via_generate() -> None:
    """Driving generate() with purpose='verify' must use model_verify on the wire.

    This pin ensures the exact string 'verify' dispatches to the tier model and
    does not silently fall back to model_execute.  A mismatch in _VERIFY_PURPOSES
    would make this assertion fail.
    """
    client, fake = _make_tier_client(
        model_execute="claude-sonnet-4-6",
        model_verify="claude-opus-5",
    )
    client.generate("sys", "user", purpose="verify")
    assert len(fake.calls) == 1
    assert fake.calls[0]["model"] == "claude-opus-5"


def test_correct_purpose_routes_to_tier_model_via_generate() -> None:
    """Driving generate() with purpose='correct' must use model_correct on the wire."""
    client, fake = _make_tier_client(
        model_execute="claude-sonnet-4-6",
        model_correct="claude-fable-5",
    )
    client.generate("sys", "user", purpose="correct")
    assert len(fake.calls) == 1
    assert fake.calls[0]["model"] == "claude-fable-5"


def test_verify_purpose_routes_to_tier_model_via_generate_with_image() -> None:
    """generate_with_image(purpose='verify') must use model_verify."""
    client, fake = _make_tier_client(
        model_execute="claude-sonnet-4-6",
        model_verify="claude-opus-5",
    )
    client.generate_with_image("sys", "user", image_path=None, purpose="verify")
    assert len(fake.calls) == 1
    assert fake.calls[0]["model"] == "claude-opus-5"


def test_correct_purpose_routes_to_tier_model_via_generate_json() -> None:
    """generate_json(purpose='correct') must use model_correct."""
    client, fake = _make_tier_client(
        model_execute="claude-sonnet-4-6",
        model_correct="claude-fable-5",
    )
    client.generate_json("sys", "user", purpose="correct")
    assert len(fake.calls) >= 1
    assert fake.calls[0]["model"] == "claude-fable-5"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Fallback chain
# ─────────────────────────────────────────────────────────────────────────────


def test_verify_falls_back_to_execute_when_model_verify_unset() -> None:
    """When model_verify='' (unset), verify calls use model_execute."""
    client, fake = _make_tier_client(
        model_execute="claude-sonnet-4-6",
        model_verify="",
    )
    client.generate("sys", "user", purpose="verify")
    assert fake.calls[0]["model"] == "claude-sonnet-4-6"


def test_correct_falls_back_to_execute_when_model_correct_unset() -> None:
    """When model_correct='' (unset), correct calls use model_execute."""
    client, fake = _make_tier_client(
        model_execute="claude-sonnet-4-6",
        model_correct="",
    )
    client.generate("sys", "user", purpose="correct")
    assert fake.calls[0]["model"] == "claude-sonnet-4-6"


def test_verify_fallback_uses_overridden_execute_model_after_dataclasses_replace() -> None:
    """When model_verify is unset AND model_execute is overridden via dataclasses.replace,
    verify calls must use the OVERRIDDEN execute model.

    This is the per-request model-override path in server/generate/service.py
    (dataclasses.replace(cfg, model_execute=request_model) before LLMClient is built).
    The default must be '' (not captured at Config init time) so the fallback
    resolves at call time against the effective model_execute.
    """
    base_cfg = Config(
        api_key="x",
        llm_stream=False,
        model_execute="claude-sonnet-4-6",
        model_verify="",  # unset — should fall through to effective execute
    )
    # Simulate the per-request override
    overridden_cfg = dataclasses.replace(base_cfg, model_execute="claude-opus-5")
    client = LLMClient(overridden_cfg)
    fake = _FakeMessagesAPI()
    client.client = SimpleNamespace(messages=fake)

    client.generate("sys", "user", purpose="verify")
    # Must resolve to the OVERRIDDEN execute model, not the original
    assert fake.calls[0]["model"] == "claude-opus-5"


def test_correct_fallback_uses_overridden_execute_model_after_dataclasses_replace() -> None:
    """Parallel test for correct tier fallback."""
    base_cfg = Config(
        api_key="x",
        llm_stream=False,
        model_execute="claude-sonnet-4-6",
        model_correct="",
    )
    overridden_cfg = dataclasses.replace(base_cfg, model_execute="claude-opus-5")
    client = LLMClient(overridden_cfg)
    fake = _FakeMessagesAPI()
    client.client = SimpleNamespace(messages=fake)

    client.generate("sys", "user", purpose="correct")
    assert fake.calls[0]["model"] == "claude-opus-5"


# ─────────────────────────────────────────────────────────────────────────────
# 4. No-change regression (both tier env vars unset)
# ─────────────────────────────────────────────────────────────────────────────


def test_no_change_regression_model_identical_across_generate_verify_correct() -> None:
    """When both tier env vars are unset, verify and correct must use the same
    model as generate — byte-identical to the pre-374 behavior."""
    client, fake = _make_tier_client(
        model_execute="claude-sonnet-4-6",
        model_verify="",
        model_correct="",
        effort_execute="medium",
    )
    client.generate("sys", "user", purpose="generate")
    client.generate("sys", "user", purpose="verify")
    client.generate("sys", "user", purpose="correct")

    models = [c["model"] for c in fake.calls]
    assert models[0] == models[1] == models[2] == "claude-sonnet-4-6"


def test_no_change_regression_effort_kwargs_identical_across_purposes() -> None:
    """When both tier env vars are unset, the effort kwargs for verify/correct
    must be byte-identical to those for generate."""
    client, fake = _make_tier_client(
        model_execute="claude-sonnet-4-6",
        model_verify="",
        model_correct="",
        effort_execute="high",
    )
    client.generate("sys", "user", purpose="generate")
    client.generate("sys", "user", purpose="verify")
    client.generate("sys", "user", purpose="correct")

    extra_bodies = [c.get("extra_body", {}) for c in fake.calls]
    assert extra_bodies[0] == extra_bodies[1] == extra_bodies[2]
    # Confirm effort is actually present and correct
    assert extra_bodies[0].get("output_config", {}).get("effort") == "high"


# ─────────────────────────────────────────────────────────────────────────────
# 5. html_image stays on execute
# ─────────────────────────────────────────────────────────────────────────────


def test_html_image_purpose_stays_on_execute_when_verify_correct_set() -> None:
    """html_image is not in _VERIFY_PURPOSES or _CORRECT_PURPOSES, so it must
    always resolve to model_execute regardless of the tier models."""
    client, fake = _make_tier_client(
        model_execute="claude-sonnet-4-6",
        model_verify="claude-opus-5",
        model_correct="claude-fable-5",
    )
    client.generate("sys", "user", purpose="html_image")
    assert fake.calls[0]["model"] == "claude-sonnet-4-6"


def test_fact_check_purpose_stays_on_execute_when_tier_models_set() -> None:
    """fact_check is not in _VERIFY_PURPOSES or _CORRECT_PURPOSES."""
    client, fake = _make_tier_client(
        model_execute="claude-sonnet-4-6",
        model_verify="claude-opus-5",
        model_correct="claude-fable-5",
    )
    client.generate("sys", "user", purpose="fact_check")
    assert fake.calls[0]["model"] == "claude-sonnet-4-6"


def test_generate_purpose_stays_on_execute_when_tier_models_set() -> None:
    """generate purpose is unaffected by tier models."""
    client, fake = _make_tier_client(
        model_execute="claude-sonnet-4-6",
        model_verify="claude-opus-5",
        model_correct="claude-fable-5",
    )
    client.generate("sys", "user", purpose="generate")
    assert fake.calls[0]["model"] == "claude-sonnet-4-6"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Effort guard (interim guard: diverged tier model + incompatible effort)
# ─────────────────────────────────────────────────────────────────────────────


def test_effort_guard_drops_effort_when_verify_tier_diverges_and_effort_incompatible(
    reset_warned_tier_effort_drops, caplog
) -> None:
    """Verify tier: model diverges from execute AND effort is incompatible → effort dropped.

    Setup: model_execute='claude-opus-5' (supports xhigh), model_verify='claude-sonnet-4-6'
    (only low/medium/high/max — NOT xhigh), effort_execute='xhigh'.
    The guard must drop the effort (return {}) and emit one WARNING.
    """
    client, fake = _make_tier_client(
        model_execute="claude-opus-5",
        model_verify="claude-sonnet-4-6",
        effort_execute="xhigh",
    )
    with caplog.at_level(logging.WARNING, logger="src.llm_client"):
        client.generate("sys", "user", purpose="verify")

    assert len(fake.calls) == 1
    call_kw = fake.calls[0]
    # Effort must be absent (guard dropped it)
    effort_in_call = call_kw.get("extra_body", {}).get("output_config", {}).get("effort")
    assert effort_in_call is None, f"Expected effort to be dropped, got {effort_in_call!r}"


def test_effort_guard_emits_warning_for_dropped_effort(
    reset_warned_tier_effort_drops, caplog
) -> None:
    """The WARNING must mention the tier model and the dropped effort value."""
    client, fake = _make_tier_client(
        model_execute="claude-opus-5",
        model_verify="claude-sonnet-4-6",
        effort_execute="xhigh",
    )
    with caplog.at_level(logging.WARNING, logger="src.llm_client"):
        client.generate("sys", "user", purpose="verify")

    warning_texts = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    # At least one warning must be present
    assert warning_texts, "Expected at least one WARNING log, got none"
    combined = " ".join(warning_texts)
    # The warning must reference the problematic effort value
    assert "xhigh" in combined, f"Expected 'xhigh' in warning; got: {combined!r}"


def test_effort_guard_warning_emitted_only_once_for_same_pair(
    reset_warned_tier_effort_drops, caplog
) -> None:
    """The WARNING must be emitted at most once per (model, effort) pair
    (dedup via _warned_tier_effort_drops)."""
    client, fake = _make_tier_client(
        model_execute="claude-opus-5",
        model_verify="claude-sonnet-4-6",
        effort_execute="xhigh",
    )
    with caplog.at_level(logging.WARNING, logger="src.llm_client"):
        client.generate("sys", "user", purpose="verify")
        client.generate("sys", "user", purpose="verify")  # second call, same pair

    tier_drop_warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "xhigh" in r.message
    ]
    assert len(tier_drop_warnings) == 1, (
        f"Expected exactly 1 tier-effort-drop warning, got {len(tier_drop_warnings)}"
    )


def test_effort_guard_compatible_effort_not_dropped(
    reset_warned_tier_effort_drops, caplog
) -> None:
    """When the inherited effort is valid for the tier model, it must NOT be dropped."""
    # claude-sonnet-4-6 supports high (low/medium/high/max)
    client, fake = _make_tier_client(
        model_execute="claude-opus-5",
        model_verify="claude-sonnet-4-6",
        effort_execute="high",  # compatible with sonnet-4-6
    )
    with caplog.at_level(logging.WARNING, logger="src.llm_client"):
        client.generate("sys", "user", purpose="verify")

    call_kw = fake.calls[0]
    effort_in_call = call_kw.get("extra_body", {}).get("output_config", {}).get("effort")
    assert effort_in_call == "high", f"Expected effort='high' to be kept, got {effort_in_call!r}"

    # No tier-effort-drop warning
    tier_drops = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("tier" in r.message.lower() or "drop" in r.message.lower() for r in tier_drops), (
        "Should emit no tier-effort-drop warning for compatible effort"
    )


def test_effort_guard_no_divergence_never_drops(
    reset_warned_tier_effort_drops, caplog
) -> None:
    """When the tier model IS the execute model (no divergence), the guard must not
    fire even if the effort value would fail the roster check for some other model.

    This preserves the pre-374 behavior when model_verify == model_execute.
    """
    # model_verify == model_execute → no divergence → guard never applies
    client, fake = _make_tier_client(
        model_execute="claude-sonnet-4-6",
        model_verify="claude-sonnet-4-6",  # explicitly same as execute
        effort_execute="medium",
    )
    with caplog.at_level(logging.WARNING, logger="src.llm_client"):
        client.generate("sys", "user", purpose="verify")

    call_kw = fake.calls[0]
    effort_in_call = call_kw.get("extra_body", {}).get("output_config", {}).get("effort")
    assert effort_in_call == "medium", (
        f"Guard should not fire when tier == execute; effort was {effort_in_call!r}"
    )


def test_effort_guard_correct_tier_model_diverges_incompatible(
    reset_warned_tier_effort_drops, caplog
) -> None:
    """Parallel effort-guard test for the correct tier."""
    client, fake = _make_tier_client(
        model_execute="claude-opus-5",
        model_correct="claude-sonnet-4-6",
        effort_execute="xhigh",
    )
    with caplog.at_level(logging.WARNING, logger="src.llm_client"):
        client.generate("sys", "user", purpose="correct")

    call_kw = fake.calls[0]
    effort_in_call = call_kw.get("extra_body", {}).get("output_config", {}).get("effort")
    assert effort_in_call is None, (
        f"Expected effort to be dropped for correct tier; got {effort_in_call!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 7a. EFFORT_LEVELS / DEFAULT_EFFORT_LEVELS moved to src.config
# ─────────────────────────────────────────────────────────────────────────────


def test_src_config_effort_levels_exists_and_has_known_models() -> None:
    """EFFORT_LEVELS is now in src.config and contains the known model roster."""
    assert "claude-opus-5" in EFFORT_LEVELS
    assert "claude-sonnet-4-6" in EFFORT_LEVELS
    assert "claude-fable-5" in EFFORT_LEVELS


def test_src_config_effort_levels_sonnet4_6_no_xhigh() -> None:
    """claude-sonnet-4-6 supports low/medium/high/max but NOT xhigh."""
    levels = EFFORT_LEVELS["claude-sonnet-4-6"]
    assert "xhigh" not in levels
    assert "max" in levels
    assert set(levels) == {"low", "medium", "high", "max"}


def test_src_config_default_effort_levels_is_four_level() -> None:
    """DEFAULT_EFFORT_LEVELS is the fallback roster for unknown models."""
    assert "low" in DEFAULT_EFFORT_LEVELS
    assert "medium" in DEFAULT_EFFORT_LEVELS
    assert "high" in DEFAULT_EFFORT_LEVELS
    assert "max" in DEFAULT_EFFORT_LEVELS
    # Must NOT include xhigh (conservative fallback)
    assert "xhigh" not in DEFAULT_EFFORT_LEVELS


def test_server_config_effort_levels_still_importable() -> None:
    """_EFFORT_LEVELS must still be importable from server.config for backwards compat."""
    from server.config import _EFFORT_LEVELS as server_effort_levels  # noqa: PLC0415
    # Must be the same data as src.config.EFFORT_LEVELS
    assert server_effort_levels is EFFORT_LEVELS or server_effort_levels == EFFORT_LEVELS


# ─────────────────────────────────────────────────────────────────────────────
# 7b. All three subject pipelines — drive real production entrypoints
# ─────────────────────────────────────────────────────────────────────────────

_TIER_VERIFY_MODEL = "claude-opus-5"
_TIER_CORRECT_MODEL = "claude-fable-5"
_EXECUTE_MODEL = "claude-sonnet-4-6"


def _make_pipeline_client(
    model_verify: str = _TIER_VERIFY_MODEL,
    model_correct: str = _TIER_CORRECT_MODEL,
) -> tuple[LLMClient, _FakeMessagesAPI]:
    """Client with tier models set for pipeline assertions."""
    return _make_tier_client(
        model_execute=_EXECUTE_MODEL,
        model_verify=model_verify,
        model_correct=model_correct,
    )


# ── Math verifier ─────────────────────────────────────────────────────────────


def test_math_verifier_uses_verify_tier_model() -> None:
    """src/verifier.py:verify_question drives generate_with_image(purpose='verify').
    The model on the wire must be model_verify, not model_execute.
    """
    client, fake = _make_pipeline_client()
    question = _make_math_question()
    math_verify(client, question)

    assert len(fake.calls) >= 1
    assert fake.calls[0]["model"] == _TIER_VERIFY_MODEL, (
        f"Math verifier used model {fake.calls[0]['model']!r}, expected {_TIER_VERIFY_MODEL!r}"
    )


# ── Math corrector — generate_json path (no chart issues) ─────────────────────


def test_math_corrector_generate_json_path_uses_correct_tier_model() -> None:
    """src/corrector.py:correct_question → generate_json path (no chart_verification).
    The model on the wire must be model_correct.
    """
    client, fake = _make_pipeline_client()
    question = _make_math_question()
    verification = MathVerifResult(
        passed=False,
        answer_match=False,
        details="answer wrong",
        chart_verification=None,  # no chart → uses generate_json path
    )
    math_correct(client, question, verification)

    assert len(fake.calls) >= 1
    assert fake.calls[0]["model"] == _TIER_CORRECT_MODEL, (
        f"Math corrector (generate_json) used {fake.calls[0]['model']!r}, "
        f"expected {_TIER_CORRECT_MODEL!r}"
    )


# ── Math corrector — generate_with_image path (chart issues + file) ───────────


def test_math_corrector_generate_with_image_path_uses_correct_tier_model(
    tmp_path,
) -> None:
    """src/corrector.py:correct_question → generate_with_image path (chart_verification set).
    The model on the wire must be model_correct.
    """
    chart_png = tmp_path / "chart.png"
    chart_png.write_bytes(b"\x89PNG\r\n\x1a\n")  # minimal PNG header bytes

    client, fake = _make_pipeline_client()
    question = _make_math_question()
    chart_verif = MathChartVerif(
        chart_data_match=False,
        chart_labels_correct=False,
        chart_details="data mismatch",
    )
    verification = MathVerifResult(
        passed=False,
        answer_match=False,
        details="chart wrong",
        chart_verification=chart_verif,
    )
    math_correct(client, question, verification, chart_image_path=str(chart_png))

    assert len(fake.calls) >= 1
    assert fake.calls[0]["model"] == _TIER_CORRECT_MODEL, (
        f"Math corrector (generate_with_image) used {fake.calls[0]['model']!r}, "
        f"expected {_TIER_CORRECT_MODEL!r}"
    )


# ── SS verifier ───────────────────────────────────────────────────────────────


def test_ss_verifier_uses_verify_tier_model() -> None:
    """src/social_studies/verifier.py:verify_question → verify_question_common.
    Drives generate_with_image(purpose='verify'). Model must be model_verify.
    """
    client, fake = _make_pipeline_client()
    question = _make_ss_question()
    ss_verify(client, question)

    assert len(fake.calls) >= 1
    assert fake.calls[0]["model"] == _TIER_VERIFY_MODEL, (
        f"SS verifier used {fake.calls[0]['model']!r}, expected {_TIER_VERIFY_MODEL!r}"
    )


# ── SS corrector — generate_json path ────────────────────────────────────────


def test_ss_corrector_generate_json_path_uses_correct_tier_model() -> None:
    """src/social_studies/corrector.py:correct_question → correct_question_common.
    generate_json path (no chart). Model must be model_correct.
    """
    client, fake = _make_pipeline_client()
    question = _make_ss_question()
    verification = SSVerifResult(
        passed=False,
        answer_match=False,
        details="fix needed",
        chart_verification=None,
    )
    ss_correct(client, question, verification)

    assert len(fake.calls) >= 1
    assert fake.calls[0]["model"] == _TIER_CORRECT_MODEL, (
        f"SS corrector (generate_json) used {fake.calls[0]['model']!r}, "
        f"expected {_TIER_CORRECT_MODEL!r}"
    )


# ── SS corrector — generate_with_image path ──────────────────────────────────


def test_ss_corrector_generate_with_image_path_uses_correct_tier_model(
    tmp_path,
) -> None:
    """src/social_studies/corrector.py → generate_with_image path (chart issues).
    Model must be model_correct.
    """
    chart_png = tmp_path / "ss_chart.png"
    chart_png.write_bytes(b"\x89PNG\r\n\x1a\n")

    client, fake = _make_pipeline_client()
    question = _make_ss_question()
    chart_verif = SSChartVerif(
        chart_data_match=False,
        chart_labels_correct=False,
        chart_details="mismatch",
    )
    verification = SSVerifResult(
        passed=False,
        answer_match=False,
        details="chart wrong",
        chart_verification=chart_verif,
    )
    ss_correct(client, question, verification, chart_image_path=str(chart_png))

    assert len(fake.calls) >= 1
    assert fake.calls[0]["model"] == _TIER_CORRECT_MODEL, (
        f"SS corrector (generate_with_image) used {fake.calls[0]['model']!r}, "
        f"expected {_TIER_CORRECT_MODEL!r}"
    )


# ── NS verifier ───────────────────────────────────────────────────────────────


def test_ns_verifier_uses_verify_tier_model() -> None:
    """src/natural_sciences/verifier.py:verify_question → verify_question_common.
    Drives generate_with_image(purpose='verify'). Model must be model_verify.

    Note: the NS post-verify hook validates curriculum codes; our minimal question
    has no codes so it may flip passed=False, but the LLM call was already recorded.
    """
    client, fake = _make_pipeline_client()
    question = _make_ns_question()
    ns_verify(client, question)

    assert len(fake.calls) >= 1
    assert fake.calls[0]["model"] == _TIER_VERIFY_MODEL, (
        f"NS verifier used {fake.calls[0]['model']!r}, expected {_TIER_VERIFY_MODEL!r}"
    )


# ── NS corrector — generate_json path ────────────────────────────────────────


def test_ns_corrector_generate_json_path_uses_correct_tier_model() -> None:
    """src/natural_sciences/corrector.py:correct_question → correct_question_common.
    generate_json path (no chart). Model must be model_correct.
    """
    client, fake = _make_pipeline_client()
    question = _make_ns_question()
    verification = NSVerifResult(
        passed=False,
        answer_match=False,
        details="fix needed",
        chart_verification=None,
    )
    ns_correct(client, question, verification)

    assert len(fake.calls) >= 1
    assert fake.calls[0]["model"] == _TIER_CORRECT_MODEL, (
        f"NS corrector (generate_json) used {fake.calls[0]['model']!r}, "
        f"expected {_TIER_CORRECT_MODEL!r}"
    )


# ── NS corrector — generate_with_image path ──────────────────────────────────


def test_ns_corrector_generate_with_image_path_uses_correct_tier_model(
    tmp_path,
) -> None:
    """src/natural_sciences/corrector.py → generate_with_image path (chart issues).
    Model must be model_correct.
    """
    chart_png = tmp_path / "ns_chart.png"
    chart_png.write_bytes(b"\x89PNG\r\n\x1a\n")

    client, fake = _make_pipeline_client()
    question = _make_ns_question()
    chart_verif = NSChartVerif(
        chart_data_match=False,
        chart_labels_correct=False,
        chart_details="bad data",
    )
    verification = NSVerifResult(
        passed=False,
        answer_match=False,
        details="chart wrong",
        chart_verification=chart_verif,
    )
    ns_correct(client, question, verification, chart_image_path=str(chart_png))

    assert len(fake.calls) >= 1
    assert fake.calls[0]["model"] == _TIER_CORRECT_MODEL, (
        f"NS corrector (generate_with_image) used {fake.calls[0]['model']!r}, "
        f"expected {_TIER_CORRECT_MODEL!r}"
    )
