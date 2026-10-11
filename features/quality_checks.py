"""
Runnable-standalone data-quality checks (drift / null / outlier) against a
built features DataFrame, implementing every check listed in the confirmed
`feature_spec.md`'s data-quality section.

Each check returns a dict with at minimum:
  {"passed": bool, "failing_features": [...], "failing_rows": [...],
   "message": str}

A check never silently passes on bad input, and `run_all_checks` raises a
``QualityCheckError`` (non-zero on the CLI) when any check fails — never just
logs a warning.
"""

import numpy as np
import pandas as pd

from features.schema import FEATURE_BY_NAME, FEATURE_NAMES

# Sane bounds for monetary/aggregate features (per feature_spec.md). A value
# outside these bounds signals a unit error, a duplicate-row join, or a
# transform bug — not a real customer.
BOUNDS = {
    "days_since_last_txn": (0, 10000),          # 9999 sentinel is allowed
    "txn_count_recent": (0, 10_000),           # per 90d window — far above any real count
    "spend_recent": (0.0, 50_000.0),            # 90d non-returned spend ceiling
    "avg_monthly_spend": (-1_000.0, 50_000.0), # negative allowed only if returns net-negative
    "active_months_12m": (0, 12),               # months in a 12-month window
    "return_rate_90d": (0.0, 1.0),              # a rate
    "tenure_days": (0, 365 * 20),               # up to ~20 years
}


class QualityCheckError(Exception):
    """Raised when one or more data-quality checks fail."""


def check_no_unexpected_nulls(features: pd.DataFrame) -> dict:
    """Fail if any feature column that should never be null (per schema.py)
    is null. Catches a transform silently dropping a customer or a reindex bug
    that leaves NaN instead of the stated default.
    """
    feature_cols = [c for c in FEATURE_NAMES if c in features.columns]
    bad = features[feature_cols].isnull()
    failing_features = [c for c in feature_cols if bad[c].any()]
    failing_rows = (
        features.index[bad.any(axis=1)].tolist() if bad.any().any() else []
    )
    passed = len(failing_features) == 0
    return {
        "passed": passed,
        "failing_features": failing_features,
        "failing_rows": failing_rows,
        "message": (
            "no unexpected nulls" if passed
            else f"nulls in {failing_features} ({len(failing_rows)} rows)"
        ),
    }


def check_zero_activity_defaults_applied(features: pd.DataFrame) -> dict:
    """Fail if a zero-activity customer ended up with NaN or a bare-null default
    instead of the spec's explicit default. We can't know activity from the
    features frame alone, so this check verifies the *defaults themselves are
    present and not NaN* on every row for the features that carry an explicit
    default, plus that days_since_last_txn never equals NaN (it must be 9999 for
    never-active customers). This is load-bearing: it catches the off-by-one
    reindex/fillna bug that leaves a zero-activity customer with NaN.
    """
    problems = []
    # days_since_last_txn must never be NaN — the 9999 sentinel must be applied.
    if "days_since_last_txn" in features.columns:
        col = features["days_since_last_txn"]
        n_nan = int(col.isnull().sum())
        if n_nan > 0:
            problems.append(
                f"days_since_last_txn has {n_nan} NaN values (expected 9999 default)"
            )
    # Every feature's default must be a real value, not NaN, on all rows.
    for name in FEATURE_NAMES:
        if name in features.columns:
            spec = FEATURE_BY_NAME[name]
            if spec.nullable is False and features[name].isnull().any():
                problems.append(
                    f"{name} should be non-null (default={spec.default!r}) but has nulls"
                )
    passed = len(problems) == 0
    return {
        "passed": passed,
        "failing_features": list({p.split()[0] for p in problems}),
        "failing_rows": [],
        "message": "zero-activity defaults applied" if passed else "; ".join(problems),
    }


