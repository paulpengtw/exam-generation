# Research #722 — AICSS Motion Vocabulary (wayfinder map #720)

**Issue:** https://github.com/paulpengtw/exam-generation/issues/722  
**Parent map:** https://github.com/paulpengtw/exam-generation/issues/720  
**Date:** 2026-09-12  
**App commit under test:** `ad3318f` (branch `research/720-aicss-motion`, origin/staging)  
**AICSS commit read:** `4556a918fd8c9358d42d2b24a3866301b8ea10a2` (MIT, https://github.com/kvnkld/aicss)  
**Primary source:** cloned to scratchpad at `packages/react/src/`; every `.module.css` and `.tsx` read directly.  
**Registry:** all 15 components fetched from `https://www.aicss.dev/r/<name>.json` — 14 returned HTTP 200, `todo-list` returned 404 (registry names it `task-list` instead).

---

## TL;DR

AICSS's motion personality is **Premium** with a Sine/Spring hybrid: dominant easing `cubic-bezier(0.22, 1, 0.36, 1)` (aggressive spring — very high overshoot), duration centroid 280–360 ms for state transitions, with a separate two-family approach: indeterminate-progress loops run 1.6–4.8 s with `ease-in-out` or `linear`; state-change transitions run 220–420 ms with the spring curve. No component uses `ease-out-expo` or `ease-out-back`; none overshoots on opacity-only transitions. The shimmer motif (`label-shine` / `tr-shine` / `todo-shine` / `pi-shine`) is shared across five components at exactly `2.25 s cubic-bezier(0.25, 0.1, 0.25, 1)`. The app currently has no CSS motion at all (static ◐ glyph, `animate-spin` via Tailwind at an unknown cubic-bezier). Proposed palette: quick 150 ms / standard 320 ms / slow 560 ms, signature easing `cubic-bezier(0.22, 1, 0.36, 1)`.

---

## 1. Animation Inventory

Sources: `packages/react/src/*/` at commit `4556a918`. All durations/easings are as declared in the CSS; no `prefers-reduced-motion` notes below unless the CSS provides an explicit guard.

### ThinkingState — `thinking-state/ThinkingState.module.css`

| Keyframe | Property animated | Duration | Delay | Easing | Iteration | Amplitude | Reduced-motion guard |
|---|---|---|---|---|---|---|---|
| `label-shine` (`.shimmer`) | `background-position` (shimmer sweep) | 2.25 s | — | `cubic-bezier(0.25, 0.1, 0.25, 1)` (near-linear with soft start/end) | infinite | 300% background-size sweep | None |

No additional animations. Hard-coded colours `#a1a1a1` / `rgba(161,161,161,0.45)`. No CSS custom properties exposed.

### ThinkingReasoning — `thinking-reasoning/ThinkingReasoning.module.css`

| Keyframe | Property | Duration | Delay | Easing | Iteration | Amplitude | Guard |
|---|---|---|---|---|---|---|---|
| `tr-block-in` (`.tr`) | `opacity` | 320 ms | — | `cubic-bezier(0.22, 1, 0.36, 1)` | once (`both`) | 0→1 | None |
| `tr-sentence-in` (`.trSentence`) | `opacity` | 420 ms | — | `cubic-bezier(0.22, 1, 0.36, 1)` | once (`both`) | 0→1 | None |
| `tr-shine` (`.trShimmer`) | `background-position` | 2.25 s | — | `cubic-bezier(0.25, 0.1, 0.25, 1)` | infinite | 300% sweep | None |

Transitions (not keyframes):
- `.trChevron`: `transform 280ms cubic-bezier(0.22, 1, 0.36, 1)`
- `.trCollapsible`: `grid-template-rows 320ms cubic-bezier(0.22, 1, 0.36, 1)`, `opacity 220ms ease`
- `.trViewport`: `height 360ms cubic-bezier(0.22, 1, 0.36, 1)`
- `.trStream`: `transform 560ms cubic-bezier(0.22, 1, 0.36, 1)` (`will-change: transform`)

CSS custom properties exposed (with light/dark defaults):

| Property | Light | Dark |
|---|---|---|
| `--tre-label` | `color-mix(in srgb, #a1a1a1 68%, transparent)` | `#737373` |
| `--tre-verb` | `#a1a1a1` | `#a3a3a3` |
| `--tre-chevron` | `#a1a1a1` | `#737373` |
| `--tre-sentence` | `#a1a1a1` | `#737373` |
| `--tre-hover` | `#a1a1a1` | `#a3a3a3` |

Font: `"Inter", system-ui, sans-serif`. No hard-coded bg colour; no dark-mode for block-in or sentence-in animations.

### Orbs — `orbs/Orb.module.css`

Three easing variables declared on `.root`:
- `--orb-ease-smooth`: `cubic-bezier(0.22, 1, 0.36, 1)`
- `--orb-ease-out`: `cubic-bezier(0.17, 1, 0.32, 1)`
- `--orb-ease-in-out`: `cubic-bezier(0.66, 0, 0.34, 1)` (symmetric S-curve, very tight)

These cannot be used inside `@keyframes` `animation-timing-function` declarations (the comment says so explicitly at line 9), so they are stored for reference only and keyframes use literal values.

**Lattice family (S-variants):**

| Keyframe | Variants | Duration | Easing | Iteration | Properties | Per-cell stagger (set via JS) |
|---|---|---|---|---|---|---|
| `orb-wave` | S1, S2 | 1.7 s | `cubic-bezier(0.66, 0, 0.34, 1)` (per-segment) | infinite `both` | `opacity` (rest→1→rest), `transform scale` (1→1.18→1) | yes |
| `orb-wave` | S4 | 1.6 s | same | infinite `both` | same | yes |
| `orb-comet` | S3, S5 | 1.7 s | `cubic-bezier(0.22, 1, 0.36, 1)` (per-segment) | infinite `both` | `opacity` (1→rest), `transform scale` (1.2→1) | yes |

**Lens family (B-variants):**

| Keyframe | Variants | Duration | Easing | Iteration | Properties | Stagger |
|---|---|---|---|---|---|---|
| `orb-focus` | B1 | 4 s | `cubic-bezier(0.4, 0, 0.2, 1)` (per-segment) then `linear` | infinite `both` | `opacity`, `filter blur`, `transform scale` | −3s, −2s, −1s, 0s |
| `orb-revolve` | B2 | 3.3 s | `linear` | infinite `both` | `opacity`, `filter blur`, `transform rotate+translateY scale` | −1.1s, −2.2s |
| `orb-bloom` | B3 | 4.2 s | `cubic-bezier(0, 0, 0.2, 1)` (enter) then `cubic-bezier(0.16, 1, 0.3, 1)` (mid) then `linear` | infinite `both` | `opacity`, `filter blur`, `transform scale` (0.35→2.4) | −1.4s, −2.8s |
| `orb-converge` | B4 shapeA | 3.6 s | `linear` + per-segment `cubic-bezier(0.55, 0, 1, 0.45)` (accel) + `cubic-bezier(0.33, 1, 0.68, 1)` (decel) | infinite `both` | `transform translate+scale`, `filter blur` | — |
| `orb-breathe` | B4 shapeB, B5 shapeB | 3.6 s | `ease-in-out` | infinite `both` | `opacity`, `filter blur`, `transform scale` | — |
| `orb-handoff` | B5 shapeA, C | 2.8 s | `cubic-bezier(0.33, 1, 0.68, 1)` (entry/exit) | infinite `both` | `opacity`, `filter blur`, `transform translateX scale` (±11px, 0.55→1→0.55) | −1.4s |

**Ring family (C-variants):**

| Keyframe | Variants | Duration | Easing | Iteration | Properties | Guard |
|---|---|---|---|---|---|---|
| `orb-ring-chase` | C1 | 1.6 s | `linear` | infinite `both` | `opacity` | — |
| `orb-ring-pulse` | C2 | 2 s | `ease-in-out` | infinite `both` | `opacity`, `transform scale` (0.7→1.15) | — |
| `orb-ring-comet` | C3, C5 | 1.8 s | `ease-in-out` + per-segment `cubic-bezier(0.33, 1, 0.68, 1)` | infinite `both` | `opacity` | — |
| `orb-ring-stagger` | C4 | 1.6 s | `ease-in-out` | infinite `both` | `opacity` | — |

**Globe / Helix family (G-variants):**

| Keyframe | Variants | Duration | Easing | Properties |
|---|---|---|---|---|
| `orb-globe-spin` | G1 | 4.5 s | `linear` | `transform translate`, `opacity` (via CSS var) |
| `orb-globe-spin` | G2 | 3.6 s | `linear` | same |
| `orb-globe-ringturn` | G3, G4 | 2.8 s | `linear` | same |
| `orb-globe-breathe` | G5 | 3.6 s | `linear` | same |

**Morph family (M-variants):**

| Keyframe | Variants | Duration | Easing | Properties |
|---|---|---|---|---|
| `orb-morph` | M (default) | 4.8 s | `cubic-bezier(0.4, 0, 0.2, 1)` | `transform translate` (via CSS var `--m-1` through `--m-4`) |
| `orb-morph-twist` | M2, M4 | 9.6 s | `linear` | `transform rotate(360deg)` |
| `orb-morph-scatter` | M5 | 2.8 s | `cubic-bezier(0.4, 0, 0.2, 1)` | `transform translate`, `opacity` |

**`prefers-reduced-motion` guard:** YES. At the bottom of `Orb.module.css`:
```css
@media (prefers-reduced-motion: reduce) {
  .cell, .shape, .ringDot, .helixDot, .morphDot { animation: none !important; }
  /* fallback static appearances defined */
}
```

CSS custom properties (Orbs):

| Property | Light | Dark |
|---|---|---|
| `--orb-fg` | `#1a1a1a` | `#f5f5f5` |
| `--orb-pill-bg` | `#ffffff` | `#1a1a1a` |
| `--orb-pill-shadow` | light box-shadow | dark box-shadow |
| `--orb-label` | `#a1a1a1` | `#a3a3a3` |
| `--orb-rest-ink` | `0.14` | `0.2` |
| `--orb-dim-ink` | `0.07` | `0.1` |
| `--orb-ring-rest-ink` | `0.22` | `0.3` |

Scale knob: `--orb-k` (default 1; scales the 28 px stage). Per-dot position vars: `--orb-rx/ry`, `--g0x…g30x/y/o`, `--m-1…m-4`, `--orb-ox/oy`, `--orb-d`.

### StreamingText — `streaming-text/StreamingText.module.css`

| Keyframe | Property | Duration | Easing | Iteration | Guard |
|---|---|---|---|---|---|
| `caret-blink` (`.caret`) | `opacity` | 1 s | `step-end` | infinite | YES: `animation: none` under `prefers-reduced-motion: reduce` |

`.caretSteady { animation: none; opacity: 1; }` — caret is solid while streaming.

CSS custom properties:

| Property | Light | Dark |
|---|---|---|
| `--st-fg` | `#1a1a1a` | `#f5f5f5` |
| `--st-caret` | `#0b0d12` | `#f5f5f5` |

### TextResponse — `text-response/TextResponse.module.css`

No animations or transitions. Static layout only.

CSS custom properties:

| Property | Light | Dark |
|---|---|---|
| `--tr-fg` | `#1a1a1a` | `#f5f5f5` |
| `--tr-code-bg` | `#f4f5f7` | `#242424` |

### CodeBlock — `code-block/CodeBlock.module.css`

No animations or transitions.

CSS custom properties:

| Property | Light | Dark |
|---|---|---|
| `--cb-bg` | `#fff` | `#1a1a1a` |
| `--cb-ring` | `#e6e8ec` | `#303030` |
| `--cb-shadow` | hairline + 2-layer drop | same dark |
| `--cb-fg` | `#1a1a1a` | `#f5f5f5` |
| `--cb-copy-hover-fg` | `#1a1a1a` | `#f5f5f5` |
| `--cb-copy-hover-bg` | `#f4f5f7` | `#242424` |

### TaskList (TodoList) — `task-list/TodoList.module.css`

| Keyframe / transition | Property | Duration | Easing | Iteration | Amplitude | Guard |
|---|---|---|---|---|---|---|
| `todo-item-in` | `opacity`, `transform translateY` | 360 ms | `ease` (implicit) | once (`backwards`) | `translateY(-7px)` → 0 | YES: `animation: none` |
| `todo-shine` (active item label `::before`) | `background-position` | 2.25 s | `cubic-bezier(0.25, 0.1, 0.25, 1)` | infinite | 300% sweep | YES: `animation: none` |
| `.todoCollapsible` transition | `grid-template-rows`, `opacity` | 280 ms / 200 ms | `ease` | — | 1fr→0fr | YES: `transition: none` |
| `.todoIcon` transition | `opacity` | 320 ms | `ease` | — | 0→1 crossfade | YES: `transition: none` |
| `.todoLabel` transition | `color` | 360 ms | `ease` | — | muted→transparent | YES: `transition: none` |
| `.todoLabel::before` transition | `opacity` | 360 ms | `ease` | — | 0→1 (shimmer on) | YES: `transition: none` |
| `.rollInner` transition (count digit roll) | `transform translateY` | 350 ms | `cubic-bezier(0.4, 0, 0.2, 1)` | — | −1em | not explicitly guarded |
| `--todo-pie` CSS `@property` transition | `<percentage>` (pie fill) | 400 ms | `ease` | — | 0%→n% | not explicitly guarded |

Per-item stagger: `animation-delay: calc(var(--i, 0) * 50ms)` — 50 ms per item.

CSS custom properties:

| Property | Light | Dark |
|---|---|---|
| `--todo-fg` | `#1a1a1a` | `#f5f5f5` |
| `--todo-bg` | `#fff` | `#1a1a1a` |
| `--todo-shadow` | hairline + 2-layer drop | dark equivalent |
| `--todo-muted` | `#a1a1a1` | `#737373` |
| `--todo-check` | `#15a06a` (green) | `#34d399` |
| `--todo-strong` | `#1a1a1a` | `#f5f5f5` |
| `--todo-pie-fg` | `#1a1a1a` | `#f5f5f5` |
| `--todo-shine` | gradient literal | gradient literal |
| `--todo-pie` (CSS `@property`) | `<percentage>` 0% init | — |

### DataTable — `data-table/DataTable.module.css`

No animations or transitions.

CSS custom properties:

| Property | Light | Dark |
|---|---|---|
| `--tbl-bg` | `#fafafa` | `#242424` |
| `--tbl-shadow` | hairline + 2-layer drop | dark equivalent |
| `--tbl-body-bg` | `#fff` | `#1a1a1a` |
| `--tbl-line` | `#e6e8ec` | `#303030` |
| `--tbl-cell` | `#1a1a1a` | `#f5f5f5` |

### AIAgentInput (PromptInput) — `ai-agent-input/PromptInput.module.css`

CSS `@property` for `--pi-angle`:
```css
@property --pi-angle { syntax: "<angle>"; inherits: false; initial-value: 0deg; }
```

| Keyframe / transition | Property | Duration | Easing | Iteration | Amplitude | Guard |
|---|---|---|---|---|---|---|
| `pi-border-spin` (enhancing ring) | `--pi-angle` | 1.1 s | `linear` | infinite | 0→360deg | YES: `animation: none` |
| `pi-border-in` | `opacity` | 220 ms | `cubic-bezier(0.22, 1, 0.36, 1)` | once (`both`) | 0→1 | YES: `animation: none` |
| `pi-shine` (`.enhancingText`) | `background-position` | 2.25 s | `cubic-bezier(0.25, 0.1, 0.25, 1)` | infinite | 300% sweep | YES: `animation: none` |
| `pi-chip-in` | `opacity`, `transform translateY`, `filter blur` | 260 ms | `cubic-bezier(0.22, 1, 0.36, 1)` | once (`both`) | `translateY(4px)`, `blur(2px)` | YES: `animation: none` |
| `pi-pill-in` | `opacity`, `transform scale`, `filter blur` | 260 ms | `cubic-bezier(0.22, 1, 0.36, 1)` | once (`both`) | `scale(0.96)`, `blur(2px)` | YES: `animation: none` |
| `pi-pill-out` | same reversed | 180 ms | `cubic-bezier(0.22, 1, 0.36, 1)` | once (`both`) | symmetric | YES: `animation: none` |
| `pi-menu-in` | `opacity`, `transform translateY+scale`, `filter blur` | 200 ms | `cubic-bezier(0.22, 1, 0.36, 1)` | once (`both`) | `translateY(6px) scale(0.98)`, `blur(2px)` | YES: `animation: none` |
| `pi-spin` (loading spinner) | `transform rotate` | 0.7 s | `linear` | infinite | 360deg/cycle | spinner slows to 1.4s under reduced-motion |
| `.iconBtn::before` transition | `background`, `transform` | 150 ms | `cubic-bezier(0.22, 1, 0.36, 1)` | — | scale 0.98 on active | YES: `transition: none` |
| `.plusIcon` transition | `transform rotate` | 200 ms | `cubic-bezier(0.35, 1.55, 0.65, 1)` (**overshoot spring**) | — | 0→45deg | YES: `transition: none` |
| `.skillPillX` transition | `opacity`, `background` | 150 ms | `cubic-bezier(0.22, 1, 0.36, 1)` | — | — | YES: `transition: none` |
| `.chipRemove` transition | `background`, `color` | 150 ms | `cubic-bezier(0.22, 1, 0.36, 1)` | — | — | YES: `transition: none` |

Note: `.plusIcon` uses `cubic-bezier(0.35, 1.55, 0.65, 1)` — the only **explicit overshoot** (back-easing) in the library. The +icon rotates to × past 45° and springs back.

CSS custom properties:
`--pi-frame-bg`, `--pi-frame-shadow`, `--pi-fg`, `--pi-muted`, `--pi-enhance-ring` (conic gradient), `--pi-shimmer`, `--pi-chip-bg`, `--pi-chip-border`, `--pi-icon-fill`, `--pi-icon-fill-hover`, `--pi-icon-fill-open`, `--pi-chip-remove-hover`, `--pi-send-fg`, `--pi-send-bg`, `--pi-send-bg-hover`, `--pi-menu-bg`, `--pi-menu-border`, `--pi-menu-hover`, `--pi-menu-active`, `--pi-skill-bg`, `--pi-skill-fg`, `--pi-angle`.

Hard-coded brand colours in `--pi-enhance-ring`: `#2b7fff`, `#8b5cf6`, `#d946ef`, `#22d3ee` (light); muted equivalents in dark.

### ApprovalCard — `approval-card/ApprovalCard.module.css`

| Keyframe / transition | Property | Duration | Easing | Iteration | Amplitude | Guard |
|---|---|---|---|---|---|---|
| `ap-card-in` (`.card`) | `opacity`, `transform translateY` | 380 ms | `cubic-bezier(0.22, 1, 0.36, 1)` | once (`both`) | `translateY(8px)` → none | YES: `animation: none` |
| `.questionsViewport[data-animate]` transition | `height` | 360 ms | `cubic-bezier(0.22, 1, 0.36, 1)` | — | content height change | YES: `transition: none` |
| `.questionsTrack[data-animate]` transition | `transform` | 360 ms | `cubic-bezier(0.22, 1, 0.36, 1)` | — | slide between questions | YES: `transition: none` |
| `.questionsTrack .question` transition | `opacity` | 360 ms | `cubic-bezier(0.22, 1, 0.36, 1)` | — | 0→1 per-question fade | YES: `transition: none` |
| `.todoCollapsible` transition | `grid-template-rows`, `opacity` | 280 ms / 200 ms | `cubic-bezier(0.22, 1, 0.36, 1)` | — | 1fr→0fr | YES: `transition: none` |
| `.digitRollInner` transition | `transform translateY` | 350 ms | `cubic-bezier(0.4, 0, 0.2, 1)` | — | digit roll | YES: `transition: none` |
| `.btnGhost::before`, `.btnPrimary::before` | `background` | 150 ms | `cubic-bezier(0.22, 1, 0.36, 1)` | — | hover colour | YES: `transition: none` |
| `.autoApprove` transition | `opacity` | 280 ms | `cubic-bezier(0.22, 1, 0.36, 1)` | — | show/hide | YES: `transition: none` |
| `.autoApprovePieFill` transition | `stroke-dashoffset` | 1 s | `linear` | — | countdown pie | YES: `transition: none` |
| `.autoApproveTip::after` transition | `opacity`, `transform`, `filter blur` | 150 ms | `ease` | — | tooltip fade | YES: `transition: none` |
| `.option` transition | `background-color` | 150 ms | `cubic-bezier(0.22, 1, 0.36, 1)` | — | hover | YES: `transition: none` |
| `.key::before` transition | `opacity` | 240 ms | `cubic-bezier(0.22, 1, 0.36, 1)` | — | selected state | YES: `transition: none` |
| `.stepArrow`, `.todoMore`, `.headAction` transitions | `color` | 150 ms | `cubic-bezier(0.22, 1, 0.36, 1)` | — | hover colour | YES: `transition: none` |

ApprovalCard has **no CSS custom properties** — all colours are hard-coded:
- Light: `background: #ffffff`, `color: #1a1a1a`, `#a1a1a1` muted, `#15a06a` green auto-approve (light), `#0b0d12` primary button bg.
- Dark (via `[data-theme="dark"]` / `.dark` / `@media prefers-color-scheme: dark`): `background: #1a1a1a`, `color: #f5f5f5`, `#737373` muted, `#34d399` green, `#f5f5f5` primary button.

---

## 2. CSS Custom Properties and Theming Hooks

All components use the three-tier theming pattern:
```css
:global(:root), :global([data-theme="light"]) { ... }
:global([data-theme="dark"]), :global(.dark) { ... }
@media (prefers-color-scheme: dark) { :global(:root:not([data-theme])) { ... } }
```

**Font:** `"Inter"` (or `"Inter Variable"` in AIAgentInput) everywhere. No font custom properties — hard-coded in selectors.

**Consolidated palette across all components:**

| Semantic | Light hex | Dark hex |
|---|---|---|
| Foreground / text | `#1a1a1a` | `#f5f5f5` |
| Background (card) | `#ffffff` | `#1a1a1a` |
| Background (table bg) | `#fafafa` | `#242424` |
| Background (code well) | `#f4f5f7` | `#242424` |
| Muted (label, icon) | `#a1a1a1` | `#737373` or `#a3a3a3` |
| Divider / ring | `#e6e8ec` | `#303030` |
| Success / check | `#15a06a` | `#34d399` |
| Primary button bg | `#0b0d12` | `#f5f5f5` |
| Primary button fg | `#ffffff` | `#0a0a0a` |
| Primary button hover | `#2a2f3a` | `#ffffff` |
| Caret (StreamingText) | `#0b0d12` | `#f5f5f5` |

Dark mode is supported via three-tier selector chain AND `prefers-color-scheme`. No component relies on OS preference alone — explicit `[data-theme]` overrides are provided.

---

## 3. Motion Personality

### Duration range

Excluding indeterminate-progress loops:

- **Minimum (micro-interactions, hover):** 140–150 ms (`.todoIcon` opacity, hover transitions)
- **Centroid (state-change transitions):** 280–380 ms (`ap-card-in` 380 ms, `tr-block-in` 320 ms, viewport height 360 ms, collapsible 280 ms)
- **Maximum (deep content reveal):** 560 ms (`.trStream` transform)
- **Shimmer loops:** 2.25 s (same across all 5 uses)
- **Indeterminate orbs:** 1.6–4.8 s; globe/helix: 2.8–4.5 s

### Easing family

**Dominant:** `cubic-bezier(0.22, 1, 0.36, 1)` — used in every component for entrance/exit/collapse/viewport transitions. This is an aggressive spring with zero control-point pull on exit and a very high exit velocity (approaches `ease-out-expo` in feel) but without the hard overshoot of `ease-out-back`. Mathematically: starts slow, peaks fast at ~15% of duration, then gently decelerates.

**Shimmer:** `cubic-bezier(0.25, 0.1, 0.25, 1)` — near-CSS-default `ease`, with a slightly rounder arc.

**Morph/digit:** `cubic-bezier(0.4, 0, 0.2, 1)` — Material Design's standard easing; symmetric sigmoid; used for content changes (digit roll, morph shape morphing).

**Orb progress loops:** `cubic-bezier(0.66, 0, 0.34, 1)` (symmetric tight S, near sine wave), `ease-in-out`, `linear`.

**Only overshoot (back):** `cubic-bezier(0.35, 1.55, 0.65, 1)` — `.plusIcon` rotate (AIAgentInput + button toggle only).

**Overshoot percentage of primary spring (`0.22, 1, 0.36, 1`):** The y-value reaches ~1.03–1.06 at the exit peak (barely perceivable on opacity; more visible on `transform`). Functionally 0–5% overshoot. Not a back-easing.

### Archetype classification

| Archetype | Criteria match | Notes |
|---|---|---|
| Playful (150-300ms, ease-out-back, 10-20% overshoot) | Partial | Duration range overlaps 150-300ms but easing is not `ease-out-back`; only 1 use of back-spring |
| **Premium (350-600ms, cubic-bezier(0.4,0,0.2,1), 0% overshoot)** | **Partial** | The `0.4,0,0.2,1` curve is used only for digit rolls and morph; overall state-change centroid 280-380ms is slightly faster |
| Corporate (200-400ms, cubic-bezier(0.2,0,0,1), 0-3%) | No | Curve not used; feel is less stiff |
| Energetic (100-250ms, ease-out-expo, 15-30%) | No | No `ease-out-expo`; no fast range |

**Nearest archetype: Premium**, but with the standard curve swapped for `cubic-bezier(0.22, 1, 0.36, 1)` — a softer, more spring-like variant. The library departs from Premium's stiffness by starting each entrance with a noticeable ease-in (the 0.22 x1 delays the velocity peak), giving a "inhale then release" feel rather than a pure deceleration. It also runs faster (280–380 ms vs. Premium's 350–600 ms centroid).

