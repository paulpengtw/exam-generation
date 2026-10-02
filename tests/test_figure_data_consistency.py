"""Pure tests for cross-figure chart data consistency."""

from __future__ import annotations

from pathlib import Path

from src.common import figure_policy
from src.common.open_response_rubric import EXTRA_ITEMS_FIXED_SENTENCE
from src.config import Config
from src.natural_sciences.cli import generate_one as generate_ns_one
from src.natural_sciences.sampler import sample_params as sample_ns_params
from src.natural_sciences.schemas import ExamQuestion as NSExamQuestion
from src.social_studies.cli import generate_one
from src.social_studies.sampler import sample_params
from src.social_studies.schemas import ExamQuestion


def _spec(series_name: str, values: list[int]) -> dict:
    return {
        "render_mode": "html",
        "labels": {"y": "全球能源占比（%）"},
        "data": {
            "x_labels": [1990, 2023],
            "series": [{"name": series_name, "values": values}],
        },
    }


def test_detects_conflicting_shared_series_at_overlapping_x_values() -> None:
    detector = getattr(figure_policy, "find_data_inconsistencies", None)
    assert detector is not None, "shared chart-data consistency detector is missing"

    conflicts = detector(
        [
            _spec("石油", [38, 31]),
            _spec(" Petroleum ", [10, 3]),
        ]
    )

    assert len(conflicts) == 2
    assert [
        (conflict.series, conflict.x, conflict.left_value, conflict.right_value)
        for conflict in conflicts
    ] == [
        ("石油", 1990, 38.0, 10.0),
        ("石油", 2023, 31.0, 3.0),
    ]


def test_detects_conflicting_named_columns_in_table_specs() -> None:
    detector = figure_policy.find_data_inconsistencies

    def table_spec(values: list[int]) -> dict:
        return {
            "labels": {"y": "全球能源占比（%）"},
            "data": {
                "columns": ["年份", "石油"],
                "rows": [[1990, values[0]], [2023, values[1]]],
            },
        }

    conflicts = detector([table_spec([38, 31]), table_spec([10, 3])])

    assert [(conflict.x, conflict.left_value, conflict.right_value) for conflict in conflicts] == [
        (1990, 38.0, 10.0),
        (2023, 31.0, 3.0),
    ]


def test_ignores_different_series_and_different_units() -> None:
    detector = figure_policy.find_data_inconsistencies

    different_series = detector(
        [_spec("石油", [38, 31]), _spec("再生能源", [13, 16])]
    )
    different_units = detector(
        [
            _spec("石油", [38, 31]),
            {
                **_spec("石油", [3800, 3100]),
                "labels": {"y": "全球能源產量（TWh）"},
            },
        ]
    )

    assert different_series == []
    assert different_units == []


def test_accepts_agreeing_zoom_subset_and_small_rounding_difference() -> None:
    detector = figure_policy.find_data_inconsistencies

    subset = {
        "render_mode": "html",
        "labels": {"y": "全球能源占比（%）"},
        "data": {
            "x_labels": [2023],
            "series": [{"name": "石油", "values": [31.4]}],
        },
    }

    assert detector([_spec("石油", [38, 31]), subset]) == []


def _energy_chart(oil: list[int], renewable: list[int], figure_kind: str) -> dict:
    return {
        "render_mode": "gpt_image",
        "figure_kind": figure_kind,
        "labels": {"y": "全球能源占比（%）"},
        "data": {
            "x_labels": [1990, 2023],
            "series": [
                {"name": "石油", "values": oil},
                {"name": "再生能源", "values": renewable},
            ],
        },
    }


def _valid_open_response_rubric(label: str) -> list[dict[str, object]]:
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


_SS_TEXT_SHELL = {
    "核心問題": "全球能源結構如何變化？",
    "文本": "比較1990年至2023年的全球能源結構與大氣中的二氧化碳。",
    "取材來源": ["測試資料"],
    "chart_spec": _energy_chart([38, 31], [7, 13], "折線圖"),
    "subquestions": [
        {"序號": 1, "題型": "選擇題", "出題概念": "石油變化"},
        {"序號": 2, "題型": "選擇題", "出題概念": "再生能源變化"},
        {"序號": 3, "題型": "選擇題", "出題概念": "資料判讀"},
    ],
}


