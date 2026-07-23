# Path-Scoped Claude Code Instructions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 497-line root `CLAUDE.md` with a concise global router, focused nested instruction files, path-scoped cross-cutting rules, and automated documentation-contract checks.

**Architecture:** Claude Code will always receive a short root instruction file, then load directory-owned `CLAUDE.md` files and matching `.claude/rules/*.md` files only when work enters those scopes. A pytest contract suite will enforce the file inventory, size budgets, path frontmatter, local links, and anti-duplication rules without adding a dependency.

**Tech Stack:** Markdown, Claude Code `CLAUDE.md`, Claude Code `.claude/rules/` YAML frontmatter, Python 3.11 standard library (`pathlib`, `re`), pytest, Ruff.

## Global Constraints

- Implement on branch `docs/claude-md-decomposition`, based on `main`.
- Leave `docs/superpowers/plans/2026-07-22-generation-progress-bar.md` untouched and exclude it from every commit.
- Do not modify production Python, TypeScript, schemas, curriculum data, migrations, or runtime behavior.
- Root `CLAUDE.md` must contain at most 100 lines.
- Each nested `CLAUDE.md` must contain at most 180 lines.
- Each `.claude/rules/*.md` must contain at most 140 lines.
- Parent and child instruction files must be additive; do not rely on child files overriding parent instructions.
- Every initial `.claude/rules/*.md` file must have a non-empty `paths` list.
- Do not use `@README.md`, `@FLOW.md`, `@LOGIC.md`, or equivalent large imports; use normal Markdown links.
- Do not add a dependency for instruction-file validation; use the Python standard library and existing pytest.
- Keep full schemas, exhaustive file inventories, execution waterfalls, issue history, volatile counts, and source line numbers out of instruction files.
- Treat Phase 2 cleanup of `README.md`, `FLOW.md`, `LOGIC.md`, `web/README.md`, and `data/social_studies/csv_填寫指南.md` as out of scope.
- Do not copy progress/cancellation protocol details from the unrelated feature branch into instructions based on `main`.

---

## File Structure

### Create

- `tests/test_claude_instructions.py` — parses the limited frontmatter/link forms used by project instructions and enforces the documentation contract.
- `src/CLAUDE.md` — generation-engine and math-pipeline rules shared under `src/`.
- `src/common/CLAUDE.md` — subject-neutral shared utility rules.
- `src/social_studies/CLAUDE.md` — social-studies pipeline differences.
- `src/natural_sciences/CLAUDE.md` — natural-sciences pipeline differences.
- `server/CLAUDE.md` — backend-wide FastAPI, persistence, auth, and lifecycle rules.
- `server/generate/CLAUDE.md` — generation route, SSE, worker, and exchange-recorder rules.
- `web/CLAUDE.md` — React/TypeScript, state, SSE, i18n, accessibility, and frontend test rules.
- `data/CLAUDE.md` — runtime-editable, canonical-source, generated, and reference-only data ownership.
- `scripts/CLAUDE.md` — builder, importer, converter, and smoke-test rules.
- `tests/CLAUDE.md` — focused-test and test-double conventions plus documentation-contract ownership.
- `alembic/CLAUDE.md` — migration-chain, database compatibility, and downgrade rules.
- `.claude/rules/figure-rendering.md` — cross-layer rendering policy synchronization.
- `.claude/rules/question-contracts.md` — producer/transport/consumer/export schema compatibility.
- `.claude/rules/generated-assets.md` — canonical source and generated-output synchronization.
- `.claude/rules/documentation.md` — instruction ownership, size, linking, and anti-duplication policy.

### Modify

- `CLAUDE.md:1-497` — replace the catch-all document with the global router.

### Verify without modifying

- `tests/test_context_builder_docstrings.py` — its existing root policy-link assertion must continue to pass.
- `tests/test_figure_rendering_policy.py` — rendering policy remains authoritative.
- `docs/figure-rendering-policy.md` — linked, not copied.
- `README.md`, `FLOW.md`, `LOGIC.md`, `DEPLOYMENT.md`, `IMPLEMENTATION_PLAN.md`, `docs/ADDING_SAMPLES.md` — referenced, not cleaned up in Phase 1.

## Execution Prerequisite

The current container may not have `uv` on `PATH`. Before Task 1, run:

```bash
command -v uv >/dev/null || python3 -m pip install --break-system-packages uv
uv sync --all-extras
```

Expected: `uv` is available and the project, development, and optional web dependencies are synchronized. This changes the execution environment only; it must not add dependency files to the commit.

---

### Task 1: Build the Instruction Contract Test Helpers

**Files:**
- Create: `tests/test_claude_instructions.py`

**Interfaces:**
- Consumes: Python 3.11 standard library and pytest.
- Produces:
  - `_without_markdown_code(text: str) -> str`
  - `_parse_paths_frontmatter(text: str) -> list[str] | None`
  - `_local_markdown_targets(source: Path, text: str) -> list[Path]`
  - passing unit tests for those helpers, reused by Tasks 2–4.

- [ ] **Step 1: Write failing helper tests**

Create `tests/test_claude_instructions.py` with this initial content:

```python
"""Contract tests for the repository's path-scoped Claude Code instructions."""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


def test_parse_paths_frontmatter_extracts_quoted_globs() -> None:
    text = """---
paths:
  - "src/**/*.py"
  - 'tests/*.py'
---
# Rule
"""
    assert _parse_paths_frontmatter(text) == ["src/**/*.py", "tests/*.py"]


def test_parse_paths_frontmatter_returns_none_when_absent() -> None:
    assert _parse_paths_frontmatter("# Instructions\n") is None


def test_without_markdown_code_removes_fenced_and_inline_examples() -> None:
    text = """Do not import large files.

`@README.md`

```md
@FLOW.md
```

Keep this prose.
"""
    cleaned = _without_markdown_code(text)
    assert "@README.md" not in cleaned
    assert "@FLOW.md" not in cleaned
    assert "Keep this prose." in cleaned


def test_local_markdown_targets_ignores_remote_and_anchor_links(tmp_path: Path) -> None:
    source = tmp_path / "nested" / "CLAUDE.md"
    source.parent.mkdir()
    text = """[Local](../README.md#usage)
[Remote](https://code.claude.com/docs/en/memory.md)
[Anchor](#scope)
"""
    assert _local_markdown_targets(source, text) == [tmp_path / "README.md"]
```

- [ ] **Step 2: Run the helper tests and verify they fail**

Run:

```bash
uv run pytest tests/test_claude_instructions.py -q
```

Expected: FAIL because `_parse_paths_frontmatter`, `_without_markdown_code`, and `_local_markdown_targets` are not defined.