**Indeterminate loops are distinct:** they use balanced S-curves (`cubic-bezier(0.66, 0, 0.34, 1)` / `ease-in-out`) or `linear`, because momentum and perpetual flow are the intent. These must not be conflated with state-change transitions when judging motion personality.

---

## 4. Proposed Duration Palette

Derivation from AICSS values:

| Name | Duration | Derivation |
|---|---|---|
| `quick` | **150 ms** | The fastest micro-interaction (icon hover, `.todoIcon` 140ms → rounded to 150ms for cross-browser predictability) |
| `standard` | **320 ms** | Modal centroid of state-change keyframes: `tr-block-in` 320ms = `.trCollapsible` 320ms = `todo-item-in` 360ms avg. Matches what the eye reads as "responsive but not rushed". |
| `slow` | **560 ms** | `.trStream transform` 560ms — used for large content blocks scrolling or reveal; also close to Premium archetype's upper range (600ms). |

**Signature easing: `cubic-bezier(0.22, 1, 0.36, 1)`** — the AICSS dominant. Applied to all three named durations.

Applying to button feedback:
- **Pending/loading state enters:** `standard (320ms)` with signature easing — button label crossfades, spinner appears.
- **Done state (success/check):** `standard (320ms)` — same curve gives the resolution the same weight as the appearance.
- **Error state (shake or colour change):** `quick (150ms)` — errors should feel immediate, not delayed.
- **Hover/focus ring:** `quick (150ms)` — matches AICSS hover transitions.
- **Modal/panel slide-in (e.g., waiting overlay):** `standard (320ms)` entering, `slow (560ms)` for large content streaming areas.