def _ss_subquestion(index: int) -> dict:
    values = {
        1: ([10, 3], [9, 32], "表格"),
        2: ([30, 24], [8, 16], "地圖"),
    }
    oil, renewable, figure_kind = values[index]
    return {
        "序號": index,
        "年級": 8,
        "科目": ["地理"],
        "核心素養": ["社-J-A2"],
        "學習內容": [{"編碼": "地Af-Ⅳ-3", "說明": "都市發展"}],
        "學習表現": [{"編碼": "社1b-Ⅳ-1", "說明": "解析"}],
        "出題概念": "資料判讀",
        "題型": "選擇題",
        "題目": "下列何者正確？（A）甲（B）乙（C）丙（D）丁",
        "答案": "A",
        "答案解析": "解析",
        "評分規準": [],
        "chart_spec": _energy_chart(oil, renewable, figure_kind),
    }


class _SSConsistencyMainClient:
    def __init__(self) -> None:
        self.calls = 0
        self.repair_calls: list[str] = []

    def get_observer(self):
        return None

    def generate_json(self, _system, user, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return _SS_TEXT_SHELL
        self.repair_calls.append(user)
        return {
            "chart_specs": [
                {
                    "label": "小題 1",
                    "chart_spec": _energy_chart([38, 31], [7, 13], "表格"),
                },
                {
                    "label": "小題 2",
                    "chart_spec": _energy_chart([38, 31], [7, 13], "地圖"),
                },
            ]
        }

    def generate_image(self, _prompt: str, output_path: Path) -> str:
        output_path.write_bytes(b"png")
        return str(output_path)


class _SSUnresolvedConsistencyMainClient(_SSConsistencyMainClient):
    def generate_json(self, _system, user, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return _SS_TEXT_SHELL
        self.repair_calls.append(user)
        return {"chart_specs": []}


class _SSConsistencySubClient:
    def set_observer(self, _obs) -> None:
        pass

    def generate_json(self, _system, _user, agent_override=None, **_kwargs):
        index = int(agent_override.split("#")[1])
        if index == 3:
            return {
                "序號": 3,
                "年級": 8,
                "科目": ["地理"],
                "核心素養": ["社-J-A2"],
                "學習內容": [],
                "學習表現": [],
                "出題概念": "資料判讀",
                "題型": "選擇題",
                "題目": "下列何者正確？（A）甲（B）乙（C）丙（D）丁",
                "答案": "A",
                "答案解析": "解析",
                "評分規準": [],
            }
        return _ss_subquestion(index)


class _SSCleanConsistencySubClient(_SSConsistencySubClient):
    def generate_json(self, _system, _user, agent_override=None, **_kwargs):
        index = int(agent_override.split("#")[1])
        if index == 3:
            return super().generate_json(_system, _user, agent_override, **_kwargs)
        raw = _ss_subquestion(index)
        raw["chart_spec"] = _energy_chart([38, 31], [7, 13], raw["chart_spec"]["figure_kind"])
        return raw


class _NSConsistencyMainClient:
    def __init__(self) -> None:
        self.calls = 0
        self.repair_calls: list[str] = []

    def get_observer(self):
        return None

    def generate_json(self, _system, user, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return _SS_TEXT_SHELL
        self.repair_calls.append(user)
        return {
            "chart_specs": [
                {
                    "label": "小題 1",
                    "chart_spec": _energy_chart([38, 31], [7, 13], "表格"),
                },
                {
                    "label": "小題 2",
                    "chart_spec": _energy_chart([38, 31], [7, 13], "地圖"),
                },
            ]
        }

    def generate_image(self, _prompt: str, output_path: Path) -> str:
        output_path.write_bytes(b"png")
        return str(output_path)


class _NSConsistencySubClient:
    def set_observer(self, _obs) -> None:
        pass

    def generate_json(self, _system, _user, agent_override=None, **_kwargs):
        index = int(agent_override.split("#")[1])
        if index == 3:
            return {
                "序號": 3,
                "年級": 8,
                "科目": ["自然科學"],
                "科學能力": ["能力一：以科學的角度解釋現象"],
                "核心素養": [],
                "學習內容": [],
                "學習表現": [],
                "出題概念": "資料判讀",
                "題型": "Simple multiple-choice",
                "題目": "下列何者正確？（A）甲（B）乙（C）丙（D）丁",
                "答案": "A",
                "答案解析": "解析",
                "評分規準": _valid_open_response_rubric("資料判讀"),
            }
        response = {
            "序號": index,
            "年級": 8,
            "科目": ["自然科學"],
            "科學能力": ["能力一：以科學的角度解釋現象"],
            "核心素養": [],
            "學習內容": [],
            "學習表現": [],
            "出題概念": "資料判讀",
            "題型": "Simple multiple-choice",
            "題目": "下列何者正確？（A）甲（B）乙（C）丙（D）丁",
            "答案": "A",
            "答案解析": "解析",
            "評分規準": _valid_open_response_rubric("資料判讀"),
            "chart_spec": _energy_chart(
                [10, 3] if index == 1 else [30, 24],
                [9, 32] if index == 1 else [8, 16],
                "表格" if index == 1 else "地圖",
            ),
        }
        return response


def test_social_studies_repairs_three_figure_energy_mix_inconsistency_once(
    tmp_path: Path,
) -> None:
    params = sample_params(
        seed=581,
        content_type="graphs/charts/tables",
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "graphs/charts/tables"},
            {"content_type": "graphs/charts/tables"},
            {},
        ],
    )
    client = _SSConsistencyMainClient()
    policy_events: list[dict] = []

    question = generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=client,
        params=params,
        question_id="ss_547_shape",
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: _SSConsistencySubClient(),
        on_figure_policy_entry=lambda entry: policy_events.append(
            entry.model_dump(mode="json")
        ),
    )

    assert isinstance(question, ExamQuestion)
    assert len(client.repair_calls) == 1
    assert "single source of truth" in client.repair_calls[0]
    assert question.subquestions[0].chart_spec is not None
    assert question.subquestions[1].chart_spec is not None
    assert question.subquestions[0].chart_spec.data["series"][0]["values"] == [38, 31]
    assert question.subquestions[0].chart_spec.data["series"][1]["values"] == [7, 13]
    assert question.subquestions[1].chart_spec.data["series"][0]["values"] == [38, 31]
    assert question.subquestions[1].chart_spec.data["series"][1]["values"] == [7, 13]
    assert not [event for event in policy_events if event["kind"] == "data_inconsistency"]


