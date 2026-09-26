"""
Research #870 — Measure first-draft shape-check failures on live generation.

This script generates 5 題組 per subject (自然科學 and 社會領域), each containing
at least one open-response 小題, through the REAL generation pipeline with
verify+correct enabled. It records from the verification trail:

  - first-draft shape-check failure rate (fraction of 題組 whose first
    verification details contain ``[評分規準形狀檢核]``);
  - pass rate after correction;
  - the number of correction rounds per 題組.

It exits early with a clear message when API credit/keys are unavailable,
without writing any numbers.

Credentials required:
  - 自然科學 and 社會領域 both route generation through the EXECUTE model
    (LLM_MODEL_EXECUTE / GEMINI_API_KEY for Gemini, or LLM_API_KEY for Anthropic).
  - Verification routes through LLM_API_KEY (claude-opus-4-6 by default).

Run from the repo root:
    uv run python scripts/research/rubric_870_live_batch.py

Results are written to:
    docs/research/870-live-shape-check-batch/results.json

IMPORTANT: No LLM calls are made until API credentials are probed successfully.
"""

from __future__ import annotations

import json
import pathlib
import sys
import uuid
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.common.open_response_rubric import SHAPE_CHECK_TAG  # noqa: E402
from src.config import Config  # noqa: E402
from src.llm_client import LLMClient  # noqa: E402

# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------
OUT = ROOT / "docs" / "research" / "870-live-shape-check-batch"
OUT.mkdir(parents=True, exist_ok=True)

RESULTS_FILE = OUT / "results.json"

# ---------------------------------------------------------------------------
# Batch parameters
# ---------------------------------------------------------------------------
BATCH_SIZE = 5  # 題組 per subject

# ---------------------------------------------------------------------------
# Credential probe
# ---------------------------------------------------------------------------

