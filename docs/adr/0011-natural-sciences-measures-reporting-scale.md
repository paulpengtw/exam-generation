# natural sciences measures reporting scale, not 難度

自然科學 uses Reporting Scale (PISA Science proficiency levels 1c, 1b, 1a, 2, 3, 4, 5, 6) as the per-小題 demand signal. 數學 and 社會領域 use 難度 (easy / medium / hard). The asymmetry is deliberate: PISA scientific-literacy framing gives 自然科學 a criterion-referenced scale with published level descriptors; 數學 and 社會領域 have no equivalent published framework, so a coarse three-point 難度 remains their demand signal.

## Considered Options

**Keeping both signals in parallel for 自然科學** — Having both 難度 and Reporting Scale in the same prompt creates two competing demand signals. The model cannot simultaneously satisfy a coarse ordinal and an eight-level criterion-referenced scale anchored to published descriptors; it will satisfy whichever signal happens to dominate the prompt context and silently ignore the other. This was the state issue #282 removed, and it was rejected for exactly that reason.

**Translating the term into Chinese** — Traditional Chinese has no established equivalent for the PISA term "Reporting Scale". A coined rendering such as 報告等級 reads as jargon that is disconnected from the published PISA descriptors the prompts quote verbatim. The interface intentionally shows the literal English headword in both locales rather than a coined translation.

**Treating Reporting Scale as a verifier pass/fail criterion** — Level assignment is a framework judgement with no objective ground truth, unlike answer correctness. Treating an unexpected level as a verification failure would spend the retry budget on subjective level disagreement. The corrector is additionally forbidden from altering level assignments once frozen, so a pass/fail criterion on level would put correction in an unresolvable loop. The assignment is therefore an input constraint only — the generator receives it and the verifier ignores it.

**Recording the requested 題組-level value in metadata** — The 題組-level Reporting Scale is a default-filler that any 小題 may override, and it is absent from the payload altogether when left 隨機. It is therefore not a stable fact about what was generated. Only the resolved per-小題 levels are facts about the shipped output. `metadata.reporting_scales` records these in 序號 order; blank slots (from dropped or unresolved subquestions) leave no entry.

## Consequences

The demand signal for 自然科學 is now exclusively Reporting Scale. Code, prompts, and UI that set or display 難度 must not touch 自然科學 requests, and code that sets or displays Reporting Scale must not touch 數學 or 社會領域 requests. The verifier receives neither signal — it concentrates on answer correctness and code validity. Resolved per-小題 levels are the authoritative record of what was generated; the 題組-level requested value is transient and is not persisted.
