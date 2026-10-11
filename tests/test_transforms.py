"""
Tests for each feature function in features/transforms.py, in isolation.

Per skill.md's Workflow: each feature gets, at minimum, a normal case, a
zero-activity case, a single-record case, and (where relevant) a case right at
a time-window boundary.

These tests build tiny synthetic frames and call the transform functions
directly — no I/O, no feature store — so a failure points straight at the
transform logic.
"""

import numpy as np
import pandas as pd

from features import transforms


def _customers(ids):
    return pd.DataFrame({"customer_id": ids, "signup_date": pd.to_datetime(["2024-01-01"] * len(ids))})


def _txn_frame(rows):
    # rows: list of (customer_id, txn_timestamp, amount, is_returned)
    return pd.DataFrame(
        rows,
        columns=["customer_id", "txn_timestamp", "amount", "is_returned"],
    )


# ---------------------------------------------------------------------------
# days_since_last_txn
# ---------------------------------------------------------------------------

def test_recency_normal_case():
    cust = _customers([1])
    txn = _txn_frame([(1, "2026-07-01", 10.0, 0)])
    r = transforms.days_since_last_txn(cust, txn, as_of="2026-08-01")
    assert r.iloc[0] == 31


def test_recency_zero_activity_returns_sentinel_not_nan():
    cust = _customers([99])  # no transactions
    txn = _txn_frame([(1, "2026-07-01", 10.0, 0)])
    r = transforms.days_since_last_txn(cust, txn, as_of="2026-08-01")
    assert r.iloc[0] == transforms.NEVER_TRANSACTED_RECENCY
    assert not pd.isna(r.iloc[0])


def test_recency_single_record():
    cust = _customers([1])
    txn = _txn_frame([(1, "2026-08-01 00:00:00", 5.0, 0)])
    r = transforms.days_since_last_txn(cust, txn, as_of="2026-08-01")
    assert r.iloc[0] == 0  # same day


def test_recency_uses_only_on_or_before_as_of_no_leakage():
    cust = _customers([1])
    txn = _txn_frame([
        (1, "2026-07-01", 10.0, 0),
        (1, "2026-09-01", 20.0, 0),  # after as_of -> must be ignored
    ])
    r = transforms.days_since_last_txn(cust, txn, as_of="2026-08-01")
    assert r.iloc[0] == 31


# ---------------------------------------------------------------------------
# txn_count_recent (versioned: window_days)
# ---------------------------------------------------------------------------

def test_txn_count_normal_case():
    cust = _customers([1])
    txn = _txn_frame([
        (1, "2026-07-15", 10.0, 0),
        (1, "2026-07-20", 10.0, 0),
        (1, "2026-05-01", 10.0, 0),  # >90 days ago, outside 90d window
    ])
    c = transforms.txn_count_recent(cust, txn, as_of="2026-08-01", window_days=90)
    assert c.iloc[0] == 2


def test_txn_count_zero_activity_returns_zero_not_nan():
    cust = _customers([99])
    txn = _txn_frame([(1, "2026-07-15", 10.0, 0)])
    c = transforms.txn_count_recent(cust, txn, as_of="2026-08-01", window_days=90)
    assert c.iloc[0] == 0


def test_txn_count_single_record():
    cust = _customers([1])
    txn = _txn_frame([(1, "2026-07-31", 10.0, 0)])
    c = transforms.txn_count_recent(cust, txn, as_of="2026-08-01", window_days=90)
    assert c.iloc[0] == 1


def test_txn_count_time_window_boundary_inclusive_of_as_of():
    # Convention: (as_of - window, as_of]. A txn exactly 90 days before is OUT;
    # a txn exactly at as_of is IN.
    cust = _customers([1])
    txn = _txn_frame([
        (1, "2026-05-03", 10.0, 0),  # exactly 90 days before 2026-08-01 -> OUT
        (1, "2026-05-04", 10.0, 0),  # 89 days before -> IN
        (1, "2026-08-01", 10.0, 0),  # exactly as_of -> IN
    ])
    c = transforms.txn_count_recent(cust, txn, as_of="2026-08-01", window_days=90)
    assert c.iloc[0] == 2


