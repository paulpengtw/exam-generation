"""Utility routes: /health and /api/schemas."""

# ruff: noqa: E501

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status

from server.auth.dependencies import get_config
from server.config import ServerConfig
from src.common.curriculum_loader import load_learning_performance as load_common_lp
from src.natural_sciences.curriculum_loader import (
    load_learning_content as load_ns_learning_content,
)
from src.natural_sciences.curriculum_loader import (
    load_learning_performance as load_ns_learning_performance,
)
from src.natural_sciences.schema_loader import load_schemas as load_ns_schemas
from src.social_studies.curriculum_loader import load_learning_content as load_ss_learning_content
from src.social_studies.curriculum_loader import load_learning_performance
from src.social_studies.schema_loader import load_schemas as load_ss_schemas

router = APIRouter(tags=["utility"])


_MATH_SUBJECTS = [
    {
        "value": "數與量",
        "instruction": "題目主要涵蓋108課綱數學領域「數與量」主題（編碼前綴 N/n），含整數、有理數、實數、估算、單位換算等。",
    },
    {
        "value": "代數",
        "instruction": "題目主要涵蓋108課綱數學領域「代數」主題（編碼前綴 R/A/F），含關係、方程式、函數、不等式等。",
    },
    {
        "value": "幾何",
        "instruction": "題目主要涵蓋108課綱數學領域「幾何」主題（編碼前綴 S/G），含平面與立體幾何、座標、變換等。",
    },
    {
        "value": "統計與機率",
        "instruction": "題目主要涵蓋108課綱數學領域「統計與機率」主題（編碼前綴 D/P），含資料整理、敘述統計、機率初步等。",
    },
]

_MATH_CONTENT_TYPES = [
    {
        "value": "純文字",
        "instruction": "純文字題目，不需任何圖表或圖片。題目僅透過文字描述情境與數學問題，不得輸出 chart_spec。",
    },
    {
        "value": "含圖片",
        "instruction": "題目必須搭配圖片式或視覺式素材，如幾何圖形、示意圖、座標平面、數線等，並以 chart_spec 描述素材。",
    },
    {
        "value": "graphs/charts/tables",
        "instruction": "題目必須搭配圖表或表格素材，如統計圖、折線圖、圓餅圖、比較表或資料表，並以 chart_spec 提供完整資料。",
    },
    {
        "value": "customized",
        "instruction": "由使用者自行輸入題目內容類型；送出時以前端輸入文字作為實際內容類型。",
    },
]


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/schemas")
async def get_schemas(
    subject: str = Query(default="math"),
    grade: int | None = Query(default=None),
    config: ServerConfig = Depends(get_config),
) -> dict:
    from src.sampler import grade_to_learning_stage

    def _resolve_stage(schemas: dict, grade: int | None) -> str:
        if grade is not None:
            try:
                return grade_to_learning_stage(grade)
            except ValueError:
                pass
        return schemas.get("學習階段", "")

    if subject == "social_studies":
        try:
            schemas = load_ss_schemas(config.social_studies_curriculum_dir)
            performance = load_learning_performance(
                config.social_studies_curriculum_dir / "learning_performance.json"
            )
            learning_stage = _resolve_stage(schemas, grade)
            schemas["學習表現"] = [
                {
                    "value": entry["value"],
                    "instruction": entry.get("說明", ""),
                    "科目": entry.get("科目", ""),
                }
                for entry in performance.get("學習表現", [])
                if entry.get("學習階段") == learning_stage
            ]
            content = load_ss_learning_content(
                config.social_studies_curriculum_dir / "learning_content.json"
            )
            schemas["學習內容"] = [
                {
                    "value": entry["value"],
                    "instruction": entry.get("條目說明", ""),
                    "科目": entry.get("科目", ""),
                }
                for entry in content.get("學習內容", [])
                if entry.get("學習階段") == learning_stage
            ]
            return schemas
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"failed to load social_studies schemas: {exc}",
            ) from exc

    if subject == "natural_sciences":
        try:
            schemas = load_ns_schemas(config.natural_sciences_curriculum_dir)
            learning_stage = _resolve_stage(schemas, grade)
            performance = load_ns_learning_performance(
                config.natural_sciences_curriculum_dir / "learning_performance.json"
            )
            content = load_ns_learning_content(
                config.natural_sciences_curriculum_dir / "learning_content.json"
            )
            schemas["學習表現"] = [
                {
                    "value": entry["value"],
                    "instruction": entry.get("說明", ""),
                    "科目": entry.get("科目", ""),
                }
                for entry in performance.get("學習表現", [])
                if entry.get("學習階段") == learning_stage
            ]
            schemas["學習內容"] = [
                {
                    "value": entry["value"],
                    "instruction": entry.get("條目說明", ""),
                    "科目": entry.get("科目", ""),
                }
                for entry in content.get("學習內容", [])
                if entry.get("學習階段") == learning_stage
            ]
            ns_subjects = sorted({
                entry["科目"] for entry in schemas["學習內容"] if entry.get("科目")
            })
            if ns_subjects:
                schemas["科目"] = [{"value": s, "instruction": ""} for s in ns_subjects]
            return schemas
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"failed to load natural_sciences schemas: {exc}",
            ) from exc

    if subject == "math":
        try:
            path: Path = config.question_schemas_path
            with path.open("r", encoding="utf-8") as f:
                schemas = json.load(f)
            schemas["科目"] = list(_MATH_SUBJECTS)
            schemas["題目內容類型"] = list(_MATH_CONTENT_TYPES)
            learning_stage = _resolve_stage(schemas, grade)
            performance = load_common_lp(config.math_curriculum_dir)
            schemas["學習表現"] = [
                {
                    "value": entry["value"],
                    "instruction": entry.get("說明", ""),
                    "科目": entry.get("科目", ""),
                }
                for entry in performance.get("學習表現", [])
                if entry.get("學習階段") == learning_stage
            ]
            return schemas
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="schemas file not found for subject 'math'",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"failed to load math schemas: {exc}",
            ) from exc

    path = config.question_schemas_path
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"schemas file not found for subject '{subject}'",
        ) from exc
