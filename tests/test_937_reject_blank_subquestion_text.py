"""Issue #937: blank or missing 題目 in a subquestion response must be rejected.

A subquestion 子題 whose `題目` field is absent or contains only whitespace
must raise ``SubquestionParseError`` so the existing bounded retry/drop path
handles it correctly.  An empty ``SubQuestion`` must never be accepted.
"""

from __future__ import annotations

import pytest

from src.common.generation_core import SubquestionParseError
from src.natural_sciences.cli import _parse_subquestion as ns_parse_subquestion
from src.natural_sciences.sampler import sample_params as ns_sample_params
from src.social_studies.cli import _parse_subquestion as ss_parse_subquestion
from src.social_studies.sampler import sample_params as ss_sample_params


# ---------------------------------------------------------------------------
# Helpers: minimal valid subquestion raw dicts
# ---------------------------------------------------------------------------

def _ss_valid_raw() -> dict:
    return {
        "題型": "選擇題",
        "題目": "下列哪一項描述正確？",
        "答案": "A",
        "答案解析": "因為...",
        "出題概念": "測試概念",
        "學習內容": [{"編碼": "歷Ka-Ⅳ-1", "說明": "說明"}],
        "學習表現": [{"編碼": "社1a-Ⅳ-1", "說明": "說明"}],
    }


def _ns_valid_raw() -> dict:
    return {
        "題型": "Simple multiple-choice",
        "題目": "下列哪一項描述正確？",
        "答案": "A",
        "答案解析": "因為...",
        "出題概念": "測試概念",
        "學習內容": [{"編碼": "INc-IV-1", "說明": "說明"}],
        "學習表現": [{"編碼": "tr-IV-1", "說明": "說明"}],
    }


# ---------------------------------------------------------------------------
# Social Studies
# ---------------------------------------------------------------------------

class TestSocialStudiesParseSubquestion:
    def setup_method(self):
        # Use seed for reproducibility; grade 8 is in the default pool
        self.params = ss_sample_params(grade=8, seed=1)
        self.question_id = "q_TEST_001"

    def test_valid_subquestion_is_accepted(self):
        """Sanity check: a well-formed response with a non-empty 題目 returns a SubQuestion."""
        raw = _ss_valid_raw()
        result = ss_parse_subquestion(raw, self.question_id, self.params, 1)
        assert result.題目 == raw["題目"]

    def test_missing_題目_raises_parse_error(self):
        """When 題目 key is absent the slot must be rejected as unparseable."""
        raw = _ss_valid_raw()
        del raw["題目"]
        with pytest.raises(SubquestionParseError):
            ss_parse_subquestion(raw, self.question_id, self.params, 1)

    def test_empty_string_題目_raises_parse_error(self):
        """When 題目 is an empty string the slot must be rejected as unparseable."""
        raw = _ss_valid_raw()
        raw["題目"] = ""
        with pytest.raises(SubquestionParseError):
            ss_parse_subquestion(raw, self.question_id, self.params, 1)

    def test_whitespace_only_題目_raises_parse_error(self):
        """When 題目 contains only whitespace the slot must be rejected as unparseable."""
        raw = _ss_valid_raw()
        raw["題目"] = "   \n\t  "
        with pytest.raises(SubquestionParseError):
            ss_parse_subquestion(raw, self.question_id, self.params, 1)


# ---------------------------------------------------------------------------
# Natural Sciences
# ---------------------------------------------------------------------------

class TestNaturalSciencesParseSubquestion:
    def setup_method(self):
        self.params = ns_sample_params(grade=8, seed=1)
        self.question_id = "q_TEST_001"

    def test_valid_subquestion_is_accepted(self):
        """Sanity check: a well-formed response with a non-empty 題目 returns a SubQuestion."""
        raw = _ns_valid_raw()
        result = ns_parse_subquestion(raw, self.question_id, self.params, 1)
        assert result.題目 == raw["題目"]

    def test_missing_題目_raises_parse_error(self):
        """When 題目 key is absent the slot must be rejected as unparseable."""
        raw = _ns_valid_raw()
        del raw["題目"]
        with pytest.raises(SubquestionParseError):
            ns_parse_subquestion(raw, self.question_id, self.params, 1)

    def test_empty_string_題目_raises_parse_error(self):
        """When 題目 is an empty string the slot must be rejected as unparseable."""
        raw = _ns_valid_raw()
        raw["題目"] = ""
        with pytest.raises(SubquestionParseError):
            ns_parse_subquestion(raw, self.question_id, self.params, 1)

    def test_whitespace_only_題目_raises_parse_error(self):
        """When 題目 contains only whitespace the slot must be rejected as unparseable."""
        raw = _ns_valid_raw()
        raw["題目"] = "   \n\t  "
        with pytest.raises(SubquestionParseError):
            ns_parse_subquestion(raw, self.question_id, self.params, 1)
