"""
Main pipeline: convert a Taiwan math exam PDF into few-shot JSON training data.

Usage:
    python -m scripts.pdf_to_fewshot_JSON.pipeline <pdf_path> [--output-dir <dir>] [--exam-name <name>]

The pipeline runs 5 stages:
    1. Extract  — text + page images from PDF
    2. Parse    — LLM identifies individual questions from page batches
    3. Solve    — LLM solves each question and assigns metadata
    4. Map      — LLM assigns curriculum codes
    5. Format   — writes grouped JSON files to output_dir
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as a module from the project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import Config
from src.llm_client import LLMClient
from src.data_loader import load_curriculum, get_target_grade_content

from scripts.pdf_to_fewshot_JSON.pdf_extractor import extract_pages, group_pages
from scripts.pdf_to_fewshot_JSON.question_parser import parse_questions_from_batch
from scripts.pdf_to_fewshot_JSON.question_solver import solve_question, verify_question
from scripts.pdf_to_fewshot_JSON.curriculum_mapper import map_curriculum
from scripts.pdf_to_fewshot_JSON.json_formatter import format_question, group_by_style, save_to_files

PROMPTS_DIR = Path(__file__).parent / "prompts"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "few_shot"
CURRICULUM_PATH = PROJECT_ROOT / "data" / "curriculum" / "學習內容.json"


def run_pipeline(
    pdf_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    exam_name: str | None = None,
    batch_size: int = 2,
    skip_verify: bool = False,
) -> dict:
    """
    Run the full PDF-to-fewshot pipeline.

    Returns a summary dict:
        {
            "total": int,
            "by_style": {"text_only": N, "with_chart": N, "with_image": N},
            "files": {"text_only": Path, ...}
        }
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if exam_name is None:
        # Use the PDF filename stem as the exam name (e.g. "112P_Math" -> "112P")
        stem = pdf_path.stem
        exam_name = stem.split("_")[0] if "_" in stem else stem

    print(f"\n{'='*60}")
    print(f"PDF to Few-Shot Pipeline")
    print(f"Input:  {pdf_path}")
    print(f"Output: {output_dir}")
    print(f"Exam:   {exam_name}")
    print(f"{'='*60}\n")

    # Initialize LLM client
    config = Config()
    llm = LLMClient(config)

    # Load curriculum for grades 7-9
    print("Loading curriculum data...")
    curriculum = load_curriculum(CURRICULUM_PATH)
    curriculum_items = get_target_grade_content(curriculum)
    curriculum_dicts = [{"編碼": item.編碼, "說明": item.說明} for item in curriculum_items]

    # --- Stage 1: Extract ---
    print(f"\n[Stage 1] Extracting pages from PDF...")
    pages = extract_pages(pdf_path)
    has_images = any(p.get("image_b64") for p in pages)
    print(f"  Extracted {len(pages)} pages (images: {'yes' if has_images else 'no — pdftoppm not found'})")

    # --- Stage 2: Parse ---
    print(f"\n[Stage 2] Parsing questions from pages (batch_size={batch_size})...")
    batches = group_pages(pages, batch_size=batch_size)
    all_parsed: list[dict] = []
    for i, batch in enumerate(batches):
        page_nums = [p["page_number"] for p in batch]
        print(f"  Parsing batch {i+1}/{len(batches)}: pages {page_nums}...")
        try:
            parsed = parse_questions_from_batch(llm, batch, PROMPTS_DIR)
            print(f"    Found {len(parsed)} questions")
            all_parsed.extend(parsed)
        except Exception as e:
            print(f"    Warning: batch {i+1} parsing failed: {e}")

    # Deduplicate by question_number (keep last occurrence in case of cross-page splits)
    seen_nums: dict[str, int] = {}
    for i, q in enumerate(all_parsed):
        num = q.get("question_number", f"unknown_{i}")
        seen_nums[num] = i
    deduped = [all_parsed[i] for i in sorted(seen_nums.values())]
    print(f"\n  Total unique questions found: {len(deduped)}")

    # --- Stage 3: Solve ---
    print(f"\n[Stage 3] Solving questions...")
    solved_questions: list[tuple[dict, dict]] = []  # (parsed, solved)
    for parsed_q in deduped:
        q_num = parsed_q.get("question_number", "?")
        print(f"  Solving {q_num}...")
        try:
            solved = solve_question(llm, parsed_q, PROMPTS_DIR)
            if not skip_verify:
                solved = verify_question(llm, solved, PROMPTS_DIR)
            solved_questions.append((parsed_q, solved))
        except Exception as e:
            print(f"    Warning: failed to solve {q_num}: {e}")

    # --- Stage 4: Map Curriculum ---
    print(f"\n[Stage 4] Mapping curriculum codes...")
    enriched: list[tuple[dict, dict, list[dict]]] = []
    for parsed_q, solved in solved_questions:
        q_num = parsed_q.get("question_number", "?")
        print(f"  Mapping curriculum for {q_num}...")
        try:
            codes = map_curriculum(llm, solved, curriculum_dicts, PROMPTS_DIR)
            enriched.append((parsed_q, solved, codes))
        except Exception as e:
            print(f"    Warning: curriculum mapping failed for {q_num}: {e}")
            enriched.append((parsed_q, solved, [{"編碼": "N-7-1", "說明": "（需手動確認課程編碼）"}]))

    # --- Stage 5: Format & Save ---
    print(f"\n[Stage 5] Formatting and saving...")
    formatted: list[dict] = []
    for parsed_q, solved, codes in enriched:
        q_num = parsed_q.get("question_number", "unknown")
        result = format_question(solved, codes, q_num)
        if result:
            formatted.append(result)
        else:
            print(f"  Warning: could not format {q_num} — missing required fields")

    grouped = group_by_style(formatted)
    files = save_to_files(grouped, output_dir, exam_name)

    # Summary
    by_style = {style: len(qs) for style, qs in grouped.items() if qs}
    summary = {
        "total": len(formatted),
        "by_style": by_style,
        "files": {style: str(path) for style, path in files.items()},
    }

    print(f"\n{'='*60}")
    print(f"Pipeline complete!")
    print(f"  Total questions: {summary['total']}")
    for style, count in by_style.items():
        print(f"  {style}: {count}")
    print(f"{'='*60}\n")

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Convert a Taiwan math exam PDF into few-shot JSON training data."
    )
    parser.add_argument("pdf_path", help="Path to the exam PDF file")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory for few-shot JSON files (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--exam-name",
        default=None,
        help="Exam identifier used in output filenames (default: derived from PDF filename)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=2,
        help="Number of PDF pages to process per LLM call (default: 2)",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip the second-pass answer verification (faster but less reliable)",
    )

    args = parser.parse_args()

    summary = run_pipeline(
        pdf_path=Path(args.pdf_path),
        output_dir=Path(args.output_dir),
        exam_name=args.exam_name,
        batch_size=args.batch_size,
        skip_verify=args.skip_verify,
    )

    # Print machine-readable summary to stdout
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
