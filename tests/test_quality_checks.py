"""
Feed each check in features/quality_checks.py a deliberately bad input (an
injected null, an out-of-range amount, a shifted distribution) and confirm it
fires; feed it clean input and confirm it doesn't false-positive.
"""

import numpy as np
import pandas as pd

from features import quality_checks as qc


def _clean_features(n=20):
    return pd.DataFrame({
        "customer_id": range(n),
        "as_of_date": pd.Timestamp("2026-08-01"),
        "days_since_last_txn": 30,
        "txn_count_recent": 5,
        "spend_recent": 200.0,
        "avg_monthly_spend": 100.0,
        "active_months_12m": 6,
        "return_rate_90d": 0.1,
        "tenure_days": 400,
    })


def test_null_check_fires_on_injected_null():
    bad = _clean_features()
    bad.loc[3, "spend_recent"] = np.nan
    res = qc.check_no_unexpected_nulls(bad)
    assert res["passed"] is False
    assert "spend_recent" in res["failing_features"]


def test_null_check_does_not_fire_on_clean_input():
    res = qc.check_no_unexpected_nulls(_clean_features())
    assert res["passed"] is True
    assert res["failing_features"] == []


def test_zero_activity_default_check_fires_on_nan_recency():
    bad = _clean_features()
    bad.loc[2, "days_since_last_txn"] = np.nan  # should be 9999, not NaN
    res = qc.check_zero_activity_defaults_applied(bad)
    assert res["passed"] is False


def test_zero_activity_default_check_passes_on_sentinel():
    good = _clean_features()
    good.loc[2, "days_since_last_txn"] = 9999  # the sentinel default
    res = qc.check_zero_activity_defaults_applied(good)
    assert res["passed"] is True


def test_outlier_check_fires_on_out_of_range_value():
    bad = _clean_features()
    bad.loc[0, "spend_recent"] = 999_999.0  # above 50k bound
    res = qc.check_outliers(bad)
    assert res["passed"] is False
    assert "spend_recent" in res["failing_features"]


def test_outlier_check_fires_on_return_rate_above_one():
    bad = _clean_features()
    bad.loc[0, "return_rate_90d"] = 1.5  # a rate must be in [0,1]
    res = qc.check_outliers(bad)
    assert res["passed"] is False
    assert "return_rate_90d" in res["failing_features"]


def test_outlier_check_does_not_fire_on_clean_input():
    res = qc.check_outliers(_clean_features())
    assert res["passed"] is True


def test_drift_check_fires_on_shifted_distribution():
    ref = _clean_features()
    cur = _clean_features()
    # Shift a feature's mean by well over the 20% threshold.
    cur["spend_recent"] = cur["spend_recent"] * 5.0
    res = qc.check_drift(cur, reference=ref)
    assert res["passed"] is False
    assert "spend_recent" in res["failing_features"]


def test_drift_check_passes_with_no_reference():
    res = qc.check_drift(_clean_features(), reference=None)
    assert res["passed"] is True  # not load-bearing without a reference


def test_drift_check_passes_on_clean_input():
    ref = _clean_features()
    res = qc.check_drift(_clean_features(), reference=ref)
    assert res["passed"] is True


def test_row_count_check_fires_on_mismatch():
    res = qc.check_row_count(_clean_features(n=20), expected=25)
    assert res["passed"] is False


def test_row_count_check_passes_on_match():
    res = qc.check_row_count(_clean_features(n=20), expected=20)
    assert res["passed"] is True


def test_run_all_checks_raises_on_failure():
    bad = _clean_features()
    bad.loc[0, "spend_recent"] = 999_999.0
    res = qc.run_all_checks(bad, expected_rows=len(bad))
    assert res["passed"] is False


def test_run_all_checks_passes_on_clean():
    res = qc.run_all_checks(_clean_features(), expected_rows=20)
    assert res["passed"] is True
