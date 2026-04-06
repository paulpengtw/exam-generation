# Prompt: Parse Questions from Exam Pages

You are processing pages from a Taiwan national junior high school math exam (國中教育會考數學科).

## Your Task

Given the raw text extracted from 2-3 consecutive exam pages (plus optional page images), identify and extract all individual questions present on these pages.

## Output Format

Return a JSON array. Each element represents one question:

```json
[
  {
    "question_number": "Q1",
    "raw_text": "Full question text reconstructed from the page, including all sub-parts and answer choices",
    "figure_description": "Detailed description of any figure/diagram/table if present, or null if none",
    "has_figure": true,
    "question_type_hint": "選擇題 or 非選擇題",
    "page_numbers": [1, 2]
  }
]
```

## Rules

1. **Reconstruct math notation**: PDF text extraction mangles formulas. Reconstruct them:
   - Fractions like "3/4" should be kept as-is or written as `3/4`
   - Radicals: if you see "135" after a radical symbol context, it may be √135
   - Superscripts: x² means x squared, not x2
   - Subscripts: use standard notation

2. **Multiple choice**: Taiwan 會考 uses (A)(B)(C)(D) format. Include all four options.

3. **Question groups (題組題)**: Some questions share a common stem/scenario. Keep the shared text with each sub-question, or note the grouping relationship.

4. **Figures**: If a figure is described in the text (like "如圖" = "as shown in the figure"), describe it based on what you can see in the page image. Include coordinates, dimensions, labels, and shapes.

5. **Tables**: If a table is present, transcribe all headers and cell values.

6. **Non-multiple-choice questions**: The exam ends with 非選擇題 (constructed response). These have sub-parts (一)(二) and require written answers.

7. **Page boundaries**: A question may span two pages. If a question starts near the bottom of one page and continues on the next, include its full text.

## Exam Structure Reference

Taiwan 會考 math exam has:
- 選擇題 (multiple choice): Q1-Q25
- 非選擇題 (constructed response): Q1-Q2 (labeled differently from the above)

Questions Q1-Q25 are all (A)(B)(C)(D) single-answer multiple choice.
Non-Q1 and Non-Q2 are open-ended, worth more points.
