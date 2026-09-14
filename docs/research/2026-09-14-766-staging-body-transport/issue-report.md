Live acceptance completed on **2026-09-14, 15:21–15:44 Asia/Taipei**. The core body-transport and full-batch History checks pass; two independent findings are tracked below.

Hard refresh loaded **`8941814b7973428a485d39c1a5d2b90fd52ddcad`** (PR #768 merge), asset `index-BRzyNnVX.js`. Staging deployment **6432290186** succeeded at 07:19:59 UTC. Used one ego-browser TaskSpace (12) and the existing signed-in supervisor session. Sentry inspection used the already-configured read-only `sentry-cli` credentials; no credentials were exported.

| Real UI run | JSON body bytes | Equivalent GET target bytes | Preview / generation | Result |
|---|---:|---:|---|---|
| SS original | 10,222 | 20,314 | POST 200 / POST 200 | 2 題組 × 3 小題 |
| NS original | 9,882 | 19,917 | POST 200 / POST 200 | 2 題組 × 3 小題 |
| Math smoke | 1,641 | 2,920 | POST 200 / POST 200 | 1 question |
| SS History replay | 10,222 | 20,314 | POST 200 / POST 200 | 2 題組 × 3 小題 |
| NS History replay | 9,944 | 19,995 | POST 200 / POST 200 | 2 題組 × 3 小題 |

Both SS/NS forms included long synthetic Chinese 文本出題指示 and per-小題 出題指示. Actual paths stayed at 21 bytes (`/api/generate/preview`) and 13 bytes (`/api/generate`). Equivalent GET sizes use `URLSearchParams`, repeated array keys and UTF-8 path+query length; preview equivalents are 8 bytes larger. **No 414.** Each submission opened **one** generation request, with one `started`, the expected results, one `done`, zero SSE error events and visible results. The fetch abort following `done` is normal cleanup.

**Exact History comparisons:** all **nine completed records** preserve every submitted value; **zero changed/missing values** after decoding JSON-string fields. All batch and 小題 rows, order, seeds, curriculum, contexts/subcontext, types/counts, math thinking/competencies, Reporting Scale, limits, instructions, media and `drawn` provenance were compared. Both actual History → 重新帶入 flows returned **`drawn=[]`, `cleared=[]`**. Entire restored batches match; original and replay saved parameter objects are semantically identical. NS outputs retain per-slot scales **2/3/4**.

| Run | History records |
|---|---|
| SS original | [1](https://examgen-staging.cpeng.me/history/cfe53c47-b73e-4dd0-bdc5-0c4bf5f7d2db), [2](https://examgen-staging.cpeng.me/history/46595a62-3163-4723-8fdb-0c437f95f1e0) |
| SS replay | [1](https://examgen-staging.cpeng.me/history/8b5ec211-666f-4a11-ae33-1d3a7e2b2eca), [2](https://examgen-staging.cpeng.me/history/b96a683c-82ab-408a-95f6-c448e297455d) |
| NS original | [1](https://examgen-staging.cpeng.me/history/c2a0a542-c872-4b0f-884d-8c6e656b5c8b), [2](https://examgen-staging.cpeng.me/history/fb7fd9d6-bd56-413f-bc45-49ac6396d70e) |
| NS replay | [1](https://examgen-staging.cpeng.me/history/1ab3c3ce-ca78-484c-96fb-684f990ad353), [2](https://examgen-staging.cpeng.me/history/d320e8c7-7da0-43d9-832a-ecb4417c815e) |
| Math | [completed](https://examgen-staging.cpeng.me/history/d00692d7-7ce5-475e-93ac-b4d7b8b35142) |

**Defaults are separate from value changes.** Explicit `image_generation_mode=html` was preserved. NS replay additionally submits the two saved row `coverage_mode=balanced` defaults, explaining its size increase; other omitted top-level defaults are restored identically by persistence.

<details><summary>Exact serialization additions for each original saved record</summary>

```json
{
  "ss-original": {
    "non_null_additions": {
      "$.allow_duplicate_figure_kinds": false,
      "$.max_retries": 3
    },
    "null_addition_paths": [
      "$.content_domain",
      "$.core_competency",
      "$.difficulty",
      "$.effort_correct",
      "$.effort_verify",
      "$.learning_content",
      "$.learning_performance",
      "$.math_thinking",
      "$.model_correct",
      "$.model_execute",
      "$.model_plan",
      "$.option_word_limit",
      "$.options",
      "$.passage",
      "$.question_word_limit",
      "$.reporting_scale",
      "$.science_competency",
      "$.sub_context",
      "$.target_surface"
    ]
  },
  "ns-original": {
    "non_null_additions": {
      "$.allow_duplicate_figure_kinds": false,
      "$.coverage_mode": "balanced",
      "$.max_retries": 3,
      "$.per_question_params[0].coverage_mode": "balanced",
      "$.per_question_params[1].coverage_mode": "balanced"
    },
    "null_addition_paths": [
      "$.content_domain",
      "$.core_competency",
      "$.difficulty",
      "$.effort_correct",
      "$.effort_verify",
      "$.learning_content",
      "$.learning_performance",
      "$.math_thinking",
      "$.model_correct",
      "$.model_execute",
      "$.model_plan",
      "$.option_word_limit",
      "$.options",
      "$.passage",
      "$.question_word_limit",
      "$.subject_filter",
      "$.target_surface"
    ]
  },
  "math-original": {
    "non_null_additions": {
      "$.allow_duplicate_figure_kinds": false,
      "$.core_question_callback": true,
      "$.coverage_mode": "balanced",
      "$.disable_reference_fewshot": false,
      "$.max_retries": 3,
      "$.per_question_params[0].coverage_mode": "balanced",
      "$.per_question_params[0].disable_reference_fewshot": false
    },
    "null_addition_paths": [
      "$.content_domain",
      "$.core_competency",
      "$.difficulty",
      "$.effort_correct",
      "$.effort_verify",
      "$.learning_content",
      "$.learning_performance",
      "$.math_thinking",
      "$.model_correct",
      "$.model_execute",
      "$.model_plan",
      "$.option_word_limit",
      "$.options",
      "$.passage",
      "$.question_word_limit",
      "$.reporting_scale",
      "$.science_competency",
      "$.sub_context",
      "$.sub_question_count",
      "$.subquestion_configs",
      "$.target_surface",
      "$.text_instruction",
      "$.text_word_limit"
    ]
  }
}
```

</details>

**Rejection / cancellation:** anonymous POST preview and generation returned 401 without SSE. Authenticated NS omission returned 422 at `per_question_params[1].subquestion_configs[2].learning_content` for both endpoints. Actual math UI showed `Incomplete request: per_question_params[0].數學思考 (unresolved)`, one rejected request, no generation/reconnect. A complete **3,001-byte legacy GET** returned 200 and began streaming; clicking History during generation aborted it without reconnect or `done`. [Cancellation record](https://examgen-staging.cpeng.me/history/f658a7ef-a6c8-4f4c-b60f-e0188e6efa69) is `aborted`. Full GET completion remains covered by #768's automated checks.

**Sentry / ADR 0004:** live frontend collection settings exclude bodies and gen-AI inputs/outputs. Seventy observed frontend envelopes contained no instruction marker or request-body field. Seven retrieved Sentry events (five backend warnings, two expected frontend rejection errors) contain no test instruction/topic or request body. Backend spans: 1,725 queried, 77 with model metadata; `has:` counts are **0** for input messages, output messages, prompts, system instructions and response text. Compressed replay recordings were not decoded; legacy transaction-detail lookups returned 404, so the findings use actual error-event bodies and span-presence queries.

**Follow-ups / limits:**
- **#787:** standard Pydantic error arrays still display only generic HTTP 422; canonical resolver field errors display correctly.
- **#789:** [API-STAGING-J](https://cpengme.sentry.io/issues/7730828215/) has five blank `llm_exchanges insert failed:` warnings. They did not prevent these generations or History writes; eventual exchange loss is unproven.
- SS completed after exhausting correction retries with `verification.passed=false` in both original/replay runs. NS and math passed verification. Transport acceptance does not certify SS question correctness.

Reproducible sanitized artifacts are saved locally in `docs/research/2026-09-14-766-staging-body-transport/`: README, four captures, `compare.py`, exact `comparisons.json`, and two Sentry evidence files. `python3 …/compare.py` verifies all five completed runs, nine records and the GET cancellation; JSON/credential-pattern/privacy audits pass. No application code or deployment was changed, and #759 was not touched. No remaining deployment/login blocker. **#756 remains open for its broader acceptance scope.**
