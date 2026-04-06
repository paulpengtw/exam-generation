---
name: pdf-to-fewshot
description: >
  Converts a Taiwan junior high school math exam PDF into structured few-shot JSON training data
  for the exam-generation project. Use this skill whenever the user mentions converting a PDF exam,
  processing a new exam file, making few-shot samples from a PDF, OCR-ing an exam, or wants to add
  training data from any exam PDF (e.g. "process 113P_Math.pdf", "make few-shot from the new exam",
  "add 114P to the training data").
---

# PDF to Few-Shot JSON Pipeline

This skill runs the pipeline at `scripts/pdf_to_fewshot_JSON/pipeline.py` to convert a Taiwan
national math exam PDF into few-shot JSON training examples.

## When to use

- User drops a new exam PDF (e.g. 113P_Math.pdf, 114P_Math.pdf) and wants it as training data
- User asks to "process", "OCR", or "convert" an exam PDF
- User wants to add few-shot examples from a new exam year

## Steps

1. **Confirm the PDF path** — check that the file exists in `data/example_exams/` or wherever the user indicates.

2. **Run the pipeline**:
   ```bash
   cd /path/to/exam-generation
   uv run python -m scripts.pdf_to_fewshot_JSON.pipeline data/example_exams/<exam>.pdf
   ```
   Optional flags:
   - `--exam-name 113P` — override the exam identifier in output filenames
   - `--output-dir data/few_shot` — where to write the JSON files (default)
   - `--batch-size 2` — pages per LLM call (default 2)
   - `--skip-verify` — skip second-pass verification (faster)

3. **Review output** — the pipeline writes to:
   - `data/few_shot/text_only/{exam_name}_questions.json`
   - `data/few_shot/with_chart/{exam_name}_questions.json`
   - `data/few_shot/with_image/{exam_name}_questions.json`

4. **Spot-check quality** — read 3-5 questions from each output file and verify:
   - Correct answers are accurate
   - Curriculum codes are appropriate
   - Chart specs have correct data
   - `description` field is a meaningful Chinese topic label

5. **Report summary** — tell the user:
   - Total questions processed
   - Count by style (text_only, with_chart, with_image)
   - Any questions that failed or need manual review

## Quality signals to watch for

- `正確答案：` line must be present in `正確解題分析`
- `chart_spec` must be non-null for all `with_chart` and `with_image` questions
- `學習內容` codes should follow the pattern `{X}-{7|8|9}-{N}` (e.g. A-8-5, S-9-2)
- `題目` array should include the answer choices for 選擇題

## Prerequisites

- `poppler` must be installed for page image rendering: `brew install poppler`
- Environment variables `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) and `OPENAI_BASE_URL` must be set
- Dependencies installed: `uv sync`

## Troubleshooting

**"pdftoppm is not available"**: Install poppler with `brew install poppler`. Without it, the pipeline
falls back to text-only extraction (no vision), which may miss figures.

**JSON parse errors**: The LLM occasionally returns malformed JSON. Re-running the pipeline usually
fixes this. For stubborn cases, run with `--batch-size 1` to isolate the problematic page.

**Wrong answers**: The two-pass verification catches most errors, but complex geometry questions
may need manual review. Check questions flagged with `【驗算注意】` in their solution.
