from __future__ import annotations

from pathlib import Path


def test_natural_sciences_loader_preserves_multi_parent_admitted_values(
    tmp_path: Path,
) -> None:
    (tmp_path / "schema_meta.csv").write_text(
        "欄位,值\n學習階段,第四學習階段\ngrades,7;8;9\n",
        encoding="utf-8-sig",
    )
    (tmp_path / "schema_parameters.csv").write_text(
        "類別,value,instruction,parent\n"
        "情境,Personal,,\n"
        "情境,Global,,\n"
        "情境子類別,Shared child,,Personal;Global\n",
        encoding="utf-8-sig",
    )

    from src.natural_sciences.schema_loader import load_schemas

    schemas = load_schemas(tmp_path)

    assert schemas["情境子類別"] == [
        {
            "value": "Shared child",
            "instruction": "",
            "parent": "Personal;Global",
            "admitted_by": {"情境": ["Personal", "Global"]},
        },
    ]