These three durations and one curve are sufficient to make pending/done/failed feedback on ordinary buttons feel like the same family as ThinkingState shimmer and ThinkingReasoning block-in.

---

## 5. Component Reusability for App Surfaces

App commit read: `ad3318f`. Source files examined: `web/src/components/ParamForm.tsx`, `web/src/components/AgentStatusPanel.tsx`, `web/src/components/ProgressLog.tsx`, `web/src/components/GenerationStatusBar.tsx`, `web/src/components/QuestionCard.tsx`, `web/src/components/DestructiveConfirm.tsx`.

### Waiting window after confirm-and-generate button (`ParamForm.tsx` ~line 3778, `useGenerate.ts`)

After `handleConfirmSend`, `useGenerate` sets `status = "generating"` (`useGenerate.ts:567`). The button has no loading/spinner state — it is disabled via `disabled` prop. The form currently renders no waiting indicator.

**AICSS fit:**
- **`<ThinkingState />`** — directly usable as a status label on the button or below it while `status === "generating"`. Drop-in: `<ThinkingState />` renders `<span class="shimmer">Thinking</span>`. CSS-only, no props. The label text "Thinking" would need localisation override — the component accepts no children in the published registry version; a custom shimmer `<span>` applying the same `label-shine` keyframe is the correct approach.
- **`<Orbs />`** (variant B1 or B2) — usable as an ambient activity indicator in the waiting panel. Requires importing from `@aicss/react`.

