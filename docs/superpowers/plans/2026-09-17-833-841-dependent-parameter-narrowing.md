# Plan: 從屬參數 narrowing, rejection, confirmation edits and form affordances (#833–#841)

Specs: GitHub issues #833–#841, each saved verbatim at
`/tmp/claude-1000/-workspace/d5582b09-840b-4a37-aaea-51044acdf755/scratchpad/specs/<n>.md`.
Design authorities: ADR 0019 (resolve is one pure function; `/generate` and preview
rerun it), ADR 0020 (admission ships as `admitted_by` data; `src/common/admission.py`
is the one lookup, landed in #832), ADR 0021 (editing a parent on 發送前確認 behaves
like 重抽), ADR 0003 (never silently correct). #832 is already on this branch.

Two lanes run concurrently in two worktrees of the same repo:

- **Lane S (server)** — worktree `/workspace/eg-wt/832-admission-lookup`, branch
  `feat/832-admission-lookup`: Tasks 1–5 in order.
- **Lane W (web)** — worktree `/workspace/eg-wt/832-841-web`, branch
  `feat/832-841-web`: Tasks 6–10 in order. Lane W never edits Python or
  `web/src/api/generated/contract.ts`; Lane S never edits `web/src/**` except
  regenerating that contract file.

## Global Constraints

- **The rule (all tickets):** a 釘選 child narrows a parent left blank: the parent is
  drawn only from values that admit every 釘選 child. Admission always comes from the
  `admitted_by` tags on loaded curriculum entries through `src/common/admission.py`
  (server) or `filterEntriesByAdmittedParent` / `admitted_by` on the schema payload
  (web). No prefix tables (`startswith("公")`, `isPublicSocialStudiesCode`) may decide
  admission anywhere touched by these tasks.
- **學習表現 has no 內容領域 parent** (#833). Only 學習內容 codes that carry an
  `admitted_by["內容領域"]` tag constrain 內容領域; 歷/地 codes and all 學習表現 never do.
- **Draws for payloads without 釘選 codes are unchanged**: candidate sets are filtered,
  draw keying (`draw_rng(seed, field_path, redraws)`) and order are not.
- **Error contract:** every resolver error is `{"field", "code", "parent"}` with
  `code ∈ {"unresolved", "incompatible_parent", "no_admitting_parent"}`; fields use the
  resolver's existing addressing (`learning_content`, `learning_performance`,
  `subquestion_configs[j].<field>`, batch prefix `per_question_params[i].`). 科目 is
  evaluated before 內容領域; when 科目 fails, no 內容領域 error for that 題組. One
  error per offending field path; repeated codes never duplicate an error.
- **Contributing field (ruling):** for `no_admitting_parent`, a field path contributes
  when its own pinned codes alone exclude at least one candidate of the parent's
  unnarrowed range (multiple sources: report every contributing path, including
  question-level paths in a mixed-level conflict).
