# #761: recheck after reported removal of overrides

The operator reported that the no-override version was deployed. A fresh
ego-browser request to staging `/api/models` returned HTTP 200, with:

```json
{
  "plan": "",
  "execute": "",
  "verify": "claude-opus-4-6",
  "correct": "",
  "effort_plan": "high",
  "effort_execute": "high",
  "effort_verify": "high",
  "effort_correct": ""
}
```

See [models.json](models.json) for the timestamp and full credential-free response.
Gemini remains first in the allowed roster. Plan and execute still fail #761's
required defaults; no generation was submitted and no preferences were changed.

Staging's GitHub head is still `ad80b9bc0af2321ad22751dcbf3e8fcc4015d7ac`.
Both configuration readers at that revision use
`os.environ.get("LLM_MODEL_PLAN", DEFAULT_MODEL_PLAN)` and the equivalent
execute lookup. An explicitly empty environment variable therefore overrides
the code default. The endpoint directly returns these configuration values.

The response is consistent with empty override entries. Deployment variables
were not inspected, so their exact source was not independently established.
The operator should remove the `LLM_MODEL_PLAN` and `LLM_MODEL_EXECUTE` entries
entirely, including any inherited/shared definitions, and redeploy. The expected
endpoint values are `claude-opus-4-6` and `gemini-3.1-pro-preview` respectively.

The acceptance check remains pending. No GitHub comments or issue-state changes
were made.
