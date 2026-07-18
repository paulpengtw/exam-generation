> **SUPERSEDED 2026-07-18.** The operator approved a **hybrid** decision instead of the
> `frontend_ts` rollout planned here. See `docs/figure-rendering-policy.md` (Phase A
> outcome, HYBRID entry) and `docs/figure-rendering-evaluation.md` (15-spec fidelity
> comparison) for the evidence and decision. Part A tasks 1-5 already shipped as PR #147.
> Part B tasks 6-12 are NOT to be executed; the new routing scope will live in a fresh
> plan doc (to be authored in a later session).

---

# Frontend-TS Render Mode — Gate Evidence + Gated Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish GitHub issue #110 ("Codify figure-rendering routing") — Part A builds the tooling that collects the Phase A GO/NO-GO gate evidence (production chart_spec census + live fidelity comparison harness); Part B (gated on an operator-recorded GO) extends `render_mode` with `"frontend_ts"`, reroutes the prompt instructions, and adds the issue's classification test.

**Architecture:** Part A adds two standalone scripts (`scripts/census_chart_specs.py` reads `generation_records` via the same async-SQLAlchemy stack the server uses; `scripts/build_fidelity_manifest.py` renders illustrative specs through the existing LLM-HTML + Playwright path into a JSON manifest) plus a flag-gated React harness page (`/fidelity-compare`) that displays server PNG vs `FigureRenderer` side-by-side and exports a Markdown fidelity table. Part B touches the three `ImageSpec` schemas, `src/renderer.py` dispatch, the three `CONTENT_TYPE_INSTRUCTIONS` tables and prompt templates, the math schema surface in `server/utility/routes.py`, and adds `src/common/figure_policy.py` for the render-mode ↔ 題目內容類型 consistency check. The policy half of #110 (PR #141: `docs/figure-rendering-policy.md`, docstring citations, `tests/test_figure_rendering_policy.py`) is already shipped and is NOT re-planned here.

**Tech Stack:** Python 3.11 + uv + pytest + pydantic 2 + SQLAlchemy 2 (async, aiosqlite/asyncpg) + matplotlib + Playwright; React 19 + Vite + Tailwind 4 + vitest + @testing-library/react.

**Issue:** https://github.com/paulpengtw/exam-generation/issues/110 (remaining execution half; see the 2026-07-16 status comment on the issue).

## Global Constraints

- **THE GATE (verbatim from `docs/figure-rendering-policy.md`, Phase A outcome):** "A full GO (triggering Task 10) requires both a production census (≥30 questions per subject) and a live fidelity comparison with measured fallback rates." **Tasks 6–12 of this plan are GATED: do not start them until a human operator has recorded a GO or HYBRID decision in `docs/figure-rendering-policy.md`. An agent may prepare evidence but must never self-declare GO.** Tasks 1–5 are ungated and are done now.
- **Policy update-order rule (verbatim from CLAUDE.md):** "update the policy first, then the docstrings, then the `CONTENT_TYPE_INSTRUCTIONS` tables." Part B task order (6 → 7 → 9) encodes this; do not reorder.
- `"html"` remains **permanently accepted as a legacy alias** for already-generated questions (policy doc). Part B never removes `"html"` from any `Literal`, and the renderer keeps dispatching it.
- Verifier and ODT export always consume the server-side PNG. `render_mode: "frontend_ts"` changes the on-page `<img>` display only — the server still renders a Playwright PNG for every illustrative spec.
- Backend deps: run `uv sync --extra web` once before any test run. A plain `uv sync` **drops** the web extras (fastapi/sqlalchemy) and breaks `tests/server/` and the new census tests.
- Backend tests run from the repo root: `uv run pytest <file> -v`. Web tests run from `/workspace/exam-generation/web/`: `npm test` (vitest; `npm test -- <file>` filters).
- Lint baselines are dirty: `uv run ruff check src/ scripts/ server/` has ~141 pre-existing errors (mostly E501 on Chinese prompt strings) and `npm run lint` has 6 pre-existing errors (ParamForm/VerifyPage set-state-in-effect). **Lint checks in this plan are scoped to the files the task touches; introduce no new violations.**
- Branching: Part A on `feat/110-figure-gate-evidence` off `staging`; Part B (later, post-GO) on `feat/110-frontend-ts-render-mode` off the then-current `staging`. Commit per task; do not push or merge as part of this plan.
- `scripts/` is not a package: every new script must insert the repo root into `sys.path` before importing `scripts.*` or `server.*` (see Task 1 code), because tests import it as `scripts.<name>` via `tests/conftest.py` while operators run it as `python scripts/<name>.py`.
- Do not touch the shipped policy-half artifacts except where a task explicitly edits them: `docs/figure-rendering-policy.md`, `tests/test_figure_rendering_policy.py`, the three context-builder docstrings.

---

# PART A — Gate evidence tooling (ungated, do now)

### Task 1: Census aggregation core (pure functions)

**Files:**
- Modify: `scripts/analyze_chart_spec_coverage.py` (extract `iter_item_specs` from `iter_specs`, lines 44–63)
- Modify: `tests/test_analyze_chart_spec_coverage.py`
- Create: `scripts/census_chart_specs.py`
- Create: `tests/server/test_census_chart_specs.py`

**Interfaces:**
- Consumes: `classify_spec(spec: dict) -> str` from `scripts/analyze_chart_spec_coverage.py` (categories: `chart` / `table` / `geometry` / `scenario_card` / `other`).
- Produces (used by Tasks 2–3):
  - `iter_item_specs(item: dict) -> Iterable[dict]` in `scripts/analyze_chart_spec_coverage.py` — yields every non-null `chart_spec` dict on one question item (top-level + `subquestions[*]`).
  - In `scripts/census_chart_specs.py`: `GATE_SUBJECTS = ("math", "social_studies", "natural_sciences")`, `DEFAULT_MIN_PER_SUBJECT = 30`, dataclasses `SubjectCensus` / `CensusResult` (property `gate_met: bool`), `summarize_census(rows: list[tuple[str, dict]], min_per_subject: int = 30) -> CensusResult`, `render_census_markdown(result: CensusResult) -> str`.

- [ ] **Step 1: Create the branch**

```bash
cd /workspace/exam-generation
git checkout staging && git pull
git checkout -b feat/110-figure-gate-evidence
uv sync --extra web
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_analyze_chart_spec_coverage.py` (also extend the import at the top of the file from `from scripts.analyze_chart_spec_coverage import classify_spec, iter_specs, summarize` to include `iter_item_specs`):

```python
def test_iter_item_specs_yields_top_level_and_subquestion_specs() -> None:
    item = {
        "chart_spec": {"render_mode": "chart", "chart_type": "boxplot", "data": {}},
        "subquestions": [
            {"chart_spec": {"render_mode": "html", "description": "表格", "data": {"rows": []}}},
            {"chart_spec": None},
            "not-a-dict",
        ],
    }
    specs = list(iter_item_specs(item))
    assert len(specs) == 2
    assert {classify_spec(s) for s in specs} == {"chart", "table"}
```

Create `tests/server/test_census_chart_specs.py`:

```python
"""Tests for the generation-record chart_spec census (issue #110 gate evidence)."""

from __future__ import annotations

from scripts.census_chart_specs import (
    GATE_SUBJECTS,
    render_census_markdown,
    summarize_census,
)


def test_summarize_census_counts_questions_and_specs_per_subject() -> None:
    rows = [
        ("math", {"chart_spec": {"render_mode": "chart", "chart_type": "histogram", "data": {}}}),
        ("math", {"chart_spec": None}),
        (
            "social_studies",
            {
                "subquestions": [
                    {"chart_spec": {"render_mode": "html", "data": {"rows": [], "columns": []}}}
                ]
            },
        ),
    ]
    result = summarize_census(rows, min_per_subject=2)
    assert result.per_subject["math"].questions == 2
    assert result.per_subject["math"].questions_with_spec == 1
    assert result.per_subject["math"].specs_by_category["chart"] == 1
    assert result.per_subject["social_studies"].specs_by_category["table"] == 1
    assert result.per_subject["social_studies"].specs_by_render_mode["html"] == 1


def test_gate_requires_all_three_subjects_at_threshold() -> None:
    assert GATE_SUBJECTS == ("math", "social_studies", "natural_sciences")
    rows = [("math", {})] * 30 + [("social_studies", {})] * 30
    assert summarize_census(rows, min_per_subject=30).gate_met is False
    rows += [("natural_sciences", {})] * 30
    assert summarize_census(rows, min_per_subject=30).gate_met is True


def test_render_census_markdown_lists_subjects_and_gate_status() -> None:
    rows = [
        ("math", {"chart_spec": {"render_mode": "chart", "chart_type": "histogram", "data": {}}}),
    ]
    md = render_census_markdown(summarize_census(rows, min_per_subject=30))
    assert "| math | 1 | 1 |" in md
    # Subjects with zero rows still get a gate row.
    assert "| natural_sciences | 0 | 0 |" in md
    assert "GATE NOT MET" in md
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/server/test_census_chart_specs.py tests/test_analyze_chart_spec_coverage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.census_chart_specs'` and `ImportError: cannot import name 'iter_item_specs'`.

- [ ] **Step 4: Refactor `iter_specs` in `scripts/analyze_chart_spec_coverage.py`**

Replace the existing `iter_specs` (lines 44–63) with:

```python
def iter_item_specs(item: dict) -> Iterable[dict]:
    """Yield every non-null chart_spec on one question item (top-level + subquestions)."""
    top = item.get("chart_spec")
    if isinstance(top, dict):
        yield top
    for sq in item.get("subquestions") or []:
        if not isinstance(sq, dict):
            continue
        sub = sq.get("chart_spec")
        if isinstance(sub, dict):
            yield sub


def iter_specs(root: Path) -> Iterable[dict]:
    """Yield every non-null chart_spec found under root (top-level + subquestions)."""
    for path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payloads = payload if isinstance(payload, list) else [payload]
        for item in payloads:
            if not isinstance(item, dict):
                continue
            yield from iter_item_specs(item)
```

- [ ] **Step 5: Write the census module (pure part)**

Create `scripts/census_chart_specs.py`:

