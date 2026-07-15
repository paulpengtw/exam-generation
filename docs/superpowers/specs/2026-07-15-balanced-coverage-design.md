# Spec: Default balanced 題型/學習範圍 batch coverage (issue #112)

## Why

Batch generation samples every question independently, so a 5-question batch can cluster on one 題型 and leave curriculum gaps — statistically valid, perceptually unbalanced (Spotify-shuffle problem).

## Decision

Per the issue: social studies only for v1; `coverage_mode` defaults to **balanced**; random mode remains available.

## Design

### `src/batch_sampler.py` (new)

`BatchSampler(count, q_type_pool, learning_content_pool, rng)`:

- Pre-plans a 題型 assignment list of length `count` by round-robin over a shuffled pool (pool ≥ count → `count` distinct types; pool < count → every type appears ⌊count/|pool|⌋ or +1 times), then shuffles assignment order so the batch isn't sorted by type.
- Optionally pre-stratifies 學習內容: spread draws across distinct codes before repeating any (sample-without-replacement across the batch until the pool is exhausted, then reshuffle).
- Deterministic under a fixed seed (uses the same `random.Random` seeding convention as the samplers).

### Wiring

- `server/generate/models.py`: `coverage_mode: Literal["balanced", "random"] = "balanced"` on `GenerateParams` (+ query param). Missing field ⇒ balanced (new default, per issue).
- `server/generate/service.py` (SS branch): when `count > 1` and balanced, instantiate one `BatchSampler` before the loop; pass `assigned_q_type` (and `assigned_learning_content` when stratified) into each `ss_sample_params` call. Random mode and `count == 1` use the existing per-question path untouched.
- `src/social_studies/sampler.py`: `sample_params(..., assigned_q_type=None, assigned_learning_content=None)` — assigned values override the random draw. Interaction rule: explicit user overrides (`q_type` pool, `subquestion_configs`, `learning_content` selections) win over BatchSampler assignments; the sampler only balances dimensions the user left random.
- Metadata: emit `coverage_mode_used` in the batch/question metadata so callers can verify.
- CLI: `--coverage-mode balanced|random` on the SS CLI mirroring the API.

### UI

`ParamForm.tsx`: 出題模式 dropdown — 均衡（題型平均分配）(default) / 隨機; sent as `coverage_mode`.

## Testing

- `tests/test_batch_sampler.py`: 6 questions × 3-type pool → each type ×2; 5 × 4-type pool → 4 distinct + 1 repeat; determinism under fixed seed; assignment order shuffled.
- Service test: balanced batch of 5 yields ≥ min(5, |pool|) distinct 題型; random mode can repeat (seeded fixture).
- Regression: count=1 and explicit user q_type/config behavior unchanged.

## Out of scope

Math/NS stratification (follow-ups); preset "packages" beyond balanced/random; persisting the preference; changing single-question generation.
