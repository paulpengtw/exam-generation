# Batch [#529](https://github.com/paulpengtw/exam-generation/issues/529)–[#536](https://github.com/paulpengtw/exam-generation/issues/536) completion record (2026-08-25)

日期：2026-08-25

**Scope note:** [#529](https://github.com/paulpengtw/exam-generation/issues/529) (parent issue, 自然科學 小題-level image generation missing) was the umbrella; it was NOT labeled ready-for-agent and was left open — its children [#530](https://github.com/paulpengtw/exam-generation/issues/530)/[#531](https://github.com/paulpengtw/exam-generation/issues/531)/[#532](https://github.com/paulpengtw/exam-generation/issues/532) are the deliverables. All work was implemented via the Codex delegation pipeline, one branch + PR per issue, merged to staging sequentially.

## NS 小題-image chain

- [#530](https://github.com/paulpengtw/exam-generation/issues/530) → [PR #568](https://github.com/paulpengtw/exam-generation/pull/568) (merged): NS SubQuestion schema carries `chart_spec`/`image_generation_mode`; 子題產生器 prompts state the 小題 image requirement; parser+corrector read/preserve the fields; `_NS_SPEC` gains `render_subquestion_images_fn`. Red-first seam tests in `tests/test_ns_subq_image_contract.py`. Suite after merge: 1630 passed/1 skipped.
- [#531](https://github.com/paulpengtw/exam-generation/issues/531) → [PR #569](https://github.com/paulpengtw/exam-generation/pull/569) (merged): `_NS_SPEC` gains `ensure_visual_spec_fn` — one repair attempt when a required 小題 `chart_spec` is missing; no repair for 純文字 or mode-only; graceful degradation. `tests/test_ns_subq_chart_spec_repair.py`. Suite: 1634 passed/1 skipped.
- [#532](https://github.com/paulpengtw/exam-generation/issues/532) → [PR #570](https://github.com/paulpengtw/exam-generation/pull/570) (merged): docs record the new reality — figure-rendering policy updated, new ADR 0017 (NS mirrors SS; ADR 0015 figure-kind diversity explicitly out of scope for NS), `CONTEXT.md` glossary + README corrections.

## 重新帶入 chain

- [#533](https://github.com/paulpengtw/exam-generation/issues/533) → [PR #571](https://github.com/paulpengtw/exam-generation/pull/571) (merged): page-level regression coverage for the saved-草稿 dialog reload path (`web/src/pages/GeneratePage.history-prefill.test.tsx`); path found NOT broken.
- [#534](https://github.com/paulpengtw/exam-generation/issues/534) → [PR #574](https://github.com/paulpengtw/exam-generation/pull/574) (merged): coverage for 中斷紀錄 (aborted-run) entries using the real aborted-persistence shape; found and fixed a REAL bug — malformed-prefill cleanup caused an infinite render loop on partial entries (referential-equality guard in `ParamForm.tsx`).
- [#535](https://github.com/paulpengtw/exam-generation/issues/535) → [PR #575](https://github.com/paulpengtw/exam-generation/pull/575) (merged): 重新帶入 now reloads every resolved value pinned; the [#411](https://github.com/paulpengtw/exam-generation/issues/411) restore-to-random behavior retired; `predrawn_fields` provenance still recorded on fresh submissions; complete reloads submit `predrawn_fields "[]"`. Six [#411](https://github.com/paulpengtw/exam-generation/issues/411)-era tests rewritten to pinned semantics. Rebased over the concurrent ICCS 確認頁 work, keeping ICCS domain filtering while retiring `historyPredrawnFields` re-roll.
- [#536](https://github.com/paulpengtw/exam-generation/issues/536) → closed by verification, no PR: no `[DEBUG-rt507]` marker exists in the tree or anywhere in git history (`git log -S` across all branches) — the diagnostic harness was never committed; its assertions are absorbed by [#533](https://github.com/paulpengtw/exam-generation/issues/533)/[#534](https://github.com/paulpengtw/exam-generation/issues/534).

## Environment facts

For future agents:

- Playwright Chromium must be installed (`uv run playwright install chromium`) or render tests leak driver processes and hang.
- `tests/integration/` needs a real postgres and hangs in the bot sandbox; exclude it with `--ignore=tests/integration`.
- Web Vitest needs `--maxWorkers=2` in this sandbox.
- Final states: backend 1634+ passed/1 skipped (non-integration), web 86 files/715 tests green.
