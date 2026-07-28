# Natural Sciences Generator — Known Limitations

Status: verified offline against the committed codebase and data files.
Last updated: 2026-07-28.  GitHub issue: #95.

Every claim below names a file or a command whose output the author
observed.  Anything unverified is marked explicitly.

---

## 1. Few-shot pool is severely skewed by item family

The 60 checked-in JSON files break down as follows (verified with
`find data/natural_sciences/few_shot -name '*.json' | sort`):

| Item family | JSON files | Sampling items |
|---|---|---|
| `Constructed-response/` | 47 | 47 |
| `Complex-multiple-choice/` | 10 | 12 |
| `Simple-multiple-choice/` | 3 | 5 |

"Sampling items" counts individual JSON objects (some files in the
`pisa_examples.json` batch contain top-level arrays of multiple items).

The text-generator stage samples `min(2, len(example_groups))` examples
(`src/natural_sciences/context_builder.py`, line 390).  For
`Simple-multiple-choice` with only 5 items, the sampler draws 2 from
those 5, giving just C(5,2) = 10 distinct pairs.  The subquestion-generator
stage draws 1 example at random, so the effective diversity for
`Simple-multiple-choice` is 5 distinct prompts.

Consequence: generated `Simple-multiple-choice` questions will show more
repetition of topic, phrasing, and question structure than the other two
families until more examples are added to
`data/natural_sciences/few_shot/Simple-multiple-choice/`.

---

## 2. NS has no 科目 bucketing — sampler draws from the full stage pool

Social studies draws from subject-specific sub-pools (歷史 / 地理 / 公民
/ 跨科) keyed by `_SUBJECT_TO_PREFIXES` in
`src/social_studies/curriculum_loader.py`.

Natural sciences deliberately omits this mechanism.  Verified in two
places:

- `src/common/subject_spec.py` (the `NATURAL_SCIENCES` spec):
  `subject_to_prefixes = {}` (empty dict).
- `src/natural_sciences/curriculum_loader.py:allowed_learning_content`:
  calls `_base.allowed_learning_content(..., subject_to_prefixes={})`,
  which returns the full stage pool regardless of the `subject` argument.

As a result, `科目` is fixed at `["自然科學"]` on every subquestion, and
the sampler draws `學習內容` from all subjects (生物/物理/化學/地球科學/
理化 and the shared `科目=""` entries) at once.  At the 第五學習階段
(grades 10-12) this is a pool of 426 entries split across four specialised
subject tracks that senior-high students study independently.

Consequence: a single generated question set might cite a `化學` content
code alongside a `地球科學` content code with no subject boundary enforced
by the sampler.  Whether that cross-subject blending is appropriate is a
judgement call for content review.  The PISA framing intentionally
encourages cross-disciplinary contexts, but it is not guaranteed.

---

## 3. NS has no `learning_performance_intro.md` — `### 學習表現架構說明` is omitted

Social studies injects a 5 880-character official NAER chapter into the
system prompt under `### 學習表現架構說明`
(`data/social_studies/curriculum/learning_performance_intro.md`,
loaded by `src/social_studies/context_builder.py` line 55 via
`load_performance_intro()`).

Natural sciences has no such file.  Verified:

```
ls data/natural_sciences/curriculum/learning_performance_intro.md
# → No such file or directory
```

The NS context builder's `_build_curriculum_section` function
(`src/natural_sciences/context_builder.py`, lines 284-297) accepts a
`performance_intro` parameter but immediately discards it with
`del performance_intro`.  The `### 學習表現架構說明` block therefore never
appears in any NS system prompt.

Consequence: the LLM receives no structural explanation of the 99
`學習表現` codes (their 構面, 項目, or coding convention).  Whether this
degrades generation quality compared with social studies is not measurable
offline, but it is a systematic difference from the SS pipeline.

---

## 4. Curriculum codes in few-shot examples — 32 bad references across 15 codes

