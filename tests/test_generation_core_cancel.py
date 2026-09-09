"""Cancel-boundary unit tests for generate_one_core and src/cli.py generate_one.

These tests drive the REAL pipeline code (generate_one_core / generate_one) with
fake LLM clients, verifying that the ``is_cancelled`` checkpoints added in
src/common/generation_core.py and src/cli.py work correctly.

Unlike tests A1–A4 in tests/server/test_generate_cancel.py (which use a fake
``do_generate`` that re-implements the boundary check), these tests exercise the
actual check site in production code.

Boundary map for 社會領域 (generate_one_core):
  text LLM call
  ← boundary 1: after text stage, before subquestion generation
  subquestion generation (ThreadPoolExecutor)
  ← boundary 2: after subquestion generation, before image / verify
  (no image in these fakes)
  ← boundary 3: after image rendering, before verification (always hit here too)
  verify

Boundary map for math flat path (src/cli.py generate_one, no sub_question_count):
  flat LLM call
  ← boundary 1: after LLM call, before image / verify
  (no image in these fakes)
  ← boundary 2: before verify
  verify
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from src.common.generation_core import GenerationCancelled, generate_one_core
from src.config import Config

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _config(tmp_path: Path) -> Config:
    return Config(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        subgen_max_concurrency=4,
        subgen_retries=0,
    )


# ---------------------------------------------------------------------------
# 社會領域 fake clients
# ---------------------------------------------------------------------------


def _ss_text_response(n_subs: int = 3) -> dict[str, Any]:
    return {
        "核心問題": "Test Q",
        "文本": "Test text.",
        "取材來源": ["Test source"],
        "subquestions": [
            {"序號": i, "題型": "選擇題", "出題概念": f"C{i}"}
            for i in range(1, n_subs + 1)
        ],
    }


def _ss_sub_response(index: int) -> dict[str, Any]:
    return {
        "序號": index,
        "年級": 8,
        "科目": ["地理"],
        "核心素養": ["社-J-A2"],
        "學習內容": [{"編碼": "地Af-Ⅳ-3", "說明": "test lc"}],
        "學習表現": [{"編碼": "社1b-Ⅳ-1", "說明": "test lp"}],
        "出題概念": f"C{index}",
        "題型": "選擇題",
        "題目": "Test question? (A)A (B)B (C)C (D)D",
        "答案": "A",
        "答案解析": "Test.",
        "評分規準": [],
    }


class _SSTextClient:
    """Fake text-stage client.

    ``after_call`` is called (in the same thread) at the end of
    ``generate_json``, just before it returns.  Use it to flip a cancel flag so
    that the boundary check immediately after the call sees it.
    """

    def __init__(
        self,
        n_subs: int = 3,
        after_call: Any = None,
    ) -> None:
        self.n_subs = n_subs
        self.after_call = after_call

    def get_observer(self) -> None:
        return None

    def generate_json(self, _system: str, _user: str, **_kwargs: Any) -> dict[str, Any]:
        resp = _ss_text_response(self.n_subs)
        if self.after_call is not None:
            self.after_call()
        return resp


class _SSSubClient:
    """Fake subquestion client.

    ``on_call`` is invoked per sub-question call (useful for counting / cancel).
    """

    def __init__(self, on_call: Any = None) -> None:
        self.on_call = on_call

    def set_observer(self, _obs: Any) -> None:
        pass

    def generate_json(
        self,
        _system: str,
        _user: str,
        *,
        agent_override: str,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        index = int(agent_override.split("#")[1])
        if self.on_call is not None:
            self.on_call(index)
        return _ss_sub_response(index)


def _ss_spec() -> Any:
    """Import the real SS spec (singleton from cli)."""
    from src.social_studies.cli import _SS_SPEC  # noqa: PLC0415

    return _SS_SPEC


def _ss_params(n_subs: int = 3) -> Any:
    from src.social_studies.sampler import sample_params  # noqa: PLC0415

    return sample_params(seed=554, sub_question_count=n_subs)


# ---------------------------------------------------------------------------
# SS tests
# ---------------------------------------------------------------------------


def test_ss_cancel_after_text_stage_raises_before_subquestion_generation(
    tmp_path: Path,
) -> None:
    """Boundary 1 (after text LLM, before subquestion gen):
    GenerationCancelled is raised; the sub_client_factory is NEVER invoked.

    Red-first verification: comment out
        ``if is_cancelled is not None and is_cancelled(): raise GenerationCancelled()``
    at boundary 1 in generate_one_core — this test would then fail because
    sub_client_factory would be called and no exception would be raised.
    """
    cancelled = [False]

    def is_cancelled() -> bool:
        return cancelled[0]

    factory_calls: list[int] = []

    def sub_client_factory() -> _SSSubClient:
        factory_calls.append(1)
        return _SSSubClient()

    # Flip the cancel flag inside the text client so the boundary check
    # immediately after the text LLM call sees it as True.
    text_client = _SSTextClient(
        n_subs=3,
        after_call=lambda: cancelled.__setitem__(0, True),
    )

    with pytest.raises(GenerationCancelled):
        generate_one_core(
            config=_config(tmp_path),
            client=text_client,
            params=_ss_params(3),
            question_id="ss_cancel_text",
            spec=_ss_spec(),
            skip_verify=True,
            disable_reference_fewshot=True,
            sub_client_factory=sub_client_factory,
            is_cancelled=is_cancelled,
        )

    assert factory_calls == [], (
        "sub_client_factory must NOT be called when cancel fires at boundary 1; "
        f"got calls: {factory_calls}"
    )


def test_ss_cancel_after_subquestion_generation_raises_before_verify(
    tmp_path: Path,
) -> None:
    """Boundary 2 (after subquestion gen, before verify):
    GenerationCancelled is raised; all sub-questions ran but verify is skipped.

    Red-first verification: comment out boundary 2 in generate_one_core — the
    function would return an ExamQuestion instead of raising.
    """
    n_subs = 3
    cancelled = [False]

    def is_cancelled() -> bool:
        return cancelled[0]

    # Track sub-question call counts (concurrent, needs a lock).
    sub_calls: list[int] = []
    lock = threading.Lock()

    def on_sub_call(index: int) -> None:
        with lock:
            sub_calls.append(index)
            # Set cancel after ALL subquestions have been requested.
            if len(sub_calls) >= n_subs:
                cancelled[0] = True

    text_client = _SSTextClient(n_subs=n_subs)

    with pytest.raises(GenerationCancelled):
        generate_one_core(
            config=_config(tmp_path),
            client=text_client,
            params=_ss_params(n_subs),
            question_id="ss_cancel_sub",
            spec=_ss_spec(),
            # skip_verify=False would call the real SS verifier, which needs
            # a proper LLM client.  The boundary check fires BEFORE verify,
            # so setting it False here would expose the test to a missing-LLM
            # error instead of proving the cancel.  Use True to keep the test
            # self-contained; the cancel fires before verify regardless.
            skip_verify=True,
            disable_reference_fewshot=True,
            sub_client_factory=lambda: _SSSubClient(on_call=on_sub_call),
            is_cancelled=is_cancelled,
        )

    assert len(sub_calls) == n_subs, (
        f"All {n_subs} subquestions should have been generated before the cancel "
        f"boundary; got sub_calls={sub_calls}"
    )


def test_ss_no_cancel_completes_normally(tmp_path: Path) -> None:
    """is_cancelled=None → generate_one_core returns an ExamQuestion normally.

    This acts as a sanity control: the fake clients are valid enough to
    produce a parseable result end-to-end.
    """
    from src.social_studies.schemas import ExamQuestion  # noqa: PLC0415

    n_subs = 3
    text_client = _SSTextClient(n_subs=n_subs)
    sub_calls: list[int] = []

    result = generate_one_core(
        config=_config(tmp_path),
        client=text_client,
        params=_ss_params(n_subs),
        question_id="ss_no_cancel",
        spec=_ss_spec(),
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _SSSubClient(on_call=sub_calls.append),
        is_cancelled=None,
    )

    assert isinstance(result, ExamQuestion), (
        f"Expected ExamQuestion, got {type(result)}"
    )
    assert len(result.subquestions) == n_subs
    assert len(sub_calls) == n_subs


# ---------------------------------------------------------------------------
# Math flat-path cancel tests (src/cli.py generate_one, no sub_question_count)
# ---------------------------------------------------------------------------


class _MathFlatClient:
    """Fake flat-math LLM client.

    ``after_call`` is called after generate_json returns.
    """

    def __init__(self, after_call: Any = None) -> None:
        self.after_call = after_call

    def get_observer(self) -> None:
        return None

    def generate_json(self, _system: str, _user: str, **_kwargs: Any) -> dict[str, Any]:
        resp: dict[str, Any] = {
            "情境": ["個人"],
            "題型種類": "單一題",
            "題型": "選擇題",
            "數學思考": ["運用"],
            "學習內容": [],
            "題目": ["若 x=2，求 3x？"],
            "正確解題分析": ["3×2=6。"],
        }
        if self.after_call is not None:
            self.after_call()
        return resp


def _math_single_params() -> Any:
    from src.sampler import sample_params  # noqa: PLC0415

    # seed=8 → 單一題 (confirmed in test_math_group_pipeline.py snapshot)
    return sample_params(grade=8, seed=8, content_type="純文字")


def test_math_cancel_after_flat_llm_call_raises_before_verify(
    tmp_path: Path,
) -> None:
    """Math flat path, boundary 1 (after text LLM, before verify):
    GenerationCancelled is raised; the verifier is never called.

    Red-first verification: comment out boundary 1 in src/cli.py generate_one —
    the function would return an ExamQuestion instead of raising.
    """
    from src.cli import generate_one  # noqa: PLC0415

    cancelled = [False]

    def is_cancelled() -> bool:
        return cancelled[0]

    verifier_called = [False]

    # Monkeypatch the math verifier to detect if it is called.
    import src.cli as math_cli  # noqa: PLC0415
    import src.verifier as math_verifier_module  # noqa: PLC0415

    original_verify = math_verifier_module.verify_question

    def spy_verify(*args: Any, **kwargs: Any) -> Any:
        verifier_called[0] = True
        return original_verify(*args, **kwargs)

    math_verifier_module.verify_question = spy_verify  # type: ignore[assignment]
    # Also patch the reference used inside cli.py
    original_cli_verify = math_cli.verify_question
    math_cli.verify_question = spy_verify  # type: ignore[assignment]

    text_client = _MathFlatClient(after_call=lambda: cancelled.__setitem__(0, True))

    try:
        with pytest.raises(GenerationCancelled):
            generate_one(
                config=_config(tmp_path),
                client=text_client,
                curriculum=[],
                performance={},
                intro_text="",
                grade_content={},
                params=_math_single_params(),
                question_id="math_cancel_flat",
                skip_verify=False,  # verifier would run if not cancelled
                is_cancelled=is_cancelled,
            )
    finally:
        math_verifier_module.verify_question = original_verify  # type: ignore[assignment]
        math_cli.verify_question = original_cli_verify  # type: ignore[assignment]

    assert not verifier_called[0], (
        "Verifier must NOT be called when cancel fires at boundary 1 in math "
        "generate_one; the cancel check gates the verify path."
    )
