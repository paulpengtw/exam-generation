# 全量預抽 is enforced by a gate, an RNG allowlist test and a classification guard

全量預抽 (ADR 0018) had been a claim in `CLAUDE.md`, and #583 is what the unenforced claim cost. Three guards now make a violation fail loudly (#592):

1. **Runtime completeness gate.** `/generate` reruns `resolve(payload)` (ADR 0019); a non-empty `drawn` set is 422 naming the gaps, and an incompatible pinned 從屬參數 pair is 422 field-addressed. Catches a web bug that drops a field or a scripted caller that skips resolve.
2. **Static RNG allowlist test.** Every `random.`/`rng.` use under `src/` and `server/` outside the resolver modules must match an allowlist entry with a one-line reason; the allowlist is the 參考範例 picks in the three `context_builder` modules, all keyed on the request seed. `sample_params` may be called only from the resolve function. Since ADR 0024 those picks are also disclosed after generation as 參考範例紀錄; the allowlist entries' reasons say so, and no new RNG use is added for it. Catches a new draw added to generation code with no request field — the 數學思考 pattern the gate cannot see. **Do not delete this test as dead weight.**
3. **Classification guard.** `tests/test_contract_forwarding_guard.py` already requires every `GenerateParams` field × subject to be classified FORWARDED / REJECTED / INAPPLICABLE-with-reason. It is extended so every FORWARDED field is RESOLVED (present in that subject's drawable set) or PIN-ONLY (no default; with reason), and every drawable value is a request field. A new field or subject fails until classified. Catches the 核心素養 pattern — a forwarded field with a default draw that the resolver and 發送前確認 never learned about.

No caller is exempt (ADR 0018).

## Considered options

Handing generation an RNG that raises was rejected: 參考範例 legitimately needs a seeded RNG, and it would police at request time what guard 2 polices at commit time. A documented checklist was rejected as the same class of unenforced promise.