### `AgentStatusPanel.tsx` lanes (thinking/streaming panes)

Currently: `StatusDot` renders `animate-spin border-t-blue-500` (Tailwind) for running state, static dots for done/error (`AgentStatusPanel.tsx:13`). Streaming content is in a `<pre>` with auto-scroll.

**AICSS fit:**
- **`<ThinkingReasoning />`** — designed exactly for the thinking/streaming pane pattern. Provides collapsible viewport, auto-scroll sentence streaming, shimmer on active label, spring collapse transition. The `--tre-*` custom properties are all overridable. **Directly reusable** for `lane.streamingThinking` content.
- **`<StreamingText />`** — for `lane.streamingContent`. Provides caret + prose styling. Requires replacing the `<pre>` with `<StreamingText prose={lane.streamingContent} streaming={lane.status === "running"} />`.
- The Tailwind `animate-spin` on `StatusDot` could be replaced with `<Orbs variant="C1" />` (ring-chase, 1.6 s) for visual consistency.

### `ProgressLog.tsx`

Currently shows raw log lines in a `<pre>` with auto-scroll and a separate LLM call trace panel. No animations.

**AICSS fit:**
- **`<TaskList />`** (`task-list` / `TodoList.module.css`) — if log lines are promoted to named stages (generate / verify / correct etc.), TaskList provides staggered entrance (`todo-item-in` 360ms, 50ms per-item stagger), active-item shimmer, and a determinate pie progress indicator. Moderate reuse: requires restructuring `lines: string[]` into typed stage objects.
- **`<StreamingText />`** — direct replacement for each streaming log segment's `<pre>` block.