def test_social_studies_ships_unresolved_data_warning_in_policy_trail(
    tmp_path: Path,
) -> None:
    params = sample_params(
        seed=581,
        content_type="graphs/charts/tables",
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "graphs/charts/tables"},
            {"content_type": "graphs/charts/tables"},
            {},
        ],
    )
    client = _SSUnresolvedConsistencyMainClient()
    policy_events: list[dict] = []

    generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=client,
        params=params,
        question_id="ss_547_unresolved",
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: _SSConsistencySubClient(),
        on_figure_policy_entry=lambda entry: policy_events.append(
            entry.model_dump(mode="json")
        ),
    )

    warnings = [
        event for event in policy_events if event["kind"] == "data_inconsistency"
    ]
    assert len(client.repair_calls) == 1
    assert warnings
    assert warnings[0]["series"] == "石油"
    assert warnings[0]["x"] == 1990
    assert warnings[0]["conflicting_values"] == {"題幹": 38.0, "小題 1": 10.0}
    assert "conflicting figures shipped" in warnings[0]["message"]


def test_social_studies_clean_figures_do_not_warn_or_repair(
    tmp_path: Path,
) -> None:
    params = sample_params(
        seed=581,
        content_type="graphs/charts/tables",
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "graphs/charts/tables"},
            {"content_type": "graphs/charts/tables"},
            {},
        ],
    )
    client = _SSConsistencyMainClient()
    policy_events: list[dict] = []

    generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=client,
        params=params,
        question_id="ss_clean_data",
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: _SSCleanConsistencySubClient(),
        on_figure_policy_entry=lambda entry: policy_events.append(
            entry.model_dump(mode="json")
        ),
    )

    assert client.repair_calls == []
    assert not [
        event
        for event in policy_events
        if event["kind"] in {"warning", "data_inconsistency"}
    ]


