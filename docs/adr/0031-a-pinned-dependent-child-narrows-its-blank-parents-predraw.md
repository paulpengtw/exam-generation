# A 釘選 從屬參數 child narrows its blank parent's 預抽

ADR 0020 made 預抽 a dependency order — parents first, children drawn from the parent's range — but said nothing about a child the user pinned under a parent left blank. 社會領域 then drew 科目 and 內容領域 blind to 釘選 學習內容, `/resolve` returned payloads its own gate rejected (breaking ADR 0019), and production requests failed after confirmation. We decide that **a 釘選 child narrows a blank parent: the parent is drawn only from values that admit every 釘選 child**, counting 各小題配置 codes within the resolved 小題數; an empty range is a field-addressed 422 (`no_admitting_parent`), an explicitly supplied incompatible parent stays `incompatible_parent` (ADR 0003), and a parent edited or 重抽'd on 發送前確認 still clears its unfitting children (ADR 0021). 自然科學's 情境子類別 → 情境 already behaved this way.

## Considered options

Rejecting a 釘選 child whose parent is blank was rejected: it forces a 科目 choice the codes already imply and removes 全部/隨機 for anyone who starts from codes. Drawing the parent freely and dropping children that do not fit was rejected as silent correction (ADR 0003). Allowing several 內容領域 per 題組, so disjoint 公 codes could coexist, is out of scope.
