# CLAUDE.md

## Project Overview

This is a CLI-based exam question generator for Taiwan math (default: grades 7-9, 第四學習階段), 108課綱 社會領域 (歷史/地理/公民與社會/跨科), and 108課綱 自然科學 (PISA-style scientific literacy framing). Math target 學習階段 and grade list are configurable in `question_schemas.json`. It uses LLMs via OpenAI-compatible endpoints to generate structured exam questions with optional chart/image output.

## Architecture Decisions

### No RAG
All curriculum data (學習內容.json, 學習表現.json) is injected directly into the LLM context. The full grades 1-12 curriculum is provided so the model can calibrate difficulty — understanding what students already know (grades 1-6) and what lies ahead (grades 10-12).

### Frontend motion and 操作回饋
`web/src/motion/actionFeedback.tsx` provides the single 操作回饋 primitive used by every async control; keep its pending/done/failed state model aligned with ADR 0028. Motion durations, easings, and choreography live in `web/src/motion/tokens.ts`, with matching `@theme inline` utilities; keyframes stay under `web/src/motion/`. Motion is loaded selectively through `LazyMotion`, and surface patterns follow ADR 0029.

### Script-side randomness
The resolver handles all random selection before generation (grade, 情境, 題型種類, 題型, 數學思考, 學習內容, 學習表現, 核心素養, 題目內容類型, subject_filter, question style, and per-小題 fields). Social-studies parent items are fixed as 題組題; web/API per-小題 `question_type`, `instruction`, `learning_content`, and `learning_performance` pins are carried into complete slot rows, and explicit selections are forced verbatim into the output SubQuestion. Natural sciences also resolves 情境子類別, 科學能力, and its per-小題 SubQuestionConfig rows. After each 子題產生器 response is parsed, `科目` is a 強制值: 社會領域 uses the resolved `params.科目`, while 自然科學 always uses `自然科學`, overriding any conflicting LLM value. An explicitly supplied 情境子類別 is 釘選: if 情境 is omitted its parent constrains the 情境 draw, while an explicitly incompatible 情境/情境子類別 pair is rejected during resolution. The LLM receives deterministic instructions — it does not choose these parameters itself.
For a seeded request, each drawn value uses its own `draw_rng(seed, field_path, redraws.get(field_path, 0))` stream instead of consuming a shared sequential RNG. Field paths use the serialized top-level parameter name and indexed dotted paths such as `subquestion_configs[2].question_type` for per-小題 slots; 從屬參數 resolve their parent first and then draw the child from that resolved range. `redraws` is a per-field 重抽 counter, so incrementing one path changes only that path's stream and the same seed, pins, and counters replay the same payload.
For 社會領域, 內容領域 is resolved before its dependent 學習內容 pool: 公民與社會/跨科 draw only domains with a non-empty 科目 intersection, while a pinned empty intersection is an incompatible-parent conflict rather than a redraw.

### Resolve step (ADR 0019)
`src/common/resolver.py::resolve` is the pure whole-payload seam shared by the resolve endpoint and the future `/generate` completeness gate.
Supplied values remain pins; only blank drawable fields use the seeded sampler streams, and batches resolve each row with `seed + index` unless a row pins its own seed.
Drawn and 重抽 paths use canonical sampler names: top-level fields, `per_question_params[i].<field>`, and `subquestion_configs[j].<field>`.
Incompatible parent/child pins are rejected on an initial resolve; an explicit confirmation parent redraw clears and re-resolves the incompatible child instead. Both `/generate` and `/generate/preview` rerun `resolve(payload)` at the HTTP seam and return field-addressed HTTP 422 errors whenever `drawn` is non-empty, so generation receives only a complete payload.
`/generate/preview` returns `{ prompts: PromptPreview[] }`. Each entry has `index` (0-based batch position), `system_prompt`, `user_prompt`, and — for 子題產生器 stages (社會領域, 自然科學, and 數學題組) — a zero-based `subquestion_index` (0..N-1). The SSE stream uses the same zero-based convention; the frontend adds +1 to render display labels 第1小題..第N小題. Flat (單一題) math produces no `subquestion_index` entries.
The optional math `math_thinking` request field is resolved from the same keyed sampler stream, while `core_competency` is resolved for math and social-studies requests when blank.
Resolved values are forwarded unchanged through the web confirmation payload and `/generate`; neither field has a form control or a browser-side draw.
Math and social-studies prompt builders therefore receive the resolver's pinned competency list, and math receives its pinned `math_thinking` list, as the only values offered to the model.
The three CLI entry points expose a client-free `resolve` subcommand with the same subject-specific pin flags as `generate`; it prints `{payload, drawn}` JSON and reports resolver conflicts on stderr with a non-zero exit.
Each CLI's `generate` path builds a partial GenerateParams-style payload, resolves and prints one record per question before generation, and passes the completed values directly to the subject pipeline without another sampler call.
Seeded batches resolve each question independently with `seed + index`, so repeated CLI runs with the same pins replay the printed payloads.
Supplying 內容領域 is a pin and does not consume its keyed sampler stream; a blank value is resolved per 題組 and carried into the submitted `per_question_params` rows.
For 社會領域 and 自然科學, a blank `sub_question_count` is resolved on the keyed `sub_question_count` stream in the 3–7 range and materializes exactly that many fully resolved `subquestion_configs`; a supplied count remains a pin. A count redraw uses the prior `drawn` paths to reopen only auto-drawn slot fields, preserving user pins while growth adds resolved rows and shrinking drops the tail.

### Batch-level prompt dedup (issue #111)

When a batch generates `count > 1` questions, each subject's batch loop accumulates a `list[PriorScope]` of already-accepted siblings (`{核心問題 | 出題概念, 學習內容 codes}`) and passes it to the next question's user prompt via a new optional `prior_scopes` keyword on `build_user_prompt` (math) / `build_text_user_prompt` (社會/自然). The LLM sees a short `## 已生成題目（請避免相似範圍）` block listing up to the 10 most recent siblings so it varies angle/題材 even when learning-content codes overlap. Empty list → section omitted → count=1 prompts are byte-identical to today. Extractor helpers and formatter live in `src/common/batch_dedup.py`. The server's `generate_question_stream` shares one `threading.Lock`-guarded list across concurrent workers — best-effort dedup consistent with the concurrent worker design. Embedding-similarity retry (Phase 2) is out of scope.

### Web confirmation dialog pre-draw
When the user submits the web form, it sends the partial payload (including
pins, history rows, and `redraws`) to `POST /api/generate/resolve`. The
confirmation screen is populated only from the resolver's completed
`{payload, drawn, cleared}` response; the browser performs no random draw and does not
filter a 全域池 for drawing. `drawn` paths drive 隨機 badges and are carried in
the final generation payload so they are persisted in `params_json`.
Confirmation value rows use the generic `DrawnValueRows` renderer: a canonical
field path is matched to a label-map entry, read from the completed payload,
and rendered with its drawn/pinned badge. This applies to both 題組-level and
per-小題 paths, while an existing editable control can provide the value slot
without taking over path or badge handling. Adding another drawable field
therefore requires only its label-map entry on the client; the resolver remains
the source of the displayed value.

Every resolver-drawn confirmation row offers 編輯 and 重抽; editing pins the selected value in the confirmation payload without changing the form state. Editing 情境, 科目/內容領域, or 小題數 clears only drawn descendants before resubmitting, preserves pinned descendants that still fit, and leaves the seed unchanged. If a pinned descendant no longer fits, the resolver clears and re-resolves it instead of returning 422, lists its canonical path in `cleared`, and the row shows a notice. Enumerated editors use schema options and admitted-parent filters, list editors enforce their cardinality limits, and count edits use the 3–7 slot rebuild rule.

For 社會領域 and 自然科學, the resolver also completes blank per-小題
學習內容 / 學習表現 in the existing 各小題配置 cards. A 重抽 clears only the
target field, increments its canonical path in `redraws`, and resubmits to the
resolver; the seed and sibling fields remain unchanged. A pending resolver
request shows a lightweight loading state, while a 422/5xx leaves no stale
resolved value in place and offers a retry. Regenerating an older History
record may silently resolve a field absent from that record; it receives the
隨機 badge without a separate flag or backfill of the old record.
The form's 小題數 input remains blank when the resolver supplies the count, and
the confirmation-only draw does not create a 未送出輸入 draft. Its count 重抽
clears the pending count and resubmits the existing slot rows with the incremented
keyed counter; the resolver applies the parent-edit survival rule before returning
the rebuilt list.

Natural-sciences schema payloads carry each 情境子類別's admitting values as
`admitted_by: {"情境": [...]}` while retaining the legacy `parent` field for existing consumers.
The web client uses one generic parent-keyed filter, resolves each 題組's own 情境 before drawing its 情境子類別, and keeps an explicitly pinned 情境 out of the per-題組 draw. The 發送前確認 screen lets the supervisor edit or redraw the resolved 情境 and shows its schema-filtered 情境子類別 result.

For 社會領域 and 數學, curriculum rows expose `admitted_by: {"科目": [...]}`, computed when the active curriculum is loaded from the same backend pools used for sampling; shared rows therefore follow backend admission, including runtime `SOCIAL_STUDIES_CURRICULUM_DIR` swaps. ParamForm reuses `filterEntriesByAdmittedParent` for each 題組's resolved 科目 across group and per-小題 學習內容/學習表現 pools, with no client-side prefix tables. An explicitly pinned 科目 remains in the submitted batch but suppresses the per-題組 科目 draw.
Social-studies 學習內容 rows for 公民與社會/跨科 additionally carry `admitted_by["內容領域"]` from the ICCS mapping; 歷史/地理 rows omit that key because 內容領域 is not an applicable parent for those subjects. 預抽 pool filtering and generation-time validation both read those tags through `src/common/admission.py`, never from prefixes or a separate map.

數學也 exposes request-level `sub_question_count` and the 題組文本
`text_word_limit` in the web form. For a resolved 題組題, 發送前確認 shows the
sampler-derived count as a canonical value, while math still does not submit
`subquestion_configs`.

### Workspace registry (issue #769)

`web/src/lib/workspace/workspaceStore.ts` records declared 工作區參與 and 可觀察作業, with operations begun and ended explicitly at their call sites.
Each mounted surface declares its readiness, editable state, received results and optional workspace export seam through `useSurfaceParticipation`; zero surfaces is unsafe and `isRefreshSafe` reports every blocker.
Generation and 人工審題修正 expose 受理 beside their existing `status`, acknowledged by the SSE `started` event or a returned `run_id`, while guards and 發送前確認 timing remain unchanged.
The store never receives an AbortController, promise or callback that can cancel work; see [ADR 0030](docs/adr/0030-workspace-participation-is-declared-by-each-surface.md) when extending participation, observed operations or admission for the updater.

### Release version detection (issue #770)