Running `tests/test_ns_few_shot_curriculum_validation.py` (introduced in
issue #95) validates every `學習內容` and `學習表現` `編碼` in all 60
few-shot JSON files against `data/natural_sciences/curriculum/learning_content.json`
and `learning_performance.json` using `canonical_lc` / `canonical_lp` from
`src/natural_sciences/curriculum_codes.py`.

Result: **32 references to 15 distinct codes do not resolve**.  These appear
in 8 files:

| File | Bad LC codes | Bad LP codes |
|---|---|---|
| `Complex-multiple-choice/pisa_examples.json` | `INa-IV-2`, `INa-IV-3`, `INa-IV-4`, `Lb-IV-4` | `tr-IV-2`, `tm-IV-3` |
| `Simple-multiple-choice/pisa_examples.json` | `Bb-IV-6`, `INc-IV-2`, `INc-IV-4` | `tr-IV-2`, `tm-IV-2` |
| `Constructed-response/weather-proverbs.json` | `Ea-IV-5` | `tr-IV-2`, `pe-IV-5` |
| `Constructed-response/typhoon-database.json` | `Ea-IV-4` | — |
| `Complex-multiple-choice/self-heating-pack.json` | — | `tr-IV-2` |
| `Constructed-response/truck-cornering.json` | — | `tr-IV-2`, `pe-IV-3` |
| `Constructed-response/fasting-method.json` | — | `pe-IV-4` |

Root causes:

- **Off-by-one on existing series**: `Lb-IV` runs to `Lb-IV-3` (not 4),
  `Ea-IV` runs to `Ea-IV-3` (not 4/5), `Bb-IV` runs to `Bb-IV-5` (not 6).
  `pe-IV` runs to `pe-IV-2`; `tr-IV` and `tm-IV` have exactly one entry each
  (`tr-IV-1`, `tm-IV-1`).  The extra-numbered codes appear to be annotation
  errors made when the files were authored.
- **Non-existent prefixes at stage IV**: `INa-IV-*` and `INc-IV-*` have no
  entries in the `第四學習階段` block of the curriculum JSON (these 跨科概念
  codes are present at earlier stages only).

These codes are never used by the runtime sampler (it draws only from
`canonical_lc`/`canonical_lp`-valid entries), so they do not cause
generation failures.  They do, however, inject misleading codes into the
LLM prompt as few-shot labels, since the data loader passes them through
without validation.  Correcting the files requires a human content review.

---

## 5. Schema drift between few-shot files and production Pydantic model

Attempting `ExamQuestion(**q)` for each of the 64 JSON items across all
60 few-shot files yields:

- 16 items parse cleanly.
- 48 items fail with one or more Pydantic validation errors, all falling
  into two categories:

  **`情境子類別` enum mismatch (48 failures)**: Many files use
  `情境子類別` strings that are not in the current `QuestionSubContext`
  enum (built from `data/natural_sciences/curriculum/schema_parameters.csv`).
  The offending values are a mix of outdated English PISA subcontext labels
  (e.g. `"Climate change"`, `"Nature of science and technology"`,
  `"Food production and distribution"`) and Chinese custom values
  (e.g. `"台灣天氣與災害"`, `"學校實驗室探究活動"`, `"生活中的化學與物質性質探究"`).
  The current enum lists 52 English PISA subcontext values; none of the
  Chinese values appear there.

  **`RubricEntry` field name mismatch (538 validation error messages across
  48 items)**: Few-shot files encode rubric entries as
  `{"編碼": "2", "說明": "..."}` (a legacy format) while the Pydantic
  `RubricEntry` model in `src/natural_sciences/schemas.py` (lines 57-62)
  expects `{"code": "2", "規準說明": "..."}`.  The CLI's
  `_parse_subquestion` reads `r.get("code", "")` and `r.get("規準說明", "")`,
  so LLM output must use the new field names; the few-shot examples
  demonstrating the old names may subtly confuse the model on rubric format.

Neither type of failure has been observed to block generation in practice
(the data loader passes raw dicts to the prompt without Pydantic parsing),
but the field-name discrepancy is a prompt consistency risk.  Fixing the
few-shot files to use the `code`/`規準說明` format and to register Chinese
subcontexts in `schema_parameters.csv` are tracked human tasks.

---

## 6. Few-shot files contain empty `學習表現` lists on some subquestions

Scanning all 64 items: approximately one-third of subquestions across the
Constructed-response and Complex-multiple-choice families have
`"學習表現": []`.  The existing test
`tests/test_natural_sciences_few_shot.py::test_subquestions_have_learning_codes`
only checks that the field is not `None` (not that it is non-empty), so
these pass.

Consequence: when the LLM imitates those few-shot examples it may also
emit empty `學習表現` lists, which the verifier then flags as a
`[課綱代碼檢核]` issue (see `src/natural_sciences/verifier.py`), potentially
triggering unnecessary correction retries.  The extent of this effect is
not measurable offline.

---

## Not yet measured — requires live LLM runs and staging data

The following three acceptance criteria from GitHub issue #95 are
**intentionally out of scope for this offline audit** because they require
live LLM generation calls and access to staging output that is not
available in this environment:

1. **Natural-sciences generation quality reviewed with sample outputs
   across all three item families.**  Requires running the generator with a
   real LLM API key and manually reviewing outputs.

2. **Prompt cost and latency measured.**  Requires live API calls with token
   counting enabled (or server-side `llm_exchanges` log analysis against a
   staging database).

3. **Rollout decision based on staging examples, verifier pass rate, and
   manual content review.**  A go/no-go decision cannot be made from
   offline analysis alone.

These items remain open for the team to complete in a staging environment.
