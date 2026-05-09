"""Pydantic request models for the generation API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GenerateParams(BaseModel):
    """Optional overrides for a generation request.

    Mirrors the CLI flags on `src.cli` `generate` subcommand. All fields are
    optional; missing fields fall back to random sampling in `sample_params()`.
    """

    grade: int | None = None
    style: list[str] | None = None
    context: list[str] | None = None
    set_type: str | None = Field(default=None, alias="set_type")
    q_type: list[str] | None = None
    count: int = 1
    skip_verify: bool = False
    seed: int | None = None

    model_config = {"populate_by_name": True}
