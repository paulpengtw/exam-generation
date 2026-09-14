# the motion identity is a token module plus the platform, with Motion loaded selectively

Before wayfinder map #720 the web app's entire stylesheet was `@import "tailwindcss";`: zero design tokens, no animation library, no shared spinner, button or skeleton, six hand-rolled `animate-spin` spinners in four shapes, seven bare `transition` classes with no `duration-*` / `ease-*`, no `@keyframes`, and no `prefers-reduced-motion` handling anywhere. The map's constraint C8 said *use others' wheels* — shadcn/ui, AICSS and an animation library — and C3 said the motion identity covers every motion-eligible moment that already exists (route changes, QuestionCards streaming into results, 生成進度列 state changes, disclosure toggles, the 破壞性操作確認 dialog, subject-select cards, language switch) using only elements that already exist: no new decorative or ambient elements.

This ADR records the stack-fit research (#721), the AICSS motion-vocabulary research (#722), the library and token decisions (#725), the AICSS adoption decision (#726), and the timing amendments from the maintainer's measured review of the #727 prototype. The states these motions carry are ADR 0028. A reader will question two things here: why there is no single animation library, and why the tokens are a TypeScript module rather than CSS. Both are answered below.

## The stack

**shadcn/ui is initialised, and adopted only as far as the map reaches.** `npx shadcn init` coexists with `@tailwindcss/vite` (no PostCSS). Repo-specific adjustments from the spike: drop the CLI's `baseUrl` (TypeScript 6 `TS5101`) while keeping `paths` plus `@` aliases in `vite.config.ts` and `vitest.config.ts`; one file-local lint disable on `button.tsx`. The CLI's defaults were re-decided deliberately: **Base UI** stays as the primitive layer; the `@fontsource-variable/geist` import is dropped (the app renders CJK on the system stack); `--primary` is remapped to the app's blue-600; the generated `.dark` block stays inert and `data-theme="light"` is pinned on `<html>`. Adoption scope: `init` for the theme plumbing plus `tw-animate-css`, and the `Button` primitive under the 操作回饋 control. Nothing else migrates.

**AICSS is a recipe source, not a dependency.** Exactly two keyframes are vendored into `web/src/motion/aicss.css` — `label-shine` (the shimmer sweep) and `caret-blink` — re-tokenised to the loop easing and duration tokens and the app's colours (shimmer base blue-600, highlight blue-300). The header comment names `github.com/kvnkld/aicss`, commit `4556a918` and the MIT licence; the licence text ships as `web/src/motion/LICENSE-aicss.txt`. No registry components, no `@aicss/react`, no Orbs, no TaskList, no ThinkingReasoning / StreamingText, no Inter. AICSS remains the *source of the motion personality* (#722 read its CSS modules: shimmer loops at `2.25s cubic-bezier(0.25, 0.1, 0.25, 1)`, state changes 140–560 ms on `cubic-bezier(0.22, 1, 0.36, 1)`, a decelerate with no overshoot), not a runtime dependency.

**Motion (`motion/react`) is adopted selectively**, through `LazyMotion` with the `domAnimation` feature set (≈15 kB gzip, not the ≈127 kB of the full import) and `m.` components under `strict`, for presence and layout only: QuestionCards entering the results list, dynamic disclosures, and the hand-off. `useReducedMotion` mirrors the reduced-motion rule below. **`tw-animate-css`** (installed by shadcn, CSS-only) drives class-driven state swaps on controls. **Native CSS** — `@starting-style`, `dialog:open`, discrete `display` / `overlay` transitions with `transition-behavior: allow-discrete` — animates the 破壞性操作確認 dialog's `showModal()` lifecycle; no JS wrapper around the dialog. **React Router `viewTransition`** on the data router, feature-detected, handles route changes; `useBlocker` and the ADR 0008 / 0013 behaviour are untouched. Nothing else.

## The tokens

| Token | Value | Used for |
|---|---|---|
| `quick` | 150 ms | control state swaps, hover, the 重抽 row flash, every exit (confirmation exit, dialog close, list fade) |
| `standard` | 320 ms | card entrance, dialog open and backdrop, disclosure expand, inline notice appear, bar pulse, route cross-fade |
| `loop-shimmer` | 2250 ms | the 生成進度列 shimmer sweep |
| `loop-spinner` | 900 ms | one rotation of the shared spinner |
| `signature` | `cubic-bezier(0.22, 1, 0.36, 1)` | every entrance and on-screen state change |
| `exit` | `cubic-bezier(0.64, 0, 0.78, 0)` | anything leaving |
| `loop` | `cubic-bezier(0.25, 0.1, 0.25, 1)` | indeterminate indicators only |

**No overshoot, no back-easing anywhere.** Entrances are opacity 0→1 plus 8 px of upward travel, `standard`, `signature`, always from below; lists stagger 40 ms per item, capped at 400 ms. Exits use the faster token than their entrance.

Two amendments from the #727 review, which measured every moment with in-page recorders. First, **the single `loop` duration of 2250 ms is split**: it is right for a shimmer and wrong for a spinner — the 重抽 and history-paging spinners are on screen for about 600 ms, a quarter of one rotation, so at 2250 ms they read as a tilted glyph, not activity. Second, **control state swaps drop from `standard` to `quick`** (a label / icon swap is a discrete change, not a travelling one) and **the route cross-fade drops from 560 ms to the review's 300 ms target**, which this ADR rounds to the `standard` token rather than adding a fifth duration. That left the `slow` 560 ms token with no user, so it is retired. Everything else measured well and keeps its #725 value.

**The hand-off** (the acknowledgement for 確定發送, ADR 0028) is three beats in one direction of travel with at most one element in flight: the confirmation section exits downward (`quick`, `exit`) → the form section enters (`standard`) → the 生成進度列 highlights with a single background pulse and its running indicator switches on, starting 100 ms after the exit begins (`standard`). Under 600 ms in total; the review measured the first SSE event and bar pulse at ~300 ms and the confirmation gone by ~500 ms and judged the three beats one motion. No auto-scroll; the bar is fixed and visible.

**The ambient rule.** The shimmer sweep across the 生成進度列's live text is the one ambient layer C3 allows, and it appears nowhere else; the static ◐ glyph is removed. Every other 處理中 uses one shared spinner with linear rotation. The `AgentStatusPanel` lanes show a caret at the tail of the active `<pre>` pane while streaming; the `ProgressLog` status line mirrors the bar's label with the spinner and no shimmer; an in-flight card in a batch carries a spinner phase chip.

## Where the tokens live

**`web/src/motion/tokens.ts` is the single source of truth.** At startup, before first render in `main.tsx`, it writes `--motion-duration-{quick,standard,loop-shimmer,loop-spinner}` and `--motion-ease-{signature,exit,loop}` onto `:root`; the vitest setup file applies the same call so jsdom components see them. `index.css` declares `@theme inline { --duration-quick: var(--motion-duration-quick); … }` — the same indirection shadcn uses for colours — so `duration-quick` / `ease-signature` utilities resolve at runtime. Motion's `MotionConfig` reads the module directly. No adapter, no build step, no duplicated values.

## Reduced motion

When `prefers-reduced-motion: reduce` holds, the state still changes; only the transition is dropped. Entrances, exits and state transitions collapse to an instant, opacity-only change; route cross-fades are skipped; indeterminate indicators keep running but drop to an opacity pulse with no translation or rotation; the caret goes solid. `useReducedMotion` applies the same rule to Motion.

## Considered Options

**One blanket animation library for every surface.** Rejected. The dialog's `showModal()` lifecycle and route changes are better served by the platform, and the full Motion import costs ≈127 kB gzip for work it would not do; `LazyMotion` with `domAnimation` covers the three places JS presence and layout are actually needed at ≈15 kB.

**AICSS as a dependency (`@aicss/react` or registry components).** Rejected. The package fails the app's strict `tsc -b` on unused declarations in `Orb.tsx`; the components carry their own easings and require Inter; Orbs are decorative and would breach C3; the registry `ThinkingState` has no children prop and the lane panes hold raw thinking and JSON, not prose. Two keyframes carry the personality without any of that.

**Tokens as CSS custom properties only, or as a Tailwind theme only.** Rejected. Motion reads JS values through `MotionConfig` and does not read CSS custom properties, so a CSS-only source needs an adapter and two sources drift. A module that writes onto `:root` gives CSS, Tailwind utilities and Motion one origin.

**Picking a personality from an archetype table.** Rejected at charting (C8): the personality is derived from AICSS's own curves, then extended into a palette.

**Keeping one `loop` token for shimmer and spinner.** Rejected after measurement, as above. **Adding a fifth duration for the route cross-fade.** Rejected; 300 ms and 320 ms are indistinguishable at that scale and the palette stays at four.

**Overshoot or back-easing** for entrances, **Radix** instead of Base UI, **Geist**, and **dark mode** were each rejected or deferred: the last is a fresh effort with its own palette and replay-masking questions, recorded on the map as out of scope.

## Consequences

Adding or changing a duration or easing means editing `tokens.ts` only; the CSS utilities and Motion follow. A bare `transition` class without a token, a literal `duration-300`, or a hand-rolled `@keyframes` outside `web/src/motion/` is a review flag. Six spinners become one component; `.animate-spin` disappears from the app.

jsdom runs no CSS animations, so tests assert what jsdom can see: the tokens written onto `:root` (values and the reduced-motion branch), the class and data contracts on the surfaces, and Motion presence with real timers and `waitFor` where the DOM actually changes. The native dialog transition and the route view transition are verified in a browser when the build lands and are not unit-tested.

Bundle: JS grows by roughly the `LazyMotion` feature set; CSS grows by shadcn's theme (about 33 → 49 kB uncompressed on the spike). No new `sentry-unmask` beyond the fixed state labels of ADR 0028; no portal-mounted element.

The renames the surfaces carry (生成中 → 產生中, breadcrumb 驗證/修正 → 審題/改題 in zh-TW, English unchanged) ship in both locales; the existing `GenerationStatusBar` and `AgentStatusPanel` tests are updated to the decided labels and the shared spinner.

A dark theme, AICSS Orbs or any ambient element beyond the bar's shimmer would supersede parts of this decision and need their own ADR.
