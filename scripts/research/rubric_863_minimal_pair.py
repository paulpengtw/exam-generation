# ruff: noqa: E501
"""
Research #863 — scorer for the 最小對照 (minimal pair) checker measurement.

Builds one checker prompt for every (item, variant) unit in the synthetic
minimal-pair set, assigns units to seven deterministic batches, imports
externally-produced checker responses, and scores the checker flag against the
independent labeller's pass/fail labels. Responses are cached by
(unit_key, prompt_sha), matching the #862 research-script convention.

CLI:
  --emit-prompts          Write prompts.jsonl and batches/batch_<n>.jsonl.
  --import-responses FILE Import external JSONL responses into the cache.
  --live                  Call the LLM for cache-missing units.
  --score                 Write matrices.md and disagreements.json.
  --cache PATH            Override the default cache path.

GitHub issue: paulpengtw/exam-generation#863
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import pathlib
import random
import sys
import time
from typing import Any

# ---------------------------------------------------------------------------
# Path setup and #862 helper imports
# ---------------------------------------------------------------------------
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

_862_path = ROOT / "scripts" / "research" / "rubric_862_examples.py"
_862_spec = importlib.util.spec_from_file_location("rubric_862_examples_for_863", _862_path)
if _862_spec is None or _862_spec.loader is None:
    raise RuntimeError(f"Cannot import #862 helpers from {_862_path}")
_862 = importlib.util.module_from_spec(_862_spec)
sys.modules["rubric_862_examples_for_863"] = _862
_862_spec.loader.exec_module(_862)

_build_examples_text = _862._build_examples_text
_build_user_prompt = _862._build_user_prompt
_prompt_sha = _862._prompt_sha
_rubric_entries_to_text = _862._rubric_entries_to_text
append_to_cache = _862.append_to_cache
cache_lookup = _862.cache_lookup
load_all_ns_entries = _862.load_all_ns_entries
load_cache = _862.load_cache
DATA_NS_CR: pathlib.Path = _862.DATA_NS_CR
DATA_NS_CMC: pathlib.Path = _862.DATA_NS_CMC
DATA_NS_SMC: pathlib.Path = _862.DATA_NS_SMC
DATA_SS_CSV: pathlib.Path = _862.DATA_SS_CSV

from src.config import Config  # noqa: E402
from src.llm_client import LLMClient  # noqa: E402

# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------
OUT_DIR = ROOT / "docs" / "research" / "863-minimal-pair"
OUT_DIR.mkdir(parents=True, exist_ok=True)
BATCHES_DIR = OUT_DIR / "batches"

DEFAULT_CACHE_PATH = OUT_DIR / "checker_responses.jsonl"
PROMPTS_PATH = OUT_DIR / "prompts.jsonl"
MATRICES_PATH = OUT_DIR / "matrices.md"
DISAGREEMENTS_PATH = OUT_DIR / "disagreements.json"
SYSTEM_PATH = OUT_DIR / "checker_system.txt"
USER_TEMPLATE_PATH = OUT_DIR / "checker_user_template.txt"
SYNTHETIC_SET_PATH = OUT_DIR / "synthetic_set.json"
LABELLED_SET_PATH = OUT_DIR / "labelled_set.json"

BATCH_COUNT = 7
EXPECTED_UNIT_COUNT = 105


# ---------------------------------------------------------------------------
# Unit construction
# ---------------------------------------------------------------------------
def _load_social_studies_questions() -> dict[str, dict[str, str]]:
    """Load SS rows using the exact row-index and column convention from #862."""
    questions: dict[str, dict[str, str]] = {}
    with open(DATA_SS_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=1):
            key = f"社會領域_row{i}|0|{i}"
            questions[key] = {
                "question_type": row.get("小題題型", "").strip(),
                "question_stem": row.get("題目", ""),
                "learning_content": row.get("學習內容", ""),
                "science_ability": row.get("認知歷程", ""),
            }
    return questions