`web/buildIdentity.ts` computes a deterministic build ID (SHA-256 over commit + canonical public VITE_* config) and emits two static assets at build time:
- `dist/build-meta.json` (`exam-generation.build-meta/1`) — build provenance.
- `dist/release/policy.json` (`exam-generation.release-policy/1`) — deterministic authority fixture (starts as `admission: 'open'`, `released_build_id` = this artifact's id).

`web/src/lib/release/releaseStore.ts` is a zustand store that polls `GET /release/policy.json` (cache: no-store, 5 s timeout, coalesced) and sets one of: `checking | current | update-required | paused | unavailable`. A previously known update requirement is sticky — it survives transient failures. `web/src/lib/release/useReleaseStatus.ts` installs the event-driven triggers (pageshow, popstate, online, visibilitychange, 60 s interval gated by visibility).

`web/src/components/ReleaseNotice.tsx` is a persistent bar (mounted in `RootLayout` under `StagingBanner`) that shows the localized state. `checking/current/unavailable` → `role=status`; `update-required/paused` → `role=alert`. A "重新檢查 / Check again" button calls `checkNow()`. Focus is never moved by state changes. Reduced-motion is respected.

The store never calls `location.reload`, never touches workspace operations, and never submits anything. Generation enforcement (#771), save-and-update (#772+), and scheduling (#777) remain separate tickets; the live controller integration is described below.

Production builds require a commit SHA (`RAILWAY_GIT_COMMIT_SHA`, `RENDER_GIT_COMMIT`, or `GIT_COMMIT_SHA`) or an explicit `BUILD_ID`; a placeholder commit throws at build time. See `docs/research/2026-09-15-770-release-detection.md`.

The `environment` field in both emitted files comes from `VITE_ENVIRONMENT` (build arg forwarded by `web/Dockerfile`) or falls back to the Vite mode when that variable is absent or empty (issue #892). Staging deployments must set `VITE_ENVIRONMENT=staging` as a Railway build variable on the frontend service so the bundle declares `environment: "staging"`. Three settings must flip together for staging generation to pass preflight: (1) `VITE_ENVIRONMENT=staging` on the frontend build, (2) `RELEASE_ENVIRONMENT=staging` on the backend, (3) `environment: "staging"` in the gateway policy record. See DEPLOYMENT.md § "Staging environment name — coordinated switch-over" for the full operator runbook.

### Build admission (issue #771)

Every `GET` and `POST /api/generate` request must carry an `X-Frontend-Build-ID` header whose value equals the authority fixture's `released_build_id`.

`server/generate/release_authority.py` provides async `LiveControllerAuthoritySource`, `HttpAuthoritySource`, and `FileAuthoritySource` implementations plus the injectable `AuthoritySource` seam. `RELEASE_AUTHORITY_URL` is preferred; otherwise `RELEASE_AUTHORITY_PATH` is used; with neither configured, the source is absent and generation fails closed with retryable 503 `AUTHORITY_UNAVAILABLE`. HTTP reads are bounded to 2 seconds and every request reads afresh — there is no positive process-local cache. `check_build_admission(header, source) → JSONResponse | None` returns 426 `CLIENT_UPDATE_REQUIRED` (missing/outdated build) or 503 `AUTHORITY_UNAVAILABLE`/`SERVICE_PAUSED` (source unreachable or paused), and `None` on pass. Check order: FastAPI `get_current_user` (auth) → `stream_version` 426 → build-ID 426/503 → `_check_generation_admission` (model/effort/provider). The source is built once in FastAPI app state and deployments must point it at the gateway/controller policy route.

`web/src/hooks/useGenerate.ts`: preflight `await useReleaseStore.getState().checkNow()` before each `fetchEventSource` call; `X-Frontend-Build-ID: __BUILD_ID__` header on the stream request; `setResults([])` / `setEvidence(null)` moved to the `started` event handler so previous output is preserved on pre-stream errors (426/503/timeout).

Preview, resolve, history, modification API, and CLI pipeline are excluded.

### Live release controller (issue #778)

`gateway/release_controller.py` extends the existing `admission.json` gate with the `exam-generation.release-policy/1` contract: environment, increasing release revision, released build, `open|paused|preparing` admission, recovery formats, reader metadata, and current/prepared-rollback/transition artifacts. `gateway/app.py` serves `/release/policy.json` and `/build-meta.json` from that same record, gates both generation spellings before proxy dispatch, and counts pending admissions through response delivery. It never keeps a positive policy cache. Target publication requires fresh positive #741 drain evidence (all inventory instances and gauges, including pending admissions) plus matching metadata from every serving route; publication leaves admission paused. Application rollback cannot reopen the gateway volume. Use `scripts/release_admission_rehearsal.py` and the committed evidence under `docs/research/2026-09-17-778-release-admission/` for the controlled two-instance checkpoint.

Follow mode (issue #922) adds a narrow exception for staging: `POST /gateway/release/follow`
(enabled when `GATEWAY_FOLLOW_FRONTEND=1` on the gateway) atomically advances
`released_build_id` and `release_revision` without drain or route evidence.  The frontend
nginx entrypoint hook `web/docker-entrypoint.d/50-follow-release.sh` posts the bundle's
`build_id` on every container start, so each staging deploy automatically updates the
gateway policy.  Production does not set `GATEWAY_FOLLOW_FRONTEND`.

### Evidence profiles (issue #739)

`web/src/lib/runEvidence.ts` defines the `generate-legacy`, `modification`, and reserved `generate-v2` profiles. The shared status bar on GeneratePage and inside QuestionCard consumes a profile-tagged evidence object. `generationStream.ts` projects legacy stage events and the five generation card fields; `modificationStream.ts` projects modification steps and decodes its existing SSE events. Modification never requires a generation manifest. `generate-v2` is the generation-only entry point for OpenSpec `per-question-live-progress` (issue #742). The frontend decoder (`createGenerationStreamDecoder` in `generationStream.ts`) routes v2 SSE events through the `RunEvidenceState` reducer (`generationEvidence.ts`), which tracks per-question processing, content receipt, terminal status, and review. `GenerationStatusBar` renders a live 已結束/收到最終結果 counts line; `QuestionCard` renders a compact placeholder when `content.receipt === 'none'` and an evidence status line when content is available. `GeneratePage` renders cards in manifest order with live placeholders. HistoryDetail retains its stored-record card props.

### Live SSE endpoint (issue #909)

`GET /api/runs/{id}/events` is an optional in-process SSE endpoint that streams raw generation events to authenticated owners while a run is executing. It is available only when the run is live in the current host process (`is_live_available(run_id)` returns `True`). The endpoint uses `subscribe_live` / `unsubscribe_live` / `_publish_live` from `server/generate/run.py`, which maintain a per-run `asyncio.Queue` registry. `execute_run` initialises the run's observer slot before the main event loop, publishes each event after `recorder.observe`, and emits a `{"event": "done"}` sentinel plus cleans up the slot in its `finally` block. `GET /api/runs/{id}` includes `live_events_available: true` in its response body when the run's slot exists in the in-process observer registry (regardless of observer count), so clients can discover availability. `RunSnapshot.live_events_available?: boolean` carries this flag to the frontend. `pollReadFailed: boolean` in `UseGenerateReturn` is `true` when three or more consecutive poll attempts fail transiently, letting the UI display `generate.run_read_unavailable` while the server-side run continues uninterrupted.

**Frontend live consumer (`openLiveStream` in `useGenerate.ts`).** The stream is opened only when a polled snapshot advertises `live_events_available: true` and no stream is already open or has previously ended for that run. The `createGenerationStreamDecoder` is pre-seeded with the accepted manifest (from the 202 response for fresh runs, or derived from the first polled snapshot for resumed runs) so late subscribers start in v2 mode without waiting for a `started` event. Every incoming message is defensively JSON-parsed before the decoder sees it: if `context.run_id` differs from the accepted run id, or if a `started` event's manifest (total, question ids) mismatches the accepted manifest, the stream is immediately aborted and marked permanently ended for that run. A stream that ends via the `done` sentinel, a non-200 `onopen`, an `onerror`, or a server-closed `onclose` is also marked permanently ended — subsequent polls advertising `live_events_available` never reopen it. Teardown is abort-only (the `AbortController` is signalled; no cancel request is sent to the server). Polling continues on its normal 3 s/15 s cadence regardless and remains the authoritative source of truth; a stream end never calls `closeRun` and never surfaces an error.

**Three-way distinction between connection-loss reducers.** `closeRun` (in `generationEvidence.ts`) is called only when the run is definitively over (terminal status received plus `done` sentinel): it sets `closed: true` and marks questions without a terminal as `processing: "unknown"`. `applyStreamLost` is called when the SSE connection drops while the run is still executing: it does NOT set `closed: true`, does NOT change `processing`, and only clears live-only `activity` indicators. `applyPollReadFailed` is called after three consecutive poll failures (transient network errors): it marks no-terminal questions as `processing: "unknown"` (idempotent) but does not set `closed: true`; a subsequent successful poll that returns a valid snapshot calls `applyRunSnapshot` which restores processing from the snapshot, clearing the "unknown" state. These three functions are intentionally distinct and must not be conflated. `tests/server/test_909_live_route.py` proves the SSE wire format carries the full `{event, context, payload}` envelope for each published generation event. The modification pipeline is unaffected: `GenerationStatusBar.test.tsx` and `QuestionCard.test.tsx` carry existing tests that render modification-profile evidence through the same shared components.

### Owner cancels a run (issue #910)

`POST /api/runs/{id}/cancel` lets the authenticated owner request cancellation of a queued or running detached run. Non-owners always receive 404 (existence-hiding; never 403).

**Backend route and flag.** `cancel_run(run_id, user_id, *, session)` in `server/generate/run.py`:
- If all question states already have a non-null `termination_reason`: returns `{cancelled: False, reason: "already_ended"}`.
- If status is `"queued"`: immediately sets status `"cancelled"` (no host in-flight); returns `{cancelled: True}`.
- If status is `"running"`: sets `cancel_requested = True` on `GenerationLog`; returns `{cancelled: True}`.
- Idempotent: a second call on an already-`cancel_requested` run returns `{cancelled: True}` again.

**Host integration.** `_heartbeat()` (in `execute_run`) checks `GenerationLog.cancel_requested` on every tick and, when `True`, calls `confirmed_cancel_event.set()`. `execute_run` checks `confirmed_cancel_event.is_set()` after the stream finishes: if set and status is not `"failed"`, it records status as `"cancelled"`. Workers that reach `confirmed_cancel_event.is_set()` before completing emit a `termination_reason="cancelled"` terminal for their question.

**Latency.** Cancel is acknowledged immediately (202 body). The run transitions to `status="cancelled"` only after the next heartbeat fires (interval ≤ 0.1 s in tests, configurable in production) or after all questions complete — whichever comes first.

**Race rule.** `_QuestionStateRecorder._record_terminal()` uses `WHERE termination_reason IS NULL` for exactly-once semantics: a normal terminal that commits first wins; a concurrent cancel terminal for the same question is silently discarded.

**Frontend cancel control.** `useGenerate` exposes `cancelRun(): Promise<boolean>` and `cancelRequested: boolean`. `GeneratePage` renders a `data-testid="cancel-run-btn"` button while `status === "generating"`. The button shows `generate.btn_cancel_pending` ("取消中…") while `cancelFeedback.state === "pending"` OR `cancelRequested` is true. Errors use `generate.cancel_error` via `useActionFeedback`. Key files: `web/src/api/client.ts` (`cancelRun`), `web/src/lib/runSnapshot.ts` (`cancel_requested?`), `web/src/i18n/messages.ts` (en-US / zh-TW strings).

**Tests.** `tests/server/test_910_cancel.py` (9 backend tests), `web/src/pages/GeneratePage.cancel.test.tsx` (5 frontend component tests).

### Admission limits and duplicate-submit protection (issue #912)

**Submission key idempotency.** Every `POST /api/generate` body must contain a `submission_key` UUID generated by the client. The client generates one key per 確定發送 press (`crypto.randomUUID()`), reuses the same key on any network-error retry, and generates a fresh key after any HTTP response (202 or 4xx). `accept_run` returns the original `AcceptedRun` (202) for repeated `(user_id, submission_key)` pairs — including when the queue is full — so retries are safe. `submission_key` is in `SERVER_ONLY_GENERATE_FIELDS` and excluded from `params_json`. A `UniqueConstraint("user_id", "submission_key")` on `generation_logs` collapses race-condition duplicates via `IntegrityError` catch.

**Queue limit.** `QUEUE_LIMIT` (env, default `5`) caps the number of simultaneously `queued` runs per teacher. A sixth submission returns HTTP 429 with `{code: "queue_limit_reached", detail: "…"}`. Duplicate-key retries bypass this check and return the original run. The check is race-safe via `SELECT count` inside the same transaction as the insert.

**Queue position.** `GET /api/runs/{id}` includes `queue_position` (0-based count of older `queued` runs ahead of this one) when status is `"queued"`. `GET /api/runs` lists all runs for the authenticated user. The frontend (`useGenerate`) exposes `queuePosition: number | null` and GeneratePage shows 「排隊中 · 前面還有 k 個」 while queued.

**Frontend 429.** Shows the localised `generate.queue_limit` message, keeps the form usable (`status = "error"`, not `"generating"`), clears `runId`, and does NOT auto-resubmit. After a 429, the submission key is refreshed so the next press is treated as a new intent.

**i18n.** `generate.queue_position` and `generate.queue_limit` are added to `web/src/i18n/messages.ts` for `en-US` and `zh-TW`.

**Key files.** `server/generate/run.py` (`accept_run`, `list_runs`), `server/generate/routes.py` (`GET /api/runs`, 429 response), `server/generate/models.py` (`submission_key` field + `SERVER_ONLY_GENERATE_FIELDS`), `web/src/hooks/useGenerate.ts` (`submissionKeyRef`, `queuePosition`), `web/src/lib/runSnapshot.ts` (`queue_position`), `web/src/pages/GeneratePage.tsx` (queue position display), `web/src/test/fakeRunServer.ts` (`dropSubmitConnection`), `tests/server/test_912_admission.py` (15 SQLite + 1 postgres test).

### 「尚未結束」 section and History nav badge (issue #913)

**HistoryPage unfinished section.** `HistoryList` polls `GET /api/runs` every 4 s when visible (20 s when hidden) and renders a `<section aria-label="尚未結束">` above the ordinary history list whenever any queued or running run exists. Each run links to `/generate/<subject>?run=<id>` (fix(913): uses `run.subject` from the list response; falls back to `/generate` when subject is null or unrecognised). Labels: `cancel_requested=true` → "取消中"; `status="running"` → "生成中"; `status="queued"` → "排隊中 · 前面還有 k 個" (k = `queue_position`). When a run ID that was active in the previous poll is gone from the active set, `loadInitial()` is called to pull that ended run into the ordinary list without a manual reload. On each successful poll the badge marker is updated to the server's newest `completed_at`, clearing the badge using server time rather than the client clock.

**History nav badge.** `useHistoryBadge(userId, disabled?)` in `web/src/lib/useHistoryBadge.ts` polls `GET /api/runs` every 30 s (60 s when hidden). `disabled=true` idles the hook (no polling, badge stays false), preventing redundant `/api/runs` requests when the badge is already being polled by another component on the same page. On first poll, `initLastSeenAt` is called with the server's newest `completed_at` so the marker is server-time-derived, not client-clock. Subsequent polls re-read the marker from localStorage so a HistoryPage visit (which updates the marker) is reflected without a hook remount. `computeBadge` uses `Date.parse()` for reliable cross-format comparison (+00:00 vs Z, microseconds vs milliseconds). `GeneratePage` mounts a red dot `aria-label="有生成已結束"` on the History button when the hook returns true. All localStorage access is wrapped in try/catch.

**Badge on other pages (issue #913 audit).** Only `GeneratePage` renders a History navigation link (the "歷史 / History" button with the badge dot). `SubjectSelectPage`, `HistoryDetail`, `LoginPage`, and `VerifyPage` do not render a History nav link and therefore do not need the badge. No new navigation links were added (conservative).

**Badge marker storage.** Key: `exam_history_last_seen_<userId>`. Updated by HistoryPage's `pollOnce` to the server's newest `completed_at` (clears the badge); initialized on first use to the same server-derived time (preventing a retroactive badge). Implemented in `web/src/lib/historyBadge.ts` (`getLastSeenAt`, `setLastSeenAt`, `initLastSeenAt`, `findNewestCompletedAt`, `computeBadge`).

**Backend addition.** `server/generate/run.py` `list_runs` return rows now include `cancel_requested: bool(log.cancel_requested)` so the frontend can show "取消中".

**list_runs cap (code-review finding #8).** `list_runs` returns all unfinished (queued/running) runs but caps ended (completed/failed/cancelled) runs at `_LIST_RUNS_ENDED_LIMIT = 20` to keep the response size bounded. Two queries are issued (unfinished + most-recent-20-ended) and the results are merged and re-sorted newest-first. Tests: `test_list_runs_caps_ended_at_20`, `test_list_runs_always_includes_unfinished` in `tests/server/test_912_admission.py`.

**i18n.** 6 new keys in both locales: `history.unfinished_title`, `history.run_running`, `history.run_cancelling`, `history.run_queued` (with `{k}` placeholder), `history.unfinished_error`, `history.badge_label`.

**Tests.** `web/src/pages/HistoryPage.unfinished.test.tsx` (5 tests: queued position, running, cancelling, hidden-section, link, transition refetch); `web/src/lib/useHistoryBadge.test.ts` (6 tests: false/true result, no userId, storage error, poll interval, tab-hidden slower interval); `web/src/i18n/messages.913-unfinished-badge.test.ts` (i18n completeness, 14 assertions). `web/src/test/fakeRunServer.ts` extended with `setRunList`, `failRunList`, `listPolls`.

**Key files.** `web/src/lib/historyBadge.ts`, `web/src/lib/useHistoryBadge.ts`, `web/src/pages/HistoryPage.tsx` (unfinished section + polling), `web/src/pages/GeneratePage.tsx` (badge on History button), `server/generate/run.py` (`cancel_requested` in list rows).

### Generation stream protocol v3 — detached runs (issue #908)

**Protocol v3 supersedes v2 on this branch (`wip/908-detached-runs`).** Clients **must** send `stream_version=3` on POST `/api/generate`; any other value (including `2` or absent) returns HTTP 426 with body `{code: "CLIENT_UPDATE_REQUIRED", supported_stream_versions: [3]}`. `stream_version` is a transport-only field excluded from `params_json`.

**Submit response.** `POST /api/generate` returns **HTTP 202** (not 200/SSE) with JSON body `{run_id, protocol_version: 3, total, questions: [{id}]}`. `run_id` equals `GenerationLog.id`. The run is queued immediately; execution happens out of band.

**Execution module (`server/generate/run.py`).** Four public functions:
- `accept_run(params, user, submission_key, *, session_factory)` → `AcceptedRun`: writes one `GenerationLog` (status `"queued"`) plus N `GenerationQuestionState` rows in one transaction; returns existing run on duplicate `submission_key`.
- `claim_next_run(session_factory, *, host_id)` → `ClaimedRun | None`: atomically claims the oldest `"queued"` run and sets it to `"running"`.
- `execute_run(claimed, *, app_state, config, session_factory, host_id)`: runs `generate_question_stream` as an in-process event bus; persists per-question state via `GenerationQuestionState`; calls `persist_failed_generation_record` post-stream on failure.
- `run_host_loop(stop_event, *, app_state, config, session_factory, host_id)`: loop that calls `claim_next_run` + `execute_run` until `stop_event` is set.

**DB models added for v3.** `GenerationLog` gains columns `heartbeat_at`, `attempts`, `claimed_by`, `started_at`, `cancel_requested`, `submission_key` (unique per user). `GenerationStatus` enum gains `queued`, `running`, `cancelled`. New table `generation_question_states` with columns `index`, `processing`, `current_step`, `termination_reason`, `terminal_json`, `generation_record_id`, `error`, `updated_at` and unique constraint `(generation_log_id, question_id)`.

**Test seam.** Tests call `_execute_run(client)` (defined in each test file) which calls `claim_next_run` + `execute_run` directly using the `transport_client` fixture's patched `AsyncSessionLocal` and the real `client.app.state`. Results are read via `GET /api/history/{id}` and `GET /api/history/{id}/detail` (DB-backed); SSE framing is no longer emitted on the wire for v3 runs.

**Removed behaviors (intentional).** Observer-disconnect-cancels-run is gone: a client disconnect never affects an in-progress run. SSE wire framing is removed from the v3 generate path; live event access is in-process only.

### Runs survive host failure — stale detection and resume (issue #911)

**Stale requeue.** A `running` run whose `heartbeat_at` is more than 3 minutes old (invariant: stale ≥ 3× heartbeat interval of 30 s) is treated as abandoned. `claim_next_run` uses a two-phase query: first a fresh `queued` run (same `~owner_is_running` filter), then a stale `running` run. The stale query does NOT apply `owner_is_running` (the stale run itself is the owner's "running" entry). Constants: `STALE_THRESHOLD_S = 180.0`, `MAX_ATTEMPTS = 3`.

**Attempt limit.** `GenerationLog.attempts` is incremented on each claim. When `claimed.attempt > MAX_ATTEMPTS`, `execute_run` skips generation, calls `recorder.fail_unfinished("recovery_exhausted")` on all still-unfinished questions, and marks the run `status="failed", error="recovery_exhausted"`. A stale run whose `attempts >= MAX_ATTEMPTS` is **finalised inside `claim_next_run`** (under FOR UPDATE SKIP LOCKED) rather than returned — this prevents the stuck-forever bug where such a run could never be reclaimed or finalized.

**2-hour time limit.** Each heartbeat checks `(now - started_at).total_seconds() >= TIME_LIMIT_S (7200)` and sets `time_limit_exceeded_event`. `execute_run` also checks at start and polls after each event. When exceeded, `_TimeLimitExceededError` is raised, unfinished questions get `fail_unfinished("time_limit")`, and the run is marked `status="failed", error="time_limit"`. Cancellation reuses the cancel flag and `termination_reason="failed"` (not `"cancelled"`). A stale run that is past the 2-hour wall-clock limit is also **finalised inside `claim_next_run`** as `time_limit` — same path as the exhausted-attempts case.

**`started_at` is set at first claim, not at submit time.** `accept_run` writes `started_at=now` as the submission timestamp used for FIFO ordering; `claim_next_run` sets it to the claim timestamp only when `attempts == 0` (first claim). This preserves FIFO order (runs submitted earlier are always claimed first) while giving the time-limit check a reference time that starts from the first actual execution attempt rather than from when the user submitted.

**Resume (skip already-ended questions).** At the start of each attempt, `execute_run` loads all `question_id` values from `GenerationQuestionState` where `termination_reason IS NOT NULL`. These are passed as `skip_question_ids: frozenset[str]` to `generate_question_stream` → `_build_run_context` → `_RunContext.skip_question_ids`. The worker-futures loop skips manifest slots whose `question_id` is in the set. No duplicate `generation_records` are created because the `(generation_log_id, question_id)` unique constraint (issue #907) prevents re-insert. `read_run` always returns the latest persisted state.

**Attempt number in trail entries.** `claimed.attempt` is threaded through `generate_question_stream(attempt=)` → `_build_run_context(attempt=)` → `make_figure_policy_trail_recorder(attempt=)` / `make_reference_example_record_recorder(attempt=)`. `_IncrementalTrailStager` tags each entry with `{"attempt": N}` when N > 1, so recovery-attempt entries are honest labelled in the trail column; first-attempt entries carry no tag and are byte-identical to pre-recovery runs (ADR 0024).

**Termination reason codes.** `recovery_exhausted` and `time_limit` are `unknown_reason` strings on a `termination_reason="failed"` terminal (produced by `_unfinished_terminal(reason)`). The frontend QuestionCard renders `card.termination_recovery_exhausted` and `card.termination_time_limit` i18n keys by inspecting `terminal.unknown_reason`.

### Generation stream protocol v2 (issue #742)

**Removed on this branch** — `SUPPORTED_STREAM_VERSIONS` now contains only `3`. The description below is retained for historical reference; the v2 SSE path no longer exists on `wip/908-detached-runs`.

The backend implemented stream protocol v2. Clients **must** send `stream_version=2` on GET/POST `/api/generate`; missing or unsupported values return HTTP 426 with body `{code: "CLIENT_UPDATE_REQUIRED", supported_stream_versions: [2]}`. `stream_version` is a transport field: it is excluded from `params_json` and from the TypeScript contract (`SERVER_ONLY_GENERATE_FIELDS`). The frontend sends `stream_version: 2` on every POST `/api/generate` request (appended by `useGenerate` in `buildQueryString` and the POST body); unsupported protocol versions abort the stream with a localized error.

**Run identity.** `run_id` = `GenerationLog.id` when available, otherwise a fresh UUID4 hex string (32 chars, from `new_run_id()`). All question IDs are allocated before workers start: `allocate_manifest(prefix, run_id, count)` returns `{prefix}{run_id}_{i+1:03d}` for each question.

**Event sequence.** One `GenerationPublisher` per run assigns monotonic `event_seq` at the `publish()` call site (thread-safe). Every emitted event is a `{event, context, payload}` triple on the wire (`event` is kept for v1 compatibility).

**question_update and result.** Both carry `context.content_revision` from the per-question `QuestionSnapshotLedger`. The ledger's `commit(question_dict, output_dir) -> (revision, snapshot)` increments the revision only when the effective content signature changes. Signature = stable JSON of the question with `verification/verification_trail/figure_policy_trail/reference_example_record/metadata/review/progress/export/_export` stripped at any depth; `image_base64` is not stripped but hashed — its decoded bytes contribute `embedded:<path>:<digest>` to the signature so real image changes still bump the revision while base64 formatting does not; plus sha256 of image files referenced by `圖片` / `subquestions[*].圖片`. Missing files contribute the literal `"missing"`. Snapshots are deep copies; the ledger is thread-safe.

**question_terminal.** One validated `QuestionTerminalPayload` is published per question at every worker exit point:
- Normal path (published AFTER the result): `termination_reason='normal'`, `has_final=True`, `final_revision` from the ledger commit on the final question. Image slots: flat questions get one `{kind:'image', question_id, subquestion_id:None}` when the adopted result has `圖片` or `chart_spec`; fixed-slot grouped questions get per-小題 `{kind:'image', question_id, subquestion_id, subquestion_index}` slots for each adopted image or explicitly visual 小題 config; selecting `image_generation_mode` alone never creates a slot. `delivery_status` = `'complete'` when `missing==[]`, `'partial'` otherwise. `review.status` = `'skipped'` when `params.skip_verify` is True; `'passed'`/`'failed'` when verification exists AND the trail's most recent verification entry has `content_revision == final_revision`; `'unknown'` with a reason otherwise.
- Exception path (published AFTER the error event): `termination_reason='failed'`; if a result was already published, `has_final=True`/`final_revision=published_revision` with `unknown_reason='terminal completion failed after final delivery'`; otherwise `has_final=False`, `delivery_status='none'`, `review.status='unknown'` with `reason='no final content'`.
- GenerationCancelled path: a cancelled terminal (`termination_reason='cancelled'`, `has_final=False`, `delivery_status='unknown'`, `unknown_reason='cancelled before completion'`) is emitted ONLY when `confirmed_cancel_event` is set internally; an ordinary client disconnect exits silently with no terminal.
- On `QuestionTerminalPayload` validation failure: logs a WARNING and falls back to a minimal `delivery_status='unknown'` terminal (never crashes the worker).
- Fixed grouped slots: SS, NS, and grouped math opt in via `SubjectGenerationSpec.fixed_subquestion_identity`; the plan event announces a zero-based manifest (`subquestion_index`, `<question_id>-sqNNN`, one-based `序號`) before any 小題 work; model-reported id/序號 never route; `expected`/`delivered`/`missing` come from the manifest (or the resolved count for pre-plan failures); flat math gets no 小題 slots.
- `SlotRef` `reason` field: present only on `missing` slots (values: `"render_failed"` / `"empty_image"` / `"spec_missing"` / `"subquestion not delivered"`); `expected` and `delivered` slots must omit `reason` entirely — never `null`. `parseSlotReferences` in the TS client rejects any slot where `reason` is present but not a string. Image delivery validation (issue #939): a rendered PNG file is only counted as delivered when its first 8 bytes equal the PNG magic signature `\x89PNG\r\n\x1a\n`; files that are empty, truncated, or contain non-PNG bytes (e.g. an HTML error page) get `reason: "empty_image"` and appear in `missing`. The check lives in `_is_valid_png_header` / `_PNG_MAGIC` in `server/generate/question_terminal.py`.

**Operation and call identity (#743).** `OperationScope`/`CallScope` in `src/common/generation_events.py` are immutable; `new_operation_scope()` / `new_call_scope()` allocate them. One `call_id` per real provider dispatch (`src/llm_client.py`). JSON resend = new call with `retry_of_call_id`, same operation; whole-slot redo = new operation with `supersedes_operation_id`. `ExchangeRecorder` pairs context-bearing exchanges by `(run_id, call_id)`; write failures are isolated and never block generation. Identity is persisted inside `request_body["identity"]` / `response_body["identity"]` (the `LLMExchange` table has no identity columns; `server/generate/persistence.py` strips the flat keys before insert). Legacy and modification exchanges keep agent-key pairing and carry no identity. Failed calls (provider exception → `llm_failure` event) write a row with `response_body["error"]` carrying normalized `ProviderErrorDetail` fields (`provider`, `model`, `http_status`, `provider_error_type`, `provider_error_code`, `provider_error_status`, `provider_message`, `request_id`, `retry_after_seconds`, `raw_body_truncated`) and `prompt_tokens`/`completion_tokens` set to `None`. When a Fable model substitution occurs (issue #942), `requested_model` is added to `llm_request`, `llm_response`, and `llm_failure` events (only when it differs from the dispatched `model`), and `ExchangeRecorder` copies it into `request_body["requested_model"]` for both successful and failed exchange rows; unsubstituted exchanges carry no such key.

**SSE error event `failure_class` (issue #946).** Every SSE `error` event payload (`{code, message}`) now also carries an optional `failure_class` string from the 10-code taxonomy (`auth_config`, `quota_billing_exhausted`, `rate_limited`, `overloaded`, `timeout`, `connection`, `context_length`, `content_filtered`, `malformed_response`, `unknown`). `classify_provider_error(exc, detail) -> str` in `src/llm_client.py` maps any caught exception to exactly one taxonomy code and is called at all five SSE error-emission sites (per-question worker, batch-planner, stream-failed, modification-failed). `build_sse_error` in `server/generate/models.py` accepts optional kwargs `failure_class`, `provider`, `model`, `tier`, `retry_after_seconds`; absent kwargs are omitted from the emitted dict. `parseErrorPayload` in `web/src/hooks/useGenerate.ts` extracts `failure_class` from the SSE payload; the `case "error"` handlers (both v2 and legacy) compute a pre-localized message using `MESSAGES[lang]["error.class.<code>"]` + `"\n"` + `MESSAGES[lang]["error.class_hint.<code>"]` when the code is recognized, then fall back to the raw `message` field. `ProgressLog` receives the pre-localized string and renders it in a `<div role="alert">` (not a `<pre>`). `ApiError.failureClass` carries the code from HTTP non-stream error bodies (e.g. 502 from `/api/plan-core-questions`); `CoreQuestionPicker` re-throws `ActionFailure` with the localized label when the code is recognized. Already-received draft content is preserved on error (#938): `setResults([])` runs only on the `started` event, not on pre-stream errors.

**Sibling independence and sealing (#747).** One question's failure never stops sibling workers; only batch-planner failure is batch-fatal. The publisher seals each question at its `question_terminal`; an identical `question_terminal` resend is accepted idempotently (via `setdefault`), while a contradictory one raises `QuestionTerminalConflictError`; afterwards only the declared final `result` at `final_revision` is accepted — any other event raises `QuestionSealedError`. `done` is emitted only after all workers finish and recorders flush.

**Key files.**
- `src/common/generation_events.py`: `RunContext`, `QuestionContext`, `new_run_id()`, `allocate_manifest()`.
- `server/generate/event_protocol.py`: `PROTOCOL_VERSION=2`, `EventContext`, `StartedPayload`, `QuestionTerminalPayload`, `SlotRef`, `envelope_dict()`; `StartedPayload` (validated before emission in `service.py`, issue #855; `generation_log_id` is an explicitly declared optional field: `str` with a log, `null` on the direct seam).
- `server/generate/publisher.py`: `GenerationPublisher` — thread-safe monotonic `event_seq`, `loop.call_soon_threadsafe`.
- `server/generate/snapshot_ledger.py`: `QuestionSnapshotLedger.commit(question_dict, output_dir)` → `(revision, snapshot)`.
- `server/generate/service.py`: `_build_question_terminal_payload()` (thin composition point), `_worker_one` wiring; per-question worker is split into three phases: `_setup_worker_recorders()` (recorder + observer + trail-capture setup, testable without generation), generation execution, and `_finalize_worker_terminal()` (shared finalize path for all five terminal exits: normal, final-failure, confirmed-cancellation, resend-of-sealed, batch-planning-failure, worker-unexpected-exit; issue #858).
- `server/generate/question_terminal.py`: `_QuestionPositionResolution`, `_compute_review`, `_compute_expected_delivered_missing`, `_compute_delivery_status` (independently testable units; issue #857).
- `web/src/lib/generationStream.ts`: `createGenerationStreamDecoder()` — state machine (`awaiting-start` → `v2`/`legacy`/`unsupported`); `projectGenerationEvidence()` accepts optional `RunEvidenceState` and returns `GenerationV2Evidence`.
- `web/src/lib/generationEvidence.ts`: `RunEvidenceState` reducer — `createRunEvidence`, `applyV2Event`, `closeRun`, `selectEndedCount`, `selectFinalReceivedCount`.
- `web/src/hooks/useGenerate.ts`: sends `stream_version: 2`; routes events through decoder; builds `RunEvidenceState` from `started` manifest; exposes `evidence: RunEvidenceState | null`.
- `web/src/components/GenerationStatusBar.tsx`: `GenerationV2StatusLine` for live ended/final counts.
- `web/src/components/QuestionCard.tsx`: `EvidenceStatusLine`; placeholder branch for `content.receipt === 'none'`.
- `server/generate/exchange_recorder.py`: `ExchangeRecorder` — pairs context-bearing exchanges by `(run_id, call_id)`; write failures are isolated.
- `src/common/subject_spec.py`: `SubjectGenerationSpec.fixed_subquestion_identity`.

**Fixtures** in `tests/fixtures/generation_v2/`: `math_single_interleaved.jsonl` (`GENERATE_V2_FIXTURE=1 uv run pytest tests/server/test_742_fixture.py::test_interleaved_fixture`); `social_groups_interleaved.jsonl` (`…test_744_social_fixture.py::test_social_fixed_slot_fixture_and_terminal`); `natural_sciences_groups_interleaved.jsonl` (`…test_745_adapter_fixtures.py::test_fixed_adapter_fixture_and_terminal[natural_sciences]`); `math_groups_interleaved.jsonl` (`…test_745_adapter_fixtures.py::test_fixed_adapter_fixture_and_terminal[math]`); `math_abcd_transport.jsonl` (`GENERATE_747_FIXTURE=1 uv run pytest tests/server/test_747_abcd_fixture.py::test_real_publisher_fixture_captures_transport_omitted_terminal`); `ns_six_slot_visual.jsonl` (issue #939 — six-slot NS run, slots 1/2/4/6 delivered, slot 3 `render_failed`, slot 5 `empty_image`; driven by `web/src/lib/generationStream.939visualObligations.test.ts`).

### Seq dedup and bounded buffer (issue #748)

`createGenerationStreamDecoder(options?: { clock?: DecoderClock })` now maintains per-event-seq dedup and a bounded out-of-order buffer in v2 mode. Seqs already processed are tracked in a compact fingerprint set (`seqSeen`); a duplicate seq returns `{ kind: "ignore", reason: "duplicate_seq" }` and does NOT inflate the pending buffer. Out-of-order events (seq > nextExpected) are held in `seqPending` until the gap is filled or a bound is hit. Unknown event names in valid v2 envelopes are accepted and occupy their seq slot — no permanent gap. Pending byte size is measured with `TextEncoder` (UTF-8), not `rawData.length` (UTF-16). Bounds: 2 s, 256 pending events, or 4 MiB pending data (whichever hits first); `done`/EOF with an open gap also degrades immediately. On degradation the decoder emits `{ kind: "degraded"; reason: "timeout" | "count" | "size" | "eof_gap" }` followed by any buffered `question_update`/`result`/`question_terminal` events (flushed in seq order); activity-only events (`stage`, `llm_*`, `pipeline`) in the buffer are silently dropped. The decoder also exposes `checkDeadline(): DecodedEvent[]` for timer-driven degradation: if the gap is still open when the timer fires (no new events filled it), this method checks the clock and degrades + flushes the same way. The decoder additionally exposes `msUntilDeadline(): number | null` — returns the remaining milliseconds until the gap deadline, or null when no gap is open (or degraded). `useGenerate` arms a named `fireGapTimer` callback on the first `held` event in v2 mode; after a non-degrading `checkDeadline()` call, if `decoder.msUntilDeadline() !== null` the callback re-arms itself for the remaining time, ensuring a gap 2 that opens after gap 1 fills before the timer fires also expires correctly. The timer is cleared on stream completion, error, or teardown. `RunEvidenceState.degraded` is set by `applyDegraded(state, reason)` exported from `generationEvidence.ts`; when true, `applyV2Event` skips activity-only event processing. `GenerationV2Evidence.degraded` (projected via `projectGenerationEvidence`) drives the `data-testid="statusbar-v2-degraded"` amber notice rendered by `GenerationV2StatusLine`. The injectable `DecoderClock` is used only in tests; production uses `Date.now()`.

### Conflict isolation (issue #749)

`DecodedEvent` gained two new variants emitted by `createGenerationStreamDecoder`: `{ kind: "conflict"; conflictType: "seq_data"; seq: number; eventName: string; questionId: string | null }` and `{ kind: "conflict"; conflictType: "legacy_in_v2" }`. Fingerprinting: `seqFingerprints: Map<number, string>` stores the raw data string for every seq added to `seqSeen`; when a duplicate seq arrives with different raw data a `seq_data` conflict is emitted rather than `duplicate_seq` ignore. `questionId` in the conflict event is extracted from the new event's context (or `null` when absent). Raw legacy events (JSON objects without a `context` key) produce `legacy_in_v2`; the decoder stays in v2 mode.

`RunEvidenceState` gained `batchConflict: boolean`, `batchConflictReason: string | null`, and `legacyMixed: boolean`. `QuestionEvidence` gained `contentConflict?: boolean` and `contentConflictReason?: string`. `applyConflictEvent` (unexported) handles all `{ kind: "conflict" }` events before the v2-only gate in `applyV2Event`: `seq_data` with a known question routes to `terminalConflict` (for `question_terminal` events) or `contentConflict` (for `result`/`question_update`); activity-event seq conflicts produce no question-level effect; unknown or absent questionId sets `batchConflict`. `legacy_in_v2` sets only `legacyMixed`. The `question_update` handler detects same-draft-revision-different-content (only when `receipt === "draft"`) and the `result` handler detects same-final-revision-different-content (only when `receipt === "final"`). Both also check manifest/payload identity (`payload.id` vs `context.question_id`). A `result` arriving at the same `content_revision` as a prior `question_update` draft is checked: `questionContentFingerprint` normalises both by recursively stripping all 10 sidecar fields (`verification`, `verification_trail`, `figure_policy_trail`, `reference_example_record`, `image_base64`, `metadata`, `review`, `progress`, `export`, `_export`) at every depth before comparing (issue #932; the server uses the same key set via `CONTENT_SIGNATURE_EXCLUDED_KEYS` in `src/common/generation_events.py`; the shared ground truth lives in `contracts/content-sidecar-keys.json`). `CONTENT_SIDECAR_FIELDS` is now exported from `generationEvidence.ts`; the `stripSidecarFields` helper is module-private. Identical normalised content → intentional finalisation, adopted as final; different normalised content → `same_revision_different_content` conflict, draft body kept. `selectConflictCount(state)` counts questions with any active conflict flag. `GenerationV2Evidence` gained `conflictCount: number`, `batchConflict: boolean`, `legacyMixed: boolean` (projected via `projectGenerationEvidence`). `GenerationV2StatusLine` renders `data-testid="statusbar-v2-batch-conflict"` and `data-testid="statusbar-v2-legacy-mixed"` amber notices (`role="status"`). `QuestionCard` renders conflict notices with `role="status"` and a `data-testid="evidence-*-conflict-reason"` child showing the specific localized reason code (`card.conflict_reason_<code>`). Reason codes (not English prose): `seq_data`, `same_revision_different_content`, `identity_mismatch`, `terminal_contradiction`, `terminal_invalid`, `review_contradiction`. Both en-US and zh-TW translations are present in `web/src/i18n/messages.ts`.

Key invariants: only terminal disputes set `processing = "unknown"` and reduce `endedCount` (X); content conflicts do not affect X; `batchConflict` does not erase already-confirmed terminals; `legacyMixed` does not affect any evidence conclusions; after permanent degradation `result`/`question_terminal` events still accepted; no auto-resubmit or modification eligibility change.

### Legacy stream adapter (issue #750)

C1×S0 compatibility: a new client (C1) accidentally receiving a stream from an old server (S0) now routes all legacy-mode events through a dedicated state machine (`web/src/lib/legacyAdapter.ts`) that preserves the batch with degraded display instead of applying the C0/S0 arrival-order indexing bug.

**Documented C0/S0 defects NOT fixed here (unfixed old clients remain C0):**
- C0 assigns index by arrival order of `result` events (`nextFinalIndexRef.current++`)
- C0 does not deduplicate duplicate result events
- C0 does not track consistent index↔id mappings
- C0 may let a later result overwrite an earlier draft at the same position

**Adapter rules (C1×S0):**
- `LegacyAdapterState`: items keyed by opaque id (`stable_id` → `question_id` → `question.id` → synthetic); consistent explicit `index↔id` evidence resolves original position; arrival order never substitutes.
- `resolvedIndex: number | null`: `null` → 原題序未知; consistent explicit mapping required to set it.
- Inconsistent mapping (same id → different index, or same index → different id): silently rejected; item stays at 原題序未知.
- Duplicate final (same id, already `isFinal`): silently ignored.
- `done` sets `done: true` only; NOT per-question terminal evidence.
- Events after `done` are silently discarded (stream is sealed).
- Late consistent mapping: a `question_update` arriving after a `result` with the same id can still resolve `resolvedIndex`.

**Evidence profile:** Adapter data is embedded as optional `legacyAdapter?: { requestTotal, finalCount, done }` in the existing `generate-legacy` profile (`GenerationLegacyEvidence` in `runEvidence.ts`). No separate `generate-legacy-adapter` profile — the union stays minimal. `projectGenerationEvidence` in `generationStream.ts` accepts an optional `legacyAdapter?: LegacyAdapterState | null` fourth parameter and populates `GenerationLegacyEvidence.legacyAdapter` when the adapter is active.

**Fixture format (sha 35a7219):** `started.data` = `{"generation_log_id": null}` (JSON object, not empty string); `question_update.data` = `{"index": int, "phase": str, "question": {..., "id": str}}`; `result.data` = direct question object (no wrapper). `done.data` = `""`. Route `_serialize_event()` in `routes.py` only serializes `event` + `data`; verification_trail etc. come in separate `trail` events.

**Always-adapter:** The legacy adapter is initialized at `generate()` start (not just on `started`), so pre-started held events also route through it. The "started" handler re-initializes with the server-confirmed count. C0 arrival-order fallback (`nextFinalIndexRef`) is permanently removed from `question_update` and `result` handlers.

**UI treatment:** `GenerationLegacyAdapterStatusLine` in `GenerationStatusBar.tsx` shows "此批無每題即時進度" notice and "請求總數 N" (from `requestTotal`, not a manifest count), rendered when `evidence.profile === "generate-legacy" && evidence.legacyAdapter != null`. Items with `positionUnknown: true` on `GeneratedQuestion` render "原題序未知" in `QuestionCard` via a `data-testid="question-card-position-unknown"` badge. No placeholder cards are built (no pre-allocated manifest slots); `selectLegacyItems` returns only items with received content.

**Modification flow unchanged:** The adapter state lives in legacy mode only; the modification flow never touches it. No auto-resubmit, no modification eligibility change.

Key files:
- `web/src/lib/legacyAdapter.ts`: `LegacyItem`, `LegacyAdapterState`, `createLegacyAdapter`, `applyLegacyEvent`, `selectLegacyItems`.
- `web/src/lib/legacyAdapter.test.ts`: TDD unit tests for all adapter rules (18 tests).
- `tests/fixtures/generation_legacy/math_single_legacy.jsonl`: two-question legacy stream fixture derived from pre-v2 server format (sha 35a7219); `started.data` = `{"generation_log_id": null}`.
- `web/src/hooks/useGenerate.ts`: adapter initialized at `generate()` start; `question_update`/`result` always route through adapter; `legacyAdapter: LegacyAdapterState | null` exposed in `UseGenerateReturn`; `nextFinalIndexRef` removed.
- `web/src/i18n/messages.ts`: `stream.legacy_no_per_question_progress`, `card.position_unknown`, `statusbar.legacy_request_total` in both `en-US` and `zh-TW`.

### Snapshot export — JSON (issue #751)

`web/src/utils/exportSnapshot.ts` (capability `question-snapshot-export`) provides atomic, click-time snapshots for single-question, batch, and history JSON downloads. All three surfaces share the same immutable snapshot contract.

**`_export` schema (format_version: 1, `exam-generation.question-snapshot-export/1`):**
- `format_version: 1` — always 1 for this revision.
- `exported_at` — ISO 8601 UTC timestamp frozen at click time; identical for all items in a batch.
- `is_draft: boolean` — true when `content.receipt === "draft"` (v2 evidence) or `isFinal === false` (legacy item). A final with unknown terminal stays `is_draft: false`.
- `run_id: string | null` — v2 protocol run id from `RunEvidenceState.runId` (= `context.run_id` in the started event); null for legacy cards. History records use `detail.generation_log_id` (equals the v2 run_id for persisted records). NOT the DB `GenerationLog.id` (`generationLogId`) — those happen to be equal when a log exists, but are semantically distinct.
- `index: number | null` — 0-based original batch position; null for unknown-order legacy items.
- `content_revision: number | null` — content version from evidence; null for legacy/history.
- `processing` — `"waiting" | "running" | "ended" | "unknown"`.
- `termination_reason` — from terminal payload; null when no terminal received.
- `delivery_status` — from terminal payload; null when no terminal received.
- `missing: GenerationSlotReference[]` — from terminal.missing; empty when unknown.
- `review.status` — matched to the current content_revision; `"unknown"` with `unknown_reason: "review_revision_mismatch"` when revision doesn't match.

**Capture rules:**
- Bodyless placeholders (`receipt === "none"`) are excluded from batch exports.
- Batch ordering: by known index ascending; `positionUnknown` items sort last, stable by original array order.
- `stripExport(exported)` removes `_export` and restores the original captured question.
- Live/stored questions are never mutated.
- History records always get `is_draft: false`, `processing: "ended"`, `termination_reason: "normal"`, `delivery_status: "complete"`.

**Visible image sources (`QuestionSnapshot.imageSources`):**
Each snapshot holds a `CapturedImageSources` record (lives on `QuestionSnapshot` only, NOT in the downloaded JSON body) capturing what was visible at click time:
- Keys: `"stem"` for the top-level question image, `"sq{序號}"` (1-based) for per-subquestion images.
- Source priority per slot: `image_base64` → `"png_base64"` (with `pngBase64` field); slot in `terminal.missing` for `kind="image"` → `"known_missing"` (issue #939 — checked before `chart_spec` so a render-failed slot whose spec is still present is correctly shown as missing, not as a re-renderable preview); `chart_spec` (no image_base64 and not in missing) → `"chart_spec_preview"` (with `chartSpec` field); none → slot absent from record.
- Each source has `contentRevision: number | null` binding it to the snapshot's content revision.
- Sources are captured AFTER `captureQuestion()` deep-copy so later mutations never affect them.
- Consumed by #752 (ODT export) and #753 (rasterization); do NOT appear in JSON downloads.

**Filename conventions:**
- Single draft: `草稿_{questionId}.json`
- Single final: `{questionId}.json`
- Batch with any draft: `含草稿_batch_{timestamp}.json`
- Batch all final: `batch_{timestamp}.json`

**Component wiring:**
- `QuestionCard`: `runId` prop added; JSON export enabled for drafts (shows "Download Draft JSON"); uses `captureFromEvidence` (v2) or `captureFromGeneratedQuestion` (legacy/history) for the snapshot.
- `GeneratePage`: batch JSON export uses `captureBatch` with `runId: runEvidence?.runId ?? null`; v2 QuestionCards receive `runId={runEvidence?.runId ?? null}`; legacy QuestionCards receive `runId={null}` (never the DB log id).
- `HistoryDetail`: JSON download uses `captureFromHistory` when `detail.question_json` is present; falls back to server endpoint only when `question_json` is null.
- `HistoryDetail` evidence (issue #939): `GET /api/generation-logs/{id}` now returns a typed `terminal_delivery: HistoryTerminalDelivery | null` field (extracted from `annotations_json` server-side by `_extract_terminal_delivery()` in `server/history/routes.py`). `HistoryTerminalDelivery` is declared in `web/src/api/client.ts` with `expected`, `delivered`, `missing` slot arrays. `buildHistoryEvidence(questionId, terminalDelivery)` in `HistoryDetail.tsx` constructs a synthetic `QuestionEvidence` that lets `QuestionCard` show missing-slot markers for partial deliveries. The raw `annotations_json` field is no longer exposed in the TypeScript API contract.

**Key files:** `web/src/utils/exportSnapshot.ts`, `web/src/utils/exportSnapshot.test.ts`.

### Snapshot export — ODT (issue #752)

> **Full ODT contract met as of issue #753 (re-implemented).** chart_spec_preview slots are rasterized via `defaultRasterizer` using DOM capture + SVG foreignObject with data: URL (same-source: uses what FigureRenderer actually renders; injectable for testing). Per-image conversion failure emits 「匯出缺圖／預覽轉換失敗」 at the slot position; other content is preserved. Whole-ZIP failure throws `OdtBuildError`; no broken file is produced. Retry reuses the last captured snapshot.

`web/src/utils/odt.ts` exports `buildOdtFromSnapshots(title, snapshots)` which consumes the same frozen `QuestionSnapshot[]` produced by `exportSnapshot.ts`.

`buildOdtFromBatch` was removed (review). All callers must use `captureBatchSnapshots` (from `exportSnapshot.ts`) + `buildOdtFromSnapshots` directly, so image sources are never lost.

**Draft / status labelling:**
- Questions with `_export.is_draft === true` are prefixed with `【草稿】` in the heading.
- A status line is appended below each question heading: processing, delivery_status (null delivery → "未知（未收到 terminal）"), review.
- `buildStatusLabel(snapshot)` maps each field to a Chinese chip string.

**題組 (group question) structure — `isGroupQuestion` helper:**
- A shared `isGroupQuestion(question, missingSlots=[])` helper detects group questions via ANY of: `題型種類 === "題組題"` (math 題組, 社會, 自然 all use it) OR `subquestions.length > 0` OR `missingSlots.some(s => s.kind === "subquestion")`.
- Preserved even when no subquestions survived (text-only 題組 — `q_RUN_003` in the math_groups fixture).
- Subquestion numbers are rendered using the original `序號` field (1-based, gapped sequences preserved).
- Known-missing subquestion slots (from `terminal.missing`) are injected at their correct ordinal position.
- Final without terminal = `is_draft: false`; NOT relabelled as draft.

**Image embedding from `imageSources`:**
- `embedSnapshotImages(zip, snapshot, idx, imageRefs)` reads exclusively from `snapshot.imageSources` (frozen at click time); never reads `question.image_base64` directly.
- `png_base64` kind → embedded in `Pictures/` and referenced as `<draw:image>` in content.xml.
- `chart_spec_preview` kind → rasterization attempted via injectable `Rasterizer` (issue #753); on success embedded as PNG; on failure emits 「匯出缺圖／預覽轉換失敗」 at the slot position. `buildOdtFromSnapshots` accepts optional `{ rasterizer }` for injection; production uses `defaultRasterizer` from `rasterizer.ts`. `Rasterizer` type takes `RasterizeInput { chartSpec, previewMarkup? }` — `previewMarkup` carries the DOM-captured HTML from the mounted FigureRenderer so the rasterizer uses the same output as the visible preview.
- `known_missing` kind → text marker `【圖片缺項】`; no PNG file embedded.

**Filename conventions:**
- Single draft: `草稿_{questionId}.odt`
- Single final: `{questionId}.odt`
- Batch with any draft: `含草稿_batch_{timestamp}.odt`
- Batch all final: `batch_{timestamp}.odt`
- Helpers: `singleQuestionOdtFilename`, `batchOdtFilename` in `exportSnapshot.ts`.

**Component wiring (issue #753 — retry + DOM augmentation):**
- `QuestionCard`: ODT button enabled for drafts (label `"card.download_odt_draft"`); captures snapshot via `captureFromEvidence`; augments `imageSources` with live DOM markup via `augmentWithDomMarkup`; stores snapshot in `lastOdtSnapshotRef`; on retry (`odtFeedback.state === "failed"`) re-uses the stored ref without re-capturing. Filename via `singleQuestionOdtFilename`.
- `GeneratePage`: batch ODT uses `captureBatchSnapshots` (returns `[QuestionSnapshot[], hasDraft]`); wraps each `QuestionCard` in `<div data-question-id={qid}>` so `augmentWithDomMarkup` can look up live FigureRenderer DOM per card; stores result in `lastBatchOdtSnapshotsRef` for retry. On retry (`odtFeedback.state === "failed"`) re-uses the stored ref. Filename via `batchOdtFilename(hasDraft)`.
- `HistoryDetail`: ODT button (shown when `question_json` present) uses `captureFromHistorySnapshot` + `buildOdtFromSnapshots`; augments with DOM markup from `[data-testid="question-card-content"]`; stores snapshot in `lastHistoryOdtSnapshotRef` for retry. On retry re-uses the stored ref. Filename via `singleQuestionOdtFilename`. `captureFromHistorySnapshot` is separate from `captureFromHistory` (JSON only).
- All three surfaces: `OdtBuildError` (whole-ZIP failure) → `operationFeedback.state = "failed"` → `InlineFailureNotice`; no broken file is produced. Generation evidence (`_export` fields) is never mutated by export failures.

**TDD:** `web/src/utils/odt.snapshot.test.ts` — 26 tests covering draft label, final (no label), status labels, math 題組 detection via `題型種類`, text-only 題組, subquestion number gaps, known-missing subquestion markers, known-missing/preview image markers, PNG embedding, batch page-break ordering, mixed draft/final batch, `OdtBuildError` on invalid base64.

**Acceptance tests:** `web/src/utils/odt.acceptance.test.ts` — (a) fixture-based: math_groups_interleaved.jsonl batch, verifying text-only 題組 structure (q_RUN_003), partial/complete status labels; (b) legacy unknown-order batch stable sort; (c) snapshot immutability after source mutation; (d) flat question still renders flat.

**Component-level jsdom tests (issue #753):**
- `web/src/components/QuestionCard.odt.test.tsx` — 6 tests (q1–q6): per-image failure → ODT still downloads with marker; ZIP failure → error shown, no download; retry re-uses same snapshot; fresh click after dismiss captures new snapshot; evidence unchanged after failure; PNG download uses correct filename convention.
- `web/src/pages/GeneratePage.odt-retry.test.tsx` — 4 tests (r1–r4): ZIP failure → InlineFailureNotice; retry re-uses same batch snapshot; fresh click captures new snapshot; evidence unchanged.
- `web/src/pages/HistoryDetail.odt.test.tsx` — 4 tests (h1–h4): ODT success; ZIP failure; retry re-uses stored snapshot (no re-capture); evidence unchanged.

**Real-browser tests (issue #753):**
- `tests/test_753_odt_browser.py` — 9 tests: 3 raw SVG foreignObject tests (table, scenario, no tainted canvas) + 6 harness tests driving real modules via `npx vite` dev server: defaultRasterizer produces PNG, same-source previewMarkup path, buildOdtFromSnapshots with chart_spec (PNG embedded), with png_base64, injected failure → marker with no PNG, no SecurityError.
- Test harness: `web/test-harness/odt-export.html` + `web/test-harness/odt-export-entry.ts` — served by `npx vite`, exposes `window.__harness.runAll()` for Playwright.

**Key files:** `web/src/utils/odt.ts`, `web/src/utils/odt.snapshot.test.ts`, `web/src/utils/odt.acceptance.test.ts`, `web/src/utils/exportSnapshot.ts`, `web/src/utils/rasterizer.ts`, `web/src/pages/GeneratePage.tsx`, `web/src/pages/HistoryDetail.tsx`, `web/test-harness/odt-export.html`, `web/test-harness/odt-export-entry.ts`.

### Save draft and update (issue #772)

`web/src/lib/recovery/format.ts` defines `RecoverySnapshotV1` (schema `exam-generation.recovery/1`) with `parseRecoverySnapshot` for strict validation (account, origin, environment, form shape).

`web/src/lib/recovery/storage.ts` provides transactional localStorage/sessionStorage helpers: `saveSnapshotTransactionally` (write + read-back verify; catches `QuotaExceededError` → `{ok:false,reason:'quota'}`), `persistTabPointer`, `getOrCreateTabId`, `loadSnapshot`, `deleteSnapshot`, `clearTabPointer`. `TabPointer` carries optional `tab_id`, `attempted_target_build_id`, `attempted_target_release_revision` (backward-compatible).

`web/src/lib/workspace/workspaceStore.ts` tracks `workspace_revision` (monotonically incremented on every surface/operation change), `navigationApproved: {target}|null`, and `freezeInput: boolean`. New methods: `approveNavigation`, `clearNavigationApproval`, `setFreezeInput`.

`web/src/lib/recovery/saveAndUpdate.ts` exports:
- `evaluateSaveAndUpdate(state)` — returns `{allowed:true}` only when all conditions are met.
- `runSaveAndUpdate(deps?)` — **full 10-step implementation** (not a stub): evaluate → record revision/user → export form → freeze → checkNow recheck (target, format, account, workspace) → build RecoverySnapshotV1 with `crypto.randomUUID()` → `saveSnapshotTransactionally` → `persistTabPointer` → `approveNavigation` → `navigate()`. On failure: `setFreezeInput(false)` + `clearNavigationApproval()`. `deps` is injectable for tests (`navigate`, `now`, `origin`, `environment`, `buildId`).

`web/src/lib/recovery/recoveryStore.ts` is a zustand store. Call `initRecoveryStore({currentRoute, origin, environment})` at app boot or after sign-in to attempt snapshot restore. Sets `pending` on success, `blocked:'wrong_account'` when account mismatches, or silently skips otherwise. `discardRecovery()` deletes the snapshot from localStorage, clears the tab pointer, and clears `pending`.

`web/src/components/ReleaseNotice.tsx` renders a "儲存草稿並更新 / Save Draft & Update" button in `update-required` state, disabled with a localised tooltip when denied. On failure, shows inline error + "重試" button. On success `navigate()` calls `window.location.reload()`. `GeneratePage.tsx` `useBlocker` and `beforeunload` consult `navigationApproved` so an approved navigation bypasses the guard once.

`web/buildIdentity.ts` now emits `supported_recovery_formats: ["exam-generation.recovery/1"]` in the policy fixture. `useReleaseStore` exposes `supportedRecoveryFormats` from the last parsed policy.

`web/src/components/ParamForm.tsx` accepts a `recoveredForm?: FormWorkspaceSnapshot` prop. When present: form fields are initialised from `recoveredForm.fields` (wins over draft/history prefill); a blue restoration banner is shown; `formReadiness` is `'restoring'` while the banner is visible; after schemas load, `recoveredInvalidFields: Set<string>` marks values not admitted by the current curriculum (submit disabled until corrected); the schema-load effect is guarded to prevent overwriting recovered values. `onRecoveryAcknowledge` and `onRecoveryDiscard` callbacks are called by the respective banner buttons.

`web/src/pages/GeneratePage.tsx` reads `useRecoveryStore().pending` and passes `pending?.form` as `recoveredForm` and `discardRecovery` as `onRecoveryAcknowledge`/`onRecoveryDiscard` to ParamForm.

See `docs/research/2026-09-15-772-save-draft-and-update.md`.

Issue #773 extends the same `exam-generation.recovery/1` envelope with an
optional settled `confirmation` workspace. Save-and-update captures the
ordinary form and the exact 發送前確認 payload independently before its
release recheck; restore mounts that confirmation before schema/model
hydration, never re-runs resolver/planner/preview work, and keeps invalid
current-schema values visible and blocked until an explicit correction.
Confirmation-only edits, per-題組/per-小題 rows, seed/drawn/redraw/cleared
provenance, pending prefill, and draft-versus-History choice are not folded
back into the form. Active operations, results, and modification drafts remain
refused for their owning issues.
See `docs/research/2026-09-17-773-preserve-confirmation.md`.

### Received results recovery (issue #774)

The same v1 recovery envelope may also carry an optional `results` workspace.
Save is allowed only after observed work settles; it preserves final and
visible partial content, evidence, progress, totals, errors, and raw PNG
base64. Missing terminal evidence remains `unknown`, and result hydration must
finish before the snapshot/pointer is acknowledged or deleted. Quota,
read-back, persistence, or hydration failures leave the live cards and their
existing JSON/ODT exports available; no object URLs, provider diagnostics,
credentials, draft-export feature, or History-only modification eligibility is
introduced. Active generation and modification drafts remain refusals.
See `docs/research/2026-09-17-774-preserve-results.md`.

### Manual-review modification draft recovery (issue #775)

The v1 recovery envelope may also carry an optional settled `modification`
workspace from History detail: unsent 圈選/instructions, route and exact
record/question/content identity, known revision, eligibility evidence, and a
received replacement. Restore re-fetches the authorized History record and
blocks changed descendants, content/revision, authorization, or eligibility;
it never replays admission or SSE. Active modification operations still refuse
Save Draft & Update, while settled replacements are captured for a later save.
See `docs/research/2026-09-17-775-preserve-modification-drafts.md`.

### Recovery identity hardening (issue #776)

Two 401 paths and explicit logout are now distinct. `authStore.logout()` (called on API/stream 401s) clears credentials only — recovery snapshot preserved. `authStore.logoutExplicit()` (called on UI logout) calls `deleteAllSnapshotsForAccount(userId)` + `clearTabPointer()` first so a different account signing in next sees no prior snapshot.

Both `apiFetch` 401 and `useGenerate` stream 401 now also call `saveSignoutReason("session_expired", userId)` and `saveReturnDestination(pathname)` so the login page can navigate back and restore.

`web/src/lib/recovery/storage.ts` adds: `claimSnapshot(tabId, snapshotId)` (write+read-back nonce claim, structural fields only), `releaseSnapshotClaim(snapshotId)`, `deleteAllSnapshotsForAccount(accountId)`, `startTabCollisionListener(myTabId)` (BroadcastChannel probe responder), `detectTabCollision(tabId, timeoutMs)` (async probe — returns true if another live tab has same ID).

`web/src/lib/recovery/recoveryStore.ts` adds `initRecoveryStoreAsync` (claims snapshot before hydrating; sets `claimedTabId`/`claimedSnapshotId` in state), and `acknowledgeRecovery`/`discardRecovery` now release the claim. Synchronous `initRecoveryStore` unchanged.

New storage key: `localStorage exam_recovery_claim_<snapshot_id>`. No snapshot contents in any telemetry or log call.
See `docs/research/2026-09-18-776-recovery-identity.md`.

### Generation admission gateway (issue #740)

`gateway/` is an independent ASGI reverse proxy that lets an operator pause all new `GET /api/generate` and `POST /api/generate` requests from a single control point, independent of the frontend and backend deployment units.

State is file-backed (`admission.json` on a dedicated volume), fail-closed (missing or unreadable file = paused), and survives application rollbacks.  The proxy is transparent to every other route — preview, resolve, planning, modification stream, history, auth, health — only the two generation entry-points are gated.

Key files:
- `gateway/admission.py` — `is_generation_entry(method, path)`, `PAUSED_DETAIL`, `PAUSED_CODE`
- `gateway/state.py` — `AdmissionState`, `read_state`, `pause`, `open_gate`
- `gateway/app.py` — `create_app(*, backend_url, state_dir, control_token, release_controller)` → Starlette app
- `gateway/release_controller.py` — live policy contract, revision/asset state, evidence-gated transitions
- `gateway/__main__.py` — uvicorn entry point (env: `GATEWAY_BACKEND_URL`, `GATEWAY_STATE_DIR`, `GATEWAY_CONTROL_TOKEN`, `PORT`)
- `scripts/admission_gate.py` — CLI (`pause`, `open`, `status --require PAUSED|OPEN`)
- `Dockerfile.gateway`, `docker-compose.yml` (gateway service)
- `DEPLOYMENT.md` § "Generation admission gateway" for Compose and Railway instructions

Drain evidence (#741) is implemented (see `### Drain telemetry and release control` below). Stream-version/426 upgrade (#742) is implemented (see `### Generation stream protocol v2` above).

### Drain telemetry and release control (issue #741)

`server/generate/drain.py` exports `DrainTelemetry`, `_NoopDrainTelemetry`, `NOOP_DRAIN`, and `get_drain(app_state)`.  `DrainTelemetry` maintains six thread-safe gauges (`active_runs`, `active_workers`, `open_streams`, `pending_deliveries`, `pending_persistence`, `renderer_leases_held`) plus instance-identity fields.  `snapshot()` returns a JSON-serialisable dict including `quiescent: bool` (all six gauges are zero).

Key files:
- `server/generate/drain.py` — `DrainTelemetry`, `_NoopDrainTelemetry`, `NOOP_DRAIN`, `get_drain`
- `server/internal/routes.py` — `GET /internal/drain` (requires `X-Drain-Token` header matching `DRAIN_TELEMETRY_TOKEN` env; missing token → 404)
- `server/config.py` — `drain_telemetry_token` field (`DRAIN_TELEMETRY_TOKEN` env)
- `gateway/admission.py` — `is_private_path(path)` helper; `/internal/*` never proxied
- `gateway/app.py` — blocks `/internal/*` before forwarding to backend
- `scripts/release_control.py` — `preflight`, `drain-check`, `pause-and-drain`, `compat-check`, `reopen`, `readiness` subcommands; reads `inventory.json`
- `DEPLOYMENT.md` § "Drain telemetry and release control" for runbook

Integration points in `service.py`:
- `generate_question_stream` registers the stream's queue with `drain.register_queue(queue)` and increments `_active_runs` at entry; a `with anyio.CancelScope(shield=True)` in the finally block ensures decrements run even on GeneratorExit.
- `_worker_one` body is wrapped with `with ctx.drain_telemetry.ctx_active_worker():`.
- `RendererLease.__init__` accepts an optional `drain_telemetry` parameter and increments/decrements `_renderer_leases_held` inside `render()`.
- `event_generator` in `routes.py` increments/decrements `_open_streams` around the SSE loop.


### 出題模式 is a prompt-level hint

`coverage_mode` remains an accepted request parameter but affects no mechanical draw. For 均衡 with `count > 1`, each question's 文本生成器 user prompt gains one `## 出題模式：均衡` instruction asking the model to spread 題型 and 取材角度 across the batch and avoid scopes listed in the `已生成題目` block from issue #111. 隨機 injects nothing, and `count = 1` prompts remain byte-identical. Response metadata reports the requested mode as `coverage_mode_used`.

`core_question_callback` is a 社會領域 request-level 建議值, defaulting to `true`. When enabled, the 文本生成器 is asked to plan the 題組's last 小題 as a synthesis question that explicitly addresses that 題組's own 核心問題 and integrates the earlier 小題; the resolved final 子題產生器 slot receives the corresponding instruction, including after truncation or padding. It composes with 各小題配置, whose explicit 題型、出題指示、學習內容、學習表現 remain authoritative. This is prompt-only: it adds no verifier criterion and changes no 題型/學習內容/學習表現 sampling. `false` preserves the pre-change prompt bytes.

自然科學 uses the same `core_question_callback` field, default-on behavior, wording, resolved-last-slot handling, and CLI opt-out as 社會領域. It is likewise prompt-only and preserves explicit 各小題配置 plus the pre-change prompt bytes when disabled.

### Verify + correct loop
1. First call (execute model): generates the question and solution. **For math whose resolved `題型種類` is `單一題` and has no `sub_question_count`,** this remains one call producing the full flat question, byte-identical to before. **For math whose resolved `題型種類` is `題組題`,** the resolver has already supplied `sub_question_count` and the shared `src/common/generation_core.py` **文本生成器 → N 子題產生器** pipeline runs a **文本生成器** call for the shared 核心問題/文本/取材來源 and an N-entry 小題 plan, then N concurrent **子題產生器** calls each write one complete 小題; a supplied `sub_question_count` still pins `題型種類=題組題`, and supplying it with explicit `題型種類=單一題` remains HTTP 422. **For social studies and natural sciences,** this is also a two-stage pipeline: a **文本生成器** call produces the shared 核心問題/文本/取材來源 plus an N-entry 子題 plan, then N concurrent **子題產生器** calls each write one complete 子題 (via `ThreadPoolExecutor`, capped by `SUBGEN_MAX_CONCURRENCY`, default 6; failed/unparseable 子題 calls get up to `SUBGEN_RETRIES` fresh retries, default 1, before the slot is dropped); the assembled 題組 then enters the verify/correct loop.
2. Chart/image specs are rendered to PNG before verification so the verifier can see them. Math renders top-level `chart_spec`; social studies and natural sciences also render `subquestions[*].chart_spec` to per-小題 PNGs. For 社會／自然, a visual 題組-level content type requests one shared 題幹 figure; each 小題's own configuration determines its figure obligation. An image generation mode selects the renderer and creates no obligation by itself.
3. Second call (驗證模型, default `claude-opus-4-6`, multimodal): independently solves the question, inspects PNG, returns `VerificationResult` with `passed`, `answer_match`, `details`, `my_answer`, `provided_answer`, and optional `chart_verification`.
4. If `passed=False`, a correction pass sends the failed question + verifier feedback back to the execute model for a minimal targeted fix. Validate the complete candidate before applying it; rejected candidates retain the entering question and consume one retry. PNG re-renders only for accepted changes to `chart_spec`. Re-verify accepted or retained content and loop up to `max_retries` (default 3, via `LLM_MAX_RETRIES` / `--max-retries`).

When changing correctors, automatic retries, manual-review application, or correction timelines, read [the correction integrity contract](docs/correction-integrity.md) for identity rules, decision callbacks, retained snapshots, and legacy trail behavior.

### Fact-check pass (social studies only)

Optional web-search fact-check runs after the teacher verify pass for
時事-flagged social-studies questions (issue #104). Enable by setting
`WEB_SEARCH_PROVIDER=anthropic`, `gemini`, or `none` (default `none` — opt-in)
and optionally `WEB_SEARCH_MAX_USES=N` (default `5`). The gate is keyed to the
effective 驗證模型 (`model_verify` or, when empty, `model_execute`); the
configured provider must match that model's provider or the pass is skipped.
Anthropic uses its native `web_search_20250305` server tool, while Gemini uses
Google grounding through its OpenAI-compatible endpoint. The fact-check call
uses the 驗證 tier because `fact_check` belongs to `_VERIFY_PURPOSES`, and
therefore also uses `effort_verify` (falling back to `effort_execute`). When
enabled, `src/social_studies/verifier.py::verify_question` calls
`src/social_studies/fact_check.py::fact_check_question` only when
`is_current_events(question)` is True (heuristic: any subquestion's 學習內容
編碼 starts with `公`, or `核心問題`/`文本` matches `近年|最近|今年|去年|本屆|
現任|當前`). A definitive negative (`fact_check.verified is False`) forces
`passed=False` and appends issues to `details` so the existing correction
loop sees them. Any failure — provider disabled, provider/model mismatch,
endpoint rejection, malformed JSON, or exhausted iterations — fails open:
`fact_check=None` and the teacher verdict is unchanged.

### 自然科學 measures Reporting Scale, not 難度
自然科學 uses Reporting Scale — the PISA Science proficiency scale (levels 1c, 1b, 1a, 2, 3, 4, 5, 6) — as its per-小題 demand signal. 數學 and 社會領域 use 難度 (easy / medium / hard). The two signals never overlap across subjects.

**Precedence for 自然科學:** an explicit per-小題 Reporting Scale overrides the 題組-level value; when neither is set, the slot draws independently at random. The 題組-level value is only a default-filler and is absent when the user leaves the field 隨機.

**What each prompt stage receives:**
- 文本生成器 user prompt — the 題組-level target stated with its single PISA level descriptor verbatim in English (## 目標報告等級 block, only when a 題組-level value is set), plus the resolved per-小題 levels in the 各小題配置 block. The eight-level calibration reference is deliberately NOT included here (~8.5K chars; the planner needs its target, not the whole scale).
- 子題產生器 user prompt — the full eight-level PISA calibration reference verbatim plus the 小題's own target level, so the model writes to one specific level with the whole scale for calibration.
- Verifier — receives neither 難度 nor Reporting Scale; it concentrates on answer correctness and 課綱代碼 validity.
- Corrector — level assignment is frozen through all correction retries; the corrector may not alter it.

**Output:** resolved per-小題 levels are recorded in `metadata.reporting_scales` in 序號 order; slots that were dropped or unresolved leave no entry.

### LLM provider is selected per-request from the model id

`resolve_provider(model)` in `src/llm_client.py` maps each call to a provider at call time: `gemini-*` → Gemini via its OpenAI-compatible endpoint (OpenAI SDK, `GEMINI_API_KEY` / `GEMINI_BASE_URL`); `gpt-*/o-series` → OpenAI SDK (`OPENAI_API_KEY` / `OPENAI_BASE_URL`); `claude-*` → Anthropic SDK (prompt caching, streaming, `system` param, `LLM_API_KEY` / `LLM_BASE_URL`); unknown ids → Anthropic (proxy deployments). The shared constants in `src/config.py` supply both config readers: plan and 驗證 default to `claude-opus-4-6` at `high` effort, execute defaults to `gemini-3.1-pro-preview` at `high`, and 修正 model/effort stay empty to inherit execute at call time. Explicitly empty 驗證 model/effort also inherit execute; only unset env vars use the defaults. Both `GEMINI_API_KEY` and `LLM_API_KEY` are required for the default configuration. `gemini-3.1-pro-preview` heads the built-in `_DEFAULT_MODELS_ALLOWED` roster, followed by `claude-opus-4-6`. Effort translation: Anthropic uses `extra_body.output_config.effort`; Gemini/OpenAI use `reasoning_effort` (low/medium/high only — other values are dropped with a one-time WARNING). Opus 4.6 calls enable adaptive thinking with a shared thinking/response output ceiling of 16,384 tokens and omit temperature. Other calls retain an 8,192-token ceiling. Temperature is also withheld from `gemini-3.x`, `gpt-5.x`, o1/o3/o4, and the Claude sampling-reject roster documented in the README environment table. OpenAI provider gets `max_completion_tokens` instead of `max_tokens`. A missing provider key returns HTTP 422 naming the env var. Fact-check is provider-general: Anthropic uses `web_search_20250305` and Gemini uses Google grounding; `fact_check_question` silently returns `None` (fail-open) when `WEB_SEARCH_PROVIDER` is disabled or does not match the effective 驗證模型 (`model_verify` or `model_execute`). The call itself resolves through the 驗證 tier and uses `effort_verify`. Image generation (IMAGE\_API\_KEY / IMAGE\_BASE\_URL / IMAGE\_MODEL, `gpt-image2`) is unchanged — Gemini image generation is future work. Known gaps: #338 (UI effort fields dropped before reaching server), #346 (planner purpose string never matches `"plan"` so plan calls get `effort_execute`). `classify_provider_error(exc, detail=None) -> str` (issue #946) maps any caught exception to one of 10 taxonomy codes: `auth_config` (auth/key errors), `quota_billing_exhausted` (spend/billing limit), `rate_limited` (HTTP 429 / RESOURCE_EXHAUSTED), `overloaded` (HTTP 529), `timeout` (APITimeoutError), `connection` (APIConnectionError), `context_length` (HTTP 413), `content_filtered` (ContentFilterFinishReasonError), `malformed_response` (unparseable output), `unknown` (fallback). Two-pass design: exception-class gives a fast approximation; when `ProviderErrorDetail` is available a second body-based pass applies precision overrides (e.g. Anthropic `enforced_spend_limit_reached` → `quota_billing_exhausted` over the generic 400 class). The function never raises.

### Fable model downgrade switch (issue #940)

`LLM_FABLE_DOWNGRADE` (parsed in `src/config.py`; default off) — when set to `1` or `true`, any call whose model id contains `"fable"` (case-insensitive) is transparently dispatched to `FABLE_DOWNGRADE_TARGET = "claude-opus-4-6"` instead. `xhigh` effort is clamped to `high` for the substituted model (opus-4-6 does not accept `xhigh`). One `WARNING` per substituted call names both the requested and the effective model ids; no prompt text is included.

Two guarded entry points in `LLMClient`:
- `_call()` — covers `generate`, `generate_json`, `generate_with_image`, and all Anthropic streaming paths.
- `generate_with_tools()` — covers the Anthropic web-search fact-check path (issue #941).

`generate_with_google_search()` is unreachable with a Fable model (the provider gate blocks it at `resolve_provider`), so no guard is needed there. `generate_image()` uses `IMAGE_MODEL` (`gpt-image2`), never a Claude model — no guard needed.

The dispatch applies at call time through `Config.dispatch_model(model)` and `Config.dispatch_effort(effort, dispatched_model)`. When a substitution occurs, `requested_model` is added to `llm_request`/`llm_response`/`llm_failure` events (only when different from the dispatched `model`), and `ExchangeRecorder` copies it into `request_body["requested_model"]` (#942). Recording in `model_substitutions` in `params_json` is implemented in issue #943 (see below). Switch off → SDK args, events, and records are byte-identical to before.

**Fact-check guard (issue #941):** `src/social_studies/fact_check.py::fact_check_question` calls `client.generate_with_tools()`, which already applies the `generate_with_tools()` guard above. End-to-end tests in `tests/test_941_fact_check_fable_guard.py` drive `fact_check_question` with a real `LLMClient` (fake SDK) and assert that a Fable verify model with `xhigh` effort yields `model=claude-opus-4-6`, `effort=high`, adaptive thinking, and one WARNING per call. The provider gate (`resolve_provider(effective_verify_model) == provider`) continues to use the *requested* model's provider — `claude-fable-5` is still `anthropic`, so the gate passes unchanged.

**Guard-coverage test (issue #941):** `tests/test_941_dispatch_coverage.py` contains an AST-based checker that scans `src/llm_client.py` for all SDK dispatch calls (`messages.create`, `messages.stream`, `chat.completions.create`, `images.generate`) and verifies each is in a guarded function (one that calls `dispatch_model`) or in the explicit `EXEMPT` dict with a documented reason. A negative test removes the guard from `generate_with_tools` on a scratch copy and asserts the checker reports a violation, confirming the checker itself works. Add a new entry to `EXEMPT` whenever a new SDK dispatch method is introduced that genuinely does not need Fable substitution.

**History model substitutions display (issue #943):** When `LLM_FABLE_DOWNGRADE` is on and any tier's model is Fable, the server writes `model_substitutions: {tier: {requested, ran}}` into the stored `params_json` (only for substituted tiers; absent when switch off or no Fable models). This is a server-derived field: `routes.py` and `persistence.py` both strip any client-supplied value before writing, then add the server-computed dict if non-empty. `model_substitutions` is in `SERVER_ONLY_GENERATE_FIELDS` so it is excluded from the TypeScript contract and the resolver. `HistoryDetail.tsx` renders a localized amber notice listing each substituted tier (requested → ran) when the field is present. `handleRegenerate` strips the field so the prefill form sees no substitution. `server/generate/model_substitutions.py` provides the helper `model_substitutions(params, config)`. 14 backend unit/integration tests in `tests/server/test_943_model_substitutions.py`; 4 frontend tests in `web/src/pages/HistoryDetail.model-substitutions.test.tsx`.

**Question metadata and verification trail (issue #944):** `QuestionMetadata.model` and every verification/correction trail entry's `model` field name the model that actually ran, passed through `config.dispatch_model(...)` at the point each value is written. This applies to all three subject pipelines: math flat (`src/cli.py` — `_parse_question` call, `_emit_verification_trail`, correction trail entry) and math grouped / social studies / natural sciences (`src/common/generation_core.py` — `spec.parse_text_shell_fn` call, two `_emit_trail` calls, `_emit_correction_trail` call). The requested model id is still preserved separately in `params_json` / `model_substitutions` (#943). Switch off → field values are byte-identical to before. `metadata` and `verification_trail` are stripped from the v2 content signature, so these fields never bump a content revision.

### Web-ready design
All core modules (`sampler`, `context_builder`, `llm_client`, `verifier`, `renderer`) are standalone importable components. The CLI (`cli.py`) is a thin wrapper. Config comes from env vars. This allows future integration with FastAPI/Flask without refactoring.

### Shared loaders, three subject pipelines
Math (`src/*.py`), social studies (`src/social_studies/*.py`), and natural sciences (`src/natural_sciences/*.py`) are three parallel question-generation pipelines that share their curriculum-loading core. The subject-agnostic loaders live in `src/common/`: Social studies and natural sciences `generate_one` now run a **文本生成器 → N parallel 子題產生器** pipeline; math's `generate_one` keeps its original single-call structure when `sub_question_count` is absent and uses the shared **文本生成器 → N 子題產生器** core when it is present.

- `src/common/curriculum_loader.py` — JSON loaders + `allowed_learning_content` / `allowed_learning_performance` filters, parameterized by `data_dir` and a `subject_to_prefixes` map.
- `src/common/core_competency_loader.py` — JSON loader + `build_core_competency_enum` + `allowed_competencies(stage)`.
- `src/common/planner.py` — subject-agnostic 核心問題 generator; callers pass their own system/user prompt templates.

Each subject package wraps these with its own data directory and prefix map:

- **Math** uses `data/math/curriculum/` and `_MATH_SUBJECT_TO_PREFIXES` (in `src/sampler.py`): 數與量={N,n}, 代數={A,F,R,a,f,r}, 幾何={S,G,s,g}, 統計與機率={D,P,d,p}, 跨領域=all. Subject prompts live in `src/planner.py` (數學領域命題教師).
- **Social studies** uses `data/social_studies/curriculum/` and `_SUBJECT_TO_PREFIXES` (in `src/social_studies/curriculum_loader.py`). The `src/social_studies/{curriculum_loader, core_competency_loader, planner}.py` modules are thin shims over `src.common.*`.
- **Natural sciences** uses `data/natural_sciences/curriculum/`, subject_prefix `"自"` (in `src/natural_sciences/core_competency_loader.py`). Unlike the other two subjects, natural sciences has **no per-subject bucketing** — `科目` is fixed as `"自然科學"` on all subquestions, and `src/natural_sciences/curriculum_loader.py` overrides `allowed_learning_content` / `allowed_learning_performance` to skip the subject filter entirely. Subject prompts live in `src/natural_sciences/planner.py` (PISA-Science scientific literacy template). The `src/natural_sciences/{curriculum_loader, core_competency_loader, planner}.py` modules are thin shims over `src.common.*`.

Math keeps its byte-identical single-call flat output when the resolved `題型種類` is `單一題` and `sub_question_count` is absent. When the resolved `題型種類` is `題組題`, the resolver has already supplied `sub_question_count` before the shared `src/common/generation_core.py` **文本生成器 → N 子題產生器** pipeline; a supplied `sub_question_count` still pins `題型種類=題組題`, and supplying it with explicit `題型種類=單一題` remains HTTP 422. The shared core truncates or pads the plan so exactly the resolved number of 小題 is generated. Social studies and natural sciences both use a 題組 structure with `subquestions[]` and rubric entries. Social-studies parent items are fixed as 題組題; the ICCS-era social pipeline assigns `認知歷程` and `內容領域`, supports the four live `subquestions[*].題型` formats, and consumes complete per-小題 題型, 出題指示, question/option word-limit, content/image constraints from the web/API (no per-小題 text_word_limit — that is a request-level field only, ADR 0023). Natural sciences replaces `核心素養` with `科學能力` (6 entries: 能力一/二/三 + 環境能力一/二/三) and adds `情境子類別` (a PISA sub-context parented to the top-level 情境). Natural sciences also supports complete per-小題 SubQuestionConfig rows. The natural sciences verifier uses the lenient "寬鬆通過、只攔重大問題" stance, distinct from math's strict "明確錯誤" stance.

Social studies is now in the ICCS era: `認知歷程` uses four buckets, `內容領域` uses four ICCS domains, and `內容領域_mapping.csv` anchors public/cross-subject learning-content codes to the selected domain. `閱讀歷程` and `文本形式` remain schema fields only for rendering old records; new generation, prompts, and authoring surfaces do not create them. `target_surface` is `紙本` or `數位`; `拖放題` and `滑桿題` are digital-only. Interactive items carry authoritative `interaction` specs and native scoring, while open responses carry fixed 2 / 1 / 0 rubrics (1 / 2 / 1 學生作答實例; shape enforced by the post-verify hook in `src/common/open_response_rubric.py`; legacy codes remain readable).

Schema, curriculum, and few-shot data are **CSV-driven** for schema/few-shot; **JSON-driven** for curriculum. Files under `data/social_studies/` read at runtime:

| File | Purpose |
|---|---|
| `curriculum/schema_meta.csv` | 學習階段 label + grades list |
| `curriculum/schema_parameters.csv` | Allowed values + instructions for the live parameter categories: 情境/題型種類/題型/認知歷程/內容領域/科目/題目內容類型/難度 |
| `curriculum/內容領域_mapping.csv` | Approved learning-content-code → ICCS content-domain mapping used by the sampler and verifier |
| `curriculum/learning_performance.json` | 108課綱 社會領域 學習表現標準 (26 codes; ODT-sourced) → system prompt + sampler pool |
| `curriculum/learning_content.json` | 108課綱 社會領域 學習內容 (472 entries; ODT-sourced `對應學習表現`) → system prompt + sampler pool |
| `few_shot/few_shot_examples.csv` | Channel-1 few-shot examples (long format, grouped by `範例編號`; one row per subquestion; keyed by six 題目內容類型 values) |
| `few_shot/<題目內容類型>/` | Channel-1 JSON groups, one directory per content-type key; `graphs/charts/tables` is nested because the key contains `/` |
| `few_shot/process_exemplars/` | Channel-2 process exemplars selected by the `(內容領域, 認知歷程)` prompt pair |

CSVs are `utf-8-sig` (Excel BOM-tolerant); multi-value fields use `;` as separator. `範例_`-prefixed files in the same folders are reference examples for researchers — they are never loaded by the system. See `data/social_studies/csv_填寫指南.md` for the field-by-field filler guide.

**Sampler 科目 filter:** `_SUBJECT_TO_PREFIXES` in `curriculum_loader.py` maps each subject to its 科目 set. All subjects include `"社"` so the 16 cross-subject general 學習表現 codes (社1a/1b/2a/2b/2c/3a/3b/3c/3d-Ⅳ-*) are in every subject's pool — not only 跨科. This is per 108課綱 design where 社_* codes apply across all 社會領域 subjects. All subjects also include the empty-string `""` bucket so the 57 shared 學習內容 entries with `科目=""` appear in every subject's draw pool (parallel to the `社` bucket for 學習表現).

### Natural sciences curriculum data
`data/natural_sciences/curriculum/` contains 108課綱 自然科學領域 curriculum assets. The JSON files are generated from the canonical source `converted/課綱各項指標列表.xlsx` via `python3 scripts/build_natural_sciences_curriculum.py`. The CSV files are researcher-editable, mirroring the social-studies layout.

| File | Purpose |
|---|---|
| `curriculum/schema_meta.csv` | 學習階段 label + grades list (runtime-editable) |
| `curriculum/schema_parameters.csv` | Parameter values + instructions for 情境, 情境子類別, 題型種類, 題型, 科學能力, 題目內容類型. 情境子類別 rows carry a `parent` column linking each sub-context to its parent 情境 value. |
| `curriculum/learning_content.json` | Top-level `學習階段_to_grades`, `跨科概念` taxonomy (48 entries), and `學習內容` (757 entries). |
| `curriculum/learning_performance.json` | `學習表現` standards (99 entries) plus `學習階段_to_grades`. |
| `curriculum/core_competencies.json` | 自然科學領域 核心素養 (9 entries). |

Natural-sciences JSON shapes:

- `跨科概念`: `課題`, `跨科概念`, `主題`, `次主題`.
- `學習內容`: `value`, `學習階段`, `科目`, `條目說明`, `備註`, `對應學習表現`.
- `學習表現`: `value`, `學習階段`, `科目`, `構面`, `項目`, `說明`, `對應學習內容`.

Stage mapping is shared across the two files: 第二學習階段 grades 3-4, 第三 5-6, 第四 7-9, 第五 10-12. High-school 學習內容 uses `科目` buckets `生物`, `物理`, `化學`, `地球科學`; earlier-stage shared rows use `科目=""`.

**Sampler 科目 filter:** Natural sciences deliberately does NOT bucket by 科目 (生物/物理/化學/地球科學) at the sampler level, unlike social studies. `科目` is fixed at `"自然科學"` on every subquestion. `src/natural_sciences/curriculum_loader.py` overrides `allowed_learning_content` / `allowed_learning_performance` to omit the subject parameter and return the full stage pool.

Few-shot examples live under `data/natural_sciences/few_shot/` in one folder per 題型:

| Folder | 題型 |
|---|---|
| `Simple-multiple-choice/` | PISA 單選 |
| `Complex-multiple-choice/` | PISA 複選 |
| `Constructed-response/` | PISA 建構反應題 |

Each folder accepts `*.json` files (flat pool, parallel to math's `data/few_shot/{style}/`) or a `few_shot_examples.csv` (parallel to social studies). The repo ships a pool of JSON examples across these folders (count it with `ls data/natural_sciences/few_shot/*/*.json | wc -l`). The data loader (`src/natural_sciences/data_loader.py`) falls back to scanning all subdirectories when `q_type` is unknown.

## Key Files

| File | Purpose |
|---|---|
| `data/curriculum/學習內容.json` | Full K-12 math curriculum content, 14 grade levels (legacy source for `data_loader.py`) |
| `data/curriculum/學習表現.json` | Math learning performance standards by stage (legacy source) |
| `data/math/curriculum/learning_content.json` | Reshaped math 學習內容 (288 entries across 5 學習階段; row shape `{value, 學習階段, 科目, 條目說明, 對應學習表現}`; `科目` is a single-letter strand prefix N/A/F/R/S/G/D/P). Loaded via `src.common.curriculum_loader`. |
| `data/math/curriculum/learning_performance.json` | Reshaped math 學習表現 (131 entries; row shape `{value, 學習階段, 科目, 說明}`). Loaded via `src.common.curriculum_loader`. |
| `data/math/curriculum/core_competencies.json` | 108課綱 數學領域 核心素養 (27 codes 數-E/J/U-A1..C3, synthesized from social studies' template with `值` rewritten from 社- to 數-). |
| `data/math/curriculum/learning_performance_intro.md` | Math 學習表現 framework intro → injected into system prompt. |
| `scripts/build_math_curriculum.py` | Reproducible builder: emits the four `data/math/curriculum/` files from `data/curriculum/{學習內容,學習表現}.json` + the social studies core_competencies template. |
| `src/common/curriculum_loader.py` | Subject-agnostic JSON loaders + `allowed_learning_content/performance(data, stage, *, subject, subject_to_prefixes)` filters. |
| `src/common/core_competency_loader.py` | Subject-agnostic 核心素養 loader + `build_core_competency_enum` + `allowed_competencies(data, stage)`. |
| `src/common/planner.py` | Subject-agnostic `plan_core_questions()`; callers pass their own system/user prompt templates. |
| `src/common/admission.py` | Shared admission lookup over `admitted_by` tags (ADR 0020): answers which 科目 / 內容領域 admit a loaded curriculum row; read by the social-studies 學習內容 內容領域 pool filter and by generation-time 科目/code validation. |
| `src/planner.py` | Math planner shim — wraps `src.common.planner.plan_core_questions` with a 資深108課綱數學領域命題教師 system prompt asking for 3 candidate 核心問題 covering 代數 / 幾何 / 統計三大面向. |
| `data/few_shot/` | Math few-shot examples by question style |
| `data/example_exams/` | Past national exam PDFs (112-114) for reference |
| `question_schemas.json` | Math user-editable config: `"學習階段"` (string), `"grades"` (int array), and all 5 question parameter categories using `[{value, instruction}]` objects. Non-empty `instruction` fields are injected into the LLM prompt. |
| `src/schema_loader.py` | Loads `question_schemas.json`, exposes `load_grades()` / `load_learning_stage()`, builds dynamic str-enums via `build_enums()`, and builds `{category: {value: instruction}}` lookup via `build_instructions()` |
| `data/social_studies/curriculum/schema_meta.csv` | Social studies 學習階段 + grades (runtime-editable) |
| `data/social_studies/curriculum/schema_parameters.csv` | Social studies parameter values + instructions (6 categories) |
| `data/social_studies/curriculum/learning_performance.json` | Social studies 學習表現標準 JSON (26 codes; 科目/構面/項目 metadata + bidirectional `對應學習內容` field populated from ODT 呼應表) → system prompt + sampler pool |
| `data/social_studies/curriculum/learning_performance_intro.md` | Official NAER 學習表現 framework chapter (構面/項目/編碼規則 + full 條目) → system prompt `### 學習表現架構說明` |
| `data/social_studies/curriculum/learning_content.json` | Social studies 學習內容 JSON (472 entries spanning 學習階段 二/三/四/五; `對應學習表現` populated from ODT 呼應表 — 55 entries mapped at 第四學習階段) → system prompt + sampler pool |
| `scripts/connect_curriculum_from_odt.py` | One-shot importer: reads the official 社會領域學習重點與核心素養呼應表 (ODT) and overwrites `對應學習表現` in `learning_content.json` and `對應學習內容` in `learning_performance.json`; also appends any perf codes referenced in the ODT but missing from the JSON. Re-run if NAER publishes an updated 呼應表. |
| `data/natural_sciences/curriculum/learning_content.json` | Natural sciences 學習內容 JSON (757 entries) plus top-level `跨科概念` taxonomy (48 entries), generated from the canonical converted workbook. |
| `data/natural_sciences/curriculum/learning_performance.json` | Natural sciences 學習表現 JSON (99 entries; stages 二/三/四/五). |
| `scripts/build_natural_sciences_curriculum.py` | Rebuilds natural-sciences `learning_content.json`, `learning_performance.json`, and `core_competencies.json` from `converted/課綱各項指標列表.xlsx`. |
| `data/social_studies/few_shot/few_shot_examples.csv` | Social studies few-shot examples (long format grouped by 範例編號; one row per subquestion with all 108課綱 metadata columns; header-only as of #542; awaiting ICCS-native content from #544) |
| `data/social_studies/csv_填寫指南.md` | zh-TW filler guide: field-by-field explanation of JSON + CSV files |
| `src/social_studies/schema_loader.py` | Builds social-studies schema dict from `schema_meta.csv` + `schema_parameters.csv` |
| `src/social_studies/curriculum_loader.py` | Thin shim over `src.common.curriculum_loader`. Owns `_SUBJECT_TO_PREFIXES` (歷史/地理/公民與社會/跨科, all include `"社"` and `""`) and the `data/social_studies/curriculum/` default path. Adds `*_instructions` / `load_performance_intro` helpers on top of the shared loader. |
| `data/social_studies/curriculum/core_competencies.json` | 108課綱 社會領域 核心素養 codes → sampler pool; loaded via `src.common.core_competency_loader` through the shim. |
| `src/social_studies/core_competency_loader.py` | Thin shim over `src.common.core_competency_loader`; adds `allowed_core_competencies(data, stage, subject)` for 核心素養 sampler pool. |
| `src/social_studies/planner.py` | Thin shim over `src.common.planner.plan_core_questions`; provides the 社會領域 system/user templates. |
| `src/social_studies/data_loader.py` | Loads CSV few-shot examples (learning content/performance now via `curriculum_loader`) |
| `src/social_studies/domain_mapping.py` | `內容領域_mapping.csv` is read by the curriculum loader to attach `admitted_by["內容領域"]` tags, by the schema payload, and by the verifier. The sampler no longer reads it directly for either curriculum pool: 學習內容 reads the shared admission lookup (`src/common/admission.py`) and 學習表現 has no 內容領域 parent (#833). |
| `src/social_studies/process_exemplar_loader.py` | Loads Channel-2 JSON exemplars keyed by the four `認知歷程` buckets; invalid or unknown entries fail open. |
| `src/social_studies/interaction_scoring.py` | Scores digital 拖放題 and 滑桿題 responses using their authoritative interaction specs. |
| `src/social_studies/pin_rules.py` | Checks composition constraints for pinned ICCS cognitive-process assignments. |
| `src/social_studies/context_builder.py` | Social studies prompt assembly; `## 課程綱要參考` block injected into system prompt; renders `## 各小題配置` when web/API per-小題 constraints are provided; adds `build_text_system/user_prompt` (文本生成器 stage) and `build_subquestion_system/user_prompt` (per-子題 stage); `build_text_user_prompt` and `build_subquestion_user_prompt` accept `disable_reference_fewshot: bool = False`; original `build_system/user_prompt` retained for correction passes; `build_subquestion_user_prompt` accepts an optional `cfg: SubQuestionConfig` for per-slot LC/LP; explicit codes use hard "不得替換或新增" wording; public `LC_INSTRUCTIONS`/`LP_INSTRUCTIONS` aliases exported. |
| `src/social_studies/sampler.py` | Standalone resolver sampler for grade, 科目, per-小題 題型, curriculum pools, 核心素養, and explicit per-小題 configs. It has no request-wide global 題型 fallback or phantom cognitive-process slot; generation receives the resolver-completed rows. Per-小題 learning-content/performance selections remain raw and may use the global curriculum pool at prompt-build time. |
| `src/social_studies/schemas.py` | Social studies Pydantic models: `ExamQuestion`, `SubQuestion`, `SubQuestionConfig`, `LearningContentRef`, `RubricEntry`, `QuestionSubject` (歷史/地理/公民與社會/跨科), `VerificationResult`, `ImageSpec`. `SubQuestionConfig` includes optional per-小題 `question_type`, `instruction`, `learning_content: list[str]`, `learning_performance: list[str]` (empty = global pool fallback), content/image mode, and per-小題 `question_word_limit` / `option_word_limit` (no `text_word_limit` — that is a request-level field only, ADR 0023); `SubQuestion` includes optional persisted `出題指示`, per-小題 `題目內容類型`, `image_generation_mode`, `圖片`, and `chart_spec`. |
| `src/natural_sciences/cli.py` | CLI entry point (no `--subject` flag; adds `--science-competency` and `--sub-context`; 題型 choices: Simple/Complex-multiple-choice/Constructed-response); `generate_one` runs 文本生成器 → N parallel 子題產生器 stages via `ThreadPoolExecutor`; helpers `_parse_text_shell` / `_parse_subquestion`; optional `sub_client_factory` for test injection; wires the shared ADR 0015 figure-kind declaration/collision policy and trail callback for rendered NS visuals |
| `src/social_studies/cli.py` | CLI entry point for 108課綱 社會領域 generation; `generate_one` runs 文本生成器 → N parallel 子題產生器 stages via `ThreadPoolExecutor`; helpers `_parse_text_shell` / `_parse_subquestion`; optional `sub_client_factory` for test injection |
| `src/natural_sciences/schema_loader.py` | Builds schema dict from `schema_meta.csv` + `schema_parameters.csv`; handles `parent` column on `情境子類別` rows to build the parent-child map used by the sampler |
| `src/natural_sciences/curriculum_loader.py` | Thin shim over `src.common.curriculum_loader`; overrides `allowed_learning_content` / `allowed_learning_performance` to skip subject filtering (科目 is fixed as 自然科學). Owns `grade_to_learning_stage` (grades 3-12 → 學習階段 二/三/四/五; NS has no 第一 stage) and `relevant_cross_concepts` (narrows the 48-entry 跨科概念 taxonomy to the concept groups matching 學習內容-code prefixes; full-taxonomy fallback on empty/unknown codes) |
| `src/natural_sciences/core_competency_loader.py` | Thin shim over `src.common.core_competency_loader`; `NaturalCoreCompetency` enum, subject_prefix `"自"` |
| `src/natural_sciences/planner.py` | Thin shim over `src.common.planner.plan_core_questions`; PISA-Science prompt template (自然科學領域命題教師) |
| `src/natural_sciences/sampler.py` | Standalone PISA-Science resolver sampler: picks grade (學習階段 derived per-question via `grade_to_learning_stage`, so grades 10-12 draw 第五學習階段 pools), 情境 + 情境子類別 (parent-child constrained), 題型, 科學能力 (1–2 of 6: 能力一/二/三 + 環境能力一/二/三), 學習表現 (1–2), and 學習內容 (1–3 preferentially derived from chosen 學習表現 via `對應學習內容`). No 科目 buckets. It resolves explicit subquestion counts/config rows; generation consumes those rows without another draw. |
| `src/natural_sciences/schemas.py` | Pydantic models: `ExamQuestion` (subquestions[], 科學能力, 情境子類別, no 核心素養 at top level), `SubQuestion` (科學能力 replaces 社會領域 核心素養; 科目 fixed as 自然科學), `ScienceCompetency` (6-member enum), `QuestionSubContext`. No `QuestionSubject` enum. Now includes `SubQuestionConfig` (per-小題 overrides: question_type/instruction/content_type/image_generation_mode/figure_kind/question_word_limit/option_word_limit/reporting_scale/LC/LP; no `text_word_limit` — that is a request-level field only, ADR 0023), `ImageSpec.figure_kind`, and the private one-slot figure-policy repair budget — parallel to social studies. |
| `src/natural_sciences/data_loader.py` | Hybrid few-shot loader: scans `data/natural_sciences/few_shot/{q_type}/` for `*.json` and optional `few_shot_examples.csv`; falls back to all subdirs when q_type unknown. Example count is not pinned here — see `data/natural_sciences/few_shot/`. |
| `src/natural_sciences/context_builder.py` | PISA-Science prompt assembly; `curriculum_texts(learning_stage, lc_codes)` builds the `## 課程綱要參考` block (學習內容 + 學習表現 filtered to the grade-derived 學習階段; 跨科概念 narrowed to the sampled codes' concept groups with full-taxonomy fallback), injected into the system prompt; adds `build_text_system/user_prompt` and `build_subquestion_system/user_prompt` for the two-stage pipeline; `build_text_user_prompt` and `build_subquestion_user_prompt` accept `disable_reference_fewshot: bool = False`; original builders retained; `build_subquestion_user_prompt` accepts an optional `cfg: SubQuestionConfig` for per-slot LC/LP; explicit codes use hard "不得替換或新增" wording; public `LC_INSTRUCTIONS`/`LP_INSTRUCTIONS` aliases exported. |
| `src/natural_sciences/curriculum_codes.py` | Deterministic 學習內容/學習表現 code validation (issue #92): normalized lookup over the NS curriculum JSON (Unicode Ⅰ–Ⅴ ↔ ASCII roman-numeral spellings), `canonical_lc/lp`, `repair_lc/lp_refs` (canonicalize valid codes, drop unknown, fall back to the sampled pool), `validate_question_codes`. Parse-time repair runs in `cli.py` `_parse_subquestion`/`_parse_question` (cfg-pinned per-小題 codes stay verbatim); the verifier appends `[課綱代碼檢核]` issues to details and forces `passed=False` on unknown/missing codes; the corrector keeps its metadata freeze but canonicalizes codes on LLM-added subquestions. |
| `src/natural_sciences/verifier.py` | Explicit "寬鬆通過、只攔重大問題" stance — more lenient than math's "明確錯誤"; otherwise parallel architecture (multimodal when chart PNG present) Deterministic `[課綱代碼檢核]` check (issue #92) rejects unknown/missing 學習內容/學習表現 codes regardless of the LLM verdict.  |
| `src/natural_sciences/corrector.py` | Frozen fields: `學習內容/學習表現/科學能力/出題概念/科目/年級`; minimal targeted correction (parallel to social studies corrector) |
| `data/natural_sciences/curriculum/schema_meta.csv` | Natural sciences 學習階段 + grades (runtime-editable) |
| `data/natural_sciences/curriculum/schema_parameters.csv` | Natural sciences parameter values + instructions (情境/情境子類別/題型/科學能力/題目內容類型; `parent` column on 情境子類別) |
| `src/schemas.py` | Math Pydantic models (enums loaded dynamically from `question_schemas.json` at import time). `ExamQuestion` has optional 核心素養 (list[str]), 學習表現 (list[LearningContentItem]), 題目內容類型 (str \| None), 出題概念 (str). `SampledParams` mirrors these plus `subject_filter`. New enums: `CoreCompetency` (27 數-E/J/U-A1..C3 codes built via `src.common.core_competency_loader.build_core_competency_enum`) and `QuestionSubject` (數與量/代數/幾何/統計與機率/跨領域). `ImageSpec` describes the image; `ChartVerificationResult` is nested in `VerificationResult`. |
| `src/sampler.py` | Curriculum-aware math sampler. Loads `data/math/curriculum/` via `src.common.*`. Owns `_MATH_SUBJECT_TO_PREFIXES` (科目→prefix-letter map) and `grade_to_learning_stage(grade)` helper. Samples 核心素養 (1–3), 學習表現 (1–3), 題目內容類型 (1 of 純文字 / 含圖片 / graphs/charts/tables / customized), and optional `subject_filter` alongside the existing 情境/題型種類/題型/數學思考/學習內容/style draws. |
| `src/context_builder.py` | Math prompt assembly. Injects curriculum context (`## 課程綱要參考`) into the system prompt — same pattern as social studies. `build_user_prompt` accepts `user_topic`, `user_passage`, `user_options`, `user_core_question` overrides and returns `(prompt, few_shot_images)`. `CONTENT_TYPE_INSTRUCTIONS` maps the 4 題目內容類型 values to per-prompt instructions. |
| `src/llm_client.py` | OpenAI-compatible API client with model routing; `generate_with_image()` for multimodal (text + PNG) calls; `generate_json(..., agent_override=str)` stamps per-子題 agent ids (`sub_generator#i`) on all streamed events; `emit_stage(obs, agent, stage, status)` emits stage-lifecycle events. `ProviderErrorDetail` (frozen dataclass) and `extract_provider_error(exc, *, provider, model) -> ProviderErrorDetail` normalize all three provider body shapes (Anthropic dict, OpenAI dict, Google list-wrapped). All four `llm_failure` emission sites (`_call`, `generate_image`, `generate_with_tools`, `generate_with_google_search`) call `extract_provider_error` and emit one structured WARNING log (forwarded to Sentry via `LoggingIntegration`); `provider_message` and `raw_body_truncated` are excluded from the log. |
| `src/verifier.py` | Independent answer verification pass |
| `src/corrector.py` | Minimal targeted correction pass for failed-verification questions |
| `src/renderer.py` | matplotlib PNG generation for statistical charts (`render_mode: "chart"`) |
| `src/html_renderer.py` | Playwright HTML→PNG renderer (`render_mode: "html"`) |
| `IMPLEMENTATION_PLAN.md` | Planned refactors and known tech debt |
| `FLOW.md` | ASCII tree of web Generate request lifecycle (frontend click → SSE → queue → worker → result) |
| `LOGIC.md` | Full waterfall execution trace with file + line references |
| `src/data_loader.py` | Curriculum data loading + grade filtering (legacy `data/curriculum/*.json` paths) and the CSV-driven few-shot loader with image-manifest support (`data/few_shot/few_shot_examples.csv` + `images/<id>/manifest.json`), with fallback to per-style JSON. No rubric parsing (math has no 評分規準). |
| `src/verifier.py` (math) | Independent answer verification pass. Module-level `_CURRICULUM_PREFIX` (~93 KB curriculum context) mirrors social studies. Keeps math's stricter "明確錯誤" verification stance — NOT loosened to social studies' "寬鬆通過". |
| `src/corrector.py` (math) | Targeted correction pass. Frozen-fields list extended with 核心素養, 學習內容, 學習表現, 出題概念, 題目內容類型 (alongside existing 情境/題型種類/題型/數學思考). |
| `server/generate/routes.py` `/api/plan-core-questions` | Branches on `body.subject` (`"math"` \| `"social_studies"` \| `"natural_sciences"`, default `"social_studies"`). Math derives `learning_stage` from `body.grade` via `src.sampler.grade_to_learning_stage`. Natural sciences uses `src.natural_sciences.planner.plan_core_questions`. On `CandidateValidationError` → HTTP 502 `{"detail": "<stage message>"}` (unchanged). On any other exception → HTTP 502 `{"failure_class": "<taxonomy code>", "message": "<safe message>"}` (issue #946); raw provider text is never forwarded. `ApiError.failureClass` on the frontend carries the taxonomy code from the response body. |
| `server/generate/routes.py` `/api/generate/resolve` | Authenticated, rate-limited POST that calls the pure ADR 0019 resolver and returns `{payload, drawn}`; field-addressed parent conflicts are HTTP 422. |
| `server/generate/exchange_recorder.py` | `ExchangeRecorder` observer — buffers `llm_request` events per-agent and writes one `LLMExchange` row on the matching `llm_response` or `llm_failure`. `llm_failure` events call `_flush_failure()`, which encodes `ProviderErrorDetail` fields into `response_body["error"]` with `prompt_tokens=None`/`completion_tokens=None`. Thread-safe (parallel `sub_generator#i` workers share one recorder). Persistence failures log a warning and never raise. |
| `server/models.py` `LLMExchange` | New table `llm_exchanges` (FK → `generation_logs.id`, indexed). Columns: `id`, `generation_log_id`, `exchange_order`, `agent`, `purpose`, `request_body`, `response_body`, `model_used`, `prompt_tokens`, `completion_tokens`, `created_at`. |
| `server/generate/routes.py` `/api/generation-logs/{id}/exchanges` | Auth-guarded GET; returns the LLM exchanges owned by the caller, ordered by `exchange_order`. Returns 404 for other users' logs (existence-hiding). |
| `server/app.py` `prune_expired_llm_exchanges` | Startup helper that deletes `llm_exchanges` rows older than `LLM_EXCHANGE_RETENTION_DAYS` (default 30). `0` disables persistence entirely — the recorder is not attached at request time and pruning is skipped. |
| `server/generate/models.py` `GenerateParams` | Accepts all three subjects. NS-specific fields: `sub_context: str \| None`, `science_competency: list[str] \| None`. Per-小題 fields (social studies and natural sciences): `sub_question_count` (3-7), `question_word_limit`, `option_word_limit`, and `subquestion_configs` JSON string; generation requires the resolver-completed count/config rows and does not draw missing values. `disable_reference_fewshot: bool = False` (SS/NS only; when true, skips `load_few_shot_example_groups` in both 文本生成器 and 子題產生器 stages and falls back to the 暫無範例 string). `subject` is plain `str` (accepts `"natural_sciences"`). `PlanCoreQuestionsRequest.subject` is `Literal["math", "social_studies", "natural_sciences"]`. |
| `server/utility/routes.py` `/api/schemas?subject=...` | `subject=math` augments base math schema with `科目` (4 strands), `題目內容類型` (4 entries), and `學習表現` filtered by 學習階段. `subject=natural_sciences` builds schema from `schema_parameters.csv` + curriculum JSON (PISA-Science dimensions: 情境/情境子類別/科學能力/題型/題目內容類型 with 學習表現 and 學習內容 pools). |
| `server/config.py` `ServerConfig.math_curriculum_dir` | Env `MATH_CURRICULUM_DIR`, parallel to `social_studies_curriculum_dir`. `natural_sciences_curriculum_dir` env `NATURAL_SCIENCES_CURRICULUM_DIR` added alongside. |
| `src/config.py` | Environment variable configuration; `subgen_max_concurrency` (env `SUBGEN_MAX_CONCURRENCY`, default 6) caps parallel 子題產生器 calls; `subgen_retries` (env `SUBGEN_RETRIES`, default 1) bounds per-子題 fresh-call retries before a failed slot is dropped |
| `src/cli.py` | CLI entry point (argparse) |

## Code Conventions

- **Language**: Python 3.11+, managed with `uv`
- **Type hints**: Use throughout, Pydantic for data validation
- **Naming**: snake_case for Python. Chinese field names in JSON output match the exam schema (情境, 題型, etc.)
- **Config**: All secrets and endpoints via environment variables, never hardcoded
- **Output schema**: Must match the structure in `test-item.json.example` — the Chinese field names are intentional and required
- **Imports**: Use absolute imports from `src.` package

## Exam Question Schema

### Math question schema

The output JSON follows this structure (Chinese keys are required):

```
情境: 1+ of [個人, 社會時事, 科學, 職業, 建築與藝術, 數學文字情境]
題型種類: one of [單一題, 題組題]
題型: one of [選擇題, 是非題, 封閉式建構反應題, 開放式建構反應題]
數學思考: 1-3 of [形成, 運用, 詮釋評估]
學習內容: 1+ entries with {編碼, 說明} — a single question can span multiple items
題目: array of strings (question text, options, etc.)
正確解題分析: array of strings (step-by-step solution)

# Optional curriculum-aware fields (Phase 3+):
核心素養: list[str]                          # e.g. ["數-J-A2"] (codes only)
學習表現: list[{編碼, 說明}]
題目內容類型: str | None                     # 純文字 / 含圖片 / graphs/charts/tables / customized
出題概念: str

# Optional 題組 fields; emitted only when sub_question_count is supplied:
核心問題: str
文本: str
取材來源: list[str]
subquestions: list[SubQuestion]               # exactly sub_question_count entries
  SubQuestion: {id, 序號, 年級, 題型, 題目, 答案, 答案解析, 誘答分析,
                學習內容, 學習表現, 出題概念}  # math has no 評分規準
```

### Social studies question schema (108課綱)

```
核心問題: string — the essential question driving the 題組
文本: string — the passage / stimulus material
取材來源: array of strings — source citations
情境: 1+ of [個人, 公共, 職業, 教育]
題型種類: 題組題
題型: one of [選擇題, 開放式建構反應題, 拖放題, 滑桿題] — legacy/top-level primary type; subquestions may vary
認知歷程: list[str] | None — ICCS-era discriminator; new values are assigned per subquestion
內容領域: str | None — one of the four ICCS content domains
題目內容類型: one of [純文字, 含圖片, graphs/charts/tables, customized, 混合, 數位閱讀]
target_surface: one of [紙本, 數位]; interactive types require 數位
閱讀歷程: list[str] — legacy-only field, populated only while rendering old records
文本形式: str | None — legacy-only field, populated only while rendering old records
題目: array of strings (legacy flat format — kept for compatibility)
正確解題分析: array of strings (legacy)
subquestions: array of SubQuestion objects (primary format)
  SubQuestion:
    id: string
    序號: int
    年級: int
    科目: list[str] — e.g. ["地理"] or ["歷史", "公民與社會"]
    核心素養: list[str] — e.g. ["社-J-A2"]
    學習內容: list[{編碼, 說明}] — 108課綱 codes e.g. 歷Ka-Ⅳ-1
    學習表現: list[{編碼, 說明}] — e.g. 社1b-Ⅳ-1
    出題概念: string
    出題指示: str | None — submitted per-小題 instruction persisted from subquestion_configs[].instruction
    認知歷程: str | None — one of the four ICCS process buckets
    題型: one of [選擇題, 開放式建構反應題, 拖放題, 滑桿題]
    題目內容類型: str | None — per-小題 content/stimulus type when configured
    image_generation_mode: "html" | "gpt_image" | None — per-小題 renderer override; not an image requirement by itself
    圖片: str | None — rendered per-小題 PNG filename, e.g. {question_id}_sq1.png
    chart_spec: ImageSpec | None — use here when a visual belongs only to this 小題
    題目: string (full question text including options)
    答案: string
    答案解析: string
    評分規準: list[RubricEntry] — for open-response items
      RubricEntry: {code: str (new records: "2"|"1"|"0"; legacy 0..N codes remain readable), 規準說明: str, 學生作答實例: list[str]}
    interaction: DragDropSpec | SliderSpec | None — authoritative digital interaction spec
```

Scoring is native to the format: 選擇題 is 0/1; 開放式建構反應題 uses a fixed 2 / 1 / 0 per-item rubric; 拖放題 scores each correct mapping unless `exact_match=true`; 滑桿題 is 0/1 within `correct_value ± tolerance`. `拖放題` and `滑桿題` are 僅限數位卷面. `interaction` is authoritative; human-readable `答案` remains required.

### Natural sciences question schema (108課綱 自然科學 + PISA)

```
核心問題: string — the essential question driving the 題組
文本: string — the passage / stimulus material
取材來源: array of strings — source citations
情境: 1+ of [Personal, Local-and-national, Global] (PISA-Science contexts)
情境子類別: string | None — PISA sub-context (e.g. 健康, 自然資源, 環境品質); must be a child of the chosen 情境
題型種類: 題組題
題型: one of [Simple-multiple-choice, Complex-multiple-choice, Constructed-response]
科學能力: list[str] — 1–2 of [能力一, 能力二, 能力三, 環境能力一, 環境能力二, 環境能力三]
題目內容類型: str | None
subquestions: array of SubQuestion objects
  SubQuestion:
    id: string
    序號: int
    年級: int
    科目: list[str] — fixed as ["自然科學"] (no 生物/物理/化學/地球科學 branching at question level)
    科學能力: list[str] — per-subquestion capability codes
    核心素養: list[str] — present but not actively sampled (legacy field, typically empty)
    學習內容: list[{編碼, 說明}] — 108課綱 codes e.g. INc-IV-1
    學習表現: list[{編碼, 說明}] — e.g. tr-IV-1
    出題概念: string
    題型: string
    題目: string (full question text including options)
    答案: string
    答案解析: string
    評分規準: list[RubricEntry] — for Constructed-response items
      RubricEntry: {code: "2"|"1"|"0" (new records); "0X" reserved for Complex-multiple-choice; legacy codes remain readable, 規準說明: str, 學生作答實例: list[str]}
```

Constructed-response rubrics use fixed 2 / 1 / 0 levels with 1 / 2 / 1 學生作答實例; shape enforced by `_ns_rubric_shape_check_hook`. `0X` remains for Complex-multiple-choice.

## Curriculum Data Structure

`學習內容.json` is a JSON array of 14 objects, one per grade. Each grade has:
```json
{
  "年級": "7年級",
  "學習內容": [
    {
      "編碼": "N-7-1",
      "學習內容條目及說明": "...",
      "備註": "...",
      "對應學習表現": [{"對應學習表現": "n-IV-1"}]
    }
  ]
}
```

Content codes follow the pattern `{Category}-{Grade}-{Number}`:
- N: 數與量 (Number & Quantity)
- S: 空間與形狀 (Space & Shape)
- G: 坐標幾何 (Coordinate Geometry, grade 8-9 only)
- A: 代數 (Algebra)
- F: 函數 (Function)
- D: 資料與不確定性 (Data & Uncertainty)
- R: 關係 (Relations, elementary only)

### `data/math/curriculum/` (reshaped, used by the shared loader)

The Phase 2 build materializes these four files for the `src.common.*` loaders. Row shape parallels social studies' files:

| File | Shape / size |
|---|---|
| `learning_content.json` | 288 entries across 5 學習階段; rows `{value, 學習階段, 科目, 條目說明, 備註, 對應學習表現}`. `科目` is a single-letter strand prefix N / A / F / R / S / G / D / P (capital = junior/senior high curriculum table, lowercase = 學習表現 codes). |
| `learning_performance.json` | 131 entries; rows `{value, 學習階段, 科目, 說明}`. |
| `core_competencies.json` | 27 數-E/J/U-A1..C3 codes synthesized from the social studies template with `value` rewritten from 社- to 數-. Same outer shape (`學習階段_to_stage`, `面向`, `項目`, `核心素養`). |
| `learning_performance_intro.md` | NAER framework chapter, injected as `### 學習表現架構說明` in the math system prompt. |

All four files are rebuilt reproducibly by `scripts/build_math_curriculum.py` from `data/curriculum/{學習內容,學習表現}.json` (the legacy K-12 sources) plus the social studies core_competencies template.

## Sampler Constraints

**Math:** Allowed values for all parameters come from `question_schemas.json` at the project root. Edit that file to add or remove options — no Python changes required. Override the path with `QUESTION_SCHEMAS_PATH` env var.

**Social studies:** Allowed values come from `data/social_studies/curriculum/schema_parameters.csv` (`類別,value,instruction`). Override the directory with `SOCIAL_STUDIES_CURRICULUM_DIR` env var.

The file has two top-level scalar/array fields:
- **`學習階段`**: string injected into the system prompt (e.g. `"第四學習階段"`)
- **`grades`**: integer array of allowed grade levels (e.g. `[7, 8, 9]`) — drives CLI `--grade` choices, sampler selection, grade content index, and system prompt grade range text

Social studies resolves every request before generation: grade, 情境, 題型種類 (always 題組題), **科目** (歷史/地理/公民與社會/跨科), **內容領域** (one of four ICCS domains), **認知歷程** (four process buckets assigned per 小題), **核心素養**, curriculum pools, `題目內容類型`, `target_surface`, a 3–7 `sub_question_count`, and exactly that many complete `SubQuestionConfig` rows. The resolver owns all blank-value draws; the prompt and generation stages consume those pinned rows. A submitted `subquestion_configs[].question_type`, curriculum selection, instruction, or media/word-limit setting remains authoritative, and interactive types require `target_surface=數位`. Use `--subject`, `--learning-content`, `--learning-performance`, `--core-competency`, and `--text-instruction` to pin values; `--text-instruction` sets the 文本出題指示 for every 題組 (the same field as the web form's `text_instruction`), and a blank or whitespace-only value behaves like omission. Social studies does not use `--style`; the web `subject_filter` query accepts the same subject pool as the CLI.

Social-studies web/API per-小題 controls are encoded as `subquestion_configs`, and batch-wide resolved rows as `per_question_params`, both JSON array strings accepted by `GET /api/generate`. Each array must be structurally valid and complete before generation. The HTTP gate reruns `resolve(payload)` and rejects unresolved paths with HTTP 422; the worker then converts the completed row directly, without merging partial values or invoking a sampler. The confirmation flow remains the place where users edit or redraw pins before submitting the final request. Natural sciences uses the same complete-row contract and PISA-Science 題型 values. The top-level 文本字數限制（題組文本建議值） is available in the 社會領域/自然科學 and 數學 web forms; math does not send `subquestion_configs`.

When randomly selecting parameters, respect these rules:
- **grade**: pick one from `question_schemas.json["grades"]`. `grade_to_learning_stage(grade)` in `src/sampler.py` maps the chosen grade to a 108課綱 學習階段 (一/二/三/四/五).
- **情境**: pick 1 to N (from `question_schemas.json["情境"]`) — multi-select, same pattern as 數學思考
- **題型種類**: pick exactly one (from `question_schemas.json["題型種類"]`)
- **題型**: pick exactly one (from `question_schemas.json["題型"]`)
- **數學思考**: pick 1 to 3 (from `question_schemas.json["數學思考"]`)
- **學習內容**: pick 1–3 entries from `data/math/curriculum/learning_content.json` filtered by 學習階段 + (optional) 科目. The 科目→prefix map lives in `_MATH_SUBJECT_TO_PREFIXES` in `src/sampler.py`.
- **學習表現**: pick 1–3 entries from `data/math/curriculum/learning_performance.json`, filtered identically.
- **核心素養**: pick 1–3 codes from `data/math/curriculum/core_competencies.json` for the selected 學習階段 (數-E-* / 數-J-* / 數-U-*).
- **題目內容類型**: pick exactly one of 純文字 / 含圖片 / graphs/charts/tables (customized is never picked randomly — it's a manual override).
- **subject_filter**: optional 科目 focus (數與量 / 代數 / 幾何 / 統計與機率 / 跨領域); when set, restricts the 學習內容 and 學習表現 draw pools by prefix.
- **Question style**: pick one from `question_schemas.json["question_style"][*].value` — determines which few-shot examples to inject and whether to generate images.

CLI overrides: `--subject-filter`, `--core-competency`, `--learning-content`, `--learning-performance`, `--content-type`, `--topic`, `--passage`, `--options`, `--core-question`, `--image-generation-mode` (in addition to the legacy `--grade`, `--style`, `--q-type`, `--context`, `--set-type` flags). `resolve` accepts the sampling/pin subset of these flags and prints the completed payload before `generate` uses it.

All 5 categories share the same `{value, instruction}` object format. A non-empty `instruction` on any entry is injected into the LLM user prompt: style instructions land under `## 題目風格`; instructions for 情境, 題型種類, 題型, and 數學思考 land under `## 條件補充說明` (section omitted if all instructions are empty).

**Natural sciences:** Allowed values come from `data/natural_sciences/curriculum/schema_parameters.csv` (categories: 情境, 情境子類別, 題型種類, 題型, 科學能力, 題目內容類型). Override the directory with `NATURAL_SCIENCES_CURRICULUM_DIR`.

Natural sciences sampler picks: grade (from `schema_meta.csv`), **情境** (1 from [Personal / Local-and-national / Global]), **情境子類別** (1 from the sub-contexts whose `parent` matches the chosen 情境), **題型種類** (always 題組題), **題型** (Simple-multiple-choice / Complex-multiple-choice / Constructed-response), **科學能力** (1–2 of 6: 能力一/二/三 + 環境能力一/二/三), **題目內容類型** (1 of 純文字 / 含圖片 / graphs/charts/tables; customized is never random), **學習表現_pool** (1–2 codes from `learning_performance.json` filtered by the 學習階段 derived from the sampled grade via `grade_to_learning_stage` — grades 7-9 → 第四學習階段, 10-12 → 第五學習階段), **學習內容_pool** (1–3 codes: first tries to derive from chosen 學習表現 codes' `對應學習內容` cross-links, then falls back to the full stage pool). There is no `--subject` flag and no 科目 bucketing.

CLI overrides: `--science-competency`, `--sub-context`, `--learning-content`, `--learning-performance`, `--content-type`, `--image-generation-mode`, `--grade`, `--q-type`, `--count`, `--batch`, `--seed`, `--no-verify`, `--max-retries`, `--output`, `--dry-run`, `--text-instruction`. `--text-instruction` sets the 文本出題指示 for every 題組 (the same field as the web form's `text_instruction`); a blank or whitespace-only value behaves like omission. The client-free `resolve` subcommand accepts the sampling/pin subset and prints the completed payload first. No `--style` flag (few-shot examples are keyed by 題型 folder, not style).

## Image Rendering Architecture

Images are described by `ImageSpec` (field `chart_spec` on `ExamQuestion`). The `render_mode` field determines the rendering path:

1. **`render_mode: "chart"`** — `render_chart()` in `src/renderer.py` dispatches to hardcoded matplotlib renderers for the 4 supported statistical chart types: `histogram`, `boxplot`, `line_chart`, `pie_chart`. Deterministic; no LLM call required.

2. **`render_mode: "html"`** — `render_image()` calls `_generate_html_via_llm()` (`gemini-3.1-pro-preview` generates a self-contained HTML/CSS/SVG document from `description` + `data`), then `PlaywrightRenderer.render()` in `src/html_renderer.py` screenshots it to PNG. Used for geometry diagrams, tables, menus, and any non-chart visual.

> **Routing rule:** which `render_mode` value the prompt asks the model to emit is codified in [`docs/figure-rendering-policy.md`](docs/figure-rendering-policy.md). Every `src/**/context_builder.py` module cites that doc from its top-level docstring — update the policy first, then the docstrings, then the `CONTENT_TYPE_INSTRUCTIONS` tables.

ADR 0015's layered figure-kind guarantee applies to both 社會領域 and 自然科學: every non-null visual spec that reaches rendering declares free-text `figure_kind`, which is normalized through the shared policy helpers and canonical vocabulary data. The shared policy also compares named series or table columns at overlapping x-values when normalized units match; values differing by more than 5% and 0.1 absolute are treated as a cross-figure data inconsistency, while agreeing zoom/subsets remain valid. Each visual slot gets one shared missing-spec/declaration attempt, each detected collision gets one targeted repair, and one data reconciliation attempt shares that budget; unresolved declarations, collisions, or data inconsistencies are recorded in the subject-agnostic figure-policy trail while images continue to ship. The request-level `allow_duplicate_figure_kinds` kill switch remains available, and the canonical list guides prompts without rejecting useful NS genres such as 電路圖 or 受力圖.
The real 社會領域 pipeline seam is regression-tested in `tests/test_figure_kind_diversity_pipeline_seam.py`.

Orthogonal to `render_mode`, the caller-controlled `image_generation_mode` kwarg on `render_image()` selects the rendering backend:

- `"html"` (default) — use the path described above (matplotlib for `render_mode: "chart"`, Playwright for `render_mode: "html"`).
- `"gpt_image"` — bypass both deterministic paths and send the image spec to `LLMClient.generate_image()` (model from `IMAGE_MODEL`, default `gpt-image2`). Requires `IMAGE_API_KEY`; falls back to `None` (no image) on failure rather than to the Playwright path.
> **UI default vs. API/CLI default:** The web form UI defaults `image_generation_mode` to `gpt_image`; the API and CLI still default to `html`.

Math (`src/cli.py`), social studies (`src/social_studies/cli.py`), and natural sciences (`src/natural_sciences/cli.py`) all thread `image_generation_mode` from the CLI flag `--image-generation-mode` and the HTTP query param of the same name through to `render_image()`. Social-studies web rows can also send per-小題 `image_generation_mode` inside `subquestion_configs`; that value overrides the renderer only for that 小題, while the request-level `image_generation_mode` remains the fallback. The renderer does not trust model-emitted per-小題 image modes over submitted settings.

Social studies has two image locations:
- Top-level `question.chart_spec` renders to `{question_id}.png` and is stored as `question.圖片`.
- Per-小題 `subquestions[*].chart_spec` renders to `{question_id}_sq{序號}.png` and is stored as `subquestions[*].圖片`. `server/generate/service.py` embeds those PNGs as `subquestions[*].image_base64`; the React card displays them inline and ODT export inserts them near the matching 小題.

The entry point is always `render_image()` (`src/renderer.py:271`), called from `generate_one()` in `src/cli.py`.

## Common Commands

```bash
# Install dependencies — runs `uv sync --all-extras --all-groups` (all extras incl. fastapi/sqlalchemy)
# and `uv run playwright install chromium` (browser binary is NOT installed by uv sync alone)
bash scripts/setup.sh

# Run the CLI
uv run python -m src.cli generate

# Run tests
choom -n 500 -- uv run pytest

# Lint
uv run ruff check src/
```

### Full-預抽 guards (ADR 0022)

The runtime completeness gate, static RNG/`sample_params` allowlist, and forwarding RESOLVED/PIN-ONLY classification guard keep 全量預抽 from silently regressing.
The static allowlist lives in `tests/test_generation_sampler_allowlist.py`; its five resolver modules are documented there.
Run these guards with the backend tests, and do not delete the allowlist test as dead weight.

### Test-run memory discipline

The bot container has ~8 GB total for the bot, Codex, and all active worktree lanes.

1. Run test suites in at most 2–3 concurrent lanes; never run pytest in every worktree at once.
2. Prefix pytest and other memory-heavy batch commands with `choom -n 500 --`, e.g. `choom -n 500 -- uv run pytest …` or `choom -n 500 -- npm --prefix web test`.
3. If memory is still tight, bound pytest with `ulimit -v` or reduce concurrency for tests that spawn subprocesses.

`choom` requires no extra privileges; its `oom_score_adj` setting is inherited by children.
The `tests/test_curriculum_context*.py` tests spawn Python subprocesses, so keep their concurrency especially conservative.
If `choom` is unavailable, preserve the lane cap and avoid broad parallel pytest runs.

### Browser marker (`requires_browser`)

Tests that launch a real Playwright Chromium browser are marked `@pytest.mark.requires_browser`.  Before the session runs any such test a single probe is made; if the browser is absent or broken, all marked tests are skipped with a message naming the fix command (`uv run playwright install chromium`), and the cause is written once to the terminal summary.  If no marked tests are collected the probe is skipped entirely, adding no startup cost.

### Postgres marker (`postgres`)

Tests that require a real Postgres 16 instance are marked `@pytest.mark.postgres`.  Before any such test runs the plugin checks for the `TEST_POSTGRES_URL` environment variable; if absent, all marked tests are skipped with a message naming the variable, and the cause is written once to the terminal summary.  If no postgres-marked tests are collected the check is skipped entirely, adding zero startup cost.

Unmarked tests are never affected: they continue to use the default SQLite engine from `server/db.py` (`DATABASE_URL` is intentionally not set by this mechanism).  The dedicated variable `TEST_POSTGRES_URL` (not `DATABASE_URL`) is used because `server/db.py` reads `DATABASE_URL` at import time to build the module-level engine; overriding it would silently route every test that imports `server.db` through Postgres.

To run postgres-marked tests locally you need a Postgres 16 instance.  The easiest way is to start one with `docker run` or to use the bundled `pgserver` package:

```bash
# Option A – Docker
docker run --rm -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16

TEST_POSTGRES_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres \
    uv run pytest -m postgres -v

# Option B – pgserver (bundled in dev dependencies, no Docker needed)
# pgserver listens on a Unix socket; pass the socket directory as the host.
# Example (one-liner):
PGDATA=$(mktemp -d) uv run python -c "
import pgserver, os
s = pgserver.get_server(os.environ['PGDATA'], cleanup_mode=None)
uri = s.get_uri()          # postgresql://postgres:@/postgres?host=<path>
socket_dir = uri.split('?host=')[1]
print(socket_dir)
"
# Then set TEST_POSTGRES_URL to point at the socket (asyncpg host= kwarg form):
# TEST_POSTGRES_URL is not directly the socket URI; use the test fixture below.
```

In CI a Postgres 16 service container is started automatically and `TEST_POSTGRES_URL` is injected by the workflow; no manual setup is required there.  See `docs/adr/0035-run-claim-tests-target-postgres-in-ci.md` and the `services.postgres` block in `.github/workflows/ci.yml`.

### Environment Variables

- `LLM_EXCHANGE_RETENTION_DAYS` (default `30`) — window in days for retaining `llm_exchanges` rows. Set to `0` to disable persistence entirely (no rows written, no pruning).
- `LLM_TIMEOUT_SECONDS` (default `600`) — HTTP timeout in seconds for LLM API calls. Passed as `timeout=` to the OpenAI-compat client constructor. Set to `0` for no timeout.
- `IMAGE_TIMEOUT_SECONDS` (default `300`) — HTTP timeout in seconds for image generation API calls. Passed as `timeout=` to the image OpenAI client constructor.
- `DB_POOL_CHECKOUT_ATTRIBUTION` (default off) — set to `1` or `true` to enable pool-connection checkout attribution. When enabled, each connection checkout records a compact call-stack origin and a timestamp; if a connection is garbage-collected without being returned to the pool, one `WARNING` is emitted to the `server.db_attribution` logger (and forwarded to Sentry by the `LoggingIntegration`). Intended to be **on in staging** (see DEPLOYMENT.md) and **off in production** to avoid the per-checkout `traceback.extract_stack()` cost.

### Staging smoke tests

```bash
# End-to-end staging smoke tests (env-driven; no committed secrets).
bash scripts/smoke_test.sh                          # Full docker-compose auth+generate
BASE_URL=https://examgen-staging.cpeng.me \
  bash scripts/smoke_test_natural_sciences.sh       # Natural-sciences layer probe (issue #94)
```

Each script prints `FRONTEND` / `API` / `PROVIDER` layer prefixes on failure so
red output names the failing layer.

## Execution Logic

Complete waterfall trace of `uv run python -m src.cli generate`. Full reference: [`LOGIC.md`](LOGIC.md). For the web request lifecycle (SSE queue, worker thread, DB logging), see [`FLOW.md`](FLOW.md).

### Phase 1: Bootstrap & Configuration (`src/cli.py`, `src/config.py`)
1. `main()` → `parse_args()` (cli.py:215, 43-70)
2. `Config.from_env()` reads `.env` + env vars: `LLM_API_KEY`/`LLM_BASE_URL`, `GEMINI_API_KEY`/`GEMINI_BASE_URL`, all four `LLM_MODEL_*`/`LLM_EFFORT_*` tiers, `LLM_RATE_LIMIT_DELAY`, `OUTPUT_DIR`, `DATA_DIR`, `SUBGEN_MAX_CONCURRENCY`. The provider-routing section above defines defaults and inheritance.
3. `config.validate()` ensures `LLM_API_KEY` present (cli.py:227)
4. `output_dir.mkdir()` (cli.py:230)

### Phase 2: Data Loading (`src/data_loader.py`, cli.py:233-238)
5. `load_curriculum()` — full K-12 JSON array (data_loader.py:11-14)
6. `load_performance_standards()` — performance standards (data_loader.py:17-20)
7. `load_intro_text()` — curriculum intro markdown (data_loader.py:59-63)
8. Build grade content index `{g: [...] for g in _GRADES}` via `get_grade_content()` (data_loader.py:23-35); `_GRADES` from `question_schemas.json["grades"]`

### Phase 3: LLM Client Init (`src/llm_client.py`, cli.py:241)
9. `LLMClient(config)` initialises an `Anthropic` client (for `claude-*` calls) eagerly and lazily constructs `OpenAI` compat clients for Gemini/OpenAI providers on first use (`src/llm_client.py` `LLMClient.__init__`). Skipped if `--dry-run`.
   Playwright renderer also started here once and reused across questions (cli.py:245-253).

### Phase 4: Generation Loop (`src/cli.py` lines 269-310)

For each question:

**4A. Resolve** — `seed = base_seed + i` if seeded; each partial CLI payload goes through `resolve()` and the completed values are passed directly to generation.

**4B. Completed parameters** — `resolve()` owns the keyed draws for grade, 情境, 題型種類, 題型, 數學思考, curriculum pools, style, and per-小題 fields. Enum values come from the schema loaders. All are overridable via CLI pins; multiple `--q-type` or `--style` values define the resolver's deterministic draw pool.

**4C. Prompt build** (`src/context_builder.py`) —
- `build_system_prompt()`: injects full curriculum JSON + performance JSON + intro text (lines 131-150)
- `build_user_prompt()`: injects sampled params + per-param instructions + style instruction + few-shot examples (lines 153-230). All instructions come from `_INSTRUCTIONS` (built via `schema_loader.build_instructions()` at module import, line 14). Non-empty instructions for 情境/題型種類/題型/數學思考 appear under `## 條件補充說明`; style instruction appears under `## 題目風格`. Both sections are omitted if empty.

**4D. Few-shot injection** —
- `load_few_shot_examples(few_shot_dir, style)` loads ALL `*.json` from `data/few_shot/{style}/` alphabetically (data_loader.py:66-75)
- Flatten arrays; `rng.sample(pool, min(2, len))` picks 1-2 examples (context_builder.py:208-209)

**4E. LLM call #1** — `client.generate_json()` → `openai.chat.completions.create()`, `gemini-3.1-pro-preview`, `reasoning_effort="high"`, `max_tokens=8192`, with temperature omitted

**4F. JSON extraction** — `extract_json()` tries: markdown code block → raw `{` → brute regex (llm_client.py:76-93)

**4G. Parse** — `_parse_question()` builds `ExamQuestion` + `QuestionMetadata` (cli.py:145-212); handles both `image_spec` (new) and `chart_spec` (legacy) field names from LLM output

### Phase 5: Image Rendering + Verification + Correction Loop (`src/renderer.py`, `src/html_renderer.py`, `src/verifier.py`, `src/corrector.py`, cli.py inside `generate_with_corrections`)
Image rendering happens **before** verification so the verifier can see the PNG.

1. If `question.chart_spec` exists: `render_image(spec, path, question_text, html_renderer, llm_client)` (renderer.py:271) first checks effective `image_generation_mode`; `gpt_image` sends the spec to `LLMClient.generate_image()`, while `html` dispatches by `render_mode`:
   - `"chart"` → `render_chart()` (renderer.py:50-71): `histogram/boxplot/line_chart/pie_chart` → hardcoded matplotlib
   - `"html"` → LLM call #2: `_generate_html_via_llm()` (renderer.py:343) asks `gemini-3.1-pro-preview` to write HTML/CSS/SVG; then `html_renderer.render()` (html_renderer.py) screenshots via Playwright
2. Social studies and natural sciences also render each `subquestions[*].chart_spec` before verification, using submitted per-小題 `image_generation_mode` when present and otherwise the request-level fallback. Surviving 小題 retain their original plan-slot configuration and image filename even when earlier slots are dropped.
3. LLM call #3: `verify_question(client, question, chart_image_path)` — sends question + solution + optional PNG via `client.generate_with_image()` (multimodal). Returns `VerificationResult{passed, answer_match, details, my_answer, provided_answer, chart_verification}` where `chart_verification: ChartVerificationResult | None` holds `{chart_data_match, chart_labels_correct, chart_details}` (verifier.py)
4. If `passed=False` and retries remain: `correct_question(client, question, verification, chart_image_path, on_decision=...)` sends the failed question JSON + verifier feedback to the effective correction model (multimodal if chart failed + PNG exists). Subject-specific editable top-level and 小題 fields may change only after complete candidate validation; frozen fields and surviving row identities remain intact. Re-render PNG only for an accepted `chart_spec` change. Re-verify the accepted or retained question and loop up to `max_retries` times, following the correction integrity contract above.

### Phase 7: Output (cli.py:313-330)
- Default: `{question_id}.json` per question (`model_dump_json`, cli.py:315-320)
- `--batch`: single `batch_{timestamp}.json` array (cli.py:323-330)

### LLM Calls Summary

| # | Purpose | Model | File |
|---|---|---|---|
| 0 | Plan 核心問題 candidates (optional; only when called via `/api/plan-core-questions` or upstream of CLI `--core-question`) | `model_plan` | `src/planner.py` + `src/common/planner.py` |
| 1 | Generate question | `model_execute` | `src/llm_client.py` |
| 2 | Generate HTML image (only when `render_mode="html"`) | `model_execute` | `src/renderer.py` |
| 3 | Verify answer + image (multimodal) | `model_verify` | `src/verifier.py` |
| 4 | Correction (when verification fails; multimodal if chart failed) | `model_correct` (inherits execute) | `src/corrector.py` |
> **Social studies & natural sciences:** Call #1 is replaced by a 文本生成器 call (agent `generator`) + N concurrent 子題產生器 calls (agents `sub_generator#1`…`sub_generator#N`), each on its own `LLMClient` instance. Calls #2–4 (image/verify/correct) are unchanged.

Calls 3 + 4 may repeat up to `max_retries` times (default 3, via `LLM_MAX_RETRIES` / `--max-retries`).

### Randomness Summary

Seeded sampler values use independent `draw_rng(seed, field_path, counter)` streams; the 參考範例 selection in each context builder remains a separate prompt-only draw. The sampler paths cover grade, 情境, 題型種類, 題型, curriculum pools, style, and indexed per-小題 fields; `redraws` supplies the counter for the path being 重抽.

## Agent skills

### Issue tracker

Issues live in GitHub Issues at `paulpengtw/exam-generation`, via the `gh` CLI. See `docs/agents/issue-tracker.md`. Issues are closed when the resolving PR merges to `staging` (close manually — `Closes #N` only auto-fires on `main`); see the close convention in that doc.

### Triage labels

Default five-role vocabulary, label string equals role name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.

## 參考範例紀錄 (Reference Example Record) — Issue #670

Each question-generation run now records which few-shot examples were drawn. The record is stored as `reference_example_record_json` (a JSON list) on both `generation_logs` and `generation_records` tables (migration `d9e5f2a3b7c1`).

**Entry kinds:**
- `kind="example"` — a single-question or text few-shot example
- `kind="process_exemplar"` — an SS/NS cognitive-process exemplar

**Data flow:** `build_text_user_fn` / `build_subquestion_user_fn` return 3-tuples `(text, images, entries)`. `generate_one_core` emits each entry via `on_reference_example_entry`. `service.py` captures entries in `capture_reference_example_entry`, stages them to the DB via `ReferenceExampleRecordRecorder`, and persists them in `reference_example_record_json` on the `GenerationRecord`. The history detail API returns the field as `reference_example_record` (the list omits it, #687); `QuestionCard` renders it via `ReferenceExampleRecordSection`.

**RNG allowlist:** All 10 few-shot RNG draws in the context builders are covered by `RNG_ALLOWLIST` in `tests/test_generation_sampler_allowlist.py` and now carry `"; disclosed as 參考範例紀錄"` in their reason strings.
