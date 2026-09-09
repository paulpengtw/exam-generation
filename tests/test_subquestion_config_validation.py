"""Validation of 各小題配置 rows at subject schema boundaries."""

import pytest
from pydantic import ValidationError

from src.social_studies.schemas import SubQuestionConfig


def test_social_studies_config_rejects_natural_sciences_reporting_scale() -> None:
    with pytest.raises(ValidationError, match="reporting_scale"):
        SubQuestionConfig(reporting_scale="local")


# Issue #644 — text_word_limit is removed from SubQuestionConfig in both subjects
def test_social_studies_subquestion_config_rejects_text_word_limit() -> None:
    """SubQuestionConfig must reject text_word_limit (removed in #644)."""
    with pytest.raises(ValidationError, match="text_word_limit"):
        SubQuestionConfig(text_word_limit=1)


def test_natural_sciences_subquestion_config_rejects_text_word_limit() -> None:
    """Natural-sciences SubQuestionConfig must reject text_word_limit (removed in #644)."""
    from src.natural_sciences.schemas import SubQuestionConfig as NSSubQuestionConfig

    with pytest.raises(ValidationError, match="text_word_limit"):
        NSSubQuestionConfig(text_word_limit=1)