def _question_fields(
    item_key: str,
    source: str,
    ns_by_key: dict[str, Any],
    ss_by_key: dict[str, dict[str, str]],
) -> dict[str, str]:
    if source == "ns":
        entry = ns_by_key.get(item_key)
        if entry is None:
            raise RuntimeError(f"Synthetic NS item was not found by cache_key: {item_key}")
        return {
            "question_type": entry.question_type,
            "question_stem": entry.question_stem,
            "learning_content": entry.learning_content,
            "science_ability": entry.science_ability,
        }
    if source == "ss":
        fields = ss_by_key.get(item_key)
        if fields is None:
            raise RuntimeError(f"Synthetic SS item was not found by row key: {item_key}")
        return fields
    raise RuntimeError(f"Unknown synthetic item source {source!r} for {item_key}")


def _make_unit(
    item: dict[str, Any],
    variant: dict[str, Any],
    label_entry: dict[str, Any],
    ns_by_key: dict[str, Any],
    ss_by_key: dict[str, dict[str, str]],
    system_text: str,
    user_template: str,
) -> dict[str, Any]:
    item_key = item["item"]
    variant_name = variant["variant"]
    unit_key = f"{item_key}|{variant_name}"
    fields = _question_fields(item_key, item["source"], ns_by_key, ss_by_key)

    if variant_name == "framed_omission" and "rubric_l1_omission" in item:
        l1_rubric_text = item["rubric_l1_omission"]
    else:
        l1_rubric_text = item["rubric"]["1"]
    rubric_entries = [
        {"code": "2", "規準說明": item["rubric"]["2"]},
        {"code": "1", "規準說明": l1_rubric_text},
        {"code": "0", "規準說明": item["rubric"]["0"]},
    ]
    rubric_text = _rubric_entries_to_text(rubric_entries)

    ex2_text = variant["ex2"] if "ex2" in variant else item["ex2"]
    examples = [
        {"id": f"{unit_key}|2|0", "level": "2", "text": ex2_text},
        {"id": f"{unit_key}|1|0", "level": "1", "text": variant["ex1a"]},
        {"id": f"{unit_key}|1|1", "level": "1", "text": item["ex1b"]},
        {"id": f"{unit_key}|0|0", "level": "0", "text": item["ex0"]},
    ]
    user = _build_user_prompt(
        fields["question_type"],
        fields["question_stem"],
        fields["learning_content"],
        fields["science_ability"],
        rubric_text,
        examples,
        user_template,
    )

    return {
        "unit_key": unit_key,
        "item": item_key,
        "source": item["source"],
        "stratum": item["stratum"],
        "framing_basis": item.get("framing_basis"),
        "variant": variant_name,
        "gap_kind": label_entry.get("gap_kind"),
        "variant_gap_kind": variant.get("gap_kind"),
        "question_type": fields["question_type"],
        "question_stem": fields["question_stem"],
        "learning_content": fields["learning_content"],
        "science_ability": fields["science_ability"],
        "rubric_text": rubric_text,
        "l1_rubric_text": l1_rubric_text,
        "examples": examples,
        "system": system_text,
        "user": user,
        "prompt_sha": _prompt_sha(system_text, user),
        "label": label_entry["label"],
        "borderline": bool(label_entry.get("borderline", False)),
        "labeller_reason": label_entry.get("reason", ""),
        "variant_index": 0,
        "batch": None,
    }


