"""Tests for 參考範例紀錄 Pydantic models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.common.reference_example_record import (
    ReferenceExampleExampleEntry,
    ReferenceExampleProcessExemplarEntry,
    ReferenceExampleRecord,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TestReferenceExampleExampleEntry:
    def test_creates_with_required_fields(self) -> None:
        entry = ReferenceExampleExampleEntry(
            question_id="Q001",
            stage="generator",
            description="A math example",
            source="data/math/few_shot",
            timestamp=_now(),
        )
        assert entry.code == "reference_example"
        assert entry.kind == "example"
        assert entry.slot is None
        assert entry.content is None
        assert entry.images == []

    def test_creates_with_all_fields(self) -> None:
        ts = _now()
        entry = ReferenceExampleExampleEntry(
            question_id="Q001",
            stage="subquestion_generator",
            slot=2,
            description="Example with slot",
            source="data/math/few_shot/grouped",
            content={"question": "some math"},
            images=[{"path": "img.png"}],
            timestamp=ts,
        )
        assert entry.slot == 2
        assert entry.content == {"question": "some math"}
        assert entry.timestamp == ts


class TestReferenceExampleProcessExemplarEntry:
    def test_creates_with_required_fields(self) -> None:
        entry = ReferenceExampleProcessExemplarEntry(
            question_id="Q002",
            stage="subquestion_generator",
            slot=1,
            cognitive_process="理解",
            source="data/ss/process_exemplars",
            content={"example": "..."},
            timestamp=_now(),
        )
        assert entry.code == "reference_example"
        assert entry.kind == "process_exemplar"


class TestReferenceExampleRecord:
    def test_disabled_empty_record(self) -> None:
        record = ReferenceExampleRecord(disabled=True)
        assert record.disabled is True
        assert record.entries == []

    def test_enabled_with_entries(self) -> None:
        ts = _now()
        entry = ReferenceExampleExampleEntry(
            question_id="Q001",
            stage="generator",
            description="test",
            source="src",
            timestamp=ts,
        )
        record = ReferenceExampleRecord(disabled=False, entries=[entry])
        assert len(record.entries) == 1
        assert record.entries[0].kind == "example"

    def test_model_dump_roundtrip(self) -> None:
        ts = _now()
        entry = ReferenceExampleExampleEntry(
            question_id="Q001",
            stage="text_generator",
            description="round trip",
            source="data/path",
            content={"key": "val"},
            timestamp=ts,
        )
        record = ReferenceExampleRecord(disabled=False, entries=[entry])
        dumped = record.model_dump(mode="json")
        assert dumped["disabled"] is False
        assert len(dumped["entries"]) == 1
        assert dumped["entries"][0]["kind"] == "example"
        assert dumped["entries"][0]["code"] == "reference_example"
