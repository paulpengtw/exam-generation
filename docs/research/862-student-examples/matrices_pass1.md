# 學生作答實例 checker matrices — #862 (pass-1 labeller labels)

### Rule r1 (not_student_voice)

| Stratum | n | TP | FP | FN | TN | errors | recall | false-flag rate |
|---|---|---|---|---|---|---|---|---|
| ns | 57 | 17 | 0 | 1 | 39 | 0 | 94% | 0% |
| ss | 6 | 0 | 0 | 0 | 6 | 0 | n/a | 0% |
| in-scope (ns+ss) | 63 | 17 | 0 | 1 | 45 | 0 | 94% | 0% |
| trap | 18 | 0 | 0 | 0 | 18 | 0 | n/a | 0% |

**Trap-set false positives (r1):** 0/18 flagged. None.

### Rule r2 (not_this_item)

| Stratum | n | TP | FP | FN | TN | errors | recall | false-flag rate |
|---|---|---|---|---|---|---|---|---|
| ns | 57 | 3 | 2 | 1 | 51 | 0 | 75% | 4% |
| ss | 6 | 0 | 0 | 1 | 5 | 0 | 0% | 0% |
| in-scope (ns+ss) | 63 | 3 | 2 | 2 | 56 | 0 | 60% | 3% |
| trap | 18 | 0 | 0 | 0 | 18 | 0 | n/a | 0% |

**Trap-set false positives (r2):** 0/18 flagged. None.

### Rule r3 (implausible_zero)

| Stratum | n | TP | FP | FN | TN | errors | recall | false-flag rate |
|---|---|---|---|---|---|---|---|---|
| ns | 23 | 3 | 0 | 2 | 18 | 0 | 60% | 0% |
| ss | 2 | 2 | 0 | 0 | 0 | 0 | 100% | n/a |
| in-scope (ns+ss) | 25 | 5 | 0 | 2 | 18 | 0 | 71% | 0% |
| trap | 6 | 0 | 0 | 0 | 6 | 0 | n/a | 0% |

**Trap-set false positives (r3):** 0/6 flagged. None.

### Per-unit checker verdicts (informational)

| unit_key | specificity_violation | counting_violation | verdict |
|---|---|---|---|
| fasting-method\|0\|2 | True | False | fail |
| fasting-method\|0\|3 | True | True | fail |
| fasting-method\|0\|4 | False | False | pass |
| truck-cornering\|0\|2 | False | False | pass |
| truck-cornering\|0\|3 | False | False | pass |
| typhoon-database\|0\|1 | False | False | pass |
| typhoon-database\|0\|3 | False | True | fail |
| typhoon-database\|0\|4 | True | False | fail |
| weather-proverbs\|0\|1 | False | False | pass |
| weather-proverbs\|0\|2 | False | False | pass |
| weather-proverbs\|0\|4 | False | False | pass |
| wind-corridor-effect\|0\|1 | False | True | fail |
| wind-corridor-effect\|0\|2 | False | False | pass |
| wind-corridor-effect\|0\|3 | False | False | pass |
| jumping-bottle-cap\|0\|3 | True | False | fail |
| jumping-bottle-cap\|0\|4 | True | False | fail |
| self-heating-pack\|0\|2 | False | False | pass |
| 社會領域_row4\|0\|4 | True | False | fail |
| 社會領域_row6\|0\|6 | False | False | pass |
