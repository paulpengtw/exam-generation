"""The math server path must thread a non-None CurriculumContext through to
math_generate_with_corrections (issue #154).

Before the fix, VERIFICATION_SYSTEM_PROMPT / CORRECTION_SYSTEM_PROMPT had the
curriculum prefix baked in at import time; after the refactor those constants
are curriculum-free and the context must be passed explicitly.  Without
app.state.math_curriculum_context the server path silently loses the curriculum
— this test catches that regression.
"""

from __future__ import annotations

import asyncio
import types
from pathlib import Path
from unittest.mock import patch

from server.config import ServerConfig
from server.generate import service
from server.generate.models import GenerateParams
from src.curriculum_context import CurriculumContext, load_curriculum_context
from src.schemas import ExamQuestion, LearningContentItem


def _fake_math_generate(**kwargs):
    """Minimal stub that returns a valid ExamQuestion."""
    return ExamQuestion.model_construct(
        id=kwargs.get("question_id", "test"),
        情境=[],
        題型種類="單一題",
        題型="選擇題",
        數學思考=[],
        學習內容=[LearningContentItem(編碼="N-7-1", 說明="整數")],
        題目=[],
        正確解題分析=[],
        metadata=None,
    )


def _run_math_stream(
    app_state: types.SimpleNamespace,
    tmp_path: Path,
) -> dict:
    """Drive generate_question_stream for one math question; capture kwargs."""
    config = ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
    )
    params = GenerateParams(subject="math", count=1, skip_verify=True, seed=1)
    captured: dict = {}

    def capturing_stub(**kwargs):
        captured.update(kwargs)
        return _fake_math_generate(**kwargs)

    async def collect() -> None:
        async for _ in service.generate_question_stream(params, config, app_state):
            pass

    with patch.object(service, "math_generate_with_corrections", side_effect=capturing_stub):
        asyncio.run(collect())

    return captured


def test_server_math_path_passes_curriculum_context_to_generate_with_corrections(
    tmp_path,
) -> None:
    """When app_state has math_curriculum_context, the service must forward it
    as the ``curriculum_context`` kwarg to math_generate_with_corrections."""
    ctx = load_curriculum_context()
    app_state = types.SimpleNamespace(
        renderer_pool=None,
        curriculum=[],
        performance={},
        intro_text="",
        grade_content={7: [], 8: [], 9: []},
        math_curriculum_context=ctx,
    )
    captured = _run_math_stream(app_state, tmp_path)

    assert "curriculum_context" in captured, (
        "math_generate_with_corrections was not called with a curriculum_context kwarg"
    )
    received = captured["curriculum_context"]
    assert isinstance(received, CurriculumContext), (
        f"Expected CurriculumContext, got {type(received)}"
    )
    assert received is ctx, (
        "curriculum_context passed to generate_with_corrections is not the same "
        "object that was stored in app_state.math_curriculum_context"
    )


def test_server_math_path_without_curriculum_context_attr_does_not_crash(
    tmp_path,
) -> None:
    """Legacy / test app_state stubs that omit math_curriculum_context must not
    crash the service — they fall back to curriculum_context=None."""
    app_state = types.SimpleNamespace(
        renderer_pool=None,
        curriculum=[],
        performance={},
        intro_text="",
        grade_content={7: [], 8: [], 9: []},
        # deliberately omit math_curriculum_context
    )
    captured = _run_math_stream(app_state, tmp_path)

    assert "curriculum_context" in captured
    assert captured["curriculum_context"] is None