- [ ] **Step 3: Add the minimal standard-library helper implementation**

Add these imports below `from __future__ import annotations`:

```python
import re
```

Add these definitions below `_ROOT` and above the tests:

```python
_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def _without_markdown_code(text: str) -> str:
    without_fences = _FENCED_CODE_RE.sub("", text)
    return _INLINE_CODE_RE.sub("", without_fences)


def _parse_paths_frontmatter(text: str) -> list[str] | None:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return None

    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise AssertionError("frontmatter is missing its closing ---") from exc

    paths: list[str] = []
    reading_paths = False
    for line in lines[1:end]:
        stripped = line.strip()
        if stripped == "paths:":
            reading_paths = True
            continue
        if reading_paths and stripped.startswith("- "):
            paths.append(stripped[2:].strip().strip('"\''))
            continue
        if reading_paths and stripped and not line.startswith((" ", "\t")):
            reading_paths = False
    return paths


def _local_markdown_targets(source: Path, text: str) -> list[Path]:
    targets: list[Path] = []
    for raw_target in _MARKDOWN_LINK_RE.findall(text):
        target = raw_target.strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target = target.split("#", 1)[0]
        if target:
            targets.append((source.parent / target).resolve())
    return targets
```

- [ ] **Step 4: Run the helper tests and verify they pass**

Run:

```bash
uv run pytest tests/test_claude_instructions.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Run Ruff on the new test module**

Run:

```bash
uv run ruff check tests/test_claude_instructions.py
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit the helper foundation**

```bash
git add tests/test_claude_instructions.py
git commit -m "test: add Claude instruction contract helpers" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Replace the Root File and Add the Generation Scopes

**Files:**
- Modify: `CLAUDE.md:1-497`
- Create: `src/CLAUDE.md`
- Create: `src/common/CLAUDE.md`
- Create: `src/social_studies/CLAUDE.md`
- Create: `src/natural_sciences/CLAUDE.md`
- Modify: `tests/test_claude_instructions.py`
- Test: `tests/test_context_builder_docstrings.py`

**Interfaces:**
- Consumes: Task 1 helper functions.
- Produces:
  - the always-loaded root router;
  - the shared and subject-specific `src/` instruction hierarchy;
  - repository-level tests for inventory, budgets, required root anchors, local links, large imports, catch-all sections, and volatile line references.

- [ ] **Step 1: Add failing repository-level contract tests for root and `src/`**

Add these constants below `_MARKDOWN_LINK_RE`:

```python
_ROOT_INSTRUCTION = _ROOT / "CLAUDE.md"
_NESTED_INSTRUCTIONS = [
    _ROOT / "src" / "CLAUDE.md",
    _ROOT / "src" / "common" / "CLAUDE.md",
    _ROOT / "src" / "social_studies" / "CLAUDE.md",
    _ROOT / "src" / "natural_sciences" / "CLAUDE.md",
]
_RULE_FILES: list[Path] = []
_INSTRUCTION_FILES = [_ROOT_INSTRUCTION, *_NESTED_INSTRUCTIONS, *_RULE_FILES]
_REQUIRED_ROOT_ANCHORS = [
    "## Project Overview",
    "## Global Invariants",
    "## Common Commands",
    "## Scoped Guidance",
    "docs/figure-rendering-policy.md",
]
_BANNED_HEADINGS = [
    "## Key Files",
    "## Execution Logic",
    "### LLM Calls Summary",
]
_LARGE_IMPORT_RE = re.compile(
    r"(?<![\w`])@(?:\.\./)*(?:README|FLOW|LOGIC)\.md\b"
)
_LINE_REFERENCE_RE = re.compile(
    r"(?<![\w/])(?:[\w.-]+/)*[\w.-]+\.py:\d+(?:-\d+)?"
)
```

Add these tests after the Task 1 helper tests:

```python
def _relative_id(path: Path) -> str:
    return path.relative_to(_ROOT).as_posix()


def _line_budget(path: Path) -> int:
    if path == _ROOT_INSTRUCTION:
        return 100
    if path in _RULE_FILES:
        return 140
    return 180


@pytest.mark.parametrize("path", _INSTRUCTION_FILES, ids=_relative_id)
def test_expected_instruction_files_exist(path: Path) -> None:
    assert path.is_file(), f"missing instruction file: {_relative_id(path)}"


@pytest.mark.parametrize("path", _INSTRUCTION_FILES, ids=_relative_id)
def test_instruction_files_stay_within_line_budgets(path: Path) -> None:
    line_count = len(path.read_text(encoding="utf-8").splitlines())
    assert line_count <= _line_budget(path), (
        f"{_relative_id(path)} has {line_count} lines; "
        f"budget is {_line_budget(path)}"
    )


def test_root_instruction_contains_required_sections_and_scope_map() -> None:
    text = _ROOT_INSTRUCTION.read_text(encoding="utf-8")
    for anchor in _REQUIRED_ROOT_ANCHORS:
        assert anchor in text, f"root CLAUDE.md is missing {anchor!r}"
    for path in _NESTED_INSTRUCTIONS:
        assert _relative_id(path) in text, (
            f"root CLAUDE.md scope map is missing {_relative_id(path)}"
        )


