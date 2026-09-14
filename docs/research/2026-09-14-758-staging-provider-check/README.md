# Issue #758: live staging provider check

On 2026-09-14, ego-browser hard-refreshed staging after PR #765 was deployed at merge commit `2586e1defb5c76863741d8201611693978cf9b74` (successful GitHub deployment 6431460500).

The real planner API returned HTTP 200 with three candidates using the configured Opus 4.6 default. A single text-only math generation then used explicit `claude-opus-4-6` with high effort for generation and verification. Both streamed request records carried only `thinking={"type":"adaptive"}` plus `max_tokens=16384` and effective `temperature=null`.

| Stage | Output tokens | Thinking chunks | Summary characters |
|---|---:|---:|---:|
| Generation | 12443 | 1470 | 11252 |
| Verification | 470 | 37 | 348 |

The UI displayed the thinking summaries. The completed response parsed as JSON, including a generation response larger than the old 8192-token ceiling. Verification passed with a matching answer. There were no SSE error events or correction calls. The operation took about four minutes.

The [saved history record](https://examgen-staging.cpeng.me/history/6d5b5d23-2b0f-43c5-9bf7-f2b905947fed) is completed and verified, with question id `q_20260914_061457_001`.

Files:

- `question.json`: the question downloaded from the result card, including its verifier verdict.
- `browser-evidence.json`: sanitized request parameters, token usage, event counts, deployment, planner response, and persisted record identity. It contains no authentication token or provider key. The captured `AbortError` follows the successful SSE `done` event: the UI aborts its fetch in the done handler. It is not an SSE provider error.

The operator confirmed that `LLM_TEMPERATURE` was **unset**. The live run therefore does not measure an explicitly non-default temperature combined with adaptive thinking. That portion of #758 remains unperformed; the guard currently rests on automated SDK-boundary tests and [Anthropic's documented thinking/sampling restriction](https://platform.claude.com/docs/en/build-with-claude/thinking). The server-tool call site was covered by automated tests, not this math smoke test. No keys were read from the checkout. Model-picker defaults were restored after testing.
