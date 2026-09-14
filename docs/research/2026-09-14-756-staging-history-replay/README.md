# #756 — staging History parameter replay acceptance

**Result: acceptance not passed.** Real staging runs reproduced two blockers:
math 題組 rendering crashes and interrupts generation; social-studies and
natural-sciences batches fail to open generation with HTTP 414. No completed
batch was produced, so completed-History reload cannot be signed off.

The math **中斷紀錄** path was tested separately: 重新帶入 made no fresh resolver
draws, preserved both saved per-question rows, and produced a second interrupted
record with exactly identical `params_json`. This is a successful parameter
comparison for interrupted records, not a substitute for the completed-record
acceptance criteria.

Issue: [#756](https://github.com/paulpengtw/exam-generation/issues/756).

## Deployment and session

- Date: 2026-09-14, Asia/Taipei. Recorded requests span 13:04–13:13;
  individual timestamps in the captures are UTC.
- Site: `https://examgen-staging.cpeng.me`.
- One ego-browser TaskSpace: **#756 staging History parameter replay**, ID **9**.
  Tabs p1/p2/p3 exercised math/social studies/natural sciences respectively.
- Authenticated using the user-provided staging sign-in link and chosen account.
  Account address, credentials, magic link, authorization headers, cookies, and
  browser storage are excluded from these artifacts. The application exposes
  an authenticated author session, not a separate supervisor-role field.
- Deployed JS: `/assets/index-Dh12gpdu.js`.
  SHA-256: `e27132d92bb165df1f5310f9b4324eb8cdc5d0f6f7ffb718f8427b0c05d05838`.
- Deployed CSS: `/assets/index-C11DTYmP.css`.
- Public `/health`: HTTP 200, `{"status":"ok"}` during this run.
- Source-inspection baseline: local `staging` at
  `bc4932a4c1117b289a6b74046ae468fdb278f72d`. The deployed commit/backend SHA
  was not exposed by the inspected site; this local SHA is **not** a claim about
  the deployed revision. The public deployed JS was inspected directly for the
  math failure.

## Test matrix and results

All three forms used `count=2`, grade 7, `sub_question_count=3`, verification
enabled, request content type 純文字, and image mode `html`. Each retained
explicit settings and left multiple applicable fields random. Counts were
pinned to keep the batch small; blank-count sampling was not exercised.

| Subject | Row seeds | Resolve | Generation | History / replay |
|---|---|---|---|---|
| 數學 | 742848790, 742848791 | 200; 15 drawn paths | 200 stream opens, then frontend crash; same crash on replay | Two interrupted records; saved parameters identical |
| 社會領域 | 1061985255, 1061985256 | 200; 37 drawn paths | 414 at stream open | No new History record; reload/repeated generation not reachable |
| 自然科學 | 1102086858, 1102086859 | 200; 29 drawn paths | 414 at stream open | No new History record; reload/repeated generation not reachable |

The captured History list at 13:13 contains only the two math interrupted
records created during the test. Existing older entries were not used to
claim that either rejected batch was persisted.

### Math settings and interrupted-record comparison

Pinned: 題組題, text_only style, easy difficulty, text word limit 200, and the
common settings above. An input displayed under 選項字數限制 was submitted by
the deployed UI as `options=["25"]`; the evidence preserves that actual wire
field and does not treat it as a numeric `option_word_limit`.

Random: contexts, question type, 學習內容, 學習表現, 數學思考, 核心素養, seeds.
The two rows had different question types and curriculum selections. Math
does not send `subquestion_configs`.

1. First interrupted record:
   [`75f85dcc-a549-4a8a-b32f-10c2c9f1e3c7`](https://examgen-staging.cpeng.me/history/75f85dcc-a549-4a8a-b32f-10c2c9f1e3c7),
   created `2026-09-14T05:06:32.162940+00:00`.
2. Opened this record through History and selected **重新帶入**. No draft-choice
   dialog appeared. Left every restored value unchanged and selected 產生.
3. Replay resolver returned `drawn=[]`, `cleared=[]`, the same seed, and the
   same two `per_question_params` rows as the saved record.
4. Submitted the confirmation. The math crash recurred.
5. Second interrupted record:
   [`5a5ab383-62f8-4457-80ba-cf4783324280`](https://examgen-staging.cpeng.me/history/5a5ab383-62f8-4457-80ba-cf4783324280),
   created `2026-09-14T05:12:31.620364+00:00`.
6. Compared complete `params_json` objects, including their serialized batch
   rows: **exactly equal**, zero differences. Neither record has a completed
   question ID (`question_id=""`).

Transport differences are retained in [comparisons.json](comparisons.json),
not hidden by a permissive comparison:

- The replay request additionally transmits persisted defaults
  `per_question_params[i].coverage_mode="balanced"` and
  `per_question_params[i].disable_reference_fewshot=false`, for both rows.
  These were absent in the first generation URL and materialized before the
  first save. The two submitted URLs are therefore **not byte-identical**.
- The replay resolver envelope omits unused/default/null top-level fields and
  represents blank top-level `context`/`q_type` as `[]` instead of saved `null`.
  The resulting second saved envelope is nevertheless exactly identical.
- The first confirmation's asynchronous core-question planner filled the
  previously empty `core_question` before submission. That value was then
  saved and restored unchanged. No original resolver-completed row value was
  removed or changed between resolution and submission.

### Social-studies settings

Pinned easy difficulty, paper surface, balanced coverage, text word limit 220,
and text instruction `請以簡短、可獨立閱讀的情境呈現，清楚區分資料與觀點。`.

For slot 1: 選擇題, question/option word limits 90/20, content type
`graphs/charts/tables`, image mode `html`, figure kind 表格, and instruction
`請根據表格中的資料判讀，避免只靠常識作答。`.
For slot 2: question word limit 110 and instruction
`請指出推論所依據的文本證據。`. Other per-slot drawable fields stayed random.

Resolved subjects were 歷史 and 公民與社會. Contexts, 內容領域, 核心素養,
group curriculum selections, per-slot 認知歷程, slot 2/3 question types, and
all six per-slot 學習內容/學習表現 rows were captured in the resolver response
and generation query. No resolved row values were lost or changed in that
transition. Their persistence/restoration remains untested because of HTTP 414.

### Natural-sciences settings

Pinned Personal / Maintenance of health (the form's defaults), text word limit
240, and text instruction
`請明確呈現觀察資料與科學解釋的差異，並使用簡短文本。`.

For slot 1: deployed type `Simple multiple-choice`, Reporting Scale 2,
question/option word limits 95/22, content type `graphs/charts/tables`, image
mode `html`, figure kind 折線圖, and instruction
`請根據圖中趨勢比較觀察結果，勿要求學生猜測未提供的數據。`.
For slot 2: question word limit 120 and instruction
`請指出證據支持的結論，並說明理由。`.

題組-level Reporting Scale stayed blank. Per-slot levels resolved to
`[2, 4, 3]` and `[2, 1b, 1b]`; only each first-slot 2 was pinned. 科學能力,
curriculum pools, slot 2/3 question types, and per-slot curriculum selections
were random. All six slot rows and the contexts/media/instruction/limit
settings reached the submitted query unchanged. Their persistence/restoration
remains untested because of HTTP 414.

## Reproducible blockers and follow-up scope

### 1. Math 題組 crashes the shared QuestionCard renderer

**Observed twice**, once from the original form and once from untouched
History reload. Both `/api/generate` requests returned HTTP 200 before the
page displayed:

```text
Unexpected Application Error!
t is not a function or its return value is not iterable
at tP (.../assets/index-Dh12gpdu.js:568:22241)
at .../assets/index-Dh12gpdu.js:568:27155
```

Reproduction: use the math settings above → 產生 → 確定發送 → wait for streamed
question rendering. The React route crashes and the stream is aborted; History
labels the run 中斷. Reload the first record without edits to reproduce.

The deployed `tP` function iterates `picker(sub)`. Its failing caller picks
`sub.科目`. Source inspection agrees: `QuestionCard.tsx` treats any nonempty
`subquestions` array as `isSocialStudies`, then aggregates `s.科目` and
`s.核心素養`; math's `SubQuestion` schema defines neither field.

Relevant source:
[QuestionCard.tsx](../../../web/src/components/QuestionCard.tsx) (lines 206,
452, 475, 479) and [src/schemas.py](../../../src/schemas.py) (math SubQuestion).
The follow-up needs subject-aware math 題組 rendering, including partial
streamed questions and completed History detail, then a real completion/reload
retest. This report makes no claim that a null fallback alone is sufficient.

### 2. Complete SS/NS batch parameters exceed the generation URL limit

For each subject, POST `/api/generate/resolve` returned 200 and populated
發送前確認. Activating 確定發送 produced:

```text
Stream open failed: HTTP 414
```

Exact captured request-target lengths (path + `?` + encoded query):

| Request | Bytes | Response |
|---|---:|---:|
| Math original | 4,521 | 200 |
| Math History replay | 4,683 | 200 |
| Social studies original | 9,489 | 414 |
| Natural sciences original | 9,354 | 414 |

Reproduction: use either subject's settings above, resolve the two-set batch,
then submit. Exact resolved payloads and ordered query pairs are in
[p2-capture.json](p2-capture.json) and [p3-capture.json](p3-capture.json).
An authenticated maintainer can reconstruct the rejected URL from `query`
without any authentication data from these artifacts.

The client serializes complete `per_question_params`, per-slot configurations,
and drawn-path provenance into GET `/api/generate`
([useGenerate.ts](../../../web/src/hooks/useGenerate.ts), `buildQueryString`).
The observed failure is at this request boundary, before a generation stream
opens. Which deployed proxy imposes the limit still requires deployment
inspection; this test did not identify that hop. The follow-up should support
complete structured batches without losing fields to URL-length constraints,
then rerun both subjects through completed History and unchanged reload.

### Ancillary UI obstruction

On the math confirmation screen, the fixed 生成進度列 covered 確定發送 at the
observed viewport. A normal ego-browser pointer click reported that a div
intercepted pointer events; `elementFromPoint` at the button returned the
progress bar's 尚未生成 span. Focusing the same button and pressing Enter
submitted it. This keyboard path was also used for subsequent confirmations.
It did not alter any parameter.

## Acceptance coverage and limits

| #756 requirement | Result |
|---|---|
| One named ego TaskSpace and chosen authenticated account | Exercised |
| Two-set batches for all subjects with random fields and explicit pins | Exercised; generation attempted for each |
| Resolver-completed and submitted parameters, including every row | Captured for all three subjects |
| Complete generation and inspect complete History records | Blocked: math renderer; SS/NS HTTP 414 |
| Reload saved complete record unchanged, choosing History over a draft if needed | Complete-record path blocked; math interrupted record tested, no draft-choice dialog |
| All applicable curriculum/context/type/count/competency/level/limit/instruction/media fields survive full round trip | Math interrupted record passes for its applicable saved fields; SS/NS only resolver→request verified |
| Complete repeated generation and compare new History parameters | Math repeated run interrupted with equal params; SS/NS unreachable |
| Distinguish older/retired fields from new-record failures | Only newly created records used; no old-record backfill or retirement behavior inferred |

No saved random parameter mismatch was observed in the one reachable History
replay. The blocking failures prevent the broader passing claim. Draft-choice,
completed-record replay, and rendered SS/NS media outputs require a new live
test after the blockers are resolved. No application code or deployment was
changed, and no completed issue status is asserted.

## Evidence and repeatable comparison

- [capture.mjs](capture.mjs): the ego-browser-injected observer used here.
  It copies only parameter/history endpoints, never auth headers or storage.
  SSE capture is selective; completion status comes from the UI and History,
  not an assumption that missing captured SSE events prove completion.
- [p1-capture.json](p1-capture.json): initial math resolve and generation query.
- [math-history-capture.json](math-history-capture.json): first saved math
  parameters, unchanged reload resolver response, and replay generation query.
- [math-replay-history.json](math-replay-history.json): second saved parameters.
- [p2-capture.json](p2-capture.json), [p3-capture.json](p3-capture.json): full
  SS/NS inputs, resolved rows, generation queries, HTTP statuses; the history
  list is restricted to records created during this test.
- `*-confirmation.txt`: sanitized semantic snapshots of 發送前確認.
- `math-*-crash.txt`, `*-original-result.txt`: observed UI failures.
- [comparisons.json](comparisons.json): exact field-addressed comparisons,
  including additions, missing keys, and envelope representation differences.

Recompute and verify the recorded observations:

```bash
python3 docs/research/2026-09-14-756-staging-history-replay/compare.py
```

A successful exit verifies these recorded observations, including the 414s and
interrupted records. It does **not** mean the live acceptance criteria passed.
