"""#283 – NS QuestionMetadata records the Reporting Scale each 小題 landed on.

Seam under test: generate_with_corrections (fake clients) — the only place
where dropped-slot behaviour AND correction-pass alignment are both observable.

Slices:
  1. All 小題 succeed → metadata.reporting_scales equals resolved per-小題 levels
     in 序號 order (literal expected values, independent of the request value).
  2. Slot dropped after retries → list length equals surviving 小題 count.
  3. Correction pass → list unchanged (levels frozen through metadata preservation).
  4. Old stored JSON carrying metadata.difficulty (and lacking reporting_scales)
     still deserializes without error; the field defaults to [].
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from src.config import Config
from src.natural_sciences.cli import generate_with_corrections
from src.natural_sciences.sampler import sample_params
from src.natural_sciences.schemas import ExamQuestion

N_SLOTS = 3
# Distinct per-slot levels driven by the fake sub-client.
_SCALES = ["level_a", "level_b", "level_c"]


# ---------------------------------------------------------------------------
# Shared fake infrastructure
# ---------------------------------------------------------------------------

class _State:
    """Call-recording state shared across fake sub-clients (thread-safe)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls_by_slot: dict[int, int] = {}


def _slot(agent_override: str) -> int:
    return int(agent_override.split("#", 1)[1])


def _text_shell_raw(n: int = N_SLOTS) -> dict:
    return {
        "核心問題": "核心問題",
        "文本": "文本",
        "取材來源": ["來源"],
        "subquestions": [
            {"序號": i, "題型": "Simple multiple-choice", "出題概念": f"概念{i}"}
            for i in range(1, n + 1)
        ],
    }


def _sq_raw(idx: int, scale: str) -> dict:
    return {
        "序號": idx,
        "題型": "Simple multiple-choice",
        "題目": f"第{idx}小題題目",
        "答案": "A",
        "答案解析": "解析",
        "出題概念": f"概念{idx}",
        "reporting_scale": scale,
    }


class _FakeTextClient:
    """文本生成器 stand-in: plain text shell, no chart_spec."""

    def get_observer(self):
        return None

    def generate_json(self, system, user, images=None, **kwargs):
        return _text_shell_raw()


class _ScaleSubClient:
    """Always succeeds; returns distinct reporting_scale per slot (from _SCALES)."""

    def set_observer(self, obs) -> None:
        pass

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        idx = _slot(agent_override)
        return _sq_raw(idx, _SCALES[idx - 1])


class _FlakySubClient:
    """Slot 2 always fails (simulates a permanently failing sub-generator)."""

    def __init__(self, state: _State) -> None:
        self._state = state

    def set_observer(self, obs) -> None:
        pass

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        idx = _slot(agent_override)
        with self._state.lock:
            attempt = self._state.calls_by_slot.get(idx, 0) + 1
            self._state.calls_by_slot[idx] = attempt
        if idx == 2:
            raise RuntimeError(f"boom: slot {idx} attempt {attempt}")
        return _sq_raw(idx, _SCALES[idx - 1])


def _config(subgen_retries: int = 0) -> Config:
    return Config(data_dir=Path("data"), subgen_retries=subgen_retries)


def _call(sub_client_factory, *, config=None, skip_verify=True,
          client=None) -> ExamQuestion:
    if config is None:
        config = _config()
    if client is None:
        client = _FakeTextClient()
    params = sample_params(seed=11, content_type="純文字")
    question = generate_with_corrections(
        config=config,
        client=client,
        params=params,
        question_id="ns_reporting_test",
        skip_verify=skip_verify,
        disable_reference_fewshot=True,
        sub_client_factory=sub_client_factory,
    )
    assert isinstance(question, ExamQuestion)
    return question


# ---------------------------------------------------------------------------
# Slice 1: metadata.reporting_scales records resolved per-小題 levels in order
# ---------------------------------------------------------------------------

def test_metadata_records_resolved_reporting_scales() -> None:
    question = _call(lambda: _ScaleSubClient())
    assert question.metadata is not None
    assert question.metadata.reporting_scales == _SCALES


# ---------------------------------------------------------------------------
# Slice 2: dropped slot → list length equals surviving 小題 count
# ---------------------------------------------------------------------------

def test_metadata_excludes_dropped_slot() -> None:
    state = _State()
    question = _call(lambda: _FlakySubClient(state))
    # Confirm slot 2 was dropped
    assert [sq.序號 for sq in question.subquestions] == [1, 3]
    assert question.metadata is not None
    assert len(question.metadata.reporting_scales) == 2
    assert question.metadata.reporting_scales == ["level_a", "level_c"]


# ---------------------------------------------------------------------------
# Slice 3: correction pass → reporting_scales list unchanged
# ---------------------------------------------------------------------------

class _VerifyFailThenPassClient:
    """Handles text gen + verify-fail + correct + verify-pass in sequence."""

    def __init__(self) -> None:
        self._verify_calls = 0

    def get_observer(self):
        return None

    def generate_json(self, system, user, images=None, purpose=None, **kwargs):
        if purpose == "correct":
            # Return a minimal corrected question with subquestions
            return {
                "題目": ["Corrected question"],
                "文本": "corrected text",
                "subquestions": [
                    {
                        "序號": i,
                        "題型": "Simple multiple-choice",
                        "題目": f"Corrected 小題{i}",
                        "答案": "A",
                        "答案解析": "corrected 解析",
                    }
                    for i in range(1, N_SLOTS + 1)
                ],
            }
        # Text shell generation (no purpose kwarg)
        return _text_shell_raw()

    def generate_with_image(self, system, user, image_path=None, purpose=None, **kwargs):
        self._verify_calls += 1
        if self._verify_calls == 1:
            # First verify: fail → triggers correction pass
            return json.dumps({
                "passed": False,
                "answer_match": False,
                "details": "needs correction",
                "my_answer": "",
                "provided_answer": "",
            })
        # Subsequent verifies: pass
        return json.dumps({
            "passed": True,
            "answer_match": True,
            "details": "ok",
            "my_answer": "",
            "provided_answer": "",
        })


def test_reporting_scales_frozen_through_correction_pass() -> None:
    main_client = _VerifyFailThenPassClient()
    question = _call(
        lambda: _ScaleSubClient(),
        client=main_client,
        skip_verify=False,
        config=Config(data_dir=Path("data"), subgen_retries=0),
    )
    assert question.metadata is not None
    # Levels must equal the values set during generation — unchanged by correction.
    assert question.metadata.reporting_scales == _SCALES


# ---------------------------------------------------------------------------
# Slice 4: old JSON with metadata.difficulty and without reporting_scales loads
# ---------------------------------------------------------------------------

def test_old_json_without_reporting_scales_deserializes() -> None:
    from src.natural_sciences.schemas import (
        QuestionMetadata,
        QuestionSetType,
        QuestionSubContext,
        QuestionType,
    )

    old_metadata_dict = {
        "grade": 8,
        "model": "claude-sonnet-4-6",
        "seed": None,
        "difficulty": "hard",   # present in old persisted files, must be ignored
        # reporting_scales absent — must default to []
    }
    q = ExamQuestion(
        id="old-ns",
        subquestions=[],
        情境=[],
        情境子類別=next(iter(QuestionSubContext)),
        題型種類=next(iter(QuestionSetType)),
        題型=next(iter(QuestionType)),
        metadata=QuestionMetadata(**old_metadata_dict),
    )
    raw = json.loads(q.model_dump_json())
    q2 = ExamQuestion(**raw)
    assert q2.id == "old-ns"
    assert q2.metadata is not None
    assert q2.metadata.reporting_scales == []
