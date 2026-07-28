"""Verify that GenerateParams.model_execute is forwarded to LLMClient.config."""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from types import SimpleNamespace

from server.config import ServerConfig
from server.generate.models import GenerateParams
from server.generate.service import generate_question_stream
from server.generate.subjects import SUBJECTS
from src.social_studies.schemas import ExamQuestion


def _fake_ss_spec(fake_generate_fn):
    """Return a copy of the SS SubjectSpec with do_generate replaced by fake_generate_fn.

    fake_generate_fn receives the same **kwargs the real ss_generate_with_corrections
    would receive, plus params=rng_params.
    """
    def fake_do_generate(rng_params, overrides, **kwargs):
        return fake_generate_fn(params=rng_params, **kwargs)

    return dataclasses.replace(SUBJECTS["social_studies"], do_generate=fake_do_generate)


def test_model_execute_override_is_baked_into_llmclient_config(tmp_path: Path) -> None:
    config = ServerConfig(
        api_key="x",
        model_plan="claude-opus-4-6",
        model_execute="claude-sonnet-4-6",
        output_dir=tmp_path,
        data_dir=Path("data"),
        llm_models_allowed=(
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-6",
        ),
    )
    params = GenerateParams(
        subject="social_studies",
        count=1,
        skip_verify=True,
        model_execute="claude-haiku-4-6",
        model_plan="claude-opus-4-6",
    )

    captured: dict = {}

    def fake_generate_with_corrections(**kwargs):
        client = kwargs["client"]
        captured["model_execute"] = client.config.model_execute
        captured["model_plan"] = client.config.model_plan
        sampled = kwargs["params"]
        return ExamQuestion(
            id=kwargs["question_id"],
            核心問題="q",
            文本="t",
            subquestions=[],
            情境=[c.value for c in sampled.情境],
            題型種類=sampled.題型種類.value,
            題型=sampled.題型[0].value,
            閱讀歷程=[p.value for p in sampled.閱讀歷程],
            文本形式=sampled.文本形式.value,
            題目=["題目"],
            正確解題分析=["解析"],
        )

    async def collect_events():
        events = []
        async for event in generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            subjects={"social_studies": _fake_ss_spec(fake_generate_with_corrections)},
        ):
            events.append(event)
        return events

    asyncio.run(collect_events())

    assert captured["model_execute"] == "claude-haiku-4-6"
    assert captured["model_plan"] == "claude-opus-4-6"


def test_model_override_absent_preserves_config_defaults(tmp_path: Path) -> None:
    config = ServerConfig(
        api_key="x",
        model_plan="claude-opus-4-6",
        model_execute="claude-sonnet-4-6",
        output_dir=tmp_path,
        data_dir=Path("data"),
    )
    params = GenerateParams(subject="social_studies", count=1, skip_verify=True)

    captured: dict = {}

    def fake_generate_with_corrections(**kwargs):
        client = kwargs["client"]
        captured["model_execute"] = client.config.model_execute
        captured["model_plan"] = client.config.model_plan
        sampled = kwargs["params"]
        return ExamQuestion(
            id=kwargs["question_id"],
            核心問題="q",
            文本="t",
            subquestions=[],
            情境=[c.value for c in sampled.情境],
            題型種類=sampled.題型種類.value,
            題型=sampled.題型[0].value,
            閱讀歷程=[p.value for p in sampled.閱讀歷程],
            文本形式=sampled.文本形式.value,
            題目=["題目"],
            正確解題分析=["解析"],
        )

    async def collect_events():
        events = []
        async for event in generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            subjects={"social_studies": _fake_ss_spec(fake_generate_with_corrections)},
        ):
            events.append(event)
        return events

    asyncio.run(collect_events())

    assert captured["model_execute"] == "claude-sonnet-4-6"
    assert captured["model_plan"] == "claude-opus-4-6"


def test_model_execute_override_reaches_ss_generate_config(tmp_path: Path) -> None:
    """The `config` kwarg passed into ss_generate_with_corrections must reflect the
    per-request override, not the original un-overridden ServerConfig — otherwise the
    parallel 子題產生器 LLMClient instances built inside src/social_studies/cli.py from
    a stale `config` silently ignore model_execute."""
    config = ServerConfig(
        api_key="x",
        model_plan="claude-opus-4-6",
        model_execute="claude-sonnet-4-6",
        output_dir=tmp_path,
        data_dir=Path("data"),
        llm_models_allowed=(
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-6",
        ),
    )
    params = GenerateParams(
        subject="social_studies",
        count=1,
        skip_verify=True,
        model_execute="claude-haiku-4-6",
    )

    captured: dict = {}

    def fake_generate_with_corrections(**kwargs):
        captured["config"] = kwargs["config"]
        sampled = kwargs["params"]
        return ExamQuestion(
            id=kwargs["question_id"],
            核心問題="q",
            文本="t",
            subquestions=[],
            情境=[c.value for c in sampled.情境],
            題型種類=sampled.題型種類.value,
            題型=sampled.題型[0].value,
            閱讀歷程=[p.value for p in sampled.閱讀歷程],
            文本形式=sampled.文本形式.value,
            題目=["題目"],
            正確解題分析=["解析"],
        )

    async def collect_events():
        events = []
        async for event in generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            subjects={"social_studies": _fake_ss_spec(fake_generate_with_corrections)},
        ):
            events.append(event)
        return events

    asyncio.run(collect_events())

    assert captured["config"].model_execute == "claude-haiku-4-6"
