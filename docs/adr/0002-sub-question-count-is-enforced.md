# 小題數量 and per-小題 題型 are 強制值, not 建議值

`sub_question_count` and a per-小題 題型 were submitted as instructions to the 文本生成器, but the actual number of 小題 came from the plan the model returned and the 子題產生器 read its 題型 from that plan too — so both settings were 建議值 in practice while being documented and displayed as though they were 強制值. Since 發送前確認 now states them as facts, they are enforced: an over-long plan is truncated, a short one is padded with fallback entries, and an explicitly pinned 題型 overrides the plan.

## Consequences

A padded 小題 is produced without the 文本生成器's planning pass, so it may cover ground close to a sibling 小題. Requests that omit 小題數量 keep the previous model-decided behaviour.
