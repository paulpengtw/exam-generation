"""Process-wide generation state shared by the backend and the run worker.

Both hosts of ``run_host_loop`` (the backend's lifespan and ``python -m
server.worker``) need the same curriculum contexts, renderer pool and drain
telemetry on an ``app_state``-like object (ADR 0034).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from server.config import ServerConfig
from server.generate.drain import DrainTelemetry
from src.common.subject_spec import NATURAL_SCIENCES, SOCIAL_STUDIES
from src.curriculum_context import load_curriculum_context
from src.data_loader import (
    get_grade_content,
    load_curriculum,
    load_intro_text,
    load_performance_standards,
)
from src.html_renderer import PlaywrightRenderer
from src.schema_loader import load_grades, load_schemas

logger = logging.getLogger(__name__)

RENDERER_POOL_SIZE = 2


def load_generation_state(state: Any, config: ServerConfig) -> None:
    """Populate *state* with curriculum, renderer pool and drain telemetry."""
    curriculum = load_curriculum(config.data_dir / "curriculum" / "學習內容.json")
    performance = load_performance_standards(config.data_dir / "curriculum" / "學習表現.json")
    intro_text = load_intro_text(Path('Introduction to "學習表現" and "學習階段".md'))
    grades = load_grades(load_schemas(config.question_schemas_path))
    grade_content = {g: get_grade_content(curriculum, g) for g in grades}

    state.curriculum = curriculum
    state.performance = performance
    state.intro_text = intro_text
    state.grade_content = grade_content
    # Build the canonical math curriculum context once per server process so
    # generator, verifier, and corrector all share the same corpus (issue #154).
    state.math_curriculum_context = load_curriculum_context()
    # Build social-studies and natural-sciences curriculum contexts (issue #158).
    state.ss_curriculum_context = load_curriculum_context(SOCIAL_STUDIES.data_dir)
    state.ns_curriculum_context = load_curriculum_context(NATURAL_SCIENCES.data_dir)
    print(f"Curriculum loaded: {len(curriculum)} grade entries, target grades {grades}")

    renderer_pool: asyncio.Queue[PlaywrightRenderer] = asyncio.Queue()
    started = 0
    for _ in range(RENDERER_POOL_SIZE):
        try:
            renderer = PlaywrightRenderer()
            renderer.start()
            renderer_pool.put_nowait(renderer)
            started += 1
        except Exception as exc:
            print(f"Warning: Playwright failed to start: {exc}", file=sys.stderr)
            break
    state.renderer_pool = renderer_pool if started else None
    state.drain_telemetry = DrainTelemetry()
    state.html_renderer = None  # legacy; service.py uses renderer_pool
    if started:
        print(f"Playwright renderer pool started ({started} instances)")

    # Surface CJK font availability to deploy logs (issue #258).
    try:
        from src.renderer import report_cjk_font_status

        report_cjk_font_status(logger)
    except Exception as exc:  # pragma: no cover — best effort
        print(f"Warning: CJK font status check failed: {exc}", file=sys.stderr)


def stop_generation_state(state: Any) -> None:
    """Stop every pooled renderer that load_generation_state started."""
    pool = getattr(state, "renderer_pool", None)
    if pool is None:
        return
    while not pool.empty():
        renderer = pool.get_nowait()
        try:
            renderer.stop()
        except Exception as exc:  # pragma: no cover
            print(f"Warning: Playwright shutdown failed: {exc}", file=sys.stderr)
