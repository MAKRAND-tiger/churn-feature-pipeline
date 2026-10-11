# data_dictionary.md — Churn Feature Pipeline (Stage 0, best-effort)

> **Status note (Stage 0):** This dictionary was generated directly from the raw
> sources (`data/customers.csv`, `data/transactions.db`,
> `data/transactions_monthly_agg.parquet`). It is best-effort inference from
> raw data under time pressure, **not a verified spec** — low-confidence fields
> are flagged inline. The learner's review pass is expected to correct real
> things here, not rubber-stamp it. Once reviewed/corrected, this file is
> treated as fixed input by the build stage.

## Business context (inferred)

The dataset models an **e-commerce customer churn** problem. We are given a
customer profile table, a row-level transaction log, and a pre-aggregated
monthly transaction extract. The goal (inferred from the `churned` label in
`customers.csv`) is to engineer features that predict whether a customer will
churn, as of a chosen reference date (`as_of`, conventionally `2026-08-01`).
This is a **retention/engagement** churn framing, not a contractual one:
churn is inferred from a drop in transaction activity, so recency, frequency,
monetary, and return-quality signals are the natural feature families.

> Confidence: medium-high. Column names and the `churned` label strongly
> support this framing; the exact churn definition (e.g. 60-day inactivity)
> is not stated anywhere in the data and is inferred.

## Schemas

### `data/customers.csv` — customer profile (one row per customer)

| Column | dtype | nullable | notes |
|---|---|---|---|
| `customer_id` | int | no | primary key, 1..1500 |
| `signup_date` | date (ISO `YYYY-MM-DD`) | no | customer acquisition date |
| `acquisition_channel` | str | no | one of `organic`, `paid_search`, `social`, `referral` |
| `region` | str | no | one of `east`, `west`, `north`, `south` |
| `churned` | int (0/1) | no | **label**; 1 = churned. Class distribution is imbalanced toward 0. |

> Confidence: high for columns/dtypes (verified via the CSV header and a sample
> of values). `churned` is the training label; it is **not** available at
> scoring time and must never be used as a feature.

### `data/transactions.db` — row-level transactions (SQLite, table `transactions`)

| Column | dtype | nullable | notes |
|---|---|---|---|
| `customer_id` | INTEGER | no | FK to customers; indexed (`idx_transactions_customer_id`) |
| `txn_timestamp` | TEXT (ISO-8601 `YYYY-MM-DD HH:MM:SS.ffffff`) | no | transaction timestamp, sub-second precision |
| `category` | TEXT | no | one of `apparel`, `grocery`, `home`, `sports`, `electronics`, `beauty` |
| `channel` | TEXT | no | one of `web`, `mobile_app`, `store` |
| `amount` | REAL | no | transaction amount in currency units |
| `is_returned` | INTEGER (0/1) | no | 1 = returned transaction |

> Confidence: high for column names/dtypes (verified from the SQLite
> `CREATE TABLE` statement). **Low-confidence, needs verification:** the sign
> convention of `amount` for returned transactions — I have not yet confirmed
> whether returns are stored as positive amounts (flagged only by
> `is_returned=1`) or as negative amounts (refund). The build's `spend_recent`
> feature sidesteps this by summing only non-returned transactions
> (`is_returned=0`), which is unambiguous either way.

### `data/transactions_monthly_agg.parquet` — pre-aggregated customer × month extract

| Column | dtype | nullable | notes |
|---|---|---|---|
| `customer_id` | int | no | FK to customers |
| `txn_month` | datetime (first-of-month) | no | calendar month |
| `txn_count` | int | no | number of transactions that month |
| `total_amount` | float | no | sum of transaction `amount` that month (returns included with their stored sign) |
| `return_count` | int | no | number of returned transactions that month |

> Confidence: high for columns/dtypes (verified from the parquet footer
> schema). The extract is **sparse**: a customer with zero activity in a month
> has **no row** for that month (not a row of zeros). This matters for any
> "active months" feature — the count of rows per customer in a window IS the
> active-month count, by construction.

## Time dimensions

- `customers.signup_date` is a date (day grain).
- `transactions.txn_timestamp` is a timestamp (sub-second grain) — the
  fine-grained source.
- `transactions_monthly_agg.txn_month` is a month (first-of-month grain) —
  the coarse, pre-aggregated source. Transactions span roughly 2025 through
  2026-07-30 (verified range: latest txn on or around 2026-07-30).

> **Sources can disagree at the edges.** The monthly aggregate is an ETL
> product over the row-level table, and a window expressed in *days* (e.g.
> "trailing 90 days") is **not aligned to calendar months**. So a 90-day
> feature computed from the aggregate (≈3 months) can differ from the same
> feature computed from row-level data, depending on where the as-of date
> falls within a month and on any ETL lag. This is the core multi-source
> judgment the feature spec has to make per feature (see feature_spec.md).

## Data-quality realities detected by inspection

1. **Zero-activity customers exist.** **81** of the 1500 customers have **no
   matching rows** in `transactions.db`; **91** have no rows in the monthly
   aggregate (the aggregate count is higher because it is ETL-lagged for the
   latest month — see point 3). These customers must receive the spec's
   explicit zero-activity defaults (e.g. `days_since_last_txn = 9999`,
   `txn_count_recent = 0`), never a bare null/NaN.
   > Confidence: high — verified by cross-source count.

2. **Right-skew in monetary features.** Transaction `amount` is right-skewed:
   mean 49.72, median 33.82, max 1684.21 (a few large spenders, many small
   transactions), typical for e-commerce spend. This is why monetary features
   use the raw sum and why the outlier check sets a generous but finite ceiling
   rather than assuming normality.
   > Confidence: high — verified from the amount distribution.

3. **Source-timing gap — the monthly aggregate is ETL-lagged for the latest
   month.** **212 customer-months** differ between the row-level table and the
   monthly aggregate, **all in 2026-07** (the most recent month): the aggregate
   is missing or stale rows for that month (e.g. customer 2 has a 2026-07-01
   transaction of 3.00 in the row-level data but `NaN`/missing in the
   aggregate). This is **not a defect** in either source — it is the real
   ETL lag — and it is the concrete evidence behind the multi-source judgment:
   any feature whose window includes the latest month must use the row-level
   table, because the aggregate is not current for it.
   > Confidence: high — verified by a row-level-vs-aggregate diff.

4. **Returns are present but a minority.** 591 of 11,742 transactions are
   returns (`is_returned=1`, ~5%), a real but minority signal.
   > Confidence: high — verified by count.

5. **Returned `amount` is stored POSITIVE (flagged only by `is_returned=1`).**
   Verified: returned-amount stats (min 3.0, max 439.76) are positive, same sign
   as non-returned. So `total_amount` in the monthly aggregate INCLUDES returned
   amounts as positive values. The build's `spend_recent` sidesteps this by
   summing only non-returned transactions (`is_returned=0`); `return_rate_90d`
   uses the `is_returned` flag as the numerator.
   > Confidence: high — verified from the returned-amount distribution.

## Open questions for the learner's review

- What is the **exact churn definition** behind `churned`? (Inferred as
  activity-based; not stated in the data.) This affects the as-of date choice
  and which window lengths are meaningful.
- Confirm the **as-of date** `2026-08-01` is the intended scoring reference
  (it is the day after the latest observed transaction 2026-07-31, which is a
  clean scoring boundary — chosen for that reason).

## Verified facts (no longer open)

- The **returned-amount sign convention** is confirmed: returned `amount` is
  POSITIVE, flagged only by `is_returned=1` (see data-quality reality #5).
  This is no longer an open question.
