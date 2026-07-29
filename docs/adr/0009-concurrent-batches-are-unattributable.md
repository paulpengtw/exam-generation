# concurrent batches are unattributable

A batch launches all questions concurrently, while its agent stage events carry no question identity. The browser therefore cannot attribute an event to one question or reconstruct a truthful per-question pipeline for a multi-question run.

## Decisions

- 生成進度列 shows a roll-up and no 生成步驟 breadcrumb for a multi-question run (#246).

This list remains open for the 代理狀態面板 合計模式 decision in #248.

## Rejected Alternative

Stamping a question identifier onto every agent ID would change the existing event contract. At the parameter caps it would also render roughly a hundred lanes in 代理狀態面板, replacing an attribution gap with an unusable panel.