def load_units() -> list[dict[str, Any]]:
    """Load, validate, and prompt all 105 synthetic minimal-pair units."""
    synthetic = json.loads(SYNTHETIC_SET_PATH.read_text(encoding="utf-8"))
    labelled = json.loads(LABELLED_SET_PATH.read_text(encoding="utf-8"))
    labelled_entries = labelled["entries"]
    label_by_id = {entry["id"]: entry for entry in labelled_entries}

    expected_keys = {
        f"{item['item']}|{variant['variant']}"
        for item in synthetic["items"]
        for variant in item["variants"]
    }
    label_ids = set(label_by_id)
    if expected_keys != label_ids:
        only_generated = sorted(expected_keys - label_ids)
        only_labelled = sorted(label_ids - expected_keys)
        raise SystemExit(
            "ASSERTION FAILED: synthetic unit keys != labelled_set ids; "
            f"only generated={only_generated[:10]}, only labelled={only_labelled[:10]}"
        )
    if len(labelled_entries) != len(label_ids):
        raise SystemExit("ASSERTION FAILED: labelled_set.json contains duplicate ids")
    if len(expected_keys) != EXPECTED_UNIT_COUNT:
        raise SystemExit(
            f"ASSERTION FAILED: expected {EXPECTED_UNIT_COUNT} units, found {len(expected_keys)}"
        )

    system_text = SYSTEM_PATH.read_text(encoding="utf-8").rstrip("\n")
    user_template = USER_TEMPLATE_PATH.read_text(encoding="utf-8")
    ns_entries = load_all_ns_entries(DATA_NS_CR, DATA_NS_CMC, DATA_NS_SMC)
    ns_by_key = {entry.cache_key: entry for entry in ns_entries}
    ss_by_key = _load_social_studies_questions()

    units: list[dict[str, Any]] = []
    for item in sorted(synthetic["items"], key=lambda value: value["item"]):
        for variant_index, variant in enumerate(item["variants"]):
            unit_key = f"{item['item']}|{variant['variant']}"
            unit = _make_unit(
                item,
                variant,
                label_by_id[unit_key],
                ns_by_key,
                ss_by_key,
                system_text,
                user_template,
            )
            unit["variant_index"] = variant_index
            units.append(unit)
    return units


