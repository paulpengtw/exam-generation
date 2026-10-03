from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "research" / "rubric_863_minimal_pair.py"
SPEC = importlib.util.spec_from_file_location("rubric_863_minimal_pair", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
rubric_863 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rubric_863)


def test_framed_omission_prompt_uses_omission_rubric_and_fixed_example_order() -> None:
    units = rubric_863.load_units()
    unit = next(
        u for u in units if u["unit_key"] == "sea-ice-land-ice|0|3|framed_omission"
    )

    assert (
        "[1] 理由有缺口：（甲）只寫出陸地或海洋其中一項的器材與理由；"
        "（乙）陸地器材的理由談的是冰塊會不會滑落，與水位變化無關。"
    ) in unit["user"]
    e1 = "[E1]（[2]） (1) 用石塊模擬陸地"
    e2 = "[E2]（[1]） (1) 用石塊模擬陸地"
    e3 = "[E3]（[1]） (1) 用石塊模擬陸地"
    e4 = "[E4]（[0]） (1) 用保麗龍模擬陸地"
    assert unit["user"].index(e1) < unit["user"].index(e2)
    assert unit["user"].index(e2) < unit["user"].index(e3)
    assert unit["user"].index(e3) < unit["user"].index(e4)


def test_assign_batches_is_deterministic_and_keeps_items_unique() -> None:
    units = rubric_863.load_units()
    batches = rubric_863.assign_batches(units)

    assert sorted(batches) == list(range(7))
    assert [len(batches[i]) for i in range(7)] == [13, 15, 15, 16, 17, 14, 15]
    assert all(len({unit["item"] for unit in batch}) == len(batch) for batch in batches.values())

    first_item = [u for u in units if u["item"] == "black-white-car-heat|0|2"]
    assert {u["unit_key"]: u["batch"] for u in first_item} == {
        "black-white-car-heat|0|2|true_pair": 0,
        "black-white-car-heat|0|2|fewer_points": 1,
        "black-white-car-heat|0|2|different_claim": 2,
        "black-white-car-heat|0|2|no_reason": 3,
        "black-white-car-heat|0|2|closes_chain": 4,
    }


def test_fenced_response_parser_returns_the_outermost_json_object() -> None:
    response = rubric_863.parse_response_text(
        '```json\n{"minimal_pair_violation": true, "minimal_pair_reason": "gap"}\n```'
    )

    assert response == {"minimal_pair_violation": True, "minimal_pair_reason": "gap"}


def test_live_does_not_cache_a_response_without_a_boolean_checker_flag(
    monkeypatch, tmp_path
) -> None:
    units = rubric_863.load_units()[:1]

    class FakeConfig:
        @staticmethod
        def from_env():
            return object()

    class FakeClient:
        def __init__(self, config):
            pass

        def generate_json(self, **kwargs):
            return {"minimal_pair_violation": "true"}

    monkeypatch.setattr(rubric_863, "Config", FakeConfig)
    monkeypatch.setattr(rubric_863, "LLMClient", FakeClient)
    monkeypatch.setattr(rubric_863.time, "sleep", lambda _: None)
    cache_path = tmp_path / "cache.jsonl"

    rubric_863.cmd_live(units, cache_path)

    assert not cache_path.exists()


def test_partial_score_recommends_prompt_only() -> None:
    units = rubric_863.load_units()
    response = {"minimal_pair_violation": False}

    recommendation, details = rubric_863.recommendation_for(
        [(units[0], response)], missing_count=104, total_count=105
    )

    assert recommendation == "prompt only"
    assert "104" in details