@pytest.mark.parametrize("path", _INSTRUCTION_FILES, ids=_relative_id)
def test_local_instruction_links_resolve(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for target in _local_markdown_targets(path, text):
        assert target.is_relative_to(_ROOT), (
            f"{_relative_id(path)} links outside the repository: {target}"
        )
        assert target.exists(), (
            f"{_relative_id(path)} has a broken local link to "
            f"{target.relative_to(_ROOT).as_posix()}"
        )


@pytest.mark.parametrize("path", _INSTRUCTION_FILES, ids=_relative_id)
def test_instruction_files_do_not_import_large_reference_docs(path: Path) -> None:
    text = _without_markdown_code(path.read_text(encoding="utf-8"))
    assert _LARGE_IMPORT_RE.search(text) is None, (
        f"{_relative_id(path)} imports a large reference document"
    )


@pytest.mark.parametrize("path", _INSTRUCTION_FILES, ids=_relative_id)
def test_instruction_files_do_not_recreate_catch_all_sections(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for heading in _BANNED_HEADINGS:
        assert heading not in text, f"{_relative_id(path)} contains banned {heading!r}"


@pytest.mark.parametrize("path", _INSTRUCTION_FILES, ids=_relative_id)
def test_instruction_files_do_not_pin_python_line_numbers(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert _LINE_REFERENCE_RE.search(text) is None, (
        f"{_relative_id(path)} contains a volatile Python line reference"
    )
```

- [ ] **Step 2: Run the contract tests and verify the expected failures**

Run:

```bash
uv run pytest tests/test_claude_instructions.py -q
```

Expected: FAIL because the four nested files do not exist and the current root `CLAUDE.md` exceeds 100 lines and contains catch-all sections.

- [ ] **Step 3: Replace the root `CLAUDE.md` with the global router**

Replace the complete contents of `CLAUDE.md` with:

```markdown
# Project Instructions

## Project Overview

This repository generates structured Taiwan exam questions for mathematics, 108課綱 social studies, and 108課綱 natural sciences. Math uses a flat single-question pipeline; social studies and natural sciences use shared-text question sets with parallel subquestion generation. The CLI, FastAPI server, React frontend, curriculum data, and rendering tools share these generation cores.

## Global Invariants

- Use Python 3.11+, `uv`, type hints, Pydantic models, snake_case names, and absolute imports from `src.`.
- Keep secrets, endpoints, model names, and deployment-specific values in environment configuration; never hardcode credentials.
- Chinese JSON field names are intentional API and export contracts. Preserve them across generation, persistence, frontend display, and exports.
- Curriculum is injected directly into prompts; do not introduce RAG without a separately approved architecture change.
- Random parameter selection belongs in Python. The LLM receives deterministic sampled constraints.
- Follow the nearest applicable nested `CLAUDE.md` and matching `.claude/rules/*.md` files. Parent and child guidance must remain additive, not contradictory.
- Source code, tests, and owned policy documents take precedence over stale summaries. Files under `docs/superpowers/` are task records, not standing project policy.
- Keep instruction files concise. Put explanatory detail in owned documentation and link to it rather than copying it.

## Common Commands

```bash
uv sync
uv run pytest
uv run ruff check src/ server/ tests/
npm --prefix web test
npm --prefix web run lint
```

## Scoped Guidance

- `src/CLAUDE.md` — generation engine and math pipeline.
- `src/common/CLAUDE.md` — subject-neutral shared utilities.
- `src/social_studies/CLAUDE.md` — social-studies pipeline and schema differences.
- `src/natural_sciences/CLAUDE.md` — natural-sciences pipeline and schema differences.
- `server/CLAUDE.md` — FastAPI, auth, persistence, and application lifecycle.
- `server/generate/CLAUDE.md` — generation routes, SSE, workers, and exchanges.
- `web/CLAUDE.md` — React/TypeScript, state, i18n, accessibility, and frontend tests.
- `data/CLAUDE.md` — curriculum and few-shot ownership.
- `scripts/CLAUDE.md` — builders, importers, converters, and smoke tests.
- `tests/CLAUDE.md` — test organization and documentation contracts.
- `alembic/CLAUDE.md` — database migration discipline.
- `.claude/rules/` — cross-cutting rendering, schema, generated-asset, and documentation contracts.

## Canonical References

- [Project setup and usage](README.md)
- [CLI execution trace](LOGIC.md)
- [Web generation flow](FLOW.md)
- [Figure rendering policy](docs/figure-rendering-policy.md)
- [Adding few-shot samples](docs/ADDING_SAMPLES.md)
- [Deployment guide](DEPLOYMENT.md)
- [Deferred technical work](IMPLEMENTATION_PLAN.md)
```

- [ ] **Step 4: Create `src/CLAUDE.md`**

```markdown
# Generation Engine Instructions

## Scope

These rules apply to the Python generation engine under `src/`. The flat files are the math pipeline; `social_studies/` and `natural_sciences/` add subject-specific behavior.

## Invariants

- Sample grade, context, question type, curriculum codes, competencies, content type, and style in Python. Prompts must receive concrete constraints rather than asking the LLM to choose them.
- Load endpoints, credentials, models, retry limits, concurrency, and output locations through `src.config.Config`; do not add hardcoded provider settings.
- Keep core modules importable by both CLI and server code. CLI entry points should remain thin orchestration layers.
- Render `chart_spec` before verification so the verifier can inspect the actual PNG.
- Verification must independently solve or inspect the question. Correction retries must be minimal and preserve frozen sampled metadata.
- Re-render an image only when its specification changes.
- Keep math output flat. Do not add social-studies or natural-sciences `subquestions[]` assumptions to math models.
- Verifier strictness and subject-specific frozen fields belong in the subject package instructions.
- Follow `.claude/rules/figure-rendering.md` for image-routing changes and `.claude/rules/question-contracts.md` for schema changes.

## Math Pipeline

- `src/cli.py` owns math orchestration, parsing, rendering, verification, correction, and output.
- `src/sampler.py` owns curriculum-aware random selection and manual overrides.
- `src/context_builder.py` owns math prompt assembly and few-shot injection.
- `src/schemas.py` is the authoritative math output contract.
- `src/renderer.py` is the common rendering entry point for all subjects.

## Verification

```bash
uv run pytest tests/test_math_sampler.py tests/test_math_context_builder.py
uv run pytest tests/test_verifier.py tests/test_renderer_image_generation.py
uv run ruff check src/ tests/
```

## References

- [Project setup and CLI usage](../README.md)
- [CLI execution trace](../LOGIC.md)
- [Figure rendering policy](../docs/figure-rendering-policy.md)
```

- [ ] **Step 5: Create `src/common/CLAUDE.md`**

```markdown
# Shared Generation Utilities Instructions

## Scope

This directory contains subject-neutral loaders, planners, deduplication helpers, and other utilities consumed by more than one generation pipeline.

## Invariants

- Keep shared modules independent of social-studies and natural-sciences package internals.
- Parameterize subject differences through arguments, maps, callbacks, or thin subject shims; do not branch on subject names inside generic loaders unless the shared interface explicitly requires it.
- Preserve existing public function signatures when a subject shim or server route imports them.
- Curriculum filters must return canonical source rows without mutating loaded JSON data.
- Batch deduplication remains prompt-level best effort; do not add embedding or persistence behavior without a separate design.
- Shared helpers must be deterministic for deterministic inputs. Random selection stays in subject samplers.
- Add focused tests for shared behavior and at least one subject-facing integration when changing a shared interface.

## Key Entry Points

- `curriculum_loader.py` — common curriculum JSON loading and stage/subject filtering.
- `core_competency_loader.py` — common competency loading and enum construction.
- `planner.py` — subject-parameterized core-question planning.
- `batch_dedup.py` — prior-scope extraction and prompt formatting.

## Verification

```bash
uv run pytest tests/test_batch_dedup.py
uv run pytest tests/test_math_sampler.py tests/test_natural_sciences_sampler.py
uv run ruff check src/common/ tests/
```
```

- [ ] **Step 6: Create `src/social_studies/CLAUDE.md`**

```markdown
# Social Studies Pipeline Instructions

## Scope

These rules apply to 108課綱 social-studies generation, including history, geography, civics, and cross-subject question sets.

## Invariants

- Parent questions are `題組題`. Generation uses one text-generator call followed by concurrent per-subquestion generator calls.
- Cap subquestion concurrency with `SUBGEN_MAX_CONCURRENCY`; retry failed or unparseable slots with fresh calls up to `SUBGEN_RETRIES`.
- Subject filtering must retain shared `社` learning-performance rows and empty-subject learning-content rows for every subject.
- Empty per-subquestion learning-content or learning-performance selections inherit the global sampled pool at prompt-build time.
- Explicit per-subquestion codes are hard constraints: inject them with must-use wording and force the parsed output to those exact selections.
- Persist submitted per-subquestion instructions as `subquestions[*].出題指示` and preserve them during correction.
- Per-subquestion question types may differ. Blank configured slots are sampled from the allowed social-studies type pool.
- Keep `閱讀歷程` and `文本形式` as diversity axes while framing the pipeline primarily around 108課綱.
- Top-level and per-subquestion images are distinct. Per-subquestion renderer selection overrides the request-level mode; model-emitted renderer metadata is not authoritative.
- Current-events fact checking is opt-in. Provider/tool failures fail open; only a definitive negative result forces correction.
- Correction may repair question content, answers, explanations, rubrics, and image specs, but must restore frozen curriculum and sampled metadata.
- `src/social_studies/schemas.py` is the authoritative output model; do not duplicate its complete field list here.

## Key Entry Points

- `cli.py` — two-stage generation, subquestion dispatch, rendering, verification, and correction.
- `sampler.py` — subject-aware sampling and per-subquestion configuration.
- `context_builder.py` — text and subquestion prompts plus hard LC/LP constraints.
- `verifier.py` and `corrector.py` — teacher verification and targeted correction.
- `fact_check.py` — optional current-events web fact check.

## Verification

```bash
uv run pytest tests/test_social_studies_sampler_assignments.py
uv run pytest tests/test_social_studies_subquestion_images.py
uv run pytest tests/test_social_studies_verifier.py tests/test_social_studies_corrector.py
uv run pytest tests/test_subgen_retry_social_studies.py
uv run ruff check src/social_studies/ tests/
```

## References

- [Adding few-shot samples](../../docs/ADDING_SAMPLES.md)
- [Social-studies data guide](../../data/social_studies/csv_填寫指南.md)
- [Figure rendering policy](../../docs/figure-rendering-policy.md)
```

- [ ] **Step 7: Create `src/natural_sciences/CLAUDE.md`**

```markdown
# Natural Sciences Pipeline Instructions

## Scope

These rules apply to the 108課綱 natural-sciences pipeline with PISA-style scientific-literacy framing.

## Invariants

- `科目` is fixed as `自然科學`; do not add sampler-level biology, physics, chemistry, or earth-science bucketing.
- Derive the learning stage from grade for every question. Grades 7–9 use 第四學習階段 and grades 10–12 use 第五學習階段.
- Choose `情境子類別` only from children of the selected top-level PISA context.
- Sample one or two science competencies from the configured six-value pool.
- Prefer learning content linked from sampled learning performance, then fall back to the full stage pool.
- Generation uses one text-generator call followed by concurrent per-subquestion calls with the same concurrency and retry configuration as social studies.
- Empty per-subquestion LC/LP selections inherit the global pool. Explicit selections are hard constraints and remain verbatim in parsed output.
- Blank configured question types are sampled from the PISA-Science type pool.
- Canonicalize valid curriculum-code spelling, drop unknown codes, and fall back to sampled codes where allowed. Config-pinned codes remain exact.
- Deterministic curriculum validation can fail verification even when the LLM verifier passes.
- The verifier is intentionally lenient and blocks major errors; do not silently make it as strict as math.
- Correction freezes curriculum codes, science competencies, concept, subject, and grade while repairing mutable question content.
- `src/natural_sciences/schemas.py` is the authoritative output model; do not duplicate its complete field list here.

## Key Entry Points

- `cli.py` — two-stage generation, rendering, verification, correction, and output.
- `sampler.py` — grade/stage, context, competency, curriculum, and subquestion sampling.
- `context_builder.py` — curriculum context and two-stage prompts.
- `curriculum_codes.py` — canonical lookup, repair, and deterministic validation.
- `verifier.py` and `corrector.py` — lenient verification and targeted correction.

## Verification

```bash
uv run pytest tests/test_natural_sciences_sampler.py
uv run pytest tests/test_natural_sciences_curriculum_codes.py
uv run pytest tests/test_natural_sciences_verifier.py
uv run pytest tests/test_subgen_retry_natural_sciences.py
uv run ruff check src/natural_sciences/ tests/
```

## References

- [Adding few-shot samples](../../docs/ADDING_SAMPLES.md)
- [Figure rendering policy](../../docs/figure-rendering-policy.md)
```

- [ ] **Step 8: Run the focused instruction tests**

Run:

```bash
uv run pytest tests/test_claude_instructions.py \
  tests/test_context_builder_docstrings.py -q
```

Expected: all tests pass. The existing context-builder test confirms the new root file still links to `docs/figure-rendering-policy.md`.

- [ ] **Step 9: Run Ruff**

Run:

```bash
uv run ruff check tests/test_claude_instructions.py
```

Expected: `All checks passed!`

- [ ] **Step 10: Commit the root and generation scopes**

```bash
git add CLAUDE.md \
  src/CLAUDE.md \
  src/common/CLAUDE.md \
  src/social_studies/CLAUDE.md \
  src/natural_sciences/CLAUDE.md \
  tests/test_claude_instructions.py
git commit -m "docs: split generation instructions by subject" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Add Backend, Frontend, Data, Script, Test, and Migration Scopes

**Files:**
- Create: `server/CLAUDE.md`
- Create: `server/generate/CLAUDE.md`
- Create: `web/CLAUDE.md`
- Create: `data/CLAUDE.md`
- Create: `scripts/CLAUDE.md`
- Create: `tests/CLAUDE.md`
- Create: `alembic/CLAUDE.md`
- Modify: `tests/test_claude_instructions.py`

**Interfaces:**
- Consumes: Task 2 root scope map and repository-level test functions.
- Produces: complete nested instruction inventory required by the design spec.

- [ ] **Step 1: Extend the nested-file inventory and verify it fails**

Replace `_NESTED_INSTRUCTIONS` in `tests/test_claude_instructions.py` with:

```python
_NESTED_INSTRUCTIONS = [
    _ROOT / "src" / "CLAUDE.md",
    _ROOT / "src" / "common" / "CLAUDE.md",
    _ROOT / "src" / "social_studies" / "CLAUDE.md",
    _ROOT / "src" / "natural_sciences" / "CLAUDE.md",
    _ROOT / "server" / "CLAUDE.md",
    _ROOT / "server" / "generate" / "CLAUDE.md",
    _ROOT / "web" / "CLAUDE.md",
    _ROOT / "data" / "CLAUDE.md",
    _ROOT / "scripts" / "CLAUDE.md",
    _ROOT / "tests" / "CLAUDE.md",
    _ROOT / "alembic" / "CLAUDE.md",
]
```

Run:

```bash
uv run pytest tests/test_claude_instructions.py -q
```

Expected: FAIL with seven missing instruction files.

- [ ] **Step 2: Create `server/CLAUDE.md`**

```markdown
# Server Instructions

## Scope

These rules apply to the FastAPI application, authentication, persistence, history, utility routes, and application lifecycle under `server/`.

## Invariants

- Keep request validation in Pydantic request models and server configuration in `server.config.ServerConfig`.
- Use async SQLAlchemy patterns consistently. Do not introduce blocking database calls on the event loop.
- Authenticate protected routes and scope reads/writes to the current owner.
- Preserve existence hiding: resources owned by another user return 404 rather than revealing that they exist.
- Keep persistence failures from crashing successful generation unless persistence is the requested operation.
- Keep startup pruning and retention behavior controlled by environment configuration.
- Do not serialize secrets, provider credentials, or raw authorization headers into logs or API responses.
- Generation-specific queue, SSE, worker, and exchange behavior belongs in `server/generate/CLAUDE.md`.

## Key Entry Points

- `app.py` — application creation and startup lifecycle.
- `config.py` — server environment configuration.
- `models.py` — persistence models.
- `auth/` — authentication and current-user dependencies.
- `history/` — owned generation history access.
- `utility/` — subject schemas and supporting endpoints.

## Verification

```bash
uv run pytest tests/server -q
uv run ruff check server/ tests/server/
```

## References

- [Project setup and server usage](../README.md)
- [Web request lifecycle](../FLOW.md)
- [Deployment guide](../DEPLOYMENT.md)
```

- [ ] **Step 3: Create `server/generate/CLAUDE.md`**

```markdown
# Generation Service Instructions

## Scope

This directory owns generation request models, routes, worker coordination, SSE payloads, result assembly, and LLM exchange recording.

## Invariants

- Preserve existing SSE event names, ordering, payload shapes, and terminal behavior unless a separately approved API change updates backend and frontend together.
- Keep blocking generation work off the event loop. Threaded workers may share only explicitly synchronized state.
- A result payload must preserve the subject-specific question schema and may add transport-only fields such as `image_base64`.
- Strip embedded base64 data before persisting history records where the existing storage path expects file references or compact JSON.
- Keep question-scoped updates and final results compatible with `web/src/hooks/useGenerate.ts`.
- `ExchangeRecorder` is thread-safe across parallel sub-generators. Persistence failures log a warning and never fail generation.
- Retention setting `LLM_EXCHANGE_RETENTION_DAYS=0` disables exchange persistence and pruning.
- Preserve ownership checks for log and exchange endpoints.
- Do not document or implement branch-only progress/cancellation protocols until their production changes are merged into the target branch.

## Key Entry Points

- `models.py` — HTTP generation and planning parameters.
- `routes.py` — authenticated endpoints and SSE response setup.
- `service.py` — worker orchestration, event emission, result payloads, and persistence handoff.
- `exchange_recorder.py` — request/response pairing and LLM exchange persistence.

## Verification

```bash
uv run pytest tests/server/test_generate_routes.py -q
uv run pytest tests/server/test_generate_service_coverage.py -q
uv run pytest tests/server/test_history_routes.py -q
uv run ruff check server/generate/ tests/server/
```

## References

- [Web generation flow](../../FLOW.md)
```

- [ ] **Step 4: Create `web/CLAUDE.md`**

```markdown
# Web Frontend Instructions

## Scope

These rules apply to the React 19 and TypeScript frontend under `web/`.

## Invariants

- Keep API payload types synchronized with backend Pydantic models and subject-specific question contracts.
- Centralize HTTP calls in `src/api/` and generation-stream handling in `src/hooks/useGenerate.ts`.
- Use Zustand stores for shared client state already owned by a store; keep component-local state local.
- Treat SSE as an ordered protocol. Handle every documented terminal event and preserve partial question updates.
- Keep Chinese schema keys unchanged in TypeScript interfaces and rendering code.
- Add user-facing copy through `src/i18n/messages.ts`; do not hardcode untranslated UI text in new shared components.
- Preserve keyboard access, labels, alt text, and visible focus behavior when changing forms or question display.
- Keep ODT export synchronized with on-screen support for top-level and per-subquestion images.
- Use `web/package.json` as the authoritative command and dependency list.
- Follow `.claude/rules/question-contracts.md` for cross-layer field changes and `.claude/rules/figure-rendering.md` for image changes.

## Key Entry Points

- `src/hooks/useGenerate.ts` — generation request, SSE events, and question types.
- `src/components/ParamForm.tsx` — subject-aware generation controls.
- `src/components/QuestionCard.tsx` — question and image display.
- `src/pages/` — route-level screens.
- `src/utils/odt.ts` — document export.

## Verification

```bash
npm --prefix web test
npm --prefix web run lint
npm --prefix web run build
```

## References

- [Project setup](../README.md)
- [Web generation flow](../FLOW.md)
- [Figure rendering policy](../docs/figure-rendering-policy.md)
```

- [ ] **Step 5: Create `data/CLAUDE.md`**

```markdown
# Data Instructions

## Scope

This directory contains runtime curriculum, schema, few-shot, example-exam, converted-source, and generated data assets.

## Data Ownership

- `data/curriculum/` contains legacy K–12 math source data used by the reproducible math curriculum builder.
- `data/math/curriculum/` is generated by `scripts/build_math_curriculum.py`; change its source or builder and regenerate it.
- `data/natural_sciences/curriculum/learning_content.json`, `learning_performance.json`, and `core_competencies.json` are generated by `scripts/build_natural_sciences_curriculum.py` from the canonical converted workbook.
- Social-studies runtime schemas are CSV-driven and curriculum is JSON-driven. Use `scripts/connect_curriculum_from_odt.py` when rebuilding ODT-derived cross-links.
- Files prefixed with `範例_` are researcher references and are not runtime inputs.
- Few-shot loaders differ by subject; follow `docs/ADDING_SAMPLES.md` before adding or moving examples.

## Invariants

- Preserve UTF-8/UTF-8-SIG expectations and `;` separators in researcher-editable CSVs.
- Do not hand-edit generated outputs without changing the canonical source or generator in the same change.
- Preserve Chinese keys and curriculum code spelling exactly unless the owning loader defines canonicalization.
- Keep image manifests and their referenced files together.
- Do not commit secrets, generated exam outputs, or local databases under `data/`.
- Follow `.claude/rules/generated-assets.md` for source/output synchronization.

## Verification

```bash
uv run pytest tests/test_math_sampler.py -q
uv run pytest tests/test_social_studies_few_shot.py -q
uv run pytest tests/test_natural_sciences_few_shot.py -q
uv run pytest tests/test_natural_sciences_curriculum_stage.py -q
```

## References

- [Adding few-shot samples](../docs/ADDING_SAMPLES.md)
- [Social-studies data guide](social_studies/csv_填寫指南.md)
```

- [ ] **Step 6: Create `scripts/CLAUDE.md`**

```markdown
# Scripts Instructions

## Scope

This directory contains reproducible curriculum builders, one-shot importers, converters, evidence tools, and staging smoke tests.

## Invariants

- Run scripts from the repository root and use `uv run python` for Python entry points unless the script documents another runtime.
- Builders own their generated outputs. Commit generator/source changes and regenerated files together.
- Keep canonical input paths and output shapes explicit in module docstrings or CLI help.
- Make conversion scripts deterministic for identical inputs.
- Read credentials and target URLs from environment variables; never commit them.
- Smoke tests must report the failing layer clearly and exit non-zero on failure.
- Avoid converting one-shot research utilities into runtime dependencies without a separate design.
- Follow `.claude/rules/generated-assets.md` when a script writes under `data/`.

## Key Entry Points

- `build_math_curriculum.py` — reshaped math curriculum and competencies.
- `build_natural_sciences_curriculum.py` — natural-sciences curriculum JSON.
- `connect_curriculum_from_odt.py` — social-studies curriculum cross-links.
- `smoke_test.sh` and `smoke_test_natural_sciences.sh` — staging probes.
- `pdf_to_fewshot_JSON/` — standalone PDF-to-few-shot workflow.

## Verification

```bash
uv run pytest tests/test_build_fidelity_manifest.py -q
uv run ruff check scripts/ tests/
```

## References

- [Adding few-shot samples](../docs/ADDING_SAMPLES.md)
- [Staging and deployment](../DEPLOYMENT.md)
```

- [ ] **Step 7: Create `tests/CLAUDE.md`**

```markdown
# Test Instructions

## Scope

These rules apply to Python tests under `tests/`. Frontend Vitest files follow `web/CLAUDE.md`.

## Invariants

- Run the narrowest relevant test first, then the full suite before completion.
- Use deterministic fakes for LLM clients, renderers, clocks, and persistence boundaries. Unit tests must not call paid or external providers.
- Test observable contracts rather than implementation details or source line numbers.
- Keep subject-specific fixtures explicit; do not silently reuse a social-studies shape for natural sciences or math.
- When a shared interface changes, cover the common behavior and at least one affected consumer.
- Documentation-contract tests belong in `test_claude_instructions.py` and `test_context_builder_docstrings.py`.
- Preserve clear assertion messages for path inventories and policy synchronization.

## Verification

```bash
uv run pytest tests/test_claude_instructions.py -q
uv run pytest tests/server -q
uv run pytest
uv run ruff check tests/
```

## References

- [Figure rendering policy](../docs/figure-rendering-policy.md)
```

- [ ] **Step 8: Create `alembic/CLAUDE.md`**

```markdown
# Alembic Migration Instructions

## Scope

These rules apply to Alembic configuration and database revisions.

## Invariants

- Keep one coherent revision chain. Set `down_revision` to the actual current head unless the change intentionally creates a documented branch.
- Do not rewrite a migration that may have been deployed; add a new revision.
- Keep upgrades compatible with PostgreSQL production behavior and verify SQLite development/test behavior where the application supports it.
- Treat enum changes, foreign keys, indexes, and destructive column changes explicitly; do not rely on backend-specific implicit behavior.
- Provide a meaningful downgrade when reversal is safe. If reversal would destroy data, make the limitation explicit in the revision.
- Keep model changes and migration changes in the same feature commit series.
- Do not place application data migrations in startup code when an Alembic revision owns the change.

## Verification

```bash
uv run alembic heads
uv run alembic history
uv run pytest tests/server -q
```

Run upgrade/downgrade checks only against a disposable test database configured for that migration task.

## References

- [Deployment guide](../DEPLOYMENT.md)
```

- [ ] **Step 9: Run the expanded contract tests**

Run:

```bash
uv run pytest tests/test_claude_instructions.py -q
```

Expected: all tests pass with the complete nested instruction inventory.

- [ ] **Step 10: Run focused backend and frontend checks**

Run:

```bash
uv run pytest tests/server/test_generate_routes.py -q
npm --prefix web test
```

Expected: both commands pass; documentation-only changes do not alter runtime tests.

- [ ] **Step 11: Commit the remaining nested scopes**

```bash
git add server/CLAUDE.md \
  server/generate/CLAUDE.md \
  web/CLAUDE.md \
  data/CLAUDE.md \
  scripts/CLAUDE.md \
  tests/CLAUDE.md \
  alembic/CLAUDE.md \
  tests/test_claude_instructions.py
git commit -m "docs: add scoped project instructions" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Add Path-Scoped Cross-Cutting Rules

**Files:**
- Create: `.claude/rules/figure-rendering.md`
- Create: `.claude/rules/question-contracts.md`
- Create: `.claude/rules/generated-assets.md`
- Create: `.claude/rules/documentation.md`
- Modify: `tests/test_claude_instructions.py`
- Test: `tests/test_context_builder_docstrings.py`
- Test: `tests/test_figure_rendering_policy.py`

**Interfaces:**
- Consumes: complete nested hierarchy and Task 1 frontmatter parser.
- Produces: four path-scoped contracts and final test coverage for rule inventory and non-empty `paths` lists.

- [ ] **Step 1: Add failing rule inventory and frontmatter tests**

Replace `_RULE_FILES` with:

```python
_RULE_FILES = [
    _ROOT / ".claude" / "rules" / "figure-rendering.md",
    _ROOT / ".claude" / "rules" / "question-contracts.md",
    _ROOT / ".claude" / "rules" / "generated-assets.md",
    _ROOT / ".claude" / "rules" / "documentation.md",
]
```

Add this test after `test_instruction_files_stay_within_line_budgets`:

```python
@pytest.mark.parametrize("path", _RULE_FILES, ids=_relative_id)
def test_path_scoped_rules_have_nonempty_paths(path: Path) -> None:
    paths = _parse_paths_frontmatter(path.read_text(encoding="utf-8"))
    assert paths is not None, f"{_relative_id(path)} has no frontmatter"
    assert paths, f"{_relative_id(path)} has an empty paths list"
    assert all(pattern.strip() for pattern in paths), (
        f"{_relative_id(path)} has a blank path pattern"
    )
```

Run:

```bash
uv run pytest tests/test_claude_instructions.py -q
```

Expected: FAIL because the four rule files do not exist.

- [ ] **Step 2: Create `.claude/rules/figure-rendering.md`**

```markdown
---
paths:
  - "src/context_builder.py"
  - "src/social_studies/context_builder.py"
  - "src/natural_sciences/context_builder.py"
  - "src/renderer.py"
  - "src/html_renderer.py"
  - "src/cli.py"
  - "src/social_studies/cli.py"
  - "src/natural_sciences/cli.py"
  - "src/schemas.py"
  - "src/social_studies/schemas.py"
  - "src/natural_sciences/schemas.py"
  - "server/generate/service.py"
  - "server/history/routes.py"
  - "web/src/hooks/useGenerate.ts"
  - "web/src/components/ParamForm.tsx"
  - "web/src/components/FigureRenderer.tsx"
  - "web/src/components/QuestionCard.tsx"
  - "web/src/components/QuestionCard.test.tsx"
  - "web/src/utils/odt.ts"
  - "web/src/utils/odt.test.ts"
  - "tests/test_context_builder_docstrings.py"
  - "tests/test_figure_rendering_policy.py"
  - "tests/test_renderer_image_generation.py"
  - "tests/test_social_studies_subquestion_images.py"
  - "tests/server/test_generate_routes.py"
---

# Figure Rendering Contract

- [Figure rendering policy](../../docs/figure-rendering-policy.md) is authoritative. Update it before changing routing instructions or renderer behavior.
- Keep all three context-builder module docstrings linked to the policy.
- `純文字` must not emit `chart_spec`.
- Illustrative figures, geometry, maps, forms, menus, and diagrams use `render_mode: "html"`.
- Statistical charts use `render_mode: "chart"`; tables use `render_mode: "html"`.
- `src.renderer.render_image()` remains the common entry point.
- `image_generation_mode="html"` follows deterministic chart or HTML rendering. `image_generation_mode="gpt_image"` bypasses both and uses the configured image model.
- Render PNGs before verification so multimodal verification sees the actual artifact.
- Re-render only when `chart_spec` changes.
- Social studies supports top-level and per-subquestion images. Preserve submitted per-subquestion renderer precedence over request-level fallback.
- The server may add transport-only `image_base64`; persistence should keep its existing compact/file-reference behavior.
- Keep frontend display and ODT export synchronized for top-level and per-subquestion images.
- Update focused rendering, payload, and frontend tests with any contract change.
- When adding a new rendering consumer, add its exact path here; do not replace the list with a broad catch-all glob.
```

- [ ] **Step 3: Create `.claude/rules/question-contracts.md`**

```markdown
---
paths:
  - "src/schemas.py"
  - "src/social_studies/schemas.py"
  - "src/natural_sciences/schemas.py"
  - "src/cli.py"
  - "src/social_studies/cli.py"
  - "src/natural_sciences/cli.py"
  - "server/generate/models.py"
  - "server/generate/routes.py"
  - "server/generate/service.py"
  - "server/history/routes.py"
  - "server/utility/routes.py"
  - "web/src/api/client.ts"
  - "web/src/hooks/useGenerate.ts"
  - "web/src/components/ParamForm.tsx"
  - "web/src/components/QuestionCard.tsx"
  - "web/src/pages/HistoryDetail.tsx"
  - "web/src/utils/odt.ts"
  - "tests/server/test_generate_routes.py"
  - "tests/server/test_history_routes.py"
  - "web/src/components/QuestionCard.test.tsx"
  - "web/src/utils/odt.test.ts"
---

# Question Contract Synchronization

- Treat Chinese JSON keys and subject-specific output shapes as compatibility contracts.
- `src/schemas.py`, `src/social_studies/schemas.py`, and `src/natural_sciences/schemas.py` are the authoritative generation models. Do not copy their full schemas into documentation.
- Math remains flat. Social studies and natural sciences use `subquestions[]`; do not force one subject shape onto another.
- Preserve legacy compatibility fields unless a separately approved migration updates every producer and consumer.
- A field change must cover all affected layers in one change: generator parsing, Pydantic model, server request/result serialization, persistence/history, frontend types and display, export, and focused tests.
- Transport-only fields such as `image_base64` do not become generation-model fields unless the architecture explicitly changes.
- Per-subquestion configured curriculum codes and instructions must survive parsing, correction, persistence, display, and export.
- Validate enum/value changes against the runtime schema source: math JSON configuration or subject CSV configuration.
- Add exact new consumers to this rule's `paths` list when they begin depending on the question contract.
```

- [ ] **Step 4: Create `.claude/rules/generated-assets.md`**

```markdown
---
paths:
  - "data/**/*"
  - "scripts/build_math_curriculum.py"
  - "scripts/build_natural_sciences_curriculum.py"
  - "scripts/connect_curriculum_from_odt.py"
  - "scripts/build_fidelity_manifest.py"
  - "scripts/extract_few_shot_images.py"
  - "scripts/ns_few_shot_converter.py"
  - "scripts/pdf_to_fewshot_JSON/**/*"
  - "tests/test_*curriculum*.py"
  - "tests/test_*few_shot*.py"
  - "tests/test_build_fidelity_manifest.py"
---

# Generated Asset Contract

- Identify the canonical source before editing a generated file.
- Change the canonical source or generator, run the owning builder, and commit both generator/source and generated outputs together.
- Do not hand-maintain generated curriculum JSON when a reproducible builder owns it.
- `scripts/build_math_curriculum.py` owns reshaped math curriculum assets under `data/math/curriculum/`.
- `scripts/build_natural_sciences_curriculum.py` owns generated natural-sciences curriculum JSON from the canonical converted workbook.
- `scripts/connect_curriculum_from_odt.py` owns ODT-derived social-studies cross-links.
- Keep few-shot image files and manifests synchronized; loaders must not point to missing assets.
- Preserve CSV encoding and separator conventions.
- `範例_` files are references, not runtime inputs.
- Run the focused curriculum or few-shot tests after regeneration.
- If a new builder writes under `data/`, add the builder and its focused tests to this rule's `paths` list.

## Reference

- [Adding few-shot samples](../../docs/ADDING_SAMPLES.md)
```

- [ ] **Step 5: Create `.claude/rules/documentation.md`**

```markdown
---
paths:
  - "*.md"
  - "**/*.md"
  - ".claude/rules/*.md"
  - "tests/test_claude_instructions.py"
  - "tests/test_context_builder_docstrings.py"
---

# Documentation and Instruction Ownership

## Put Guidance in the Smallest Durable Owner

1. Root `CLAUDE.md` only for repository-wide invariants and routing.
2. Nearest nested `CLAUDE.md` for one directory tree.
3. Path-scoped rule for one contract spanning separate trees.
4. Owned document for explanatory or operational detail.
5. Spec or plan for feature-specific, historical, or temporary decisions.

## Budgets

- Root `CLAUDE.md`: at most 100 lines.
- Nested `CLAUDE.md`: at most 180 lines.
- `.claude/rules/*.md`: at most 140 lines.

## Content Rules

- Use normal Markdown links for large references. Do not inline README, FLOW, or LOGIC through Claude Code imports.
- Keep parent and child instructions additive; never depend on a child overriding its parent.
- Use stable paths and symbols, not source line numbers.
- Do not copy complete schemas, exhaustive file tables, execution waterfalls, issue narratives, branch state, or volatile dataset counts into instruction files.
- Update or remove obsolete guidance instead of appending a second version.
- Treat files under `docs/superpowers/` as design and task records, not automatically active policy.
- Run `tests/test_claude_instructions.py` after changing instruction structure, links, frontmatter, or budgets.
```

- [ ] **Step 6: Run the complete instruction contract suite**

Run:

```bash
uv run pytest tests/test_claude_instructions.py \
  tests/test_context_builder_docstrings.py -q
```

Expected: all tests pass, including non-empty rule paths and the existing root rendering-policy link.

- [ ] **Step 7: Run focused rendering policy tests**

Run:

```bash
uv run pytest tests/test_figure_rendering_policy.py \
  tests/test_renderer_image_generation.py \
  tests/test_social_studies_subquestion_images.py \
  tests/server/test_generate_routes.py -q
```

Expected: all tests pass; the new rule documents existing behavior without changing it.

- [ ] **Step 8: Run Ruff**

Run:

```bash
uv run ruff check tests/test_claude_instructions.py
```

Expected: `All checks passed!`

- [ ] **Step 9: Commit the path-scoped rules and final contract tests**

```bash
git add .claude/rules/figure-rendering.md \
  .claude/rules/question-contracts.md \
  .claude/rules/generated-assets.md \
  .claude/rules/documentation.md \
  tests/test_claude_instructions.py
git commit -m "docs: add path-scoped project rules" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Verify Loading Behavior and the Full Repository

**Files:**
- Verify: `CLAUDE.md`
- Verify: all nested `CLAUDE.md` files
- Verify: `.claude/rules/*.md`
- Verify: `tests/test_claude_instructions.py`
- Verify untouched: `docs/superpowers/plans/2026-07-22-generation-progress-bar.md`

**Interfaces:**
- Consumes: completed instruction hierarchy and contract suite.
- Produces: evidence that automated contracts, existing tests, and Claude Code loading behavior satisfy the design.

- [ ] **Step 1: Run the focused documentation and policy tests**

```bash
uv run pytest tests/test_claude_instructions.py \
  tests/test_context_builder_docstrings.py \
  tests/test_figure_rendering_policy.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run focused Python lint**

```bash
uv run ruff check tests/test_claude_instructions.py
```

Expected: `All checks passed!`

- [ ] **Step 3: Run the full Python test suite**

```bash
uv run pytest
```

Expected: all tests pass. If an environment-dependent test is skipped, report the skip; do not describe it as a pass.

- [ ] **Step 4: Run frontend tests**

```bash
npm --prefix web test
```

Expected: all Vitest tests pass.

- [ ] **Step 5: Record the existing frontend lint baseline**

```bash
npm --prefix web run lint
```

Expected on `main` as of 2026-07-23: exit 1 with six existing `react-hooks/set-state-in-effect` errors—five in `web/src/components/ParamForm.tsx` and one in `web/src/pages/VerifyPage.tsx`. Because this implementation changes no TypeScript, confirm there are no additional lint errors. If those six baseline errors have already been fixed before execution, expect the command to pass.

- [ ] **Step 6: Check instruction line counts directly**

Run:

```bash
wc -l CLAUDE.md \
  src/CLAUDE.md \
  src/common/CLAUDE.md \
  src/social_studies/CLAUDE.md \
  src/natural_sciences/CLAUDE.md \
  server/CLAUDE.md \
  server/generate/CLAUDE.md \
  web/CLAUDE.md \
  data/CLAUDE.md \
  scripts/CLAUDE.md \
  tests/CLAUDE.md \
  alembic/CLAUDE.md \
  .claude/rules/*.md
```

Expected: root is at most 100 lines, nested files at most 180, and rules at most 140. This duplicates the automated assertion intentionally as human-readable review evidence.

- [ ] **Step 7: Verify Claude Code loading manually**

In a fresh Claude Code session started at the repository root:

1. Run `/context` and confirm the root project `CLAUDE.md` is loaded.
2. Read `src/social_studies/verifier.py`, run `/context`, and confirm `src/CLAUDE.md` and `src/social_studies/CLAUDE.md` appear while `src/natural_sciences/CLAUDE.md` does not.
3. Read `server/generate/service.py`, run `/context`, and confirm `server/CLAUDE.md`, `server/generate/CLAUDE.md`, `figure-rendering.md`, and `question-contracts.md` appear.
4. Record the observed loaded-file list in the task summary; do not add it to standing documentation because it is verification evidence, not a durable rule.

- [ ] **Step 8: Confirm git isolation and diff scope**

Run:

```bash
git status --short
git diff main...HEAD --stat
git diff main...HEAD --name-only
```

Expected:

- the diff contains only the committed design spec, this implementation plan if committed separately, instruction files, rules, and `tests/test_claude_instructions.py`;
- `docs/superpowers/plans/2026-07-22-generation-progress-bar.md` remains untracked and unchanged;
- no production Python, TypeScript, schema, data, or migration file appears in the diff.

- [ ] **Step 9: Commit only if verification required a real fix**

If Steps 1–8 required a correction, stage only the corrected instruction/test files and commit:

```bash
git add CLAUDE.md .claude/rules src/CLAUDE.md src/common/CLAUDE.md \
  src/social_studies/CLAUDE.md src/natural_sciences/CLAUDE.md \
  server/CLAUDE.md server/generate/CLAUDE.md web/CLAUDE.md \
  data/CLAUDE.md scripts/CLAUDE.md tests/CLAUDE.md alembic/CLAUDE.md \
  tests/test_claude_instructions.py
git commit -m "docs: finalize scoped instruction contracts" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
```

If no correction was needed, do not create an empty commit.
