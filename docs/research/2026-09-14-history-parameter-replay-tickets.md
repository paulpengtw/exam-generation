# Research — Generation history parameter persistence and exact reload

**Date:** 2026-09-14

**Repository:** `paulpengtw/exam-generation`

**Code baseline:** `staging` at [`bc4932a4c1117b289a6b74046ae468fdb278f72d`](https://github.com/paulpengtw/exam-generation/commit/bc4932a4c1117b289a6b74046ae468fdb278f72d)

**Question:** Do existing tickets cover saving every randomly resolved question-set parameter in Generation history and letting a supervisor reload the same parameters?

**Search basis:** GitHub `gh issue list --state all` searches for `history`, `重新帶入`, `reload`, `predrawn`, `params_json`, `per_question_params`, `隨機`, `預抽`, `resolver`, `seed`, and `replay`, followed by issue-comment and linked-PR reads for the strongest matches.

**Validation scope:** Read-only GitHub status checks and source/test inspection. No application replay, test suite, or deployment verification was run for this research note.

## Finding

Yes. The requested behavior is already covered by a completed ticket chain. The direct current-semantics ticket is [#535](https://github.com/paulpengtw/exam-generation/issues/535), implemented by [PR #575](https://github.com/paulpengtw/exam-generation/pull/575): reloading a history entry keeps **every resolved value pinned**, including values that were randomly drawn in the original run, and resubmits them without a fresh draw. There is no open ticket found that asks for this same parameter-save-and-reload behavior.

The main feature is complete on `staging`; the open [#734](https://github.com/paulpengtw/exam-generation/issues/734) map and [#737](https://github.com/paulpengtw/exam-generation/issues/737) ticket concern reconnecting to an in-progress or disconnected batch, which is a separate work-recovery problem. Open [#751](https://github.com/paulpengtw/exam-generation/issues/751) concerns immutable JSON download snapshots, not parameter replay.

## Ticket chain

| Ticket | What it covers | Status / implementation |
|---|---|---|
| [#30](https://github.com/paulpengtw/exam-generation/issues/30) | Original Generation history feature: `generation_records`, full `params_json`, history list/detail/download, and a regenerate entry point. | Closed by [PR #137](https://github.com/paulpengtw/exam-generation/pull/137), merged 2026-07-17. |
| [#184](https://github.com/paulpengtw/exam-generation/issues/184) | Batch requests carry one independently resolved parameter set per question through `per_question_params`; no backend re-sampling of supplied values. | Closed by [PR #195](https://github.com/paulpengtw/exam-generation/pull/195), merged 2026-07-28. |
| [#185](https://github.com/paulpengtw/exam-generation/issues/185) | Per-question seed is fixed before submission so the same confirmed payload replays seeded draws and prompt few-shot selection. | Closed by [PR #195](https://github.com/paulpengtw/exam-generation/pull/195), merged 2026-07-28. |
| [#408](https://github.com/paulpengtw/exam-generation/issues/408) | Persists random-draw provenance (`predrawn_fields`) in saved request parameters for successful and interrupted runs. | Closed by [PR #473](https://github.com/paulpengtw/exam-generation/pull/473), merged 2026-08-23. It was groundwork for reload behavior, not the final reload policy. |
| [#410](https://github.com/paulpengtw/exam-generation/issues/410) | Adds 重新帶入 for successful and 中斷紀錄 entries, restoring all three subjects, per-小題 rows, word limits, pools, and resolved values as pins. | Closed by [PR #509](https://github.com/paulpengtw/exam-generation/pull/509), merged 2026-08-23. |
| [#411](https://github.com/paulpengtw/exam-generation/issues/411) | Earlier policy: use `predrawn_fields` to return originally random fields to 隨機 and draw fresh values on reload. | Closed by [PR #510](https://github.com/paulpengtw/exam-generation/pull/510), merged 2026-08-23, then superseded by #535. |
| [#535](https://github.com/paulpengtw/exam-generation/issues/535) | Current policy: reload every resolved value, including originally random values, as a user-pinned value; no fresh draw; works for all subjects and per-小題 configuration. | Closed by [PR #575](https://github.com/paulpengtw/exam-generation/pull/575), merged 2026-08-25. |
| [#601](https://github.com/paulpengtw/exam-generation/issues/601) | Makes each sampler draw deterministic by `(seed, field path, 重抽 counter)`, so changing or redrawing one field does not perturb siblings. | Closed by [PR #611](https://github.com/paulpengtw/exam-generation/pull/611), merged 2026-08-26. |
| [#602](https://github.com/paulpengtw/exam-generation/issues/602) | Adds the pure `/api/generate/resolve` contract: pins stay unchanged, blanks are completed, and resolving a completed payload returns the same payload with no draws. | Closed by [PR #614](https://github.com/paulpengtw/exam-generation/pull/614), merged 2026-08-26. |
| [#604](https://github.com/paulpengtw/exam-generation/issues/604), [#608](https://github.com/paulpengtw/exam-generation/issues/608) | Moves confirmation draws to the resolver, carries `drawn` in the submitted payload, and gates generation against any unresolved field. | Closed by [PR #621](https://github.com/paulpengtw/exam-generation/pull/621) and [PR #625](https://github.com/paulpengtw/exam-generation/pull/625), merged 2026-08-26. |
| [#533](https://github.com/paulpengtw/exam-generation/issues/533), [#534](https://github.com/paulpengtw/exam-generation/issues/534) | Regression coverage for reload through the draft-choice route and for complete/partial 中斷紀錄 entries. | Closed by [PR #571](https://github.com/paulpengtw/exam-generation/pull/571) and [PR #574](https://github.com/paulpengtw/exam-generation/pull/574), merged 2026-08-24/25. #534 also fixed an infinite render loop for malformed partial prefills. |
| [#507](https://github.com/paulpengtw/exam-generation/issues/507) | Era-tolerant reload across the social-studies PISA → ICCS schema change, with visible notices for retired keys and restoration of new pins. | Closed; its issue records the completed implementation and era-drift behavior. |
| [#638](https://github.com/paulpengtw/exam-generation/issues/638) | Fixes live per-小題 edits being discarded when a form was prefilled from history; current editor state overlays the stored baseline at submission. | Closed by [PR #656](https://github.com/paulpengtw/exam-generation/pull/656), merged 2026-09-09. |

The design decisions behind this chain are recorded in [ADR 0019](https://github.com/paulpengtw/exam-generation/blob/bc4932a4c1117b289a6b74046ae468fdb278f72d/docs/adr/0019-the-resolve-step-is-one-pure-function.md) and [ADR 0022](https://github.com/paulpengtw/exam-generation/blob/bc4932a4c1117b289a6b74046ae468fdb278f72d/docs/adr/0022-full-predraw-is-enforced-by-three-guards.md). ADR 0019 explicitly says resolution is deterministic and replayable from stored parameters; ADR 0022 makes the `/generate` completeness gate, resolver-only sampler calls, and forwarding classification enforce that contract.

## Current code evidence

At the stated baseline:

- Successful history persistence stores the whole request model as `params_json` via `params.model_dump(mode="json")` in [`server/generate/persistence.py:228-265`](https://github.com/paulpengtw/exam-generation/blob/bc4932a4c1117b289a6b74046ae468fdb278f72d/server/generate/persistence.py#L228-L265). The failed and aborted tombstone paths do the same at [`server/generate/persistence.py:277-355`](https://github.com/paulpengtw/exam-generation/blob/bc4932a4c1117b289a6b74046ae468fdb278f72d/server/generate/persistence.py#L277-L355).
- The history detail API returns `params_json`, and the completed-history download includes it, in [`server/history/routes.py:204-252`](https://github.com/paulpengtw/exam-generation/blob/bc4932a4c1117b289a6b74046ae468fdb278f72d/server/history/routes.py#L204-L252).
- The History detail page passes those saved parameters to the generate form as `prefillParams` in [`web/src/pages/HistoryDetail.tsx:72-76`](https://github.com/paulpengtw/exam-generation/blob/bc4932a4c1117b289a6b74046ae468fdb278f72d/web/src/pages/HistoryDetail.tsx#L72-L76); the UI label is “Reload saved parameters” in [`web/src/i18n/messages.ts:92-101`](https://github.com/paulpengtw/exam-generation/blob/bc4932a4c1117b289a6b74046ae468fdb278f72d/web/src/i18n/messages.ts#L92-L101).
- The form preserves saved `per_question_params`, carries saved `drawn` paths, and resubmits the reconstructed payload through the resolver in [`web/src/components/ParamForm.tsx:2363-2486`](https://github.com/paulpengtw/exam-generation/blob/bc4932a4c1117b289a6b74046ae468fdb278f72d/web/src/components/ParamForm.tsx#L2363-L2486). Current regression tests cover math resolved rows, social-studies rows, and natural-sciences pools/slots in [`web/src/components/ParamForm.history-prefill.test.tsx`](https://github.com/paulpengtw/exam-generation/blob/bc4932a4c1117b289a6b74046ae468fdb278f72d/web/src/components/ParamForm.history-prefill.test.tsx).

One implementation detail matters for batches: [`server/generate/service.py:582-598`](https://github.com/paulpengtw/exam-generation/blob/bc4932a4c1117b289a6b74046ae468fdb278f72d/server/generate/service.py#L582-L598) persists one History row per successful question while passing the request-level `params` object, so each row stores the batch envelope, including `per_question_params`; the saved row is not reduced to only the generated question's indexed parameter object. The form's reload path above preserves those per-question rows when their count matches the submitted batch count.

Exact restoration also depends on the saved values remaining valid in the current schema: [`ParamForm.tsx:1977-2049`](https://github.com/paulpengtw/exam-generation/blob/bc4932a4c1117b289a6b74046ae468fdb278f72d/web/src/components/ParamForm.tsx#L1977-L2049) clears unavailable settings and displays a notice.

## Limits and remaining distinctions

“Same parameters” is covered; “same generated question text” is not promised. [#600](https://github.com/paulpengtw/exam-generation/issues/600) resolves missing fields in old records silently from their stored seed rather than backfilling history, and explicitly records that reload/regenerate is not expected to reproduce the original LLM item. The current ADR contract guarantees the resolved request payload; LLM generation itself remains a new generation.

The full-predraw contract has one deliberate exception: seeded 參考範例 selection is prompt input rather than a request parameter. The exception and its seed determinism are recorded in [#586](https://github.com/paulpengtw/exam-generation/issues/586) and ADR 0018; the selected examples are now disclosed after generation through the separate 參考範例紀錄 work ([#664](https://github.com/paulpengtw/exam-generation/issues/664), [#670](https://github.com/paulpengtw/exam-generation/issues/670)), rather than being part of the reloadable parameter set.

## Answer for the requested feature

There is no new feature ticket needed for the exact request. Use [#535](https://github.com/paulpengtw/exam-generation/issues/535) as the authoritative ticket for the final reload semantics, with [#30](https://github.com/paulpengtw/exam-generation/issues/30), [#184](https://github.com/paulpengtw/exam-generation/issues/184), [#185](https://github.com/paulpengtw/exam-generation/issues/185), and the #587–#608 full-predraw chain as its persistence, batch, determinism, and completeness foundations. If the desired scope expands to reconnecting to a still-running or disconnected batch, start from open [#734](https://github.com/paulpengtw/exam-generation/issues/734) and [#737](https://github.com/paulpengtw/exam-generation/issues/737), rather than reopening the completed parameter-reload work.
