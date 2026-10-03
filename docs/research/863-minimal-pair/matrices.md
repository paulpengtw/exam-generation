# 最小對照 checker matrices — #863

Cached units scored: 105 / 105

## Missing responses

Count: 0
 (none)

## Recommendation

Recommendation: **note only**
Details: [學生作答實例檢核] 檢核員發現最小對照違反時，請依上述差異提示修正第一個 [1] 實例，但不要把此旗標作為阻擋條件。

## Overall

| Scope | n | TP | FP | FN | TN | recall | false-flag rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| all units | 105 | 61 | 1 | 16 | 27 | 79% | 4% |
| excluding borderline | 94 | 58 | 1 | 12 | 23 | 83% | 4% |

## By near-miss type (variant)

| variant | n | labelled pass | labelled fail | checker flagged | correct | metric | rate |
|---|---:|---:|---:|---:|---:|---|---:|
| true_pair | 19 | 19 | 0 | 1 | 18 | false-flag rate | 5% |
| fewer_points | 10 | 0 | 10 | 6 | 6 | recall | 60% |
| different_claim | 19 | 0 | 19 | 19 | 19 | recall | 100% |
| no_reason | 19 | 0 | 19 | 18 | 18 | recall | 95% |
| closes_chain | 19 | 0 | 19 | 17 | 17 | recall | 89% |
| framed_omission | 9 | 9 | 0 | 0 | 9 | false-flag rate | 0% |
| omission_plus_gap | 9 | 0 | 9 | 0 | 0 | recall | 0% |
| omits_two | 1 | 0 | 1 | 1 | 1 | recall | 100% |

## By stratum

| stratum | n | TP | FP | FN | TN | recall | false-flag rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| open | 50 | 36 | 1 | 4 | 9 | 90% | 10% |
| framed_stem | 43 | 20 | 0 | 9 | 14 | 69% | 0% |
| framed_figure | 12 | 5 | 0 | 3 | 4 | 62% | 0% |

## true_pair false flags by gap_kind

| gap_kind | n | false flags | false-flag rate |
|---|---:|---:|---:|
| 依據不足 | 5 | 1 | 20% |
| 未回扣證據 | 5 | 0 | 0% |
| 連結錯誤 | 9 | 0 | 0% |

## Framing agreement

| stratum | n | checker set_framed=true | set_framed=false | missing/non-bool | true rate |
|---|---:|---:|---:|---:|---:|
| open | 50 | 41 | 9 | 0 | 82% |
| framed_stem | 43 | 43 | 0 | 0 | 100% |
| framed_figure | 12 | 12 | 0 | 0 | 100% |