def _probe_credentials(config: Config) -> str | None:
    """Return None if credentials look usable; return an error message otherwise.

    Probes by attempting a minimal (1-token) completion.  The probe is cheap
    and reveals missing keys or exhausted credit before starting the batch.
    """
    try:
        client = LLMClient(config)
        client.messages(
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
        return None
    except Exception as exc:  # noqa: BLE001
        return str(exc)


# ---------------------------------------------------------------------------
# Trail collection helpers
# ---------------------------------------------------------------------------

@dataclass
class TrialRecord:
    """Per-題組 result."""

    question_id: str
    subject: str  # "ss" | "ns"
    first_draft_shape_failed: bool = False
    final_passed: bool = False
    correction_rounds: int = 0
    trail: list[dict[str, Any]] = dc_field(default_factory=list)


def _collect_trail(record: TrialRecord, entry: Any) -> None:
    """on_trail_entry callback that appends trail entries to record.trail."""
    d = entry.model_dump() if hasattr(entry, "model_dump") else dict(entry)
    record.trail.append(d)


def _analyse_trail(record: TrialRecord) -> None:
    """Set first_draft_shape_failed, final_passed, correction_rounds from trail."""
    verification_entries = [
        e for e in record.trail if e.get("kind") == "verification"
    ]
    correction_entries = [
        e for e in record.trail if e.get("kind") == "correction"
    ]

    if not verification_entries:
        return

    # First-draft shape check: first verification entry
    first = verification_entries[0]
    details = first.get("details", "")
    record.first_draft_shape_failed = SHAPE_CHECK_TAG in details

    # Final pass: last verification entry
    last = verification_entries[-1]
    record.final_passed = bool(last.get("passed", False))

    # Correction rounds: number of correction trail entries
    record.correction_rounds = len(correction_entries)


# ---------------------------------------------------------------------------
# Social studies batch
# ---------------------------------------------------------------------------

def _run_ss_batch(config: Config, client: LLMClient) -> list[TrialRecord]:
    from src.social_studies.cli import generate_with_corrections
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import SubQuestionConfig

    # Force at least one 開放式建構反應題 小題 per 題組 via subquestion_configs.
    # Use a 3-小題 layout: 選擇題, 開放式建構反應題, 選擇題.
    def _make_params(seed: int) -> Any:
        sq_configs = [
            SubQuestionConfig(question_type=None),          # 小題1: sampled freely
            SubQuestionConfig(question_type="開放式建構反應題"),  # 小題2: open-response
            SubQuestionConfig(question_type=None),          # 小題3: sampled freely
        ]
        return sample_params(seed=seed, subquestion_configs=sq_configs)

    records: list[TrialRecord] = []
    for i in range(BATCH_SIZE):
        qid = f"870-ss-{i+1}-{uuid.uuid4().hex[:8]}"
        record = TrialRecord(question_id=qid, subject="ss")
        params = _make_params(seed=1000 + i)
        try:
            generate_with_corrections(
                config=config,
                client=client,
                params=params,
                question_id=qid,
                max_retries=3,
                on_trail_entry=lambda e: _collect_trail(record, e),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  [ss {qid}] ERROR: {exc}", file=sys.stderr)
        _analyse_trail(record)
        records.append(record)
        print(
            f"  ss {i+1}/{BATCH_SIZE}: shape_failed={record.first_draft_shape_failed}"
            f"  final_passed={record.final_passed}"
            f"  corrections={record.correction_rounds}"
        )
    return records


# ---------------------------------------------------------------------------
# Natural sciences batch
# ---------------------------------------------------------------------------

def _run_ns_batch(config: Config, client: LLMClient) -> list[TrialRecord]:
    from src.natural_sciences.cli import generate_with_corrections
    from src.natural_sciences.sampler import sample_params
    from src.natural_sciences.schemas import SubQuestionConfig

    # Force at least one Constructed-response 小題 per 題組.
    # Use a 3-小題 layout: Simple-multiple-choice, Constructed-response, Simple-multiple-choice.
    def _make_params(seed: int) -> Any:
        sq_configs = [
            SubQuestionConfig(question_type=None),                  # 小題1: sampled freely
            SubQuestionConfig(question_type="Constructed-response"),# 小題2: open-response
            SubQuestionConfig(question_type=None),                  # 小題3: sampled freely
        ]
        return sample_params(seed=seed, subquestion_configs=sq_configs)

    records: list[TrialRecord] = []
    for i in range(BATCH_SIZE):
        qid = f"870-ns-{i+1}-{uuid.uuid4().hex[:8]}"
        record = TrialRecord(question_id=qid, subject="ns")
        params = _make_params(seed=2000 + i)
        try:
            generate_with_corrections(
                config=config,
                client=client,
                params=params,
                question_id=qid,
                max_retries=3,
                on_trail_entry=lambda e: _collect_trail(record, e),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  [ns {qid}] ERROR: {exc}", file=sys.stderr)
        _analyse_trail(record)
        records.append(record)
        print(
            f"  ns {i+1}/{BATCH_SIZE}: shape_failed={record.first_draft_shape_failed}"
            f"  final_passed={record.final_passed}"
            f"  corrections={record.correction_rounds}"
        )
    return records


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _summarise(records: list[TrialRecord], subject_label: str) -> dict[str, Any]:
    n = len(records)
    if n == 0:
        return {"subject": subject_label, "n": 0}
    shape_fails = sum(1 for r in records if r.first_draft_shape_failed)
    final_passes = sum(1 for r in records if r.final_passed)
    total_corrections = sum(r.correction_rounds for r in records)
    return {
        "subject": subject_label,
        "n": n,
        "first_draft_shape_check_failure_rate": shape_fails / n,
        "pass_rate_after_correction": final_passes / n,
        "mean_correction_rounds": total_corrections / n,
        "per_question": [
            {
                "question_id": r.question_id,
                "first_draft_shape_failed": r.first_draft_shape_failed,
                "final_passed": r.final_passed,
                "correction_rounds": r.correction_rounds,
            }
            for r in records
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    config = Config.from_env()

    # --- Credential probe ---
    print("Probing API credentials …")

    # Check Anthropic API key (used for verification / planning)
    if not config.api_key:
        print(
            "\nEXIT: LLM_API_KEY is not set. "
            "Both subjects require an Anthropic key for verification (claude-opus-4-6). "
            "Set LLM_API_KEY in .env and retry.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Check execute-model credentials (Gemini is the default execute model)
    # The default execute model is gemini-3.1-pro-preview, which needs GEMINI_API_KEY.
    execute_model = config.model_execute
    if "gemini" in execute_model.lower() and not config.gemini_api_key:
        print(
            f"\nEXIT: GEMINI_API_KEY is not configured but the execute model is "
            f"'{execute_model}'. Set GEMINI_API_KEY in .env (or override "
            f"LLM_MODEL_EXECUTE to an Anthropic model) and retry.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Live probe against the Anthropic verify endpoint
    error = _probe_credentials(config)
    if error is not None:
        print(
            f"\nEXIT: API credential probe failed — {error}\n"
            "No numbers were written. Fix the credentials and retry.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("Credentials OK.")

    # --- Run batches ---
    client = LLMClient(config)

    print(f"\nRunning 社會領域 batch ({BATCH_SIZE} 題組) …")
    ss_records = _run_ss_batch(config, client)

    print(f"\nRunning 自然科學 batch ({BATCH_SIZE} 題組) …")
    ns_records = _run_ns_batch(config, client)

    # --- Summarise and write ---
    results = {
        "batch_size_per_subject": BATCH_SIZE,
        "shape_check_tag": SHAPE_CHECK_TAG,
        "social_studies": _summarise(ss_records, "社會領域"),
        "natural_sciences": _summarise(ns_records, "自然科學"),
    }

    RESULTS_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\nResults written to {RESULTS_FILE}")

    # --- Print summary ---
    for key in ("social_studies", "natural_sciences"):
        s = results[key]
        print(
            f"\n{s['subject']} ({s['n']} 題組):"
            f"\n  first-draft shape-check failure rate : {s.get('first_draft_shape_check_failure_rate', 'N/A'):.0%}"  # noqa: E501
            f"\n  pass rate after correction           : {s.get('pass_rate_after_correction', 'N/A'):.0%}"  # noqa: E501
            f"\n  mean correction rounds               : {s.get('mean_correction_rounds', 'N/A'):.2f}"  # noqa: E501
        )


if __name__ == "__main__":
    main()