def test_txn_count_versioning_param_changes_value():
    # The versioning exercise: a shorter window yields a different (smaller or
    # equal) count for a customer with spread-out activity.
    cust = _customers([1])
    txn = _txn_frame([
        (1, "2026-07-15", 10.0, 0),
        (1, "2026-04-01", 10.0, 0),  # ~122 days before as_of
    ])
    c90 = transforms.txn_count_recent(cust, txn, as_of="2026-08-01", window_days=90)
    c30 = transforms.txn_count_recent(cust, txn, as_of="2026-08-01", window_days=30)
    c180 = transforms.txn_count_recent(cust, txn, as_of="2026-08-01", window_days=180)
    assert c90.iloc[0] == 1 and c30.iloc[0] == 1 and c180.iloc[0] == 2


# ---------------------------------------------------------------------------
# spend_recent
# ---------------------------------------------------------------------------

def test_spend_normal_case_excludes_returns():
    cust = _customers([1])
    txn = _txn_frame([
        (1, "2026-07-15", 50.0, 0),
        (1, "2026-07-20", 30.0, 1),  # returned -> excluded
        (1, "2026-05-01", 20.0, 0),   # outside 90d
    ])
    s = transforms.spend_recent(cust, txn, as_of="2026-08-01", window_days=90)
    assert s.iloc[0] == 50.0


def test_spend_zero_activity_returns_zero_not_nan():
    cust = _customers([99])
    txn = _txn_frame([(1, "2026-07-15", 50.0, 0)])
    s = transforms.spend_recent(cust, txn, as_of="2026-08-01", window_days=90)
    assert s.iloc[0] == 0.0


def test_spend_single_record():
    cust = _customers([1])
    txn = _txn_frame([(1, "2026-07-31", 25.0, 0)])
    s = transforms.spend_recent(cust, txn, as_of="2026-08-01", window_days=90)
    assert s.iloc[0] == 25.0


def test_spend_time_window_boundary():
    cust = _customers([1])
    txn = _txn_frame([
        (1, "2026-05-03", 100.0, 0),  # exactly 90 days before -> OUT
        (1, "2026-05-04", 7.0, 0),    # 89 days before -> IN
        (1, "2026-08-01", 13.0, 0),   # as_of -> IN
    ])
    s = transforms.spend_recent(cust, txn, as_of="2026-08-01", window_days=90)
    assert s.iloc[0] == 20.0


# ---------------------------------------------------------------------------
# avg_monthly_spend (versioned: window_months)
# ---------------------------------------------------------------------------

def _monthly_agg_frame(rows):
    # rows: (customer_id, txn_month, total_amount)
    return pd.DataFrame(rows, columns=["customer_id", "txn_month", "total_amount"])


def test_avg_monthly_spend_normal_case():
    cust = _customers([1])
    agg = _monthly_agg_frame([
        (1, "2026-03-01", 100.0),
        (1, "2026-05-01", 200.0),
        (1, "2026-06-01", 300.0),
    ])
    # as_of 2026-08-01; window_months=6 -> months 2026-03..2026-08 inclusive
    # total = 100 + 200 + 300 = 600; avg = 600/6 = 100
    a = transforms.avg_monthly_spend(cust, agg, as_of="2026-08-01", window_months=6)
    assert a.iloc[0] == 100.0


def test_avg_monthly_spend_zero_activity_returns_zero():
    cust = _customers([99])
    agg = _monthly_agg_frame([(1, "2026-06-01", 300.0)])
    a = transforms.avg_monthly_spend(cust, agg, as_of="2026-08-01", window_months=6)
    assert a.iloc[0] == 0.0


def test_avg_monthly_spend_versioning_window_months_changes_value():
    cust = _customers([1])
    agg = _monthly_agg_frame([
        (1, "2025-09-01", 1000.0),  # in 12m window only
        (1, "2026-06-01", 60.0),     # in both 6m and 12m
        (1, "2026-07-01", 120.0),    # in both
    ])
    # as_of 2026-08-01
    a6 = transforms.avg_monthly_spend(cust, agg, as_of="2026-08-01", window_months=6)
    a12 = transforms.avg_monthly_spend(cust, agg, as_of="2026-08-01", window_months=12)
    # 6m window = 2026-03..2026-08: total = 60+120 = 180, avg = 180/6 = 30
    assert a6.iloc[0] == 30.0
    # 12m window = 2025-09..2026-08: total = 1000+60+120 = 1180, avg = 1180/12
    assert a12.iloc[0] == 1180.0 / 12.0
    assert a6.iloc[0] != a12.iloc[0]


def test_avg_monthly_spend_excludes_future_months():
    cust = _customers([1])
    agg = _monthly_agg_frame([
        (1, "2026-08-01", 999.0),  # month of as_of -> IN
        (1, "2026-09-01", 500.0),  # after as_of month -> OUT
    ])
    a = transforms.avg_monthly_spend(cust, agg, as_of="2026-08-01", window_months=6)
    assert a.iloc[0] == 999.0 / 6.0