def test_natural_sciences_repairs_cross_figure_data_with_one_shared_call(
    tmp_path: Path,
) -> None:
    params = sample_ns_params(
        seed=581,
        content_type="graphs/charts/tables",
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "graphs/charts/tables"},
            {"content_type": "graphs/charts/tables"},
            {},
        ],
    )
    client = _NSConsistencyMainClient()
    policy_events: list[dict] = []

    question = generate_ns_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=client,
        params=params,
        question_id="ns_547_data_consistency",
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: _NSConsistencySubClient(),
        on_figure_policy_entry=lambda entry: policy_events.append(
            entry.model_dump(mode="json")
        ),
    )

    assert isinstance(question, NSExamQuestion)
    assert len(client.repair_calls) == 1
    assert "single source of truth" in client.repair_calls[0]
    assert question.subquestions[0].chart_spec is not None
    assert question.subquestions[0].chart_spec.data["series"][0]["values"] == [38, 31]
    assert question.subquestions[1].chart_spec is not None
    assert question.subquestions[1].chart_spec.data["series"][1]["values"] == [7, 13]
    assert not [event for event in policy_events if event["kind"] == "data_inconsistency"]


def test_natural_sciences_unresolved_data_conflict_ships_a_warning(
    tmp_path: Path,
) -> None:
    class UnresolvedMainClient(_NSConsistencyMainClient):
        def generate_json(self, _system, user, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return _SS_TEXT_SHELL
            self.repair_calls.append(user)
            return {"chart_specs": []}

    params = sample_ns_params(
        seed=581,
        content_type="graphs/charts/tables",
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "graphs/charts/tables"},
            {"content_type": "graphs/charts/tables"},
            {},
        ],
    )
    client = UnresolvedMainClient()
    policy_events: list[dict] = []

    generate_ns_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=client,
        params=params,
        question_id="ns_547_unresolved",
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: _NSConsistencySubClient(),
        on_figure_policy_entry=lambda entry: policy_events.append(
            entry.model_dump(mode="json")
        ),
    )

    assert len(client.repair_calls) == 1
    assert [event for event in policy_events if event["kind"] == "data_inconsistency"]


def test_natural_sciences_clean_figures_do_not_warn_or_repair(
    tmp_path: Path,
) -> None:
    class CleanSubClient(_NSConsistencySubClient):
        def generate_json(self, _system, _user, agent_override=None, **_kwargs):
            index = int(agent_override.split("#")[1])
            if index == 3:
                return super().generate_json(_system, _user, agent_override, **_kwargs)
            response = self._consistent_response(index)
            return response

        @staticmethod
        def _consistent_response(index: int) -> dict:
            response = _NSConsistencySubClient().generate_json(
                "", "", agent_override=f"sub#{index}"
            )
            response["chart_spec"] = _energy_chart(
                [38, 31],
                [7, 13],
                "表格" if index == 1 else "地圖",
            )
            return response

    params = sample_ns_params(
        seed=581,
        content_type="graphs/charts/tables",
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "graphs/charts/tables"},
            {"content_type": "graphs/charts/tables"},
            {},
        ],
    )
    client = _NSConsistencyMainClient()
    policy_events: list[dict] = []

    generate_ns_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=client,
        params=params,
        question_id="ns_clean_data",
        skip_verify=True,
        disable_reference_fewshot=True,
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: CleanSubClient(),
        on_figure_policy_entry=lambda entry: policy_events.append(
            entry.model_dump(mode="json")
        ),
    )

    assert client.repair_calls == []
    assert not [
        event
        for event in policy_events
        if event["kind"] in {"warning", "data_inconsistency"}
    ]


def test_data_repair_does_not_bypass_an_already_spent_slot_budget() -> None:
    entries = [
        figure_policy.FigureConsistencySpec(
            index=0,
            label="題幹",
            spec=_spec("石油", [38, 31]),
            repair_key="題幹",
            set_spec=lambda _raw: False,
        ),
        figure_policy.FigureConsistencySpec(
            index=1,
            label="小題 1",
            spec=_spec("石油", [10, 3]),
            repair_key="小題 plan 1",
            set_spec=lambda _raw: False,
        ),
    ]
    attempted = {"小題 plan 1"}
    repair_calls = 0

    def repair(*_args) -> bool:
        nonlocal repair_calls
        repair_calls += 1
        return False

    result = figure_policy.reconcile_figure_data_consistency(
        lambda: entries,
        attempted=attempted,
        repair=repair,
    )

    assert repair_calls == 0
    assert result.final_conflicts
