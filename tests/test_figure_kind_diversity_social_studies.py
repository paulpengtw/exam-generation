"""Pipeline tests for SS 圖像種類 diversity enforcement."""

from __future__ import annotations

from pathlib import Path

from src.config import Config
from src.social_studies.cli import generate_one
from src.social_studies.sampler import sample_params
from src.social_studies.schemas import ExamQuestion

_TEXT_SHELL_WITH_TOP_IMAGE = {
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
        "figure_kind": "表格",
        "description": "題幹圖片",
    },
}


def _subquestion_response(index: int, figure_kind: str) -> dict:
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
        "評分規準": [],
        "chart_spec": {
            "render_mode": "gpt_image",
            "figure_kind": figure_kind,
            "description": "小題圖片",
        },
    }


class _MainClient:
    def __init__(self, repair_kind: str, top_kind: str = "表格") -> None:
        self.repair_kind = repair_kind
        self.top_kind = top_kind
        self.calls = 0
        self.repair_calls: list[tuple[str, str]] = []
        self.rendered_paths: list[Path] = []

    def get_observer(self):
        return None

    def generate_json(self, system, user, **kwargs):
        self.calls += 1
        if self.calls == 1:
            response = dict(_TEXT_SHELL_WITH_TOP_IMAGE)
            response["chart_spec"] = dict(response["chart_spec"])
            response["chart_spec"]["figure_kind"] = self.top_kind
            return response
        self.repair_calls.append((system, user))
        return {
            "chart_spec": {
                "render_mode": "gpt_image",
                "figure_kind": self.repair_kind,
                "description": "修補圖片",
            }
        }

    def generate_image(self, _prompt: str, output_path) -> str:
        path = Path(output_path)
        self.rendered_paths.append(path)
        path.write_bytes(b"png")
        return str(path)


class _SubClient:
    def __init__(self, figure_kind: str) -> None:
        self.figure_kind = figure_kind

    def set_observer(self, _obs) -> None:
        pass

    def generate_json(self, _system, _user, agent_override=None, **_kwargs):
        index = int(agent_override.split("#")[1])
        response = _subquestion_response(index, self.figure_kind)
        if index != 1:
            response.pop("chart_spec")
        return response


class _UndeclaredVisualMainClient:
    def __init__(self, repaired_kinds: list[str], events: list[str]) -> None:
        self.repaired_kinds = iter(repaired_kinds)
        self.events = events
        self.calls = 0
        self.repair_calls: list[tuple[str, str]] = []

    def get_observer(self):
        return None

    def generate_json(self, _system, user, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            self.events.append("text")
            return {
                "核心問題": "測試核心問題",
                "文本": "測試文本素材",
                "取材來源": ["測試來源"],
                "subquestions": [
                    {"序號": 1, "題型": "選擇題", "出題概念": "概念一"},
                    {"序號": 2, "題型": "選擇題", "出題概念": "概念二"},
                    {"序號": 3, "題型": "選擇題", "出題概念": "概念三"},
                ],
            }
        kind = next(self.repaired_kinds)
        self.repair_calls.append(("repair", user))
        self.events.append("declaration_repair")
        return {
            "chart_spec": {
                "render_mode": "gpt_image",
                "figure_kind": kind,
                "description": "宣告圖像種類後的圖片",
            }
        }

    def generate_image(self, _prompt: str, output_path) -> str:
        path = Path(output_path)
        self.events.append(f"render:{path.name}")
        path.write_bytes(b"png")
        return str(path)


class _UndeclaredVisualSubClient:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def set_observer(self, _obs) -> None:
        pass

    def generate_json(self, _system, _user, agent_override=None, **_kwargs):
        index = int(agent_override.split("#")[1])
        response = _subquestion_response(index, "")
        if index == 3:
            response.pop("chart_spec")
        return response


def test_collision_gets_one_repair_and_still_duplicate_ships_with_warning(
    tmp_path: Path,
    capsys,
) -> None:
    params = sample_params(
        seed=1,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[{"content_type": "含圖片"}, {}, {}],
    )
    client = _MainClient(repair_kind="表格")

    question = generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=client,
        params=params,
        question_id="collision_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: _SubClient("表格"),
    )

    assert isinstance(question, ExamQuestion)
    assert len(client.repair_calls) == 1
    assert question.chart_spec is not None
    assert question.subquestions[0].chart_spec is not None
    assert question.圖片 == "collision_test.png"
    assert question.subquestions[0].圖片 == "collision_test_sq1.png"
    assert (tmp_path / "collision_test.png").exists()
    assert (tmp_path / "collision_test_sq1.png").exists()
    assert "圖像種類" in capsys.readouterr().err


