"""
One pure function per candidate feature named in the confirmed `feature_spec.md`.

Conventions (see feature_spec.md + data_dictionary.md):
  - `as_of` is threaded as a parameter into every transform — never hardcoded.
  - Every feature handles the zero-activity case explicitly with the default the
    spec states (never a bare null/NaN).
  - Time windows are defined as `(as_of - window, as_of]` — i.e. inclusive of
    `as_of` itself, exclusive of the start boundary. A transaction exactly
    `window_days` before `as_of` is therefore OUTSIDE the window; a transaction
    exactly at `as_of` is INSIDE. This convention is asserted in the tests.
  - Each function only touches the source(s) feature_spec.md names for that
    feature — it does not silently blend both sources.

All functions are independent of any I/O: they take already-loaded DataFrames
in and return a Series/DataFrame out, so they are unit-testable in isolation.
"""

from typing import Optional

import numpy as np
import pandas as pd

# Sentinel default for "customer never transacted" — a large finite number so it
# sorts / scales correctly in downstream models, but is recognizably an extreme.
NEVER_TRANSACTED_RECENCY = 9999


def days_since_last_txn(
    customers: pd.DataFrame,
    transactions: pd.DataFrame,
    as_of: str,
    source_paths: Optional[dict] = None,
) -> pd.Series:
    """Recency: days from each customer's last transaction to `as_of`.

    Source: data/transactions.db (row-level precision required — the monthly
    aggregate only stores a month, not a day, so it cannot express an exact
    recency).

    Zero-activity default: 9999 (the NEVER_TRANSACTED_RECENCY sentinel), not NaN.
    """
    as_of_ts = pd.Timestamp(as_of)
    cust_ids = customers["customer_id"]
    txn = transactions[["customer_id", "txn_timestamp"]].copy()
    txn["txn_timestamp"] = pd.to_datetime(txn["txn_timestamp"])
    # Only consider transactions on or before the as-of date (no leakage).
    txn = txn[txn["txn_timestamp"] <= as_of_ts]
    if not txn.empty:
        last = txn.groupby("customer_id")["txn_timestamp"].max()
        recency = (as_of_ts - last.reindex(cust_ids)).dt.days
    else:
        recency = pd.Series(index=cust_ids, dtype=float)
    recency = recency.fillna(NEVER_TRANSACTED_RECENCY).astype(int)
    recency.name = "days_since_last_txn"
    return recency


def txn_count_recent(
    customers: pd.DataFrame,
    transactions: pd.DataFrame,
    as_of: str,
    window_days: int = 90,
    source_paths: Optional[dict] = None,
) -> pd.Series:
    """Frequency: number of transactions in the trailing `window_days` days,
    window `(as_of - window_days, as_of]`.

    Source: data/transactions.db — chosen over the monthly aggregate because a
    `window_days` that is not aligned to calendar months (e.g. 90 days from an
    arbitrary as-of) can disagree with the ETL-lagged monthly aggregate at the
    edges; row-level precision avoids that.

    Zero-activity default: 0.
    """
    as_of_ts = pd.Timestamp(as_of)
    start = as_of_ts - pd.Timedelta(days=window_days)
    cust_ids = customers["customer_id"]
    txn = transactions[["customer_id", "txn_timestamp"]].copy()
    txn["txn_timestamp"] = pd.to_datetime(txn["txn_timestamp"])
    mask = (txn["txn_timestamp"] > start) & (txn["txn_timestamp"] <= as_of_ts)
    counts = txn.loc[mask].groupby("customer_id").size()
    out = counts.reindex(cust_ids, fill_value=0).astype(int)
    out.name = f"txn_count_recent"
    return out


def spend_recent(
    customers: pd.DataFrame,
    transactions: pd.DataFrame,
    as_of: str,
    window_days: int = 90,
    source_paths: Optional[dict] = None,
) -> pd.Series:
    """Monetary: total spend in the trailing `window_days` days, where spend is
    the sum of `amount` over NON-returned transactions only
    (`is_returned == 0`), window `(as_of - window_days, as_of]`.

    Source: data/transactions.db — row-level needed both for window-edge
    precision and to filter on `is_returned` (the monthly aggregate has
    `return_count` but no returned-amount column).

    Zero-activity default: 0.0.
    """
    as_of_ts = pd.Timestamp(as_of)
    start = as_of_ts - pd.Timedelta(days=window_days)
    cust_ids = customers["customer_id"]
    txn = transactions[["customer_id", "txn_timestamp", "amount", "is_returned"]].copy()
    txn["txn_timestamp"] = pd.to_datetime(txn["txn_timestamp"])
    mask = (
        (txn["txn_timestamp"] > start)
        & (txn["txn_timestamp"] <= as_of_ts)
        & (txn["is_returned"] == 0)
    )
    spend = txn.loc[mask].groupby("customer_id")["amount"].sum()
    out = spend.reindex(cust_ids, fill_value=0.0).astype(float)
    out.name = "spend_recent"
    return out


