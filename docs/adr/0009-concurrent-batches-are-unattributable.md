# concurrent batches are unattributable

A batch launches all questions concurrently, while its agent stage events carry no question identity. The browser therefore cannot attribute an event to one question or reconstruct a truthful per-question pipeline for a multi-question run.

## Decisions

- 生成進度列 shows a roll-up and no 生成步驟 breadcrumb for a multi-question run (#246).
- 代理狀態面板 switches to 合計模式 for a multi-question run: aggregate counts per agent, no per-run timer, and a mode label instead of per-question grouping (#248).

This list now records both current status surfaces and remains open for future multi-question surfaces.

## Rejected Alternative

Stamping a question identifier onto every agent ID would change the existing event contract. At the parameter caps it would also render roughly a hundred lanes in 代理狀態面板, replacing an attribution gap with an unusable panel.

## Conditional exception

[ADR 0032](0032-per-question-live-progress-is-a-conditional-exception-to-unattributability.md) records a conditional exception: when both the v2 event contract (stream_version=2) **and** the release acceptance gates defined there are satisfied, per-question attribution is permissible. The legacy / unattributable limitation above applies to all other sessions and must not be removed.