- **Sampler exception (ruling):** `src/social_studies/sampler.py` raises one structured
  `ParentAdmissionError(errors: list[dict])` (a `ValueError`) carrying local field paths;
  `src/common/resolver.py::_resolve_social` converts it to `ResolveConflictError` or,
  when the failing parent's 重抽 counter is > 0, clears the named children and
  resamples (#837). The old `IncompatibleContentDomainError` may become an alias
  subclass or be replaced; the redraw-clearing behaviour for 內容領域 must survive.
- **Tests, Python:** focused files with `choom -n 500 -- uv run pytest <files> -q`
  (never the whole suite; the controller runs it once per lane at the end). Use grade
  7 for 第四學習階段 examples. Seeds 0–199 loops where the spec says "every seed".
- **Tests, web** (Lane W, run from `web/`): focused `npx vitest run <file>`; before
  each commit `npx tsc -b --noEmit` (or `npm run build`'s `tsc -b` if `--noEmit` is
  rejected) and `npm test` once. Lane W has `web/node_modules`; Lane S does not.
- **Commits:** one commit per ticket (Task 2 makes two: #834 then #835). Stage only
  your own files with `git add <path>...`; never `git add -A`, `-a`, or `git stash`.
  Trailer on every commit: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
  Subject line names the issue, e.g. `feat(834): ...`.
- Do not edit `MEMORY.md` unless you hit a gotcha the next session would rediscover.

---

## Task 1: #833 server — 學習表現 is no longer restricted by 內容領域

Spec: `specs/833.md` (server bullets only; the form is Task 6).

In `src/social_studies/sampler.py` delete `_filter_performance_entries_for_domain`
and its call in `_resolve_domain_and_pools` (`filtered_lp` becomes `lp_entries`
unchanged); delete `_is_public_code` and `_DOMAIN_MAPPING` if nothing else in the
module uses them (keep `src/social_studies/domain_mapping.py`: the loader, schema
payload and verifier still read it). Update `tests/test_iccs_sampler_rules.py`:
tests asserting `學習表現_pool ⊆ mapped_codes` change to the unbound expectation, and
add one test that with 科目 公民與社會 and every 內容領域, `公1c-Ⅳ-1` (the only stage-4
公 學習表現 code) is in the drawable 學習表現 pool, plus one resolver-level test in
`tests/test_resolver.py` that a request pinning `learning_performance=["公1c-Ⅳ-1"]`
with 科目 公民與社會 and a 內容領域 resolves with it unchanged. Run
`tests/test_iccs_sampler_rules.py tests/test_resolver.py tests/server/test_generate_resolve.py`.

## Task 2: #834 + #835 server — narrowing and readable rejection

Specs: `specs/834.md`, `specs/835.md` (server and CLI bullets; the web formatting is
Task 7). Two commits: first the narrowing (#834), then the rejections + contract (#835).

Seams: `src/social_studies/sampler.py::sample_params` draws 科目 at
`field_rng("科目").choice(...)` and resolves 內容領域 in `_resolve_domain_and_pools`;
pinned codes arrive as `learning_content` / `learning_performance` (already merged
per question by `resolve`); `_LC_DATA` / `_LP_DATA` are the tagged loaded pools
(tests monkeypatch them, so build any by-code map inside `sample_params`, not at
import). `src/common/resolver.py::_resolve_social` wraps the sampler and maps
`IncompatibleContentDomainError` to `incompatible_parent` today (lines ~585–605).
Routes already turn `ResolveConflictError` into a field-addressed 422
(`server/generate/routes.py:52–70, 160–170`) for `/resolve`, preview and generation.
Contract: `server/generate/models.py:282` Literal, `scripts/generate_ts_contract.py:183`,
`web/src/api/generated/contract.ts`, drift guard `tests/test_ts_contract_drift.py`.
CLI: `src/common/cli_resolver.py` already prints `{"errors": [...]}` and exits 2.

#834 behaviour:
- 科目 candidates = supplied list, or all four when blank. Narrow to candidates that
  admit every pinned 學習內容 and 學習表現 code
  (`admitted_parents_by_code(_LC_DATA, "學習內容", "科目")` and the 學習表現 twin;
  a code absent from both maps is admitted by no candidate). Draw from the narrowed
  list on the unchanged `field_rng("科目")` stream. A single supplied value is a pin:
  it is not narrowed (Task 2's second commit rejects it when it does not admit).
- 內容領域 when the resolved 科目 is 公民與社會/跨科 and 內容領域 is blank: usable
  domains = domains with a non-empty 學習內容 pool that also admit every pinned
  學習內容 code carrying a 內容領域 tag (`admitted_parents(entry, "內容領域") is not
  None`; look entries up by value in the subject's stage pool). Draw on the unchanged
  `field_rng("內容領域")` stream. A supplied 內容領域 keeps today's admitted-codes
  check.
- Structure the pin collection as a list of `(field_path, codes)` pairs so Task 3 can
  append `subquestion_configs[i].<field>` rows without reshaping.

#835 behaviour (server): raise `ParentAdmissionError` per Global Constraints:
- single supplied 科目 that does not admit a pinned code → one
  `incompatible_parent` error per contributing field, `parent` = that 科目 value;
- blank/multi-valued 科目 with an empty narrowed range → `no_admitting_parent`,
  `parent: "科目"`, per contributing field;
- supplied 內容領域 not admitting a tagged pinned 學習內容 code →
  `incompatible_parent`, `parent` = the domain (today's error, now via the new type);
- blank 內容領域 with an empty narrowed range → `no_admitting_parent`,
  `parent: "內容領域"`, `field: "learning_content"`.
`_resolve_social` converts to `ResolveConflictError` (keeping the existing
內容領域-redraw clearing path working: a 內容領域 or 科目 counter > 0 still clears
`learning_content` and resamples exactly as today; Task 4 generalises it). Add
`no_admitting_parent` to the models Literal, the TS generator and regenerate
`web/src/api/generated/contract.ts` so the drift guard passes.

Tests (add to `tests/test_resolver.py`, `tests/server/test_generate_resolve.py`,
`tests/test_iccs_sampler_rules.py`, `tests/test_cli_resolve_first.py`): every
acceptance bullet of #834 and the server/CLI bullets of #835, including: seeds 0–199
for 科目 blank + `公Bn-Ⅳ-3`; `["公民與社會","地理"]` + `公Bj-Ⅳ-1` → 公民與社會;
blank + `公Bn-Ⅳ-3` + `歷Fb-Ⅳ-1` → 跨科; blank + 學習表現 `公1c-Ⅳ-1` → 公民與社會/跨科;
公民與社會 + blank 內容領域 + `公Bn-Ⅳ-3` → `Civic Institutions and Systems` for seeds
0–199; 跨科 + only `歷Fb-Ⅳ-1`,`地Bb-Ⅳ-1` → any domain with a pool; batch rows replace
request-level codes before narrowing; re-resolving each result is identical with empty
`drawn` and `cleared`, and preview + generation accept it (use the existing route
tests' style for the two production reproductions); the four 422 examples of #835
with exact error lists; batch prefixing; both-field contributing errors; no duplicate
errors for repeated codes; the CLI prints `no_admitting_parent` on stderr and exits 2
for the empty-domain payload. Run those files plus `tests/test_ts_contract_drift.py`
and `tests/server/test_generate_routes.py`.

## Task 3: #836 — 各小題配置 codes narrow and are checked like 題組-level codes

Spec: `specs/836.md`. Extend Task 2's pin collection with the `learning_content` /
`learning_performance` of each `subquestion_configs[i]` row for
`i < resolved 小題數` (the resolver always passes `sub_question_count`; when a
standalone caller omits it, use `len(subquestion_configs)`). Errors are addressed to
`subquestion_configs[i].<field>` (batch prefix added by `resolve` as today). Every
contributing path is reported in an empty-intersection conflict, including
question-level paths. Per-小題 學習表現 constrains 科目 only. Tests for every
acceptance bullet (seeds 0–199 where stated) in `tests/test_resolver.py` and
`tests/server/test_generate_resolve.py`; run those plus `tests/test_iccs_sampler_rules.py`.

## Task 4: #837 — editing 科目 or 內容領域 on 發送前確認 clears 釘選 codes that no longer fit

Spec: `specs/837.md`. In `src/common/resolver.py::_resolve_social`, when the sampler
raises `ParentAdmissionError` and the failing parent's 重抽 counter is > 0
(`redraws` keys `科目`/`內容領域`; the request-field aliases `subject_filter` /
`content_domain` must behave identically — check `_local_redraws` /
`_canonical_local_path` and extend `_TOP_LEVEL_ALIASES` if `content_domain` is
missing), clear exactly the children named in the errors — top-level fields set to
`None`, per-小題 rows within the resolved count lose the field — record their
canonical paths in `cleared` (`學習內容`, `學習表現`,
`subquestion_configs[i].learning_content`, batch-prefixed by `resolve`), and resample;
loop until the sampler succeeds (科目 conflicts first, then 內容領域). Without a
counter the conflict is raised as today. Compatible children survive untouched. A
內容領域-only edit never clears 學習表現. Tests for every acceptance bullet in
`tests/test_resolver.py` and `tests/server/test_generate_resolve.py` (including
`per_question_params[0].content_domain` as a redraw key and "result re-resolves
unchanged and generation accepts it"). The last bullet ("in the running app") is
verified by Lane W's tests, not here.

## Task 5: #838 — resolver property test, glossary and ADR

Spec: `specs/838.md`. New `tests/test_resolver_property.py` importing only
`src.common.resolver` and subject schema/curriculum modules (never `server.*` or
fastapi). A `random.Random(<fixed seed>)` generator builds payloads for all three
subjects exactly as the spec lists (count 1–3; blank or valid 科目/內容領域/情境/
情境子類別 per subject; list-valued only where the request contract allows lists —
內容領域 scalar; random 釘選 學習內容/學習表現 at request, question and 小題 level
drawn from the real curriculum pools; random 重抽 counters). For each payload: either
`resolve` succeeds and `resolve(result.payload)` returns an identical payload with
empty `drawn` and `cleared`, or it raises `ResolveConflictError` whose every error
has a code in the known set and a `field` that addresses an input present after the
per-question merge (inherited request-level values addressed through their batch row).
Include the production reproduction (科目 公民與社會 + `公Bn-Ⅳ-3` + blank 內容領域) as
a fixed sanity case. Keep total runtime well under a minute (a few hundred payloads).
Amend `CONTEXT.md` **從屬參數** first paragraph and add
`docs/adr/0031-a-pinned-dependent-child-narrows-its-blank-parents-predraw.md`
(0031 is free) with the spec's text, lightly edited. Run the new file plus
`tests/test_resolver.py`.

---

## Task 6: #833 web — the form no longer restricts 學習表現 by 內容領域

Spec: `specs/833.md` (form bullets). In `web/src/components/ParamForm.tsx` remove the
內容領域 restriction of 學習表現 everywhere: `iccsDomainMappedCodes`, `filteredLpPool`,
`restrictCodesToIccsDomain` for 學習表現 (around lines 2236–2280), the per-小題
學習表現 picker filtering, the submit-time drop, and the 發送前確認 per-小題
`questionLpEntries` domain filtering (around line 3292). 學習內容 filtering stays as it
is (Task 9 changes it). Update/add tests (likely `ParamForm.iccs-compat.test.tsx` and a
per-小題 picker test) covering the three form acceptance bullets, including the
resolve request body carrying the selected 學習表現 unchanged.

## Task 7: #835 web — readable field-addressed errors

Spec: `specs/835.md` (web bullets). Seams: `web/src/api/client.ts::extractError`
discards a non-string `detail` (keep the string path; additionally return the parsed
error array); `web/src/hooks/useGenerate.ts::formatHttpErrorDetail` emits
`Incomplete request: …`; the 發送前確認 resolver banner sets `resolverError` in
`ParamForm.tsx` (~line 2439) from the thrown message; prompt-preview errors follow the
same client path. Build ONE pure formatter module under `web/src/lib/` that takes an
error array and the active language (read from `useLangStore.getState().lang` outside
React) and returns one readable sentence per error using the zh-TW/en-US catalogs in
`web/src/i18n/messages.ts`; `unresolved` and request-validation errors keep their
current text. Position: `per_question_params[i]` → question i+1;
`subquestion_configs[j]` → 小題 j+1. Parent kind (ruling): for `no_admitting_parent`
the parent field is the `parent` value itself (`科目`/`內容領域`); for
`incompatible_parent` infer from the field: `sub_context` → 情境, otherwise 科目 when
the value is one of the four social-studies 科目 values (歷史/地理/公民與社會/跨科),
else 內容領域. Wire the formatter into the resolver banner, the generation error and
preview errors. Tests: formatter unit tests from an error fixture (including
`per_question_params[1].subquestion_configs[0].learning_content` → question 2, 小題 1,
both codes, both languages, 學習表現 labels), `client.test.ts` for array `detail`, and
the existing `useGenerate.test.ts` expectations updated.

## Task 8: #839 — the form disables 科目 and 內容領域 options the 釘選 codes do not allow, with a hint

Spec: `specs/839.md`. Seams: the 科目 control (grep `subjectFilter` select/options),
the 內容領域 select (~line 4220), the schema entries' `admitted_by` (科目 on every
學習內容/學習表現 row; 內容領域 on tagged 學習內容 rows), per-小題 rows
(`subquestion_configs` state). Disabled, never hidden; `全部` and `隨機` stay enabled;
one hint line under the control, associated via `aria-describedby`, naming the
constraining codes with `小題 N:` prefixes for row-sourced codes; zh-TW and en-US
strings. 發送前確認 controls unchanged. Tests for every acceptance bullet in a new
`ParamForm.*.test.tsx` (screen-reader association asserted through the accessible
description).

## Task 9: #840 — 學習內容 codes the chosen or remaining 內容領域 would not accept are disabled, never dropped

Spec: `specs/840.md`. Seams: `filterLearningContentEntriesByDomain` (~line 1152,
which still carries the prefix+map hybrid — replace with `admitted_by` only: a row
without a 內容領域 tag is unscoped), `filteredLcPool` (~2258), the request-level
學習內容 list/search and per-小題 學習內容 pickers, and the submit-time filtering of
學習內容 by 內容領域 (remove it; the resolve request body carries exactly what is
selected). Disabled state with the Task 8 hint pattern; selected codes always
deselectable; 發送前確認 per-小題 controls unchanged. Tests for every acceptance bullet.

## Task 10: #841 — restored drafts and history prefills keep and flag 科目/內容領域 conflicts

Spec: `specs/841.md`. Seams: the restore reconciliation effect (~lines 2160–2215:
`missing`, `dropped`, `poolMatchesGrade`, `history.prefill_dropped_codes`), the
curriculum reconciliation effects that deselect codes outside `availableLearningContent`
/ `availableLearningPerformance` (judge absence against the grade's whole pool — see
`web/src/lib/curriculumPool.ts` — not the 科目-filtered pool), draft restore via
`web/src/lib/formDraft.ts`, the history and Regenerate prefill paths (`initialParams`),
the 產生 button disabled expression (~line 3910) and `confirmInvalidFields`. Mark the
conflicting parent control invalid (`aria-invalid` + the Task 8 hint), keep the codes,
keep 產生 disabled until the conflict clears. Tests for every acceptance bullet
(draft restore, history prefill, Regenerate prefill, whole-pool absence still dropped
and still reported, 發送前確認 科目 edit to 地理 shows 地理-admitted codes). Finish with
`npx tsc -b --noEmit` and the full `npm test`.
