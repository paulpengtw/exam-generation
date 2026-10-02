# ruff: noqa: E501
"""
Research #862 — checker prompts, labels and scorer for the 學生作答實例 rules.

Builds LLM-checker call prompts for every rubric-bearing open-response 小題 whose
rubric contains at least one non-empty 學生作答實例 string (real units), plus six
trap units assembled from trap_set.json.  Caches responses keyed by (unit_key,
prompt_sha).  Imports externally-produced responses and scores per-rule confusion
matrices against the independent labeller's reference labels.

Three rules are scored:
  r1 — 擬答 (student voice)      label positive: narration  checker flag: not_student_voice
  r2 — answers this 小題          label positive: generic    checker flag: not_this_item
  r3 — plausible [0]             label positive: filler     checker flag: implausible_zero
                                 (only level-0 examples; n/a examples are excluded)

CLI:
  --emit-prompts          Write prompts.jsonl and print unit/example counts.
  --import-responses FILE Import external JSONL responses into the cache.
  --live                  Call the LLM for cache-missing units.
  --score                 Score all units against the labelled set.
  --cache PATH            Override the default cache path (for testing).

GitHub issue: paulpengtw/exam-generation#862
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import pathlib
import sys
import time
from typing import Any

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Import loaders from rubric_counting_prototype via importlib
# ---------------------------------------------------------------------------
_proto_path = ROOT / "scripts" / "research" / "rubric_counting_prototype.py"
_proto_spec = importlib.util.spec_from_file_location("rubric_counting_prototype", _proto_path)
_proto = importlib.util.module_from_spec(_proto_spec)  # type: ignore[arg-type]
sys.modules["rubric_counting_prototype"] = _proto
_proto_spec.loader.exec_module(_proto)  # type: ignore[union-attr]

load_all_ns_entries = _proto.load_all_ns_entries
_rubric_entries_to_text = _proto._rubric_entries_to_text
DATA_NS_CR: pathlib.Path = _proto.DATA_NS_CR
DATA_NS_CMC: pathlib.Path = _proto.DATA_NS_CMC
DATA_NS_SMC: pathlib.Path = _proto.DATA_NS_SMC
DATA_SS_CSV: pathlib.Path = _proto.DATA_SS_CSV

from src.config import Config  # noqa: E402
from src.llm_client import LLMClient  # noqa: E402

# ---------------------------------------------------------------------------
# Directories and paths
# ---------------------------------------------------------------------------
OUT_DIR = ROOT / "docs" / "research" / "862-student-examples"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CACHE_PATH = OUT_DIR / "checker_responses.jsonl"
PROMPTS_PATH = OUT_DIR / "prompts.jsonl"
MATRICES_PATH = OUT_DIR / "matrices.md"
DISAGREEMENTS_PATH = OUT_DIR / "disagreements.json"

SYSTEM_PATH = OUT_DIR / "checker_system.txt"
USER_TEMPLATE_PATH = OUT_DIR / "checker_user_template.txt"
LABELLED_SET_PATH = OUT_DIR / "labelled_set.json"
TRAP_SET_PATH = OUT_DIR / "trap_set.json"


# ---------------------------------------------------------------------------
# Unit and example construction
# ---------------------------------------------------------------------------


def _build_examples_text(examples: list[dict[str, Any]]) -> str:
    """Format the examples block for the user prompt (examples NOT truncated)."""
    lines = []
    for i, ex in enumerate(examples, 1):
        lines.append(f"[E{i}]（[{ex['level']}]） {ex['text']}")
    return "\n".join(lines)


def _build_user_prompt(
    question_type: str,
    question_stem: str,
    learning_content: str,
    science_ability: str,
    rubric_text: str,
    examples: list[dict[str, Any]],
    user_template: str,
) -> str:
    examples_text = _build_examples_text(examples)
    return user_template.format(
        question_type=question_type,
        question_stem=question_stem[:600],
        learning_content=learning_content[:200],
        science_ability=science_ability[:200],
        rubric_text=rubric_text[:600],
        examples_text=examples_text,
    )


def _prompt_sha(system: str, user: str) -> str:
    content = (system + "\n\n" + user).encode("utf-8")
    return hashlib.sha256(content).hexdigest()[:12]


def _make_unit(
    unit_key: str,
    question_type: str,
    question_stem: str,
    learning_content: str,
    science_ability: str,
    rubric_text: str,
    examples: list[dict[str, Any]],
    system_text: str,
    user_template: str,
) -> dict[str, Any]:
    """Build a unit dict with prompt fields filled in."""
    user = _build_user_prompt(
        question_type,
        question_stem,
        learning_content,
        science_ability,
        rubric_text,
        examples,
        user_template,
    )
    sha = _prompt_sha(system_text, user)
    # Build E-number map: {"E1": ex_id, "E2": ex_id, ...}
    e_map = {f"E{i}": ex["id"] for i, ex in enumerate(examples, 1)}
    return {
        "unit_key": unit_key,
        "question_type": question_type,
        "question_stem": question_stem,
        "learning_content": learning_content,
        "science_ability": science_ability,
        "rubric_text": rubric_text,
        "examples": examples,
        "user": user,
        "prompt_sha": sha,
        "e_map": e_map,  # {"E1": example_id, ...}
    }


# ---------------------------------------------------------------------------
# Load all units (real NS, real SS, trap)
# ---------------------------------------------------------------------------


def load_units() -> list[dict[str, Any]]:
    """Load and return all units (19 real + 6 trap = 25 total)."""
    system_text = SYSTEM_PATH.read_text(encoding="utf-8").rstrip("\n")
    user_template = USER_TEMPLATE_PATH.read_text(encoding="utf-8")

    units: list[dict[str, Any]] = []

    # --- NS real units ---
    ns_entries = load_all_ns_entries(DATA_NS_CR, DATA_NS_CMC, DATA_NS_SMC)
    ns_lookup: dict[str, Any] = {e.cache_key: e for e in ns_entries}

    for e in ns_entries:
        if not ("Constructed" in e.question_type or "開放式" in e.question_type):
            continue
        examples: list[dict[str, Any]] = []
        for rubric_entry in e.rubric_raw:
            code = rubric_entry.get("code") or rubric_entry.get("編碼", "?")
            for idx, text in enumerate(rubric_entry.get("學生作答實例", [])):
                if not text.strip():
                    continue
                examples.append(
                    {
                        "id": f"{e.cache_key}|{code}|{idx}",
                        "level": str(code),
                        "text": text,
                    }
                )
        if not examples:
            continue
        units.append(
            _make_unit(
                e.cache_key,
                e.question_type,
                e.question_stem,
                e.learning_content,
                e.science_ability,
                e.rubric_text,
                examples,
                system_text,
                user_template,
            )
        )

    # --- SS real units (re-read CSV using 小題題型 column) ---
    with open(DATA_SS_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=1):
            small_q_type = row.get("小題題型", "").strip()
            if small_q_type != "開放式建構反應題":
                continue
            rubric_raw_str = row.get("評分規準", "").strip()
            if not rubric_raw_str:
                continue
            try:
                rubric_raw: list[dict] = json.loads(rubric_raw_str)
                if not isinstance(rubric_raw, list):
                    rubric_raw = [{"code": "?", "規準說明": rubric_raw_str}]
            except json.JSONDecodeError:
                rubric_raw = [{"code": "?", "規準說明": rubric_raw_str}]

            unit_key = f"社會領域_row{i}|0|{i}"
            rubric_text = _rubric_entries_to_text(rubric_raw)

            examples = []
            for rubric_entry in rubric_raw:
                code = rubric_entry.get("code") or rubric_entry.get("編碼", "?")
                for idx, text in enumerate(rubric_entry.get("學生作答實例", [])):
                    if not text.strip():
                        continue
                    examples.append(
                        {
                            "id": f"{unit_key}|{code}|{idx}",
                            "level": str(code),
                            "text": text,
                        }
                    )
            if not examples:
                continue

            units.append(
                _make_unit(
                    unit_key,
                    small_q_type,
                    row.get("題目", ""),
                    row.get("學習內容", ""),
                    row.get("認知歷程", ""),
                    rubric_text,
                    examples,
                    system_text,
                    user_template,
                )
            )

    # --- Validate real example ids vs labelled_set.json ---
    labelled_data = json.loads(LABELLED_SET_PATH.read_text(encoding="utf-8"))
    labelled_non_trap_ids = {e["id"] for e in labelled_data["entries"] if e["set"] in {"ns", "ss"}}
    generated_ids: set[str] = set()
    for u in units:
        for ex in u["examples"]:
            generated_ids.add(ex["id"])

    if generated_ids != labelled_non_trap_ids:
        only_generated = sorted(generated_ids - labelled_non_trap_ids)
        only_labelled = sorted(labelled_non_trap_ids - generated_ids)
        print(
            "ASSERTION FAILED: generated example ids != non-trap ids in labelled_set.json",
            file=sys.stderr,
        )
        if only_generated:
            print(
                f"  Only in generated ({len(only_generated)}): {only_generated[:10]}",
                file=sys.stderr,
            )
        if only_labelled:
            print(
                f"  Only in labelled ({len(only_labelled)}): {only_labelled[:10]}", file=sys.stderr
            )
        sys.exit(1)

    # --- Trap units ---
    trap_data = json.loads(TRAP_SET_PATH.read_text(encoding="utf-8"))
    traps_by_key: dict[str, list[dict]] = {}
    for trap in trap_data["traps"]:
        traps_by_key.setdefault(trap["key"], []).append(trap)

    for key in sorted(traps_by_key.keys()):
        traps = traps_by_key[key]
        real_entry = ns_lookup.get(key)
        if real_entry is None:
            print(f"[WARN] trap key {key!r} not found in NS entries", file=sys.stderr)
            continue
        unit_key = f"trap:{key}"
        examples = [
            {"id": trap["id"], "level": trap["level"], "text": trap["text"]} for trap in traps
        ]
        units.append(
            _make_unit(
                unit_key,
                real_entry.question_type,
                real_entry.question_stem,
                real_entry.learning_content,
                real_entry.science_ability,
                real_entry.rubric_text,
                examples,
                system_text,
                user_template,
            )
        )

    return units


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def load_cache(cache_path: pathlib.Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Load JSONL cache.  Key: (unit_key, prompt_sha)."""
    cache: dict[tuple[str, str], dict[str, Any]] = {}
    if not cache_path.exists():
        return cache
    for line in cache_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            k = (rec["_key"], rec.get("_prompt_sha", ""))
            cache[k] = rec
        except (json.JSONDecodeError, KeyError):
            pass
    return cache