```python
"""Chart-spec census over production/staging generation records (issue #110).

Collects the Phase A gate evidence required by docs/figure-rendering-policy.md:
per-subject question counts and chart_spec category / render_mode distributions,
read from the ``generation_records`` table (per-user history, server/models.py).
The gate is MET when every subject in GATE_SUBJECTS has >= --min-per-subject
questions recorded.

Run (aiosqlite dev DB by default; point DATABASE_URL at staging/production):
    uv run python scripts/census_chart_specs.py
    DATABASE_URL=postgresql+asyncpg://... uv run python scripts/census_chart_specs.py --check
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analyze_chart_spec_coverage import classify_spec, iter_item_specs  # noqa: E402

GATE_SUBJECTS = ("math", "social_studies", "natural_sciences")
DEFAULT_MIN_PER_SUBJECT = 30


@dataclass
class SubjectCensus:
    """Aggregated chart_spec statistics for one subject."""

    questions: int = 0
    questions_with_spec: int = 0
    specs_by_category: Counter = field(default_factory=Counter)
    specs_by_render_mode: Counter = field(default_factory=Counter)


@dataclass
class CensusResult:
    per_subject: dict[str, SubjectCensus]
    min_per_subject: int

    @property
    def gate_met(self) -> bool:
        return all(
            self.per_subject.get(s, SubjectCensus()).questions >= self.min_per_subject
            for s in GATE_SUBJECTS
        )


def summarize_census(
    rows: list[tuple[str, dict]],
    min_per_subject: int = DEFAULT_MIN_PER_SUBJECT,
) -> CensusResult:
    """Aggregate (subject, question_json) rows into per-subject census stats."""
    per_subject: dict[str, SubjectCensus] = {}
    for subject, item in rows:
        census = per_subject.setdefault(subject, SubjectCensus())
        census.questions += 1
        specs = list(iter_item_specs(item)) if isinstance(item, dict) else []
        if specs:
            census.questions_with_spec += 1
        for spec in specs:
            census.specs_by_category[classify_spec(spec)] += 1
            mode = (spec.get("render_mode") or "").lower() or "(missing)"
            census.specs_by_render_mode[mode] += 1
    return CensusResult(per_subject=per_subject, min_per_subject=min_per_subject)


def render_census_markdown(result: CensusResult) -> str:
    """Render the census as Markdown ready to paste into figure-rendering-evaluation.md."""
    n = result.min_per_subject
    lines = [
        "# chart_spec census (issue #110 gate evidence)",
        "",
        f"| subject | questions | with chart_spec | chart | table | geometry "
        f"| scenario_card | other | gate (>= {n}) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for subject in sorted(set(result.per_subject) | set(GATE_SUBJECTS)):
        c = result.per_subject.get(subject, SubjectCensus())
        gate = "MET" if c.questions >= n else "NOT MET"
        cat = c.specs_by_category
        lines.append(
            f"| {subject} | {c.questions} | {c.questions_with_spec} | {cat.get('chart', 0)} "
            f"| {cat.get('table', 0)} | {cat.get('geometry', 0)} "
            f"| {cat.get('scenario_card', 0)} | {cat.get('other', 0)} | {gate} |"
        )
    lines += ["", "## render_mode distribution", "", "| subject | render_mode | count |",
              "| --- | --- | --- |"]
    for subject in sorted(result.per_subject):
        for mode, count in sorted(result.per_subject[subject].specs_by_render_mode.items()):
            lines.append(f"| {subject} | {mode} | {count} |")
    verdict = "MET" if result.gate_met else "NOT MET"
    lines += [
        "",
        f"**GATE {verdict}** — requires >= {n} questions per subject "
        f"for {', '.join(GATE_SUBJECTS)}.",
    ]
    return "\n".join(lines)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/server/test_census_chart_specs.py tests/test_analyze_chart_spec_coverage.py -v`
Expected: PASS — 3 new census tests + 8 coverage tests (7 existing + 1 new) green.

- [ ] **Step 7: Lint the touched files**

Run: `uv run ruff check scripts/census_chart_specs.py scripts/analyze_chart_spec_coverage.py tests/server/test_census_chart_specs.py tests/test_analyze_chart_spec_coverage.py`
Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add scripts/census_chart_specs.py scripts/analyze_chart_spec_coverage.py \
  tests/server/test_census_chart_specs.py tests/test_analyze_chart_spec_coverage.py
git commit -m "feat: chart_spec census aggregation over generation records (#110 Part A)"
```

---

### Task 2: Census DB loader + CLI entry (`--check` gate mode)

**Files:**
- Modify: `scripts/census_chart_specs.py`
- Modify: `tests/server/test_census_chart_specs.py`

**Interfaces:**
- Consumes: `server.models.GenerationRecord` (columns `subject: str`, `question_json: dict`), `server.models.Base`, `server.models.User`; `summarize_census` / `render_census_markdown` from Task 1.
- Produces (used by Task 3): `default_database_url() -> str` (env `DATABASE_URL`, fallback `sqlite+aiosqlite:///./dev.db` — same default as `server/db.py`), `load_records(database_url: str) -> list[tuple[str, dict]]` (async), `main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/server/test_census_chart_specs.py` (and extend its imports):

```python
import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from scripts.census_chart_specs import default_database_url, load_records, main
from server.models import Base, GenerationRecord, User


def _seed_db(tmp_path) -> str:
    """Create an aiosqlite DB with one math generation record; return its URL."""
    url = f"sqlite+aiosqlite:///{tmp_path}/census.db"
    engine = create_async_engine(url)

    async def init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        user_id = uuid.uuid4()
        async with session_local() as s:
            s.add(User(id=user_id, email="census@example.com"))
            s.add(
                GenerationRecord(
                    user_id=user_id,
                    subject="math",
                    question_id="q1",
                    params_json={},
                    question_json={
                        "id": "q1",
                        "chart_spec": {
                            "render_mode": "chart",
                            "chart_type": "histogram",
                            "data": {},
                        },
                    },
                    image_files=[],
                )
            )
            await s.commit()
        await engine.dispose()

    asyncio.run(init())
    return url


def test_default_database_url_reads_env(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert default_database_url() == "sqlite+aiosqlite:///./dev.db"
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./other.db")
    assert default_database_url() == "sqlite+aiosqlite:///./other.db"


def test_load_records_reads_subject_and_question_json(tmp_path) -> None:
    url = _seed_db(tmp_path)
    rows = asyncio.run(load_records(url))
    assert len(rows) == 1
    subject, item = rows[0]
    assert subject == "math"
    assert item["chart_spec"]["chart_type"] == "histogram"


def test_main_prints_markdown_and_check_gates_exit_code(tmp_path, capsys) -> None:
    url = _seed_db(tmp_path)
    # Without --check: always exit 0, markdown printed.
    assert main(["--database-url", url]) == 0
    out = capsys.readouterr().out
    assert "| math | 1 | 1 |" in out
    assert "GATE NOT MET" in out
    # With --check: gate unmet (SS/NS have 0 < 1 questions) -> exit 1.
    assert main(["--database-url", url, "--min-per-subject", "1", "--check"]) == 1
```

Note: `--min-per-subject 1 --check` still exits 1 because social_studies and natural_sciences have zero rows — the gate needs **all three** subjects at threshold.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/server/test_census_chart_specs.py -v`
Expected: FAIL — `ImportError: cannot import name 'default_database_url'`.

- [ ] **Step 3: Implement loader + CLI**

Append to `scripts/census_chart_specs.py` — and add `import os` to the module's import block (alphabetically, after `import asyncio`). SQLAlchemy imports stay **inside** the function so importing the module never requires web extras:

```python
def default_database_url() -> str:
    """Same default as server/db.py: env DATABASE_URL or the local aiosqlite dev DB."""
    return os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")


