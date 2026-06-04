"""Tests for direct GPT image generation rendering."""

from __future__ import annotations

import base64
from pathlib import Path

from src.config import Config
from src.llm_client import LLMClient
from src.renderer import render_image


class _FakeImage:
    def __init__(self, b64_json: str) -> None:
        self.b64_json = b64_json


class _FakeImages:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return type(
            "ImageResponse",
            (),
            {"data": [_FakeImage(base64.b64encode(b"png-bytes").decode("ascii"))]},
        )()


class _FakeImageClient:
    def __init__(self) -> None:
        self.images = _FakeImages()


def test_llm_client_generate_image_writes_png(tmp_path: Path) -> None:
    client = LLMClient(
        Config(
            api_key="text-key",
            image_api_key="image-key",
            image_model="gpt-image2",
        )
    )
    fake_image_client = _FakeImageClient()
    client._image_client = fake_image_client

    out = tmp_path / "image.png"
    result = client.generate_image("draw a map", out)

    assert result == str(out)
    assert out.read_bytes() == b"png-bytes"
    assert fake_image_client.images.calls == [{
        "model": "gpt-image2",
        "prompt": "draw a map",
        "size": "1024x1024",
        "n": 1,
    }]


def test_llm_client_generate_image_emits_observer_events(tmp_path: Path) -> None:
    client = LLMClient(
        Config(
            api_key="text-key",
            image_api_key="image-key",
            image_model="gpt-image2",
        )
    )
    fake_image_client = _FakeImageClient()
    client._image_client = fake_image_client
    events: list[dict] = []
    client.set_observer(events.append)

    out = tmp_path / "image.png"
    client.generate_image("draw a map", out)

    assert [e["type"] for e in events] == ["llm_request", "llm_response"]
    assert events[0]["purpose"] == "gpt_image"
    assert events[0]["agent"] == "image_agent"
    assert events[0]["model"] == "gpt-image2"
    assert events[1]["purpose"] == "gpt_image"
    assert events[1]["agent"] == "image_agent"


def test_render_image_uses_gpt_image_mode_for_html_specs(tmp_path: Path) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.prompt = ""

        def generate_image(self, prompt: str, output_path: str | Path) -> str:
            self.prompt = prompt
            Path(output_path).write_bytes(b"png")
            return str(output_path)

    fake_client = FakeClient()
    out = tmp_path / "ss.png"

    result = render_image(
        {
            "render_mode": "html",
            "title": "人口變化圖",
            "description": "呈現甲乙兩地人口變化",
            "data": {"甲地": [100, 120]},
        },
        out,
        question_text="請依據圖表判斷人口趨勢。",
        llm_client=fake_client,
        image_generation_mode="gpt_image",
    )

    assert result == str(out)
    assert out.read_bytes() == b"png"
    assert "人口變化圖" in fake_client.prompt
    assert "甲地" in fake_client.prompt


def test_render_image_uses_gpt_image_mode_for_chart_specs(tmp_path: Path) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.prompt = ""

        def generate_image(self, prompt: str, output_path: str | Path) -> str:
            self.prompt = prompt
            Path(output_path).write_bytes(b"png")
            return str(output_path)

    fake_client = FakeClient()
    out = tmp_path / "ss_chart.png"

    result = render_image(
        {
            "render_mode": "chart",
            "chart_type": "line_chart",
            "title": "人口變化圖",
            "data": {"甲地": [100, 120]},
            "labels": {"x": "年份", "y": "人口"},
        },
        out,
        question_text="請依據圖表判斷人口趨勢。",
        llm_client=fake_client,
        image_generation_mode="gpt_image",
    )

    assert result == str(out)
    assert out.read_bytes() == b"png"
    assert "人口變化圖" in fake_client.prompt
    assert "甲地" in fake_client.prompt
