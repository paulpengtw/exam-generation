# PDF to Few-Shot JSON Pipeline

Converts a Taiwan national junior high school math exam PDF into structured few-shot JSON training data for the `exam-generation` project.

## Quick Start

```bash
# From the project root
uv run python -m scripts.pdf_to_fewshot_JSON.pipeline data/example_exams/113P_Math.pdf
```

Outputs:
- `data/few_shot/text_only/113P_questions.json`
- `data/few_shot/with_chart/113P_questions.json`
- `data/few_shot/with_image/113P_questions.json`

## Prerequisites

```bash
# Install poppler for PDF page image rendering
brew install poppler  # macOS

# Install Python dependencies
uv sync
```

Set environment variables:
```bash
export ANTHROPIC_API_KEY=...       # or OPENAI_API_KEY
export OPENAI_BASE_URL=...         # if using a proxy (optional)
```

## CLI Options

```
python -m scripts.pdf_to_fewshot_JSON.pipeline <pdf_path> [options]

Arguments:
  pdf_path              Path to the exam PDF

Options:
  --output-dir DIR      Output directory (default: data/few_shot)
  --exam-name NAME      Exam identifier for filenames (default: derived from PDF name)
  --batch-size N        Pages per LLM parsing call (default: 2)
  --skip-verify         Skip two-pass answer verification
```

## Pipeline Stages

| Stage | Module | Description |
|-------|--------|-------------|
| 1. Extract | `pdf_extractor.py` | Extract text (pdfplumber) + render page images (pdftoppm) |
| 2. Parse | `question_parser.py` | LLM identifies individual questions from page batches, uses vision for figures |
| 3. Solve | `question_solver.py` | LLM solves each question + two-pass answer verification |
| 4. Map | `curriculum_mapper.py` | LLM assigns grades 7-9 curriculum codes (學習內容) |
| 5. Format | `json_formatter.py` | Groups by style, validates fields, writes JSON output |

## Output Schema

Each question in the output JSON follows this schema:

```json
{
  "style": "text_only | with_chart | with_image",
  "description": "Brief Chinese topic label",
  "question": {
    "情境": "個人 | 社會時事 | 科學 | 職業 | 建築與藝術 | 數學文字情境",
    "題型種類": "單一題 | 題組題",
    "題型": "選擇題 | 封閉式建構反應題 | 開放式建構反應題",
    "數學思考": ["形成 | 運用 | 詮釋評估"],
    "學習內容": [{"編碼": "A-8-5", "說明": "..."}],
    "題目": ["question text", "(A)...", "(B)...", "(C)...", "(D)..."],
    "正確解題分析": ["正確答案：(X)", "【步驟一：...】..."],
    "chart_spec": { ... }  // only for with_chart and with_image
  }
}
```

## Architecture Notes

- **Reuses `src/`**: Uses `src/llm_client.py`, `src/config.py`, `src/data_loader.py` for LLM calls and curriculum loading
- **Self-contained**: Can be run independently without importing from `src.cli` or other entry points
- **Prompt templates**: All LLM prompts live in `prompts/*.md` for easy iteration
- **Vision-first**: When pdftoppm is available, page images are sent to the LLM alongside text for better figure interpretation