def append_to_cache(cache_path: pathlib.Path, record: dict[str, Any]) -> None:
    """Append one record to the JSONL cache."""
    with open(cache_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def cache_lookup(
    cache: dict[tuple[str, str], dict[str, Any]],
    unit_key: str,
    prompt_sha: str,
) -> dict[str, Any] | None:
    return cache.get((unit_key, prompt_sha))


# ---------------------------------------------------------------------------
# --emit-prompts
# ---------------------------------------------------------------------------


def cmd_emit_prompts(units: list[dict[str, Any]]) -> None:
    rows = []
    total_examples = 0
    for u in units:
        rows.append(
            {
                "unit_key": u["unit_key"],
                "prompt_sha": u["prompt_sha"],
                "user": u["user"],
                "examples": u["e_map"],
            }
        )
        total_examples += len(u["examples"])

    PROMPTS_PATH.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    print(f"{len(units)} units, {total_examples} examples → {PROMPTS_PATH}")


# ---------------------------------------------------------------------------
# --import-responses
# ---------------------------------------------------------------------------


def cmd_import_responses(
    import_file: str,
    units: list[dict[str, Any]],
    cache_path: pathlib.Path,
) -> None:
    unit_by_key = {u["unit_key"]: u for u in units}
    existing_cache = load_cache(cache_path)
    added = skipped = failed = 0

    with open(import_file, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"[WARN] line {lineno}: JSON decode error: {exc}", file=sys.stderr)
                failed += 1
                continue

            unit_key = rec.get("_key", "")
            unit = unit_by_key.get(unit_key)
            if unit is None:
                print(f"[WARN] line {lineno}: unknown unit_key {unit_key!r}", file=sys.stderr)
                failed += 1
                continue

            prompt_sha = unit["prompt_sha"]

            # Check for duplicate
            if (unit_key, prompt_sha) in existing_cache:
                print(f"[SKIP] {unit_key} (sha={prompt_sha}) already in cache", file=sys.stderr)
                skipped += 1
                continue

            # Validate example_flags
            expected_e_nums = set(unit["e_map"].keys())
            example_flags = rec.get("example_flags", [])
            actual_e_nums = {ef.get("id", "") for ef in example_flags}
            if actual_e_nums != expected_e_nums:
                only_expected = sorted(expected_e_nums - actual_e_nums)
                only_actual = sorted(actual_e_nums - expected_e_nums)
                print(
                    f"[FAIL] {unit_key}: example_flags mismatch. "
                    f"Missing: {only_expected}, Extra: {only_actual}",
                    file=sys.stderr,
                )
                failed += 1
                continue

            # Attach prompt_sha and append
            rec["_prompt_sha"] = prompt_sha
            append_to_cache(cache_path, rec)
            existing_cache[(unit_key, prompt_sha)] = rec
            added += 1

    print(f"Import complete: added={added}, skipped={skipped}, failed={failed}")


# ---------------------------------------------------------------------------
# --live
# ---------------------------------------------------------------------------


def cmd_live(
    units: list[dict[str, Any]],
    cache_path: pathlib.Path,
) -> None:
    cache = load_cache(cache_path)
    missing = [u for u in units if cache_lookup(cache, u["unit_key"], u["prompt_sha"]) is None]

    if not missing:
        print("All units already cached.")
        return

    print(f"Calling LLM for {len(missing)} cache-missing units…")
    config = Config.from_env()
    client = LLMClient(config)
    system_text = SYSTEM_PATH.read_text(encoding="utf-8").rstrip("\n")

    for i, u in enumerate(missing, 1):
        print(f"  [{i}/{len(missing)}] {u['unit_key']}")
        try:
            result = client.generate_json(
                system=system_text,
                user=u["user"],
                purpose="verify",
            )
            record = {"_key": u["unit_key"], "_prompt_sha": u["prompt_sha"]}
            record.update(result)
            append_to_cache(cache_path, record)
            cache[(u["unit_key"], u["prompt_sha"])] = record
            time.sleep(0.5)
        except Exception as exc:
            print(f"  [ERROR] {u['unit_key']}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# --score helpers
# ---------------------------------------------------------------------------

_RULE_CFG = {
    "r1": {"positive_label": "narration", "checker_flag": "not_student_voice"},
    "r2": {"positive_label": "generic", "checker_flag": "not_this_item"},
    "r3": {"positive_label": "filler", "checker_flag": "implausible_zero"},
}


def _get_checker_flags(
    response: dict[str, Any],
    e_map: dict[str, str],  # {"E1": ex_id, ...}
) -> dict[str, dict[str, Any]]:
    """Return {ex_id: flag_dict} from response example_flags, using E-map to resolve ids."""
    result: dict[str, dict[str, Any]] = {}

    for ef in response.get("example_flags", []):
        e_num = ef.get("id", "")  # e.g. "E1"
        ex_id = e_map.get(e_num)
        if ex_id is None:
            continue
        result[ex_id] = ef
    return result


def _score_rule(
    rule: str,
    labelled_entries: list[dict[str, Any]],
    unit_flags: dict[str, dict[str, Any]],  # ex_id -> flag_dict
) -> dict[str, int]:
    """Score one rule over a list of labelled entries.  Returns count dict."""
    cfg = _RULE_CFG[rule]
    positive_label = cfg["positive_label"]
    flag_key = cfg["checker_flag"]

    tp = fp = fn = tn = errors = 0

    for entry in labelled_entries:
        ex_id = entry["id"]
        labels = entry["labels"]

        if rule == "r3":
            if labels["r3"] == "n/a":
                continue
            label_positive = labels["r3"] == positive_label
        else:
            label_positive = labels[rule] == positive_label

        flag_dict = unit_flags.get(ex_id)
        if flag_dict is None:
            errors += 1
            continue

        flag_val = flag_dict.get(flag_key)
        if rule == "r3" and flag_val is None:
            # null on a level-0 example counts as error
            errors += 1
            continue
        if not isinstance(flag_val, bool):
            errors += 1
            continue

        if label_positive and flag_val:
            tp += 1
        elif not label_positive and flag_val:
            fp += 1
        elif label_positive and not flag_val:
            fn += 1
        else:
            tn += 1

    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn, "errors": errors}


def _recall(counts: dict[str, int]) -> str:
    denom = counts["TP"] + counts["FN"]
    if denom == 0:
        return "n/a"
    return f"{counts['TP'] / denom:.0%}"


def _ffr(counts: dict[str, int]) -> str:
    """False-flag rate = FP / (FP + TN)."""
    denom = counts["FP"] + counts["TN"]
    if denom == 0:
        return "n/a"
    return f"{counts['FP'] / denom:.0%}"


def _md_cell(value: object) -> str:
    """Escape pipe characters so a value is safe inside a markdown table cell."""
    return str(value).replace("|", "\\|")


def cmd_score(
    units: list[dict[str, Any]],
    cache_path: pathlib.Path,
) -> None:
    cache = load_cache(cache_path)

    # Check all units are cached
    missing_keys = []
    for u in units:
        if cache_lookup(cache, u["unit_key"], u["prompt_sha"]) is None:
            missing_keys.append(u["unit_key"])
    if missing_keys:
        print("Missing from cache (run --live or --import-responses first):")
        for k in sorted(missing_keys):
            print(f"  {k}")
        sys.exit(1)

    # Load labelled set
    labelled_data = json.loads(LABELLED_SET_PATH.read_text(encoding="utf-8"))
    labelled_entries = labelled_data["entries"]

    # Build combined flag lookup: ex_id -> flag_dict
    # and also unit_lookup: unit_key -> unit
    unit_by_key = {u["unit_key"]: u for u in units}
    all_flags: dict[str, dict[str, Any]] = {}
    for u in units:
        resp = cache_lookup(cache, u["unit_key"], u["prompt_sha"])
        flags = _get_checker_flags(resp, u["e_map"])
        all_flags.update(flags)

    # Partition labelled entries by set
    ns_entries = [e for e in labelled_entries if e["set"] == "ns"]
    ss_entries = [e for e in labelled_entries if e["set"] == "ss"]
    trap_entries = [e for e in labelled_entries if e["set"] == "trap"]
    inscope_entries = ns_entries + ss_entries

    lines: list[str] = []

    disagreements: list[dict[str, Any]] = []

    for rule in ["r1", "r2", "r3"]:
        cfg = _RULE_CFG[rule]
        flag_key = cfg["checker_flag"]

        # Build per-example text lookup: ex_id -> text
        # (from units)
        ex_text_lookup: dict[str, str] = {}
        for u in units:
            for ex in u["examples"]:
                ex_text_lookup[ex["id"]] = ex["text"]

        # Compute confusion matrices
        strata = [
            ("ns", ns_entries),
            ("ss", ss_entries),
            ("in-scope (ns+ss)", inscope_entries),
            ("trap", trap_entries),
        ]

        rule_lines = [f"### Rule {rule} ({flag_key})\n"]
        rule_lines.append("| Stratum | n | TP | FP | FN | TN | errors | recall | false-flag rate |")
        rule_lines.append("|---|---|---|---|---|---|---|---|---|")

        for stratum_name, stratum_entries in strata:
            if rule == "r3":
                judged = [e for e in stratum_entries if e["labels"]["r3"] != "n/a"]
            else:
                judged = stratum_entries

            counts = _score_rule(rule, judged, all_flags)
            n = len(judged)
            rule_lines.append(
                f"| {_md_cell(stratum_name)} | {n} | {counts['TP']} | {counts['FP']} | "
                f"{counts['FN']} | {counts['TN']} | {counts['errors']} | "
                f"{_md_cell(_recall(counts))} | {_md_cell(_ffr(counts))} |"
            )

        # Trap-set false positives
        trap_judged = [e for e in trap_entries if rule != "r3" or e["labels"]["r3"] != "n/a"]
        trap_flagged_ids = []
        for entry in trap_judged:
            flag_dict = all_flags.get(entry["id"])
            if flag_dict is None:
                continue
            flag_val = flag_dict.get(flag_key)
            if flag_val is True:
                trap_flagged_ids.append(entry["id"])

        rule_lines.append("")
        rule_lines.append(
            f"**Trap-set false positives ({rule}):** "
            f"{len(trap_flagged_ids)}/{len(trap_judged)} flagged. "
            + (f"Flagged IDs: {trap_flagged_ids}" if trap_flagged_ids else "None.")
        )
        rule_lines.append("")

        lines.extend(rule_lines)

        # Collect disagreements
        positive_label = cfg["positive_label"]
        for entry in labelled_entries:
            ex_id = entry["id"]
            labels = entry["labels"]

            if rule == "r3":
                if labels["r3"] == "n/a":
                    continue
                label_positive = labels["r3"] == positive_label
                labeller_label = labels["r3"]
            else:
                label_positive = labels[rule] == positive_label
                labeller_label = labels[rule]

            flag_dict = all_flags.get(ex_id)
            if flag_dict is None:
                continue

            flag_val = flag_dict.get(flag_key)
            if not isinstance(flag_val, bool):
                continue

            if label_positive != flag_val:
                # Find the level for this example
                ex_level = "?"
                for u in units:
                    for ex in u["examples"]:
                        if ex["id"] == ex_id:
                            ex_level = ex["level"]
                            break

                disagreements.append(
                    {
                        "id": ex_id,
                        "set": entry["set"],
                        "rule": rule,
                        "level": ex_level,
                        "text": ex_text_lookup.get(ex_id, ""),
                        "labeller_label": labeller_label,
                        "labeller_borderline": rule in entry.get("borderline", []),
                        "labeller_reason": entry.get("reason", {}).get(rule, ""),
                        "checker_flag": flag_val,
                        "checker_reason": flag_dict.get("reason", ""),
                        "checker_example_details": (
                            cache_lookup(cache, _find_unit_key(ex_id, unit_by_key), "") or {}
                        ).get("example_details", ""),
                    }
                )

    # Per-unit verdict table (informational)
    lines.append("### Per-unit checker verdicts (informational)\n")
    lines.append("| unit_key | specificity_violation | counting_violation | verdict |")
    lines.append("|---|---|---|---|")
    for u in units:
        if u["unit_key"].startswith("trap:"):
            continue
        resp = cache_lookup(cache, u["unit_key"], u["prompt_sha"]) or {}
        lines.append(
            f"| {_md_cell(u['unit_key'])} | {_md_cell(resp.get('specificity_violation', '?'))} | "
            f"{_md_cell(resp.get('counting_violation', '?'))} | {_md_cell(resp.get('verdict', '?'))} |"
        )

    # Fix the checker_example_details lookup
    # (re-derive them properly with the correct unit_key lookup)
    for d in disagreements:
        unit_key = _find_unit_key(d["id"], unit_by_key)
        if unit_key:
            resp = cache_lookup(cache, unit_key, unit_by_key[unit_key]["prompt_sha"]) or {}
            d["checker_example_details"] = resp.get("example_details", "")

    # Sort disagreements: rule then id
    disagreements.sort(key=lambda x: (x["rule"], x["id"]))

    # Write outputs
    matrices_text = "# 學生作答實例 checker matrices — #862\n\n" + "\n".join(lines) + "\n"
    MATRICES_PATH.write_text(matrices_text, encoding="utf-8")

    DISAGREEMENTS_PATH.write_text(
        json.dumps(disagreements, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Print to stdout
    print(matrices_text)
    print(f"\nDisagreements written to {DISAGREEMENTS_PATH}")
    print(f"Matrices written to {MATRICES_PATH}")


def _find_unit_key(ex_id: str, unit_by_key: dict[str, dict]) -> str:
    """Find which unit contains this example id."""
    for uk, u in unit_by_key.items():
        for ex in u["examples"]:
            if ex["id"] == ex_id:
                return uk
    return ""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rubric #862 — 學生作答實例 checker prompts, import, and scorer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--emit-prompts",
        action="store_true",
        help="Write prompts.jsonl and print unit/example counts.",
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

    if not any([args.emit_prompts, args.import_responses, args.live, args.score]):
        parser.print_help()


if __name__ == "__main__":
    main()
