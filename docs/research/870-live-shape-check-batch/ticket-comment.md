# Ticket comment — #870 "Without credentials" criterion

> Post this as a comment on issue #870 when credentials are unavailable.

---

No numbers are posted for the live shape-check batch because the API credentials
needed to run the generation pipeline are not available in this environment:

- **Anthropic account credit exhausted.** A credential probe against the Anthropic
  API returns HTTP 400 with the message "Your credit balance is too low". Verification
  and planning (claude-opus-4-6) cannot run.

- **GEMINI_API_KEY not configured.** The default execute model is
  `gemini-3.1-pro-preview`. `GEMINI_API_KEY` is not set in `.env`, so generation
  calls would also fail.

The batch script (`scripts/research/rubric_870_live_batch.py`) is committed on the
branch and exits early with a clear error message in either of these conditions
without writing any numbers.

To rerun once credentials are restored, from the repository root:

```
uv run python scripts/research/rubric_870_live_batch.py
```

Required environment variables:

| Variable | Purpose |
|----------|---------|
| `LLM_API_KEY` | Anthropic API key (verification + planning) |
| `GEMINI_API_KEY` | Gemini API key (generation; or override `LLM_MODEL_EXECUTE`) |

Results will be written to `docs/research/870-live-shape-check-batch/results.json`
and printed to stdout. Post the numbers as a follow-up comment on issue #870 and on
the map issue #646.
