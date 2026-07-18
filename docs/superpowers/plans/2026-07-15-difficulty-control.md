# Difficulty Control (easy / medium / hard) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit `difficulty` parameter (`easy` / `medium` / `hard`, default `medium`) that flows from the web UI / CLI / API through each subject's sampler into a `## 難度要求` prompt section, freezes across corrections, and is recorded on the emitted question's metadata (GitHub issue #116).

**Architecture:** A single `Difficulty(str, Enum)` in `src/common/difficulty.py` is imported by all three subject schema modules. Each subject's `SampledParams` gains a `difficulty` field (default `Difficulty.medium`), each subject's sampler accepts a `difficulty` kwarg as a pure passthrough, and each subject's `context_builder` owns a `DIFFICULTY_INSTRUCTIONS: dict[str, str]` mapping. The instruction text is injected once as a `## 難度要求` section — for social studies and natural sciences, into **both** `build_text_user_prompt` (so passage complexity matches) and `build_subquestion_user_prompt` (so item cognition matches). The 難度 rows are data-driven (CSV rows in SS/NS `schema_parameters.csv`; JSON entries in `question_schemas.json` for math) so researchers can edit the wording without code changes.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, pytest via `uv run pytest`; React 19 + Vite + Tailwind 4 on the web side (vitest for component tests).

**Spec:** `docs/superpowers/specs/2026-07-15-difficulty-control-design.md`

## Global Constraints

- `Difficulty(str, Enum)` values are exactly `"easy" | "medium" | "hard"`, defined **once** in `src/common/difficulty.py`; every other module imports from there.
- Default is `medium` everywhere: `SampledParams.difficulty = Difficulty.medium`; `sample_params(..., difficulty=None)` → `medium`; API `GenerateParams.difficulty: Literal["easy","medium","hard"] | None = None`; UI dropdown default label is "預設（中等）" and sends no query param.
- Difficulty is a **pure passthrough** — never randomized. The samplers must not add it to any RNG choice.
- Applies to **all three subjects** (math, social studies, natural sciences). The spec explicitly widens issue #116 (originally SS-only).
- Difficulty joins each subject corrector's frozen-field list: a correction pass must never change 難度.
- Verifier prompts mention the requested difficulty as context but must **not** fail on subjective difficulty mismatch (consistent with math's strict and SS/NS's lenient stances — behaviour otherwise unchanged).
- For SS and NS, the `## 難度要求` section is injected in **both** the 文本生成器 prompt (`build_text_user_prompt`) and the 子題產生器 prompt (`build_subquestion_user_prompt`).
- Frontend: one 難度 dropdown in `ParamForm.tsx` (`預設(中等) / 簡單 / 中等 / 困難`) for all subjects; the value is sent as a `difficulty` query param on `GET /api/generate` **only** when the user picked a non-default option.
- Output traceability: math records `difficulty` on `QuestionMetadata` (the existing field on `ExamQuestion.metadata`); SS and NS records `difficulty` on their own `QuestionMetadata` classes so the field appears in every emitted `ExamQuestion.metadata`.
- All Python commands run from repo root `/workspace/exam-generation`; web commands run from `/workspace/exam-generation/web`.

## Pre-existing defect this plan fixes first

Commit `d534147` ("fix: remove unused fireEvent import that broke tsc build") also silently removed vitest and all testing-library devDependencies plus the `test`/`test:watch` scripts from `web/package.json`, while `web/vitest.config.ts`, `web/src/test/setup.ts`, and two `*.test.tsx` files (`QuestionCard.test.tsx`, `CoreQuestionPicker.test.tsx`) remain in the tree. Task 13 (frontend) needs `npm test` to work, so the first frontend step restores the tooling before the new component test is added.

---

### Task 1: Shared Difficulty enum module

**Files:**
- Create: `src/common/difficulty.py`
- Create: `tests/test_common_difficulty.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Difficulty(str, Enum)` with members `easy`, `medium`, `hard` — imported by every subject schema and sampler in later tasks.
  - `DEFAULT_DIFFICULTY: Difficulty = Difficulty.medium` — used by API models, samplers, and metadata to keep the default single-sourced.
  - `resolve_difficulty(value: str | Difficulty | None) -> Difficulty` — helper that maps `None` / empty string / `Difficulty` instance to a `Difficulty` value, raising `ValueError` on unknown strings.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_common_difficulty.py`:

```python
"""Tests for the shared Difficulty enum + resolver."""

from __future__ import annotations

import pytest

from src.common.difficulty import DEFAULT_DIFFICULTY, Difficulty, resolve_difficulty


def test_difficulty_members_exact():
    assert [d.value for d in Difficulty] == ["easy", "medium", "hard"]


def test_difficulty_is_str_enum():
    # str-mixin so JSON serialization and dict lookups behave like plain strings
    assert Difficulty.easy == "easy"
    assert Difficulty.medium == "medium"
    assert Difficulty.hard == "hard"


def test_default_is_medium():
    assert DEFAULT_DIFFICULTY is Difficulty.medium


def test_resolve_none_returns_medium():
    assert resolve_difficulty(None) is Difficulty.medium


def test_resolve_empty_string_returns_medium():
    assert resolve_difficulty("") is Difficulty.medium


def test_resolve_string_returns_enum():
    assert resolve_difficulty("easy") is Difficulty.easy
    assert resolve_difficulty("medium") is Difficulty.medium
    assert resolve_difficulty("hard") is Difficulty.hard


def test_resolve_enum_passthrough():
    assert resolve_difficulty(Difficulty.hard) is Difficulty.hard


def test_resolve_unknown_string_raises():
    with pytest.raises(ValueError):
        resolve_difficulty("insane")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_common_difficulty.py -x`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.common.difficulty'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/common/difficulty.py`:

```python
"""Shared difficulty enum used by all three subject pipelines (issue #116).

Difficulty is a pure passthrough — samplers never randomize it. Default is
medium. The str-mixin lets values round-trip through JSON / query strings /
Pydantic Literals interchangeably.
"""

from __future__ import annotations

from enum import Enum


class Difficulty(str, Enum):
    """easy = 直接擷取 / 一步; medium = 中等; hard = 多步整合、批判與評估。"""

    easy = "easy"
    medium = "medium"
    hard = "hard"


DEFAULT_DIFFICULTY: Difficulty = Difficulty.medium


def resolve_difficulty(value: "str | Difficulty | None") -> Difficulty:
    """Map None / empty / str / Difficulty to a Difficulty enum member.

    None or empty string → DEFAULT_DIFFICULTY (medium). A Difficulty is
    returned unchanged. An unknown string raises ValueError.
    """
    if value is None or value == "":
        return DEFAULT_DIFFICULTY
    if isinstance(value, Difficulty):
        return value
    return Difficulty(value)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_common_difficulty.py -x`
Expected: PASS — 7 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/common/difficulty.py tests/test_common_difficulty.py
git commit -m "feat(common): add Difficulty enum + resolver for issue #116"
```

---

### Task 2: Add 難度 rows to schema data files

**Files:**
- Modify: `data/social_studies/curriculum/schema_parameters.csv` (append 難度 rows at end)
- Modify: `data/natural_sciences/curriculum/schema_parameters.csv` (append 難度 rows at end)
- Modify: `question_schemas.json` (append `難度` category)
- Test: `tests/test_difficulty_schema_rows.py` (new)

**Interfaces:**
- Consumes: existing CSV/JSON loaders (which will start returning the 難度 rows after Task 3 extends `_CATEGORIES`).
- Produces: three researcher-editable data sources that Task 6/7/8 read to build `DIFFICULTY_INSTRUCTIONS`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_difficulty_schema_rows.py`:

```python
"""Data-file smoke tests: 難度 rows exist for every subject."""

from __future__ import annotations

import csv
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SS_CSV = REPO_ROOT / "data" / "social_studies" / "curriculum" / "schema_parameters.csv"
NS_CSV = REPO_ROOT / "data" / "natural_sciences" / "curriculum" / "schema_parameters.csv"
MATH_JSON = REPO_ROOT / "question_schemas.json"

_REQUIRED = {"easy", "medium", "hard"}


def _csv_values(path: Path, category: str) -> dict[str, str]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {
            row["value"]: row.get("instruction", "")
            for row in csv.DictReader(f)
            if row.get("類別") == category
        }


def test_social_studies_csv_has_difficulty_rows():
    values = _csv_values(SS_CSV, "難度")
    assert set(values) == _REQUIRED
    assert all(v.strip() for v in values.values()), (
        "SS 難度 rows must carry non-empty instructions"
    )


def test_natural_sciences_csv_has_difficulty_rows():
    values = _csv_values(NS_CSV, "難度")
    assert set(values) == _REQUIRED
    assert all(v.strip() for v in values.values())


def test_math_schemas_json_has_difficulty_category():
    data = json.loads(MATH_JSON.read_text(encoding="utf-8"))
    assert "難度" in data
    rows = data["難度"]
    assert {row["value"] for row in rows} == _REQUIRED
    assert all(row.get("instruction", "").strip() for row in rows), (
        "math 難度 entries must carry non-empty instructions"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_difficulty_schema_rows.py -x`
Expected: FAIL — `KeyError: '難度'` on the math test and empty-set assertion errors on the SS/NS tests.

- [ ] **Step 3: Append 難度 rows to `data/social_studies/curriculum/schema_parameters.csv`**

Append these three rows at the end of the file (keeping the existing quoting style — value + instruction quoted, no `parent` column):

