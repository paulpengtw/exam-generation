# coverage mode is a prompt-level hint, not a mechanical sampler

We no longer mechanically balance a batch according to `coverage_mode`. The batch pre-planner could assign values that the supervisor could neither see nor change in 發送前確認, conflicting with ADR 0001's decision that the confirmation screen shows the resolved payload. We therefore keep every draw visible and independently resolved, and use 均衡 only to add a prompt-level instruction that nudges the model to spread 題型 and 取材角度 while avoiding the sibling scopes supplied by the issue #111 context.

## Considered Options

Keeping the pre-planner and emitting all of its assignments into 發送前確認 would preserve a mechanical balance guarantee, but would add a second batch-wide resolution path and make confirmation responsible for exposing and supporting intervention in those assignments. Dropping 出題模式 entirely would make the mechanical semantics unambiguous, but would discard a useful way to ask the model for batch variety. A prompt-level hint retains that user intent without introducing draws outside the confirmation flow.

## Consequences

均衡 is advisory: the model may ignore the instruction, and identical inputs produce identical mechanical draws under 均衡 and 隨機. 隨機 and single-question requests add nothing to the prompt, while response metadata echoes the requested mode in `coverage_mode_used`. Raw-API callers that relied on mechanical 題型 balancing must now pin `q_type` or supply `per_question_params`.
