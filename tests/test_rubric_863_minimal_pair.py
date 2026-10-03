from __future__ import annotations

import importlib.util
import json
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


def test_emit_prompts_writes_blinded_batches_and_id_map(monkeypatch, tmp_path) -> None:
    batches_dir = tmp_path / "batches"
    prompts_path = tmp_path / "prompts.jsonl"
    id_map_path = tmp_path / "batch_id_map.json"
    monkeypatch.setattr(rubric_863, "BATCHES_DIR", batches_dir, raising=False)
    monkeypatch.setattr(rubric_863, "PROMPTS_PATH", prompts_path)
    monkeypatch.setattr(rubric_863, "BATCH_ID_MAP_PATH", id_map_path, raising=False)

    rubric_863.cmd_emit_prompts(rubric_863.load_units())

    variant_names = {
        "true_pair",
        "fewer_points",
        "different_claim",
        "no_reason",
        "closes_chain",
        "framed_omission",
        "omission_plus_gap",
        "omits_two",
    }
    id_map = json.loads(id_map_path.read_text(encoding="utf-8"))
    assert len(id_map) == 105
    for batch_index in range(rubric_863.BATCH_COUNT):
        lines = (batches_dir / f"batch_{batch_index}.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        for index, line in enumerate(lines):
            row = json.loads(line)
            assert list(row) == ["id", "system", "user"]
            assert row["id"] == f"q{batch_index}{index:02d}"
            assert id_map[row["id"]].endswith(
                tuple(variant_names)
            )
            assert not any(name in line for name in variant_names)

    prompt_row = json.loads(prompts_path.read_text(encoding="utf-8").splitlines()[0])
    assert set(prompt_row) == {"unit_key", "batch", "prompt_sha", "system", "user"}


def test_import_responses_accepts_id_and_unit_key_records(monkeypatch, tmp_path) -> None:
    units = rubric_863.load_units()[:2]
    id_map_path = tmp_path / "batch_id_map.json"
    id_map_path.write_text(
        json.dumps({"q000": units[0]["unit_key"]}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    monkeypatch.setattr(rubric_863, "BATCH_ID_MAP_PATH", id_map_path, raising=False)

    import_path = tmp_path / "responses.jsonl"
    import_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "q000",
                        "response": {"minimal_pair_violation": True},
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "unit_key": units[1]["unit_key"],
                        "response": {"minimal_pair_violation": False},
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cache_path = tmp_path / "cache.jsonl"

    rubric_863.cmd_import_responses(str(import_path), units, cache_path)

    cache = rubric_863.load_cache(cache_path)
    assert rubric_863.cache_lookup(cache, units[0]["unit_key"], units[0]["prompt_sha"])[
        "minimal_pair_violation"
    ] is True
    assert rubric_863.cache_lookup(cache, units[1]["unit_key"], units[1]["prompt_sha"])[
        "minimal_pair_violation"
    ] is False


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


def test_score_includes_open_framing_agreement_row(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(rubric_863, "MATRICES_PATH", tmp_path / "matrices.md")
    units = rubric_863.load_units()
    open_units = [unit for unit in units if unit["stratum"] == "open"]
    rows = [(unit, {"minimal_pair_violation": False, "set_framed": False}) for unit in open_units]

    matrices = rubric_863._write_score_outputs(rows, [])

    assert f"| open | {len(open_units)} | 0 | {len(open_units)} | 0 | 0% |" in matrices
