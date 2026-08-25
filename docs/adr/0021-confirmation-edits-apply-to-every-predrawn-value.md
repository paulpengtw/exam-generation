# 確認頁修改 applies to every 預抽 row, including 從屬參數 parents

確認頁修改 was defined as editing a resolved 各小題配置 value on 發送前確認 — per-小題 only; 題組-level 預抽 rows offered 重抽 alone. When 核心素養 and 數學思考 became 預抽'd without a form control (#594), the narrower rule (重抽-only rows) was recommended and **rejected**: the supervisor may edit any resolved 預抽 value in place, 題組-level or per-小題. The stated position is that the form is where values are pinned up front and 發送前確認 is where drawn values are reviewed and adjusted; a parameter the product chose not to *ask* about may still be *changed* once it has been drawn and shown.

## Parent edits

Editing a 從屬參數 parent (情境, 內容領域, 小題數) in place behaves exactly like 重抽 of that parent with the chosen value: its children re-resolve from the new range; 覆寫'd children that remain valid survive; a pinned child that no longer fits is cleared and re-resolved, never silently corrected (ADR 0003, applied on the confirmation screen rather than at `/generate`). The seed is untouched. One rule covers "parent changed" regardless of how.

## Considered options

Rejecting a parent edit whenever a pinned child would become invalid was rejected as stricter with more clicks. Allowing edits only on the two newly hidden parameters was rejected as an inconsistency other 題組-level rows would then have to explain.
