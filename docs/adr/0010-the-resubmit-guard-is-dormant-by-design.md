# the resubmit guard is dormant by design

The 生成頁面 keeps both submit affordances — the 產生 button and the 發送前確認 send button — disabled for the whole time a generation is streaming, via the single `disabled={status === "generating"}` prop passed to `ParamForm`. Issue #220 shipped a 破壞性操作確認 on the submit path (`handleSubmit` in `GeneratePage.tsx`): starting a new generation while one is running asks for confirmation first, because the new run aborts the old one and discards the questions it has already produced. Because the buttons are disabled, that guard is unreachable from the UI. Issue #270 asked whether this state of affairs is intentional; we decided that it is. Re-submitting mid-run stays impossible, and the guard stays in place as belt-and-braces against any future change that re-enables mid-run submission. Do not remove it as dead code.

## Considered Options

Re-enabling the buttons during a run — making interruption a real one-click action behind the existing confirm dialog — was rejected. A running generation represents minutes of LLM work, and the faster retry it would buy is already available today through a sanctioned two-step path: the 清除 button interrupts the running job (its confirm dialog explicitly warns 「正在進行中的產生作業將會被中斷」) and the form can then be re-submitted. Adding a second, one-click path to the same destructive outcome would trade little convenience for a larger accidental-interruption surface, and would also force a redesign of the 產生 button's running state, which currently doubles as the progress indicator (spinner + 「產生中」).

Deleting the dormant guard instead of documenting it was rejected because the guard is the only thing standing between a future "re-enable the buttons" change and silently aborting a run with no confirmation. Its cost is a few lines; its absence would turn a one-line prop change into a data-loss bug.

## Consequences

Both submit affordances must stay consistent with each other: they are driven by the one `disabled` prop on `ParamForm`, and any future change must keep them tied to a single source of truth rather than diverging. The guard is covered by `GeneratePage.resubmit-guard.test.tsx`, which mocks `ParamForm` and drives the captured `onSubmit` callback directly — testing at the handler level is deliberate, since no real control can reach the guard while it is dormant. If a future change re-enables mid-run submission, that test must be rewritten to exercise the actual control, and this ADR is superseded.
