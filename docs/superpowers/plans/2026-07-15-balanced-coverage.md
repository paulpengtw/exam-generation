# Balanced Batch Coverage (題型/學習內容) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For social-studies batch generation (`count > 1`), pre-plan a balanced 題型 assignment across the batch (and stratify 學習內容 draws), so a batch of N questions covers distinct 題型/學習內容 codes instead of Spotify-shuffle clustering. Default the new `coverage_mode` to `balanced`; keep `random` mode available.

**Architecture:** New standalone `src/batch_sampler.py::BatchSampler` pre-plans a length-`count` 題型 assignment (round-robin over a shuffled pool, then order-shuffled) and a stratified 學習內容 draw sequence. `src/social_studies/sampler.py::sample_params` grows two new kwargs (`assigned_q_type`, `assigned_learning_content`) that override the random draw when supplied. `server/generate/service.py` instantiates one `BatchSampler` per SS request when `count > 1` and `coverage_mode == "balanced"`, and stamps the effective mode onto `QuestionMetadata.coverage_mode_used`. UI adds a 出題模式 dropdown that sends `coverage_mode` on `/api/generate`.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI Query, pytest (`uv run pytest`), React 19 + Vite + vitest for the web bits.

**Spec:** `docs/superpowers/specs/2026-07-15-balanced-coverage-design.md`

## Global Constraints

