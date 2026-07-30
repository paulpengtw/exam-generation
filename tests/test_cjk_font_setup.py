"""Tests for CJK font setup and startup reporting (issue #258 Slice 1)."""
from __future__ import annotations

import matplotlib
import matplotlib.pyplot as plt

import src.renderer as renderer_mod
from src.renderer import _CJK_FONTS


class _CapturingLogger:
    def __init__(self):
        self.messages: list[tuple[str, str]] = []

    def error(self, msg, *args):
        self.messages.append(("error", msg % args if args else msg))

    def info(self, msg, *args):
        self.messages.append(("info", msg % args if args else msg))


def test_setup_chinese_font_all_fail_returns_none_warns_stderr_and_disables_unicode_minus(
    monkeypatch, capsys
) -> None:
    """When every findfont call raises, _setup_chinese_font returns None, warns stderr, disables unicode_minus."""

    def always_raise(font_name, fallback_to_default=True):
        raise ValueError(f"No font found: {font_name}")

    monkeypatch.setattr(matplotlib.font_manager, "findfont", always_raise)

    saved_sans = list(plt.rcParams["font.sans-serif"])
    saved_unicode_minus = plt.rcParams["axes.unicode_minus"]
    try:
        result = renderer_mod._setup_chinese_font()
    finally:
        plt.rcParams["font.sans-serif"] = saved_sans
        plt.rcParams["axes.unicode_minus"] = saved_unicode_minus

    assert result is None

    captured = capsys.readouterr()
    assert captured.err, "Expected a warning on stderr when all fonts fail"
    for font in _CJK_FONTS:
        assert font in captured.err, f"Expected font name {font!r} in stderr warning"

    assert plt.rcParams["axes.unicode_minus"] is False


def test_setup_chinese_font_second_candidate_returns_name_no_warning(
    monkeypatch, capsys
) -> None:
    """When findfont succeeds on the 2nd candidate, returns that font name with no stderr warning."""
    call_count = [0]

    def findfont_second_wins(font_name, fallback_to_default=True):
        call_count[0] += 1
        if call_count[0] == 1:
            raise ValueError("first font missing")
        return f"/fake/path/{font_name}.ttf"

    monkeypatch.setattr(matplotlib.font_manager, "findfont", findfont_second_wins)

    saved_sans = list(plt.rcParams["font.sans-serif"])
    saved_unicode_minus = plt.rcParams["axes.unicode_minus"]
    try:
        result = renderer_mod._setup_chinese_font()
    finally:
        plt.rcParams["font.sans-serif"] = saved_sans
        plt.rcParams["axes.unicode_minus"] = saved_unicode_minus

    assert result is not None
    assert isinstance(result, str)

    captured = capsys.readouterr()
    assert captured.err == ""


def test_report_cjk_font_status_logs_error_when_font_is_none(monkeypatch) -> None:
    """report_cjk_font_status logs error when module CJK_FONT is None."""
    from src.renderer import report_cjk_font_status

    monkeypatch.setattr(renderer_mod, "CJK_FONT", None)

    logger = _CapturingLogger()
    report_cjk_font_status(logger)

    error_msgs = [msg for level, msg in logger.messages if level == "error"]
    assert error_msgs, "Expected at least one logger.error call when CJK_FONT is None"


def test_report_cjk_font_status_no_error_when_font_present(monkeypatch) -> None:
    """report_cjk_font_status does NOT log error when CJK_FONT is a non-None string."""
    from src.renderer import report_cjk_font_status

    monkeypatch.setattr(renderer_mod, "CJK_FONT", "Noto Sans CJK TC")

    logger = _CapturingLogger()
    report_cjk_font_status(logger)

    error_msgs = [msg for level, msg in logger.messages if level == "error"]
    assert not error_msgs, f"Expected no errors when CJK_FONT is set, got: {error_msgs}"