# ---------------------------------------------------------------------------
# active_months_12m
# ---------------------------------------------------------------------------

def test_active_months_normal_case():
    cust = _customers([1])
    # Trailing 12-month window ending at 2026-08 = [2025-09, 2026-08] (12 months).
    agg = pd.DataFrame([
        (1, "2026-01-01", 10.0),   # IN
        (1, "2026-03-01", 10.0),   # IN
        (1, "2026-07-01", 10.0),   # IN
        (1, "2025-09-01", 10.0),   # start boundary of the 12m window -> IN
        (1, "2025-08-01", 10.0),   # 13 months before as_of month -> OUT
    ], columns=["customer_id", "txn_month", "total_amount"])
    a = transforms.active_months_12m(cust, agg, as_of="2026-08-01", window_months=12)
    assert a.iloc[0] == 4


def test_active_months_window_boundary():
    """A trailing N-month window is [as_of_month - (N-1), as_of_month]; the
    start-boundary month is IN, one month earlier is OUT."""
    cust = _customers([1])
    agg = pd.DataFrame([
        (1, "2025-09-01", 10.0),  # 11 months before 2026-08 -> start boundary -> IN
        (1, "2025-08-01", 10.0),  # 12 months before -> OUT
        (1, "2026-08-01", 10.0),  # as_of month -> IN
    ], columns=["customer_id", "txn_month", "total_amount"])
    a = transforms.active_months_12m(cust, agg, as_of="2026-08-01", window_months=12)
    assert a.iloc[0] == 2


def test_active_months_zero_activity():
    cust = _customers([99])
    agg = pd.DataFrame([(1, "2026-01-01", 10.0)], columns=["customer_id", "txn_month", "total_amount"])
    a = transforms.active_months_12m(cust, agg, as_of="2026-08-01", window_months=12)
    assert a.iloc[0] == 0


def test_active_months_single_record():
    cust = _customers([1])
    agg = pd.DataFrame([(1, "2026-07-01", 10.0)], columns=["customer_id", "txn_month", "total_amount"])
    a = transforms.active_months_12m(cust, agg, as_of="2026-08-01", window_months=12)
    assert a.iloc[0] == 1


# ---------------------------------------------------------------------------
# return_rate_90d
# ---------------------------------------------------------------------------

def test_return_rate_normal_case():
    cust = _customers([1])
    txn = _txn_frame([
        (1, "2026-07-15", 10.0, 0),
        (1, "2026-07-20", 10.0, 1),
        (1, "2026-07-25", 10.0, 1),
        (1, "2026-05-01", 10.0, 1),  # outside 90d
    ])
    r = transforms.return_rate_90d(cust, txn, as_of="2026-08-01", window_days=90)
    assert r.iloc[0] == 2 / 3


def test_return_rate_zero_activity_returns_zero_not_nan():
    cust = _customers([99])
    txn = _txn_frame([(1, "2026-07-15", 10.0, 1)])
    r = transforms.return_rate_90d(cust, txn, as_of="2026-08-01", window_days=90)
    assert r.iloc[0] == 0.0


def test_return_rate_single_record_returned():
    cust = _customers([1])
    txn = _txn_frame([(1, "2026-07-31", 10.0, 1)])
    r = transforms.return_rate_90d(cust, txn, as_of="2026-08-01", window_days=90)
    assert r.iloc[0] == 1.0


def test_return_rate_in_bounds_zero_to_one():
    cust = _customers([1])
    txn = _txn_frame([
        (1, "2026-07-15", 10.0, 0),
        (1, "2026-07-20", 10.0, 1),
    ])
    r = transforms.return_rate_90d(cust, txn, as_of="2026-08-01", window_days=90)
    assert 0.0 <= r.iloc[0] <= 1.0


# ---------------------------------------------------------------------------
# tenure_days
# ---------------------------------------------------------------------------

def test_tenure_normal_case():
    cust = pd.DataFrame({"customer_id": [1], "signup_date": pd.to_datetime(["2026-01-01"])})
    t = transforms.tenure_days(cust, as_of="2026-08-01")
    assert t.iloc[0] == 212  # Jan 1 -> Aug 1 2026


def test_tenure_zero_case_signup_on_as_of():
    cust = pd.DataFrame({"customer_id": [1], "signup_date": pd.to_datetime(["2026-08-01"])})
    t = transforms.tenure_days(cust, as_of="2026-08-01")
    assert t.iloc[0] == 0