```csv
"難度","easy","本題組整體難度為簡單。設計以直接擷取文本明示資訊為主：小題應對應文本中可直接找出的句子、事實、時間點、地點或人物；避免推論、跨段落整合或評鑑。用語與句式貼近學生日常閱讀理解水準。"
"難度","medium","本題組整體難度為中等。設計以單步推論、段內統整、簡單比較與因果解釋為主：小題可要求綜合同一段落或鄰近段落資訊，或依據文本推得未直接明示但邏輯可及的結論。避免多文本整合或高層次評鑑。"
"難度","hard","本題組整體難度為困難。設計以多步推論、跨段落／跨文本整合、觀點對比、證據評鑑、以及對文本形式或立場的省思為主。至少一小題應要求學生辨識文本立場、比較不同觀點、或整合多處證據作出評價。"
```

- [ ] **Step 4: Append 難度 rows to `data/natural_sciences/curriculum/schema_parameters.csv`**

Append these three rows at the end (trailing empty `parent` column to match the file's existing 4-column shape):

```csv
難度,easy,本題組整體難度為簡單。設計以再現科學知識、識別事實與名詞、讀取單一圖表為主的小題；避免要求解釋機制、比較實驗設計或整合多筆資料。用語直接、圖表資訊清楚可讀。,
難度,medium,本題組整體難度為中等。設計要求學生應用科學概念解釋單一現象、進行單步資料詮釋（如讀圖後計算或比較）、或連結一個實驗與一項變因。允許簡單推論與情境轉譯，但避免多資料整合與批判性論證。,
難度,hard,本題組整體難度為困難。設計要求學生評估實驗設計、辨識變因與控制、跨資料或跨圖表整合、對科學論點提出評鑑或反駁、或以科學證據支持社會生態決策。至少一小題應要求論證、批判或設計改良。,
```

- [ ] **Step 5: Append the `難度` category to `question_schemas.json`**

Add a new top-level `"難度"` key (as a sibling of `"question_style"`) with three `{value, instruction}` entries. Insert it directly before the closing `}` of the object (after `"question_style"`):

```json
  "難度": [
    {
      "value": "easy",
      "instruction": "本題整體難度為簡單。以單一概念、直接套用公式或定義為主；只需一步計算或一次觀察即可作答。誘答選項對應學生最常見的一種錯誤，避免多步推理。"
    },
    {
      "value": "medium",
      "instruction": "本題整體難度為中等。允許兩步驟解題、單一情境轉譯、或跨概念的一次連結；學生需要先理解情境再套用公式。誘答選項可對應學生常見的兩類誤解。"
    },
    {
      "value": "hard",
      "instruction": "本題整體難度為困難。以多步驟推理、跨單元整合、或非例行問題為主；可能需要建模、抽象化、逆向思考或多次代換。誘答選項可包含高階誤解或計算陷阱。"
    }
  ]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_difficulty_schema_rows.py -x`
Expected: PASS — 3 tests green.

- [ ] **Step 7: Commit**

```bash
git add data/social_studies/curriculum/schema_parameters.csv \
        data/natural_sciences/curriculum/schema_parameters.csv \
        question_schemas.json \
        tests/test_difficulty_schema_rows.py
git commit -m "feat(data): add 難度 rows (easy/medium/hard) to SS+NS CSVs and math JSON (#116)"
```

---

### Task 3: Wire 難度 through the three schema loaders

**Files:**
- Modify: `src/schema_loader.py` (`_CATEGORIES` tuple, line 13)
- Modify: `src/social_studies/schema_loader.py` (`_CATEGORIES` tuple, line 13)
- Modify: `src/natural_sciences/schema_loader.py` (`_CATEGORIES` tuple, lines 12–19)
- Test: `tests/test_difficulty_schema_loading.py` (new)

**Interfaces:**
- Consumes: the CSV/JSON rows added in Task 2.
- Produces: `build_instructions(schemas)["難度"]` returns `{"easy": ..., "medium": ..., "hard": ...}` for all three subjects. Task 6/7/8 will read these dicts to build `DIFFICULTY_INSTRUCTIONS`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_difficulty_schema_loading.py`:

```python
"""Schema loaders must expose the 難度 category via build_instructions()."""

from __future__ import annotations


def test_math_build_instructions_exposes_難度():
    from src.schema_loader import build_instructions, load_schemas
    instr = build_instructions(load_schemas())
    assert "難度" in instr
    assert set(instr["難度"]) == {"easy", "medium", "hard"}
    assert all(instr["難度"][k].strip() for k in ("easy", "medium", "hard"))


def test_social_studies_build_instructions_exposes_難度():
    from src.social_studies.schema_loader import build_instructions, load_schemas
    instr = build_instructions(load_schemas())
    assert "難度" in instr
    assert set(instr["難度"]) == {"easy", "medium", "hard"}


def test_natural_sciences_build_instructions_exposes_難度():
    from src.natural_sciences.schema_loader import build_instructions, load_schemas
    instr = build_instructions(load_schemas())
    assert "難度" in instr
    assert set(instr["難度"]) == {"easy", "medium", "hard"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_difficulty_schema_loading.py -x`
Expected: FAIL with `assert '難度' in instr` for all three — the current `_CATEGORIES` tuples filter 難度 out of `build_instructions`.

- [ ] **Step 3: Extend `_CATEGORIES` in `src/schema_loader.py`**

Change line 13:

```python
_CATEGORIES = ("情境", "題型種類", "題型", "數學思考", "question_style", "難度")
```

- [ ] **Step 4: Extend `_CATEGORIES` in `src/social_studies/schema_loader.py`**

Change line 13:

```python
_CATEGORIES = ("情境", "題型種類", "題型", "閱讀歷程", "文本形式", "科目", "題目內容類型", "難度")
```

- [ ] **Step 5: Extend `_CATEGORIES` in `src/natural_sciences/schema_loader.py`**

Replace the tuple at lines 12–19 with:

```python
_CATEGORIES = (
    "情境",
    "情境子類別",
    "題型種類",
    "題型",
    "科學能力",
    "題目內容類型",
    "難度",
)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_difficulty_schema_loading.py -x`
Expected: PASS — 3 tests green.

- [ ] **Step 7: Commit**

```bash
git add src/schema_loader.py src/social_studies/schema_loader.py src/natural_sciences/schema_loader.py \
        tests/test_difficulty_schema_loading.py
git commit -m "feat(schema): expose 難度 category through all three schema loaders (#116)"
```

---

### Task 4: Math schemas — SampledParams + QuestionMetadata carry difficulty

**Files:**
- Modify: `src/schemas.py` (`QuestionMetadata` around line 87–93; `SampledParams` around lines 117–138)
- Test: `tests/test_math_schemas_difficulty.py` (new)

**Interfaces:**
- Consumes: `Difficulty`, `DEFAULT_DIFFICULTY` from `src.common.difficulty` (Task 1).
- Produces:
  - `SampledParams.difficulty: Difficulty` field (default `Difficulty.medium`).
  - `QuestionMetadata.difficulty: Difficulty` field (default `Difficulty.medium`).
  - Read by Task 5 (sampler + CLI), Task 6 (prompt), Task 9 (corrector frozen field), Task 10 (verifier context).

- [ ] **Step 1: Write the failing test**

Create `tests/test_math_schemas_difficulty.py`:

```python
"""Math schemas must expose a difficulty field on SampledParams + QuestionMetadata."""

from __future__ import annotations


def test_sampled_params_difficulty_default_medium():
    from src.common.difficulty import Difficulty
    from src.schemas import SampledParams
    p = SampledParams(
        grade=8,
        情境=[],
        題型種類=next(iter(__import__("src.schemas", fromlist=["QuestionSetType"]).QuestionSetType)),
        題型=next(iter(__import__("src.schemas", fromlist=["QuestionType"]).QuestionType)),
        數學思考=[],
        學習內容=[],
        style=next(iter(__import__("src.schemas", fromlist=["QuestionStyle"]).QuestionStyle)),
    )
    assert p.difficulty is Difficulty.medium


def test_sampled_params_difficulty_accepts_all_three_values():
    from src.common.difficulty import Difficulty
    from src.schemas import QuestionSetType, QuestionStyle, QuestionType, SampledParams
    for value in ("easy", "medium", "hard"):
        p = SampledParams(
            grade=8,
            情境=[],
            題型種類=next(iter(QuestionSetType)),
            題型=next(iter(QuestionType)),
            數學思考=[],
            學習內容=[],
            style=next(iter(QuestionStyle)),
            difficulty=value,
        )
        assert p.difficulty is Difficulty(value)


def test_question_metadata_difficulty_default_medium():
    from src.common.difficulty import Difficulty
    from src.schemas import QuestionMetadata, QuestionStyle
    md = QuestionMetadata(grade=8, style=next(iter(QuestionStyle)), model="x")
    assert md.difficulty is Difficulty.medium
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_math_schemas_difficulty.py -x`
Expected: FAIL — `AttributeError` / Pydantic `ValidationError` because neither model has a `difficulty` field yet.

- [ ] **Step 3: Add the field to `src/schemas.py`**

Add the import at the top of the imports block (below the existing `from src.common...` line, around line 15):

```python
from src.common.difficulty import DEFAULT_DIFFICULTY, Difficulty
```

Modify `QuestionMetadata` (currently lines 87–93) to add `difficulty`:

```python
class QuestionMetadata(BaseModel):
    """Metadata about the generation process."""
    grade: int
    style: QuestionStyle  # type: ignore[valid-type]
    model: str
    generated_at: datetime = Field(default_factory=datetime.now)
    seed: int | None = None
    difficulty: Difficulty = DEFAULT_DIFFICULTY
```

Modify `SampledParams` (currently lines 117–138) to add `difficulty` after `subject_filter`:

```python
class SampledParams(BaseModel):
    """Parameters selected by the sampler for question generation."""
    grade: int

    @field_validator("grade")
    @classmethod
    def grade_must_be_allowed(cls, v: int) -> int:
        if v not in _GRADES:
            raise ValueError(f"grade must be one of {_GRADES}, got {v}")
        return v
    情境: list[QuestionContext]  # type: ignore[valid-type]
    題型種類: QuestionSetType  # type: ignore[valid-type]
    題型: QuestionType  # type: ignore[valid-type]
    數學思考: list[MathThinking]  # type: ignore[valid-type]
    學習內容: list[LearningContentItem]
    style: QuestionStyle  # type: ignore[valid-type]
    # Phase 3: curriculum-aware fields
    核心素養: list[str] = Field(default_factory=list)
    學習表現: list[LearningContentItem] = Field(default_factory=list)
    題目內容類型: str | None = None
    出題概念: str = ""
    subject_filter: str | None = None
    # Issue #116: explicit difficulty (pure passthrough — never randomized).
    difficulty: Difficulty = DEFAULT_DIFFICULTY
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_math_schemas_difficulty.py -x`
Expected: PASS — 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/schemas.py tests/test_math_schemas_difficulty.py
git commit -m "feat(math/schemas): add difficulty field to SampledParams + QuestionMetadata (#116)"
```

---

### Task 5: Math sampler + CLI — accept difficulty passthrough

**Files:**
- Modify: `src/sampler.py` (`sample_params` signature + body; lines 66–193)
- Modify: `src/cli.py` (`parse_args` around line 128, sample_params call around lines 526–539, `_parse_question` metadata assignment around lines 448–454, generate_with_corrections signature)
- Test: extend `tests/test_math_sampler.py` (new test functions appended)

**Interfaces:**
- Consumes: `Difficulty`, `resolve_difficulty` from `src.common.difficulty`; `SampledParams.difficulty` from Task 4.
- Produces:
  - `sample_params(..., difficulty: Difficulty | str | None = None) -> SampledParams` — `None` → medium; enum passthrough on returned `SampledParams`.
  - CLI flag `--difficulty {easy,medium,hard}` on `src.cli`.
  - `generate_one` / `generate_with_corrections` copy `params.difficulty` onto `QuestionMetadata.difficulty` when constructing the emitted `ExamQuestion`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_math_sampler.py`:

```python
def test_sample_params_difficulty_defaults_to_medium():
    from src.common.difficulty import Difficulty
    from src.sampler import sample_params

    p = sample_params(grade=8, seed=0)
    assert p.difficulty is Difficulty.medium


def test_sample_params_difficulty_passthrough_string():
    from src.common.difficulty import Difficulty
    from src.sampler import sample_params

    for v in ("easy", "medium", "hard"):
        p = sample_params(grade=8, seed=0, difficulty=v)
        assert p.difficulty is Difficulty(v)


def test_sample_params_difficulty_passthrough_enum():
    from src.common.difficulty import Difficulty
    from src.sampler import sample_params

    p = sample_params(grade=8, seed=0, difficulty=Difficulty.hard)
    assert p.difficulty is Difficulty.hard


def test_sample_params_difficulty_is_not_randomized():
    from src.common.difficulty import Difficulty
    from src.sampler import sample_params

    # Every seed must yield the caller-supplied difficulty verbatim.
    for seed in range(50):
        assert sample_params(grade=8, seed=seed).difficulty is Difficulty.medium
        assert sample_params(grade=8, seed=seed, difficulty="hard").difficulty is Difficulty.hard
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_math_sampler.py -x -k difficulty`
Expected: FAIL — `sample_params()` does not accept the `difficulty` keyword.

- [ ] **Step 3: Extend `src/sampler.py`**

Add near the top of the imports block (after the `from src.common.curriculum_loader ...` block):

```python
from src.common.difficulty import DEFAULT_DIFFICULTY, Difficulty, resolve_difficulty
```

Extend the `sample_params` signature — replace the current signature (lines 66–80) with:

```python
def sample_params(
    grade_content: dict[int, list[LearningContentItem]] | None = None,
    grade: int | None = None,
    style: list[QuestionStyle] | None = None,  # type: ignore[valid-type]
    context: list[QuestionContext] | None = None,  # type: ignore[valid-type]
    set_type: QuestionSetType | None = None,  # type: ignore[valid-type]
    q_type: list[QuestionType] | None = None,  # type: ignore[valid-type]
    seed: int | None = None,
    *,
    core_competency: list[CoreCompetency] | None = None,  # type: ignore[valid-type]
    learning_content: list[str] | None = None,
    learning_performance: list[str] | None = None,
    content_type: str | None = None,
    subject_filter: str | None = None,
    difficulty: Difficulty | str | None = None,
) -> SampledParams:
```

Resolve difficulty near the top of the function body — insert immediately after `rng = random.Random(seed)`:

```python
    resolved_difficulty: Difficulty = resolve_difficulty(difficulty)
```

Extend the final `return SampledParams(...)` call to include `difficulty=resolved_difficulty` (add as the last kwarg before the closing paren, around line 192):

```python
    return SampledParams(
        grade=selected_grade,
        情境=selected_context,
        題型種類=selected_set_type,
        題型=selected_q_type,
        數學思考=selected_thinking,
        學習內容=selected_content,
        style=selected_style,
        核心素養=selected_competency_values,
        學習表現=selected_performance,
        題目內容類型=selected_content_type,
        subject_filter=subject_filter,
        difficulty=resolved_difficulty,
    )
```

- [ ] **Step 4: Extend the CLI in `src/cli.py`**

Add the argparse flag inside `parse_args` — after the `--content-type` argument (around line 108) and before `--image-generation-mode`:

```python
    gen.add_argument(
        "--difficulty",
        type=str,
        choices=["easy", "medium", "hard"],
        default=None,
        help="題目難度（easy / medium / hard；預設 medium，純粹傳遞不參與隨機抽樣）",
    )
```

Thread the flag into `sample_params` — update the `params = sample_params(...)` call around lines 526–539 to include `difficulty=args.difficulty` as the last kwarg:

```python
            params = sample_params(
                grade_content=grade_content,
                grade=args.grade,
                style=style_override,
                context=context_override,
                set_type=set_type_override,
                q_type=q_type_override,
                seed=seed,
                core_competency=core_competency_override,
                learning_content=learning_content_override,
                learning_performance=learning_performance_override,
                content_type=content_type_override,
                subject_filter=subject_filter_override,
                difficulty=args.difficulty,
            )
```

Copy difficulty onto metadata — update the `QuestionMetadata(...)` block at the tail of `_parse_question` (currently lines 448–454) to:

```python
        metadata=QuestionMetadata(
            grade=params.grade,
            style=params.style,
            model=model,
            seed=None,
            difficulty=params.difficulty,
        ),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_math_sampler.py -x`
Expected: PASS — all existing sampler tests + the 4 new difficulty tests green.

- [ ] **Step 6: Commit**

```bash
git add src/sampler.py src/cli.py tests/test_math_sampler.py
git commit -m "feat(math): thread difficulty through sampler/CLI + record on metadata (#116)"
```

---

### Task 6: Math prompt — DIFFICULTY_INSTRUCTIONS and `## 難度要求` section

**Files:**
- Modify: `src/context_builder.py` (`build_user_prompt`; add `DIFFICULTY_INSTRUCTIONS` module constant near `CONTENT_TYPE_INSTRUCTIONS` around line 53–69; extend `USER_PROMPT_TEMPLATE` around line 142–178; extend `build_user_prompt` body around lines 231–387)
- Test: `tests/test_math_context_builder_difficulty.py` (new)

**Interfaces:**
- Consumes: `Difficulty` (Task 1), `SampledParams.difficulty` (Task 4), `build_instructions(schemas)["難度"]` (Task 3).
- Produces:
  - Module-level `DIFFICULTY_INSTRUCTIONS: dict[str, str]` built from the JSON at import time (`easy/medium/hard` → instruction).
  - Every user prompt from `build_user_prompt` now contains a `## 難度要求` section listing the resolved difficulty and its instruction.

- [ ] **Step 1: Write the failing test**

Create `tests/test_math_context_builder_difficulty.py`:

```python
"""Math prompt must inject a `## 難度要求` section per SampledParams.difficulty."""

from __future__ import annotations

import random
from pathlib import Path

from src.common.difficulty import Difficulty
from src.context_builder import DIFFICULTY_INSTRUCTIONS, build_user_prompt
from src.sampler import sample_params


def test_difficulty_instructions_cover_all_three_levels():
    assert set(DIFFICULTY_INSTRUCTIONS) == {"easy", "medium", "hard"}
    for level in ("easy", "medium", "hard"):
        assert DIFFICULTY_INSTRUCTIONS[level].strip(), f"missing math instruction for {level}"


def test_prompt_contains_difficulty_section_default_medium(tmp_path: Path):
    params = sample_params(grade=8, seed=1)
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "## 難度要求" in prompt
    assert "medium" in prompt
    assert DIFFICULTY_INSTRUCTIONS["medium"][:20] in prompt


def test_prompt_contains_difficulty_section_hard(tmp_path: Path):
    params = sample_params(grade=8, seed=1, difficulty="hard")
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "## 難度要求" in prompt
    assert "hard" in prompt
    assert DIFFICULTY_INSTRUCTIONS["hard"][:20] in prompt


def test_prompt_contains_difficulty_section_easy(tmp_path: Path):
    params = sample_params(grade=8, seed=1, difficulty=Difficulty.easy)
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "## 難度要求" in prompt
    assert "easy" in prompt
    assert DIFFICULTY_INSTRUCTIONS["easy"][:20] in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_math_context_builder_difficulty.py -x`
Expected: FAIL — `ImportError: cannot import name 'DIFFICULTY_INSTRUCTIONS' from 'src.context_builder'`.

- [ ] **Step 3: Extend `src/context_builder.py`**

Add module-level constant immediately after `CONTENT_TYPE_INSTRUCTIONS` (around line 69), reading from the loaded schemas at import time:

```python
DIFFICULTY_INSTRUCTIONS: dict[str, str] = _INSTRUCTIONS.get("難度", {})
```

Extend `USER_PROMPT_TEMPLATE` — replace the `- **題目內容類型**：{content_type}` line block with a new `## 難度要求` block inserted between `## 條件補充說明` and `## 題目風格`. Concretely, change the template so its `{param_instructions}` placeholder is followed by:

```python
{difficulty_section}
## 題目風格
```

And ensure `{difficulty_section}` expands via a helper in `build_user_prompt` (Step 4). The final template — from `## 條件補充說明` through `## 題目風格` — reads:

```python
{lp_pool_lines}{param_instructions}{difficulty_section}
## 題目風格
```

Extend `build_user_prompt` (in `src/context_builder.py`) — inside the function, after computing `param_instructions` and before `style_instruction` (around line 311), add:

```python
    # Difficulty is a pure passthrough; the resolved value lives on params.difficulty.
    difficulty_value = params.difficulty.value
    difficulty_instr = DIFFICULTY_INSTRUCTIONS.get(
        difficulty_value,
        "本題無指定難度說明；請以中等難度作為預設。",
    )
    difficulty_section = (
        f"\n## 難度要求\n\n"
        f"- **難度等級**：{difficulty_value}\n"
        f"- **命題指示**：{difficulty_instr}\n"
    )
```

Add `difficulty_section=difficulty_section` to the `USER_PROMPT_TEMPLATE.format(...)` call at the tail of `build_user_prompt` (around line 370).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_math_context_builder_difficulty.py -x`
Expected: PASS — 4 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/context_builder.py tests/test_math_context_builder_difficulty.py
git commit -m "feat(math/prompt): inject `## 難度要求` section from DIFFICULTY_INSTRUCTIONS (#116)"
```

---

### Task 7: Social studies — schemas, sampler, CLI, and metadata

**Files:**
- Modify: `src/social_studies/schemas.py` (`SampledParams` around lines 133–160; `QuestionMetadata` around lines 98–102)
- Modify: `src/social_studies/sampler.py` (`sample_params` signature at lines 46–61, body, and return at 176–192)
- Modify: `src/social_studies/cli.py` (argparse `--difficulty` after the `--content-type` block near line 149, `sample_params` call around lines 867–878; add `metadata=QuestionMetadata(...)` write-through in `_parse_text_shell` / question construction — locate the ExamQuestion factory used by `generate_one`)
- Test: `tests/test_social_studies_sampler_difficulty.py` (new)

**Interfaces:**
- Consumes: `Difficulty`, `DEFAULT_DIFFICULTY`, `resolve_difficulty` from `src.common.difficulty`.
- Produces: `SampledParams.difficulty`, `QuestionMetadata.difficulty`, and the CLI flag. Task 8 will consume `SampledParams.difficulty` in the prompt.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_social_studies_sampler_difficulty.py`:

```python
"""Social studies sampler difficulty passthrough."""

from __future__ import annotations

from src.common.difficulty import Difficulty
from src.social_studies.sampler import sample_params


def test_ss_sampler_difficulty_defaults_to_medium():
    p = sample_params(seed=1)
    assert p.difficulty is Difficulty.medium


def test_ss_sampler_difficulty_string_passthrough():
    for v in ("easy", "medium", "hard"):
        assert sample_params(seed=1, difficulty=v).difficulty is Difficulty(v)


def test_ss_sampler_difficulty_enum_passthrough():
    p = sample_params(seed=1, difficulty=Difficulty.hard)
    assert p.difficulty is Difficulty.hard


def test_ss_sampler_difficulty_not_randomized():
    for seed in range(50):
        assert sample_params(seed=seed).difficulty is Difficulty.medium
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_social_studies_sampler_difficulty.py -x`
Expected: FAIL — `sample_params()` does not accept `difficulty`.

- [ ] **Step 3: Extend `src/social_studies/schemas.py`**

Add at the top of the imports block (after the existing `from src.social_studies.schema_loader import ...` line):

```python
from src.common.difficulty import DEFAULT_DIFFICULTY, Difficulty
```

Add `difficulty: Difficulty = DEFAULT_DIFFICULTY` to `QuestionMetadata` (around line 98–102):

```python
class QuestionMetadata(BaseModel):
    grade: int
    model: str
    generated_at: datetime = Field(default_factory=datetime.now)
    seed: int | None = None
    difficulty: Difficulty = DEFAULT_DIFFICULTY
```

Add `difficulty: Difficulty = DEFAULT_DIFFICULTY` to `SampledParams` (append as the last field before the class ends, around line 160):

```python
    # Issue #116: explicit difficulty (pure passthrough — never randomized).
    difficulty: Difficulty = DEFAULT_DIFFICULTY
```

- [ ] **Step 4: Extend `src/social_studies/sampler.py`**

Add near the top imports:

```python
from src.common.difficulty import Difficulty, resolve_difficulty
```

Extend the signature (lines 46–61) — append `difficulty: Difficulty | str | None = None,` as the last kwarg:

```python
def sample_params(
    grade: int | None = None,
    context: list[QuestionContext] | None = None,
    set_type: QuestionSetType | None = None,
    q_type: list[QuestionType] | None = None,
    subject: list[QuestionSubject] | None = None,
    core_competency: list[CoreCompetency] | None = None,
    learning_content: list[str] | None = None,
    learning_performance: list[str] | None = None,
    content_type: str | None = None,
    seed: int | None = None,
    sub_question_count: int | None = None,
    question_word_limit: int | None = None,
    option_word_limit: int | None = None,
    subquestion_configs: list | None = None,
    difficulty: Difficulty | str | None = None,
) -> SampledParams:
```

Resolve near the top of the body — insert immediately after `rng = random.Random(seed)`:

```python
    resolved_difficulty: Difficulty = resolve_difficulty(difficulty)
```

Append `difficulty=resolved_difficulty,` to the `return SampledParams(...)` block (around lines 176–192) as the last kwarg.

- [ ] **Step 5: Extend `src/social_studies/cli.py`**

Add argparse flag inside `parse_args` — after the `--content-type` argument (line 149) and before `--count`:

```python
    gen.add_argument(
        "--difficulty",
        type=str,
        choices=["easy", "medium", "hard"],
        default=None,
        help="題組難度（easy / medium / hard；預設 medium，純粹傳遞不參與隨機抽樣）",
    )
```

Thread the flag into the `sample_params` call around lines 867–878:

```python
            params = sample_params(
                grade=args.grade,
                context=context_override,
                set_type=set_type_override,
                q_type=q_type_override,
                subject=subject_override,
                core_competency=core_competency_override,
                learning_content=learning_content_override,
                learning_performance=learning_performance_override,
                content_type=content_type_override,
                seed=seed,
                difficulty=args.difficulty,
            )
```

Locate the `ExamQuestion(...)` factory inside `src/social_studies/cli.py` that fills `metadata=QuestionMetadata(...)` (search for `QuestionMetadata(` — both `_parse_text_shell` and the assembled 題組 constructor must pass `difficulty=params.difficulty` when constructing `QuestionMetadata`, e.g.:

```python
        metadata=QuestionMetadata(
            grade=params.grade,
            model=model,
            seed=None,
            difficulty=params.difficulty,
        ),
```

Apply the same `difficulty=params.difficulty` addition to every `QuestionMetadata(...)` construction in the file.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_social_studies_sampler_difficulty.py -x`
Expected: PASS — 4 tests green.

- [ ] **Step 7: Commit**

```bash
git add src/social_studies/schemas.py src/social_studies/sampler.py src/social_studies/cli.py \
        tests/test_social_studies_sampler_difficulty.py
git commit -m "feat(social_studies): add difficulty passthrough on sampler/CLI/metadata (#116)"
```

---

### Task 8: Social studies — inject `## 難度要求` into text + subquestion prompts

**Files:**
- Modify: `src/social_studies/context_builder.py` (`DIFFICULTY_INSTRUCTIONS` constant near `CONTENT_TYPE_INSTRUCTIONS` at line 50; `_TEXT_GENERATION_USER_PROMPT_TEMPLATE` around lines 568–588; `build_text_generation_prompt` around lines 668–767; `_SUBQUESTION_USER_PROMPT_TEMPLATE` around lines 643–665; `build_subquestion_prompt` around lines 770–841; and the legacy `USER_PROMPT_TEMPLATE`/`build_user_prompt` around lines 200–233 + 277–526)
- Test: `tests/test_social_studies_context_builder_difficulty.py` (new)

**Interfaces:**
- Consumes: `SampledParams.difficulty` (Task 7); `build_instructions(schemas)["難度"]` (Task 3).
- Produces: every SS text-generator and subquestion-generator prompt contains a `## 難度要求` section keyed to the resolved difficulty. Task 9's corrector freezes the field; Task 10's verifier mentions it as context.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_social_studies_context_builder_difficulty.py`:

```python
"""SS text+subquestion prompts must inject `## 難度要求`."""

from __future__ import annotations

import random
from pathlib import Path

from src.common.difficulty import Difficulty
from src.social_studies.context_builder import (
    DIFFICULTY_INSTRUCTIONS,
    build_subquestion_user_prompt,
    build_text_user_prompt,
)
from src.social_studies.sampler import sample_params


def test_ss_difficulty_instructions_cover_all_three():
    assert set(DIFFICULTY_INSTRUCTIONS) == {"easy", "medium", "hard"}
    for level in ("easy", "medium", "hard"):
        assert DIFFICULTY_INSTRUCTIONS[level].strip()


def test_text_prompt_contains_difficulty_section_default_medium(tmp_path: Path):
    params = sample_params(seed=1)
    prompt, _ = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "## 難度要求" in prompt
    assert "medium" in prompt


def test_text_prompt_contains_difficulty_section_hard(tmp_path: Path):
    params = sample_params(seed=1, difficulty="hard")
    prompt, _ = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "## 難度要求" in prompt
    assert "hard" in prompt
    assert DIFFICULTY_INSTRUCTIONS["hard"][:20] in prompt


def test_subquestion_prompt_echoes_difficulty(tmp_path: Path):
    params = sample_params(seed=1, difficulty=Difficulty.easy)
    sq_plan = {"序號": 1, "題型": "選擇題", "出題概念": "測驗擷取訊息"}
    prompt, _ = build_subquestion_user_prompt(
        核心問題="核心",
        文本="文本內容",
        取材來源=["來源"],
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
    )
    assert "## 難度要求" in prompt
    assert "easy" in prompt
    assert DIFFICULTY_INSTRUCTIONS["easy"][:20] in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_social_studies_context_builder_difficulty.py -x`
Expected: FAIL — `ImportError: cannot import name 'DIFFICULTY_INSTRUCTIONS' from 'src.social_studies.context_builder'`.

- [ ] **Step 3: Add `DIFFICULTY_INSTRUCTIONS` and prompt injection to `src/social_studies/context_builder.py`**

Add the constant immediately after `CONTENT_TYPE_INSTRUCTIONS` (around line 70):

```python
DIFFICULTY_INSTRUCTIONS: dict[str, str] = _INSTRUCTIONS.get("難度", {})


def _difficulty_section(params: "SampledParams") -> str:
    """Return the shared `## 難度要求` block for text + subquestion prompts."""
    value = params.difficulty.value
    instr = DIFFICULTY_INSTRUCTIONS.get(
        value,
        "本題組無指定難度說明；請以中等難度作為預設。",
    )
    return (
        "\n## 難度要求\n\n"
        f"- **難度等級**：{value}\n"
        f"- **命題指示**：{instr}\n"
    )
```

Inject the block into `build_text_user_prompt` (around lines 882–922) — after `build_user_prompt(...)` returns `text, image_paths`, insert `difficulty_section = _difficulty_section(params)` and splice it in immediately before the trailing `## 參考範例` marker:

```python
    text = text.replace("\n## 參考範例\n", f"\n{_difficulty_section(params)}\n## 參考範例\n", 1)
```

Inject the block into the legacy `build_user_prompt` (around lines 277–526) — after `param_instructions` is computed and before `text = USER_PROMPT_TEMPLATE.format(...)`, add:

```python
    difficulty_section = _difficulty_section(params)
```

Change `USER_PROMPT_TEMPLATE` (around lines 200–233) so `{param_instructions}` is followed by `{difficulty_section}`:

```python
{lp_pool_lines}{subquestion_config_lines}{param_instructions}{difficulty_section}{user_materials}
```

Pass `difficulty_section=difficulty_section` into the `USER_PROMPT_TEMPLATE.format(...)` call.

Inject into `build_subquestion_user_prompt` (around lines 972–1116) — inside the f-string returned near the end, add a `## 難度要求` section before the trailing `## 參考範例`:

```python
    difficulty_section = _difficulty_section(params).lstrip("\n")
    return f"""\
請根據以下共用素材與小題規劃，生成一道108課綱社會領域素養導向小題：
...  # existing content
- **指定條件**
...
{lc_pool_lines}{lp_pool_lines}
{difficulty_section}
## 參考範例
...
""", all_image_paths
```

Concretely: locate the block starting at `## 指定條件` (line ~1098) and insert the `{difficulty_section}` immediately before `## 參考範例` in the f-string body.

Apply the same injection to `_SUBQUESTION_USER_PROMPT_TEMPLATE` (around lines 643–665) — the template is unused in the two-stage pipeline but retained for the corrector path; insert a `{difficulty_section}` placeholder before `## 重要提醒` and thread the value from `build_subquestion_prompt` (around lines 770–841) via a new local `difficulty_section=_difficulty_section(params)` passed into the `.format(...)` call.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_social_studies_context_builder_difficulty.py -x`
Expected: PASS — 4 tests green.

Also run the existing SS prompt tests to confirm they still pass:

Run: `uv run pytest tests/test_social_studies_context_builder.py -x`
Expected: PASS — no regressions.

- [ ] **Step 5: Commit**

```bash
git add src/social_studies/context_builder.py tests/test_social_studies_context_builder_difficulty.py
git commit -m "feat(social_studies/prompt): inject `## 難度要求` into text + subquestion prompts (#116)"
```

---

### Task 9: Natural sciences — schemas, sampler, CLI, and metadata

**Files:**
- Modify: `src/natural_sciences/schemas.py` (`QuestionMetadata` around lines 100–104; `SampledParams` around lines 132–156)
- Modify: `src/natural_sciences/sampler.py` (`sample_params` signature at lines 68–83; body; return at lines 202–216)
- Modify: `src/natural_sciences/cli.py` (argparse after `--content-type` around line 109; sample_params call around lines 668–679; `QuestionMetadata(...)` in `_parse_text_shell` around lines 345–349 and in `_parse_question` around lines 232–236)
- Test: `tests/test_natural_sciences_sampler_difficulty.py` (new)

**Interfaces:**
- Consumes: `Difficulty`, `DEFAULT_DIFFICULTY`, `resolve_difficulty` (Task 1).
- Produces: NS `SampledParams.difficulty`, `QuestionMetadata.difficulty`, and CLI flag. Consumed by Task 10's prompt.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_natural_sciences_sampler_difficulty.py`:

```python
"""Natural sciences sampler difficulty passthrough."""

from __future__ import annotations

from src.common.difficulty import Difficulty
from src.natural_sciences.sampler import sample_params


def test_ns_sampler_difficulty_defaults_to_medium():
    assert sample_params(seed=1).difficulty is Difficulty.medium


def test_ns_sampler_difficulty_string_passthrough():
    for v in ("easy", "medium", "hard"):
        assert sample_params(seed=1, difficulty=v).difficulty is Difficulty(v)


def test_ns_sampler_difficulty_enum_passthrough():
    assert sample_params(seed=1, difficulty=Difficulty.hard).difficulty is Difficulty.hard


def test_ns_sampler_difficulty_not_randomized():
    for seed in range(50):
        assert sample_params(seed=seed).difficulty is Difficulty.medium
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_natural_sciences_sampler_difficulty.py -x`
Expected: FAIL — `sample_params()` does not accept `difficulty`.

- [ ] **Step 3: Extend `src/natural_sciences/schemas.py`**

Add to imports:

```python
from src.common.difficulty import DEFAULT_DIFFICULTY, Difficulty
```

Update `QuestionMetadata`:

```python
class QuestionMetadata(BaseModel):
    grade: int
    model: str
    generated_at: datetime = Field(default_factory=datetime.now)
    seed: int | None = None
    difficulty: Difficulty = DEFAULT_DIFFICULTY
```

Append to `SampledParams` (last field):

```python
    # Issue #116: explicit difficulty (pure passthrough — never randomized).
    difficulty: Difficulty = DEFAULT_DIFFICULTY
```

- [ ] **Step 4: Extend `src/natural_sciences/sampler.py`**

Add to imports:

```python
from src.common.difficulty import Difficulty, resolve_difficulty
```

Extend the signature (lines 68–83) — append as last kwarg:

```python
    difficulty: Difficulty | str | None = None,
```

Resolve immediately after `rng = random.Random(seed)`:

```python
    resolved_difficulty: Difficulty = resolve_difficulty(difficulty)
```

Append to the final `return SampledParams(...)` call (around lines 202–216):

```python
        difficulty=resolved_difficulty,
```

- [ ] **Step 5: Extend `src/natural_sciences/cli.py`**

Add flag in `parse_args` — after `--content-type` (line 109):

```python
    gen.add_argument(
        "--difficulty",
        type=str,
        choices=["easy", "medium", "hard"],
        default=None,
        help="題組難度（easy / medium / hard；預設 medium，純粹傳遞不參與隨機抽樣）",
    )
```

Thread into `sample_params` (call around lines 668–679):

```python
            params = sample_params(
                grade=args.grade,
                context=context_override,
                sub_context=sub_context_override,
                set_type=set_type_override,
                q_type=q_type_override,
                science_competency=science_competency_override,
                learning_content=learning_content_override,
                learning_performance=learning_performance_override,
                content_type=content_type_override,
                seed=seed,
                difficulty=args.difficulty,
            )
```

Copy onto metadata — inside `_parse_text_shell` (lines 345–349) and `_parse_question` (lines 232–236), replace `QuestionMetadata(grade=params.grade, model=model, seed=None)` with:

```python
        metadata=QuestionMetadata(
            grade=params.grade,
            model=model,
            seed=None,
            difficulty=params.difficulty,
        ),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_natural_sciences_sampler_difficulty.py -x`
Expected: PASS — 4 tests green.

- [ ] **Step 7: Commit**

```bash
git add src/natural_sciences/schemas.py src/natural_sciences/sampler.py src/natural_sciences/cli.py \
        tests/test_natural_sciences_sampler_difficulty.py
git commit -m "feat(natural_sciences): add difficulty passthrough on sampler/CLI/metadata (#116)"
```

---

### Task 10: Natural sciences — inject `## 難度要求` into text + subquestion prompts

**Files:**
- Modify: `src/natural_sciences/context_builder.py` (add `DIFFICULTY_INSTRUCTIONS` + helper near `CONTENT_TYPE_INSTRUCTIONS`; splice `## 難度要求` into the text prompt built by `build_text_user_prompt` and the subquestion prompt built by `build_subquestion_user_prompt`)
- Test: `tests/test_natural_sciences_context_builder_difficulty.py` (new)

**Interfaces:**
- Consumes: `SampledParams.difficulty` (Task 9); `build_instructions(schemas)["難度"]` (Task 3).
- Produces: `## 難度要求` block in every NS text and subquestion prompt. Consumed by Task 11's corrector (frozen) and Task 12's verifier (context only).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_natural_sciences_context_builder_difficulty.py`:

```python
"""NS text + subquestion prompts must inject `## 難度要求`."""

from __future__ import annotations

import random
from pathlib import Path

from src.common.difficulty import Difficulty
from src.natural_sciences.context_builder import (
    DIFFICULTY_INSTRUCTIONS,
    build_subquestion_user_prompt,
    build_text_user_prompt,
)
from src.natural_sciences.sampler import sample_params


def test_ns_difficulty_instructions_cover_all_three():
    assert set(DIFFICULTY_INSTRUCTIONS) == {"easy", "medium", "hard"}
    for level in ("easy", "medium", "hard"):
        assert DIFFICULTY_INSTRUCTIONS[level].strip()


def test_ns_text_prompt_default_medium(tmp_path: Path):
    params = sample_params(seed=1)
    prompt, _ = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "## 難度要求" in prompt
    assert "medium" in prompt


def test_ns_text_prompt_hard(tmp_path: Path):
    params = sample_params(seed=1, difficulty="hard")
    prompt, _ = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "## 難度要求" in prompt
    assert "hard" in prompt
    assert DIFFICULTY_INSTRUCTIONS["hard"][:20] in prompt


def test_ns_subquestion_prompt_echoes_difficulty(tmp_path: Path):
    params = sample_params(seed=1, difficulty=Difficulty.easy)
    sq_plan = {"序號": 1, "題型": "Simple-multiple-choice", "出題概念": "回憶科學知識"}
    prompt, _ = build_subquestion_user_prompt(
        核心問題="核心",
        文本="文本內容",
        取材來源=["來源"],
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
    )
    assert "## 難度要求" in prompt
    assert "easy" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_natural_sciences_context_builder_difficulty.py -x`
Expected: FAIL — `ImportError: cannot import name 'DIFFICULTY_INSTRUCTIONS' from 'src.natural_sciences.context_builder'`.

- [ ] **Step 3: Extend `src/natural_sciences/context_builder.py`**

Add near the top (after `_INSTRUCTIONS` is built):

```python
DIFFICULTY_INSTRUCTIONS: dict[str, str] = _INSTRUCTIONS.get("難度", {})


def _difficulty_section(params: "SampledParams") -> str:
    value = params.difficulty.value
    instr = DIFFICULTY_INSTRUCTIONS.get(
        value,
        "本題組無指定難度說明；請以中等難度作為預設。",
    )
    return (
        "\n## 難度要求\n\n"
        f"- **難度等級**：{value}\n"
        f"- **命題指示**：{instr}\n"
    )
```

Splice the section into `build_text_user_prompt` — locate the return path that composes the final text (search for the `## 參考範例` marker in the assembled prompt) and insert the section immediately before `## 參考範例`, mirroring the SS pattern:

```python
    text = text.replace("\n## 參考範例\n", f"\n{_difficulty_section(params)}\n## 參考範例\n", 1)
```

Splice into `build_subquestion_user_prompt` — inside the returned f-string, insert `{_difficulty_section(params)}` immediately before the trailing `## 參考範例` block (the exact anchor mirrors the SS builder at `src/natural_sciences/context_builder.py`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_natural_sciences_context_builder_difficulty.py -x`
Expected: PASS — 4 tests green.

Also run the existing NS prompt tests:

Run: `uv run pytest tests/test_natural_sciences_context_builder.py -x`
Expected: PASS — no regressions.

- [ ] **Step 5: Commit**

```bash
git add src/natural_sciences/context_builder.py tests/test_natural_sciences_context_builder_difficulty.py
git commit -m "feat(natural_sciences/prompt): inject `## 難度要求` into text + subquestion prompts (#116)"
```

---

### Task 11: Freeze difficulty in every corrector

**Files:**
- Modify: `src/corrector.py` (`_CORRECTION_SYSTEM_PROMPT_CORE` around lines 20–34; `correct_question` frozen-field restore around lines 118–137)
- Modify: `src/social_studies/corrector.py` (`_CORRECTION_SYSTEM_PROMPT_CORE` around lines 13–28; `correct_question` around lines 51–167)
- Modify: `src/natural_sciences/corrector.py` (`_CORRECTION_SYSTEM_PROMPT_CORE` around lines 18–32; `correct_question` around lines 55–167)
- Test: `tests/test_correctors_freeze_difficulty.py` (new)

**Interfaces:**
- Consumes: `ExamQuestion.metadata.difficulty` (Tasks 5, 7, 9).
- Produces: guarantee that a corrector pass never mutates `metadata.difficulty` even if the LLM output tries to.

- [ ] **Step 1: Write the failing test**

Create `tests/test_correctors_freeze_difficulty.py`:

```python
"""Correctors must restore metadata.difficulty from the original question."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.common.difficulty import Difficulty


def test_math_corrector_freezes_difficulty(monkeypatch):
    from src.corrector import correct_question
    from src.schemas import (
        ExamQuestion,
        LearningContentItem,
        QuestionMetadata,
        QuestionSetType,
        QuestionStyle,
        QuestionType,
        VerificationResult,
    )

    q = ExamQuestion(
        id="q1",
        情境=[],
        題型種類=next(iter(QuestionSetType)),
        題型=next(iter(QuestionType)),
        數學思考=[],
        學習內容=[LearningContentItem(編碼="N-7-1", 說明="")],
        題目=["a"],
        正確解題分析=["b"],
        metadata=QuestionMetadata(
            grade=8, style=next(iter(QuestionStyle)), model="m", difficulty=Difficulty.hard
        ),
    )
    verification = VerificationResult(passed=False, answer_match=False, details="wrong")

    client = MagicMock()
    # Simulate LLM trying to change difficulty by returning metadata.difficulty=easy
    client.generate_json.return_value = {
        "題目": ["fixed"],
        "正確解題分析": ["fixed"],
        "metadata": {"difficulty": "easy"},
    }

    fixed = correct_question(client, q, verification)
    assert fixed.metadata.difficulty is Difficulty.hard


def test_social_studies_corrector_freezes_difficulty():
    from src.social_studies.corrector import correct_question
    from src.social_studies.schemas import (
        ExamQuestion,
        QuestionMetadata,
        QuestionSetType,
        QuestionSubject,
        QuestionType,
        ReadingProcess,
        TextForm,
        VerificationResult,
    )

    q = ExamQuestion(
        id="ss1",
        subquestions=[],
        情境=[],
        題型種類=next(iter(QuestionSetType)),
        題型=next(iter(QuestionType)),
        閱讀歷程=[],
        文本形式=next(iter(TextForm)),
        metadata=QuestionMetadata(grade=8, model="m", difficulty=Difficulty.easy),
    )
    verification = VerificationResult(passed=False, answer_match=False, details="wrong")

    client = MagicMock()
    client.generate_json.return_value = {"metadata": {"difficulty": "hard"}}

    fixed = correct_question(client, q, verification)
    assert fixed.metadata.difficulty is Difficulty.easy


def test_natural_sciences_corrector_freezes_difficulty():
    from src.natural_sciences.corrector import correct_question
    from src.natural_sciences.schemas import (
        ExamQuestion,
        QuestionMetadata,
        QuestionSetType,
        QuestionSubContext,
        QuestionType,
        VerificationResult,
    )

    q = ExamQuestion(
        id="ns1",
        subquestions=[],
        情境=[],
        情境子類別=next(iter(QuestionSubContext)),
        題型種類=next(iter(QuestionSetType)),
        題型=next(iter(QuestionType)),
        metadata=QuestionMetadata(grade=8, model="m", difficulty=Difficulty.hard),
    )
    verification = VerificationResult(passed=False, answer_match=False, details="wrong")

    client = MagicMock()
    client.generate_json.return_value = {"metadata": {"difficulty": "easy"}}

    fixed = correct_question(client, q, verification)
    assert fixed.metadata.difficulty is Difficulty.hard
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_correctors_freeze_difficulty.py -x`
Expected: FAIL — the correctors accept the LLM `metadata.difficulty` override (or the assertion sees the wrong value because `model_copy(update=...)` doesn't guard `metadata`).

- [ ] **Step 3: Extend `src/corrector.py`**

Update the frozen-list wording in `_CORRECTION_SYSTEM_PROMPT_CORE` (around line 31) — replace the `絕對不可修改` bullet with:

```python
- 絕對不可修改：情境、題型種類、題型、數學思考、學習內容、學習表現、核心素養、出題概念、題目內容類型、難度、id、metadata。
```

Enforce it in code — inside `correct_question`, after the `update: dict = {}` block and before `return question.model_copy(update=update)`, forbid a caller-emitted metadata override:

```python
    # Difficulty is frozen — force the original metadata (and thus difficulty) through.
    update["metadata"] = question.metadata
```

- [ ] **Step 4: Extend `src/social_studies/corrector.py`**

Update the frozen-list wording (around line 25):

```python
- 絕對不可修改：核心問題、情境、題型種類、題型、閱讀歷程、文本形式、難度、id、metadata、
  各小題的 學習內容/學習表現/核心素養/出題概念/出題指示/科目/年級。
```

Enforce in code — add before `return question.model_copy(update=update)`:

```python
    update["metadata"] = question.metadata
```

- [ ] **Step 5: Extend `src/natural_sciences/corrector.py`**

Update the frozen-list wording (around line 28):

```python
- 絕對不可修改：核心問題、情境、情境子類別、題型種類、題型、科學能力、難度、id、metadata，
  以及各小題的 學習內容/學習表現/科學能力/出題概念/科目/年級。
```

Enforce in code — add before `return question.model_copy(update=update)`:

```python
    update["metadata"] = question.metadata
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_correctors_freeze_difficulty.py -x`
Expected: PASS — 3 tests green.

Also run:

Run: `uv run pytest tests/test_social_studies_corrector.py -x`
Expected: PASS — no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/corrector.py src/social_studies/corrector.py src/natural_sciences/corrector.py \
        tests/test_correctors_freeze_difficulty.py
git commit -m "feat(corrector): freeze difficulty across all three subject correctors (#116)"
```

---

### Task 12: Verifier mentions difficulty as context (no fail on mismatch)

**Files:**
- Modify: `src/verifier.py` (`VERIFICATION_USER_TEMPLATE` around lines 59–69; `verify_question` around lines 72–97)
- Modify: `src/social_studies/verifier.py` (`VERIFICATION_USER_TEMPLATE` around lines 57–75; `verify_question` around lines 99–150)
- Modify: `src/natural_sciences/verifier.py` (`VERIFICATION_USER_TEMPLATE`; `verify_question`)
- Test: `tests/test_verifiers_mention_difficulty.py` (new)

**Interfaces:**
- Consumes: `ExamQuestion.metadata.difficulty` (Tasks 5, 7, 9).
- Produces: verifier user prompts include a `難度（僅供參考，不得作為 pass/fail 判準）` line. `passed` decisions remain based only on the existing stances (math strict; SS/NS lenient).

- [ ] **Step 1: Write the failing test**

Create `tests/test_verifiers_mention_difficulty.py`:

```python
"""Verifier prompts must include a difficulty context line."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.common.difficulty import Difficulty


def _capture_prompt(monkeypatch, module):
    captured: dict = {}

    def fake_generate_with_image(system, user_prompt, image_path=None, purpose="verify"):
        captured["system"] = system
        captured["user"] = user_prompt
        return '{"passed": true, "answer_match": true, "details": "ok"}'

    client = MagicMock()
    client.generate_with_image = fake_generate_with_image
    return client, captured


def test_math_verifier_mentions_difficulty(monkeypatch):
    from src import verifier as mod
    from src.schemas import (
        ExamQuestion,
        LearningContentItem,
        QuestionMetadata,
        QuestionSetType,
        QuestionStyle,
        QuestionType,
    )
    client, captured = _capture_prompt(monkeypatch, mod)
    q = ExamQuestion(
        id="q",
        情境=[],
        題型種類=next(iter(QuestionSetType)),
        題型=next(iter(QuestionType)),
        數學思考=[],
        學習內容=[LearningContentItem(編碼="N-7-1", 說明="")],
        題目=["a"],
        正確解題分析=["b"],
        metadata=QuestionMetadata(
            grade=8, style=next(iter(QuestionStyle)), model="m", difficulty=Difficulty.hard,
        ),
    )
    mod.verify_question(client, q)
    assert "難度" in captured["user"]
    assert "hard" in captured["user"]
    assert "僅供參考" in captured["user"]


def test_social_studies_verifier_mentions_difficulty(monkeypatch):
    from src.social_studies import verifier as mod
    from src.social_studies.schemas import (
        ExamQuestion,
        QuestionMetadata,
        QuestionSetType,
        QuestionType,
        TextForm,
    )
    client, captured = _capture_prompt(monkeypatch, mod)
    q = ExamQuestion(
        id="ss",
        subquestions=[],
        情境=[],
        題型種類=next(iter(QuestionSetType)),
        題型=next(iter(QuestionType)),
        閱讀歷程=[],
        文本形式=next(iter(TextForm)),
        metadata=QuestionMetadata(grade=8, model="m", difficulty=Difficulty.easy),
    )
    mod.verify_question(client, q)
    assert "難度" in captured["user"]
    assert "easy" in captured["user"]
    assert "僅供參考" in captured["user"]


def test_natural_sciences_verifier_mentions_difficulty(monkeypatch):
    from src.natural_sciences import verifier as mod
    from src.natural_sciences.schemas import (
        ExamQuestion,
        QuestionMetadata,
        QuestionSetType,
        QuestionSubContext,
        QuestionType,
    )
    client, captured = _capture_prompt(monkeypatch, mod)
    q = ExamQuestion(
        id="ns",
        subquestions=[],
        情境=[],
        情境子類別=next(iter(QuestionSubContext)),
        題型種類=next(iter(QuestionSetType)),
        題型=next(iter(QuestionType)),
        metadata=QuestionMetadata(grade=8, model="m", difficulty=Difficulty.medium),
    )
    mod.verify_question(client, q)
    assert "難度" in captured["user"]
    assert "medium" in captured["user"]
    assert "僅供參考" in captured["user"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_verifiers_mention_difficulty.py -x`
Expected: FAIL — the current verifier prompts contain no `難度` line.

- [ ] **Step 3: Extend `src/verifier.py`**

Update `VERIFICATION_USER_TEMPLATE` to accept a `{difficulty_line}` placeholder immediately after the `## 提供的解題分析` block:

```python
VERIFICATION_USER_TEMPLATE = """\
請審核以下考試題目：

## 題目

{question_text}

## 提供的解題分析

{solution_text}
{difficulty_line}"""
```

In `verify_question`, compute the line from `question.metadata`:

```python
    difficulty_value = (
        question.metadata.difficulty.value if question.metadata is not None else "medium"
    )
    difficulty_line = (
        f"\n## 難度（僅供參考，不得作為 pass/fail 判準）\n\n"
        f"命題者要求的難度：{difficulty_value}\n"
    )
```

Pass `difficulty_line=difficulty_line` into `VERIFICATION_USER_TEMPLATE.format(...)`.

- [ ] **Step 4: Extend `src/social_studies/verifier.py`**

Apply the same pattern — extend `VERIFICATION_USER_TEMPLATE` (lines 57–75) with a `{difficulty_line}` after `## 提供的解題分析`, and populate it inside `verify_question` (lines 99–150) from `question.metadata.difficulty`.

- [ ] **Step 5: Extend `src/natural_sciences/verifier.py`**

Apply the same pattern — add the `{difficulty_line}` placeholder to the NS `VERIFICATION_USER_TEMPLATE` and populate it inside `verify_question` from `question.metadata.difficulty`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_verifiers_mention_difficulty.py -x`
Expected: PASS — 3 tests green.

Also run:

Run: `uv run pytest tests/test_social_studies_verifier.py -x`
Expected: PASS — no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/verifier.py src/social_studies/verifier.py src/natural_sciences/verifier.py \
        tests/test_verifiers_mention_difficulty.py
git commit -m "feat(verifier): mention requested difficulty as context in all three verifiers (#116)"
```

---

### Task 13: API `GenerateParams.difficulty` + `GET /api/generate` query param + service thread-through

**Files:**
- Modify: `server/generate/models.py` (`GenerateParams` around lines 12–50)
- Modify: `server/generate/routes.py` (`generate_endpoint` signature + `GenerateParams(...)` construction, lines 42–110)
- Modify: `server/generate/service.py` (`worker_one` — thread `difficulty` into all three `sample_params` calls at lines 255–344)
- Test: append to `tests/server/test_generate_routes.py`

**Interfaces:**
- Consumes: `Difficulty` values (`easy` / `medium` / `hard`).
- Produces: `GenerateParams.difficulty: Literal["easy","medium","hard"] | None = None`; the `GET /api/generate` endpoint accepts `difficulty` and rejects unknown values with HTTP 422; `service.worker_one` forwards `params.difficulty` to whichever subject's `sample_params(...)` is invoked.

- [ ] **Step 1: Write the failing tests**

Append to `tests/server/test_generate_routes.py`:

```python
def test_generate_route_accepts_difficulty_query_param() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    config = ServerConfig(api_key="x", jwt_secret="test-secret")
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as session:
            session.add(User(id=user_id, email="u@example.com"))
            await session.commit()

    asyncio.run(add_user())

    from server.generate import routes as gen_routes

    captured = {}

    async def fake_stream(params, *_args):
        captured["params"] = params
        yield {"event": "done", "data": ""}

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()

    original = gen_routes.generate_question_stream
    gen_routes.generate_question_stream = fake_stream  # type: ignore[assignment]
    try:
        token = create_jwt(user_id, "u@example.com", config=config)
        with TestClient(app) as client:
            ok = client.get(
                "/api/generate?subject=math&difficulty=hard",
                headers={"Authorization": f"Bearer {token}"},
            )
            bad = client.get(
                "/api/generate?subject=math&difficulty=insane",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())

    assert ok.status_code == 200
    assert captured["params"].difficulty == "hard"
    assert bad.status_code == 422


def test_generate_params_difficulty_defaults_to_none():
    from server.generate.models import GenerateParams
    assert GenerateParams(subject="math").difficulty is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/server/test_generate_routes.py::test_generate_route_accepts_difficulty_query_param tests/server/test_generate_routes.py::test_generate_params_difficulty_defaults_to_none -x`
Expected: FAIL — `GenerateParams` has no `difficulty` field; the endpoint returns 200 (or ignores) instead of 422 for invalid.

- [ ] **Step 3: Extend `server/generate/models.py`**

Add the field to `GenerateParams` — insert directly after `image_generation_mode` (around line 30):

```python
    difficulty: Literal["easy", "medium", "hard"] | None = None
```

- [ ] **Step 4: Extend `server/generate/routes.py`**

Add the query parameter to `generate_endpoint` (immediately after `image_generation_mode` around line 56):

```python
    difficulty: Literal["easy", "medium", "hard"] | None = Query(default=None),
```

Ensure `Literal` is imported at the top of the file:

```python
from typing import Any, Literal
```

Pass it into the `GenerateParams(...)` construction (around lines 82–110):

```python
        difficulty=difficulty,
```

- [ ] **Step 5: Extend `server/generate/service.py`**

Add `difficulty=params.difficulty,` to each of the three `sample_params(...)` calls in `worker_one`:

1. `ss_sample_params(...)` around lines 255–270 — append as last kwarg.
2. `ns_sample_params(...)` around lines 290–307 — append as last kwarg.
3. `math_sample_params(...)` around lines 331–344 — append as last kwarg.

Each block becomes, e.g. for math:

```python
                rng_params = math_sample_params(
                    grade_content=grade_content,
                    grade=params.grade,
                    style=style_override,
                    context=context_override,
                    set_type=set_type_override,
                    q_type=q_type_override,
                    seed=seed,
                    core_competency=params.core_competency,
                    learning_content=params.learning_content,
                    learning_performance=params.learning_performance,
                    content_type=params.content_type,
                    subject_filter=math_subject_filter,
                    difficulty=params.difficulty,
                )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/server/test_generate_routes.py -x`
Expected: PASS — new tests green; existing route tests still pass.

- [ ] **Step 7: Commit**

```bash
git add server/generate/models.py server/generate/routes.py server/generate/service.py \
        tests/server/test_generate_routes.py
git commit -m "feat(api): accept `difficulty` query param on GET /api/generate for all subjects (#116)"
```

---

### Task 14: Frontend — 難度 dropdown, i18n, useGenerate query string, vitest

**Files:**
- Modify: `web/package.json` (restore test tooling — see Pre-existing defect)
- Modify: `web/src/i18n/messages.ts` (add `form.difficulty*` + `form.confirm_difficulty` keys in both language blocks)
- Modify: `web/src/hooks/useGenerate.ts` (extend `GenerateParams` at lines 8–34; extend `buildQueryString` at lines 167–199)
- Modify: `web/src/components/ParamForm.tsx` (extend `GenerateParams` interface at lines 19–42; add `difficulty` state near lines 188–213; render dropdown after the 年級 block near line 677; include in `pendingParams` at lines 424–457; include in confirm rows at line 481–508; reset in the schema-load `useEffect` at lines 217–269)
- Test: `web/src/components/ParamForm.test.tsx` (new)

**Interfaces:**
- Consumes: `Difficulty` values `easy`, `medium`, `hard`; the `difficulty` query param accepted by Task 13.
- Produces: a 難度 dropdown in `ParamForm.tsx` that sends `difficulty=<value>` on `GET /api/generate` **only** when the user picked a non-default option.

- [ ] **Step 1: Restore the vitest tooling (fixes the pre-existing defect noted above)**

```bash
cd /workspace/exam-generation/web
npm install -D vitest @vitest/ui jsdom @testing-library/jest-dom @testing-library/react @testing-library/user-event
```

Then edit `web/package.json` — after the `"preview": "vite preview"` line, add the two scripts (matching commit `4b09f45`):

```json
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
```

Run once to confirm the existing suite passes:

```bash
cd /workspace/exam-generation/web && npm test
```

Expected: PASS — 2 test files (`QuestionCard.test.tsx`, `CoreQuestionPicker.test.tsx`).

- [ ] **Step 2: Add i18n keys**

In `web/src/i18n/messages.ts`, add to the `"en-US"` block directly after `"form.grade": "Grade",` (around line 41):

```ts
    "form.difficulty": "Difficulty",
    "form.difficulty_default": "Default (medium)",
    "form.difficulty_easy": "Easy",
    "form.difficulty_medium": "Medium",
    "form.difficulty_hard": "Hard",
```

And directly after `"form.confirm_grade": "Grade",` (around line 82):

```ts
    "form.confirm_difficulty": "Difficulty",
```

Mirror both additions in the `"zh-TW"` block — after `"form.grade": "年級",` (around line 204):

```ts
    "form.difficulty": "難度",
    "form.difficulty_default": "預設（中等）",
    "form.difficulty_easy": "簡單",
    "form.difficulty_medium": "中等",
    "form.difficulty_hard": "困難",
```

And after `"form.confirm_grade": "年級",` (around line 245):

```ts
    "form.confirm_difficulty": "難度",
```

- [ ] **Step 3: Extend `web/src/hooks/useGenerate.ts`**

Add to `GenerateParams` (around lines 8–34) — after `image_generation_mode`:

```ts
  difficulty?: "easy" | "medium" | "hard";
```

Add to `buildQueryString` (around lines 167–199) — before the closing `return qs.toString();`:

```ts
  if (params.difficulty !== undefined) qs.append("difficulty", params.difficulty);
```

- [ ] **Step 4: Write the failing test**

Create `web/src/components/ParamForm.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

vi.mock("../api/client", () => ({
  getSchemas: () =>
    Promise.resolve({
      學習階段: "第四學習階段",
      grades: [7, 8, 9],
      情境: [{ value: "個人", instruction: "" }],
      題型種類: [{ value: "單一題", instruction: "" }],
      題型: [{ value: "選擇題", instruction: "" }],
      數學思考: [{ value: "形成", instruction: "" }],
      question_style: [{ value: "text_only", instruction: "" }],
      題目內容類型: [{ value: "純文字", instruction: "" }],
    }),
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

import ParamForm from "./ParamForm";

describe("ParamForm difficulty dropdown", () => {
  beforeEach(() => vi.clearAllMocks());

  it("does not send `difficulty` when left at the default option", async () => {
    const onSubmit = vi.fn();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);

    // Wait for schemas to load
    await screen.findByRole("button", { name: /generate/i });

    fireEvent.click(screen.getByRole("button", { name: /generate/i }));
    // Confirm dialog opens; click confirm.
    fireEvent.click(await screen.findByRole("button", { name: /confirm/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const [payload] = onSubmit.mock.calls[0];
    expect(payload.difficulty).toBeUndefined();
  });

  it("sends `difficulty` when the user picks hard", async () => {
    const onSubmit = vi.fn();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);
    await screen.findByRole("button", { name: /generate/i });

    const select = screen.getByLabelText(/difficulty/i) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "hard" } });

    fireEvent.click(screen.getByRole("button", { name: /generate/i }));
    fireEvent.click(await screen.findByRole("button", { name: /confirm/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const [payload] = onSubmit.mock.calls[0];
    expect(payload.difficulty).toBe("hard");
  });
});
```

Run: `cd /workspace/exam-generation/web && npm test -- src/components/ParamForm.test.tsx`
Expected: FAIL — the dropdown does not exist and `difficulty` is not in the submitted payload.

- [ ] **Step 5: Extend `web/src/components/ParamForm.tsx`**

Add to the `GenerateParams` interface (lines 19–42) after `image_generation_mode`:

```ts
  difficulty?: "easy" | "medium" | "hard";
```

Add state near lines 188–213 (after `imageGenerationMode`):

```ts
  const [difficulty, setDifficulty] = useState<"" | "easy" | "medium" | "hard">("");
```

Reset it in the schema-load `useEffect` at lines 217–269 (near `setImageGenerationMode("html");`):

```ts
    setDifficulty("");
```

Render the dropdown — inside the JSX, immediately after the closing `</div>` of the 年級 block (line 677) and before the `科目` block:

```tsx
      <div>
        <label htmlFor="difficulty" className="block text-sm font-medium">
          {t("form.difficulty")}
        </label>
        <select
          id="difficulty"
          value={difficulty}
          onChange={(e) => setDifficulty(e.target.value as "" | "easy" | "medium" | "hard")}
          className="mt-1 block w-full border rounded px-2 py-1"
        >
          <option value="">{t("form.difficulty_default")}</option>
          <option value="easy">{t("form.difficulty_easy")}</option>
          <option value="medium">{t("form.difficulty_medium")}</option>
          <option value="hard">{t("form.difficulty_hard")}</option>
        </select>
      </div>
```

Include it in `pendingParams` inside `setPendingParams(...)` at lines 424–457:

```ts
      difficulty: difficulty === "" ? undefined : difficulty,
```

Add a confirm-row entry — inside the `rows` array around lines 481–508, after the `form.confirm_grade` entry, insert:

```ts
      { label: t("form.confirm_difficulty"), value: p.difficulty },
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /workspace/exam-generation/web && npm test -- src/components/ParamForm.test.tsx`
Expected: PASS — 2 tests green.

Also run the full suite plus type check + lint:

Run: `cd /workspace/exam-generation/web && npm test && npm run lint && npm run build`
Expected: all tests pass, no lint errors, `tsc -b && vite build` succeeds.

- [ ] **Step 7: Commit**

```bash
cd /workspace/exam-generation
git add web/package.json web/package-lock.json \
        web/src/i18n/messages.ts \
        web/src/hooks/useGenerate.ts \
        web/src/components/ParamForm.tsx \
        web/src/components/ParamForm.test.tsx
git commit -m "feat(web): add 難度 dropdown wired to GET /api/generate?difficulty=... (#116)"
```

---

### Task 15: End-to-end smoke — CLI + full pytest sweep

**Files:** none (verification only).

**Interfaces:**
- Consumes: everything above.
- Produces: confirmation that a `--difficulty` CLI run emits a question whose `metadata.difficulty` matches, and that the whole Python suite is green.

- [ ] **Step 1: Run the full Python test suite**

Run: `uv run pytest`
Expected: PASS — all pre-existing tests plus the seven new test files added in Tasks 1–12 green.

- [ ] **Step 2: Dry-run each CLI to confirm the flag flows through**

```bash
uv run python -m src.cli generate --dry-run --grade 8 --difficulty hard \
    | grep -F "## 難度要求" \
    | head -n 3
uv run python -m src.social_studies.cli generate --dry-run --grade 8 --difficulty easy \
    | grep -F "## 難度要求" \
    | head -n 3
uv run python -m src.natural_sciences.cli generate --dry-run --grade 8 --difficulty medium \
    | grep -F "## 難度要求" \
    | head -n 3
```

Expected: each command prints at least one line containing `## 難度要求`, confirming the section reaches the emitted prompt for that subject/level.

- [ ] **Step 3: Web smoke (optional, requires running dev server)**

```bash
cd /workspace/exam-generation/web && npm run dev
```

In the browser: pick 難度 = 困難, submit, and confirm the network request contains `difficulty=hard`. Pick 難度 = 預設（中等） and confirm no `difficulty` query key is present in the outgoing URL.

- [ ] **Step 4: Commit (docs-only if any noise fell out)**

If Steps 1–3 revealed no code changes, no commit is required — this task is a verification gate.
