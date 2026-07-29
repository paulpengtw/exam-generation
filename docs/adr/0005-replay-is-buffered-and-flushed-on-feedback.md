# Session replay is buffered and flushed when feedback opens

Replay session mode, enabled by `replaysSessionSampleRate > 0`, uploads continuously; buffer mode, with only `replaysOnErrorSampleRate > 0`, retains the previous 60 seconds in memory and uploads them only when an error is sampled. Most reports in this app are not JavaScript errors: a teacher reporting that an 答案 does not match its 題目 throws nothing, so the conventional 10%-session and 100%-on-error configuration would leave most reports without the replay it was enabled to provide. We therefore set `replaysSessionSampleRate: 0` and `replaysOnErrorSampleRate: 1.0`, and call the replay integration's `flush()` when the feedback form opens. Every report and every error receives the preceding 60 seconds, and nothing else is uploaded.

## Considered Options

The default 10% session sampling with 100% on error was rejected because it attaches replays by luck rather than by whether something went wrong, while still missing most reports. Setting `replaysSessionSampleRate: 1.0` and recording every session end to end was rejected because it uploads a replay for every teacher whose generation succeeded, generation sessions are long, and quota is consumed per uploaded replay rather than per recorded second.

## Consequences

The buffer retains only 60 seconds, so a teacher who notices a problem, considers it, and reports three minutes later has already lost the moment it broke; session mode would not have that gap. Calling `flush()` also couples the feedback button to the replay integration, and the call must be removed if replay is removed.
