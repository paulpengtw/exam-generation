# Staging acceptance runs for #761, #822 and #825 — 2026-09-30

Four live generations on `examgen-staging.cpeng.me`, driven through the real web form in the
container Chromium (headed, Xvfb `:99`, one dedicated profile) and signed in with a
user-supplied staging sign-in link. The browser was closed and its profile deleted afterwards.
No credentials, tokens or sign-in links are in this directory.

**Model selection.** At the maintainer's instruction, all four model selectors
(規劃／出題／驗證／修正) were set to `gemini-3.1-pro-preview` for every run. The staging Anthropic
account currently returns `400 credit balance is too low`, so the default Opus plan/verify tiers
could not be exercised. Efforts were left at the advertised `high` (plan, execute); 驗證／修正
effort were left blank and followed the execute effort.

**Release under test.** Frontend asset `index-OQCnArhd.js`, build ID
`437136de3b72f55edf8820e8577c370e8e29ada3902e37f9efef167ee772d6c5`, release revision 8,
environment `staging`, admission `open`. Runs took place between 08:10 and 08:45 UTC.

Sanitized captures are in [`evidence.json`](evidence.json): submitted requests, resolver
output, per-call models and SDK parameters from the live stream, result structure, terminal
summaries, saved-exchange rows and the four math saved-parameter objects. Prompts, model
output, thinking content and images are excluded.

## Runs

| Run | Generation log | History record(s) | Stream | Outcome |
| --- | --- | --- | --- | --- |
| 自然科學 case A | `230a9ae1-17c8-40e0-8a66-a391f2ddc3f0` | `2a3b98e8-9630-4918-ae8d-bb3a08f79eb3` | HTTP 200, 608.0 s | `result` + `question_terminal` (normal, complete) + `done`; 驗證 passed |
| 自然科學 case B | `3bd26bd1-2b7f-46c7-a0e9-a40ae714f343` | `34011a67-ee03-4728-972a-112ae936d77b` | HTTP 200, 585.3 s | same; 驗證 passed on the third verification |
| 數學 original (2 題組) | `a190f825-585f-410c-89d1-97834dbeb34d` | `08ca2d94-0395-4bba-ac49-b11833739e45`, `31c6d12c-816c-4b5d-aa09-f03edffa9876` | HTTP 200, 147.4 s | 2 × `result` + terminal + `done`; both 驗證 passed |
| 數學 replay (2 題組) | `4858cd6c-b3c3-4f67-bcbc-640a2f5edb07` | `871d077f-c3d3-4507-bd8d-dfd712b30bf6`, `d5de29e2-bf4c-4fed-b23a-48cdb0615dc1` | HTTP 200, 139.1 s | same |

Every History record has `status: completed`. "Completed" and the verifier's verdict are
separate facts; here all six questions also ended with `verification.passed = true`.

## #822 — 自然科學 figures

**Case A** — 題組-level 題目內容類型 = 含圖片, 各小題配置 blank, 小題數 blank. The resolver drew
5 小題 (seed `1904016180`).

- A 題幹 figure was produced: the result carries top-level `圖片`
  `ns_230a9ae1-…_001.png`, and the terminal summary lists the stem image slot as expected and
  delivered.
- 小題 1–3 also carry figures; 小題 4–5 are 純文字. `missing` is empty.
- 小題 3 was regenerated once (a superseding operation) and recovered. No 小題 was dropped.

**Case B** — 題組-level 純文字; per-小題 content types set on three slots (含圖片,
graphs/charts/tables, 純文字); 小題數 then cleared. The resolver drew 5 小題 (seed
`1109661311`) and kept the three pinned slots in positions 1–3.

- 小題 1 (含圖片) and 小題 2 (graphs/charts/tables) each carry a figure; 小題 3–5 and the 題幹
  have none, as configured. `missing` is empty.
- The first correction was rejected with `correction_rejected` / `subquestions count changed`
  and the five-小題 structure was retained (the #806 guard). No 小題 was dropped.

**Diagnostic volume.** Staging Sentry (`exam-generation-api-staging`) has zero events for
`subquestion generation exhausted`, `Discarded natural-sciences subquestion visual
specification` and `embedded subquestion discarded`. The only traffic since deploy is these
four runs (30 小題), so this is not yet a one-day sample. The issues seen in the last 24 hours
are all the Anthropic credit failure and its planner 502.

## #825 — 數學題組 History replay

- **Original request.** 年級 8, 題目內容類型 純文字, 題型種類 題組題, 題數 2, 文本字數限制 150,
  小題數 blank; 情境, 題型, 數學思考, 學習內容, 學習表現 and 核心素養 left random. The resolver
  drew 6 and 4 小題 (seeds `753157648`, `753157649`), both in the 3–7 range.
- **Rendering.** Live updates, both final results and the batch `done` arrived with no
  rendering crash. All four History detail pages opened and rendered their 6 / 4 小題.
- **Saved parameters.** The two original records hold identical parameter objects. Against the
  submitted request they differ only by serialization defaults: added null/default keys
  (`max_retries: 3`, `coverage_mode: "balanced"`, `disable_reference_fewshot: false`,
  `core_question_callback: true`, `allow_duplicate_figure_kinds: false`, and null optionals),
  the same two defaults on each batch row, and `stream_version` stored as null. No value
  changed.
- **重新帶入.** Chosen from completed record `08ca2d94-…`; no draft-choice dialog appeared. With
  nothing edited, the resolver returned `drawn: []` and `cleared: []`. The replay request equals
  the original request except that each batch row now carries the two saved defaults
  (`coverage_mode`, `disable_reference_fewshot`). Rows, order, seeds, counts, contexts, 題型,
  style, 數學思考, 核心素養, curriculum codes, limits, media, model settings and the `drawn`
  provenance list are unchanged.
- **Replay records.** Both replay records' saved parameter objects equal the originals
  exactly.

## #761 — what these runs do and do not show

Shown, on Gemini-only selection:

- Every text call (文本生成器, 子題產生器, 驗證, 修正) used `gemini-3.1-pro-preview` with SDK
  parameters `reasoning_effort: "high"`, both in the live stream and in the saved exchanges.
- `GET /api/generation-logs/{id}/exchanges` returned HTTP 200 for all four runs after
  completion, from the History page session (16, 14, 14 and 14 rows).
- Generations completed with a final result and `done` well inside 900 s, and the resolved 小題
  structure survived correction (case B).
- `/api/models` still advertises the split defaults (plan/verify `claude-opus-4-6`/`high`,
  execute `gemini-3.1-pro-preview`/`high`, Gemini first in the roster).

Not shown:

- Anything about Opus: planner or 驗證 on `claude-opus-4-6`, adaptive thinking, thinking
  content, or `extra_body.output_config.effort`. No Anthropic call was made.
- An untouched-form run. The model selectors were changed, so the request carried all four
  model override fields.
- A planner exchange. The `batch_briefs` planner stage made no model call in any run.

## Defects found

- [#932](https://github.com/paulpengtw/exam-generation/issues/932) — every verified question
  ends with 內容版本衝突 / 結果未收到 / 審題未知 and the status bar reads 收到最終結果 0 題,
  because the post-verification `question_update` adds `verification` at an unchanged
  `content_revision`. Seen on all six questions.
- [#933](https://github.com/paulpengtw/exam-generation/issues/933) — the 核心問題 candidates
  request omits the form's 規劃模型, so it always runs on the default planner; on staging that
  is the out-of-credit Anthropic account, giving a 502 on every confirmation.
