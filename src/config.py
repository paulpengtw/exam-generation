"""Configuration management for exam-generation CLI."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Per-model effort level roster (moved here from server/config.py so that
# src/ code can reference it without importing server/).
#
# Models that support the full five-level scale include xhigh; the 4.x models
# stop at max.  Unknown models (custom roster via env) default to the safe
# four-level subset (no xhigh).
# ---------------------------------------------------------------------------

FIVE_EFFORT_LEVELS: list[str] = ["low", "medium", "high", "xhigh", "max"]
FOUR_EFFORT_LEVELS: list[str] = ["low", "medium", "high", "max"]
THREE_EFFORT_LEVELS: list[str] = ["low", "medium", "high"]

# Unknown-model fallback (conservative: no xhigh).
DEFAULT_EFFORT_LEVELS: list[str] = FOUR_EFFORT_LEVELS

EFFORT_LEVELS: dict[str, list[str]] = {
    "claude-opus-5": FIVE_EFFORT_LEVELS,
    "claude-fable-5": FIVE_EFFORT_LEVELS,
    "claude-sonnet-5": FIVE_EFFORT_LEVELS,
    "claude-sonnet-4-6": FOUR_EFFORT_LEVELS,
    "claude-opus-4-6": FOUR_EFFORT_LEVELS,
    "gemini-3.1-pro-preview": THREE_EFFORT_LEVELS,
}


@dataclass
class Config:
    api_key: str = ""
    base_url: str = "https://api.anthropic.com/v1"
    model_plan: str = "claude-sonnet-4-6"
    model_execute: str = "claude-sonnet-4-6"
    # Tier-specific model overrides (empty = follow the effective execute model,
    # resolved at call time so per-request dataclasses.replace overrides land
    # correctly — see issue #374).
    model_verify: str = ""   # 驗證模型; empty → effective execute model
    model_correct: str = ""  # 修正模型; empty → effective execute model
    image_api_key: str = ""
    image_base_url: str = "https://api.openai.com/v1"
    image_model: str = "gpt-image2"
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    output_dir: Path = field(default_factory=lambda: Path("./output"))
    data_dir: Path = field(default_factory=lambda: Path("./data"))
    rate_limit_delay: float = 0.0  # seconds between API calls
    max_retries: int = 3  # retries when verification fails (0 = no retry)
    subgen_max_concurrency: int = 6
    subgen_retries: int = 1  # extra fresh 子題 calls per failed slot (0 = drop on first)
    llm_stream: bool = True  # use streaming API when observer is set
    log_truncate: int | None = None  # max chars per message in llm_request events; None = no limit
    web_search_provider: str = "none"  # "anthropic" | "gemini" | "none" (default: opt-in disabled)
    web_search_max_uses: int = 5
    # per-batch Opus 情境-題材 planning (SS only); env CREATIVE_PLANNING
    creative_planning: bool = True
    temperature: float | None = None  # sampling temperature; None = provider default
    effort_plan: str = "medium"  # output_config.effort for plan calls (LLM_EFFORT_PLAN)
    effort_execute: str = "medium"  # output_config.effort for execute calls (LLM_EFFORT_EXECUTE)
    # Tier-specific effort overrides (issue #377); empty = inherit effort_execute at call time.
    effort_verify: str = ""   # empty → inherit effort_execute (LLM_EFFORT_VERIFY)
    effort_correct: str = ""  # empty → inherit effort_execute (LLM_EFFORT_CORRECT)

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
            model_plan=os.environ.get("LLM_MODEL_PLAN", "claude-sonnet-4-6"),
            model_execute=os.environ.get("LLM_MODEL_EXECUTE", "claude-sonnet-4-6"),
            model_verify=os.environ.get("LLM_MODEL_VERIFY", ""),
            model_correct=os.environ.get("LLM_MODEL_CORRECT", ""),
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
            subgen_max_concurrency=int(os.environ.get("SUBGEN_MAX_CONCURRENCY", "6")),
            subgen_retries=int(os.environ.get("SUBGEN_RETRIES", "1")),
            llm_stream=os.environ.get("LLM_STREAM", "1") not in ("0", "false", "False"),
            log_truncate=int(os.environ["LLM_LOG_TRUNCATE"]) if os.environ.get("LLM_LOG_TRUNCATE") else None,
            web_search_provider=os.environ.get("WEB_SEARCH_PROVIDER", "none"),
            web_search_max_uses=int(os.environ.get("WEB_SEARCH_MAX_USES", "5")),
            creative_planning=os.environ.get("CREATIVE_PLANNING", "1")
            not in ("0", "false", "False", ""),
            temperature=float(t) if (t := os.environ.get("LLM_TEMPERATURE", "").strip()) else None,
            effort_plan=os.environ.get("LLM_EFFORT_PLAN", "medium"),
            effort_execute=os.environ.get("LLM_EFFORT_EXECUTE", "medium"),
            effort_verify=os.environ.get("LLM_EFFORT_VERIFY", ""),
            effort_correct=os.environ.get("LLM_EFFORT_CORRECT", ""),
        )

    def validate(self) -> None:
        """Check that required config values are present."""
        if not self.api_key:
            raise ValueError("LLM_API_KEY is required. Set it in .env or as an environment variable.")
