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
    question_schemas_path: Path = (
        Path(__file__).resolve().parent.parent / "question_schemas.json"
    )
    social_studies_curriculum_dir: Path = (
        Path(__file__).resolve().parent.parent / "data" / "social_studies" / "curriculum"
    )
    natural_sciences_curriculum_dir: Path = (
        Path(__file__).resolve().parent.parent / "data" / "natural_sciences" / "curriculum"
    )
    math_curriculum_dir: Path = (
        Path(__file__).resolve().parent.parent / "data" / "math" / "curriculum"
    )
    email_whitelist: tuple[str, ...] = ()
    llm_models_allowed: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> ServerConfig:
        """Load server configuration from environment variables and optional .env file."""
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv()

        cfg = cls(
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
            database_url=os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./dev.db"),
            jwt_secret=os.environ.get("JWT_SECRET", ""),
            jwt_expire_days=int(os.environ.get("JWT_EXPIRE_DAYS", "7")),
            aws_region=os.environ.get("AWS_REGION", ""),
            ses_from_email=os.environ.get("SES_FROM_EMAIL", ""),
            frontend_url=os.environ.get("FRONTEND_URL", ""),
            email_backend=os.environ.get("EMAIL_BACKEND", "console"),
            email_whitelist=tuple(
                e.strip().lower()
                for e in os.environ.get("EMAIL_WHITELIST", "").split(",")
                if e.strip()
            ),
            question_schemas_path=Path(
                os.environ.get(
                    "QUESTION_SCHEMAS_PATH",
                    str(Path(__file__).resolve().parent.parent / "question_schemas.json"),
                )
            ),
            social_studies_curriculum_dir=Path(
                os.environ.get(
                    "SOCIAL_STUDIES_CURRICULUM_DIR",
                    str(
                        Path(__file__).resolve().parent.parent
                        / "data" / "social_studies" / "curriculum"
                    ),
                )
            ),
            natural_sciences_curriculum_dir=Path(
                os.environ.get(
                    "NATURAL_SCIENCES_CURRICULUM_DIR",
                    str(
                        Path(__file__).resolve().parent.parent
                        / "data" / "natural_sciences" / "curriculum"
                    ),
                )
            ),
            math_curriculum_dir=Path(
                os.environ.get(
                    "MATH_CURRICULUM_DIR",
                    str(Path(__file__).resolve().parent.parent / "data" / "math" / "curriculum"),
                )
            ),
            llm_models_allowed=tuple(
                m.strip()
                for m in os.environ.get("LLM_MODELS_ALLOWED", "").split(",")
                if m.strip()
            ),
        )
        if not cfg.llm_models_allowed:
            seen: dict[str, None] = {}
            for m in (cfg.model_plan, cfg.model_execute):
                if m and m not in seen:
                    seen[m] = None
            cfg.llm_models_allowed = tuple(seen)
        else:
            seen = {}
            for m in cfg.llm_models_allowed:
                if m and m not in seen:
                    seen[m] = None
            cfg.llm_models_allowed = tuple(seen)
        return cfg

    def validate(self) -> None:
        """Check that required server config values are present."""
        super().validate()
        if not self.jwt_secret:
            raise ValueError(
                "JWT_SECRET is required. Set it in .env or as an environment variable."
            )
