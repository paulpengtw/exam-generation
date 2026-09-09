"""Stage-aware, context-conditional curriculum injection (issue #91)."""

from __future__ import annotations

import json
import random
from pathlib import Path

from src.natural_sciences.context_builder import (
    build_subquestion_system_prompt,
    build_subquestion_user_prompt,
    build_system_prompt,
    build_text_system_prompt,
    build_user_prompt,
    curriculum_texts,
)
from src.natural_sciences.sampler import sample_params


def test_curriculum_texts_scope_stage_and_cross_concepts():
    content_text, performance_text = curriculum_texts(
        "第五學習階段", ["BDa-Ⅴa-1"]
    )
    content = json.loads(content_text)
    performance = json.loads(performance_text)
    assert content["學習內容"] and performance["學習表現"]
    assert all(
        r["學習階段"] == "第五學習階段"
        for r in content["學習內容"]
    )
    assert all(
        r["學習階段"] == "第五學習階段"
        for r in performance["學習表現"]
    )
    # BDa → 次主題 Da → 構造與功能（INb）group only (5 of 48 rows).
    assert len(content["跨科概念"]) == 5
    assert all("INb" in r["跨科概念"] for r in content["跨科概念"])


def test_curriculum_texts_without_codes_keep_full_taxonomy():
    content_text, _ = curriculum_texts("第四學習階段")
    assert len(json.loads(content_text)["跨科概念"]) == 48


def test_default_system_prompt_unchanged_without_stage():
    """No-arg call keeps the schema_meta default (第四學習階段, grades 7-12)."""
    prompt = build_system_prompt()
    assert "專門為第四學習階段" in prompt
    assert "7年級、8年級、9年級、10年級、11年級、12年級" in prompt


def test_text_system_prompt_stage5_uses_stage_grades():
    content_text, performance_text = curriculum_texts("第五學習階段")
    prompt = build_text_system_prompt(
        learning_stage="第五學習階段",
        content_text=content_text,
        performance_text=performance_text,
    )
    assert "專門為第五學習階段（10年級、11年級、12年級）" in prompt


def test_subquestion_system_prompt_accepts_stage_scoped_texts():
    content_text, performance_text = curriculum_texts(
        "第五學習階段", ["BDa-Ⅴa-1"]
    )
    prompt = build_subquestion_system_prompt(
        learning_stage="第五學習階段",
        content_text=content_text,
        performance_text=performance_text,
    )
    assert "目前學習階段：第五學習階段" in prompt
    assert '"學習階段": "第五學習階段"' in prompt
    assert '"學習階段": "第四學習階段"' not in prompt


def test_user_prompt_stage_follows_grade(tmp_path: Path):
    params = sample_params(grade=11, seed=3)
    prompt, _, _draws = build_user_prompt(
        params, tmp_path, rng=random.Random(3)
    )
    assert "11年級（第五學習階段）" in prompt


def test_subquestion_user_prompt_stage_follows_grade(tmp_path: Path):
    params = sample_params(grade=10, seed=3)
    plan = {"序號": 1, "題型": params.題型.value, "出題概念": "測試"}
    prompt, _, _draws = build_subquestion_user_prompt(
        核心問題="核心",
        文本="文本",
        取材來源=["來源"],
        sq_plan=plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(3),
    )
    assert "10年級（第五學習階段）" in prompt
