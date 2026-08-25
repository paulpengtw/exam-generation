# The resolve step is one pure function shared with the generation gate

ADR 0018 makes the backend the canonical 預抽. Its contract (#599): **`resolve(payload) → completed payload` is one pure function.** It resolves a whole payload — every supplied value is a pin, only blanks are drawn — and a complete payload resolves to itself, so the `/generate` completeness gate is literally the same call checking for an empty `drawn` set. It is exposed as `POST /api/generate/resolve` with a JSON body; `GET /generate/preview` no longer samples and requires a complete payload.

## Seed keying

Each draw is keyed by **(request seed, field path, per-field 重抽 counter)**. The client sends the counters (`redraws: {"<field path>": n}`), incremented on each 重抽. Resolution is therefore deterministic and replayable from stored params; the request seed is never rotated by 重抽; sibling fields' streams are untouched. Generation depends on the seed only for 參考範例, because the resolved payload is fully pinned.

## Reporting

An incompatible pinned pair (ADR 0003) returns **422 with field-addressed errors** and no payload — never corrected, never partially resolved. The gate emits the same shape with `code: "unresolved"` for gaps. Success returns `{payload, drawn: [field paths]}`; 發送前確認 badges 隨機 from `drawn`, and the client carries `drawn` forward in the payload (successor of `predrawn_fields`), so provenance lands in `params_json` at generation with no new table.

## Considered options

A separate single-field call was rejected as a second contract to keep seed-consistent — 重抽 is "clear the field (and its 從屬參數 children) and resubmit". A call-level nonce was rejected because a 重抽 on one field would change what another still-blank field draws. A persisted resolution record was rejected as a second source of truth that would also record resolutions nobody generated with. Extending `preview` to return payload and prompts together was rejected because it couples a cheap 重抽 to ~90 KB of prompt assembly.