async def load_records(database_url: str) -> list[tuple[str, dict]]:
    """Load every (subject, question_json) row from generation_records."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine

    from server.models import GenerationRecord

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                select(GenerationRecord.subject, GenerationRecord.question_json)
            )
            return [(row[0], row[1]) for row in result.all()]
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Census of chart_spec usage across generation_records (issue #110 gate)."
    )
    parser.add_argument(
        "--database-url",
        default=default_database_url(),
        help="SQLAlchemy async URL (default: env DATABASE_URL or the local dev.db)",
    )
    parser.add_argument("--min-per-subject", type=int, default=DEFAULT_MIN_PER_SUBJECT)
    parser.add_argument(
        "--check", action="store_true", help="exit 1 while the census gate is not met"
    )
    args = parser.parse_args(argv)

    rows = asyncio.run(load_records(args.database_url))
    result = summarize_census(rows, min_per_subject=args.min_per_subject)
    print(render_census_markdown(result))
    if args.check and not result.gate_met:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/server/test_census_chart_specs.py -v`
Expected: PASS — all 6 census tests green.

- [ ] **Step 5: Smoke-run the script against an empty local DB**

Run: `uv run python scripts/census_chart_specs.py --database-url "sqlite+aiosqlite:///$(mktemp -d)/empty.db" --check; echo "exit=$?"`
Expected: FAILS at table read? No — SQLAlchemy raises `no such table: generation_records` on a truly empty DB, which is the correct loud failure for a wrong URL. Point it at the real dev DB instead if one exists (`uv run python scripts/census_chart_specs.py`), or accept the traceback as proof the URL plumbing works. Do not "fix" this by silently returning zero rows.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check scripts/census_chart_specs.py tests/server/test_census_chart_specs.py
git add scripts/census_chart_specs.py tests/server/test_census_chart_specs.py
git commit -m "feat: census CLI with DB loader and --check gate mode (#110 Part A)"
```

---

### Task 3: Fidelity manifest builder (server-side renders)

**Files:**
- Create: `scripts/build_fidelity_manifest.py`
- Create: `tests/test_build_fidelity_manifest.py`

**Interfaces:**
- Consumes: `classify_spec` (Task 1), `default_database_url` / `load_records` (Task 2), `src.renderer.render_image(image_spec, output_path, question_text=..., html_renderer=..., llm_client=..., image_generation_mode="html")`, `src.html_renderer.PlaywrightRenderer` (context manager), `src.llm_client.LLMClient(config)`, `src.config.Config.from_env()`.
- Produces (consumed by Task 4's web page): `fidelity/manifest.json` — a JSON array of `{"id": str, "subject": str, "category": str, "spec": dict, "question_text": str, "server_png_base64": str | null}`. Also `select_illustrative_specs(rows, limit_per_subject=12) -> list[dict]` and `build_manifest(entries, render_png) -> list[dict]` for tests.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_build_fidelity_manifest.py` (module-level imports of the script are safe: its SQLAlchemy/renderer imports are lazy):

```python
"""Tests for the fidelity-manifest builder (issue #110 gate evidence)."""

from __future__ import annotations

import base64

from scripts.build_fidelity_manifest import (
    _question_text,
    build_manifest,
    select_illustrative_specs,
)


def _ss_row() -> tuple[str, dict]:
    return (
        "social_studies",
        {
            "id": "ss_q1",
            "文本": "題組文本",
            "chart_spec": {"render_mode": "html", "description": "海報", "data": {}},
            "subquestions": [
                {
                    "序號": 2,
                    "chart_spec": {
                        "render_mode": "html",
                        "data": {"rows": [["1"]], "columns": ["a"]},
                    },
                },
            ],
        },
    )


def test_select_skips_chart_mode_and_builds_subquestion_ids() -> None:
    math_row = (
        "math",
        {
            "id": "m1",
            "題目": ["題幹"],
            "chart_spec": {"render_mode": "chart", "chart_type": "histogram", "data": {}},
        },
    )
    entries = select_illustrative_specs([math_row, _ss_row()], limit_per_subject=12)
    assert [e["id"] for e in entries] == ["ss_q1", "ss_q1_sq2"]
    assert entries[0]["subject"] == "social_studies"
    assert entries[1]["category"] == "table"
    assert entries[0]["question_text"] == "題組文本"


def test_select_respects_per_subject_limit() -> None:
    rows = [_ss_row(), _ss_row(), _ss_row()]
    entries = select_illustrative_specs(rows, limit_per_subject=2)
    assert len(entries) == 2


def test_question_text_prefers_文本_then_joins_題目() -> None:
    assert _question_text({"文本": "abc", "題目": ["x"]}) == "abc"
    assert _question_text({"題目": ["x", "y"]}) == "x\ny"
    assert _question_text({}) == ""


def test_build_manifest_encodes_png_and_marks_failures_null() -> None:
    entries = [
        {"id": "a", "subject": "math", "category": "other", "spec": {}, "question_text": ""},
        {"id": "b", "subject": "math", "category": "other", "spec": {}, "question_text": ""},
    ]
    calls: list[str] = []

    def fake_render(spec: dict, question_text: str) -> bytes | None:
        calls.append("call")
        return b"png-bytes" if len(calls) == 1 else None

    manifest = build_manifest(entries, fake_render)
    assert manifest[0]["server_png_base64"] == base64.b64encode(b"png-bytes").decode("ascii")
    assert manifest[1]["server_png_base64"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_build_fidelity_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.build_fidelity_manifest'`.

- [ ] **Step 3: Implement the script**

Create `scripts/build_fidelity_manifest.py`:

```python
"""Build the side-by-side fidelity manifest (issue #110 gate evidence, Part A).

Picks illustrative chart_specs (render_mode != "chart") out of generation_records,
renders each through the current server path (LLM-HTML + Playwright, see
docs/figure-rendering-policy.md) and writes fidelity/manifest.json. Load that
file on the web app's /fidelity-compare page (frontend built with
VITE_ENABLE_FRONTEND_TS_RENDERER=1) to rate server PNG vs frontend TS renders.

Run (needs LLM_API_KEY and a Playwright chromium: `uv run playwright install chromium`):
    DATABASE_URL=<url> uv run python scripts/build_fidelity_manifest.py --limit 12
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analyze_chart_spec_coverage import classify_spec  # noqa: E402
from scripts.census_chart_specs import default_database_url, load_records  # noqa: E402


def _question_text(item: dict) -> str:
    """Context passed to the HTML generator: 文本 (題組) or joined 題目 (math)."""
    text = item.get("文本")
    if isinstance(text, str) and text:
        return text
    body = item.get("題目")
    if isinstance(body, list):
        return "\n".join(str(part) for part in body)
    return ""


def select_illustrative_specs(
    rows: list[tuple[str, dict]], limit_per_subject: int = 12
) -> list[dict]:
    """Pick up to limit_per_subject illustrative specs (render_mode != "chart") per subject."""
    picked: list[dict] = []
    counts: Counter = Counter()
    for subject, item in rows:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("id") or "unknown")
        candidates: list[tuple[str, object]] = [(qid, item.get("chart_spec"))]
        for sq in item.get("subquestions") or []:
            if isinstance(sq, dict):
                candidates.append((f"{qid}_sq{sq.get('序號', '?')}", sq.get("chart_spec")))
        for spec_id, spec in candidates:
            if not isinstance(spec, dict):
                continue
            if (spec.get("render_mode") or "").lower() == "chart":
                continue
            if counts[subject] >= limit_per_subject:
                continue
            counts[subject] += 1
            picked.append(
                {
                    "id": spec_id,
                    "subject": subject,
                    "category": classify_spec(spec),
                    "spec": spec,
                    "question_text": _question_text(item)[:300],
                }
            )
    return picked


def build_manifest(
    entries: list[dict], render_png: Callable[[dict, str], bytes | None]
) -> list[dict]:
    """Attach server_png_base64 to every entry via the injected renderer."""
    manifest: list[dict] = []
    for entry in entries:
        png = render_png(entry["spec"], entry["question_text"])
        encoded = base64.b64encode(png).decode("ascii") if png else None
        manifest.append({**entry, "server_png_base64": encoded})
    return manifest


def _server_renderer(html_renderer, llm_client) -> Callable[[dict, str], bytes | None]:
    """Real renderer: the exact server path (LLM-HTML + Playwright screenshot)."""
    from src.renderer import render_image

    def render_png(spec: dict, question_text: str) -> bytes | None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fig.png"
            rendered = render_image(
                spec,
                out,
                question_text=question_text,
                html_renderer=html_renderer,
                llm_client=llm_client,
                image_generation_mode="html",
            )
            if rendered is None:
                return None
            return Path(rendered).read_bytes()

    return render_png


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render illustrative chart_specs server-side into fidelity/manifest.json."
    )
    parser.add_argument("--database-url", default=default_database_url())
    parser.add_argument(
        "--limit", type=int, default=12, help="max illustrative specs per subject"
    )
    parser.add_argument("--output", type=Path, default=Path("fidelity/manifest.json"))
    args = parser.parse_args(argv)

    from src.config import Config
    from src.html_renderer import PlaywrightRenderer
    from src.llm_client import LLMClient

    config = Config.from_env()
    if not config.api_key:
        print("error: LLM_API_KEY is required (HTML generation uses the LLM)", file=sys.stderr)
        return 2

    rows = asyncio.run(load_records(args.database_url))
    entries = select_illustrative_specs(rows, limit_per_subject=args.limit)
    if not entries:
        print("no illustrative chart_spec entries found — generate questions first",
              file=sys.stderr)
        return 1

    client = LLMClient(config)
    with PlaywrightRenderer() as renderer:
        manifest = build_manifest(entries, _server_renderer(renderer, client))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for m in manifest if m["server_png_base64"])
    print(f"wrote {len(manifest)} entries ({ok} with server PNG) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_build_fidelity_manifest.py -v`
Expected: PASS — 4 tests green.

- [ ] **Step 5: Keep manifests out of git**

Append to `.gitignore` (repo root):

```
fidelity/
```

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check scripts/build_fidelity_manifest.py tests/test_build_fidelity_manifest.py
git add scripts/build_fidelity_manifest.py tests/test_build_fidelity_manifest.py .gitignore
git commit -m "feat: fidelity manifest builder rendering illustrative specs server-side (#110 Part A)"
```

---

### Task 4: Fidelity comparison web page (`/fidelity-compare`)

**Files:**
- Create: `web/src/pages/FidelityComparePage.tsx`
- Create: `web/src/pages/FidelityComparePage.test.tsx`
- Modify: `web/src/App.tsx`

**Interfaces:**
- Consumes: `FigureRenderer` (default export), `classifySpec(spec)`, `isFrontendTsEnabled()`, `type ChartSpecInput` from `web/src/components/FigureRenderer.tsx`; the manifest JSON produced by Task 3.
- Produces: route `/fidelity-compare`; exports `parseManifest(text: string): FidelityEntry[]`, `toMarkdownTable(entries: FidelityEntry[], verdicts: Record<string, Verdict>): string`, `type Verdict = "unrated" | "match" | "minor-diff" | "broken"`, `interface FidelityEntry`.

All commands in this task run from `/workspace/exam-generation/web/`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/pages/FidelityComparePage.test.tsx`:

```tsx
import { describe, expect, it, vi, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import FidelityComparePage, {
  parseManifest,
  toMarkdownTable,
  type FidelityEntry,
} from "./FidelityComparePage";

afterEach(() => {
  vi.unstubAllEnvs();
});

const tableEntry: FidelityEntry = {
  id: "q1",
  subject: "social_studies",
  category: "table",
  spec: {
    render_mode: "html",
    description: "課表",
    data: { columns: ["時段"], rows: [["9:00"]] },
  },
  server_png_base64: "aGVsbG8=",
};

describe("parseManifest", () => {
  it("parses a valid manifest array", () => {
    expect(parseManifest(JSON.stringify([tableEntry]))).toHaveLength(1);
  });

  it("throws when the manifest is not an array", () => {
    expect(() => parseManifest("{}")).toThrow("manifest must be a JSON array");
  });

  it("throws when an entry is missing id or spec", () => {
    expect(() => parseManifest(JSON.stringify([{ subject: "math" }]))).toThrow(
      "missing id or spec",
    );
  });
});

describe("toMarkdownTable", () => {
  it("renders one row per entry with shape and verdict", () => {
    const md = toMarkdownTable([tableEntry], { q1: "match" });
    expect(md).toContain("| 1 | q1 | social_studies | table | TS | match |");
  });

  it("marks unsupported specs as fallback and defaults verdict to unrated", () => {
    const entry: FidelityEntry = {
      ...tableEntry,
      id: "q2",
      spec: { render_mode: "html", description: "自由描述", data: {} },
    };
    const md = toMarkdownTable([entry], {});
    expect(md).toContain(
      "| 1 | q2 | social_studies | unsupported | fallback (PNG) | unrated |",
    );
  });
});

describe("FidelityComparePage", () => {
  it("shows the disabled note when the flag is off", () => {
    vi.stubEnv("VITE_ENABLE_FRONTEND_TS_RENDERER", "");
    render(<FidelityComparePage />);
    expect(screen.getByText(/disabled/i)).toBeInTheDocument();
  });

  it("renders side-by-side rows after loading a manifest file", async () => {
    vi.stubEnv("VITE_ENABLE_FRONTEND_TS_RENDERER", "1");
    render(<FidelityComparePage />);
    const file = new File([JSON.stringify([tableEntry])], "manifest.json", {
      type: "application/json",
    });
    fireEvent.change(screen.getByLabelText("Load manifest"), {
      target: { files: [file] },
    });
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.getByAltText("server render of q1")).toHaveAttribute(
      "src",
      "data:image/png;base64,aGVsbG8=",
    );
    expect(screen.getByLabelText("fidelity markdown")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- src/pages/FidelityComparePage.test.tsx`
Expected: FAIL — cannot resolve `./FidelityComparePage`.

- [ ] **Step 3: Implement the page**

Create `web/src/pages/FidelityComparePage.tsx`:

```tsx
/**
 * Operator harness for the issue #110 fidelity comparison (Part A gate evidence).
 *
 * Load fidelity/manifest.json (built by scripts/build_fidelity_manifest.py),
 * eyeball server PNG vs frontend TS render for every illustrative spec, rate
 * each pair, and paste the exported Markdown into
 * docs/figure-rendering-evaluation.md. Gated behind
 * VITE_ENABLE_FRONTEND_TS_RENDERER like the FigureRenderer prototype itself.
 */

import { useState } from "react";
import FigureRenderer, {
  classifySpec,
  isFrontendTsEnabled,
  type ChartSpecInput,
} from "../components/FigureRenderer";

export interface FidelityEntry {
  id: string;
  subject: string;
  category: string;
  spec: ChartSpecInput;
  server_png_base64: string | null;
  question_text?: string;
}

export type Verdict = "unrated" | "match" | "minor-diff" | "broken";

// eslint-disable-next-line react-refresh/only-export-components -- utility export co-located with the harness page by design
export function parseManifest(text: string): FidelityEntry[] {
  const raw: unknown = JSON.parse(text);
  if (!Array.isArray(raw)) throw new Error("manifest must be a JSON array");
  return raw.map((entry, i) => {
    const e = entry as Partial<FidelityEntry> | null;
    if (!e || typeof e !== "object" || typeof e.id !== "string" || !e.spec) {
      throw new Error(`manifest entry ${i} is missing id or spec`);
    }
    return e as FidelityEntry;
  });
}

// eslint-disable-next-line react-refresh/only-export-components -- utility export co-located with the harness page by design
export function toMarkdownTable(
  entries: FidelityEntry[],
  verdicts: Record<string, Verdict>,
): string {
  const lines = [
    "| # | id | subject | shape | TS render | verdict |",
    "| --- | --- | --- | --- | --- | --- |",
  ];
  entries.forEach((e, i) => {
    const shape = classifySpec(e.spec);
    const ts = shape === "unsupported" ? "fallback (PNG)" : "TS";
    lines.push(
      `| ${i + 1} | ${e.id} | ${e.subject} | ${shape} | ${ts} | ${verdicts[e.id] ?? "unrated"} |`,
    );
  });
  return lines.join("\n");
}

export default function FidelityComparePage() {
  const [entries, setEntries] = useState<FidelityEntry[]>([]);
  const [verdicts, setVerdicts] = useState<Record<string, Verdict>>({});
  const [error, setError] = useState("");

  if (!isFrontendTsEnabled()) {
    return (
      <div className="mx-auto max-w-3xl p-6 text-sm text-gray-600">
        Fidelity harness is disabled. Rebuild the frontend with
        VITE_ENABLE_FRONTEND_TS_RENDERER=1 to use this page.
      </div>
    );
  }

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    try {
      setEntries(parseManifest(await file.text()));
      setError("");
    } catch (e) {
      setEntries([]);
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <h1 className="text-lg font-bold">Figure fidelity comparison (issue #110)</h1>
      <p className="text-sm text-gray-600">
        Load fidelity/manifest.json produced by scripts/build_fidelity_manifest.py, rate
        each pair, then paste the Markdown below into docs/figure-rendering-evaluation.md.
      </p>
      <input
        type="file"
        accept="application/json,.json"
        aria-label="Load manifest"
        onChange={(e) => void onFile(e.target.files?.[0])}
      />
      {error && <div className="text-sm text-red-600">{error}</div>}
      {entries.map((entry) => (
        <div key={entry.id} className="rounded border border-gray-200 p-3">
          <div className="mb-2 flex items-center gap-3 text-sm">
            <span className="font-mono">{entry.id}</span>
            <span>{entry.subject}</span>
            <span className="text-gray-500">{classifySpec(entry.spec)}</span>
            <select
              aria-label={`verdict for ${entry.id}`}
              value={verdicts[entry.id] ?? "unrated"}
              onChange={(e) =>
                setVerdicts((v) => ({ ...v, [entry.id]: e.target.value as Verdict }))
              }
              className="ml-auto rounded border border-gray-300 px-2 py-1"
            >
              <option value="unrated">unrated</option>
              <option value="match">match</option>
              <option value="minor-diff">minor-diff</option>
              <option value="broken">broken</option>
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="mb-1 text-xs text-gray-500">server PNG (Playwright)</div>
              {entry.server_png_base64 ? (
                <img
                  src={`data:image/png;base64,${entry.server_png_base64}`}
                  alt={`server render of ${entry.id}`}
                  className="max-w-full rounded border border-gray-200"
                />
              ) : (
                <div className="text-xs text-red-600">no server PNG (render failed)</div>
              )}
            </div>
            <div>
              <div className="mb-1 text-xs text-gray-500">frontend TS prototype</div>
              <FigureRenderer spec={entry.spec} alt={`TS render of ${entry.id}`} />
            </div>
          </div>
        </div>
      ))}
      {entries.length > 0 && (
        <textarea
          readOnly
          aria-label="fidelity markdown"
          className="h-40 w-full rounded border border-gray-300 p-2 font-mono text-xs"
          value={toMarkdownTable(entries, verdicts)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- src/pages/FidelityComparePage.test.tsx`
Expected: PASS — 7 tests green.

- [ ] **Step 5: Add the route**

Modify `web/src/App.tsx` — add the import after the `SubjectSelectPage` import and the route before the closing `</Routes>` (no AuthGuard: the page calls no APIs and only reads a locally chosen file; it renders a disabled note unless the build flag is set):

```tsx
import FidelityComparePage from "./pages/FidelityComparePage";
```

```tsx
        <Route path="/fidelity-compare" element={<FidelityComparePage />} />
```

- [ ] **Step 6: Full web suite, scoped lint, build**

Run: `npm test && npx eslint src/pages/FidelityComparePage.tsx src/pages/FidelityComparePage.test.tsx src/App.tsx && npm run build`
Expected: all vitest files pass; no eslint errors in the three named files; `tsc -b && vite build` succeeds.

- [ ] **Step 7: Commit**

```bash
cd /workspace/exam-generation
git add web/src/pages/FidelityComparePage.tsx web/src/pages/FidelityComparePage.test.tsx web/src/App.tsx
git commit -m "feat(web): /fidelity-compare harness for server-vs-TS figure review (#110 Part A)"
```

---

### Task 5: Document the gate workflow + GO/NO-GO re-evaluation

**Files:**
- Modify: `docs/figure-rendering-policy.md`
- Modify: `docs/figure-rendering-evaluation.md`

**Interfaces:**
- Consumes: the commands shipped in Tasks 1–4.
- Produces: the authoritative procedure Part B's gate references.

- [ ] **Step 1: Fix the stale test names in the policy doc's Enforcement section**

In `docs/figure-rendering-policy.md`, replace the two bullet points under `## Enforcement` (lines 65–71) with the names that actually exist in `tests/test_figure_rendering_policy.py`:

```markdown
- `tests/test_figure_rendering_policy.py::test_plain_text_bans_chart_spec`,
  `::test_illustrative_content_routes_to_html`, and
  `::test_quantitative_content_routes_to_chart_and_html_for_tables` assert the
  `CONTENT_TYPE_INSTRUCTIONS` strings for each of the three subjects contain
  the correct `render_mode: "…"` fragment.
- `tests/test_figure_rendering_policy.py::test_dispatch_chart_render_mode_uses_matplotlib`,
  `::test_dispatch_html_render_mode_uses_playwright`,
  `::test_dispatch_gpt_image_mode_bypasses_render_mode`, and
  `::test_dispatch_unknown_render_mode_returns_none` fixture-test that
  `render_image()` in `src/renderer.py` dispatches each ImageSpec to the
  intended renderer.
```

- [ ] **Step 2: Add the gate-evidence section to the policy doc**

Insert the following new section into `docs/figure-rendering-policy.md`, directly after the `## Phase A outcome (issue #108)` section (i.e. between the NO-GO bullet and `## What each subject's prompt must instruct`):

````markdown
## Gate evidence collection and re-evaluation (issue #110)

Two tools collect the evidence the NO-GO above requires. Both are safe to run
against staging or production data at any time.

1. **Production census** — classifies every `chart_spec` stored in
   `generation_records` (per-user history, `server/models.py`):

   ```bash
   DATABASE_URL=<staging-or-prod-url> uv run python scripts/census_chart_specs.py
   # gate-check mode (exit 1 while the gate is unmet):
   DATABASE_URL=<url> uv run python scripts/census_chart_specs.py --check
   ```

   The gate requires **>= 30 questions per subject** (math, social_studies,
   natural_sciences). Paste the emitted Markdown into
   `docs/figure-rendering-evaluation.md` under "Historical coverage".

2. **Live fidelity comparison** — renders every illustrative spec through the
   server path and reviews it side-by-side with the frontend TS prototype:

   ```bash
   DATABASE_URL=<url> uv run python scripts/build_fidelity_manifest.py --limit 12
   ```

   Then open `/fidelity-compare` in a frontend built with
   `VITE_ENABLE_FRONTEND_TS_RENDERER=1`, load `fidelity/manifest.json`, rate
   each pair (match / minor-diff / broken), and paste the exported Markdown
   into `docs/figure-rendering-evaluation.md` under "Fidelity". The measured
   fallback rate is the share of rows marked `fallback (PNG)`.

### Re-running Phase A

When the census gate is MET and the fidelity table holds measured verdicts,
the operator re-evaluates:

- **GO / HYBRID** — record the dated decision in this file (replacing the
  NO-GO bullet above), then execute Part B of
  `docs/superpowers/plans/2026-07-18-frontend-ts-render-mode.md` in its task
  order: this policy file first, then the context-builder docstrings, then the
  `CONTENT_TYPE_INSTRUCTIONS` tables, per the update rule this repo codifies.
- **NO-GO again** — record the dated decision in
  `docs/figure-rendering-evaluation.md` and leave `render_mode` unchanged.

The decision is made by a human operator, not by an agent: an agent may
prepare the evidence but must not self-declare GO.
````

- [ ] **Step 3: Point the evaluation doc at the new tooling**

In `docs/figure-rendering-evaluation.md`, append this paragraph to the end of the `## Decision` section:

```markdown
**Gate tooling (added 2026-07-18, issue #110 Part A):** the census now reads
production `generation_records` via `scripts/census_chart_specs.py` (`--check`
exits 1 while any subject is below 30 questions), and the live fidelity
comparison is performed with `scripts/build_fidelity_manifest.py` plus the
web `/fidelity-compare` page. Replace the "Unmeasured" blocks above with the
Markdown those tools emit when re-running Phase A.
```

- [ ] **Step 4: Verify nothing broke**

Run: `uv run pytest tests/test_figure_rendering_policy.py tests/test_context_builder_docstrings.py -v`
Expected: PASS — 17 tests green (13 policy + 4 docstring; docs changes must not break them).

- [ ] **Step 5: Commit**

```bash
git add docs/figure-rendering-policy.md docs/figure-rendering-evaluation.md
git commit -m "docs: codify #110 gate-evidence workflow and Phase A re-evaluation procedure"
```

Part A is complete after this task. Stop here until the operator records GO.

---

# PART B — `frontend_ts` rollout (GATED — requires operator-recorded GO)

Every task below is blocked by the Global Constraints gate. Execute on a fresh branch `feat/110-frontend-ts-render-mode` off the then-current `staging`, and re-verify the file/line references below against that state before editing (they are correct as of 2026-07-18 staging, commit 1e26aa8).

### Task 6: Record GO + reroute the policy doc (docs FIRST per the update rule)

**Files:**
- Modify: `docs/figure-rendering-policy.md`

**Interfaces:**
- Consumes: the operator's GO decision + the filled-in census/fidelity numbers in `docs/figure-rendering-evaluation.md`.
- Produces: the authoritative `frontend_ts` routing statement Tasks 7–12 implement.

- [ ] **Step 1: Record the decision in the Phase A outcome section**

In `docs/figure-rendering-policy.md`, replace the `**NO-GO (for now)**: …` bullet (the whole bullet under `## Phase A outcome (issue #108)`) with the following, copying the decision date and the two evidence figures (per-subject question counts, measured fallback rate) from the operator's entries in `docs/figure-rendering-evaluation.md`:

```markdown
- **GO** (recorded by the operator on the date noted in
  `docs/figure-rendering-evaluation.md`, with the census gate MET at >= 30
  questions per subject and the measured fallback rate from the
  `/fidelity-compare` review): `render_mode` is extended with
  `"frontend_ts"` for illustrative figures whose display can be done
  client-side. Verifier and ODT export still consume the server-side PNG, so
  illustrative specs keep producing one — the frontend TS renderer replaces
  the on-page `<img>` display only. `"html"` remains permanently accepted as
  a legacy alias for already-generated questions; prompts must no longer
  instruct the model to emit it.
```

- [ ] **Step 2: Update the routing-rule table**

Replace the illustrative row of the table under `## The rule`:

```markdown
| Illustrative figures | 幾何示意圖, 座標平面, 數線, 表格, 菜單, 廣告, 海報, 情境卡, 流程圖 | `"frontend_ts"` (`"html"` = legacy alias, read-only) | Display: frontend TS renderer (`web/src/components/FigureRenderer.tsx`); server PNG for verifier/ODT: LLM-HTML + Playwright (`src/renderer.py::_generate_html_via_llm` + `src/html_renderer.py`) |
```

- [ ] **Step 3: Update the per-content-type instruction table**

Under `## What each subject's prompt must instruct`, replace the `含圖片` and `graphs/charts/tables` rows:

```markdown
| `含圖片` | Emit `chart_spec` with `render_mode: "frontend_ts"` (illustrative path; never emit the legacy alias for new questions). |
| `graphs/charts/tables` | Emit `chart_spec` with `render_mode: "chart"` when a listed statistical chart applies; otherwise `render_mode: "frontend_ts"` for tables. |
```

- [ ] **Step 4: Update the Enforcement section**

Replace the first Enforcement bullet (written in Task 5 Step 1) so it names the post-rollout tests Task 9 introduces:

```markdown
- `tests/test_figure_rendering_policy.py::test_plain_text_bans_chart_spec`,
  `::test_illustrative_content_routes_to_frontend_ts`, and
  `::test_quantitative_content_routes_to_chart_and_frontend_ts_for_tables`
  assert the `CONTENT_TYPE_INSTRUCTIONS` strings for each of the three
  subjects contain the correct `render_mode: "…"` fragment.
```

And append one dispatch bullet:

```markdown
- `tests/test_figure_rendering_policy.py::test_dispatch_frontend_ts_render_mode_uses_playwright_for_server_png`
  asserts `render_mode: "frontend_ts"` still produces a server-side PNG via
  the LLM-HTML + Playwright path.
```

- [ ] **Step 5: Verify + commit**

Run: `uv run pytest tests/test_figure_rendering_policy.py tests/test_context_builder_docstrings.py -v`
Expected: PASS (doc-only change; the code tests referenced by name arrive in Tasks 8–9).

```bash
git add docs/figure-rendering-policy.md
git commit -m "docs: record Phase A GO and reroute illustrative figures to frontend_ts (#110)"
```

---

### Task 7: Context-builder docstrings (second in the update order)

**Files:**
- Modify: `src/context_builder.py:1-8`
- Modify: `src/social_studies/context_builder.py:1-10`
- Modify: `src/natural_sciences/context_builder.py:2-10`

**Interfaces:**
- Consumes: the policy wording from Task 6.
- Produces: docstrings Task 9's instruction tables must agree with. `tests/test_context_builder_docstrings.py` keeps guarding the `docs/figure-rendering-policy.md` citation.

- [ ] **Step 1: Replace the math module docstring**

`src/context_builder.py` — replace the module docstring (lines 1–8) with:

```python
"""Assemble LLM prompts with curriculum context and few-shot examples.

Figure routing: any `chart_spec` this module instructs the model to emit must
follow the rule in ``docs/figure-rendering-policy.md`` — precise/quantitative
statistical charts use ``render_mode: "chart"`` (matplotlib); illustrative
figures use ``render_mode: "frontend_ts"`` (client-side display; the server
still renders a Playwright PNG for the verifier and ODT export; ``"html"`` is
a read-only legacy alias). See ``CONTENT_TYPE_INSTRUCTIONS`` below for the
per-``題目內容類型`` mapping.
"""
```

- [ ] **Step 2: Replace the social-studies module docstring**

`src/social_studies/context_builder.py` — replace lines 1–10 with:

```python
"""Assemble LLM prompts for 108課綱 社會領域素養導向 question generation.

Figure routing: any `chart_spec` this module instructs the model to emit
(top-level 題組 material or per-小題 supplements) must follow the rule in
``docs/figure-rendering-policy.md`` — precise/quantitative statistical charts
use ``render_mode: "chart"`` (matplotlib); illustrative figures — maps,
posters, tables, scenario cards — use ``render_mode: "frontend_ts"``
(client-side display; the server still renders a Playwright PNG for the
verifier and ODT export; ``"html"`` is a read-only legacy alias). See
``CONTENT_TYPE_INSTRUCTIONS`` below for the per-``文本素材類型`` mapping.
"""
```

- [ ] **Step 3: Replace the natural-sciences module docstring**

`src/natural_sciences/context_builder.py` — keep line 1 (`# ruff: noqa: E501`) and replace the docstring (lines 2–10) with:

```python
"""Assemble LLM prompts for PISA Science + 108課綱自然科學 question generation.

Figure routing: any `chart_spec` this module instructs the model to emit
must follow the rule in ``docs/figure-rendering-policy.md`` —
precise/quantitative statistical charts use ``render_mode: "chart"``
(matplotlib); illustrative figures — 實驗裝置圖, 模型圖, 流程圖, 標籤圖,
data tables — use ``render_mode: "frontend_ts"`` (client-side display; the
server still renders a Playwright PNG for the verifier and ODT export;
``"html"`` is a read-only legacy alias). See ``CONTENT_TYPE_INSTRUCTIONS``
below for the per-``題目內容類型`` mapping.
"""
```

- [ ] **Step 4: Verify + commit**

Run: `uv run pytest tests/test_context_builder_docstrings.py -v`
Expected: PASS — 4 tests green (the citation anchor is unchanged).

```bash
git add src/context_builder.py src/social_studies/context_builder.py src/natural_sciences/context_builder.py
git commit -m "docs: cite frontend_ts routing in context-builder docstrings (#110)"
```

---

### Task 8: `ImageSpec` literal + renderer dispatch for `frontend_ts`

**Files:**
- Modify: `src/schemas.py:47-64` (`ImageSpec`)
- Modify: `src/social_studies/schemas.py:23-31` (`ImageSpec`)
- Modify: `src/natural_sciences/schemas.py:20-30` (`ImageSpec`)
- Modify: `src/renderer.py:271-322` (`render_image`)
- Test: `tests/test_figure_rendering_policy.py`

**Interfaces:**
- Consumes: dispatch-test helpers `_RecordingHtmlRenderer` / `_RecordingLlmClient` already defined in `tests/test_figure_rendering_policy.py:61-81`.
- Produces: `render_mode: Literal["chart", "html", "frontend_ts"]` on all three `ImageSpec` classes; `render_image()` treats `"frontend_ts"` identically to `"html"` (server-side PNG via LLM-HTML + Playwright). Tasks 9 and 11 rely on `ImageSpec(render_mode="frontend_ts", ...)` validating.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_figure_rendering_policy.py`:

```python
def test_imagespec_accepts_frontend_ts_across_subjects() -> None:
    from src.natural_sciences.schemas import ImageSpec as NsImageSpec
    from src.schemas import ImageSpec as MathImageSpec
    from src.social_studies.schemas import ImageSpec as SsImageSpec

    for cls in (MathImageSpec, SsImageSpec, NsImageSpec):
        spec = cls(render_mode="frontend_ts", description="示意圖")
        assert spec.render_mode == "frontend_ts"


def test_dispatch_frontend_ts_render_mode_uses_playwright_for_server_png(tmp_path) -> None:
    from src import renderer

    html_renderer = _RecordingHtmlRenderer()
    llm_client = _RecordingLlmClient()

    out = tmp_path / "ts.png"
    result = renderer.render_image(
        {"render_mode": "frontend_ts", "description": "幾何示意圖", "data": {"shapes": []}},
        out,
        html_renderer=html_renderer,
        llm_client=llm_client,
        image_generation_mode="html",
    )

    # frontend_ts only changes the on-page display; the server still
    # produces a Playwright PNG for the verifier and ODT export.
    assert result == str(out)
    assert len(llm_client.html_calls) == 1
    assert len(html_renderer.calls) == 1
    assert llm_client.image_calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_figure_rendering_policy.py -v`
Expected: FAIL — `ValidationError` (`Input should be 'chart' or 'html'`) and the dispatch test returns `None` (unknown render_mode).

- [ ] **Step 3: Extend the three `ImageSpec` literals**

`src/schemas.py` — replace the `ImageSpec` docstring and `render_mode` line (lines 50–56):

```python
    """Specification for generating a question image.

    Render modes (docs/figure-rendering-policy.md):
    - render_mode="chart": structured data rendered by matplotlib (histogram, boxplot, etc.)
    - render_mode="frontend_ts": illustrative figure displayed client-side by the frontend
      TS renderer; the server still renders a Playwright PNG for the verifier and ODT export
    - render_mode="html": legacy alias kept for already-generated questions (server-side
      LLM-HTML + Playwright only)
    """
    render_mode: Literal["chart", "html", "frontend_ts"] = "chart"
```

`src/social_studies/schemas.py:24` — replace:

```python
    render_mode: Literal["chart", "html", "frontend_ts"] = "chart"
```

`src/natural_sciences/schemas.py:21` — replace:

```python
    render_mode: Literal["chart", "html", "frontend_ts"] = "chart"
```

- [ ] **Step 4: Extend the renderer dispatch**

`src/renderer.py` — in `render_image()`, replace `if render_mode == "html":` (line 305) with:

```python
    if render_mode in ("html", "frontend_ts"):
```

and replace the two dispatch lines of the docstring (lines 282–283, the `- "gpt_image":` and `- "html":` bullets) with:

```python
    - "gpt_image": GPT image API renders the spec directly
    - "html": render_mode controls deterministic chart vs HTML/Playwright rendering;
      render_mode "frontend_ts" also renders a server-side PNG here (the frontend TS
      renderer only replaces the on-page display — see docs/figure-rendering-policy.md)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_figure_rendering_policy.py tests/test_renderer_image_generation.py -v`
Expected: PASS — all policy tests (15 items: the 13 existing + the 2 new) + renderer tests green.

- [ ] **Step 6: Commit**

```bash
git add src/schemas.py src/social_studies/schemas.py src/natural_sciences/schemas.py src/renderer.py tests/test_figure_rendering_policy.py
git commit -m "feat: accept render_mode frontend_ts in ImageSpec and renderer dispatch (#110)"
```

---

### Task 9: Reroute `CONTENT_TYPE_INSTRUCTIONS` + prompt templates (third in the update order)

**Files:**
- Modify: `src/context_builder.py` (`CONTENT_TYPE_INSTRUCTIONS` lines 63–85; `SYSTEM_PROMPT_TEMPLATE` lines 165–176)
- Modify: `src/social_studies/context_builder.py` (`CONTENT_TYPE_INSTRUCTIONS` lines 62–87; `SYSTEM_PROMPT_TEMPLATE` lines 252–261; `_TEXT_GENERATION_SYSTEM_PROMPT_TEMPLATE` line 654)
- Modify: `src/natural_sciences/context_builder.py` (`CONTENT_TYPE_INSTRUCTIONS` lines 85–109)
- Modify: `src/social_studies/cli.py` (`_TOP_LEVEL_IMAGE_REPAIR_SYSTEM_PROMPT` lines 103–104)
- Test: `tests/test_figure_rendering_policy.py`

**Interfaces:**
- Consumes: `ImageSpec` accepting `"frontend_ts"` (Task 8 — without it, `_parse_question`'s `ImageSpec(**raw_spec)` would fall into its exception fallback and silently coerce specs to `"html"`).
- Produces: prompts that instruct the LLM to emit `render_mode: "frontend_ts"` for illustrative content across all three subjects. The wording deliberately avoids the exact substring `render_mode: "html"` so tests can assert its absence.

- [ ] **Step 1: Rewrite the prompt-routing tests (failing first)**

In `tests/test_figure_rendering_policy.py`, **delete** `test_illustrative_content_routes_to_html` and `test_quantitative_content_routes_to_chart_and_html_for_tables` (lines 34–55) and add:

```python
@pytest.mark.parametrize("subject, table", _SUBJECT_TABLES)
def test_illustrative_content_routes_to_frontend_ts(subject: str, table: dict) -> None:
    assert "含圖片" in table
    text = table["含圖片"]
    assert 'render_mode: "frontend_ts"' in text, (
        f"{subject}: 含圖片 instruction must direct the model to "
        'render_mode: "frontend_ts"'
    )
    assert 'render_mode: "html"' not in text, (
        f"{subject}: 含圖片 instruction must not instruct the legacy html mode"
    )


@pytest.mark.parametrize("subject, table", _SUBJECT_TABLES)
def test_quantitative_content_routes_to_chart_and_frontend_ts_for_tables(
    subject: str, table: dict
) -> None:
    assert "graphs/charts/tables" in table
    text = table["graphs/charts/tables"]
    assert 'render_mode: "chart"' in text
    assert 'render_mode: "frontend_ts"' in text, (
        f"{subject}: tables must route to render_mode: \"frontend_ts\""
    )
    assert 'render_mode: "html"' not in text


def test_ss_image_repair_prompt_routes_illustrative_to_frontend_ts() -> None:
    from src.social_studies.cli import _TOP_LEVEL_IMAGE_REPAIR_SYSTEM_PROMPT

    assert 'render_mode: "frontend_ts"' in _TOP_LEVEL_IMAGE_REPAIR_SYSTEM_PROMPT
    assert 'render_mode: "chart"' in _TOP_LEVEL_IMAGE_REPAIR_SYSTEM_PROMPT
    assert 'render_mode: "html"' not in _TOP_LEVEL_IMAGE_REPAIR_SYSTEM_PROMPT


def test_prompt_templates_no_longer_instruct_legacy_html_mode() -> None:
    from src import context_builder as math_cb
    from src.social_studies import context_builder as ss_cb

    templates = {
        "math SYSTEM_PROMPT_TEMPLATE": math_cb.SYSTEM_PROMPT_TEMPLATE,
        "ss SYSTEM_PROMPT_TEMPLATE": ss_cb.SYSTEM_PROMPT_TEMPLATE,
        "ss _TEXT_GENERATION_SYSTEM_PROMPT_TEMPLATE": (
            ss_cb._TEXT_GENERATION_SYSTEM_PROMPT_TEMPLATE
        ),
    }
    for name, template in templates.items():
        has_ts = (
            'render_mode: "frontend_ts"' in template
            or '"render_mode": "frontend_ts"' in template
        )
        assert has_ts, f"{name} must instruct frontend_ts"
        assert 'render_mode: "html"' not in template, name
        assert '"render_mode": "html"' not in template, name
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_figure_rendering_policy.py -v`
Expected: FAIL — the 4 new/renamed tests fail (instructions still say html); previously passing tests stay green.

- [ ] **Step 3: Reroute the math instructions**

`src/context_builder.py` — in `CONTENT_TYPE_INSTRUCTIONS`, replace the `含圖片` and `graphs/charts/tables` values (lines 68–81) with:

```python
    "含圖片": (
        "本題目必須包含圖片或視覺示意素材（幾何圖形、示意圖、版面等）。"
        "請輸出 `chart_spec`，一律使用 `render_mode: \"frontend_ts\"`"
        "（舊值 `\"html\"` 僅為既有題目的相容別名，請勿再輸出），"
        "並在 `description` 與 `data` 中完整描述版面與內容。"
        f"（示意圖聲明）本題所有圖片皆為示意用途，非完全等比例繪製；"
        f"請在 `chart_spec.description` 中明確要求下游 HTML 產生器"
        f"將「{IMAGE_DISCLAIMER}」以 caption 形式呈現在圖片下緣或版面空白處。"
    ),
    "graphs/charts/tables": (
        "本題目必須包含圖表或表格素材。統計圖（直方圖、折線圖、圓餅圖等）請使用 `render_mode: \"chart\"`；"
        "表格或複合資料表請使用 `render_mode: \"frontend_ts\"`，並在 `data` 中提供完整欄列資料。"
        f"（示意圖聲明）圖表軸線、格線與座標比例僅為示意，非完全等比例繪製；"
        f"請在 `chart_spec.description` 或圖表 caption 中加註「{IMAGE_DISCLAIMER}」，"
        "但圖表中的數值、標籤與分類仍必須完全對應 `data` 內容。"
    ),
```

Then in `SYSTEM_PROMPT_TEMPLATE`, make these four exact replacements:

1. Line 165 heading — old:
   `**HTML 示意圖（\`render_mode: "html"\`）** — 適用於幾何圖形、示意圖、菜單、比較表格、情境圖等一切無法用統計圖表表達的視覺內容：`
   new:
   `**前端示意圖（\`render_mode: "frontend_ts"\`）** — 適用於幾何圖形、示意圖、菜單、比較表格、情境圖等一切無法用統計圖表表達的視覺內容：`
2. Line 168 JSON example — old: `  "render_mode": "html",` → new: `  "render_mode": "frontend_ts",`
3. Line 175 — old: `` `render_mode: "html"` 的 `description` 請盡量詳細。`` → new: `` `render_mode: "frontend_ts"` 的 `description` 請盡量詳細。``
4. Line 176 — old: ``所有 `render_mode: "html"` 或 `render_mode: "chart"` 的圖片皆為示意用途、非完全等比例繪製，`` → new: ``所有 `render_mode: "frontend_ts"` 或 `render_mode: "chart"` 的圖片皆為示意用途、非完全等比例繪製，``

- [ ] **Step 4: Reroute the social-studies instructions**

`src/social_studies/context_builder.py` — in `CONTENT_TYPE_INSTRUCTIONS`, replace the `含圖片` and `graphs/charts/tables` values (lines 67–86) with:

```python
    "含圖片": (
        "本題組必須包含圖片式或視覺式非連續素材，例如地圖、圖解、廣告、表單、海報或網頁畫面。"
        "請在題組頂層輸出非 null 的 `chart_spec`，一律使用 `render_mode: \"frontend_ts\"`"
        "（舊值 `\"html\"` 僅為既有題目的相容別名，請勿再輸出），"
        "並在 `description` 與 `data` 中完整描述版面與內容。"
        "（重要）圖片必須是作答的必要條件：至少一道小題的答案必須直接依賴圖片中才有的資訊，無法僅憑文本回答。"
        "設計時請先確定「移除圖片後此題是否仍可作答」——若可以，請重新設計圖片，使其承載文本中未涵蓋的關鍵資訊"
        "（例如地圖上的地名/路線/分布、廣告上的價格/期限/規則、表單上的數據欄位）。"
        f"（示意圖聲明）圖片為示意用途，非完全等比例繪製；請在 `chart_spec.description` 中要求下游 HTML 產生器"
        f"將「{IMAGE_DISCLAIMER}」以 caption 呈現在圖片下緣或版面空白處。"
    ),
    "graphs/charts/tables": (
        "本題組必須包含圖表或表格素材。統計圖（直方圖、折線圖、圓餅圖等）請使用 `render_mode: \"chart\"`；"
        "表格或複合資料表請使用 `render_mode: \"frontend_ts\"`，並在題組頂層輸出非 null 的 `chart_spec`，"
        "於 `data` 中提供完整欄列資料。"
        "（重要）圖表/表格必須是作答的必要條件：至少一道小題須讀取圖表中的具體數值、趨勢或分類才能回答，"
        "且這些數值不得在 `文本` 欄位中重複列出。若移除圖表後題目仍可回答，需重新設計使數據只存在於圖表中。"
        f"（示意圖聲明）圖表軸線、格線與座標比例僅為示意，非完全等比例繪製；"
        f"請在 `chart_spec.description` 或圖表 caption 加註「{IMAGE_DISCLAIMER}」，"
        "但圖表中的數值、標籤與分類仍必須完全對應 `data` 內容。"
    ),
```

Then in `SYSTEM_PROMPT_TEMPLATE`, three exact replacements:

1. Line 252 heading — old: `**HTML排版素材（\`render_mode: "html"\`）** — 適用於表格、地圖、廣告、表單、圖解、數位網頁：` → new: `**前端排版素材（\`render_mode: "frontend_ts"\`）** — 適用於表格、地圖、廣告、表單、圖解、數位網頁：`
2. Line 255 JSON example — old: `  "render_mode": "html",` → new: `  "render_mode": "frontend_ts",`
3. Line 261 — old: ``…因此無論 `render_mode` 是 `chart` 或 `html`，`description` 都必須要求下游產生器附上 caption…`` → new: ``…因此無論 `render_mode` 是 `chart` 或 `frontend_ts`，`description` 都必須要求下游產生器附上 caption…`` (keep the rest of the line unchanged)

And in `_TEXT_GENERATION_SYSTEM_PROMPT_TEMPLATE` (line 654) — old:
`統計圖使用 \`render_mode: "chart"\`；HTML排版素材（地圖、表格、廣告等）使用 \`render_mode: "html"\`。`
new:
`統計圖使用 \`render_mode: "chart"\`；前端排版素材（地圖、表格、廣告等）使用 \`render_mode: "frontend_ts"\`。`

- [ ] **Step 5: Reroute the natural-sciences instructions**

`src/natural_sciences/context_builder.py` — in `CONTENT_TYPE_INSTRUCTIONS`, replace the `含圖片` and `graphs/charts/tables` values (lines 90–108) with:

```python
    "含圖片": (
        "本題組必須包含視覺式科學素材，例如實驗裝置圖、模型圖、流程圖、標籤圖、"
        "地圖或情境示意圖。請輸出 `chart_spec`，一律使用 `render_mode: \"frontend_ts\"`"
        "（舊值 `\"html\"` 僅為既有題目的相容別名，請勿再輸出），"
        "並在 `description` 與 `data` 中完整描述版面與作答所需元素。"
        "（重要）圖片必須是作答的必要條件：至少一道小題的答案必須直接依賴圖片中才有的資訊，無法僅憑文本回答。"
        "設計時請先確定「移除圖片後此題是否仍可作答」——若可以，請重新設計圖片，使其承載文本中未涵蓋的關鍵資訊"
        "（例如實驗裝置的連接方式、模型圖的標示數據、流程圖的條件分支）。"
        f"（示意圖聲明）圖片為示意用途，非完全等比例繪製；請在 `chart_spec.description` 中要求下游 HTML 產生器"
        f"將「{IMAGE_DISCLAIMER}」以 caption 呈現在圖片下緣或版面空白處。"
    ),
    "graphs/charts/tables": (
        "本題組必須包含數據圖表或表格。統計圖請使用 `render_mode: \"chart\"`；"
        "實驗數據表、分類表或多欄比較表請使用 `render_mode: \"frontend_ts\"`，並在 `data` 中提供完整資料。"
        "（重要）圖表/表格必須是作答的必要條件：至少一道小題須讀取圖表中的具體數值、趨勢或分類才能回答，"
        "且這些數值不得在 `文本` 欄位中重複列出。若移除圖表後題目仍可回答，需重新設計使數據只存在於圖表中。"
        f"（示意圖聲明）圖表軸線、格線與座標比例僅為示意，非完全等比例繪製；"
        f"請在 `chart_spec.description` 或圖表 caption 加註「{IMAGE_DISCLAIMER}」，"
        "但圖表中的數值、標籤與分類仍必須完全對應 `data` 內容。"
    ),
