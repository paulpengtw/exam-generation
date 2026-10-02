# Fixed-slot generation integrity and failure evidence (#975–#978) — Design

**Sources:** [#975](https://github.com/paulpengtw/exam-generation/issues/975),
[#976](https://github.com/paulpengtw/exam-generation/issues/976),
[#977](https://github.com/paulpengtw/exam-generation/issues/977), and
[#978](https://github.com/paulpengtw/exam-generation/issues/978).

**Base:** `origin/staging` at `f28ab81f5216fc84abc695efcfe41a1b4ff64fd3`.

**Constraints:** deterministic fake-provider and fake-renderer coverage only; no live LLM,
image-provider, staging-login, or paid API call. Existing bounded retry counts, sibling
independence, cancellation semantics, detached-run protocol, and fixed manifest identities
remain unchanged.

## Batch boundary

The complete `ready-for-agent` batch is split into two implementation subprojects so the
shared generation changes and unrelated frontend timing diagnoses do not share a review or
rollback boundary.

This specification covers the first subproject, #975–#978. #976 is the umbrella outcome and
is satisfied by the concrete recovery and evidence work in #977 and #978, including the
cross-subject Social Studies reproduction in its issue comment.

The second subproject will separately specify and implement #962, #965, and #972–#974.
#965 will not receive a speculative timeout increase: implementation requires a repeatable
failure or a deterministic contention harness that demonstrates the failing assertion.

Issues #861–#863, #874, #876–#878, and #884 are excluded because their acceptance criteria
require live LLM calls or provider credit. #505 is excluded because it is blocked on
human-authored content which agents are explicitly prohibited from creating.

## Problem

The fixed-slot pipeline correctly owns slot identity, but it does not yet enforce all
slot-owned content constraints at one authoritative admission point:

1. A Natural Sciences slot pinned to `純文字` can retain a model-emitted `chart_spec`. The
   downstream figure-policy hook then repairs the spec and renders an image, spending an
   unrequested image call and adding an image obligation that did not exist in the submitted
   configuration.
2. Both Natural Sciences and Social Studies parsers pass scalar `學生作答實例` values to a
   list field. The resulting safe validation error is recorded locally, but the unchanged
   retry prompt gives the model no repair feedback.
3. Fixed-slot identity is restored after parsing, while other pins and the required open-
   response rubric shape are enforced in several subject-specific places or only during
   later verification. A structurally unacceptable retry can therefore consume the final
   attempt without a single slot-contract decision point.
4. The final safe failure reason is emitted as a stage message and then discarded. Terminal
   construction sees only that the manifest slot is absent and substitutes
   `subquestion not delivered`; the same generic value is persisted to History and shown to
   the teacher.

The design makes slot admission a narrow, deterministic boundary and carries a structured,
safe failure sidecar through the terminal path already established by
[ADR 0016](https://github.com/paulpengtw/exam-generation/blob/staging/docs/adr/0016-verification-trail-is-persisted-first-class.md).

## Invariants

- Resolver-owned and slot-owned values outrank model output.
- A fixed slot is admitted only under its original manifest identity and zero-based transport
  position.
- `content_type=純文字` creates no image obligation, regardless of request-level or
  model-emitted image mode.
- Safe normalization is narrow and lossless. A scalar string may become a one-entry string
  list; arbitrary objects, numbers, malformed rubric rows, or duplicate rubric codes are not
  accepted.
- Retry feedback contains only allow-listed field/type/shape information. It never contains
  a prompt, response, provider message, credentials, reasoning, or arbitrary exception text.
- Successful and recovered subquestions produce no failure evidence.
- A dropped slot does not fail or renumber its siblings.
- Terminal evidence, persisted History evidence, and the UI use the same slot identity and
  failure classification.
- Client disconnect remains a transport observation, not proof of cancellation. Only the
  existing confirmed-cancellation path produces a cancelled terminal.

## Considered approaches

### A. Prompt-only reinforcement

Add stronger pure-text, rubric, and retry instructions to subject prompts. This is rejected
because the observed prompts already contained the pure-text constraint, model output is not
authoritative, and prompt compliance cannot protect image cost or terminal accounting.

### B. Subject-local fixes

Patch Natural Sciences parsing/rendering and separately teach each subject to persist errors.
This is rejected because the scalar-rubric and generic-terminal failures reproduce across
Natural Sciences and Social Studies, and duplicated policy would drift.

### C. Shared fixed-slot admission plus structured failure evidence — selected

Use one shared slot-contract seam after subject parsing and again after accepted correction,
while keeping domain-specific curriculum pin construction in the subject parsers. Reuse the
existing stage observer as the generation-to-service handoff for a structured, sanitized
failure sidecar. This centralizes policy without importing `server/` into `src/` or adding a
second persistence protocol.

## Design

### 1. Narrow rubric normalization at the parser boundary

A shared pure helper normalizes only `評分規準[*].學生作答實例` values that are strings:

```text
"學生作答實例": "學生回答"  ->  "學生作答實例": ["學生回答"]
```

Lists remain lists. Every other value remains invalid and reaches Pydantic validation. Both
subject parsers call the helper on their copied/raw rubric rows before constructing
`RubricEntry`; the provider response object is not mutated.

After Pydantic parsing, fixed open-response slots run the existing shared rubric-shape checker
before admission. The accepted shape remains exactly one `2`, one `1`, and one `0` row with
the existing per-level example counts and fixed `[2]` sentence. The first bounded, safe shape
message becomes a `SubquestionParseError`; the full malformed rubric is never included.

This admits the recoverable scalar case without weakening schemas while rejecting duplicate
codes such as `2 / 1 / 1 / 0` early enough to inform the remaining retry.

### 2. One fixed-slot contract seam

The shared generation core expands its current fixed-identity step into a fixed-slot contract
function. Given the plan position and its submitted `SubQuestionConfig`, it applies, in order:

1. program-owned `id`, `序號`, and private `_plan_index`;
2. configured question type;
3. configured content type;
4. pure-text visual suppression; and
5. required open-response rubric-shape admission.

For a configured `純文字` slot, visual suppression sets `題目內容類型` to `純文字` and
clears `chart_spec`, `image_spec` when present, and `圖片`. This runs before the result enters
`question.subquestions`, so figure-kind declaration/repair and rendering never observe the
discarded model visual. Explicit visual siblings are untouched and retain their existing
repair/render behavior.

Subject parsers continue to own domain-specific pins. They force submitted grade, subject,
curriculum selections, competency/cognitive-process selections, reporting scale, and
instruction where those fields exist. Model values are fallbacks only where no submitted pin
exists.

The same shared slot contract is reapplied to every surviving fixed subquestion immediately
after an accepted correction and before visual-change detection or post-correction figure
policy. Correctors already preserve the entering structure; this second application is a
defence-in-depth assertion that future corrector changes cannot reintroduce an image or alter
a slot-owned field.

### 3. Informed, bounded retry

Each attempt records a structured internal classification:

```text
validation_exhausted  known schema or rubric validation failed
parser_failure        an unexpected parser class failed without exposing its text
provider_failure      the provider call raised; only its class name is retained
unknown               no more specific safe classification exists
```

On a subsequent attempt, only `SubquestionParseError.reason`—already reduced to allow-listed
field/type or rubric-shape language—is appended to that attempt's user prompt with an explicit
instruction to repair the named shape while retaining all submitted pins. Provider failures
and unexpected exceptions do not append exception text. The original prompt value remains
unchanged, so feedback cannot accumulate beyond the fixed retry budget.

The final diagnostic detail is normalized to one line and bounded to 240 Unicode code points.
Provider and exception class names are restricted to identifier characters and 64 code
points. If sanitization produces no detail, the classification remains but the detail is
absent.

The retry count and fresh-client-per-attempt behavior do not change.

### 4. Generation-to-terminal failure sidecar

On exhaustion, the existing `sub_generator#N / llm_generate / error` stage event gains:

- `code="subquestion_exhausted"`;
- `failure_code` from the closed set above; and
- optional bounded `failure_detail`.

The existing safe human-readable stage `message` remains for live progress compatibility.
The worker's existing combined observer captures only events matching this exact code and a
valid zero-based `subquestion_index`. It stores the last event per slot in a private
`subquestion_failures` map beside the verification, figure-policy, and reference-example
recorders. Ordinary stage events cannot populate the map.

This observer seam is selected over a new callback threaded through every subject wrapper:
the event already crosses the `src/` to `server/` boundary, carries the immutable operation
scope and slot index, and is independently published for live diagnostics.

The map is included in `_QuestionPositionResolution` for both terminal construction sites:

- the save-before-result History `terminal_delivery` computation; and
- final `question_terminal` construction and ledger sealing.

No database migration or new annotation column is required. The existing
`annotations_json.terminal_delivery` JSON stores the enriched missing-slot objects.

### 5. Terminal and compatibility shape

`SlotRef` gains optional `failure_code` and `failure_detail` fields. They are explanatory
evidence and are excluded from slot identity, just like the existing `reason` field.

For an absent fixed subquestion, terminal construction chooses evidence in this order:

1. captured structured failure for that exact manifest position;
2. the existing terminal-level cancellation/failure classification;
3. generic `unknown` only when no concrete safe reason exists.

The legacy `reason` string remains populated for compatibility. For new structured failures it
contains a concise bounded fallback, not raw provider or model content. Existing image reasons
(`render_failed`, `spec_missing`, `empty_image`) remain unchanged.

Old persisted records without the optional fields continue to parse and show their existing
generic `reason`. The fixed identity tuple remains `(kind, question_id, subquestion_id,
subquestion_index)`, so adding evidence cannot create a terminal contradiction.

Confirmed cancellation continues to use `termination_reason=cancelled`; an ordinary client
disconnect neither fabricates a slot failure nor overwrites a later server terminal. Whole-
question provider failures continue through the existing failed terminal and
`unknown_reason` path. The UI therefore distinguishes those run outcomes from a normal,
partial result containing an exhausted subquestion.

### 6. History and teacher-facing projection

History extraction continues returning only the typed terminal-delivery subset, now preserving
the optional structured fields inside each `missing` entry. Live stream and History therefore
feed the same frontend evidence parser.

The frontend validates the closed `failure_code` set and the bounded detail. The missing-slot
block maps the code through localized messages:

- validation exhausted: the response format remained invalid after retry;
- parser failure: the response could not be parsed;
- provider failure: the model service call failed;
- unknown: no safe detailed cause is available.

When safe detail exists, it is appended after the localized summary. Unknown or legacy reasons
fall back to the existing `原因：…` rendering. Cancellation is rendered by the existing
terminal status, and connection interruption remains the existing live transport state rather
than a missing-slot reason.

## TDD seams

These are the agreed red/green seams for implementation:

1. **Subject parser seam:** deterministic NS and SS raw dictionaries prove scalar-string
   normalization, rejection of arbitrary values, submitted grade/curriculum/competency pins,
   and duplicate-rubric rejection.
2. **Shared generation seam:** fake clients reproduce the observed responses—scalar examples
   on attempt one, then scalar examples plus grade drift and `2 / 1 / 1 / 0` on attempt two.
   Tests inspect the second prompt's sanitized feedback, fixed identity, recovery behavior,
   concrete exhaustion evidence, and unaffected siblings.
3. **Mixed visual seam:** a six-slot NS fixture has two explicit visual slots followed by four
   explicit pure-text slots. Fake renderer/image collaborators prove only the first two can
   repair/render or enter terminal image obligations, on initial generation and after an
   accepted correction.
4. **Terminal seam:** pure terminal helpers prove exact-position failure mapping, identity
   stability, fallback precedence, bounds, and compatibility with legacy/image reasons.
5. **Detached run and History seam:** a deterministic generation request proves the reason in
   the live terminal equals the reason returned by authenticated History read-back after
   save-before-result persistence.
6. **Frontend evidence seam:** parser/reducer tests prove optional fields survive live and
   History projection without changing slot identity or terminal conflict logic; component
   tests prove localized validation/provider/parser/unknown messages and unchanged cancelled
   and disconnected states.

Every test runs with fake SDK responses and local fixtures. No environment API key is read.

## Verification

During red/green work, run the narrow parser, generation, terminal, History, and component
tests after each behavior change. Before review, run:

- the complete Python suite under the repository's `choom -n 500 --` convention;
- the complete frontend Vitest suite;
- Python and frontend lint/type/build checks required by the repository; and
- the named implementation workflow's parallel Standards and Spec reviews against
  `origin/staging`.

Baseline on the specified commit before any change: 3,494 Python tests passed with one skip;
2,316 frontend tests passed across 209 files.

## Out of scope

- Live acceptance in #822 or any provider-funded generation.
- Increasing the subquestion retry budget.
- Storing prompts, responses, provider messages, request IDs, reasoning, or credentials.
- Changing manifest slot identity, sibling scheduling, detached-run cancellation, or client-
  disconnect semantics.
- Redesigning image failure codes or verification-trail semantics.
- The unrelated flaky-test cluster, which receives its own design and implementation plan.
