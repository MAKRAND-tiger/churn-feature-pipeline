# VERSION_COMPARISON.md

Per-feature version comparison for the features `feature_spec.md` designates as versioned: ['txn_count_recent', 'avg_monthly_spend']. All values are loaded from the feature store (not recomputed). For each feature: how many customers' values changed between consecutive versions, the distribution shift, and how many customers would move across a churn-risk-ranking threshold (the 75% quantile; higher = higher churn risk) if the newer version were used instead of the older one.

## txn_count_recent

**Parameter varied:** `window_days`
**Versions registered:** [1, 2, 3]

### Per-version distribution
| version | window_days | mean | std | p50 | p75 | max | n |
|---|---|---|---|---|---|---|---|
| 1 | 90 | 2.277 | 1.792 | 2 | 3 | 12 | 1500 |
| 2 | 30 | 0.7913 | 0.9939 | 1 | 1 | 7 | 1500 |
| 3 | 180 | 3.971 | 2.475 | 4 | 6 | 15 | 1500 |


### Version-to-version change
- **v1 → v2:** 1087/1500 (72.5%) customers' values changed. At the 75% churn-risk threshold, 305 customers moved above and 116 moved below (rank-order correlation 0.603).
- **v2 → v3:** 1321/1500 (88.1%) customers' values changed. At the 75% churn-risk threshold, 86 customers moved above and 469 moved below (rank-order correlation 0.431).

### Interpretation
The versions differ because `window_days` changes the horizon over which frequency is counted. A shorter window (v2, 30d) concentrates on very recent engagement and so flags recent-disengagement churn risk more sharply; a longer window (v3, 180d) smooths toward long-term habit and moves fewer customers. A model consuming this feature WOULD notice the change where the rank-order correlation between versions is materially below 1.0: customers near the threshold are the ones who cross, so the chosen window is a real modeling decision, not a cosmetic rename.


## avg_monthly_spend

**Parameter varied:** `window_months`
**Versions registered:** [1, 2]

### Per-version distribution
| version | window_months | mean | std | p50 | p75 | max | n |
|---|---|---|---|---|---|---|---|
| 1 | 6 | 28.04 | 24.08 | 23.32 | 39.3 | 181.2 | 1500 |
| 2 | 12 | 24.12 | 17.3 | 22.59 | 33.63 | 100.7 | 1500 |


### Version-to-version change
- **v1 → v2:** 1408/1500 (93.9%) customers' values changed. At the 75% churn-risk threshold, 141 customers moved above and 141 moved below (rank-order correlation 0.729).

### Interpretation
The versions differ because `window_months` changes the averaging horizon. The 12-month window (v2) smooths seasonal spend swings that the 6-month window over-weights, so customers whose recent 6 months were atypical shift the most. A model consuming this feature would notice the change wherever the two windows disagree on rank order — the smoothing reduces noise but also dampens genuine recent-spend drops that signal churn, which is the modeling trade-off the version bump encodes.

