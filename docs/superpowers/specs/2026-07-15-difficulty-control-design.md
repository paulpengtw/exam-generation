# Spec: Explicit difficulty control easy / medium / hard (issue #116)

## Why

Difficulty is implicit (grade + curriculum only). Users cannot request an easier or harder set, and output carries no difficulty trace.

## Decision

Apply to **all three subjects** (issue was SS-only). Difficulty is a pure passthrough — never randomized; default `medium`.

## Design

### Shared model

`Difficulty(str, Enum)` = `easy | medium | hard`, defined once in `src/common/` (e.g. `src/common/difficulty.py`) and imported by all three subject schema modules. Each subject's `SampledParams` gains `difficulty: Difficulty = Difficulty.medium`. Output traceability: record the difficulty in each subject's question metadata (math `QuestionMetadata`; SS/NS on `ExamQuestion` metadata) so exports and history show it.

### Samplers

`sample_params(..., difficulty: Difficulty | None = None)` in all three samplers; `None` → `medium`; passthrough into `SampledParams`.

### Prompts

Per-subject `DIFFICULTY_INSTRUCTIONS: dict[str, str]` injected as a `## 難度要求` section in the user prompt (for SS/NS: in the 文本生成器 prompt so the passage complexity matches, and echoed in the 子題產生器 prompt so item cognition matches):

- **Social studies:** the issue's reading-inference ladder (easy = 直接擷取; medium = 單步推論/段內統整; hard = 多步推論、跨文本整合與評鑑).
- **Math:** easy = 單一概念、直接套用公式或定義; medium = 兩步驟解題、單一情境轉譯; hard = 多步驟推理、跨單元整合或建模、非例行問題.
- **Natural sciences:** PISA competency depth — easy = 再現科學知識、讀取單一圖表; medium = 應用概念解釋現象、單步資料詮釋; hard = 評估實驗設計、跨資料整合、論證與批判.

Schema CSVs: append 難度 rows (value + instruction) to `data/social_studies/curriculum/schema_parameters.csv` and `data/natural_sciences/curriculum/schema_parameters.csv`; math adds a `難度` category to `question_schemas.json`. The prompt instructions read from these data files where each subject's instruction plumbing already exists, keeping researcher editability. Note: the SS/NS loaders and math `schema_loader.build_enums()` load all categories generically, so new rows flow through without loader changes; the samplers simply don't randomize this category.

### API + UI

- `GenerateParams.difficulty: Literal["easy","medium","hard"] | None = None` + query param on `GET /api/generate`; threaded per subject into `sample_params`.
- CLI: `--difficulty` on all three CLIs.
- `ParamForm.tsx`: one 難度 dropdown (預設(中等) / 簡單 / 中等 / 困難) for all subjects; sent only when explicitly chosen.

### Verifier/corrector

Difficulty joins the corrector frozen-fields list (a correction must not change requested difficulty). Verifier prompt mentions the requested difficulty as context but does not fail on subjective difficulty mismatch (consistent with the lenient stances).

## Testing

- Sampler passthrough + default-medium tests per subject.
- Prompt tests: `## 難度要求` present with the right text per level; absent-param behaves as medium.
- Route test: query param accepted; invalid value → 422.
- Vitest: dropdown emits the param only when set.

## Out of scope

Per-小題 difficulty; auto-calibration/IRT; difficulty-based sampler pool filtering.
