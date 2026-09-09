# Every drawn value is resolved before 發送前確認 (全量預抽)

ADR 0001 moved the draw for blank 學習內容/學習表現 into the frontend so 發送前確認 could show them, and warned that any further randomness must derive from the request seed or the "what is shown is what is sent" guarantee silently breaks. An inventory (#587) found six values still drawn during generation for a supervised request — Reporting Scale, 認知歷程, 內容領域, 核心素養, 數學 小題 count and 數學思考 — one of which (#583) had already cost a wrongly-paired 情境子類別. We decide that **every value generation would otherwise draw is resolved by 預抽 and 釘選 before 發送前確認**, for every caller, with the backend resolver as the canonical 預抽 and a completeness gate on `/generate` that rejects an unresolved request with 422 naming the gaps. This completes ADR 0001 rather than replacing it: 0001's decision stands; its consequence that randomness originates in the frontend is amended — it now originates in the server resolver, and the browser draw is retired.

## The 參考範例 carve-out

The draw of which 參考範例 (few-shot exemplars) appear in a prompt is the **single deliberate exception**. It is not a parameter of the item — it shapes the prompt, not the 題組's declared 情境/題型/課綱 values — and disclosing it would mean showing prompt bytes, which this effort explicitly does not promise. Seed-determinism was accepted in place of disclosure: the pick is keyed on the request seed, so one payload always yields the same 參考範例. A reader who has just learned 全量預抽 will find `rng.sample` in the three `context_builder` modules and take it for a bug; it is not.

**Amended by ADR 0024.** The draw remains the exception to 預抽 and stays off 發送前確認, but which 參考範例 were drawn is now disclosed after generation as 參考範例紀錄. "Disclosing it would mean showing prompt bytes" no longer holds: the record shows the injected example, not the prompt.

## Consequences

- 小題數 left blank is 預抽'd 3–7 from the seed and 釘選 (ADR 0002's consequence "requests that omit 小題數量 keep the previous model-decided behaviour" no longer holds for any caller). 小題數 is a structural 從屬參數 parent: 重抽 rebuilds the slot list.
- 核心素養 and 數學思考, which the form deliberately does not expose, are still resolved and disclosed on 發送前確認; the form gains no control for them (#594).
- There is no supervised/unsupervised flag: completeness is the only gate, so a web bug that drops a field fails loudly instead of silently downgrading the request (#590).
- The CLI is a direct caller: it resolves first, prints the resolved payload, then generates; the in-generation fill and the LLM-decided 小題數 prompt branch are removed in the same change as the gate, once the web client is on the server resolver (#591).

## Considered options

Declaring API/CLI callers outside the promise was rejected: it keeps a backend sampler alive for a caller that does not exist and forces enforcement to police two paths. Keeping the client-side draw as canonical, or having both sides draw from shared data, was rejected as two implementations that must stay seed-identical.
