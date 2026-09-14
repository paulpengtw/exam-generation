During #766 staging acceptance, Sentry recorded five `llm_exchanges insert failed:` warnings with an empty exception description while SS/NS batches were running concurrently.

- Sentry: [EXAM-GENERATION-API-STAGING-J](https://cpengme.sentry.io/issues/7730828215/)
- First seen: 2026-09-14 07:28:54.161 UTC; last seen: 07:34:42.493 UTC; count: 5.
- Hard-refreshed frontend release: `8941814b7973428a485d39c1a5d2b90fd52ddcad`; successful staging deployment `6432290186`. The backend events themselves have no release tag, so this does not establish which commit introduced the warnings.
- Each event identifies `POST /api/generate`. Both subjects used two 題組 with three 小題 each. Generation and History persistence still completed, including unchanged History replay.

The events have no exception stack or informative exception type. `server/generate/persistence.py` schedules `_insert(row)` with `asyncio.run_coroutine_threadsafe`, waits on `future.result(timeout=10)`, and logs only `%s` of an exception. A timeout is a hypothesis because its string can be empty; it is not proven by the event. The scheduled coroutine is not cancelled at this catch, so a warning does not by itself prove that an exchange row was lost.

Please establish whether these are delayed commits, lost exchanges, or another failure, and make the diagnostic identify the failure class and relevant non-content run/agent/order identifiers. Preserve best-effort generation behavior and ADR 0004: never log request/response bodies, prompts, answers, credentials, or SQL bound values.

Acceptance: reproduce the observed condition at the recorder/persistence seam; verify whether the eventual row exists and that generation continues; report the actual error class and correlation metadata without content. Keep this separate from #743's operation/call identity changes unless investigation proves a dependency.

Sanitized event IDs: `35fbfc7309874ed981caebc48c92aca3`, `bcafd8827ad44c4496069fdfc3963c4b`, `47c0b7152f34417f9e8ef6f24933f171`, `598928547d63433e9bc4bf50602fe632`, `4cf246eab32d46639ab8d3450fd7bb7c`.
