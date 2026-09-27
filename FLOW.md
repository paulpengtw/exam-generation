# Generate Request Lifecycle

End-to-end trace of `GET /api/generate` from browser button click to rendered question.

> For the CLI-only trace see [`LOGIC.md`](LOGIC.md). The shared per-question pipeline (`generate_with_corrections`, which wraps `generate_one`) is the same in both paths.

## ASCII Flow

```
[Browser]
│
├── User clicks "Generate"  (ParamForm.tsx:201)
│   └── handleSubmit → useGenerate.generate(params)  (useGenerate.ts:87)
│       └── fetchEventSource  GET /api/generate?…  Authorization: Bearer <jwt>
│
▼
[FastAPI — server/generate/routes.py:36]
│
├── Auth: JWT validated, user resolved
├── Parse: GenerateParams from query string
├── DB write #1: INSERT generation_logs {status:"started"}  (routes.py:69-77)
└── Return: EventSourceResponse(event_generator())  (routes.py:109)
    │
    ▼
    [event_generator — routes.py:81]
    └── drives generate_question_stream(…)  (service.py)
        │
        ├── yield SSE: started
        │
        │   [Browser — useGenerate.ts:118-121]
        │   └── status = "generating" → ProgressLog shows spinner
        │
        ├── asyncio.Queue + LLMClient init + cancel_event = threading.Event()
        ├── Pull app_state: html_renderer (Playwright singleton)
        │     html_renderer started once at app startup  (app.py:67-74)
        │
        └── loop.run_in_executor(None, worker)  (service.py)
            │
            ▼
            [worker — runs in ThreadPoolExecutor thread]
            │
            └── for i in range(count):
                │
                ├── 1. sample_params(grade_content, overrides, seed)
                │       (src/sampler.py:21-77)
                │       grade / 情境 / 題型種類 / 題型 / 數學思考 / 學習內容 / style
                │
                ├── 2. build_system_prompt()  (src/context_builder.py:131)
                │       full curriculum JSON + performance JSON + intro text
                │
                ├── 3. build_user_prompt()  (src/context_builder.py:153)
                │       sampled params + per-param instructions + 1-2 few-shot examples
                │       (data/few_shot/{style}/*.json sampled at random)
                │
                ├── 4. LLM call #1 — generate question  (src/llm_client.py:26-40)
                │       model: gemini-3.1-pro-preview  temp: 0.7  max_tokens: 8192
                │       → extract_json() → _parse_question() → ExamQuestion
                │
                ├── 5. [if chart_spec present] render_image()  (src/renderer.py:271)
                │       ├── render_mode="chart" → matplotlib  (renderer.py:50-71)
                │       │     histogram / boxplot / line_chart / pie_chart
                │       └── render_mode="html"
                │             ├── LLM call #2 — generate HTML/CSS/SVG  (renderer.py:343)
                │             └── PlaywrightRenderer.render() → PNG screenshot
                │                   (src/html_renderer.py, reuses app_state singleton)
                │
                ├── 6. [unless skip_verify] verify_question()  (src/verifier.py)
                │       LLM call #3 — multimodal: question + solution + optional PNG
                │       → VerificationResult {passed, answer_match, my_answer, provided_answer,
                │                              chart_verification}
                │
                ├── 7. [if !passed and retries remain] correct + re-verify
                │       (src/cli.py:generate_with_corrections, src/corrector.py)
                │       ├── correct_question(client, question, verification, chart_image_path)
                │       │     LLM call #4 — text-only, or multimodal if chart_verification + PNG
                │       │     → ExamQuestion with only 題目/正確解題分析/chart_spec mutable
                │       ├── re-render PNG only if chart_spec changed
                │       └── verify_question() again → loop up to max_retries times
                │
                ├── 8. Write output files to config.output_dir
                │       {question_id}.json  +  {question_id}.png  (if image)
                │
                ├── [cancel check] is_cancelled() → GenerationCancelled (silent exit)
                │     cancel_event is set by generate_question_stream's finally block
                │     when the consumer disconnects (GeneratorExit / aclose())
                │
                └── 9. queue.put_nowait {event:"result", data: question_json + image_base64}

            [async generator drains queue, yields each event to SSE response]
            │
            ├── yield SSE: result {ExamQuestion JSON + image_base64}
            │
            │   [Browser — useGenerate.ts:125-132]
            │   └── JSON.parse → results[] → QuestionCard renders:
            │         img src="data:image/png;base64,…"  (QuestionCard.tsx:90-96)
            │         題目 text, toggleable 正確解題分析
            │         VerificationBadge (green/yellow)  (QuestionCard.tsx:171-192)
            │         Download buttons (JSON / PNG / ODT)
            │
            └── yield SSE: done

[event_generator finally block]
├── DB write #2: UPDATE generation_logs {status:"completed"|"failed"|"aborted", completed_at}
│     (routes.py:97-107)
└── generate_question_stream finally: cancel_event.set() → workers see is_cancelled()=True
      at their next stage boundary and raise GenerationCancelled (silent exit)
```

## Phase Legend

