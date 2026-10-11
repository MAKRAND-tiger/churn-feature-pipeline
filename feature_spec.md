# feature_spec.md — Churn Feature Pipeline

> Filled in by correcting Stage 0's candidate-feature proposal against
> `skill.md`'s Domain Context section. This is the confirmed spec the build
> stage implements faithfully; it is not a Claude-authored draft rubber-stamped
> after the fact. The EXAMPLE section and all `<<LEARNER: ...>>` prompts from
> the skeleton have been deleted.

## Candidate features

Per feature (name, source(s), computation, explicit zero-activity default,
multi-source choice where relevant, and a rationale that names a specific
customer behavior distinct from a plausible confound):

- **Feature**: `days_since_last_txn`
  - **Source**: `data/transactions.db` (table `transactions`, column `txn_timestamp`)
  - **Computation**: `as_of - max(txn_timestamp where txn_timestamp <= as_of)`, in days
  - **Zero-activity default**: `9999` (a finite sentinel meaning "never transacted", not NaN)
  - **If multiple sources could supply this, which and why?**: row-level only — the monthly aggregate stores only a month, not a day, so it cannot express an exact recency.
  - **Rationale**: "This predicts churn because customers whose recency is *growing* are disengaging relative to their own prior cadence, distinct from just low spend/frequency because a customer can spend normally but still be drifting away from an earlier, faster rhythm — the *trend* in recency, not its level, is the signal."

- **Feature**: `txn_count_recent` *(versioned — see below)*
  - **Source**: `data/transactions.db` (table `transactions`, column `txn_timestamp`)
  - **Computation**: `count(*) where txn_timestamp in (as_of - window_days, as_of]`
  - **Zero-activity default**: `0`
  - **If multiple sources could supply this, which and why?**: `transactions.db` — a `window_days` that is not calendar-month-aligned can disagree with the ETL-lagged monthly aggregate at the window edges; row-level precision avoids that.
  - **Rationale**: "This predicts churn because a customer whose recent transaction *frequency* has dropped relative to their own baseline is disengaging, distinct from a customer who has always been low-activity — the drop is the signal, not the level, and only a per-customer-recent window isolates it."

- **Feature**: `spend_recent`
  - **Source**: `data/transactions.db` (table `transactions`, columns `amount`, `is_returned`)
  - **Computation**: `sum(amount where is_returned=0 and txn_timestamp in (as_of - window_days, as_of])` (latest window 90d)
  - **Zero-activity default**: `0.0`
  - **If multiple sources could supply this, which and why?**: `transactions.db` — row-level needed both for window-edge precision and to filter on `is_returned` (the monthly aggregate has `return_count` but no per-returned-amount column).
  - **Rationale**: "This predicts churn because a customer whose recent *spend* has dropped relative to their own baseline is pulling back, distinct from just low frequency because a customer can transact often but spend little (downgrading), which is a different failure mode than transacting rarely."

- **Feature**: `avg_monthly_spend` *(versioned — see below)*
  - **Source**: `data/transactions_monthly_agg.parquet` (column `total_amount`)
  - **Computation**: `sum(total_amount over trailing window_months calendar months) / window_months`
  - **Zero-activity default**: `0.0`
  - **If multiple sources could supply this, which and why?**: the monthly aggregate — this window IS calendar-month-aligned, so the aggregate loses no precision and `total_amount` is already the monthly sum; re-aggregating row-level would be wasteful and ETL-lag-equivalent here.
  - **Rationale**: "This predicts churn because a falling *average monthly spend trajectory* over months shows a sustained pullback, distinct from a single quiet month (which could be vacation/seasonality) — a months-long decline is the disengagement signal, not a one-month dip."

- **Feature**: `active_months_12m`
  - **Source**: `data/transactions_monthly_agg.parquet` (column `txn_month`)
  - **Computation**: count of active customer-months in the trailing 12 calendar months (a month with no activity has no row, so row count per customer in the window IS the active-month count)
  - **Zero-activity default**: `0`
  - **If multiple sources could supply this, which and why?**: the monthly aggregate — naturally suited to the monthly grain; row-level would just be re-deriving month counts.
  - **Rationale**: "This predicts churn because a customer whose *breadth* of activity (number of active months) has narrowed is losing engagement consistency, distinct from just lower total spend/frequency because a customer could concentrate the same spend into fewer months (narrowing breadth) — breadth loss is the disengagement signal a pure spend/count feature misses."

- **Feature**: `return_rate_90d`
  - **Source**: `data/transactions.db` (table `transactions`, column `is_returned`)
  - **Computation**: `sum(is_returned) / count(*) where txn_timestamp in (as_of - 90 days, as_of]`
  - **Zero-activity default**: `0.0` (a customer with no transactions has no returns — not NaN)
  - **If multiple sources could supply this, which and why?**: `transactions.db` — a 90-day window is not calendar-aligned and the per-transaction `is_returned` flag is the natural numerator; the monthly aggregate only approximates 90 days as ~3 months, disagreeing at the edges.
  - **Rationale**: "This predicts churn because a *rising return share* signals unmet expectations / dissatisfaction that can precede churn, distinct from just low spend because a customer can spend normally but still be trending toward churn if an increasing fraction of what they buy comes back — dissatisfaction, not inactivity, is the signal."