# ---------------------------------------------------------------------------
# Deterministic batches and prompt emission
# ---------------------------------------------------------------------------
def assign_batches(units: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """Assign variant j of sorted item i to (i + j) % 7 and shuffle each batch."""
    item_keys = sorted({unit["item"] for unit in units})
    item_index = {item_key: index for index, item_key in enumerate(item_keys)}
    batches = {index: [] for index in range(BATCH_COUNT)}
    for unit in units:
        batch = (item_index[unit["item"]] + unit["variant_index"]) % BATCH_COUNT
        unit["batch"] = batch
        batches[batch].append(unit)

    rng = random.Random(863)
    for batch in batches.values():
        rng.shuffle(batch)
        if len({unit["item"] for unit in batch}) != len(batch):
            raise AssertionError("A batch contains two variants of the same item")
    return batches


def _prompt_row(unit: dict[str, Any]) -> dict[str, Any]:
    return {
        "unit_key": unit["unit_key"],
        "batch": unit["batch"],
        "prompt_sha": unit["prompt_sha"],
        "system": unit["system"],
        "user": unit["user"],
    }


def _write_jsonl(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def cmd_emit_prompts(units: list[dict[str, Any]]) -> None:
    batches = assign_batches(units)
    rows: list[dict[str, Any]] = []
    for batch_index in range(BATCH_COUNT):
        batch_rows = [_prompt_row(unit) for unit in batches[batch_index]]
        rows.extend(batch_rows)
        _write_jsonl(BATCHES_DIR / f"batch_{batch_index}.jsonl", batch_rows)
    _write_jsonl(PROMPTS_PATH, rows)

    print(f"{len(units)} units, {BATCH_COUNT} batches → {PROMPTS_PATH}")
    for batch_index in range(BATCH_COUNT):
        print(f"  batch {batch_index}: {len(batches[batch_index])} units")
    print("Assertion passed: no item repeats within any batch.")


# ---------------------------------------------------------------------------
# Cache and response import
# ---------------------------------------------------------------------------
def parse_response_text(value: object) -> dict[str, Any]:
    """Parse an object or a fenced/raw string containing its outermost JSON object."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise ValueError("response must be a JSON object or string")

    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("response string does not contain a JSON object")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON object: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("response JSON is not an object")
    return parsed


def cmd_import_responses(
    import_file: str,
    units: list[dict[str, Any]],
    cache_path: pathlib.Path,
) -> None:
    unit_by_key = {unit["unit_key"]: unit for unit in units}
    existing_cache = load_cache(cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    added = skipped = failed = 0

    with open(import_file, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"[WARN] line {lineno}: JSON decode error: {exc}", file=sys.stderr)
                failed += 1
                continue
            if not isinstance(record, dict):
                print(f"[WARN] line {lineno}: top-level JSON is not an object", file=sys.stderr)
                failed += 1
                continue

            unit_key = record.get("unit_key")
            unit = unit_by_key.get(unit_key)
            if unit is None:
                print(f"[WARN] line {lineno}: unknown unit_key {unit_key!r}", file=sys.stderr)
                failed += 1
                continue
            prompt_sha = unit["prompt_sha"]
            if (unit_key, prompt_sha) in existing_cache:
                print(
                    f"[SKIP] {unit_key} (sha={prompt_sha}) already in cache",
                    file=sys.stderr,
                )
                skipped += 1
                continue

            try:
                response = parse_response_text(record.get("response"))
            except ValueError as exc:
                print(f"[WARN] line {lineno}: {exc}", file=sys.stderr)
                failed += 1
                continue
            if not isinstance(response.get("minimal_pair_violation"), bool):
                print(
                    f"[WARN] line {lineno}: minimal_pair_violation must be a bool",
                    file=sys.stderr,
                )
                failed += 1
                continue

            cache_record = dict(response)
            cache_record["_key"] = unit_key
            cache_record["_prompt_sha"] = prompt_sha
            append_to_cache(cache_path, cache_record)
            existing_cache[(unit_key, prompt_sha)] = cache_record
            added += 1

    print(f"Import complete: added={added}, skipped={skipped}, failed={failed}")


# ---------------------------------------------------------------------------
# Live mode
# ---------------------------------------------------------------------------
def cmd_live(units: list[dict[str, Any]], cache_path: pathlib.Path) -> None:
    cache = load_cache(cache_path)
    missing = [
        unit
        for unit in units
        if cache_lookup(cache, unit["unit_key"], unit["prompt_sha"]) is None
    ]
    if not missing:
        print("All units already cached.")
        return

    print(f"Calling LLM for {len(missing)} cache-missing units…")
    client = LLMClient(Config.from_env())
    for index, unit in enumerate(missing, 1):
        print(f"  [{index}/{len(missing)}] {unit['unit_key']}")
        try:
            result = client.generate_json(
                system=unit["system"],
                user=unit["user"],
                purpose="verify",
            )
            if not isinstance(result, dict) or not isinstance(
                result.get("minimal_pair_violation"), bool
            ):
                print(
                    f"  [ERROR] {unit['unit_key']}: "
                    "minimal_pair_violation must be a bool; response not cached",
                    file=sys.stderr,
                )
                continue
            record = dict(result)
            record["_key"] = unit["unit_key"]
            record["_prompt_sha"] = unit["prompt_sha"]
            append_to_cache(cache_path, record)
            cache[unit["unit_key"], unit["prompt_sha"]] = record
            time.sleep(0.5)
        except Exception as exc:  # noqa: BLE001
            print(f"  [ERROR] {unit['unit_key']}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def _pct(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "n/a"
    return f"{numerator / denominator:.0%}"


def _confusion(rows: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, int]:
    counts = {key: 0 for key in ("TP", "FP", "FN", "TN")}
    for unit, response in rows:
        actual_positive = unit["label"] == "fail"
        checker_positive = response["minimal_pair_violation"] is True
        if actual_positive and checker_positive:
            counts["TP"] += 1
        elif not actual_positive and checker_positive:
            counts["FP"] += 1
        elif actual_positive and not checker_positive:
            counts["FN"] += 1
        else:
            counts["TN"] += 1
    return counts


def _confusion_row(scope: str, rows: list[tuple[dict[str, Any], dict[str, Any]]]) -> str:
    counts = _confusion(rows)
    return (
        f"| {_md_cell(scope)} | {len(rows)} | {counts['TP']} | {counts['FP']} | "
        f"{counts['FN']} | {counts['TN']} | {_pct(counts['TP'], counts['TP'] + counts['FN'])} | "
        f"{_pct(counts['FP'], counts['FP'] + counts['TN'])} |"
    )


def _md_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def recommendation_for(
    available: list[tuple[dict[str, Any], dict[str, Any]]],
    missing_count: int,
    total_count: int,
) -> tuple[str, str]:
    """Return a conservative issue recommendation and corrector-facing details."""
    if missing_count or len(available) < total_count:
        return (
            "prompt only",
            "[學生作答實例檢核] 尚有 "
            f"{missing_count} 個單位沒有 checker 結果；完成整組量測前，請只把最小對照判斷留在提示中。",
        )

    counts = _confusion(available)
    if counts["TP"] == 0:
        return (
            "prompt only",
            "[學生作答實例檢核] 尚未捕捉到任何標記為 fail 的最小對照違反；請只把判斷留在提示中。",
        )
    if counts["FP"] == 0:
        return (
            "fail",
            "[學生作答實例檢核] 第一個 [1] 實例應與 [2] 保留相同主張和要點，"
            "只保留理由未接上推理鏈的差異；能框定時可只缺少一個具名成分。",
        )
    return (
        "note only",
        "[學生作答實例檢核] 檢核員發現最小對照違反時，請依上述差異提示修正第一個 [1] 實例，"
        "但不要把此旗標作為阻擋條件。",
    )


def _write_score_outputs(
    available: list[tuple[dict[str, Any], dict[str, Any]]],
    missing: list[str],
) -> str:
    lines = [
        "# 最小對照 checker matrices — #863",
        "",
        f"Cached units scored: {len(available)} / {len(available) + len(missing)}",
        "",
        "## Missing responses",
        "",
        f"Count: {len(missing)}",
    ]
    if missing:
        lines.extend(["", *[f"- `{_md_cell(key)}`" for key in sorted(missing)]])
    else:
        lines.append(" (none)")

    all_rows = available
    nonborderline_rows = [row for row in available if not row[0]["borderline"]]
    recommendation, recommendation_details = recommendation_for(
        available,
        missing_count=len(missing),
        total_count=len(available) + len(missing),
    )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"Recommendation: **{recommendation}**",
            f"Details: {recommendation_details}",
            "",
            "## Overall",
            "",
            "| Scope | n | TP | FP | FN | TN | recall | false-flag rate |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
            _confusion_row("all units", all_rows),
            _confusion_row("excluding borderline", nonborderline_rows),
            "",
            "## By near-miss type (variant)",
            "",
            "| variant | n | labelled pass | labelled fail | checker flagged | correct | metric | rate |",
            "|---|---:|---:|---:|---:|---:|---|---:|",
        ]
    )

    variant_order: list[str] = []
    for unit, _ in all_rows:
        if unit["variant"] not in variant_order:
            variant_order.append(unit["variant"])
    for variant in variant_order:
        rows = [(unit, response) for unit, response in all_rows if unit["variant"] == variant]
        pass_count = sum(unit["label"] == "pass" for unit, _ in rows)
        fail_count = sum(unit["label"] == "fail" for unit, _ in rows)
        flagged = sum(response["minimal_pair_violation"] is True for _, response in rows)
        correct = sum(
            (unit["label"] == "fail") == (response["minimal_pair_violation"] is True)
            for unit, response in rows
        )
        if fail_count and not pass_count:
            metric = "recall"
            rate = _pct(
                sum(
                    response["minimal_pair_violation"] is True
                    for unit, response in rows
                    if unit["label"] == "fail"
                ),
                fail_count,
            )
        elif pass_count and not fail_count:
            metric = "false-flag rate"
            rate = _pct(flagged, pass_count)
        else:
            metric = "accuracy"
            rate = _pct(correct, len(rows))
        lines.append(
            f"| {_md_cell(variant)} | {len(rows)} | {pass_count} | {fail_count} | {flagged} | "
            f"{correct} | {metric} | {rate} |"
        )

    lines.extend(
        [
            "",
            "## By stratum",
            "",
            "| stratum | n | TP | FP | FN | TN | recall | false-flag rate |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for stratum in ("open", "framed_stem", "framed_figure"):
        rows = [(unit, response) for unit, response in all_rows if unit["stratum"] == stratum]
        lines.append(_confusion_row(stratum, rows))

    lines.extend(
        [
            "",
            "## true_pair false flags by gap_kind",
            "",
            "| gap_kind | n | false flags | false-flag rate |",
            "|---|---:|---:|---:|",
        ]
    )
    gap_kinds = sorted(
        {
            unit["gap_kind"]
            for unit, _ in all_rows
            if unit["variant"] == "true_pair" and unit["gap_kind"] is not None
        }
    )
    for gap_kind in gap_kinds:
        rows = [
            (unit, response)
            for unit, response in all_rows
            if unit["variant"] == "true_pair" and unit["gap_kind"] == gap_kind
        ]
        false_flags = sum(response["minimal_pair_violation"] is True for _, response in rows)
        lines.append(
            f"| {_md_cell(gap_kind)} | {len(rows)} | {false_flags} | "
            f"{_pct(false_flags, len(rows))} |"
        )

    lines.extend(
        [
            "",
            "## Framing agreement",
            "",
            "| stratum | n | checker set_framed=true | set_framed=false | missing/non-bool | true rate |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for stratum in ("framed_stem", "framed_figure"):
        rows = [(unit, response) for unit, response in all_rows if unit["stratum"] == stratum]
        true_count = sum(response.get("set_framed") is True for _, response in rows)
        false_count = sum(response.get("set_framed") is False for _, response in rows)
        missing_count = len(rows) - true_count - false_count
        lines.append(
            f"| {_md_cell(stratum)} | {len(rows)} | {true_count} | {false_count} | "
            f"{missing_count} | {_pct(true_count, len(rows))} |"
        )

    MATRICES_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "\n".join(lines) + "\n"


def _write_disagreements(
    available: list[tuple[dict[str, Any], dict[str, Any]]],
) -> None:
    disagreements: list[dict[str, Any]] = []
    for unit, response in available:
        checker_flag = response["minimal_pair_violation"] is True
        label_positive = unit["label"] == "fail"
        if checker_flag == label_positive:
            continue
        disagreements.append(
            {
                "unit_key": unit["unit_key"],
                "item": unit["item"],
                "stratum": unit["stratum"],
                "variant": unit["variant"],
                "gap_kind": unit["gap_kind"],
                "label": unit["label"],
                "borderline": unit["borderline"],
                "labeller_reason": unit["labeller_reason"],
                "checker_flag": checker_flag,
                "minimal_pair_reason": response.get("minimal_pair_reason", ""),
                "set_framed": response.get("set_framed"),
                "framing_evidence": response.get("framing_evidence", ""),
                "ex2_text": unit["examples"][0]["text"],
                "ex1a_text": unit["examples"][1]["text"],
                "l1_rubric_text": unit["l1_rubric_text"],
            }
        )
    disagreements.sort(key=lambda entry: entry["unit_key"])
    DISAGREEMENTS_PATH.write_text(
        json.dumps(disagreements, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def cmd_score(units: list[dict[str, Any]], cache_path: pathlib.Path) -> None:
    cache = load_cache(cache_path)
    available: list[tuple[dict[str, Any], dict[str, Any]]] = []
    missing: list[str] = []
    for unit in units:
        response = cache_lookup(cache, unit["unit_key"], unit["prompt_sha"])
        if response is None:
            missing.append(unit["unit_key"])
        elif not isinstance(response.get("minimal_pair_violation"), bool):
            missing.append(unit["unit_key"])
        else:
            available.append((unit, response))

    matrices_text = _write_score_outputs(available, missing)
    _write_disagreements(available)
    print(matrices_text)
    print(f"Disagreements written to {DISAGREEMENTS_PATH}")
    print(f"Matrices written to {MATRICES_PATH}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rubric #863 — 最小對照 checker prompts, import, and scorer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--emit-prompts",
        action="store_true",
        help="Write prompts.jsonl and batches/batch_<n>.jsonl.",
    )
    parser.add_argument(
        "--import-responses",
        metavar="FILE",
        help="Import JSONL responses into the cache.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call the LLM for cache-missing units (never call otherwise).",
    )
    parser.add_argument(
        "--score",
        action="store_true",
        help="Score cached responses against labelled_set.json.",
    )
    parser.add_argument(
        "--cache",
        metavar="PATH",
        default=str(DEFAULT_CACHE_PATH),
        help=f"Cache file path (default: {DEFAULT_CACHE_PATH}).",
    )
    args = parser.parse_args()
    cache_path = pathlib.Path(args.cache)
    units = load_units()

    if args.emit_prompts:
        cmd_emit_prompts(units)
    if args.import_responses:
        cmd_import_responses(args.import_responses, units, cache_path)
    if args.live:
        cmd_live(units, cache_path)
    if args.score:
        cmd_score(units, cache_path)
    if not any((args.emit_prompts, args.import_responses, args.live, args.score)):
        parser.print_help()


if __name__ == "__main__":
    main()
