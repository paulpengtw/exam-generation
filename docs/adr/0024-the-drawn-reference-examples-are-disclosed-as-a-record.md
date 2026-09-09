# The drawn 參考範例 are disclosed after generation as 參考範例紀錄

ADR 0018 carved the 參考範例 draw out of 全量預抽: it is not a parameter of the item, it stays seed-deterministic, and it is not shown on 發送前確認. Supervisors who curate a 題組 nevertheless need to know which 參考範例 shaped it — to judge whether the model leaned on its example, and to understand a failed run before regenerating from it (#663). We decide that **the draw stays the single exception to 預抽 and stays off 發送前確認, but its outcome is disclosed after generation as 參考範例紀錄**: one record per generated question, a sibling of the question like Agent 自主驗證修正歷程, holding one entry per stage and per 小題 with the example's description, its source path, and exactly the portion the prompt received. This extends ADR 0018 rather than replacing it: 0018's decision stands; the carve-out's reason — "disclosing it would mean showing prompt bytes" — is amended, because the record discloses the injected example, not the prompt.

## What the record is

- `reference_example_record = {disabled, entries[]}`. Entries are keyed by the pipeline's agent id (`generator`, `text_generator`, `subquestion_generator`) and the 小題 序號, and come in two kinds: `example` and `process_exemplar` — the 社會領域 認知歷程範例, titled by the 認知歷程 it was drawn for. Content is the injected portion only; images are `{path, caption}` references, never bytes. Sibling 小題 that drew the same example each keep their own entry. `disabled: true` records that 關閉參考範例 was set (#665).
- The prompt builders return their draws as a third value beside the prompt text; the core pipeline emits them through `on_reference_example_entry`, a sibling of `on_figure_policy_entry`. The record is staged incrementally like the figure policy trail, on both `generation_logs` and `generation_records`, and is first written at question start — so a failed or aborted row keeps the entries drawn before the failure (#666).
- It renders as a collapsed section on the question card — draft card while streaming, final card, history detail — and on history detail's failed panel beside the figure policy trail. The collapsed header carries the counts (#667).

## Consequences

- ADR 0022's guard 2 keeps its allowlist entries unchanged; their reasons now say the picks are disclosed as 參考範例紀錄. No new RNG use is allowlisted.
- 提示詞預覽 and 發送前確認 are untouched: the preview path reaches the same builders and discards the draws.
- CLI output omits the record, as it omits both trails.
- Records that predate the feature render 無紀錄; nothing is backfilled from persisted prompts.

## Considered options

- Deriving the record after the fact from the persisted `llm_exchanges.request_body` was rejected: parsing prompt headings is fragile and cannot see 認知歷程範例.
- Showing the draw on 發送前確認, or offering 重抽 for it, was rejected: that turns the draw into a 預抽 value and reopens the carve-out entirely.
- Recording only on success, as the verification trail does, was rejected: supervisors regenerate from failed records and need to see what was in play.