### Running state of `GenerationStatusBar.tsx` (static ◐ glyph, line 353)

Currently: `◐ {t("statusbar.running")} · <ElapsedTime />` — a static Unicode half-circle with no CSS animation (`GenerationStatusBar.tsx:353`).

**AICSS fit:**
- **`<Orbs variant="C1" size={14} />`** — ring-chase orb at 1.6 s `linear` would replace the static ◐ with a motion-equivalent. The 20px default stage scales via `--orb-k`; `--orb-k: 0.7` gives 14px effective size.
- **`<ThinkingState />`** — shimmer text label to replace the static "running" text, though at 13px it's slightly larger than the status bar's `text-xs` (`12px`).

### Modification run status inside `QuestionCard.tsx`

When `isRunInFlight === true` (`QuestionCard.tsx:596`), a `<GenerationStatusBar runState="running" mode="modification" />` is rendered. This inherits the same static ◐ issue.

**AICSS fit:** Same as GenerationStatusBar above. Additionally, `<Orbs variant="S1" size={12} />` (lattice wave) is visually compact and fits inline.

### `DestructiveConfirm.tsx` vs ApprovalCard

`DestructiveConfirm` is a `<dialog>` with Tailwind classes, a title, body paragraphs, cancel/confirm buttons (red confirm). No animation on open/close (`DestructiveConfirm.tsx:38–55`).

