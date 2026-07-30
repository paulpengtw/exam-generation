# the back guard blocks only history navigation

The 生成頁面 shows a 破壞性操作確認 before the user loses 未送出的輸入 or generated questions. In-page click handlers cover every exit the app renders itself — the back-to-subjects button, the history link, logout, clearing results, re-submitting — and they do so through the `handleNavigation` path, which sets `pendingNavigationTarget` and opens the modal before calling `navigate()`. Browser or hardware Back, however, never passes through any of those handlers; it arrives as a history-pop event that the router intercepts below the React component tree. #218–#220 added the in-page guards. #223 (PR #275) added `useBlocker` to close the Back-button gap.

`useBlocker` intercepts **every** router navigation, including the programmatic `navigate()` calls that the in-page confirmations fire after the user has already confirmed an exit. Without further qualification, confirming an in-page exit would cause the blocker to fire again immediately, raising a second 破壞性操作確認 for the same action — a regression against #218–#220. Distinguishing "user pressed Back" from "our own code called `navigate()`" requires inspecting the `historyAction` argument the router passes to the blocker predicate. Browser and hardware Back arrive as `"POP"`; programmatic `navigate()` calls arrive as `"PUSH"` or `"REPLACE"`. The blocker in `web/src/pages/GeneratePage.tsx` is therefore scoped to `"POP"`:

```ts
const blocker = useBlocker(
  ({ historyAction }) =>
    (hasUnsubmittedInput || hasResults) && historyAction === "POP",
);
```

## Considered Options

Blocking all navigations and deleting the `pendingNavigationTarget` machinery to unify on one guard was rejected. The in-page 破壞性操作確認 modals carry per-exit copy — the logout dialog warns about ending the session, the clear-results dialog warns about discarding generated questions, the re-submit dialog warns about aborting a running generation — that a single generic blocker modal cannot express. Removing `pendingNavigationTarget` would mean all in-page exits show the same generic "leave page?" text regardless of what the user is actually about to lose.

Blocking all navigations and adding a suppression flag set while an in-page confirmation is in flight was rejected. The flag would be a second piece of mutable state that must be set and cleared correctly in every current and future in-page exit. It fails open: any exit that forgets to raise the flag before calling `navigate()` causes the blocker to fire a second time, reproducing the original regression. The surface area grows with every new exit the app ever adds.

## Consequences

Two guard mechanisms coexist by design. In-page exits the app renders use the `handleNavigation` / `pendingNavigationTarget` path and call `navigate()` only after the user confirms; the blocker ignores those calls because they arrive as `"PUSH"`. Browser and hardware Back arrive as `"POP"` and are caught by the blocker. Adding a new in-page exit means wiring it through `handleNavigation` and never touching the blocker.

The `historyAction === "POP"` clause was surfaced by mutation testing: deleting it originally killed no test out of 288, leaving the behaviour unprotected. The behaviour is now pinned by `web/src/pages/GeneratePage.back-guard.test.tsx`, specifically the test "confirming an in-page exit does not ask a second time", which asserts that a confirmed in-page navigation does not trigger a second blocker modal. This ADR is the rationale; that test is the enforcement.
