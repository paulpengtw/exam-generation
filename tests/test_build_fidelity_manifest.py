"""Tests for the fidelity-manifest builder (issue #110 gate evidence)."""

from __future__ import annotations

import base64

from scripts.build_fidelity_manifest import (
    _question_text,
    build_manifest,
    select_illustrative_specs,
)


def _ss_row() -> tuple[str, dict]:
    return (
        "social_studies",
        {
            "id": "ss_q1",
            "文本": "題組文本",
            "chart_spec": {"render_mode": "html", "description": "海報", "data": {}},
            "subquestions": [
                {
                    "序號": 2,
                    "chart_spec": {
                        "render_mode": "html",
                        "data": {"rows": [["1"]], "columns": ["a"]},
                    },
                },
            ],
        },
    )


def test_select_skips_chart_mode_and_builds_subquestion_ids() -> None:
    math_row = (
        "math",
        {
            "id": "m1",
            "題目": ["題幹"],
            "chart_spec": {"render_mode": "chart", "chart_type": "histogram", "data": {}},
        },
    )
    entries = select_illustrative_specs([math_row, _ss_row()], limit_per_subject=12)
    assert [e["id"] for e in entries] == ["ss_q1", "ss_q1_sq2"]
    assert entries[0]["subject"] == "social_studies"
    assert entries[1]["category"] == "table"
    assert entries[0]["question_text"] == "題組文本"


def test_select_respects_per_subject_limit() -> None:
    rows = [_ss_row(), _ss_row(), _ss_row()]
    entries = select_illustrative_specs(rows, limit_per_subject=2)
    assert len(entries) == 2


def test_question_text_prefers_文本_then_joins_題目() -> None:
    assert _question_text({"文本": "abc", "題目": ["x"]}) == "abc"
    assert _question_text({"題目": ["x", "y"]}) == "x\ny"
    assert _question_text({}) == ""


def test_build_manifest_encodes_png_and_marks_failures_null() -> None:
    entries = [
        {"id": "a", "subject": "math", "category": "other", "spec": {}, "question_text": ""},
        {"id": "b", "subject": "math", "category": "other", "spec": {}, "question_text": ""},
    ]
    calls: list[str] = []

    def fake_render(spec: dict, question_text: str) -> bytes | None:
        calls.append("call")
        return b"png-bytes" if len(calls) == 1 else None

    manifest = build_manifest(entries, fake_render)
    assert manifest[0]["server_png_base64"] == base64.b64encode(b"png-bytes").decode("ascii")
    assert manifest[1]["server_png_base64"] is None
