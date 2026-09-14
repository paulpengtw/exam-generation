# #786: 重新帶入 curriculum integration verification

Verified on 2026-09-14 against integrated commit
`6c3ce98b5c18beb9b10191fb1ac970b1d6afc591` and the real staging UI at
`https://examgen-staging.cpeng.me` (frontend asset `index-uzHH95Bq.js`).

The five fixes for [#780](https://github.com/paulpengtw/exam-generation/issues/780)
were already merged to staging. This records the final acceptance work for
[#786](https://github.com/paulpengtw/exam-generation/issues/786); it adds no
application behavior changes.

## Confirmed cause and integrated fixes

The original form mounted two overlapping schema requests: one without a grade,
whose curriculum pool defaults to 第四學習階段, and one for the saved high-school
grade. Reconciliation pruned selected codes against whichever response was live.
The grade-less response could either erase selections before the correct pool
arrived, or replace the correct pool after it arrived.

The [live pool comparison](backend-pools.json) confirms the relevant distinction:
the default pool has 20 學習表現 / 204 學習內容 entries; grade 11 has 39 / 426.
They share **zero 學習表現 codes**. The saved `pa-Ⅴa-1` and `PKa-Ⅴa-1` are admitted
only by the grade-11 pool. The response's `學習階段` metadata label remains
`第四學習階段` even for grade 11; verification therefore checks actual code pools
and the requested grade, not that schema-wide label.

| Issue | Integrated PR | Behavior |
| --- | --- | --- |
| #781 | [#798](https://github.com/paulpengtw/exam-generation/pull/798) | Tag each curriculum pool with its requested grade. |
| #782 | [#810](https://github.com/paulpengtw/exam-generation/pull/810) | Request the saved grade on mount; reconcile only a matching pool. |
| #783 | [#804](https://github.com/paulpengtw/exam-generation/pull/804) | A late grade-less response cannot replace a newer grade pool. |
| #784 | [#807](https://github.com/paulpengtw/exam-generation/pull/807) | Re-check the current grade when queued reconciliation applies after 草稿 restore. |
| #785 | [#808](https://github.com/paulpengtw/exam-generation/pull/808) | Name genuinely dropped codes in the prefill notice. |

## Diagnostic loop: red and green

The agreed seam was the form's public UI and submitted parameters, with schema
response ordering controlled at the external API boundary. Existing tests already
cover it, so this acceptance change does not add duplicate tests.

The two original research links in #780 reference the deleted
`fix/585-origin-through-greenlet` branch and returned HTTP 404. This note preserves
the same three-case experiment using the committed
`GeneratePage.history-prefill.test.tsx` cases.

| Case | Pre-fix ParamForm (`e6805dd`) | Integrated ParamForm |
| --- | --- | --- |
| Control: both requests return 第五 pool | PASS | PASS |
| Grade-less 第四 response first | FAIL: selected codes become `[]` | PASS |
| Grade-less 第四 response last | FAIL: selected codes become `[]` | PASS |

The integrated history path no longer requests a grade-less pool. The two mock
orderings therefore also assert that no such request is made. The actual
late-response handling on subject switch is separately covered by the existing
`ParamForm.ns-grade-pool.test.tsx` case. The existing grade-11 draft suite covers
both orderings and the queued-reconciliation race from #784.

Run the replay after installing web dependencies:

```sh
npm --prefix web ci
python3 docs/research/2026-09-14-786-curriculum-reload/replay-diagnostic.py
```

The script uses a disposable copy for the pre-fix implementation and leaves the
checkout untouched. It requires the baseline Git commit to be available. It
checks the expected failures and control pass, then checks all three integrated
passes. See [results](diagnostic-results.json), [red log](race-red.log), and
[green log](race-green.log).

## Real browser acceptance

The user confirmed the test seam and supplied a staging login link after the
explicit ego-browser/environment request required by #786. Verification used
ego-browser with real staging responses; no responses were mocked or delayed.
Credentials and authorization headers are not included in these artifacts.

1. Inspect the authenticated natural-sciences history list: 13 records, all
   completed; no failed natural-sciences record was available. Select the real
   grade-11 record `f44343c7-2207-43e4-b50c-a4ea04fc8b82`.
2. Click **重新帶入**. The 全域池 and all three 各小題配置 retain the saved
   `pa-Ⅴa-1` / `PKa-Ⅴa-1` selections. Both mount requests include `grade=11`.
   See [saved pins](saved-history-pins.json) and [observed selectors](reload-observed.json).
3. Open both curriculum pickers. Each offers 第五學習階段 codes, with no 第四 code
   among the displayed results. See [picker choices](reload-picker-options.json).
4. Open **發送前確認**. The real resolve endpoint returns HTTP 200 and preserves
   all request-level and per-小題 pins. This older record also has distinct saved
   `per_question_params` overrides (`PBa-Ⅴa-1`, `pa-Ⅴc-1`, `ai-Ⅴa-1`); those remain
   authoritative in confirmation and are also preserved unchanged. See
   [saved overrides, request, and response](confirmation-pins.json).
5. Return to the form. Edit 文本出題指示 to create a real grade-11 草稿 through the
   normal autosave. Open a fresh tab at `/generate/natural_sciences`; the form
   starts at grade 7 and shows the saved draft. Click **還原草稿**. Grade 11,
   全域池, all three 小題 selections, and the edited text are restored. The
   observed request sequence is grade-less → grade 7 → grade 11. See
   [saved draft](saved-draft-pins.json), [restored selectors](draft-observed.json),
   and [restored picker choices](draft-picker-options.json).
6. Remove the test-created draft, restoring its original absence, and close both
   agent browser tabs. See [browser summary and cleanup](browser-summary.json).

The browser check stopped at confirmation; it did not submit an LLM generation.
The timing permutations are verified by the deterministic UI tests above, while
the browser run verifies actual history navigation, schema data, and draft restore.

## Integrated checks

- `npm run lint`: exit 0.
- `npx tsc -b`: exit 0.
- `npm test -- --maxWorkers=2`: **107 files / 884 tests passed**, exit 0.
- Diagnostic replay: expected pre-fix failures, integrated three cases passed.

See [verification log](verification.log). Node was `v25.6.1`, npm `11.16.0`.
`choom` is unavailable on this macOS host; the full suite was limited to two workers.