- **Feature**: `tenure_days`
  - **Source**: `data/customers.csv` (column `signup_date`)
  - **Computation**: `as_of - signup_date`, in days
  - **Zero-activity default**: `0` (a customer who signed up exactly on `as_of` has zero tenure — a real value, not missing)
  - **If multiple sources could supply this, which and why?**: `customers.csv` only — a static profile attribute, no source ambiguity.
  - **Rationale**: "This predicts churn because newer customers churn at a higher baseline rate than tenured ones (the classic tenure-churn curve), distinct from recency because tenure measures *time since acquisition* while recency measures *time since last activity* — a tenured customer who just went quiet is a different risk profile than a new customer who never engaged."

## Train/score parity design

- **Shared function/code path**: `features.build.build_features(as_of, source_paths=None, customer_ids=None)` — the single entry point both `scripts/build_training_features.py` and `scripts/score_customer.py` call.
- **Only allowed training/scoring difference**: which `customer_ids` are selected at the end (training passes `customer_ids=None` → full base; scoring passes an explicit list). Every transform runs identically either way.
- **How `as_of` is threaded (not hardcoded)**: `as_of` is a required parameter of `build_features` and is passed into every transform function as the `as_of` argument; no transform hardcodes or defaults it. The default `as_of` lives only in the CLI scripts (`--as-of 2026-08-01`), never inside a transform.

## Feature store, versioning & lineage

- **Features versioned**: `txn_count_recent`, `avg_monthly_spend` (two distinct features, each with ≥2 versions — meets the floor).

- **`txn_count_recent`**
  - **Parameter**: `window_days`
  - **Value per version**: v1 = 90, v2 = 30, v3 = 180
  - **Reason each version differs**:
    - v1 (90): initial default engagement horizon.
    - v2 (30): shortened after churn-window analysis showed recent disengagement is most predictive within a single month — isolates the very-recent signal.
    - v3 (180): widened as a long-term-habit stability baseline to contrast against the 30-day signal.

- **`avg_monthly_spend`**
  - **Parameter**: `window_months`
  - **Value per version**: v1 = 6, v2 = 12
  - **Reason each version differs**:
    - v1 (6): initial half-year average, sensitive to recent swings.
    - v2 (12): widened to smooth seasonal spend swings the 6-month window over-weighted; a deliberate smoothing-vs-responsiveness trade-off.

- **What forces a version bump vs. not**: a real change to the **parameter, source, or computation** that materially changes at least some customers' values with a stated business reason — not a renamed column or reformatted description. Each version gets a new registry row + a new parquet file; no version is ever overwritten. `is_latest` flips atomically with the new insert and must point to the **highest** version.
- **What a lineage entry must let someone reconstruct**: source (exact file/table + column) → transform (parameterized computation) → business rationale → feature-store location (registry table + exact `parquet_path`), at enough detail to recompute the feature by hand from raw data without reading any code.

## Multi-source judgment calls

Per feature that could plausibly come from either `transactions.db` or `transactions_monthly_agg.parquet`:

- **`days_since_last_txn`** — **Source chosen**: `transactions.db` — **Why**: recency needs day-precision; the monthly aggregate only has a month, so it cannot express an exact "days since last transaction."
- **`txn_count_recent`** — **Source chosen**: `transactions.db` — **Why**: a `window_days` not aligned to calendar months can disagree with the ETL-lagged aggregate at the window edges; row-level precision is load-bearing for this window.
- **`spend_recent`** — **Source chosen**: `transactions.db` — **Why**: same window-precision reason, plus the need to filter on the per-transaction `is_returned` flag (no returned-amount column in the aggregate).
- **`avg_monthly_spend`** — **Source chosen**: `transactions_monthly_agg.parquet` — **Why**: this window IS calendar-month-aligned, so the aggregate loses no precision and `total_amount` is already the monthly sum; the row-level table would just re-derive the same monthly sum with ETL-lag-equivalent results.
- **`active_months_12m`** — **Source chosen**: `transactions_monthly_agg.parquet` — **Why**: naturally monthly-grained; counting active months = counting rows per customer in the window, which the sparse aggregate already encodes.
- **`return_rate_90d`** — **Source chosen**: `transactions.db` — **Why**: 90-day window precision + the per-transaction `is_returned` numerator; the aggregate can only approximate 90 days as ~3 months.
- **`tenure_days`** — **Source chosen**: `customers.csv` — **Why**: static profile attribute, single source.

## Data-quality checks

Each check raises / exits non-zero on failure (never just logs a warning):

- **Check**: no unexpected nulls in any feature column (per `schema.py`, all features are non-nullable once defaults are applied) — **Catches**: a transform silently dropping a customer, or a reindex step leaving NaN — **On failure**: raise `QualityCheckError` / non-zero exit.
- **Check**: the zero-activity default is actually applied (e.g. `days_since_last_txn == 9999` for never-active customers, never NaN) — **Catches**: the off-by-one reindex/fillna bug that leaves a zero-activity customer with NaN instead of the stated default — **On failure**: raise / non-zero exit.
- **Check**: monetary/aggregate features stay within a sane bound (`spend_recent` < $50,000; `avg_monthly_spend` in [-1,000, 50,000]; `return_rate_90d` in [0,1]; `active_months_12m` in [0,12]) — **Catches**: a unit error or a duplicate-row join inflating spend/counts — **On failure**: raise / non-zero exit.
- **Check**: row count before/after the build reconciles against the customer count (training) or the requested `customer_ids` (scoring) — **Catches**: a join dropping or duplicating customers — **On failure**: raise / non-zero exit.
- **Check**: drift vs. a prior build snapshot — per-feature mean shift above 20% relative change fails — **Catches**: a silent transform change or data-source regression between builds — **On failure**: raise / non-zero exit (skipped cleanly when no reference snapshot exists).
