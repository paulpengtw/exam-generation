# Generate Request Lifecycle

End-to-end trace of `GET /api/generate` from browser button click to rendered question.

> For the CLI-only trace see [`LOGIC.md`](LOGIC.md). The shared per-question pipeline (`generate_one`) is the same in both paths.

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
    └── drives generate_question_stream(…)  (service.py:88)
        │
        ├── Claim ordinal: _QUEUE_TOTAL += 1  (service.py:104)
        │
        ├── [while jobs_ahead > 0]  (service.py:109-115)
        │   ├── yield SSE: queued {jobs_ahead}
        │   └── await _QUEUE_CHANGED  (wakes when previous request finishes)
        │
        │   [Browser — useGenerate.ts:112-117]
        │   └── status = "queued" → ProgressLog shows "N jobs ahead" badge
        │
        ├── Acquire _GEN_LOCK  (service.py:117)  ← single concurrent generation
        ├── yield SSE: started
        │
        │   [Browser — useGenerate.ts:118-121]
        │   └── status = "generating" → ProgressLog shows spinner
        │
        ├── asyncio.Queue + LLMClient init  (service.py:121-123)
        ├── Pull app_state: curriculum, html_renderer (Playwright singleton)
        │     html_renderer started once at app startup  (app.py:67-74)
        │
        └── loop.run_in_executor(None, worker)  (service.py:197)
            │
            ▼
            [worker — runs in ThreadPoolExecutor thread]
            │
            ├── sys.stderr = _QueueWriter(loop, queue)  (service.py:150-151)
            │     every print(…, file=sys.stderr) → SSE progress event
            │     via loop.call_soon_threadsafe(queue.put_nowait, …)
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
                │       model: claude-sonnet-4-6  temp: 0.7  max_tokens: 8192
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
                │       → VerificationResult {passed, answer_match, chart_verification}
                │
                ├── 7. Write output files to config.output_dir
                │       {question_id}.json  +  {question_id}.png  (if image)
                │
                └── 8. queue.put_nowait {event:"result", data: question_json + image_base64}
                          (service.py:188-190)

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
├── DB write #2: UPDATE generation_logs {status:"completed"|"failed", completed_at}
│     (routes.py:97-107)
└── _QUEUE_DONE += 1 ; _QUEUE_CHANGED.set()  (service.py:207-209)
      wakes all queued waiters → they re-emit updated jobs_ahead count
```

## Phase Legend

| Step | File | Lines | Notes |
|------|------|-------|-------|
| Submit button | `web/src/components/ParamForm.tsx` | 201 | `type="submit"` in `<form onSubmit={handleSubmit}>` |
| SSE client open | `web/src/hooks/useGenerate.ts` | 87–150 | `@microsoft/fetch-event-source`, GET with JWT header |
| Event handling | `web/src/hooks/useGenerate.ts` | 112–141 | queued / started / progress / result / error / done |
| Progress display | `web/src/components/ProgressLog.tsx` | 30–62 | queue badge, spinner, scrollable `<pre>` log |
| Question render | `web/src/components/QuestionCard.tsx` | 39–192 | image, 題目, 解題分析, VerificationBadge, downloads |
| FastAPI route | `server/generate/routes.py` | 36 | `GET /api/generate`, SlowAPI 10/hr per JWT user |
| DB write start | `server/generate/routes.py` | 69–77 | INSERT `generation_logs {status:"started"}` |
| SSE response | `server/generate/routes.py` | 109 | `EventSourceResponse` + `X-Accel-Buffering: no` |
| Queue counters | `server/generate/service.py` | 41–44 | `_GEN_LOCK`, `_QUEUE_TOTAL/DONE`, `_QUEUE_CHANGED` — in-process only |
| Queue wait loop | `server/generate/service.py` | 104–115 | emits `queued` events, awaits `_QUEUE_CHANGED` |
| Lock acquire | `server/generate/service.py` | 117 | `asyncio.Lock` — one generation at a time |
| Worker dispatch | `server/generate/service.py` | 197 | `loop.run_in_executor(None, worker)` — default thread pool |
| stderr hijack | `server/generate/service.py` | 150–151 | `sys.stderr = _QueueWriter` bridges thread prints → SSE |
| Queue release | `server/generate/service.py` | 207–209 | `_QUEUE_DONE += 1; _QUEUE_CHANGED.set()` |
| Playwright singleton | `server/app.py` | 67–74 | started in lifespan, attached to `app.state.html_renderer` |
| DB write finish | `server/generate/routes.py` | 97–107 | UPDATE `generation_logs {status, error, completed_at}` |
| Parameter sampling | `src/sampler.py` | 21–77 | all RNG via `random.Random(seed)` |
| Prompt assembly | `src/context_builder.py` | 131–230 | system + user prompts, few-shot injection |
| LLM call #1 | `src/llm_client.py` | 26–40 | generate question (Sonnet, temp 0.7) |
| JSON parse | `src/cli.py` | 145–212 | `_parse_question` → `ExamQuestion` |
| Image render | `src/renderer.py` | 271 | entry point `render_image()`, dispatches by `render_mode` |
| chart render | `src/renderer.py` | 50–71 | matplotlib — histogram/boxplot/line_chart/pie_chart |
| LLM call #2 | `src/renderer.py` | 343 | HTML/CSS/SVG generation (html mode only) |
| Playwright render | `src/html_renderer.py` | — | `PlaywrightRenderer.render()` → PNG screenshot |
| LLM call #3 | `src/verifier.py` | — | multimodal verify: question + solution + optional PNG |
| generate_one | `src/cli.py` | 83–142 | shared pipeline used by both CLI and web server |

## Concurrency Notes

- **In-process queue only.** `_GEN_LOCK`, `_QUEUE_TOTAL`, `_QUEUE_DONE`, `_QUEUE_CHANGED` live in `service.py` module globals. Multi-worker deployments (e.g. `uvicorn --workers 4`) would have separate counters per process — jobs_ahead counts would be wrong. Use a single worker (`--workers 1`) or replace with Redis if scaling is needed.
- **One generation at a time.** The lock is required because `sys.stderr` is process-global. Concurrent generations would interleave progress lines across SSE streams.
- **Sync work in a thread.** All LLM calls, file I/O, and Playwright screenshots are synchronous. `run_in_executor` keeps the asyncio event loop unblocked so SSE writes and new connections can proceed while a question is generating.
- **Playwright singleton.** One browser instance is launched at startup (`app.py:67-74`) and reused across all questions. It is not thread-safe; access is serialised by `_GEN_LOCK`.

## CLI vs Web

The web server calls `src.cli.generate_one()` directly (`service.py:166-178`) — the same function the CLI loop body calls. The web layer adds:

1. SSE transport (queue + `_QueueWriter` stderr bridge)
2. In-process queue with position tracking
3. JWT auth + rate limiting
4. DB logging (start/finish per request)
5. Base64 image inlining in the result event
