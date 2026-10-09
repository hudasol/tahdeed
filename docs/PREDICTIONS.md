# Predictions, written before each run

Rule: a prediction is committed **before** the evaluation that tests it. Results go in the table next
to it afterwards, hit or miss. `dev` is the iteration split; `sealed` is only used for the v1.0 baseline
and the final report. (v1.0 was evaluated on the old combined test split, which is dev + sealed.)

## Round 1 (after Google review upgrades), dev split, hole mix 30% in training

| # | Prediction | Basis | Result |
|---|---|---|---|
| P1.1 | Hole benchmark (truth removed): precision of *resolved* rises from 71% to at least 85% | district-conflict feature + 30% hole training mix | **Near miss**: 83.7% (95% CI 81.7-85.7%); was 71.0% |
| P1.2 | Hole benchmark: resolved share falls below 35% (the system should abstain more) | same | **Miss**: 46.2% resolved (was 49.6%). The system abstains only a little more under holes; the gain came mostly from fewer wrong answers |
| P1.3 | Normal benchmark (no holes): resolved precision stays at or above 96.5%; resolved share drops by no more than 8 points (from 61.9%) | price of caution | **Hit**: 98.2% precision (CI 97.8-98.7%); resolved share *rose* 61.9% → 64.5% (the retrieval fixes outweighed the caution) |
| P1.4 | Consonant-variant queries: top-1 within 50 m rises from 45% to at least 55% | short keys + sibling keys + full-name fuzzy spans | **Miss**: 49.8% top-1 ≤50 m (was 45%). Better, not enough |
| P1.5 | ECE of P(within 50 m) stays at or below 0.03 on the 30%-hole mixture | isotonic on matching mixture | **Hit**: ECE 0.021 on the no-hole benchmark, 0.010 on the 30% mix |
| P1.6 | ECE of P(within 1 km) at or below 0.05 | new head | **Hit**: ECE 0.015 |
| P1.7 | Median latency stays under 15 ms (was 5 ms) | wider span generation | **Hit**: median 8.7 ms, p95 15.3 ms |

Hole sensitivity of the Round 1 model (dev split, 1,500 queries per row):

| Share of queries whose true address is absent | resolved | precision@50 m of resolved | forced top-1 ≤50 m | ECE P(≤50 m) |
|---|---|---|---|---|
| 0% | 65.1% | 97.6% | 67.4% | 0.021 |
| 15% | 61.8% | 95.7% | 62.5% | 0.015 |
| 30% (training mix) | 59.1% | 94.3% | 58.8% | 0.010 |
| 50% | 55.2% | 91.8% | 53.4% | 0.015 |
| 100% | 46.5% | 84.0% | 41.0% | 0.049 |

Reading: calibration holds across the whole range (ECE ≤ 0.05) but *precision cannot*: if every
query is for an absent address, 16% of confident answers are wrong neighbours. That is a limit of
the data, now quantified instead of hidden.