```

- [ ] **Step 6: Reroute the SS image-repair prompt**

`src/social_studies/cli.py` line 103 — old:
`- 若是圖片式素材、地圖、海報、表單、網頁畫面、流程圖或圖解，使用 \`render_mode: "html"\`。`
new:
`- 若是圖片式素材、地圖、海報、表單、網頁畫面、流程圖或圖解，使用 \`render_mode: "frontend_ts"\`。`

- [ ] **Step 7: Fix the one known pre-existing assertion, then run the full backend suite**

`tests/test_math_context_builder.py::test_math_html_designer_guidance_carries_disclaimer` (lines 27–31) asserts the old fragment. Replace its body with:

```python
def test_math_html_designer_guidance_carries_disclaimer() -> None:
    prompt = build_system_prompt()
    # Phrase must appear inside the render_mode: "frontend_ts" guidance block.
    assert 'render_mode: "frontend_ts"' in prompt
    assert IMAGE_DISCLAIMER in prompt
```

The other `render_mode: "html"` occurrences in tests (`tests/test_renderer_image_generation.py:99`, `tests/test_social_studies_subquestion_images.py:38,91`) are spec-**dict** fixtures, not prompt assertions — `"html"` stays a dispatchable legacy alias, so leave them unchanged. Then run:

Run: `uv run pytest tests/ -x -q`
Expected: PASS — full backend suite green. If anything else fails on a `render_mode` string, it is asserting prompt wording; update the assertion to the new `frontend_ts` fragment in this same commit (`grep -rn 'render_mode' tests/` to locate).

