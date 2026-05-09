"""Server-specific configuration, extending `src.config.Config`."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from src.config import Config


@dataclass
class ServerConfig(Config):
    database_url: str = "sqlite+aiosqlite:///./dev.db"
    jwt_secret: str = ""
    jwt_expire_days: int = 7
    aws_region: str = ""
    ses_from_email: str = ""
    frontend_url: str = ""
    email_backend: str = "console"
    question_schemas_path: Path = Path(__file__).resolve().parent.parent / "question_schemas.json"

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> ServerConfig:
        """Load server configuration from environment variables and optional .env file."""
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv()

        return cls(
            api_key=os.environ.get("LLM_API_KEY", ""),
            base_url=os.environ.get("LLM_BASE_URL", "https://api.anthropic.com/v1"),
            model_plan=os.environ.get("LLM_MODEL_PLAN", "claude-opus-4-6"),
            model_execute=os.environ.get("LLM_MODEL_EXECUTE", "claude-sonnet-4-6"),
            output_dir=Path(os.environ.get("OUTPUT_DIR", "./output")),
            data_dir=Path(os.environ.get("DATA_DIR", "./data")),
            rate_limit_delay=float(os.environ.get("LLM_RATE_LIMIT_DELAY", "0")),
            database_url=os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./dev.db"),
            jwt_secret=os.environ.get("JWT_SECRET", ""),
            jwt_expire_days=int(os.environ.get("JWT_EXPIRE_DAYS", "7")),
            aws_region=os.environ.get("AWS_REGION", ""),
            ses_from_email=os.environ.get("SES_FROM_EMAIL", ""),
            frontend_url=os.environ.get("FRONTEND_URL", ""),
            email_backend=os.environ.get("EMAIL_BACKEND", "console"),
            question_schemas_path=Path(
                os.environ.get(
                    "QUESTION_SCHEMAS_PATH",
                    str(Path(__file__).resolve().parent.parent / "question_schemas.json"),
                )
            ),
        )

    def validate(self) -> None:
        """Check that required server config values are present."""
        super().validate()
        if not self.jwt_secret:
            raise ValueError(
                "JWT_SECRET is required. Set it in .env or as an environment variable."
            )
