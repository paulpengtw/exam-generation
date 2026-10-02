"""End-to-end 社會領域 figure-kind policy regression coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.common.figure_policy import effective_figure_kind, normalize_figure_kind
from src.common.open_response_rubric import EXTRA_ITEMS_FIXED_SENTENCE
from src.config import Config
from src.social_studies.cli import generate_one
from src.social_studies.sampler import sample_params
from src.social_studies.schemas import ExamQuestion


def _valid_open_response_rubric(index: int) -> list[dict[str, object]]:
    label = f"概念{index}"
    return [
        {
            "code": "2",
            "規準說明": f"{label}完整推理。{EXTRA_ITEMS_FIXED_SENTENCE}",
            "學生作答實例": [f"{label}完整作答"],
        },
        {
            "code": "1",
            "規準說明": f"{label}推理鏈有缺口。",
            "學生作答實例": [f"{label}缺少證據", f"{label}理由未連結"],
        },
        {
            "code": "0",
            "規準說明": f"{label}方向錯誤。",
            "學生作答實例": [f"{label}錯誤作答"],
        },
    ]


def _text_shell(top_kind: str) -> dict[str, Any]:
    return {
        "核心問題": "測試核心問題",
        "文本": "測試文本素材",
        "取材來源": ["測試來源"],
        "subquestions": [
            {"序號": 1, "題型": "選擇題", "出題概念": "概念一"},
            {"序號": 2, "題型": "選擇題", "出題概念": "概念二"},
            {"序號": 3, "題型": "選擇題", "出題概念": "概念三"},
        ],
        "chart_spec": {
            "render_mode": "gpt_image",
            "figure_kind": top_kind,
            "description": "題幹圖片",
        },
    }


def _subquestion_response(index: int, figure_kind: str) -> dict[str, Any]:
    return {
        "序號": index,
        "年級": 8,
        "科目": ["地理"],
        "核心素養": ["社-J-A2"],
        "學習內容": [{"編碼": "地Af-Ⅳ-3", "說明": "都市發展"}],
        "學習表現": [{"編碼": "社1b-Ⅳ-1", "說明": "解析"}],
        "出題概念": "概念",
        "題型": "選擇題",
        "題目": "根據圖片，以下何者正確？（A）甲（B）乙（C）丙（D）丁",
        "答案": "A",
        "答案解析": "解析",
        "評分規準": _valid_open_response_rubric(index),
        "chart_spec": {
            "render_mode": "gpt_image",
            "figure_kind": figure_kind,
            "description": f"小題 {index} 圖片",
        },
    }


class _PipelineMainClient:
    """Fake text/image client; calls after the text shell are policy repairs."""

    def __init__(self, top_kind: str, repair_kinds: list[str]) -> None:
        self.top_kind = top_kind
        self.repair_kinds = iter(repair_kinds)
        self.calls = 0
        self.repair_calls: list[dict[str, Any]] = []

    def get_observer(self) -> None:
        return None

    def generate_json(self, system: str, _user: str, **_kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return _text_shell(self.top_kind)

        kind = next(self.repair_kinds)
        repair_kind = (
            "declaration"
            if "只補上既有視覺素材規格" in system
            else "collision"
        )
        self.repair_calls.append({"kind": repair_kind, "figure_kind": kind})
        return {
            "chart_spec": {
                "render_mode": "gpt_image",
                "figure_kind": kind,
                "description": "修補圖片",
            }
        }

    def generate_image(self, _prompt: str, output_path: Path) -> str:
        output_path.write_bytes(b"png")
        return str(output_path)


class _PipelineSubClient:
    def __init__(self, visual_kinds: dict[int, str]) -> None:
        self.visual_kinds = visual_kinds

    def set_observer(self, _observer: Any) -> None:
        pass

    def generate_json(
        self,
        _system: str,
        _user: str,
        *,
        agent_override: str,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        index = int(agent_override.split("#")[1])
        response = _subquestion_response(index, self.visual_kinds.get(index, ""))
        if index not in self.visual_kinds:
            response.pop("chart_spec")
        return response


def _visual_params(visual_subquestions: int = 2):
    configs = [
        {"content_type": "含圖片"} if index <= visual_subquestions else {}
        for index in range(1, 4)
    ]
    return sample_params(
        seed=554,
        content_type="含圖片",
        sub_question_count=3,
        subquestion_configs=configs,
    )


def _run_pipeline(
    tmp_path: Path,
    question_id: str,
    *,
    top_kind: str,
    sub_kinds: dict[int, str],
    repair_kinds: list[str],
    visual_subquestions: int = 2,
) -> tuple[ExamQuestion, _PipelineMainClient, list[dict[str, Any]]]:
    client = _PipelineMainClient(top_kind, repair_kinds)
    # This is the same model_dump(mode="json") shape captured by the server's
    # on_figure_policy_entry callback before it is attached to/persisted with a result.
    persisted_trail: list[dict[str, Any]] = []
    question = generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=client,
        params=_visual_params(visual_subquestions),
        question_id=question_id,
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: _PipelineSubClient(sub_kinds),
        on_figure_policy_entry=lambda entry: persisted_trail.append(
            entry.model_dump(mode="json")
        ),
    )
    assert isinstance(question, ExamQuestion)
    return question, client, persisted_trail


def _figure_kinds(question: ExamQuestion) -> list[str]:
    specs = [question.chart_spec, *(sub.chart_spec for sub in question.subquestions)]
    return [
        normalize_figure_kind(effective_figure_kind(spec))
        for spec in specs
        if spec is not None
    ]


def _entries(trail: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [entry for entry in trail if entry["kind"] == kind]


def test_declared_duplicate_repair_records_warning_at_social_pipeline_seam(
    tmp_path: Path,
) -> None:
    question, client, trail = _run_pipeline(
        tmp_path,
        "ss_declared_duplicate_seam",
        top_kind="表格",
        sub_kinds={1: "表格"},
        repair_kinds=["表格"],
        visual_subquestions=1,
    )

    assert len(client.repair_calls) == 1
    assert [call["kind"] for call in client.repair_calls] == ["collision"]
    collisions = _entries(trail, "collision")
    repairs = _entries(trail, "repair")
    warnings = _entries(trail, "warning")
    assert [(entry["left"], entry["right"], entry["effective_figure_kind"])
            for entry in collisions] == [("題幹", "小題 1", "表格")]
    assert len(repairs) == 1
    assert repairs[0]["target"] == "小題 1"
    assert repairs[0]["before_effective_figure_kind"] == "表格"
    assert repairs[0]["after_effective_figure_kind"] == "表格"
    assert repairs[0]["forbidden_kinds"] == ["表格"]
    assert repairs[0]["succeeded"] is True
    assert repairs[0]["error"] is None
    assert [(entry["label"], entry["effective_figure_kind"])
            for entry in _entries(trail, "spec")[:2]] == [
        ("題幹", "表格"),
        ("小題 1", "表格"),
    ]
    assert len(warnings) == 1
    assert warnings[0]["right"] == "小題 1"
    assert warnings[0]["duplicate_image_shipped"] is True
    assert "diversity violation remains" in warnings[0]["message"]
    assert _figure_kinds(question) == ["表格", "表格"]
    assert all(entry["code"] == "figure_policy" for entry in trail)


def test_undeclared_visual_specs_get_declaration_repairs_and_distinct_kinds(
    tmp_path: Path,
) -> None:
    question, client, trail = _run_pipeline(
        tmp_path,
        "ss_undeclared_seam",
        top_kind="",
        sub_kinds={1: "", 2: ""},
        repair_kinds=["表格", "地圖", "圓餅圖"],
    )

    assert len(client.repair_calls) == 3
    assert [call["kind"] for call in client.repair_calls] == [
        "declaration",
        "declaration",
        "declaration",
    ]
    repairs = _entries(trail, "repair")
    assert [(entry["target"], entry["before_effective_figure_kind"],
             entry["after_effective_figure_kind"]) for entry in repairs] == [
        ("題幹", "", "表格"),
        ("小題 1", "", "地圖"),
        ("小題 2", "", "圓餅圖"),
    ]
    assert [entry["forbidden_kinds"] for entry in repairs] == [
        [],
        ["表格"],
        ["表格", "地圖"],
    ]
    assert all(entry["succeeded"] is True and entry["error"] is None
               for entry in repairs)
    assert _entries(trail, "collision") == []
    assert _entries(trail, "warning") == []
    assert _figure_kinds(question) == ["表格", "地圖", "圓餅圖"]
    assert len(_entries(trail, "spec")) >= 3
    assert {entry["label"] for entry in _entries(trail, "spec")} == {
        "題幹", "小題 1", "小題 2",
    }


def test_synonym_kinds_collide_at_social_pipeline_seam_and_use_shared_budget(
    tmp_path: Path,
) -> None:
    question, client, trail = _run_pipeline(
        tmp_path,
        "ss_synonym_collision_seam",
        top_kind="長條圖",
        sub_kinds={1: "直條圖", 2: "bar_chart"},
        repair_kinds=["地圖", "圓餅圖", "折線圖"],
    )

    assert len(client.repair_calls) == 3
    assert [call["kind"] for call in client.repair_calls] == [
        "collision", "collision", "collision",
    ]
    collisions = _entries(trail, "collision")
    assert [(entry["left"], entry["right"], entry["effective_figure_kind"])
            for entry in collisions] == [
        ("題幹", "小題 1", "長條圖"),
        ("題幹", "小題 2", "長條圖"),
        ("小題 1", "小題 2", "長條圖"),
    ]
    repairs = _entries(trail, "repair")
    assert len(repairs) == 3
    assert [entry["target"] for entry in repairs] == [
        "小題 1", "小題 2", "小題 2",
    ]
    assert all("長條圖" in entry["forbidden_kinds"] for entry in repairs)
    assert _entries(trail, "warning") == []
    assert len(_figure_kinds(question)) == len(set(_figure_kinds(question)))
    assert _figure_kinds(question) == ["長條圖", "地圖", "折線圖"]


def test_combined_social_pipeline_shape_persists_trail_and_repairs_all_visuals(
    tmp_path: Path,
) -> None:
    question, client, trail = _run_pipeline(
        tmp_path,
        "ss_combined_original_failure_shape",
        top_kind="表格",
        sub_kinds={1: "表格", 2: "表格"},
        repair_kinds=["地圖", "圓餅圖", "折線圖"],
    )

    assert question.圖片 == "ss_combined_original_failure_shape.png"
    assert (tmp_path / question.圖片).exists()
    assert [sub.圖片 for sub in question.subquestions[:2]] == [
        "ss_combined_original_failure_shape_sq1.png",
        "ss_combined_original_failure_shape_sq2.png",
    ]
    assert all((tmp_path / sub.圖片).exists() for sub in question.subquestions[:2])
    assert len(client.repair_calls) == 3
    assert len(_entries(trail, "collision")) == 3
    assert len(_entries(trail, "repair")) == 3
    assert _entries(trail, "warning") == []
    assert len(_figure_kinds(question)) == len(set(_figure_kinds(question)))
    assert _figure_kinds(question) == ["表格", "地圖", "折線圖"]
    assert [(entry["label"], entry["effective_figure_kind"])
            for entry in _entries(trail, "spec")[-3:]] == [
        ("題幹", "表格"),
        ("小題 1", "地圖"),
        ("小題 2", "折線圖"),
    ]

    result_event = {
        "data": question.model_dump(mode="json"),
        "figure_policy_trail": trail,
    }
    persisted_trail = result_event["figure_policy_trail"]
    assert isinstance(persisted_trail, list)
    assert all(entry["code"] == "figure_policy" for entry in persisted_trail)
    assert [(entry["kind"], entry.get("label"), entry.get("target"),
             entry.get("left"), entry.get("right")) for entry in persisted_trail
            if entry["kind"] in {"collision", "repair"}] == [
        ("collision", None, None, "題幹", "小題 1"),
        ("repair", None, "小題 1", None, None),
        ("collision", None, None, "題幹", "小題 2"),
        ("repair", None, "小題 2", None, None),
        ("collision", None, None, "小題 1", "小題 2"),
        ("repair", None, "小題 2", None, None),
    ]