| Step | File | Lines | Notes |
|------|------|-------|-------|
| Submit button | `web/src/components/ParamForm.tsx` | 201 | `type="submit"` in `<form onSubmit={handleSubmit}>` |
| SSE client open | `web/src/hooks/useGenerate.ts` | 87–150 | `@microsoft/fetch-event-source`, GET with JWT header |
| Event handling | `web/src/hooks/useGenerate.ts` | 112–141 | started / progress / result / error / done |
| Progress display | `web/src/components/ProgressLog.tsx` | 30–62 | spinner, scrollable `<pre>` log |
| Question render | `web/src/components/QuestionCard.tsx` | 39–192 | image, 題目, 解題分析, VerificationBadge, downloads |
| FastAPI route | `server/generate/routes.py` | 36 | `GET /api/generate`, SlowAPI 10/hr per JWT user |
| DB write start | `server/generate/routes.py` | 69–77 | INSERT `generation_logs {status:"started"}` |
| SSE response | `server/generate/routes.py` | 109 | `EventSourceResponse` + `X-Accel-Buffering: no` |
| Worker dispatch | `server/generate/service.py` | — | `loop.run_in_executor(None, worker)` — default thread pool |
| Cancel signal | `server/generate/service.py` | — | `threading.Event cancel_event` per run; set in finally; checked at stage boundaries |
| Playwright singleton | `server/app.py` | 67–74 | started in lifespan, attached to `app.state.html_renderer` |
| DB write finish | `server/generate/routes.py` | 97–107 | UPDATE `generation_logs {status, error, completed_at}` |
| Parameter sampling | `src/sampler.py` | 21–77 | all RNG via `random.Random(seed)` |
| Prompt assembly | `src/context_builder.py` | 131–230 | system + user prompts, few-shot injection |
| LLM call #1 | `src/llm_client.py` | 26–40 | generate question (`gemini-3.1-pro-preview`, temp 0.7) |
| JSON parse | `src/cli.py` | 145–212 | `_parse_question` → `ExamQuestion` |
| Image render | `src/renderer.py` | 271 | entry point `render_image()`, dispatches by `render_mode` |
| chart render | `src/renderer.py` | 50–71 | matplotlib — histogram/boxplot/line_chart/pie_chart |
| LLM call #2 | `src/renderer.py` | 343 | HTML/CSS/SVG generation (html mode only) |
| Playwright render | `src/html_renderer.py` | — | `PlaywrightRenderer.render()` → PNG screenshot |
| LLM call #3 | `src/verifier.py` | — | multimodal verify: question + solution + optional PNG |
| Correction loop | `src/cli.py` | `generate_with_corrections()` | one initial generate_one + ≤ max_retries (correct + re-verify) passes |
| LLM call #4 (correction) | `src/corrector.py` | `correct_question()` | multimodal when chart_verification + PNG exists |
| generate_one | `src/cli.py` | 83–142 | single question generation; called by generate_with_corrections |
| generate_with_corrections | `src/cli.py` | 148–235 | shared pipeline used by both CLI and web server |

## Concurrency Notes

- **Parallel workers per request.** Each question in a batch runs in its own `ThreadPoolExecutor` thread. Multiple requests run fully concurrently.
- **Sync work in a thread.** All LLM calls, file I/O, and Playwright screenshots are synchronous. `run_in_executor` keeps the asyncio event loop unblocked so SSE writes and new connections can proceed while questions are generating.
- **Cooperative cancel on disconnect.** Each run gets a `threading.Event cancel_event`. The generator's `finally` block sets it when the consumer disconnects (`aclose()` / `GeneratorExit`). Worker threads check `is_cancelled()` at stage boundaries and raise `GenerationCancelled` to exit without emitting an error event. The LLM call in progress is NOT interrupted — cancel takes effect only between stages.
- **Playwright singleton.** One browser instance is launched at startup (`app.py:67-74`) and reused across all questions via a renderer pool.

## CLI vs Web

The web server calls subject-specific `do_generate` functions (registered in `SUBJECTS` in `server/generate/subjects.py`) which delegate to `src.common.generation_core.generate_with_corrections_core` — the same pipeline the CLI uses. Both CLI and web go through the same correction loop. The web layer adds:

1. SSE transport (asyncio.Queue bridging thread results to the event loop)
2. JWT auth + rate limiting
3. DB logging (start/finish per request)
4. Base64 image inlining in the result event
5. Cooperative cancel signal (`threading.Event`) per run

## v2 Protocol additions (issues #742–#754)

The flow above reflects the pre-v2 single-question lifecycle.  In v2:

- Requests must carry `stream_version=2` (query or POST body); absent or
  unsupported values return HTTP 426 before any worker starts (see
  `docs/generation-event-protocol.md` §1 and `server/generate/routes.py`).
- Build admission (`X-Frontend-Build-ID`) is checked after `stream_version`
  (see DEPLOYMENT.md §"Build admission").
- `GenerationPublisher` assigns monotonic `event_seq` to every emitted event
  from a single call site; `started` is always seq=1; `done` is last.
- A pre-allocated manifest (`allocate_manifest()`) announces all question IDs
  before worker or planner starts.
- Each question carries a `QuestionSnapshotLedger` that assigns immutable
  `content_revision` values; both `question_update` and `result` carry
  `context.content_revision`.
- Each question produces exactly one `question_terminal` at every worker exit.
- One question's failure never stops sibling workers (batch-planner failure
  is the only batch-fatal path).
- The client decoder (`createGenerationStreamDecoder`) maintains a bounded
  out-of-order buffer (2 s / 256 events / 4 MiB) and degrades rather than
  stalling.

For the compatibility matrix (C0/S0, C0/S1, C1/S0, C1/S1) and buffer bound
details, see `docs/generation-event-protocol.md`.