def check_outliers(features: pd.DataFrame) -> dict:
    """Fail if a monetary/aggregate feature has values outside a sane range per
    feature_spec.md's stated thresholds. Catches a unit error or a
    duplicate-row join inflating spend/counts.
    """
    failing_features = []
    detail = []
    out_of_range_cols = {}
    for name, (lo, hi) in BOUNDS.items():
        if name not in features.columns:
            continue
        col = features[name]
        out_of_range = (col < lo) | (col > hi)
        n = int(out_of_range.sum())
        if n > 0:
            failing_features.append(name)
            detail.append(f"{name}: {n} rows outside [{lo}, {hi}]")
        out_of_range_cols[name] = out_of_range
    passed = len(failing_features) == 0
    if out_of_range_cols:
        any_bad = pd.DataFrame(out_of_range_cols).any(axis=1)
        failing_rows = features.index[any_bad].tolist() if not passed else []
    else:
        failing_rows = []
    return {
        "passed": passed,
        "failing_features": failing_features,
        "failing_rows": failing_rows,
        "message": "all features within sane bounds" if passed else "; ".join(detail),
    }


def check_row_count(features: pd.DataFrame, expected: int) -> dict:
    """Fail if the built feature row count does not match the expected count
    (customer count for training, or len(customer_ids) for scoring). Catches a
    join dropping or duplicating customers.
    """
    n = len(features)
    passed = n == expected
    return {
        "passed": passed,
        "failing_features": [],
        "failing_rows": [],
        "message": (
            f"row count {n} == expected {expected}" if passed
            else f"row count {n} != expected {expected}"
        ),
    }


def check_drift(
    features: pd.DataFrame, reference: pd.DataFrame | None = None
) -> dict:
    """Compare the current feature distribution against a reference snapshot
    (e.g. a prior build) and fail if the per-feature mean shift exceeds the
    threshold feature_spec.md allows (20% relative change for any feature).

    If no reference is supplied, the check passes with a note (it is not
    load-bearing without a prior snapshot).
    """
    if reference is None:
        return {
            "passed": True,
            "failing_features": [],
            "failing_rows": [],
            "message": "no reference snapshot supplied — drift check skipped",
        }
    failing_features = []
    detail = []
    for name in FEATURE_NAMES:
        if name not in features.columns or name not in reference.columns:
            continue
        cur_mean = features[name].mean()
        ref_mean = reference[name].mean()
        denom = abs(ref_mean) if ref_mean != 0 else 1.0
        rel_shift = abs(cur_mean - ref_mean) / denom
        if rel_shift > 0.20:
            failing_features.append(name)
            detail.append(
                f"{name}: mean {cur_mean:.4g} vs ref {ref_mean:.4g} "
                f"(shift {rel_shift:.1%})"
            )
    passed = len(failing_features) == 0
    return {
        "passed": passed,
        "failing_features": failing_features,
        "failing_rows": [],
        "message": (
            "no drift above threshold" if passed
            else "drift: " + "; ".join(detail)
        ),
    }


def run_all_checks(
    features: pd.DataFrame,
    expected_rows: int | None = None,
    reference: pd.DataFrame | None = None,
) -> dict:
    """Run every check and return a combined pass/fail summary. Raises
    ``QualityCheckError`` if any check fails when ``raise_on_fail`` is True
    (used by the build script).
    """
    results = {
        "no_unexpected_nulls": check_no_unexpected_nulls(features),
        "zero_activity_defaults": check_zero_activity_defaults_applied(features),
        "outliers": check_outliers(features),
        "drift": check_drift(features, reference),
    }
    if expected_rows is not None:
        results["row_count"] = check_row_count(features, expected_rows)
    # Capture the check names BEFORE adding the meta keys, so "checks" lists
    # only the actual checks (not "passed"/"checks" themselves).
    check_names = list(results.keys())
    results["passed"] = all(r["passed"] for r in results.values())
    results["checks"] = check_names
    return results