- [ ] **Step 8: Commit**

```bash
git add src/context_builder.py src/social_studies/context_builder.py src/natural_sciences/context_builder.py src/social_studies/cli.py tests/
git commit -m "feat: prompts route illustrative figures to render_mode frontend_ts (#110)"
```

---

### Task 10: Math schema surface in `server/utility/routes.py`

**Files:**
- Modify: `server/utility/routes.py:48-65` (`_MATH_CONTENT_TYPES`)
- Test: `tests/server/test_utility_routes.py`

**Interfaces:**
- Consumes: `create_app` / `get_config` / `ServerConfig` test pattern already in `tests/server/test_utility_routes.py:15-52`.
- Produces: `/api/schemas?subject=math` 題目內容類型 instructions that name the new mode. (SS/NS 題目內容類型 instructions live in researcher-editable `schema_parameters.csv` data files, not code — updating those CSVs is a data-maintenance step for the curriculum team, out of this plan's code scope.)

- [ ] **Step 1: Write the failing test**

Append to `tests/server/test_utility_routes.py` (reuses the module's existing imports and `_config` helper):

```python
def test_math_schemas_content_type_instructions_mention_frontend_ts(tmp_path: Path) -> None:
    payload = {"學習階段": "第四學習階段", "grades": [7, 8, 9]}
    schemas_file = tmp_path / "question_schemas.json"
    schemas_file.write_text(json.dumps(payload), encoding="utf-8")

    app = create_app()
    app.dependency_overrides[get_config] = lambda: _config(schemas_file)
    with TestClient(app) as client:
        r = client.get("/api/schemas")
    assert r.status_code == 200
    by_value = {entry["value"]: entry["instruction"] for entry in r.json()["題目內容類型"]}
    assert 'render_mode: "frontend_ts"' in by_value["含圖片"]
    assert 'render_mode: "chart"' in by_value["graphs/charts/tables"]
    assert 'render_mode: "frontend_ts"' in by_value["graphs/charts/tables"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/server/test_utility_routes.py -v`
Expected: FAIL — `KeyError`-free but assertion fails: instructions do not mention `frontend_ts` yet.

- [ ] **Step 3: Update `_MATH_CONTENT_TYPES`**

`server/utility/routes.py` — replace the `含圖片` and `graphs/charts/tables` entries (lines 53–60) with:

```python
    {
        "value": "含圖片",
        "instruction": "題目必須搭配圖片式或視覺式素材，如幾何圖形、示意圖、座標平面、數線等，並以 chart_spec（render_mode: \"frontend_ts\"）描述素材。",
    },
    {
        "value": "graphs/charts/tables",
        "instruction": "題目必須搭配圖表或表格素材，並以 chart_spec 提供完整資料：統計圖使用 render_mode: \"chart\"，表格使用 render_mode: \"frontend_ts\"。",
    },
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/server/test_utility_routes.py -v`
Expected: PASS — all utility-route tests green (the file already carries `# ruff: noqa: E501`, so the long Chinese lines are fine).

- [ ] **Step 5: Commit**

```bash
git add server/utility/routes.py tests/server/test_utility_routes.py
git commit -m "feat: /api/schemas math content-type instructions name frontend_ts (#110)"
```

---

### Task 11: Consistency helper + the issue's literal classification test

**Files:**
- Create: `src/common/figure_policy.py`
- Create: `tests/test_render_mode_classification.py`

**Interfaces:**
- Consumes: `src.cli._parse_question(raw: dict, question_id: str, params: SampledParams, model: str) -> ExamQuestion` (the real math parse path), `src.sampler.sample_params(seed=..., content_type=...)`, `ImageSpec` accepting `"frontend_ts"` (Task 8).
- Produces: `render_mode_consistency_issues(content_type: str | None, spec: dict | None) -> list[str]` — empty list means the emitted `render_mode` matches the declared 題目內容類型 per `docs/figure-rendering-policy.md`. Subject-agnostic (works on any subject's `chart_spec` dict).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_render_mode_classification.py`:

```python
"""Issue #110 classification test: emitted render_mode must match 題目內容類型.

Source of truth: docs/figure-rendering-policy.md.
"""

from __future__ import annotations

from src.cli import _parse_question
from src.common.figure_policy import render_mode_consistency_issues
from src.sampler import sample_params


def _generated_item(raw: dict, content_type: str):
    """Run a canned LLM payload through the real math parse path."""
    params = sample_params(seed=42, content_type=content_type)
    return _parse_question(raw, "q_policy_test", params, "claude-sonnet-4-6")


def _raw(content_type: str, chart_spec: dict | None) -> dict:
    raw = {
        "情境": ["個人"],
        "題型種類": "單一題",
        "題型": "選擇題",
        "數學思考": ["形成"],
        "學習內容": [],
        "題目": ["題幹"],
        "正確解題分析": ["解析"],
        "題目內容類型": content_type,
    }
    if chart_spec is not None:
        raw["chart_spec"] = chart_spec
    return raw


def test_generated_plain_text_item_has_no_chart_spec() -> None:
    q = _generated_item(_raw("純文字", None), "純文字")
    assert q.chart_spec is None
    assert render_mode_consistency_issues(q.題目內容類型, None) == []


def test_generated_illustrative_item_emits_frontend_ts() -> None:
    spec = {"render_mode": "frontend_ts", "description": "三角形示意圖", "data": {"shapes": []}}
    q = _generated_item(_raw("含圖片", spec), "含圖片")
    assert q.chart_spec is not None
    assert q.chart_spec.render_mode == "frontend_ts"
    assert render_mode_consistency_issues(q.題目內容類型, q.chart_spec.model_dump()) == []


def test_generated_quantitative_item_emits_chart() -> None:
    spec = {
        "render_mode": "chart",
        "chart_type": "histogram",
        "data": {"bins": ["0-10"], "counts": [3]},
    }
    q = _generated_item(_raw("graphs/charts/tables", spec), "graphs/charts/tables")
    assert q.chart_spec is not None
    assert render_mode_consistency_issues(q.題目內容類型, q.chart_spec.model_dump()) == []


def test_mismatches_are_reported() -> None:
    # 純文字 with a spec.
    assert render_mode_consistency_issues("純文字", {"render_mode": "frontend_ts"}) != []
    # 含圖片 without any spec.
    assert render_mode_consistency_issues("含圖片", None) != []
    # 含圖片 with a quantitative mode.
    assert render_mode_consistency_issues(
        "含圖片", {"render_mode": "chart", "chart_type": "histogram"}
    ) != []
    # chart mode without a supported statistical chart_type.
    assert render_mode_consistency_issues(
        "graphs/charts/tables", {"render_mode": "chart", "chart_type": None}
    ) != []


def test_legacy_html_alias_still_passes_for_already_generated_questions() -> None:
    assert render_mode_consistency_issues(
        "含圖片", {"render_mode": "html", "description": "海報"}
    ) == []


def test_customized_and_unknown_content_types_are_unconstrained() -> None:
    assert render_mode_consistency_issues("customized", None) == []
    assert render_mode_consistency_issues(None, {"render_mode": "frontend_ts"}) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_render_mode_classification.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.common.figure_policy'`.

- [ ] **Step 3: Implement the helper**

Create `src/common/figure_policy.py`:

```python
"""Render-mode <-> 題目內容類型 consistency checks.

Source of truth: docs/figure-rendering-policy.md. Subject-agnostic: operates
on plain chart_spec dicts so all three subjects (and their subquestions) can
use it. "html" is accepted as a read-only legacy alias for already-generated
questions.
"""

from __future__ import annotations

ILLUSTRATIVE_MODES = ("frontend_ts", "html")  # "html" = legacy alias
QUANTITATIVE_MODE = "chart"
STATISTICAL_CHART_TYPES = ("histogram", "boxplot", "line_chart", "pie_chart", "scatter_plot")


def render_mode_consistency_issues(
    content_type: str | None, spec: dict | None
) -> list[str]:
    """Return policy violations for one item's chart_spec vs its declared 題目內容類型.

    An empty list means the emitted render_mode matches the classification.
    customized / unknown / missing content types are unconstrained.
    """
    issues: list[str] = []
    if content_type == "純文字":
        if spec is not None:
            issues.append("純文字 must not emit a chart_spec")
        return issues
    if content_type not in ("含圖片", "graphs/charts/tables"):
        return issues
    if spec is None:
        issues.append(f"{content_type} requires a chart_spec")
        return issues
    mode = (spec.get("render_mode") or "").lower()
    if content_type == "含圖片":
        if mode not in ILLUSTRATIVE_MODES:
            issues.append(
                f"含圖片 requires render_mode 'frontend_ts' (got {mode!r})"
            )
        return issues
    # graphs/charts/tables
    if mode == QUANTITATIVE_MODE:
        if spec.get("chart_type") not in STATISTICAL_CHART_TYPES:
            issues.append(
                "render_mode 'chart' requires a supported statistical chart_type "
                f"(got {spec.get('chart_type')!r})"
            )
    elif mode not in ILLUSTRATIVE_MODES:
        issues.append(
            "graphs/charts/tables requires render_mode 'chart' or 'frontend_ts' "
            f"(got {mode!r})"
        )
    return issues
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_render_mode_classification.py -v`
Expected: PASS — 6 tests green.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/common/figure_policy.py tests/test_render_mode_classification.py
git add src/common/figure_policy.py tests/test_render_mode_classification.py
git commit -m "test: render_mode matches declared 題目內容類型 on generated items (#110)"
```

---

### Task 12: Frontend acceptance of `frontend_ts` + default-on build flag

**Files:**
- Modify: `web/src/components/FigureRenderer.tsx` (header comment only — the logic already treats any non-`"chart"` mode by data shape)
- Modify: `web/src/components/FigureRenderer.test.tsx`
- Modify: `web/src/components/QuestionCard.test.tsx`
- Modify: `web/Dockerfile`
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: `classifySpec` / `pickFigure` behavior shipped in PR #141 (`classifySpec` returns `"unsupported"` only for `render_mode: "chart"` or unknown data shapes — `"frontend_ts"` specs flow through the same shape checks as `"html"`).
- Produces: regression tests pinning `frontend_ts` support; Docker builds default the display flag on (`VITE_ENABLE_FRONTEND_TS_RENDERER=1`) per the GO.

All web commands run from `/workspace/exam-generation/web/`.

- [ ] **Step 1: Write the (immediately passing — pin behavior) frontend tests**

Append inside the `describe("classifySpec", …)` block of `web/src/components/FigureRenderer.test.tsx`:

```tsx
  it("classifies frontend_ts table specs as table", () => {
    expect(
      classifySpec({
        render_mode: "frontend_ts",
        data: { columns: ["a"], rows: [["1"]] },
      }),
    ).toBe("table");
  });

  it("classifies frontend_ts geometry specs as geometry", () => {
    expect(
      classifySpec({
        render_mode: "frontend_ts",
        data: { shapes: [{ type: "circle", cx: 5, cy: 5, r: 2 }] },
      }),
    ).toBe("geometry");
  });
```

Append inside the `describe("QuestionCard + FigureRenderer swap", …)` block of `web/src/components/QuestionCard.test.tsx`:

```tsx
  it("renders the FigureRenderer for render_mode frontend_ts specs when the flag is on", () => {
    vi.stubEnv("VITE_ENABLE_FRONTEND_TS_RENDERER", "1");
    const question = {
      情境: [],
      題型種類: "單一題",
      題型: "選擇題",
      題目: ["Q"],
      正確解題分析: ["A"],
      image_base64: "aGVsbG8=",
      chart_spec: {
        render_mode: "frontend_ts",
        description: "課表",
        data: { columns: ["時段"], rows: [["9:00"]] },
      },
    } as unknown as import("../hooks/useGenerate").ExamQuestion;
    render(<QuestionCard question={question} isFinal />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.queryByAltText("Question diagram")).toBeNull();
  });
```

- [ ] **Step 2: Run the web tests**

Run: `npm test -- src/components/FigureRenderer.test.tsx src/components/QuestionCard.test.tsx`
Expected: PASS immediately (the prototype already handles non-`chart` modes by data shape). If either new test FAILS, stop and debug `classifySpec` — do not weaken the test.

- [ ] **Step 3: Update the FigureRenderer header comment**

`web/src/components/FigureRenderer.tsx` — replace lines 1–11 (the block comment) with:

```tsx
/**
 * Frontend TS/SVG renderer for illustrative chart_spec entries.
 *
 * Consumes chart_spec (render_mode + description + data) and covers three
 * illustrative shapes: tables, simple SVG geometry, scenario cards. Accepts
 * render_mode "frontend_ts" (primary since the issue #110 GO) and "html"
 * (legacy alias on already-generated questions). render_mode "chart" and
 * unknown data shapes are unsupported: the component returns null so the
 * caller falls back to the server PNG.
 *
 * Gated behind VITE_ENABLE_FRONTEND_TS_RENDERER (default-on in Docker builds
 * since the GO) — the routing policy in docs/figure-rendering-policy.md
 * documents when this path is active.
 */
```

- [ ] **Step 4: Default the flag on in Docker builds**

`web/Dockerfile` — after line 9 (`ENV VITE_SENTRY_DSN=$VITE_SENTRY_DSN`), add:

```dockerfile
ARG VITE_ENABLE_FRONTEND_TS_RENDERER=1
ENV VITE_ENABLE_FRONTEND_TS_RENDERER=$VITE_ENABLE_FRONTEND_TS_RENDERER
```

`docker-compose.yml` — in the `frontend` service `build.args` block (line 36), add below `VITE_SENTRY_DSN`:

```yaml
        VITE_ENABLE_FRONTEND_TS_RENDERER: ${VITE_ENABLE_FRONTEND_TS_RENDERER:-1}
```

(Setting the env var to an empty string turns the TS display path back off without a code change — the PNG fallback keeps working either way.)

- [ ] **Step 5: Full web suite, scoped lint, build, compose config**

Run: `npm test && npx eslint src/components/FigureRenderer.tsx src/components/FigureRenderer.test.tsx src/components/QuestionCard.test.tsx && npm run build`
Expected: all vitest files pass; no eslint errors in the named files; `tsc -b && vite build` succeeds.

Then validate the compose YAML. docker is NOT available in this dev container, so use the system Python (pyyaml is installed):

Run: `python3 -c "import yaml; yaml.safe_load(open('/workspace/exam-generation/docker-compose.yml'))"`
Expected: exits 0 silently. (On a machine that has docker, `docker compose -f /workspace/exam-generation/docker-compose.yml config --quiet` is the stronger check — exits 0.)

- [ ] **Step 6: Commit + full-repo verification**

```bash
cd /workspace/exam-generation
git add web/src/components/FigureRenderer.tsx web/src/components/FigureRenderer.test.tsx \
  web/src/components/QuestionCard.test.tsx web/Dockerfile docker-compose.yml
git commit -m "feat(web): frontend_ts render mode display + default-on build flag (#110)"
uv run pytest tests/ -q
```

Expected: full backend suite green. Part B (and issue #110) is complete; hand the branch to the normal PR-into-staging flow.
