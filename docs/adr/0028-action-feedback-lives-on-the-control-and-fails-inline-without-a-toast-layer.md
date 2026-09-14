# 操作回饋 lives on the control and fails inline, with no toast layer

Until wayfinder map #720 the web app acknowledged very few of its actions. The charting audit on `origin/staging` at `ad3318f` found every download button (six) giving no feedback at all, three of them doing async work with no `.catch` (per-card ODT, batch ODT, history JSON); 產生 greying out during the resolve round-trip with its spinner gated on the wrong flag; 確定發送 never changing when pressed although it starts a run measured at 279 s; 重抽 staying clickable mid-request with a same-value redraw indistinguishable from nothing happening; and history paging leaving the old page on screen with no in-flight indicator. Two controls (傳送登入連結, 產生核心問題候選) already did the right thing — disabled, spinner, label swap, success line, `role="alert"` error — so the app had the pattern but not the rule. The problem statement was *the current design is lacking feedback to the user; they are not sure with some buttons whether it actually got ready or not.*

This ADR records the decisions of #723 (state model), #724 (where outcomes render) and #726 (labels on the AI-working surfaces), as amended by the maintainer's review of the #727 prototype. The glossary entry is **操作回饋** in `CONTEXT.md`; the motion these states move with is ADR 0029.

## The model

**Four states: 待命, 處理中, 已完成, 失敗.** These names are the vocabulary of the model, the code and the tests. On-screen labels stay verb-specific (產生中…, 下載中…, 已下載, 重抽中…, 載入中…), as the two reference controls already do.

**Runs are 處理中 naming the 生成步驟 under way.** A generation run reads 產生中 (from the click until the first server event — the hand-off window) → 文本生成中 → 子題生成中 (k/n in a batch) → 圖片生成中 → 審題中 → 改題中 → 已完成 | 失敗. A 人工審題修正 run reads 修改中 → 審題中 → 改題中. **審題中 and 改題中 are the on-screen labels for the 驗證 and 修正 生成步驟**, and the breadcrumb's resting nouns are 審題 and 改題; they were chosen because they are the teacher's words. The model, the tests, ADR 0016 and this document keep 驗證 / 修正. The English locale keeps Generating / Verify / Correct — the rename is a zh idiom. `statusbar.running` changes from 生成中 to 產生中 so the bar, the console and the model agree. The tickets call the run's sub-state a "phase"; the glossary keeps avoiding that word for 生成步驟, so read "phase" in #723–#727 as *the 生成步驟 under way*.

**Invariants.**
- Every 處理中 terminates in 已完成 or 失敗. No `.catch` swallows an error; network calls carry a timeout.
- A control in 處理中 is not re-enterable. Unrelated controls stay independent. ADR 0010 stands: the submit affordances stay disabled for the whole run; 操作回饋 changes how a disabled control looks, never whether it is disabled.
- Class-4 local toggles (show answer / solution / 誘答分析, trails, 參考範例紀錄, disclosures, language switch) never enter the model. Their content change is the acknowledgement; they get motion under ADR 0029 only.

## Where the states render

**處理中 and 已完成 render on the control** — label, icon, colour — with `role="status"` on the state text. **失敗 renders as an inline notice directly below the control's row**: full width of the control's container, styled like the app's existing red `role="alert"` blocks, holding a short state label, one line of reason (the server's `ApiError.detail` when present, otherwise a generic action-specific line such as 無法產生 ODT 檔案) and 重試 on every idempotent action — all exports, 重抽, 提示詞預覽, history paging and the 產生→resolve round-trip. The notice stays until dismissed with ×, until a retry succeeds, or until the control is pressed again; it does not clear on an unrelated interaction. **A failed control keeps its label** and carries the failure in colour plus a `!` icon; only the control that was pressed is marked. (The prototype replaced the label with 失敗, and the review found both history pager buttons reading identically 失敗 — including the one never pressed.)

**There is no global toast or notification layer.** sonner and any equivalent stay out; the #721 spike's `sonner.tsx` is not promoted.

