## Parent

[#756 — Verify saved random parameters reload unchanged on staging](https://github.com/paulpengtw/exam-generation/issues/756)

## What to build

Harden automatic 核心問題 planning from entering 發送前確認 through candidate validation, bounded recovery, displayed selection, and generation submission. Preserve the requirement for three usable candidates and the existing fallback that lets generation decide 核心問題 when planning exhausts its retry budget. Report an exhausted planning request as one actionable Sentry exception with its warning retained as diagnostic context.

On 2026-09-14 at 13:11:00.730 Asia/Taipei, natural-sciences planning logged `Planner returned 2 candidates, expected 3` in [EXAM-GENERATION-API-STAGING-7](https://cpengme.sentry.io/share/issue/e7fd52273ad6458aad71a845e12789ea/). Eight milliseconds later, the same catch path raised HTTP 502 in [EXAM-GENERATION-API-STAGING-8](https://cpengme.sentry.io/share/issue/3166b8743d6f424d9baf44bef36fe510/). These are the warning and exception for one rejection. The shared events identify the count check but omit the raw response, so the implementer must establish the response/parser cause before choosing the repair.

Keep the existing maximum of two planning calls per request. This ticket covers planner robustness and its duplicate reporting together; the independent HTTP 414 generation-transport failure is covered separately. Existing #186/#205 semantics remain authoritative: a planning failure is disclosed, and 確定發送 remains available.

## Acceptance criteria

- [ ] Establish a deterministic, sanitized reproduction of the insufficient-candidate path and record the confirmed cause. Distinguish actual short output from parsing/filtering loss; do not assume the Sentry count alone proves which occurred. If the original response is unavailable, explicitly identify that limitation and use a controlled provider-response reproduction.
- [ ] Correct the confirmed recoverable response/parser behavior and add a regression that fails before that correction. A successful planning response supplies three non-empty textual 核心問題 candidates; it does not claim success by duplicating candidates or inserting placeholders to make up the count.
- [ ] An invalid or insufficient first response receives a targeted correction attempt within the existing two-call budget. A valid corrected response succeeds. A still-invalid final response produces the existing controlled failure rather than an unbounded retry or a falsely successful short list.
- [ ] When planning succeeds, 發送前確認 displays the chosen 核心問題 and submits that same value. An explicitly supplied 核心問題 remains authoritative, and rerendering the same confirmation does not start additional planning calls.
- [ ] When the retry budget is exhausted, 發送前確認 states that generation will decide 核心問題 and still permits 確定發送. No stale or fabricated candidate is submitted. Preserve these behaviors across the shared three-subject planning flow.
- [ ] One exhausted planning request produces one Sentry exception issue event. Its warning remains available as diagnostic context without producing a second issue event; unrelated warning/error reporting remains intact.
- [ ] Diagnostics identify the failing stage, attempt, and expected/actual candidate counts without sending raw prompts, candidates, credentials, or teacher identity through logs. Preserve ADR 0004's collection boundaries.
- [ ] Verify the planning endpoint, bounded retry outcomes, confirmation success/fallback behavior, and Sentry event count together with deterministic responses. Record a staging planning check independently of whether a subsequent generation request succeeds, so HTTP 414 cannot be mistaken for a planner regression.

## Blocked by

- None (can start immediately).
