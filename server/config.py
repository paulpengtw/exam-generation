"""Server-specific configuration, extending `src.config.Config`."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from src.config import (
    DEFAULT_EFFORT_CORRECT,
    DEFAULT_EFFORT_EXECUTE,
    DEFAULT_EFFORT_PLAN,
    DEFAULT_EFFORT_VERIFY,
    DEFAULT_MODEL_CORRECT,
    DEFAULT_MODEL_EXECUTE,
    DEFAULT_MODEL_PLAN,
    DEFAULT_MODEL_VERIFY,
    Config,
)
from src.config import (
    EFFORT_LEVELS as _EFFORT_LEVELS,  # noqa: F401  (re-export: server.generate.routes + tests import this name)
)
from src.config import (
    FIVE_EFFORT_LEVELS as _FIVE_EFFORT_LEVELS,  # noqa: F401
)
from src.config import (
    FOUR_EFFORT_LEVELS as _FOUR_EFFORT_LEVELS,  # noqa: F401
)
from src.config import (
    THREE_EFFORT_LEVELS as _THREE_EFFORT_LEVELS,  # noqa: F401
)

# Built-in roster: execute default first, then plan/verify, then other models.
# Unset/empty LLM_MODELS_ALLOWED uses this roster; a non-empty value replaces it.
# Configured non-empty tier models are always appended if missing.
_DEFAULT_MODELS_ALLOWED: tuple[str, ...] = (
    "gemini-3.1-pro-preview",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-opus-5",
    "claude-fable-5",
    "claude-sonnet-5",
)


@dataclass
class ServerConfig(Config):
    database_url: str = "sqlite+aiosqlite:///./dev.db"
    jwt_secret: str = ""
    jwt_expire_days: int = 7
    session_renewal_threshold_minutes: int = 360
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
    release_authority_url: str = ""
    release_authority_path: Path | None = None
    generation_history_retention_days: int = 0
    email_whitelist: tuple[str, ...] = ()
    llm_models_allowed: tuple[str, ...] = ()
    llm_exchange_retention_days: int = 30
    creative_planning: bool = True
    effort_plan: str = DEFAULT_EFFORT_PLAN  # Planning effort (LLM_EFFORT_PLAN)
    effort_execute: str = DEFAULT_EFFORT_EXECUTE  # Execution effort (LLM_EFFORT_EXECUTE)
    # Verify/correct model and effort fields inherit the shared defaults from Config.

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
            model_plan=os.environ.get("LLM_MODEL_PLAN", DEFAULT_MODEL_PLAN),
            model_execute=os.environ.get("LLM_MODEL_EXECUTE", DEFAULT_MODEL_EXECUTE),
            model_verify=os.environ.get("LLM_MODEL_VERIFY", DEFAULT_MODEL_VERIFY),
            model_correct=os.environ.get("LLM_MODEL_CORRECT", DEFAULT_MODEL_CORRECT),
            image_api_key=os.environ.get("IMAGE_API_KEY", ""),
            image_base_url=os.environ.get("IMAGE_BASE_URL", "https://api.openai.com/v1"),
            image_model=os.environ.get("IMAGE_MODEL", "gpt-image2"),
            gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
            gemini_base_url=os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"),
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            output_dir=Path(os.environ.get("OUTPUT_DIR", "./output")),
            data_dir=Path(os.environ.get("DATA_DIR", "./data")),
            rate_limit_delay=float(os.environ.get("LLM_RATE_LIMIT_DELAY", "0")),
            max_retries=int(os.environ.get("LLM_MAX_RETRIES", "3")),
            database_url=os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./dev.db"),
            jwt_secret=os.environ.get("JWT_SECRET", ""),
            jwt_expire_days=int(os.environ.get("JWT_EXPIRE_DAYS", "7")),
            session_renewal_threshold_minutes=int(
                os.environ.get("SESSION_RENEWAL_THRESHOLD_MINUTES", "360")
            ),
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
            release_authority_url=os.environ.get("RELEASE_AUTHORITY_URL", "").strip(),
            release_authority_path=(
                Path(os.environ["RELEASE_AUTHORITY_PATH"])
                if os.environ.get("RELEASE_AUTHORITY_PATH", "").strip()
                else None
            ),
            generation_history_retention_days=int(
                os.environ.get("GENERATION_HISTORY_RETENTION_DAYS", "0")
            ),
            llm_models_allowed=tuple(
                m.strip()
                for m in os.environ.get("LLM_MODELS_ALLOWED", "").split(",")
                if m.strip()
            ),  # empty tuple = "unset"; resolved to _DEFAULT_MODELS_ALLOWED below
            llm_exchange_retention_days=int(
                os.environ.get("LLM_EXCHANGE_RETENTION_DAYS", "30")
            ),
            web_search_provider=os.environ.get("WEB_SEARCH_PROVIDER", "none"),
            web_search_max_uses=int(os.environ.get("WEB_SEARCH_MAX_USES", "5")),
            creative_planning=os.environ.get("CREATIVE_PLANNING", "1")
            not in ("0", "false", "False", ""),
            effort_plan=os.environ.get("LLM_EFFORT_PLAN", DEFAULT_EFFORT_PLAN),
            effort_execute=os.environ.get("LLM_EFFORT_EXECUTE", DEFAULT_EFFORT_EXECUTE),
            effort_verify=os.environ.get("LLM_EFFORT_VERIFY", DEFAULT_EFFORT_VERIFY),
            effort_correct=os.environ.get("LLM_EFFORT_CORRECT", DEFAULT_EFFORT_CORRECT),
        )
        # When LLM_MODELS_ALLOWED is unset/empty fall back to the built-in
        # roster; when set it replaces the roster entirely (no merge).
        initial = cfg.llm_models_allowed if cfg.llm_models_allowed else _DEFAULT_MODELS_ALLOWED
        seen: dict[str, None] = {}
        for m in initial:
            if m and m not in seen:
                seen[m] = None
        # Always ensure the configured plan/execute/verify/correct models are
        # present so GET /api/models never advertises a default that the 422
        # gate would then reject.  Empty strings are skipped by the `if m` guard.
        for m in (cfg.model_plan, cfg.model_execute, cfg.model_verify, cfg.model_correct):
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
        half_lifetime_minutes = self.jwt_expire_days * 24 * 60 // 2
        if self.session_renewal_threshold_minutes > half_lifetime_minutes:
            raise ValueError(
                "SESSION_RENEWAL_THRESHOLD_MINUTES="
                f"{self.session_renewal_threshold_minutes} must be no more than half of "
                f"JWT_EXPIRE_DAYS={self.jwt_expire_days} expressed in minutes "
                f"(half-lifetime = {half_lifetime_minutes} min). Lower "
                "SESSION_RENEWAL_THRESHOLD_MINUTES or raise JWT_EXPIRE_DAYS."
            )