def test_undeclared_visual_specs_are_repaired_once_before_subquestion_rendering(
    tmp_path: Path,
) -> None:
    params = sample_params(
        seed=1,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "含圖片"},
            {"content_type": "含圖片"},
            {},
        ],
    )
    events: list[str] = []
    client = _UndeclaredVisualMainClient(["地圖", "表格"], events)

    question = generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=client,
        params=params,
        question_id="declaration_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: _UndeclaredVisualSubClient(events),
    )

    assert isinstance(question, ExamQuestion)
    assert len(client.repair_calls) == 2
    assert [sub.chart_spec.figure_kind for sub in question.subquestions[:2]] == [
        "地圖",
        "表格",
    ]
    first_render = next(i for i, event in enumerate(events) if event.startswith("render:"))
    assert all(i < first_render for i, event in enumerate(events) if event == "declaration_repair")


def test_repair_prompt_lists_forbidden_figure_kinds_in_canonical_form(tmp_path: Path) -> None:
    params = sample_params(
        seed=1,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[{"content_type": "含圖片"}, {}, {}],
    )
    client = _MainClient(repair_kind="地圖", top_kind="直條圖")

    generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=client,
        params=params,
        question_id="canonical_forbidden_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: _SubClient("長條圖"),
    )

    assert len(client.repair_calls) == 1
    forbidden_line = next(
        line for line in client.repair_calls[0][1].splitlines() if "圖像種類不得為" in line
    )
    assert forbidden_line == "- **圖像種類不得為：**長條圖"


def test_pinned_subquestion_repairs_top_level_and_rerenders_existing_png(tmp_path: Path) -> None:
    params = sample_params(
        seed=1,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "含圖片", "figure_kind": "表格"},
            {},
            {},
        ],
    )
    client = _MainClient(repair_kind="地圖")

    question = generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=client,
        params=params,
        question_id="pinned_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: _SubClient("廣告"),
    )

    assert isinstance(question, ExamQuestion)
    assert len(client.repair_calls) == 1
    assert question.chart_spec is not None
    assert question.chart_spec.figure_kind == "地圖"
    assert question.subquestions[0].chart_spec is not None
    assert question.subquestions[0].chart_spec.figure_kind == "表格"
    assert client.rendered_paths.count(tmp_path / "pinned_test.png") == 2
    assert (tmp_path / "pinned_test.png").exists()
    assert (tmp_path / "pinned_test_sq1.png").exists()


def test_clean_visual_run_emits_figure_policy_entries_for_the_題幹_and_visual_小題(
    tmp_path: Path,
) -> None:
    params = sample_params(
        seed=1,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[{"content_type": "含圖片"}, {}, {}],
    )
    events: list[dict] = []

    generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=_MainClient(repair_kind="地圖"),
        params=params,
        question_id="clean_policy_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: _SubClient("地圖"),
        on_figure_policy_entry=lambda entry: events.append(entry.model_dump(mode="json")),
    )

    assert [entry["kind"] for entry in events] == ["spec", "spec"]
    assert [(entry["label"], entry["effective_figure_kind"]) for entry in events] == [
        ("題幹", "表格"),
        ("小題 1", "地圖"),
    ]


def test_collision_repair_is_recorded_in_the_figure_policy_trail(tmp_path: Path) -> None:
    params = sample_params(
        seed=1,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[{"content_type": "含圖片"}, {}, {}],
    )
    events: list[dict] = []

    generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=_MainClient(repair_kind="地圖"),
        params=params,
        question_id="repair_policy_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: _SubClient("表格"),
        on_figure_policy_entry=lambda entry: events.append(entry.model_dump(mode="json")),
    )

    collisions = [entry for entry in events if entry["kind"] == "collision"]
    repairs = [entry for entry in events if entry["kind"] == "repair"]
    assert collisions == [
        {
            "code": "figure_policy",
            "kind": "collision",
            "question_id": "repair_policy_test",
            "left": "題幹",
            "right": "小題 1",
            "effective_figure_kind": "表格",
            "timestamp": collisions[0]["timestamp"],
        }
    ]
    assert len(repairs) == 1
    assert repairs[0]["target"] == "小題 1"
    assert repairs[0]["before_effective_figure_kind"] == "表格"
    assert repairs[0]["after_effective_figure_kind"] == "地圖"
    assert repairs[0]["succeeded"] is True


def test_collision_shipped_with_warning_is_recorded_in_the_figure_policy_trail(
    tmp_path: Path,
) -> None:
    params = sample_params(
        seed=1,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[{"content_type": "含圖片"}, {}, {}],
    )
    events: list[dict] = []

    generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=_MainClient(repair_kind="表格"),
        params=params,
        question_id="warning_policy_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: _SubClient("表格"),
        on_figure_policy_entry=lambda entry: events.append(entry.model_dump(mode="json")),
    )

    warnings = [entry for entry in events if entry["kind"] == "warning"]
    assert len(warnings) == 1
    assert warnings[0]["duplicate_image_shipped"] is True
    assert warnings[0]["left"] == "題幹"
    assert warnings[0]["right"] == "小題 1"
