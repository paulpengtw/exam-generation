"""Validation of 各小題配置 rows at subject schema boundaries."""

import pytest
from pydantic import ValidationError

from src.social_studies.schemas import SubQuestionConfig


def test_social_studies_config_rejects_natural_sciences_reporting_scale() -> None:
    with pytest.raises(ValidationError, match="reporting_scale"):
        SubQuestionConfig(reporting_scale="local")
