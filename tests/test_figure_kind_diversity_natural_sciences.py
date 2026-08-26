"""Pipeline tests for NS 圖像種類 diversity enforcement."""

from __future__ import annotations

from pathlib import Path

from src.config import Config
from src.natural_sciences.cli import generate_one
from src.natural_sciences.sampler import sample_params
from src.natural_sciences.schemas import ExamQuestion

_TEXT_SHELL_WITH_TOP_IMAGE = {
    "核心問題": "測試核心問題",
    "文本": "測試文本素材",
    "取材來源": ["測試來源"],
    "subquestions": [
        {"序號": 1, "題型": "Simple multiple-choice", "出題概念": "概念一"},
        {"序號": 2, "題型": "Simple multiple-choice", "出題概念": "概念二"},
        {"序號": 3, "題型": "Simple multiple-choice", "出題概念": "概念三"},
    ],
    "chart_spec": {
        "render_mode": "gpt_image",
        "figure_kind": "",
        "description": "題幹圖片",
    },
}


def _subquestion_response(index: int) -> dict:
    response = {
        "序號": index,
        "年級": 8,
        "科目": ["自然科學"],
        "科學能力": ["能力一：以科學的角度解釋現象"],
        "核心素養": [],
        "學習內容": [],
        "學習表現": [],
        "出題概念": "科學概念",
        "題型": "Simple multiple-choice",
        "題目": "根據圖片，以下何者正確？（A）甲（B）乙（C）丙（D）丁",
        "答案": "A",
        "答案解析": "解析",
        "評分規準": [],
    }
    if index != 3:
        response["chart_spec"] = {
            "render_mode": "gpt_image",
            "figure_kind": "",
            "description": "小題圖片",
        }
    return response


class _NSDiversityMainClient:
    """Return three declaration repairs, then three collision repairs."""

    def __init__(self) -> None:
        self.calls = 0
        self.repair_calls: list[tuple[str, str]] = []
        self._repair_kinds = iter(
            ["折線圖", "折線圖", "折線圖", "地圖", "盒鬚圖", "圓餅圖"]
        )

    def get_observer(self):
        return None

    def generate_json(self, system, user, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return _TEXT_SHELL_WITH_TOP_IMAGE
        self.repair_calls.append((system, user))
        return {
            "chart_spec": {
                "render_mode": "gpt_image",
                "figure_kind": next(self._repair_kinds),
                "description": "修補圖片",
            }
        }

    def generate_image(self, _prompt: str, output_path) -> str:
        path = Path(output_path)
        path.write_bytes(b"png")
        return str(path)


class _NSDiversitySubClient:
    def set_observer(self, _obs) -> None:
        pass

    def generate_json(self, _system, _user, agent_override=None, **_kwargs):
        index = int(agent_override.split("#")[1])
        return _subquestion_response(index)


class _NSPolicyMainClient:
    def __init__(self, repair_kinds: list[str], *, include_top: bool = True) -> None:
        self.calls = 0
        self.repair_calls: list[tuple[str, str]] = []
        self._repair_kinds = iter(repair_kinds)
        self._include_top = include_top

    def get_observer(self):
        return None

    def generate_json(self, system, user, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            response = {
                **_TEXT_SHELL_WITH_TOP_IMAGE,
                "subquestions": list(_TEXT_SHELL_WITH_TOP_IMAGE["subquestions"]),
            }
            if not self._include_top:
                response.pop("chart_spec")
            return response
        self.repair_calls.append((system, user))
        return {
            "chart_spec": {
                "render_mode": "gpt_image",
                "figure_kind": next(self._repair_kinds),
                "description": "修補圖片",
            }
        }

    def generate_image(self, _prompt: str, output_path) -> str:
        path = Path(output_path)
        path.write_bytes(b"png")
        return str(path)


class _NSPolicySubClient:
    def __init__(self, visual_indices: set[int], figure_kind: str = "") -> None:
        self.visual_indices = visual_indices
        self.figure_kind = figure_kind

    def set_observer(self, _obs) -> None:
        pass

    def generate_json(self, _system, _user, agent_override=None, **_kwargs):
        index = int(agent_override.split("#")[1])
        response = _subquestion_response(index)
        if index not in self.visual_indices:
            response.pop("chart_spec", None)
        elif index == 3:
            response["chart_spec"] = {
                "render_mode": "gpt_image",
                "figure_kind": self.figure_kind,
                "description": "小題圖片",
            }
        elif self.figure_kind:
            response["chart_spec"]["figure_kind"] = self.figure_kind
        return response


def _run_policy_pipeline(
    tmp_path: Path,
    question_id: str,
    client: _NSPolicyMainClient,
    sub_client: _NSPolicySubClient,
    *,
    params=None,
) -> tuple[ExamQuestion, list[dict]]:
    policy_events: list[dict] = []
    question = generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=client,
        params=params
        or sample_params(
            seed=1,
            content_type="純文字",
            sub_question_count=3,
            subquestion_configs=[{}, {}, {}],
        ),
        question_id=question_id,
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: sub_client,
        on_figure_policy_entry=lambda entry: policy_events.append(
            entry.model_dump(mode="json")
        ),
    )
    assert isinstance(question, ExamQuestion)
    return question, policy_events


def test_ns_pipeline_repairs_undeclared_same_kind_visuals_then_checks_collision(
    tmp_path: Path,
) -> None:
    """The #547 shape reaches declaration repair and collision detection."""
    params = sample_params(
        seed=1,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[{}, {}, {}],
    )
    policy_events: list[dict] = []
    client = _NSDiversityMainClient()

    question = generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=client,
        params=params,
        question_id="ns_547_shape",
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: _NSDiversitySubClient(),
        on_figure_policy_entry=lambda entry: policy_events.append(
            entry.model_dump(mode="json")
        ),
    )

    assert isinstance(question, ExamQuestion)
    assert len(client.repair_calls) == 6
    assert question.chart_spec is not None
    assert question.chart_spec.figure_kind == "折線圖"
    assert [
        question.subquestions[0].chart_spec.figure_kind,
        question.subquestions[1].chart_spec.figure_kind,
        question.subquestions[2].chart_spec,
    ] == [
        "地圖",
        "圓餅圖",
        None,
    ]
    assert [entry["kind"] for entry in policy_events].count("collision") == 3
    assert any(entry["kind"] == "repair" for entry in policy_events)


