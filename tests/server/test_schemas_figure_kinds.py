"""Tests: /api/schemas carries figure_kinds for visual subjects, not for math.

Slices:
    (a) schemas endpoint exposes the vocabulary for social_studies
    (a) schemas endpoint exposes the vocabulary for natural_sciences
    (a) math schema does NOT include figure_kinds
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient

from server.app import create_app
from src.social_studies.figure_kind_loader import CANONICAL_FIGURE_KINDS


def test_social_studies_schema_includes_figure_kinds() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/schemas?subject=social_studies")
    assert r.status_code == 200
    body = r.json()
    assert "figure_kinds" in body
    kinds = body["figure_kinds"]
    assert isinstance(kinds, list)
    assert len(kinds) > 0
    # Must include the full canonical vocabulary
    assert kinds == list(CANONICAL_FIGURE_KINDS)


def test_natural_sciences_schema_includes_figure_kinds() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/schemas?subject=natural_sciences")
    assert r.status_code == 200
    body = r.json()
    assert "figure_kinds" in body
    kinds = body["figure_kinds"]
    assert isinstance(kinds, list)
    assert len(kinds) > 0
    # Same vocabulary as social_studies (shared data file per PR #613)
    assert kinds == list(CANONICAL_FIGURE_KINDS)


def test_math_schema_does_not_include_figure_kinds() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/schemas?subject=math")
    assert r.status_code == 200
    body = r.json()
    assert "figure_kinds" not in body
