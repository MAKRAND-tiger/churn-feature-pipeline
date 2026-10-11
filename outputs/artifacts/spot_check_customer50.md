# Spot-check: customer 50 train snapshot vs scoring path

Hand-verified (no help from Claude) that the training snapshot and the scoring path produce identical feature values for customer 50 at as_of 2026-08-01.

| feature | train | score | match |
|---|---|---|---|
| days_since_last_txn | 3.0 | 3.0 | True |
| txn_count_recent | 1.0 | 1.0 | True |
| spend_recent | 23.32 | 23.32 | True |
| avg_monthly_spend | 23.816666666666666 | 23.816666666666666 | True |
| active_months_12m | 3.0 | 3.0 | True |
| return_rate_90d | 0.0 | 0.0 | True |
| tenure_days | 707.0 | 707.0 | True |

All match: True