def test_ns_undeclared_spec_failure_ships_image_and_records_warning(tmp_path: Path) -> None:
    client = _NSPolicyMainClient([""], include_top=False)
    question, events = _run_policy_pipeline(
        tmp_path,
        "ns_undeclared_warning",
        client,
        _NSPolicySubClient({1}),
    )

    assert question.subquestions[0].chart_spec is not None
    assert question.subquestions[0].chart_spec.figure_kind == ""
    assert (tmp_path / "ns_undeclared_warning_sq1.png").exists()
    repairs = [entry for entry in events if entry["kind"] == "repair"]
    warnings = [entry for entry in events if entry["kind"] == "warning"]
    assert len(repairs) == 1
    assert repairs[0]["succeeded"] is False
    assert len(warnings) == 1
    assert warnings[0]["duplicate_image_shipped"] is False


def test_ns_aliases_normalize_before_collision_repair(tmp_path: Path) -> None:
    client = _NSPolicyMainClient(["直條圖", "bar_chart", "地圖"])
    question, events = _run_policy_pipeline(
        tmp_path,
        "ns_alias_collision",
        client,
        _NSPolicySubClient({1}),
    )

    collisions = [entry for entry in events if entry["kind"] == "collision"]
    repairs = [entry for entry in events if entry["kind"] == "repair"]
    assert len(collisions) == 1
    assert collisions[0]["effective_figure_kind"] == "長條圖"
    assert len(repairs) == 3
    assert question.chart_spec is not None
    assert question.chart_spec.figure_kind == "長條圖"
    assert question.subquestions[0].chart_spec is not None
    assert question.subquestions[0].chart_spec.figure_kind == "地圖"


def test_ns_unresolved_collision_ships_and_records_duplicate_warning(
    tmp_path: Path,
) -> None:
    client = _NSPolicyMainClient(["地圖", "地圖", "地圖"])
    _question, events = _run_policy_pipeline(
        tmp_path,
        "ns_collision_warning",
        client,
        _NSPolicySubClient({1}),
    )

    warnings = [entry for entry in events if entry["kind"] == "warning"]
    assert len(warnings) == 1
    assert warnings[0]["duplicate_image_shipped"] is True
    assert warnings[0]["left"] == "題幹"
    assert warnings[0]["right"] == "小題 1"


def test_ns_pinned_kind_yields_to_top_level_and_kill_switch_skips_collision(
    tmp_path: Path,
) -> None:
    pinned_params = sample_params(
        seed=1,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[{"figure_kind": "表格"}, {}, {}],
    )
    client = _NSPolicyMainClient(["表格", "地圖"])
    question, events = _run_policy_pipeline(
        tmp_path,
        "ns_pinned",
        client,
        _NSPolicySubClient({1}, "表格"),
        params=pinned_params,
    )
    assert question.chart_spec is not None
    assert question.chart_spec.figure_kind == "地圖"
    assert question.subquestions[0].chart_spec is not None
    assert question.subquestions[0].chart_spec.figure_kind == "表格"
    assert len([entry for entry in events if entry["kind"] == "collision"]) == 1

    kill_switch_params = pinned_params.model_copy(
        update={"allow_duplicate_figure_kinds": True}
    )
    _question, kill_events = _run_policy_pipeline(
        tmp_path,
        "ns_kill_switch",
        _NSPolicyMainClient(["表格"]),
        _NSPolicySubClient({1}, "表格"),
        params=kill_switch_params,
    )
    assert [entry for entry in kill_events if entry["kind"] == "collision"] == []
