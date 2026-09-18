# Plan: one lookup answers which 科目 and 內容領域 accept a curriculum code (#832)

Spec: https://github.com/paulpengtw/exam-generation/issues/832 (ADR 0020 is the
design authority: 從屬參數 admission ships as `admitted_by` data on each loaded
curriculum entry, read by both 預抽 and validation).

## Global Constraints

- **Behaviour-neutral.** No request resolves, validates or generates differently.
  Existing tests keep their assertions; synthetic fixtures that mock the ICCS map
  may be migrated to equivalent `admitted_by` metadata with the same memberships.
- **Consumers read `admitted_by` on loaded entries only.** The social-studies
  學習內容 內容領域 pool filter (`src/social_studies/sampler.py`) and the
  generation-time 科目/code validation (`server/generate/subjects.py`) must not
  derive admission from code prefixes (`startswith("公")`) or from separately
  built maps (`_DOMAIN_MAPPING.domain_to_codes`, a hand-rolled by-code dict).
  Curriculum loading (`src/common/curriculum_loader.py`,
  `src/social_studies/curriculum_loader.py`) keeps attaching the tags; do not change it.
- **學習表現 內容領域 filtering is out of scope.** It stays exactly as today
  (prefix + `_DOMAIN_MAPPING`) and is removed by #833. Isolate it in its own
  clearly named function so #833 can delete it.
- **Shared lookup lives at `src/common/admission.py`** with exactly this API:

  ```python
  def admitted_parents(entry: Mapping[str, Any], parent: str) -> list[str] | None
      # The parent values whose tag admits *entry*; None when *parent* does not
      # govern the row (no such key under entry["admitted_by"]).
      # A tag that is present but not a list returns [] (never admitted).
  def admits(entry: Mapping[str, Any], parent: str, value: str) -> bool
      # True when admitted_parents(...) is None (row unscoped by that parent)
      # or contains value.
  def entries_admitted_by(entries: Iterable[Mapping[str, Any]], parent: str, value: str) -> list[dict]
      # [e for e in entries if admits(e, parent, value)], preserving order and identity.
  def admitted_parents_by_code(data: Mapping[str, Any], key: str, parent: str) -> dict[str, list[str]]
      # Over data.get(key, []): skip rows that are not dicts or whose "value" is
      # not a str; read entry.get("admitted_by", {}).get(parent); skip rows where
      # that is not a list; union the str members per code preserving first-seen
      # order and without duplicates. Codes with no tagged row are absent.
      # (This mirrors server/generate/subjects.py::_curriculum_admitted_subjects_by_code today.)
  ```

  Untagged rule (ruling): a row with no `parent` key is unscoped by that parent
  and admitted. On shipped data every 第四學習階段 公 學習內容 row carries a
  內容領域 tag and no 歷/地/shared row does, so this equals today's prefix rule.
- **Tests.** Run focused files with `choom -n 500 -- uv run pytest <files> -q`.
  Do not run the whole suite (the controller runs it once at the end; at most
  2–3 pytest lanes may run concurrently in this checkout).
- **Commits.** Other implementers may be committing in this worktree at the same
  time. Stage only your own files with `git add <path>...` (never `git add -A`
  or `git commit -a`), retry once if `.git/index.lock` exists, and never use
  `git stash`. End every commit message with
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Use grade 7 for any named 第四學習階段 curriculum example.

## Task 1: shared admission lookup module (TDD)

Create `src/common/admission.py` implementing the API in Global Constraints
verbatim, with a module docstring citing ADR 0020 ("answer which parent values
admit a loaded curriculum entry; reads the admitting-parent data attached at load").
Pure functions, no I/O, no imports beyond typing/collections.

Create `tests/test_common_admission.py` (TDD: write failing tests first, then
implement). Cover with synthetic entries:
- `admitted_parents`: tagged list → that list; missing key → None; present
  non-list (e.g. a str) → `[]`; missing `admitted_by` altogether → None.
- `admits`: member → True; non-member → False; unscoped (no key) → True;
  non-list tag → False.
- `entries_admitted_by`: keeps order and returns the same dict objects; mixed
  tagged/untagged rows.
- `admitted_parents_by_code`: unions across duplicate codes (e.g. the same code
  at two 學習階段 with different 科目 tags) preserving first-seen order and
  dropping duplicates and non-str members; skips non-dict rows, rows without a
  str `value`, and rows whose tag is not a list; missing `key` → `{}`.
- One real-data check: load `src.social_studies.curriculum_loader.load_learning_content()`
  and assert `admits(row, "內容領域", "Civic Roles and Identities")` for the
  `公Aa-Ⅳ-1` row, `admits(row, "科目", "地理")` is False for it, and that a
  `歷Ka-Ⅳ-1` row is admitted by any 內容領域 (unscoped) but only by
  科目 歷史/跨科 (`admitted_parents(row, "科目") == ["歷史", "跨科"]`).

## Task 2: sampler 學習內容 domain pool filter reads the shared lookup

In `src/social_studies/sampler.py`:
- Import `entries_admitted_by` from `src.common.admission`.
- Replace `_filter_entries_for_domain`'s 學習內容 path: when
  `subject.value in _DOMAIN_FILTER_SUBJECTS`, return
  `entries_admitted_by(entries, "內容領域", domain.value)`; otherwise return
  `entries` unchanged. No `_is_public_code`, no `_DOMAIN_MAPPING` on this path.
  Remove the `use_admitted_domains` flag.
- Move the 學習表現 behaviour into its own function
  `_filter_performance_entries_for_domain(entries, domain, subject)` that keeps
  today's rule verbatim (subject gate; keep rows that are not 公-prefixed or
  whose value is in `_DOMAIN_MAPPING.domain_to_codes[domain]`), with a comment
  that #833 removes it. `_DOMAIN_MAPPING` and `_is_public_code` remain only for it.
