"""Configuration management for exam-generation CLI."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Config:
    api_key: str = ""
    base_url: str = "https://api.anthropic.com/v1"
    model_plan: str = "claude-opus-4-6"
    model_execute: str = "claude-sonnet-4-6"
    image_api_key: str = ""
    image_base_url: str = "https://api.openai.com/v1"
    image_model: str = "gpt-image2"
    output_dir: Path = field(default_factory=lambda: Path("./output"))
    data_dir: Path = field(default_factory=lambda: Path("./data"))
    rate_limit_delay: float = 0.0  # seconds between API calls
    max_retries: int = 3  # retries when verification fails (0 = no retry)

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> Config:
        """Load configuration from environment variables and optional .env file."""
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv()

        return cls(
            api_key=os.environ.get("LLM_API_KEY", ""),
            base_url=os.environ.get("LLM_BASE_URL", "https://api.anthropic.com/v1"),
            model_plan=os.environ.get("LLM_MODEL_PLAN", "claude-opus-4-6"),
            model_execute=os.environ.get("LLM_MODEL_EXECUTE", "claude-sonnet-4-6"),
            image_api_key=os.environ.get("IMAGE_API_KEY", ""),
            image_base_url=os.environ.get("IMAGE_BASE_URL", "https://api.openai.com/v1"),
            image_model=os.environ.get("IMAGE_MODEL", "gpt-image2"),
            output_dir=Path(os.environ.get("OUTPUT_DIR", "./output")),
            data_dir=Path(os.environ.get("DATA_DIR", "./data")),
            rate_limit_delay=float(os.environ.get("LLM_RATE_LIMIT_DELAY", "0")),
            max_retries=int(os.environ.get("LLM_MAX_RETRIES", "3")),
        )

    def validate(self) -> None:
        """Check that required config values are present."""
        if not self.api_key:
            raise ValueError("LLM_API_KEY is required. Set it in .env or as an environment variable.")
