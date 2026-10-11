"""
The ONE shared feature-build entry point. Both `scripts/build_training_features.py`
(training path: a historical as-of date, batch of many customers) and
`scripts/score_customer.py` (scoring path: single customer_id, same as-of date)
call this same function — that is the entire train/score parity guarantee for
this pipeline.

There is exactly one code path here. The ONLY difference between training and
scoring is which `customer_ids` are selected at the end; every transform runs
identically either way, and `as_of` is threaded through as a parameter
everywhere (never hardcoded or defaulted inside a transform).
"""

from typing import Optional

import pandas as pd

from features import ingest, transforms
from features.schema import (
    FEATURE_NAMES,
    FEATURE_BY_NAME,
    VERSIONED_FEATURES,
)

# Default source paths (relative to repo root, where data/ lives).
DEFAULT_SOURCE_PATHS = {
    "customers": "data/customers.csv",
    "transactions": "data/transactions.db",
    "monthly_agg": "data/transactions_monthly_agg.parquet",
}


def build_features(
    as_of: str,
    source_paths: dict | None = None,
    customer_ids: list[int] | None = None,
    version_overrides: dict | None = None,
) -> pd.DataFrame:
    """Build the full feature set as of `as_of` for either the whole customer
    base (training path, `customer_ids=None`) or a specific subset (scoring
    path, one or more `customer_ids`).

    Parameters
    ----------
    as_of : str
        The as-of date for feature computation (e.g. "2026-08-01"). Threaded
        into every transform; never hardcoded.
    source_paths : dict, optional
        Override paths to the three raw sources. Keys: "customers",
        "transactions", "monthly_agg". Defaults to the standard data/ locations.
    customer_ids : list[int], optional
        If provided, features are built only for these customers (scoring
        path). If None, the full customer base is used (training path). This
        filtering is the ONLY allowed difference between training and scoring.
    version_overrides : dict, optional
        Optional map of feature_name -> parameter value, used by the
        versioning exercise to register non-latest versions (e.g.
        {"txn_count_recent": 30}). When a feature is not in this map (or the
        map is None), the feature is built with its default/latest parameter.

    Returns
    -------
    pd.DataFrame with one row per requested customer_id, one column per
    candidate feature, plus `customer_id` and `as_of_date`.
    """
    paths = dict(DEFAULT_SOURCE_PATHS)
    if source_paths is not None:
        paths.update(source_paths)

    # Load all three sources via features/ingest.py — no direct file I/O here.
    customers = ingest.load_customers(paths["customers"])
    transactions = ingest.load_transactions(paths["transactions"])
    monthly_agg = ingest.load_monthly_agg(paths["monthly_agg"])

    # Select the customer set: full base (training) or a subset (scoring).
    # This is the ONLY difference allowed between the two call sites.
    if customer_ids is not None:
        customers = customers[customers["customer_id"].isin(customer_ids)].copy()
        if customers.empty:
            raise ValueError(
                f"None of the requested customer_ids {customer_ids} exist in "
                f"customers.csv."
            )

    # The set of customers we build for, in a stable order.
    customers = customers.sort_values("customer_id").reset_index(drop=True)

    # Build each candidate feature via the single shared transform path.
    feat_df = pd.DataFrame({"customer_id": customers["customer_id"]})
    feat_df["as_of_date"] = pd.Timestamp(as_of)

    # Determine parameter values for each feature (default vs overridden).
    def param_for(name: str, default: object) -> object:
        if version_overrides is not None and name in version_overrides:
            return version_overrides[name]
        return default

    # 1. days_since_last_txn (no tunable param)
    feat_df["days_since_last_txn"] = transforms.days_since_last_txn(
        customers, transactions, as_of=as_of
    ).values

    # 2. txn_count_recent (versioned: param window_days, latest=90)
    feat_df["txn_count_recent"] = transforms.txn_count_recent(
        customers, transactions, as_of=as_of,
        window_days=param_for("txn_count_recent", 90),
    ).values

    # 3. spend_recent (param window_days, default 90 — single-version candidate)
    feat_df["spend_recent"] = transforms.spend_recent(
        customers, transactions, as_of=as_of,
        window_days=param_for("spend_recent", 90),
    ).values

    # 4. avg_monthly_spend (versioned: param window_months, latest=6)
    feat_df["avg_monthly_spend"] = transforms.avg_monthly_spend(
        customers, monthly_agg, as_of=as_of,
        window_months=param_for("avg_monthly_spend", 6),
    ).values

    # 5. active_months_12m (param window_months, default 12 — single-version)
    feat_df["active_months_12m"] = transforms.active_months_12m(
        customers, monthly_agg, as_of=as_of,
        window_months=param_for("active_months_12m", 12),
    ).values

    # 6. return_rate_90d (param window_days, default 90 — single-version)
    feat_df["return_rate_90d"] = transforms.return_rate_90d(
        customers, transactions, as_of=as_of,
        window_days=param_for("return_rate_90d", 90),
    ).values

    # 7. tenure_days (no tunable param)
    feat_df["tenure_days"] = transforms.tenure_days(
        customers, as_of=as_of
    ).values

    return feat_df


def feature_columns() -> list[str]:
    """Return the ordered list of feature columns (excluding customer_id/as_of_date)."""
    return list(FEATURE_NAMES)


def versioned_feature_params() -> dict:
    """Return the per-version parameter values for every versioned feature,
    as declared in the schema — used by build_training_features.py to register
    each version.
    """
    out = {}
    for name in VERSIONED_FEATURES:
        spec = FEATURE_BY_NAME[name]
        out[name] = list(spec.version_values)  # list of (version, value)
    return out
