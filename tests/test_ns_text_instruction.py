"""Tests for 文本出題指示 wired into the 自然科學 文本生成器 (issue #635).

Mirror of tests/test_social_studies_context_builder.py for the NS seam:
  (1) build_text_user_prompt output: renders ## 文本出題指示 when set;
      byte-identical when unset/empty.
  (2) _ns_validate_params / NS GenerateParams validation accepts text_instruction.
  (3) /api/generate/preview (提示詞預覽) includes the section in the NS 文本生成器 prompt.
  (4) Math still rejects text_instruction (regression guard).
"""
from __future__ import annotations

import random
import uuid
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Slice 1: build_text_user_prompt byte-identical-when-unset / renders section
# ---------------------------------------------------------------------------

def test_ns_text_prompt_byte_identical_when_instruction_unset(tmp_path: Path) -> None:
    from src.natural_sciences.context_builder import build_text_user_prompt
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=1, content_type="純文字")
    prompt_no_arg, _, _draws = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    prompt_none, _, _draws = build_text_user_prompt(
        params, tmp_path, rng=random.Random(1), text_instruction=None
    )
    prompt_empty, _, _draws = build_text_user_prompt(
        params, tmp_path, rng=random.Random(1), text_instruction=""
    )
    prompt_blank, _, _draws = build_text_user_prompt(
        params, tmp_path, rng=random.Random(1), text_instruction="   "
    )

    assert prompt_no_arg == prompt_none
    assert prompt_no_arg == prompt_empty
    assert prompt_no_arg == prompt_blank


def test_ns_text_prompt_renders_text_instruction_section(tmp_path: Path) -> None:
    from src.natural_sciences.context_builder import build_text_user_prompt
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=2, content_type="純文字")
    instruction = "請聚焦電磁波的能量傳遞概念"

    prompt_with, _, _draws = build_text_user_prompt(
        params, tmp_path, rng=random.Random(2), text_instruction=instruction
    )
    prompt_without, _, _draws = build_text_user_prompt(
        params, tmp_path, rng=random.Random(2)
    )

    assert "## 文本出題指示" in prompt_with
    assert instruction in prompt_with
    assert "## 文本出題指示" not in prompt_without


def test_ns_text_instruction_does_not_appear_in_subquestion_prompt(tmp_path: Path) -> None:
    """The per-小題 出題指示 rendered by the 子題產生器 is untouched."""
    from src.natural_sciences.context_builder import build_subquestion_user_prompt
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=3, content_type="純文字")
    sq_prompt, _, _draws = build_subquestion_user_prompt(
        核心問題="測試核心問題",
        文本="測試文本",
        取材來源=["來源A"],
        sq_plan={"序號": 1, "題型": "Simple-multiple-choice", "出題概念": "電磁波"},
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(3),
    )

    assert "## 文本出題指示" not in sq_prompt


# ---------------------------------------------------------------------------
# Slice 2: NS validation accepts text_instruction; math still rejects it
# ---------------------------------------------------------------------------

def test_ns_validate_params_accepts_text_instruction() -> None:
    from server.generate.subjects import _ns_validate_params

    class FakeParams:
        content_domain = None
        target_surface = None
        text_instruction = "請聚焦電磁波"
        core_competency = None
        reporting_scale = None
        subquestion_configs = None

    # Should not raise
    _ns_validate_params(FakeParams())


def test_ns_validate_params_still_rejects_content_domain() -> None:
    from server.generate.subjects import _ns_validate_params

    class FakeParams:
        content_domain = "some_domain"
        target_surface = None
        text_instruction = None
        core_competency = None
        reporting_scale = None
        subquestion_configs = None

    with pytest.raises(ValueError, match="content_domain"):
        _ns_validate_params(FakeParams())


# ---------------------------------------------------------------------------
# Slice 3: /api/generate/preview shows ## 文本出題指示 in NS 文本生成器 prompt
# ---------------------------------------------------------------------------

def _complete_query_params(payload: dict) -> dict:
    """Build a resolver-complete payload for the GET route's wire shape."""
    import json  # noqa: PLC0415

    from src.common.resolver import resolve  # noqa: PLC0415

    completed = resolve(payload).payload
    rows = completed.get("per_question_params")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("subquestion_configs"), list):
                row["subquestion_configs"] = json.dumps(
                    row["subquestion_configs"], ensure_ascii=False
                )
        completed["per_question_params"] = json.dumps(rows, ensure_ascii=False)
    configs = completed.get("subquestion_configs")
    if isinstance(configs, list):
        completed["subquestion_configs"] = json.dumps(configs, ensure_ascii=False)
    return completed


def test_preview_route_includes_ns_text_instruction_in_text_prompt() -> None:
    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.auth.dependencies import get_config, get_current_user
    from server.config import ServerConfig
    from server.models import User
    from server.rate_limit import limiter

    instruction = "請聚焦電磁波的能量傳遞概念"
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_config] = lambda: ServerConfig(
        api_key="x", gemini_api_key="x"
    )
    limiter.reset()

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                "/api/generate/preview",
                params=_complete_query_params(
                    {
                        "subject": "natural_sciences",
                        "seed": 42,
                        "text_instruction": instruction,
                    }
                ),
            )
    finally:
        limiter.reset()

    assert response.status_code == 200, response.text
    text_prompt = next(
        item["user_prompt"]
        for item in response.json()["prompts"]
        if "subquestion_index" not in item
    )
    assert "## 文本出題指示" in text_prompt
    assert instruction in text_prompt