- `_resolve_domain_and_pools` calls the 學習內容 filter for `usable_domains`
  and `filtered_lc`, and the 學習表現 filter for `filtered_lp`. Everything
  else (draw order, RNG streams, `IncompatibleContentDomainError` checks) is
  untouched.

Migrate `tests/test_iccs_sampler_rules.py`: tests that monkeypatch
`sampler._DOMAIN_MAPPING` to steer the 學習內容 pool must instead give the
`_LC_DATA` fixture rows `"admitted_by": {"科目": [...], "內容領域": [...]}` with
the same memberships, keeping every assertion. Where a test also asserts on the
學習表現 pool, keep the `_DOMAIN_MAPPING` monkeypatch for that (the 學習表現
filter still reads it). Do not delete any test; do not weaken an assertion.
Then run these files and fix any fixture that relied on the prefix fallback:
`tests/test_iccs_sampler_rules.py tests/test_resolver.py
tests/test_social_studies_sampler_learning_stage.py tests/server/test_generate_resolve.py
tests/server/test_iccs_pin_params.py tests/test_cli_resolve_first.py`.

## Task 3: generation-time 科目/code validation reads the shared lookup

In `server/generate/subjects.py`:
- Delete `_curriculum_admitted_subjects_by_code`.
- In `_validate_curriculum_subject_pairs`, build `admissions` with
  `admitted_parents_by_code(load_content(), "學習內容", "科目")` and
  `admitted_parents_by_code(load_performance(), "學習表現", "科目")` from
  `src.common.admission`. The error message, iteration order over
  `params`/`subquestion_configs`, and every call site stay unchanged.

Add `tests/server/test_generation_subject_admission.py` exercising
`_validate_curriculum_subject_pairs` directly with synthetic loaders whose rows
carry `admitted_by` (no prefix logic anywhere in the test):
- a 科目 that admits every request-level and per-小題 code passes;
- a code the 科目 does not admit raises `ValueError` matching
  `does not admit learning_content code`; same for `learning_performance`;
- an unknown code (no tagged row) is rejected; a code tagged at two 學習階段
  with different 科目 lists is accepted for either 科目;
- multi-valued `subject_filter` passes when any listed 科目 admits the code;
- empty/None `subject_filter` returns without loading (assert the loaders
  are not called);
- one real-data path: with the real social-studies loaders, 科目 `["地理"]` +
  `learning_content=["公Bj-Ⅳ-1"]` raises, and 科目 `["公民與社會"]` +
  `learning_content=["公Bj-Ⅳ-1"]` passes.
Build the `params` argument with `types.SimpleNamespace`. Run
`tests/server/test_generation_subject_admission.py` and
`tests/server/test_generate_routes.py` (or the nearest generate-route test file
that exists) to confirm nothing else changed.

## Task 4: documentation

- `AGENTS.md`: add a Key Files row for `src/common/admission.py` ("Shared
  admission lookup over `admitted_by` tags (ADR 0020): answers which 科目 /
  內容領域 admit a loaded curriculum row; read by the social-studies 學習內容
  內容領域 pool filter and by generation-time 科目/code validation"). Update the
  `src/social_studies/domain_mapping.py` row to say the CSV is read by the
  curriculum loader to attach `admitted_by["內容領域"]` tags, by the schema
  payload, by the verifier, and (until #833) by the sampler's 學習表現 domain
  filter — the 學習內容 pool no longer reads it directly. In the paragraph that
  begins "Social-studies 學習內容 rows for 公民與社會/跨科 additionally carry",
  add one sentence: 預抽 pool filtering and generation-time validation both read
  those tags through `src/common/admission.py`, never from prefixes or a
  separate map.
- `docs/adr/0020-dependent-parameter-rules-ship-as-data-in-the-schema-payload.md`:
  append a short "Status" line: "Implemented server-side by
  `src/common/admission.py` (#832), the single lookup both 預抽 and
  generation-time validation read."
Keep every other line untouched. No code changes in this task.