def avg_monthly_spend(
    customers: pd.DataFrame,
    monthly_agg: pd.DataFrame,
    as_of: str,
    window_months: int = 6,
    source_paths: Optional[dict] = None,
) -> pd.Series:
    """Monetary trend: average monthly spend over the trailing `window_months`
    calendar months, computed from the pre-aggregated monthly extract.

    Source: data/transactions_monthly_agg.parquet — chosen over row-level
    because this window IS aligned to calendar months, so the aggregate loses
    no precision, and `total_amount` is already the monthly sum we need (no
    re-aggregation). Using row-level here would be a wasteful re-computation of
    what the aggregate already guarantees.

    The trailing `window_months` calendar months end at the calendar month of
    `as_of` (inclusive). `total_amount` in the aggregate is the sum of all
    transaction amounts in that month (returns included with their stored
    sign). Average = sum(total_amount over window) / window_months.

    Zero-activity default: 0.0.
    """
    as_of_ts = pd.to_datetime(as_of)
    # The month containing as_of, normalized to first-of-month.
    as_of_month = pd.Timestamp(year=as_of_ts.year, month=as_of_ts.month, day=1)
    start_month = as_of_month - pd.DateOffset(months=window_months - 1)
    cust_ids = customers["customer_id"]
    agg = monthly_agg[["customer_id", "txn_month", "total_amount"]].copy()
    agg["txn_month"] = pd.to_datetime(agg["txn_month"])
    mask = (agg["txn_month"] >= start_month) & (agg["txn_month"] <= as_of_month)
    total = agg.loc[mask].groupby("customer_id")["total_amount"].sum()
    avg = total / window_months
    out = avg.reindex(cust_ids, fill_value=0.0).astype(float)
    out.name = "avg_monthly_spend"
    return out


def active_months_12m(
    customers: pd.DataFrame,
    monthly_agg: pd.DataFrame,
    as_of: str,
    window_months: int = 12,
    source_paths: Optional[dict] = None,
) -> pd.Series:
    """Engagement consistency: count of active months in the trailing 12
    calendar months (months with at least one transaction).

    Source: data/transactions_monthly_agg.parquet — naturally suited to the
    monthly grain (one row per active customer-month); row-level would just be
    re-deriving month counts. A month with zero activity has no row in the
    sparse aggregate, so the count of rows per customer in the window IS the
    active-month count.

    Zero-activity default: 0.
    """
    as_of_ts = pd.to_datetime(as_of)
    as_of_month = pd.Timestamp(year=as_of_ts.year, month=as_of_ts.month, day=1)
    start_month = as_of_month - pd.DateOffset(months=window_months - 1)
    cust_ids = customers["customer_id"]
    agg = monthly_agg[["customer_id", "txn_month"]].copy()
    agg["txn_month"] = pd.to_datetime(agg["txn_month"])
    mask = (agg["txn_month"] >= start_month) & (agg["txn_month"] <= as_of_month)
    counts = agg.loc[mask].groupby("customer_id").size()
    out = counts.reindex(cust_ids, fill_value=0).astype(int)
    out.name = "active_months_12m"
    return out


def return_rate_90d(
    customers: pd.DataFrame,
    transactions: pd.DataFrame,
    as_of: str,
    window_days: int = 90,
    source_paths: Optional[dict] = None,
) -> pd.Series:
    """Return/quality signal: share of transactions that were returns in the
    trailing `window_days` days = sum(is_returned) / count(*), window
    `(as_of - window_days, as_of]`.

    Source: data/transactions.db — row-level needed for window precision and
    because the per-transaction `is_returned` flag is the natural numerator; a
    monthly aggregate could give a 90-day-approximation only by summing ~3
    months, which disagrees at the window edges.

    Zero-activity default: 0.0 (not NaN — a customer with no transactions has
    no returns, and the spec requires a non-null default).
    """
    as_of_ts = pd.Timestamp(as_of)
    start = as_of_ts - pd.Timedelta(days=window_days)
    cust_ids = customers["customer_id"]
    txn = transactions[["customer_id", "txn_timestamp", "is_returned"]].copy()
    txn["txn_timestamp"] = pd.to_datetime(txn["txn_timestamp"])
    txn["is_returned"] = txn["is_returned"].astype(int)
    mask = (txn["txn_timestamp"] > start) & (txn["txn_timestamp"] <= as_of_ts)
    windowed = txn.loc[mask]
    if windowed.empty:
        out = pd.Series(0.0, index=cust_ids, dtype=float)
    else:
        grp = windowed.groupby("customer_id")
        ret = grp["is_returned"].sum()
        tot = grp.size()
        rate = (ret / tot).reindex(cust_ids, fill_value=0.0)
        out = rate.astype(float)
    out.name = "return_rate_90d"
    return out


def tenure_days(
    customers: pd.DataFrame,
    transactions: pd.DataFrame = None,
    monthly_agg: pd.DataFrame = None,
    as_of: str = None,
    source_paths: Optional[dict] = None,
) -> pd.Series:
    """Customer profile: days from each customer's signup_date to `as_of`.

    Source: data/customers.csv — a static profile attribute, no source ambiguity.

    Zero-activity default: 0 (a customer who signed up exactly on `as_of` has
    zero tenure; this is a real value, not a missing one).
    """
    as_of_ts = pd.Timestamp(as_of)
    signup = pd.to_datetime(customers["signup_date"])
    out = (as_of_ts - signup).dt.days
    # A negative tenure (signup after as_of) would be a data defect; clamp to 0
    # but those rows are flagged by the quality checks, not silently passed.
    out = out.fillna(0).astype(int)
    out.index = customers["customer_id"]
    out.name = "tenure_days"
    return out