**Per class.**
- *Stream starters* (確定發送, 提交修改, and 產生核心問題候選 for as long as its call lasts): today's immediate teardown stays. The acknowledgement is the animated hand-off that carries attention from the pressed control to the 生成進度列 (ADR 0029). The control's 處理中 ends at the first server event; the run's 已完成 / 失敗 is narrated by the run surface, never by the control, and the control offers no retry. Because the control never narrates completion, the dead `card.modificationSubmitted` string (修改已提交。, defined in both locales, rendered nowhere) is removed rather than wired up.
- *Fire-and-forget exports* (JSON / PNG / ODT per card, batch, history): 處理中 on the control, then **已完成 persists until the next press of any control or a route change**. Export 已完成 is the label 已下載 with a check and a green tint, plus the produced file's name attached to the pressed control (the review chose prototype variant A and carried the filename over from variant B, anchored to the button rather than the row, because the results row holds three download buttons and a row-level line does not say which produced the file). Pressing a control that shows 已完成 starts a fresh 處理中. A batch ODT in which one 題組 fails reports **once**, names that 題組, and produces **no file**.
- *重抽*: the row's value dims and the button reads 重抽中… and is disabled during 處理中. On return the row flashes once whether or not the value changed; when it is identical a short hint says 重抽結果與原值相同. On failure **the previous value stays in place** — the prototype rendered the literal string `null`, which was the review's most serious finding — the row's button is marked 失敗 with its label intact, and pressing it again is the retry. The screen-level resolver banner with 重新解析 stays as the resolver's own state; there is no second row-level notice.
- *Lists* (history paging): stale rows stay visible, dimmed, with `aria-busy`; the pressed pager button enters 處理中 (載入中…). Layout stays stable; no skeleton.

## Accessibility and replay

`role="status"` on the control for 處理中 and 已完成; `role="alert"` on the notice (C7 of the map). State labels are fixed i18n strings and are `sentry-unmask`ed as static chrome, matching the 生成進度列 today; the reason line and anything derived from a question stay masked, fail-closed (ADR 0004 / 0005). No portal-mounted element is introduced, so no new masking surface exists.

## One primitive, and how far shadcn goes

One app-owned 操作回饋 primitive — a hook wrapping the async action (state, reason, retry, reset, no re-entry, done-clearing) and a control built on the shadcn `Button` — replaces the six hand-rolled spinners in four shapes and is applied to every control in the #720 audit. shadcn adoption stops there: `init` for the theme plumbing and `Button` under this primitive. The existing hand-rolled buttons, `DestructiveConfirm` and the pickers are not migrated wholesale; they receive motion tokens only. The inline notice extends the existing `role="alert"` pattern rather than adding a component-library layer for notices.

## Considered Options

**A global toast layer (sonner).** Rejected. A toast detaches the outcome from the control the user pressed, which is the uncertainty this map exists to remove; the app already had eleven inline `role="alert"` blocks directly below the failing control, so inline is the established pattern; a second announcement channel next to the 生成進度列 would compete with it; and a portal-mounted layer is a new replay-masking surface.

**Replacing the label with 失敗.** Rejected after the review: the control loses its identity, and unmarked siblings can be misattributed.

**A skeleton for history paging.** Rejected: it shifts layout; dimmed stale rows with `aria-busy` keep the page stable and still say something is in flight.

**Clearing 已完成 on any pointer or keyboard interaction.** This was #723's rule and the prototype bound it to document-level `pointerdown` and `keydown`; the review found the confirmation gone on the next click anywhere, often before the reviewer looked back. Narrowed at closing to the next press of any control or a route change; clicks on inert surface, focus moves, scroll and hover do not clear it. A timeout was also rejected: it clears the state precisely while the user is not looking.

**A ZIP silently missing the failed 題組.** Rejected: it reintroduces the uncertainty.

**Rendering `card.modificationSubmitted`.** Rejected: the run surface already narrates a modification run (status bar, ripple report, 已修改 chip) and the model says the control never narrates completion.

**Backend acknowledgement or progress events**, and **re-enabling submit during a run**, are outside this decision (map C4 and ADR 0010).

## Consequences

Every async control goes through the one primitive; a new control that does async work defaults to it, and a bare `onClick` with a promise and no `.catch` is a review flag. The three silent exports gain `.catch` and error surfaces; the 產生 spinner is gated on `resolverLoading`; 重抽 is disabled while resolving; history paging shows 處理中.

Tests assert **state and ARIA, not motion**: the state on the control (`data-action-state` or the label text), `disabled`, `aria-busy` on lists, the `role="status"` text, the presence and content of the `role="alert"` notice, that × dismisses it, that a successful retry clears it, that a second press during 處理中 is ignored, and that a failed 重抽 keeps its value. CSS motion is not asserted in jsdom (ADR 0029). Existing `GenerationStatusBar` and `AgentStatusPanel` tests change with the decided renames (生成中 → 產生中, 驗證/修正 → 審題/改題 in the breadcrumb, the removed ◐, the shared spinner replacing `.animate-spin`); they are updated, not weakened.

Every new string ships in both locales. The 操作回饋 labels are unmasked chrome; the one-line reason is not, so a reason must never be composed from question content and unmasked.

For 產生 and 確定發送, a session's replay now records the control's visible acknowledgement, whether a request began, and the disclosed error or hand-off — the acceptance evidence the #764 (Sentry E / 無法送出) investigation asked for. Closing #764 is a separate decision.
