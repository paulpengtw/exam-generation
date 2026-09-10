"""render_image propagates exception text through on_error callback."""
from __future__ import annotations

import pathlib

from src.renderer import render_image


class _FailingLLMClient:
    def __init__(self, error_msg: str = "IMAGE_API_KEY is required for GPT image generation."):
        self._error_msg = error_msg
    def get_observer(self):
        return None
    def generate_image(self, prompt: str, output_path) -> str:
        raise ValueError(self._error_msg)


class _SucceedingLLMClient:
    def get_observer(self):
        return None
    def generate_image(self, prompt: str, output_path) -> str:
        p = pathlib.Path(output_path)
        p.write_bytes(b"fake-png-data")
        return str(p)


def test_render_image_calls_on_error_with_exception_text(tmp_path):
    errors: list[str] = []
    render_image(
        {"render_mode": "gpt_image"},
        tmp_path / "out.png",
        llm_client=_FailingLLMClient(),
        on_error=errors.append,
    )
    assert len(errors) == 1
    assert "IMAGE_API_KEY" in errors[0]


def test_render_image_top_level_gpt_mode_calls_on_error(tmp_path):
    errors: list[str] = []
    render_image(
        {"render_mode": "chart"},
        tmp_path / "out.png",
        llm_client=_FailingLLMClient(),
        image_generation_mode="gpt_image",
        on_error=errors.append,
    )
    assert len(errors) == 1
    assert "IMAGE_API_KEY" in errors[0]


def test_on_error_receives_full_exception_text(tmp_path):
    unique_msg = "unique-error-signal-xyzzy-99999"
    errors: list[str] = []
    render_image(
        {"render_mode": "gpt_image"},
        tmp_path / "out.png",
        llm_client=_FailingLLMClient(error_msg=unique_msg),
        on_error=errors.append,
    )
    assert errors and unique_msg in errors[0]


def test_on_error_not_called_on_success(tmp_path):
    errors: list[str] = []
    result = render_image(
        {"render_mode": "gpt_image"},
        tmp_path / "out.png",
        llm_client=_SucceedingLLMClient(),
        on_error=errors.append,
    )
    assert errors == []
    assert result is not None


def test_on_error_none_does_not_crash_on_failure(tmp_path):
    result = render_image(
        {"render_mode": "gpt_image"},
        tmp_path / "out.png",
        llm_client=_FailingLLMClient(),
    )
    assert result is None


def test_null_llm_client_top_level_gpt_calls_on_error(tmp_path):
    """When image_generation_mode='gpt_image' and llm_client is None, on_error is called."""
    errors: list[str] = []
    result = render_image(
        {"render_mode": "chart"},
        tmp_path / "out.png",
        llm_client=None,
        image_generation_mode="gpt_image",
        on_error=errors.append,
    )
    assert result is None
    assert len(errors) == 1
    assert "LLMClient" in errors[0]


def test_null_llm_client_spec_level_gpt_calls_on_error(tmp_path):
    """When render_mode='gpt_image' and llm_client is None, on_error is called."""
    errors: list[str] = []
    result = render_image(
        {"render_mode": "gpt_image"},
        tmp_path / "out.png",
        llm_client=None,
        on_error=errors.append,
    )
    assert result is None
    assert len(errors) == 1
    assert "LLMClient" in errors[0]
