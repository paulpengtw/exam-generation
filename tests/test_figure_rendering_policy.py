"""Classification + dispatch tests for the figure-rendering routing policy.

Source of truth: docs/figure-rendering-policy.md.
"""

from __future__ import annotations

import pytest

from src.context_builder import CONTENT_TYPE_INSTRUCTIONS as MATH_CT
from src.natural_sciences.context_builder import (
    CONTENT_TYPE_INSTRUCTIONS as NS_CT,
)
from src.social_studies.context_builder import (
    CONTENT_TYPE_INSTRUCTIONS as SS_CT,
)

_SUBJECT_TABLES = [
    pytest.param("math", MATH_CT, id="math"),
    pytest.param("social_studies", SS_CT, id="social_studies"),
    pytest.param("natural_sciences", NS_CT, id="natural_sciences"),
]


@pytest.mark.parametrize("subject, table", _SUBJECT_TABLES)
def test_plain_text_bans_chart_spec(subject: str, table: dict) -> None:
    assert "純文字" in table
    text = table["純文字"]
    assert "chart_spec" in text
    # The policy forbids any chart_spec output for 純文字.
    assert ("不得輸出" in text) or ("不輸出" in text)


@pytest.mark.parametrize("subject, table", _SUBJECT_TABLES)
def test_illustrative_content_routes_to_html(subject: str, table: dict) -> None:
    assert "含圖片" in table
    text = table["含圖片"]
    assert 'render_mode: "html"' in text, (
        f"{subject}: 含圖片 instruction must direct the model to render_mode: \"html\""
    )


@pytest.mark.parametrize("subject, table", _SUBJECT_TABLES)
def test_quantitative_content_routes_to_chart_and_html_for_tables(
    subject: str, table: dict
) -> None:
    assert "graphs/charts/tables" in table
    text = table["graphs/charts/tables"]
    assert 'render_mode: "chart"' in text, (
        f"{subject}: graphs/charts/tables instruction must mention render_mode: \"chart\""
    )
    assert 'render_mode: "html"' in text, (
        f"{subject}: graphs/charts/tables instruction must also mention "
        'render_mode: "html" for tables'
    )


# --- Dispatch tests ---------------------------------------------------------


class _RecordingHtmlRenderer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def render(self, html: str, output_path):  # noqa: D401
        self.calls.append((html, str(output_path)))
        return str(output_path)


class _RecordingLlmClient:
    def __init__(self) -> None:
        self.html_calls: list[dict] = []
        self.image_calls: list[dict] = []

    def generate(self, system: str, user: str, purpose: str = "") -> str:
        self.html_calls.append({"system": system, "user": user, "purpose": purpose})
        return "<!DOCTYPE html><html><body>fake</body></html>"

    def generate_image(self, prompt: str, output_path):
        self.image_calls.append({"prompt": prompt, "output_path": str(output_path)})
        return str(output_path)


def test_dispatch_chart_render_mode_uses_matplotlib(tmp_path, monkeypatch) -> None:
    from src import renderer

    called: dict = {}

    def fake_render_chart(spec, output_path):
        called["spec"] = spec
        called["output_path"] = str(output_path)
        return str(output_path)

    monkeypatch.setattr(renderer, "render_chart", fake_render_chart)
    html_renderer = _RecordingHtmlRenderer()
    llm_client = _RecordingLlmClient()

    out = tmp_path / "hist.png"
    result = renderer.render_image(
        {"render_mode": "chart", "chart_type": "histogram", "data": {"bins": [], "counts": []}},
        out,
        html_renderer=html_renderer,
        llm_client=llm_client,
        image_generation_mode="html",
    )

    assert result == str(out)
    assert called["spec"]["chart_type"] == "histogram"
    assert html_renderer.calls == []
    assert llm_client.html_calls == []
    assert llm_client.image_calls == []


def test_dispatch_html_render_mode_uses_playwright(tmp_path) -> None:
    from src import renderer

    html_renderer = _RecordingHtmlRenderer()
    llm_client = _RecordingLlmClient()

    out = tmp_path / "table.png"
    result = renderer.render_image(
        {"render_mode": "html", "description": "課表", "data": {"columns": ["a"], "rows": [["1"]]}},
        out,
        html_renderer=html_renderer,
        llm_client=llm_client,
        image_generation_mode="html",
    )

    assert result == str(out)
    assert len(llm_client.html_calls) == 1
    assert len(html_renderer.calls) == 1
    assert llm_client.image_calls == []


def test_dispatch_gpt_image_mode_bypasses_render_mode(tmp_path) -> None:
    from src import renderer

    html_renderer = _RecordingHtmlRenderer()
    llm_client = _RecordingLlmClient()

    out = tmp_path / "gpt.png"
    result = renderer.render_image(
        {"render_mode": "chart", "chart_type": "histogram", "data": {}},
        out,
        html_renderer=html_renderer,
        llm_client=llm_client,
        image_generation_mode="gpt_image",
    )

    assert result == str(out)
    assert html_renderer.calls == []
    assert llm_client.html_calls == []
    assert len(llm_client.image_calls) == 1


def test_dispatch_unknown_render_mode_returns_none(tmp_path) -> None:
    from src import renderer

    html_renderer = _RecordingHtmlRenderer()
    llm_client = _RecordingLlmClient()

    out = tmp_path / "unknown.png"
    result = renderer.render_image(
        {"render_mode": "nonsense", "data": {}},
        out,
        html_renderer=html_renderer,
        llm_client=llm_client,
        image_generation_mode="html",
    )

    assert result is None
    assert html_renderer.calls == []
    assert llm_client.html_calls == []
    assert llm_client.image_calls == []