- Social studies only for v1. Do not touch math or natural sciences generation paths (`src/sampler.py`, `src/natural_sciences/sampler.py`, math/NS branches in `server/generate/service.py`).
- `coverage_mode` values are the string literals `"balanced"` and `"random"`. Any other value must raise at the API boundary via `Literal[...]`.
- `coverage_mode` defaults to `"balanced"` when the field is missing on `GenerateParams` (new default per issue #112).
- When `count == 1`, the existing per-question path is untouched — no `BatchSampler` is instantiated and no assignments are threaded.
- When `count > 1` and `coverage_mode == "random"`, the existing per-question path is likewise untouched. No `BatchSampler` is instantiated.
- Interaction rule: explicit user overrides win over BatchSampler assignments. In `ss_sample_params`, `assigned_q_type` is applied only when the caller did NOT pass `q_type` and did NOT pass non-empty `subquestion_configs`; `assigned_learning_content` is applied only when the caller did NOT pass `learning_content`.
- Determinism: given the same `seed` on `GenerateParams`, a balanced batch must reproduce the same per-question assignments and the same resulting `SampledParams`.
- Every emitted question carries `metadata.coverage_mode_used ∈ {"balanced", "random"}` — including `count == 1` (always `"random"` in that case, since no balancing was applied).
- Frontend commands run from `/workspace/exam-generation/web/`; Python commands run from `/workspace/exam-generation/`.

---

### Task 1: Sampler — accept per-question BatchSampler assignments

**Files:**
- Modify: `src/social_studies/sampler.py` — `sample_params()` signature + body around the `q_type_pool` and 學習內容 blocks (lines 46–200)
- Test: `tests/test_social_studies_sampler_assignments.py` (create)

**Interfaces:**
- Consumes: no upstream deps yet — Task 2 will call this with `assigned_q_type`, `assigned_learning_content`.
- Produces: `sample_params(assigned_q_type: QuestionType | None = None, assigned_learning_content: list[str] | None = None, ...)` on `src.social_studies.sampler`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_social_studies_sampler_assignments.py`:

```python
"""Balanced-coverage sampler assignment tests (issue #112)."""

from __future__ import annotations

from src.social_studies.sampler import sample_params
from src.social_studies.schemas import QuestionType


def test_assigned_q_type_forces_that_type_when_user_did_not_pin() -> None:
    p = sample_params(seed=1, assigned_q_type=QuestionType("選擇題"))
    assert [t.value for t in p.題型] == ["選擇題"]


def test_assigned_q_type_ignored_when_user_passed_q_type_pool() -> None:
    # User explicitly narrowed to 開放式建構反應題; batch tried to force 選擇題.
    p = sample_params(
        seed=1,
        q_type=[QuestionType("開放式建構反應題")],
        assigned_q_type=QuestionType("選擇題"),
    )
    for t in p.題型:
        assert t.value == "開放式建構反應題"


def test_assigned_q_type_ignored_when_user_passed_subquestion_configs() -> None:
    from src.social_studies.schemas import SubQuestionConfig

    cfg = SubQuestionConfig(question_type=QuestionType("封閉式建構反應題"))
    p = sample_params(
        seed=1,
        sub_question_count=3,
        subquestion_configs=[cfg, {}, {}],
        assigned_q_type=QuestionType("選擇題"),
    )
    # Slot 0 stays pinned to 封閉式建構反應題; blanks are filled from the *full*
    # QuestionType pool, not from the ignored assignment.
    assert p.subquestion_configs[0].question_type.value == "封閉式建構反應題"
    fill_types = {c.question_type.value for c in p.subquestion_configs[1:]}
    assert fill_types <= {t.value for t in QuestionType}


def test_assigned_learning_content_forces_pool_when_user_did_not_pin() -> None:
    p = sample_params(
        seed=1,
        assigned_learning_content=["歷Ka-Ⅳ-1"],
    )
    assert p.學習內容_pool == ["歷Ka-Ⅳ-1"]


def test_assigned_learning_content_ignored_when_user_pinned_lc() -> None:
    p = sample_params(
        seed=1,
        learning_content=["公Ab-Ⅳ-1"],
        assigned_learning_content=["歷Ka-Ⅳ-1"],
    )
    assert p.學習內容_pool == ["公Ab-Ⅳ-1"]


def test_default_call_unchanged_without_assignments() -> None:
    p1 = sample_params(seed=42)
    p2 = sample_params(seed=42)
    assert [t.value for t in p1.題型] == [t.value for t in p2.題型]
    assert p1.學習內容_pool == p2.學習內容_pool
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_studies_sampler_assignments.py -q`
Expected: FAIL with `TypeError: sample_params() got an unexpected keyword argument 'assigned_q_type'`.

- [ ] **Step 3: Write minimal implementation**

Edit `src/social_studies/sampler.py`. Replace the current `sample_params` signature and body so it accepts and applies the two new kwargs. The full function becomes:

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
    assigned_q_type: QuestionType | None = None,
    assigned_learning_content: list[str] | None = None,
) -> SampledParams:
    """Sample random PISA-reading question parameters.

    `assigned_q_type` / `assigned_learning_content` are supplied by
    `src.batch_sampler.BatchSampler` in balanced-coverage batches. They
    override the random draw *only* when the caller did not pin the same
    dimension via `q_type` / `subquestion_configs` (for 題型) or
    `learning_content` (for 學習內容).
    """
    rng = random.Random(seed)

    selected_grade = grade if grade is not None else rng.choice(_GRADES)

    all_contexts = list(QuestionContext)
    if context is not None:
        selected_context = context
    else:
        context_count = rng.randint(1, len(all_contexts))
        selected_context = rng.sample(all_contexts, context_count)

    selected_set_type = set_type if set_type is not None else rng.choice(list(QuestionSetType))

    if sub_question_count is not None and not 3 <= sub_question_count <= 7:
        raise ValueError("sub_question_count must be between 3 and 7")

    # Interaction rule: assigned_q_type only kicks in when the caller left
    # 題型 entirely random (no q_type pool, no subquestion_configs).
    user_pinned_qtype = bool(q_type) or bool(subquestion_configs)
    if q_type is not None:
        q_type_pool = q_type
    elif assigned_q_type is not None and not user_pinned_qtype:
        q_type_pool = [assigned_q_type]
    else:
        q_type_pool = list(QuestionType)

    all_processes = list(ReadingProcess)
    process_count = rng.randint(1, min(2, len(all_processes)))
    selected_process = rng.sample(all_processes, process_count)

    selected_content_type = (
        content_type.strip()
        if content_type and content_type.strip()
        else rng.choice(_RANDOM_CONTENT_TYPE_VALUES or _CONTENT_TYPE_VALUES or ["純文字"])
    )

    all_text_forms = list(TextForm)
    if selected_content_type == "純文字":
        text_form_pool = [f for f in all_text_forms if f.value.startswith("連續文本")]
    elif selected_content_type == "graphs/charts/tables":
        text_form_pool = [
            f for f in all_text_forms
            if f.value in {"非連續文本—圖表與圖形", "非連續文本—表格"}
        ]
    elif selected_content_type == "含圖片":
        text_form_pool = [
            f for f in all_text_forms
            if f.value.startswith("非連續文本") and f.value not in {"非連續文本—圖表與圖形", "非連續文本—表格"}
        ]
    else:
        text_form_pool = all_text_forms
    selected_text_form = rng.choice(text_form_pool or all_text_forms)

    selected_subject = rng.choice(subject) if subject is not None else rng.choice(list(QuestionSubject))

    if core_competency is not None:
        selected_competency = core_competency
    else:
        pool = _ALLOWED_COMPETENCIES
        competency_count = rng.randint(1, min(3, len(pool)))
        selected_competency = rng.sample(pool, competency_count)

    subj_key = selected_subject.value
    if learning_content is not None:
        selected_lc_pool = learning_content
    elif assigned_learning_content is not None:
        selected_lc_pool = list(assigned_learning_content)
    else:
        lc_entries = allowed_learning_content(_LC_DATA, _LEARNING_STAGE, subj_key)
        lc_count = rng.randint(1, min(3, max(1, len(lc_entries))))
        selected_lc_pool = [e["value"] for e in rng.sample(lc_entries, lc_count)] if lc_entries else []

    if learning_performance is not None:
        selected_lp_pool = learning_performance
    else:
        lp_entries = allowed_learning_performance(_LP_DATA, _LEARNING_STAGE, subj_key)
        lp_count = rng.randint(1, min(2, max(1, len(lp_entries))))
        selected_lp_pool = [e["value"] for e in rng.sample(lp_entries, lp_count)] if lp_entries else []

    from src.social_studies.schemas import SubQuestionConfig
    resolved_configs: list[SubQuestionConfig] = []
    if subquestion_configs:
        for cfg in subquestion_configs:
            if isinstance(cfg, dict):
                resolved_configs.append(SubQuestionConfig(**cfg))
            elif isinstance(cfg, SubQuestionConfig):
                resolved_configs.append(cfg)

    if sub_question_count is not None:
        resolved_configs = [
            resolved_configs[i] if i < len(resolved_configs) else SubQuestionConfig()
            for i in range(sub_question_count)
        ]
        blank_count = sum(1 for cfg in resolved_configs if not cfg.question_type)
        pinned_types = {cfg.question_type for cfg in resolved_configs if cfg.question_type}
        fill_pool = [q for q in q_type_pool if q not in pinned_types] or q_type_pool[:]
        shuffled = fill_pool[:]
        rng.shuffle(shuffled)
        fill_iter = iter(shuffled[i % len(shuffled)] for i in range(blank_count))
        resolved_configs = [
            cfg.model_copy(update={"question_type": cfg.question_type or next(fill_iter)})
            for cfg in resolved_configs
        ]
        selected_q_types: list[QuestionType] = []
        for cfg in resolved_configs:
            if cfg.question_type and cfg.question_type not in selected_q_types:
                selected_q_types.append(cfg.question_type)
    else:
        type_count = rng.randint(1, min(3, len(q_type_pool)))
        selected_q_types = rng.sample(q_type_pool, type_count)

    return SampledParams(
        grade=selected_grade,
        情境=selected_context,
        題型種類=selected_set_type,
        題型=selected_q_types,
        閱讀歷程=selected_process,
        文本形式=selected_text_form,
        題目內容類型=selected_content_type,
        科目=selected_subject,
        核心素養=selected_competency,
        學習內容_pool=selected_lc_pool,
        學習表現_pool=selected_lp_pool,
        sub_question_count=sub_question_count,
        question_word_limit=question_word_limit,
        option_word_limit=option_word_limit,
        subquestion_configs=resolved_configs,
    )
```

Leave `ss_sample_params` unchanged — it already forwards `**kwargs` to `sample_params`, so `assigned_q_type` and `assigned_learning_content` reach the target function verbatim.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_social_studies_sampler_assignments.py -q`
Expected: PASS — 6 tests green. Also re-run the existing SS regression suite to confirm no drift: `uv run pytest tests/test_social_studies_context_builder.py tests/test_social_studies_verifier.py tests/test_social_studies_corrector.py tests/test_social_studies_few_shot.py tests/test_social_studies_subquestion_images.py tests/test_per_subquestion_lc_lp_output.py -q` — expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/social_studies/sampler.py tests/test_social_studies_sampler_assignments.py
git commit -m "feat(ss-sampler): accept assigned_q_type/assigned_learning_content overrides (#112)"
```

---

### Task 2: `BatchSampler` — round-robin 題型 + stratified 學習內容 plans

**Files:**
- Create: `src/batch_sampler.py`
- Test: `tests/test_batch_sampler.py`

**Interfaces:**
- Consumes: `random.Random(seed)`, arbitrary comparable pool elements (concretely `QuestionType` enum members and `str` 學習內容 codes).
- Produces:
  - `class BatchSampler` with constructor `BatchSampler(count: int, q_type_pool: Sequence[Q], learning_content_pool: Sequence[str], rng: random.Random)`.
  - Instance attributes `q_type_assignments: list[Q]` (length `count`) and `learning_content_assignments: list[list[str]]` (length `count`, each inner list length 1–3).
  - Consumers in Task 5 read those two attributes indexed by question offset `i`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_batch_sampler.py`:

```python
"""Tests for BatchSampler (issue #112 balanced coverage)."""

from __future__ import annotations

import random

from src.batch_sampler import BatchSampler


def test_pool_ge_count_all_distinct() -> None:
    # 5 questions from a 6-item pool -> 5 distinct assignments.
    bs = BatchSampler(
        count=5,
        q_type_pool=["A", "B", "C", "D", "E", "F"],
        learning_content_pool=["lc-1", "lc-2", "lc-3"],
        rng=random.Random(0),
    )
    assert len(bs.q_type_assignments) == 5
    assert len(set(bs.q_type_assignments)) == 5


def test_pool_lt_count_round_robin_within_one() -> None:
    # 6 questions over a 3-type pool -> each type appears exactly twice.
    bs = BatchSampler(
        count=6,
        q_type_pool=["A", "B", "C"],
        learning_content_pool=["lc-1"],
        rng=random.Random(0),
    )
    counts = {t: bs.q_type_assignments.count(t) for t in ["A", "B", "C"]}
    assert counts == {"A": 2, "B": 2, "C": 2}


def test_pool_lt_count_uneven_within_one() -> None:
    # 5 over 4-type pool -> 4 distinct types + 1 repeat, so counts in {1, 2}.
    bs = BatchSampler(
        count=5,
        q_type_pool=["A", "B", "C", "D"],
        learning_content_pool=["lc-1"],
        rng=random.Random(0),
    )
    counts = sorted(
        [bs.q_type_assignments.count(t) for t in ["A", "B", "C", "D"]]
    )
    assert counts == [1, 1, 1, 2]
    # Each of 4 types must appear at least once.
    assert set(bs.q_type_assignments) == {"A", "B", "C", "D"}


def test_deterministic_under_fixed_seed() -> None:
    bs1 = BatchSampler(
        count=5,
        q_type_pool=["A", "B", "C", "D"],
        learning_content_pool=["lc-1", "lc-2", "lc-3", "lc-4"],
        rng=random.Random(42),
    )
    bs2 = BatchSampler(
        count=5,
        q_type_pool=["A", "B", "C", "D"],
        learning_content_pool=["lc-1", "lc-2", "lc-3", "lc-4"],
        rng=random.Random(42),
    )
    assert bs1.q_type_assignments == bs2.q_type_assignments
    assert bs1.learning_content_assignments == bs2.learning_content_assignments


def test_assignment_order_shuffled_not_sorted_by_type() -> None:
    # With a 4-type pool and count=8 (two full cycles), a deterministic
    # round-robin without an order shuffle would be [A,B,C,D,A,B,C,D];
    # BatchSampler must break that pattern for at least one seed.
    saw_break = False
    for seed in range(20):
        bs = BatchSampler(
            count=8,
            q_type_pool=["A", "B", "C", "D"],
            learning_content_pool=["lc-1"],
            rng=random.Random(seed),
        )
        if bs.q_type_assignments != ["A", "B", "C", "D", "A", "B", "C", "D"]:
            saw_break = True
            break
    assert saw_break


def test_learning_content_stratified_before_repeat() -> None:
    # 4 questions over a 4-code pool -> every code appears exactly once
    # in the union of the four per-question assignments (each of which is
    # a length-1..3 list).
    bs = BatchSampler(
        count=4,
        q_type_pool=["A"],
        learning_content_pool=["lc-1", "lc-2", "lc-3", "lc-4"],
        rng=random.Random(7),
    )
    used = [code for lst in bs.learning_content_assignments for code in lst]
    # The first 4 codes drawn (one per question, in order) must be a
    # permutation of the pool — sampling without replacement across the batch.
    firsts = [lst[0] for lst in bs.learning_content_assignments]
    assert sorted(firsts) == ["lc-1", "lc-2", "lc-3", "lc-4"]
    assert set(used) == {"lc-1", "lc-2", "lc-3", "lc-4"}


def test_empty_learning_content_pool_yields_empty_lists() -> None:
    bs = BatchSampler(
        count=3,
        q_type_pool=["A", "B"],
        learning_content_pool=[],
        rng=random.Random(0),
    )
    assert bs.learning_content_assignments == [[], [], []]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_batch_sampler.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.batch_sampler'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/batch_sampler.py`:

```python
"""Batch-level coverage planning for balanced social-studies generation (#112).

Used only when the request has `count > 1` and `coverage_mode == "balanced"`.
Pre-plans a length-`count` 題型 assignment list by round-robin over a shuffled
pool (order-shuffled afterwards so the resulting batch isn't sorted by type),
plus a stratified sequence of 學習內容 draws that spreads across distinct
codes before repeating any.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Generic, TypeVar

Q = TypeVar("Q")


class BatchSampler(Generic[Q]):
    """Pre-plan balanced per-question assignments across a whole batch."""

    def __init__(
        self,
        count: int,
        q_type_pool: Sequence[Q],
        learning_content_pool: Sequence[str],
        rng: random.Random,
    ) -> None:
        if count < 1:
            raise ValueError("count must be >= 1")
        self.count = count
        self._rng = rng
        self.q_type_assignments: list[Q] = self._plan_q_types(list(q_type_pool))
        self.learning_content_assignments: list[list[str]] = (
            self._plan_learning_content(list(learning_content_pool))
        )

    # ---- 題型 ----------------------------------------------------------------

    def _plan_q_types(self, pool: list[Q]) -> list[Q]:
        """Round-robin over a shuffled pool, then shuffle the resulting order."""
        if not pool:
            raise ValueError("q_type_pool must not be empty")
        shuffled_pool = pool[:]
        self._rng.shuffle(shuffled_pool)
        # Round-robin fill: assignments[i] = shuffled_pool[i % |pool|].
        # For count >= |pool|, this guarantees every type appears
        # ⌊count/|pool|⌋ or ⌊count/|pool|⌋ + 1 times.
        assignments = [shuffled_pool[i % len(shuffled_pool)] for i in range(self.count)]
        self._rng.shuffle(assignments)
        return assignments

    # ---- 學習內容 ------------------------------------------------------------

    def _plan_learning_content(self, pool: list[str]) -> list[list[str]]:
        """Draw one code per question without replacement until the pool is
        exhausted, then reshuffle and repeat. Each question receives a length-1
        list (the primary code) — callers that want a multi-code pool can
        extend with additional codes; v1 keeps each question narrowly focused
        so batch coverage remains observable.
        """
        if not pool:
            return [[] for _ in range(self.count)]
        assignments: list[list[str]] = []
        cursor = pool[:]
        self._rng.shuffle(cursor)
        idx = 0
        for _ in range(self.count):
            if idx >= len(cursor):
                cursor = pool[:]
                self._rng.shuffle(cursor)
                idx = 0
            assignments.append([cursor[idx]])
            idx += 1
        return assignments
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_batch_sampler.py -q`
Expected: PASS — 7 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/batch_sampler.py tests/test_batch_sampler.py
git commit -m "feat(batch-sampler): pre-plan balanced 題型 + stratified 學習內容 batches (#112)"
```

---

### Task 3: Extend `QuestionMetadata` with `coverage_mode_used`

**Files:**
- Modify: `src/social_studies/schemas.py` — `QuestionMetadata` (lines 98–102)
- Test: `tests/test_social_studies_metadata.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: optional `QuestionMetadata.coverage_mode_used: Literal["balanced", "random"] | None` field. Task 5 sets it after each question generation.

- [ ] **Step 1: Write the failing test**

Create `tests/test_social_studies_metadata.py`:

```python
"""QuestionMetadata carries coverage_mode_used (issue #112)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.social_studies.schemas import QuestionMetadata


def test_default_omits_coverage_mode_used() -> None:
    m = QuestionMetadata(grade=8, model="claude-sonnet-4-6")
    assert m.coverage_mode_used is None


def test_accepts_balanced_and_random() -> None:
    assert QuestionMetadata(
        grade=8, model="m", coverage_mode_used="balanced"
    ).coverage_mode_used == "balanced"
    assert QuestionMetadata(
        grade=8, model="m", coverage_mode_used="random"
    ).coverage_mode_used == "random"


def test_rejects_unknown_mode() -> None:
    with pytest.raises(ValidationError):
        QuestionMetadata(grade=8, model="m", coverage_mode_used="round_robin")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_studies_metadata.py -q`
Expected: FAIL — `AttributeError` (or unexpected-keyword) on `coverage_mode_used`.

- [ ] **Step 3: Write minimal implementation**

Edit `src/social_studies/schemas.py`. Replace the `QuestionMetadata` block (currently lines 98–102) with:

```python
class QuestionMetadata(BaseModel):
    grade: int
    model: str
    generated_at: datetime = Field(default_factory=datetime.now)
    seed: int | None = None
    coverage_mode_used: Literal["balanced", "random"] | None = None
```

`Literal` is already imported at the top of the file (line 6).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_social_studies_metadata.py -q`
Expected: PASS — 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/social_studies/schemas.py tests/test_social_studies_metadata.py
git commit -m "feat(ss-schemas): add QuestionMetadata.coverage_mode_used (#112)"
```

---

### Task 4: API surface — `coverage_mode` on `GenerateParams` + query param

**Files:**
- Modify: `server/generate/models.py` — `GenerateParams` (lines 12–50)
- Modify: `server/generate/routes.py` — `generate_endpoint` signature + `GenerateParams(...)` construction (lines 42–110)
- Test: `tests/server/test_generate_routes.py` (append a new function)

**Interfaces:**
- Consumes: FastAPI `Query`.
- Produces: `GenerateParams.coverage_mode: Literal["balanced", "random"] = "balanced"`, plumbed from the `/api/generate?coverage_mode=...` query string. Task 5 reads it from `params.coverage_mode`.

- [ ] **Step 1: Write the failing test**

Append to `tests/server/test_generate_routes.py`:

```python
def test_generate_route_defaults_coverage_mode_to_balanced() -> None:
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

    captured: dict = {}

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
            # No coverage_mode in the query → defaults to "balanced".
            r_default = client.get(
                "/api/generate?subject=social_studies&count=3",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r_default.status_code == 200
            assert captured["params"].coverage_mode == "balanced"

            # Explicit random passes through.
            r_random = client.get(
                "/api/generate?subject=social_studies&count=3&coverage_mode=random",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r_random.status_code == 200
            assert captured["params"].coverage_mode == "random"

            # Unknown value → 422 from Query Literal validation.
            r_bad = client.get(
                "/api/generate?subject=social_studies&count=3&coverage_mode=chaotic",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r_bad.status_code == 422
    finally:
        gen_routes.generate_question_stream = original  # type: ignore[assignment]
        limiter.reset()
        asyncio.run(engine.dispose())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/server/test_generate_routes.py::test_generate_route_defaults_coverage_mode_to_balanced -q`
Expected: FAIL — `AttributeError: 'GenerateParams' object has no attribute 'coverage_mode'` (or the Query validation never runs and the assertion trips).

- [ ] **Step 3: Write minimal implementation**

Edit `server/generate/models.py`. Directly below the existing `ImageGenerationMode = Literal["html", "gpt_image"]` line (line 9), add:

```python
CoverageMode = Literal["balanced", "random"]
```

Then, inside `GenerateParams`, add the field immediately after the existing `image_generation_mode` field (currently line 30):

```python
    coverage_mode: CoverageMode = "balanced"
```

Edit `server/generate/routes.py`. Import `CoverageMode` alongside `ImageGenerationMode`:

```python
from server.generate.models import (
    CoverageMode,
    GenerateParams,
    ImageGenerationMode,
    PlanCoreQuestionsRequest,
    PlanCoreQuestionsResponse,
)
```

Add a query parameter immediately after `image_generation_mode` (currently line 56):

```python
    coverage_mode: CoverageMode = Query(default="balanced"),
```

Add the field to the `GenerateParams(...)` construction, next to `image_generation_mode=image_generation_mode` (currently line 93):

```python
        coverage_mode=coverage_mode,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/server/test_generate_routes.py::test_generate_route_defaults_coverage_mode_to_balanced tests/server/test_generate_routes.py::test_generate_route_forwards_social_studies_options tests/server/test_generate_routes.py::test_generate_route_forwards_natural_sciences_options -q`
Expected: PASS — 3 tests green. The two existing forwarding tests must still pass unchanged (they omit `coverage_mode` and now inherit the `"balanced"` default without failing any assertion).

- [ ] **Step 5: Commit**

```bash
git add server/generate/models.py server/generate/routes.py tests/server/test_generate_routes.py
git commit -m "feat(api): add coverage_mode query param (default balanced) to /api/generate (#112)"
```

---

### Task 5: Wire `BatchSampler` into the SS service branch + stamp metadata

**Files:**
- Modify: `server/generate/service.py`
  - Add imports (top of file).
  - Insert a batch-planning block after the SS override block (around line 162) but before `worker_one` is defined.
  - Inside `worker_one`, thread `assigned_q_type` / `assigned_learning_content` into `ss_sample_params` and stamp `question.metadata.coverage_mode_used` after generation.
- Test: `tests/server/test_generate_service_coverage.py` (create)

**Interfaces:**
- Consumes: `src.batch_sampler.BatchSampler`, `src.social_studies.schemas.QuestionType`, `params.coverage_mode` (Task 4).
- Produces: `question.metadata.coverage_mode_used` on every SS `ExamQuestion` returned by the SS branch.

- [ ] **Step 1: Write the failing test**

Create `tests/server/test_generate_service_coverage.py`:

```python
"""Balanced-coverage wiring in the SS service branch (issue #112)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from server.config import ServerConfig
from server.generate import service
from server.generate.models import GenerateParams
from src.social_studies.schemas import (
    ExamQuestion,
    QuestionContext,
    QuestionMetadata,
    QuestionSetType,
    QuestionSubject,
    QuestionType,
    ReadingProcess,
    SampledParams,
    TextForm,
)


def _fake_generate_with_corrections(**kwargs):
    params: SampledParams = kwargs["params"]
    return ExamQuestion(
        id=kwargs["question_id"],
        情境=[c for c in params.情境],
        題型種類=params.題型種類,
        題型=params.題型[0] if params.題型 else QuestionType("選擇題"),
        閱讀歷程=params.閱讀歷程,
        文本形式=params.文本形式,
        題目內容類型=params.題目內容類型,
        metadata=QuestionMetadata(grade=params.grade, model="test-model"),
    )


def _run_stream(params: GenerateParams, tmp_path: Path) -> list[dict]:
    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    app_state = SimpleNamespace(renderer_pool=None)
    events: list[dict] = []

    async def collect() -> None:
        async for ev in service.generate_question_stream(params, config, app_state):
            events.append(ev)

    with patch.object(
        service, "ss_generate_with_corrections", side_effect=_fake_generate_with_corrections
    ):
        asyncio.run(collect())
    return events


def test_balanced_batch_covers_distinct_q_types(tmp_path) -> None:
    params = GenerateParams(
        subject="social_studies",
        count=4,
        skip_verify=True,
        coverage_mode="balanced",
        seed=13,
    )
    events = _run_stream(params, tmp_path)
    results = [e["data"] for e in events if e["event"] == "result"]
    assert len(results) == 4

    q_types = [r["題型"] for r in results]
    # 4 questions over the 3-value QuestionType pool: each of the 3 types
    # must appear at least once (⌊4/3⌋+1 balancing guarantee).
    from src.social_studies.schemas import QuestionType as QT

    assert set(q_types) >= {t.value for t in QT}

    assert all(r["metadata"]["coverage_mode_used"] == "balanced" for r in results)


def test_random_mode_skips_batch_sampler_and_stamps_metadata(tmp_path) -> None:
    params = GenerateParams(
        subject="social_studies",
        count=3,
        skip_verify=True,
        coverage_mode="random",
        seed=13,
    )
    events = _run_stream(params, tmp_path)
    results = [e["data"] for e in events if e["event"] == "result"]
    assert len(results) == 3
    assert all(r["metadata"]["coverage_mode_used"] == "random" for r in results)


def test_count_one_stamps_random_regardless_of_flag(tmp_path) -> None:
    params = GenerateParams(
        subject="social_studies",
        count=1,
        skip_verify=True,
        coverage_mode="balanced",
        seed=5,
    )
    events = _run_stream(params, tmp_path)
    results = [e["data"] for e in events if e["event"] == "result"]
    assert len(results) == 1
    assert results[0]["metadata"]["coverage_mode_used"] == "random"


def test_user_q_type_pool_wins_over_balanced_assignment(tmp_path) -> None:
    # User pinned q_type; balanced assignment must be a no-op for 題型.
    params = GenerateParams(
        subject="social_studies",
        count=3,
        skip_verify=True,
        coverage_mode="balanced",
        q_type=["開放式建構反應題"],
        seed=13,
    )
    events = _run_stream(params, tmp_path)
    results = [e["data"] for e in events if e["event"] == "result"]
    assert {r["題型"] for r in results} == {"開放式建構反應題"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/server/test_generate_service_coverage.py -q`
Expected: FAIL — either `KeyError('coverage_mode_used')` (metadata key missing) or the balanced batch produces clustered 題型 because no `BatchSampler` is wired in.

- [ ] **Step 3: Write minimal implementation**

Edit `server/generate/service.py`.

Add these imports after the existing `src.social_studies.*` block (around line 74):

```python
from src.batch_sampler import BatchSampler
from src.social_studies.schemas import QuestionType as SSQuestionTypeEnum
```

Inside `generate_question_stream`, after the SS override block and before `timestamp = ...` (currently line 196), add the batch-planning block:

```python
    # --- Balanced-coverage planning (SS only, count > 1, balanced mode) -----
    ss_batch_sampler: BatchSampler | None = None
    if (
        is_social_studies
        and params.count > 1
        and params.coverage_mode == "balanced"
    ):
        batch_rng = random.Random(params.seed if params.seed is not None else 0)
        # Interaction rule: only balance dimensions the user left random.
        user_pinned_qtype = bool(params.q_type) or bool(params.subquestion_configs)
        user_pinned_lc = bool(params.learning_content)
        q_pool = (
            [SSQuestionTypeEnum(v) for v in params.q_type]
            if user_pinned_qtype and params.q_type
            else list(SSQuestionTypeEnum)
        )
        # 學習內容 pool: default is the whole stage pool for the (optional)
        # subject filter; we let the sampler fill in a stage-appropriate pool
        # if the user didn't pin subject_filter either.
        from src.social_studies.curriculum_loader import (
            allowed_learning_content,
            load_learning_content,
        )
        from src.social_studies.sampler import _LEARNING_STAGE as _SS_STAGE

        subj_key = (
            params.subject_filter[0] if params.subject_filter else "跨科"
        )
        lc_entries = (
            allowed_learning_content(load_learning_content(), _SS_STAGE, subj_key)
            if not user_pinned_lc
            else []
        )
        lc_pool = [e["value"] for e in lc_entries] if not user_pinned_lc else []

        ss_batch_sampler = BatchSampler(
            count=params.count,
            q_type_pool=q_pool if not user_pinned_qtype else [q_pool[0]],
            learning_content_pool=lc_pool,
            rng=batch_rng,
        )
```

Also add `import random` at the top of the module if not already present (it isn't — check via `grep`; add `import random` under the existing `import json` line, currently line 11).

Inside `worker_one`, in the `if is_social_studies:` block (around line 254), change the `ss_sample_params(...)` call to also pass the balanced assignments:

```python
            if is_social_studies:
                assigned_qt = (
                    ss_batch_sampler.q_type_assignments[i]
                    if ss_batch_sampler is not None else None
                )
                assigned_lc = (
                    ss_batch_sampler.learning_content_assignments[i]
                    if ss_batch_sampler is not None else None
                )
                rng_params = ss_sample_params(
                    grade=params.grade,
                    context=context_override,
                    set_type=set_type_override,
                    q_type=q_type_override,
                    subject=subject_override,
                    content_type=params.content_type,
                    learning_performance=params.learning_performance,
                    seed=seed,
                    sub_question_count=params.sub_question_count,
                    question_word_limit=params.question_word_limit,
                    option_word_limit=params.option_word_limit,
                    subquestion_configs=_decode_subquestion_configs(
                        params.subquestion_configs,
                    ),
                    assigned_q_type=assigned_qt,
                    assigned_learning_content=assigned_lc,
                )
```

Immediately after the `question = ss_generate_with_corrections(...)` return in the SS branch (the block ending around line 288), stamp the metadata before the `assert isinstance(...)` at line 365. Locate the block:

```python
            assert isinstance(
                question,
                (MathExamQuestion, SSExamQuestion, NSExamQuestion),
            )
            _emit_pipeline("question_end", index=i, total=count)
```

and insert directly above the `assert`:

```python
            if is_social_studies and isinstance(question, SSExamQuestion):
                effective_mode = (
                    "balanced" if ss_batch_sampler is not None else "random"
                )
                if question.metadata is None:
                    question.metadata = QuestionMetadata(
                        grade=rng_params.grade,
                        model=config.model_execute if hasattr(config, "model_execute") else "unknown",
                        coverage_mode_used=effective_mode,
                    )
                else:
                    question.metadata = question.metadata.model_copy(
                        update={"coverage_mode_used": effective_mode}
                    )
```

Add `QuestionMetadata` to the SS import block near the top of the file (right after `SSExamQuestion`):

```python
from src.social_studies.schemas import (
    QuestionMetadata,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/server/test_generate_service_coverage.py -q`
Expected: PASS — 4 tests green.

Also re-run the full server suite to catch regressions in the two existing forwarding tests: `uv run pytest tests/server/ -q` — expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/generate/service.py tests/server/test_generate_service_coverage.py
git commit -m "feat(service): wire BatchSampler into SS branch and stamp coverage_mode_used (#112)"
```

---

### Task 6: SS CLI — `--coverage-mode balanced|random`

**Files:**
- Modify: `src/social_studies/cli.py`
  - `parse_args` — new argparse flag near the existing `--count`/`--seed` group (around line 153).
  - `main` — construct a `BatchSampler` when appropriate and thread `assigned_q_type` / `assigned_learning_content` into `sample_params`; stamp `question.metadata.coverage_mode_used` before persisting.
- Test: `tests/test_social_studies_cli_coverage.py` (create — argparse-only, does not invoke LLMs)

**Interfaces:**
- Consumes: `src.batch_sampler.BatchSampler`, existing `sample_params`.
- Produces: `Namespace.coverage_mode` on the CLI and metadata stamping mirroring the API path.

- [ ] **Step 1: Write the failing test**

Create `tests/test_social_studies_cli_coverage.py`:

```python
"""Argparse-level test for the SS CLI --coverage-mode flag (issue #112)."""

from __future__ import annotations

import pytest

from src.social_studies.cli import parse_args


def test_default_coverage_mode_is_balanced() -> None:
    ns = parse_args(["generate"])
    assert ns.coverage_mode == "balanced"


def test_can_set_random() -> None:
    ns = parse_args(["generate", "--coverage-mode", "random"])
    assert ns.coverage_mode == "random"


def test_rejects_unknown_value() -> None:
    with pytest.raises(SystemExit):
        parse_args(["generate", "--coverage-mode", "chaotic"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_studies_cli_coverage.py -q`
Expected: FAIL — `AttributeError: 'Namespace' object has no attribute 'coverage_mode'`.

- [ ] **Step 3: Write minimal implementation**

Edit `src/social_studies/cli.py`. Directly after the existing `--seed` argument (currently line 155), insert:

```python
    gen.add_argument(
        "--coverage-mode",
        choices=["balanced", "random"],
        default="balanced",
        help="出題模式：balanced（跨題目平均分配題型/學習內容）或 random（每題獨立隨機）",
    )
```

Add the runtime wiring inside `main`, immediately after `max_retries = ...` (currently line 860) and before the `for i in range(args.count):` loop:

```python
    from src.batch_sampler import BatchSampler
    from src.social_studies.schemas import QuestionType as _QT

    batch_sampler: BatchSampler | None = None
    if args.count > 1 and args.coverage_mode == "balanced":
        user_pinned_qtype = bool(args.q_type)
        user_pinned_lc = bool(args.learning_content)
        batch_rng = __import__("random").Random(base_seed if base_seed is not None else 0)
        q_pool = (
            [_resolve_enum(v, _QT) for v in args.q_type]
            if user_pinned_qtype else list(_QT)
        )
        lc_pool: list[str] = [] if user_pinned_lc else []
        # For the CLI we intentionally leave lc_pool empty; SS-CLI is the
        # single-operator path and the stage-wide 學習內容 stratification is
        # exercised via the API in Task 5. This keeps CLI startup fast.
        batch_sampler = BatchSampler(
            count=args.count,
            q_type_pool=q_pool,
            learning_content_pool=lc_pool,
            rng=batch_rng,
        )
```

Inside the loop, change the `sample_params(...)` call to add the two assignment kwargs:

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
                assigned_q_type=(
                    batch_sampler.q_type_assignments[i] if batch_sampler else None
                ),
                assigned_learning_content=(
                    batch_sampler.learning_content_assignments[i] if batch_sampler else None
                ),
            )
```

Immediately after `assert isinstance(question, ExamQuestion)` (currently line 905), before `results.append(question)`, stamp the metadata:

```python
            effective_mode = "balanced" if batch_sampler is not None else "random"
            if question.metadata is None:
                question.metadata = QuestionMetadata(
                    grade=params.grade,
                    model="",
                    coverage_mode_used=effective_mode,
                )
            else:
                question.metadata = question.metadata.model_copy(
                    update={"coverage_mode_used": effective_mode}
                )
```

`QuestionMetadata` is already imported at the top of the file (line 37).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_social_studies_cli_coverage.py -q`
Expected: PASS — 3 tests green.

Also run the sampler-assignment regression: `uv run pytest tests/test_social_studies_sampler_assignments.py tests/test_batch_sampler.py -q` — expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/social_studies/cli.py tests/test_social_studies_cli_coverage.py
git commit -m "feat(ss-cli): add --coverage-mode flag mirroring API (#112)"
```

---

### Task 7: Frontend — 出題模式 dropdown, `useGenerate` plumbing, i18n

**Files:**
- Modify: `web/src/hooks/useGenerate.ts` — `GenerateParams` interface + `buildQueryString` (lines 8–34, 167–199)
- Modify: `web/src/components/ParamForm.tsx` — `GenerateParams` interface (lines 19–42), state (lines 195 region), form JSX near the 數量 (`form.count`) block (lines 973–983), submit payload (lines 424–457), confirm-preview rows (lines 481–508)
- Modify: `web/src/i18n/messages.ts` — `en-US` block after `form.count` line (~line 51); `zh-TW` block after its `form.count` line (~line 214); confirm block additions after `form.confirm_count` (lines 89 and 252)
- Test: `web/src/components/ParamForm.coverage.test.tsx` (create)

**Interfaces:**
- Consumes: existing i18n `useT()`.
- Produces: `params.coverage_mode` on the payload sent through `useGenerate.generate()` → `/api/generate?coverage_mode=...` (Task 4 accepts it).

- [ ] **Step 1: Write the failing test**

Create `web/src/components/ParamForm.coverage.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../api/client", () => ({
  getSchemas: vi.fn(async () => ({
    grades: [7, 8, 9],
    情境: [{ value: "個人" }, { value: "公共" }],
    情境子類別: [],
    題型種類: [{ value: "題組題" }],
    題型: [
      { value: "選擇題" },
      { value: "封閉式建構反應題" },
      { value: "開放式建構反應題" },
    ],
    題目內容類型: [{ value: "純文字" }],
    科目: [{ value: "歷史" }, { value: "地理" }, { value: "公民與社會" }, { value: "跨科" }],
    學習表現: [],
    學習內容: [],
    question_style: [],
  })),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

import ParamForm, { type GenerateParams } from "./ParamForm";

describe("ParamForm coverage_mode dropdown", () => {
  beforeEach(() => vi.clearAllMocks());

  it("defaults coverage_mode to 'balanced' on submit", async () => {
    const submitted: GenerateParams[] = [];
    render(
      <ParamForm subject="social_studies" onSubmit={(p) => submitted.push(p)} disabled={false} />,
    );

    // Wait for schema-driven state to hydrate.
    await waitFor(() =>
      expect(screen.getByLabelText("form.coverage_mode")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByText("form.btn_generate"));
    // Advance past the confirm step.
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].coverage_mode).toBe("balanced");
  });

  it("sends coverage_mode='random' when the operator picks 隨機", async () => {
    const submitted: GenerateParams[] = [];
    render(
      <ParamForm subject="social_studies" onSubmit={(p) => submitted.push(p)} disabled={false} />,
    );
    await waitFor(() =>
      expect(screen.getByLabelText("form.coverage_mode")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByLabelText("form.coverage_mode"), {
      target: { value: "random" },
    });
    fireEvent.click(screen.getByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].coverage_mode).toBe("random");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run from `/workspace/exam-generation/web/`:

```bash
cd /workspace/exam-generation/web
npm test -- src/components/ParamForm.coverage.test.tsx
```

Expected: FAIL — no element with label `"form.coverage_mode"` renders, and `GenerateParams` has no `coverage_mode` field.

- [ ] **Step 3: Write minimal implementation**

Edit `web/src/hooks/useGenerate.ts`. Add the field to the interface at line 34:

```ts
  subquestion_configs?: string;
  coverage_mode?: "balanced" | "random";
}
```

Append to `buildQueryString` (directly before the final `return qs.toString();`):

```ts
  if (params.coverage_mode !== undefined) qs.append("coverage_mode", params.coverage_mode);
```

Edit `web/src/components/ParamForm.tsx`. Add to the exported `GenerateParams` interface, next to `subquestion_configs?: string;` (line 41):

```ts
  coverage_mode?: "balanced" | "random";
```

Directly below the existing `const [count, setCount] = useState<number>(1);` (line 195), add:

```tsx
  const [coverageMode, setCoverageMode] = useState<"balanced" | "random">("balanced");
```

Add a matching form section immediately after the `數量` block (which ends at line 983, `</div>`) — but only when `subject === "social_studies"`:

```tsx
      {subject === "social_studies" && (
        <div>
          <label htmlFor="coverage-mode-select" className="block text-sm font-medium">
            {t("form.coverage_mode")}
          </label>
          <select
            id="coverage-mode-select"
            aria-label="form.coverage_mode"
            value={coverageMode}
            onChange={(e) => setCoverageMode(e.target.value as "balanced" | "random")}
            className="mt-1 block w-64 border rounded px-2 py-1"
          >
            <option value="balanced">{t("form.coverage_mode.balanced")}</option>
            <option value="random">{t("form.coverage_mode.random")}</option>
          </select>
        </div>
      )}
```

Extend the `setPendingParams({...})` payload (line 424 region), adding a new property alongside `count`:

```ts
      count,
      coverage_mode: subject === "social_studies" ? coverageMode : undefined,
```

Add a confirm-preview row inside the `rows` array (line 481), directly after `{ label: t("form.confirm_count"), value: String(p.count) }`:

```ts
      { label: t("form.confirm_coverage_mode"), value: p.coverage_mode },
```

Edit `web/src/i18n/messages.ts`. In the `en-US` block, directly after the `"form.count": "Count",` line (line 51):

```ts
    "form.coverage_mode": "Coverage mode",
    "form.coverage_mode.balanced": "Balanced (spread across 題型 / 學習內容)",
    "form.coverage_mode.random": "Random",
```

In the same block, directly after `"form.confirm_count": "Count",` (line 89):

```ts
    "form.confirm_coverage_mode": "Coverage mode",
```

In the `zh-TW` block, directly after `"form.count": "數量",` (line 214):

```ts
    "form.coverage_mode": "出題模式",
    "form.coverage_mode.balanced": "均衡（題型平均分配）",
    "form.coverage_mode.random": "隨機",
```

And directly after `"form.confirm_count": "數量",` (line 252):

```ts
    "form.confirm_coverage_mode": "出題模式",
```

- [ ] **Step 4: Run test to verify it passes**

Run from `/workspace/exam-generation/web/`:

```bash
cd /workspace/exam-generation/web
npm test -- src/components/ParamForm.coverage.test.tsx
```

Expected: PASS — 2 tests green.

Then run the full web suite and typecheck/build:

```bash
cd /workspace/exam-generation/web
npm test && npm run lint && npm run build
```

Expected: all tests pass, no lint errors, build succeeds.

- [ ] **Step 5: Commit**

```bash
cd /workspace/exam-generation
git add web/src/hooks/useGenerate.ts web/src/components/ParamForm.tsx web/src/components/ParamForm.coverage.test.tsx web/src/i18n/messages.ts
git commit -m "feat(web): add 出題模式 (coverage_mode) dropdown, default balanced (#112)"
```

---

### Task 8: End-to-end integration verification

**Files:** none (verification only).

**Interfaces:**
- Consumes: all Tasks 1–7.

- [ ] **Step 1: Full backend suite**

Run: `uv run pytest -q`
Expected: PASS — no failures in the SS, natural-sciences, or math suites; the new `test_batch_sampler.py`, `test_social_studies_sampler_assignments.py`, `test_social_studies_metadata.py`, `test_social_studies_cli_coverage.py`, and `tests/server/test_generate_service_coverage.py` all pass.

- [ ] **Step 2: Full frontend suite + build**

```bash
cd /workspace/exam-generation/web
npm test && npm run lint && npm run build
```

Expected: PASS on all three.

- [ ] **Step 3: Smoke-check the CLI with a dry-run batch**

```bash
cd /workspace/exam-generation
uv run python -m src.social_studies.cli generate \
  --count 4 --coverage-mode balanced --seed 42 --dry-run
```

Expected: no traceback; stderr shows four `Sampled: ... 題型=...` lines whose 題型 values are not all identical (balanced batching must diversify at least once across four questions).

Compare against random mode:

```bash
uv run python -m src.social_studies.cli generate \
  --count 4 --coverage-mode random --seed 42 --dry-run
```

Expected: no traceback; may or may not diversify (random is allowed to cluster).

- [ ] **Step 4: Commit** (docs-only touch-up if any regression surfaced)

If Steps 1–3 all pass unchanged, there is nothing to commit for this task. If a regression was fixed, commit with:

```bash
git add -p
git commit -m "chore(#112): balanced-coverage integration fixes"
```