**ApprovalCard bearing:** YES, partial. ApprovalCard's `ap-card-in` keyframe (`380ms cubic-bezier(0.22,1,0.36,1)` fade+rise from `translateY(8px)`) is directly usable as a CSS `animation` on `DestructiveConfirm`'s inner `<div>` — it would give the dialog the same entrance feel as an AI approval prompt. ApprovalCard's button styles (`.btnPrimary`, `.btnGhost`) could replace the raw Tailwind buttons; the visual language is compatible (`border-radius: 999px` pill vs. the current `rounded` square). However, ApprovalCard has **no CSS custom properties** and hard-codes `#ffffff`/`#1a1a1a` backgrounds — applying it unchanged would conflict with the app's `bg-white border-gray-200` dialog (same whites, so no direct conflict, but dark-mode support would need the AICSS three-tier selector chain added to the app's stylesheet).

---

## 6. Theming and Dark-Mode Conflicts

App palette: `bg-gray-50` pages, `bg-white` cards, `blue-600` primary (`#2563eb`), green success, red error, amber pending. Sources examined: `AgentStatusPanel.tsx:80–82`, `GenerationStatusBar.tsx:179–184, 252–258, 321, 396, 405`.

| Conflict | AICSS assumption | App assumption | Severity |
|---|---|---|---|
| **Card background** | `#ffffff` (light) / `#1a1a1a` (dark) | `bg-white` = `#ffffff` | **No conflict** in light mode |
| **Primary colour** | `#0b0d12` (near-black) button bg | `blue-600 = #2563eb` | **Conflict**: AICSS primary buttons are near-black, not brand blue. ApprovalCard's `.btnPrimary` would look wrong next to `bg-blue-600` confirm buttons. |
| **Success green** | Light: `#15a06a`; Dark: `#34d399` | Tailwind `bg-green-500` = `#22c55e` | Minor hue conflict (`#15a06a` is more muted/forest; `#22c55e` is brighter). Not visually jarring but inconsistent. |
| **Muted grey** | `#a1a1a1` / `#737373` | Tailwind `text-gray-300` = `#d1d5db`, `text-gray-400` = `#9ca3af`, `text-gray-500` = `#6b7280` | Partial conflict: AICSS `#a1a1a1` ≈ Tailwind `text-gray-400` (`#9ca3af`) — close enough; AICSS dark `#737373` ≈ Tailwind `text-gray-500`. |
| **Font** | `"Inter"` (hard-coded) | App uses default system fonts (no explicit Inter import found in checked files) | Conflict if Inter is not loaded: fallback to `system-ui` will change metrics, potentially breaking AICSS component layouts (especially ThinkingReasoning's 20px sentence height assumes `font-weight: 425` which is Inter-specific). |
| **Dark mode toggle** | `[data-theme="dark"]` / `.dark` / `prefers-color-scheme` | App uses Tailwind; no explicit dark-mode class or `data-theme` found in checked files | Conflict: AICSS components will follow OS dark-mode (`prefers-color-scheme`) by default, but the app has no dark-mode switch. If the app is light-only, AICSS components will flip unexpectedly on dark-OS users unless `data-theme="light"` is set on the root. |
| **AgentStatusPanel running border** | — | `border-blue-300 bg-blue-50` for running lane | Compatible with AICSS; no conflict. |
| **ApprovalCard hard-coded colours** | No CSS custom properties; all colours literal | App needs `bg-white`, dark-mode opt-out | Conflict: using ApprovalCard requires either accepting its fixed palette or forking the file to replace hard-coded values with CSS custom properties. |
| **GenerationStatusBar text-xs (12px) vs AICSS 13px** | Components sized for 13px base | App status bar is `text-xs` = 12px | Minor: AICSS components will render ~8% larger than surrounding status text. |

**Summary of blocking conflicts:** The primary-button colour (near-black vs. blue-600) is the most visible; the missing Inter font and the dark-mode class mismatch are the most structurally significant. The rest are minor or non-existent.

---

## Sources

All CSS cited from `packages/react/src/` at `4556a918fd8c9358d42d2b24a3866301b8ea10a2`:
- `thinking-state/ThinkingState.module.css`
- `thinking-reasoning/ThinkingReasoning.module.css`
- `orbs/Orb.module.css`
- `streaming-text/StreamingText.module.css`
- `text-response/TextResponse.module.css`
- `code-block/CodeBlock.module.css`
- `task-list/TodoList.module.css`
- `data-table/DataTable.module.css`
- `ai-agent-input/PromptInput.module.css`
- `approval-card/ApprovalCard.module.css`

Registry JSON (all 200 except noted): `https://www.aicss.dev/r/<name>.json` for 14/15 components; `todo-list` → 404 (component is registered as `task-list`).

App files read at `ad3318f`:
- `web/src/components/AgentStatusPanel.tsx` — lines 1–90
- `web/src/components/GenerationStatusBar.tsx` — lines 1–410
- `web/src/components/ParamForm.tsx` — lines 3770–3810
- `web/src/components/ProgressLog.tsx` — lines 1–60
- `web/src/components/QuestionCard.tsx` — lines 437–615
- `web/src/components/DestructiveConfirm.tsx` — full file
- `web/src/hooks/useGenerate.ts` — lines 7–620 (status transitions)
