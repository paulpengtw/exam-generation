# Spec: Path-scoped Claude Code instructions

## Why

The repository root `CLAUDE.md` has grown to 497 lines and combines durable coding rules with architecture summaries, file inventories, full output schemas, data formats, execution traces, environment variables, and recent feature history. Much of that material duplicates `README.md`, `FLOW.md`, `LOGIC.md`, policy documents, and source code. The duplication increases initial instruction context, makes unrelated guidance visible during focused work, and has already drifted from current function locations and generation behavior.

Claude Code supports layered project instructions: root and ancestor `CLAUDE.md` files load at session start, nested files load when Claude reads files in those subtrees, and parent/child files are concatenated rather than treated as reliable overrides. It also supports path-scoped files under `.claude/rules/`. The repository should use those mechanisms to keep global context small and load detailed guidance only when relevant.

## Goals

1. Reduce the root `CLAUDE.md` to durable repository-wide guidance and a scope map.
2. Colocate subsystem-specific rules with the code they govern.
3. Use path-scoped rules for contracts spanning otherwise separate directory trees.
4. Replace copied reference material with links to owned documentation or source-of-truth code.
5. Add lightweight checks that prevent the root file and scoped files from becoming catch-alls again.
6. Preserve all current behavior; this phase changes instructions and documentation contracts only.

## Non-goals

- Rewriting production code, schemas, curriculum assets, or generation behavior.
- Fully reconciling stale or duplicated content in `README.md`, `FLOW.md`, `LOGIC.md`, the frontend README, or the social-studies data guide. That is a separate Phase 2 design.
- Using `@path` imports to inline large documents. Imports still consume instruction context and therefore do not provide the desired efficiency.
- Creating instruction files for individual modules or every leaf directory.
- Incorporating active progress-bar branch behavior that is not present on `main`.

## Documented Claude Code behavior

The design relies on the following documented behavior:

- A project root `CLAUDE.md` loads with the session.
- Nested `CLAUDE.md` files below the working directory load on demand when Claude reads files in their subtrees.
- Discovered instruction files are concatenated from broader to narrower scope; a child file is not a deterministic override.
- `.claude/rules/*.md` files may declare a YAML frontmatter `paths` list. A rule activates when Claude works with matching files.
- Rules without `paths` load unconditionally.
- `@path` imports are expanded into instruction context. They organize content but do not reduce it.
- `/context` displays loaded memory and instruction files and is the manual verification surface.

References:

- [Memory and project instructions](https://code.claude.com/docs/en/memory.md)
- [Monorepos and large codebases](https://code.claude.com/docs/en/large-codebases.md)

## Architecture

Use a hybrid model: nested files for directory-owned behavior and path-scoped rules for cross-cutting contracts.

```text
CLAUDE.md

.claude/
└── rules/
    ├── figure-rendering.md
    ├── question-contracts.md
    ├── generated-assets.md
    └── documentation.md

src/
├── CLAUDE.md
├── common/CLAUDE.md
├── social_studies/CLAUDE.md
└── natural_sciences/CLAUDE.md

server/
├── CLAUDE.md
└── generate/CLAUDE.md

web/CLAUDE.md
data/CLAUDE.md
scripts/CLAUDE.md
tests/CLAUDE.md
alembic/CLAUDE.md
```

No additional instruction file should be introduced during Phase 1. A future file requires an independently owned contract that cannot fit an existing scope without making that scope misleading.

## Size budgets

The budgets are enforced maxima, not targets to fill:

- root `CLAUDE.md`: at most 100 lines;
- nested `CLAUDE.md`: at most 180 lines each;
- `.claude/rules/*.md`: at most 140 lines each.

Most files should remain materially shorter. Explanatory detail that pushes a file toward its maximum belongs in an owned document, not in the instruction layer.

## Root `CLAUDE.md`

The root becomes a routing layer with five responsibilities:

1. A one-paragraph project overview covering the three subject pipelines.
2. Repository-wide invariants:
   - Python 3.11+, `uv`, type hints, Pydantic, and absolute `src.*` imports;
   - secrets and endpoints come from environment configuration;
   - Chinese output field names are intentional compatibility contracts;
   - curriculum remains direct-context rather than RAG;
   - source code and focused policy documents take precedence over historical plans.
3. Common install, test, and lint commands.
4. A compact path-to-instruction scope map.
5. Pointers to canonical references, including the required `docs/figure-rendering-policy.md` link.

The root must not contain subject-specific schemas, sampler details, long file tables, execution waterfalls, or feature history.

## Nested instruction ownership

### `src/CLAUDE.md`

Owns Python generation-engine contracts shared across the flat math pipeline and subject packages:

- script-side sampling rather than LLM-selected parameters;
- generation, rendering, verification, correction, and retry boundaries;
- model/client configuration conventions;
- math's flat question shape at a summary level;
- shared focused verification commands;
- delegation of subject-specific verifier and schema differences to child files.

### `src/common/CLAUDE.md`

Owns shared utilities and their neutrality requirements:

- curriculum and competency loaders;
- common planner interfaces;
- batch deduplication contracts;
- utilities shared by multiple subject packages;
- prohibition on introducing subject-specific assumptions into common code.

### `src/social_studies/CLAUDE.md`

Owns only social-studies differences:

- two-stage text-generator and concurrent subquestion-generator pipeline;
- subject filtering and shared `社`/empty curriculum buckets;
- per-subquestion configuration inheritance and pinned LC/LP behavior;
- social-studies output fields and rubric conventions at an invariant level;
- optional current-events fact check and fail-open behavior;
- social-studies verifier/corrector boundaries.

### `src/natural_sciences/CLAUDE.md`

Owns only natural-sciences differences:

- fixed `自然科學` subject and no sampler-level subject bucketing;
- grade-to-stage mapping and cross-concept context;
- PISA context/sub-context and science competency rules;
- per-subquestion configuration behavior;
- deterministic curriculum-code repair and validation;
- lenient verifier stance and correction metadata freeze.

### `server/CLAUDE.md`

Owns backend-wide contracts:

- FastAPI and async SQLAlchemy patterns;
- authentication and ownership checks;
- existence-hiding behavior;
- persistence and startup-lifecycle expectations;
- backend verification commands.

### `server/generate/CLAUDE.md`

Owns generation-service contracts:

- SSE event compatibility;
- worker and queue boundaries;
- cancellation and terminal-state behavior present on the target branch;
- batch coordination and result compatibility;
- exchange recording and persistence failure behavior;
- focused route/service tests.

Phase 1 is based on `main`; it must not copy unmerged progress-bar branch behavior into this file.

### `web/CLAUDE.md`

Owns frontend conventions:

- React and TypeScript patterns used by the project;
- Zustand/API/SSE state-flow boundaries;
- subject-specific form behavior at the interface-contract level;
- i18n, accessibility, and frontend testing expectations;
- frontend commands from `web/package.json` rather than copied dependency catalogs.

### `data/CLAUDE.md`

Owns data classification and edit safety:

- runtime-editable versus generated versus canonical-source assets;
- curriculum and few-shot directory conventions;
- encoding and multi-value separator rules;
- reference-only `範例_` naming;
- links to detailed contributor guides instead of duplicating formats.

### `scripts/CLAUDE.md`

Owns operational script contracts:

- builders and importers define generated-file ownership;
- smoke-test output and environment expectations;
- expected working directory and reproducibility;
- requirement to update generated outputs through their canonical builder rather than manual edits.

### `tests/CLAUDE.md`

Owns test organization:

- focused tests before full-suite verification;
- subject/backend/frontend test boundaries;
- documentation-contract test ownership;
- avoiding tests tied to volatile source line numbers.

### `alembic/CLAUDE.md`

Owns migration discipline:

- revision-chain integrity;
- PostgreSQL versus SQLite considerations;
- enum and downgrade constraints;
- migration verification expectations.

## Cross-cutting path-scoped rules

Every initial rule has a non-empty `paths` list. None loads unconditionally.

### `.claude/rules/figure-rendering.md`

Applies to prompt builders, renderers, backend image embedding, relevant frontend display/export code, and rendering-policy tests. It states only the synchronization contract:

- `docs/figure-rendering-policy.md` is authoritative;
- update the policy before prompt routing text;
- keep all subject context-builder docstrings and content-type instructions aligned;
- preserve renderer/backend precedence and test coverage.

Frontmatter syntax and required core matches:

```md
---
paths:
  - "src/**/*context_builder.py"
  - "src/{renderer,html_renderer}.py"
  - "tests/test_figure_rendering_policy.py"
  - "tests/test_context_builder_docstrings.py"
  # Add the exact current backend and frontend consumers found during migration.
---
```

Before committing Phase 1, the migration must locate the current backend and frontend consumers and add them as exact files or narrow globs. Broad catch-all patterns such as `server/generate/**/*.py` or `web/src/**/*.{ts,tsx}` are prohibited unless every matched file participates in the rendering contract.

### `.claude/rules/question-contracts.md`

Applies across generation schemas, parsing, API serialization, frontend consumers, exports, and compatibility tests. It records:

- Chinese field names and subject-specific shapes are API contracts;
- schema changes require synchronized producer, transport, consumer, export, and test updates;
- legacy compatibility fields may not be removed casually;
- detailed schemas live in Pydantic models and API types, not in instruction prose.

### `.claude/rules/generated-assets.md`

Applies to `data/`, curriculum/few-shot builders and importers under `scripts/`, and their tests. It records:

- which side owns the canonical source;
- generated files must be rebuilt, not hand-maintained;
- edits to generators and generated outputs belong in the same change;
- reference-only assets are not runtime inputs.

### `.claude/rules/documentation.md`

Applies to Markdown, all `CLAUDE.md` files, `.claude/rules/`, and instruction-contract tests. It records:

- the ownership decision tree;
- size budgets;
- normal links rather than large `@path` imports;
- no copied schemas, exhaustive file inventories, execution waterfalls, issue history, volatile counts, or source line numbers;
- historical specs and plans are task records, not standing policy.

## Standard content template

Each nested instruction file uses the following structure, omitting empty sections:

```md
# <Scope> Instructions

## Scope
One or two sentences defining ownership.

## Invariants
The durable rules that must remain true.

## Key entry points
Only stable paths or symbols needed for orientation.

## Verification
Focused commands for this scope.

## References
Links to detailed documentation.
```

The template is not a mandate to fill every section. “Key entry points” must remain selective and must not become another exhaustive file inventory.

## Migration of current root content

| Current root content | New owner |
|---|---|
| Global project identity, conventions, commands | root `CLAUDE.md` |
| Script-side generation and math pipeline | `src/CLAUDE.md` |
| Shared loaders and planners | `src/common/CLAUDE.md` |
| Social-studies behavior | `src/social_studies/CLAUDE.md` |
| Natural-sciences behavior | `src/natural_sciences/CLAUDE.md` |
| FastAPI, auth, persistence | `server/CLAUDE.md` |
| Generation routes, workers, SSE, exchanges | `server/generate/CLAUDE.md` |
| Frontend form and stream behavior | `web/CLAUDE.md` |
| Curriculum and few-shot ownership | `data/CLAUDE.md` |
| Builders, importers, smoke tests | `scripts/CLAUDE.md` |
| Test conventions | `tests/CLAUDE.md` |
| Migration discipline | `alembic/CLAUDE.md` |
| Rendering synchronization | `.claude/rules/figure-rendering.md` |
| Cross-layer schema compatibility | `.claude/rules/question-contracts.md` |
| Canonical/generated asset relationships | `.claude/rules/generated-assets.md` |
| Instruction maintenance | `.claude/rules/documentation.md` |
| Full schemas, key-file tables, execution traces, env-var catalogs | Remove from instruction context; link to source or owned docs |

## Parent/child conflict policy

Because files concatenate, instructions must be additive:

- a parent states only rules true for all descendants;
- a child adds local requirements and does not negate the parent;
- subject differences are explicitly delegated by the parent;
- if exceptions are needed, move the broad rule down to the common ancestor where it is true;
- do not rely on “nearest file wins.”

Example:

- acceptable parent rule: “Verifier strictness is subject-specific; follow the subject package instructions.”
- unacceptable combination: parent says all verifiers are strict while the natural-sciences child says its verifier is lenient.

## Future ownership decision tree

New durable guidance goes to:

1. root, only if it applies across the entire repository;
2. the nearest nested file, if one directory tree owns it;
3. a path-scoped rule, if multiple separate trees must change together;
4. an owned document, if it is explanatory or too detailed for instruction context;
5. a spec or plan, if it is feature-specific, historical, or temporary.

`CLAUDE.local.md` remains uncommitted personal guidance and must not be required for shared project behavior.

## Validation

Add `tests/test_claude_instructions.py` using standard-library parsing where practical. It must verify:

1. The expected root, nested, and rule files exist.
2. All files remain within their approved line budgets.
3. The root contains its required overview, global conventions, common commands, scope map, and `docs/figure-rendering-policy.md` link.
4. Every initial `.claude/rules/*.md` file has frontmatter with a non-empty `paths` list.
5. Repository-relative Markdown links from instruction files resolve.
6. Instruction files do not import large reference documents with `@README.md`, `@FLOW.md`, `@LOGIC.md`, or equivalent relative forms.
7. Catch-all structures do not return, including exhaustive `Key Files`, copied `Execution Logic`, `LLM Calls Summary`, and source references pinned to line numbers.
8. Existing rendering-policy assertions in `tests/test_context_builder_docstrings.py` continue to pass.

The test should not add a production dependency solely to parse this limited documentation format.

## Manual loading verification

After implementation:

1. Start Claude Code at the repository root and run `/context`.
2. Confirm the root instruction is present before reading subsystem files.
3. Read a social-studies source file and confirm `/context` includes root, `src/CLAUDE.md`, `src/social_studies/CLAUDE.md`, and only matching path-scoped rules.
4. Repeat with `server/generate/service.py` and confirm the server scopes load.
5. Confirm unrelated sibling instructions do not load until their files are read.

## Verification commands

```bash
uv run pytest tests/test_claude_instructions.py \
  tests/test_context_builder_docstrings.py
uv run ruff check tests/test_claude_instructions.py
uv run pytest
```

## Rollout and git isolation

The design and implementation use a dedicated branch from `main`:

```text
docs/claude-md-decomposition
```

The unrelated untracked file `docs/superpowers/plans/2026-07-22-generation-progress-bar.md` must remain untouched and excluded from commits.

Phase 1 commits should separate the instruction hierarchy from its contract tests when that improves reviewability, but no production behavior change is allowed.

## Phase 2 documentation cleanup

A separate future spec will audit and canonicalize:

- `README.md`;
- `FLOW.md`;
- `LOGIC.md`;
- `web/README.md`;
- `data/social_studies/csv_填寫指南.md`;
- other duplicated or stale references discovered during that audit.

Phase 2 will assign one explanatory owner per topic and remove duplicated architecture and execution descriptions. Phase 1 must not distribute known-stale copies into the new instruction hierarchy.

## Success criteria

- Root `CLAUDE.md` is reduced from 497 lines to at most 100.
- Focused work loads global, ancestor, local, and matching cross-cutting guidance without eagerly loading sibling guidance.
- No full output schemas, execution waterfalls, or exhaustive file inventories remain in instruction context.
- Parent and child instructions are additive and non-conflicting.
- Every scoped file and rule remains within its budget.
- Focused and full test suites pass.
- No production code, schema, data, or behavior changes.
- The existing progress-bar work and untracked plan remain unchanged.
