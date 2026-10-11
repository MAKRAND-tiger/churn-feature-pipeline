"""
Versioned output feature schema: the authoritative list of every feature this
pipeline produces, with dtype, nullability, source(s), and feature-set version.

Generated/maintained from `feature_spec.md`, consumed by `FEATURE_LINEAGE.md`
generation and by the feature-store registration step.

`nullable` is False for every feature once the zero-activity default is
correctly applied — that is the whole point of the explicit defaults in
transforms.py.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class FeatureSpec:
    name: str
    dtype: str
    nullable: bool
    source: str
    feature_set_version: str
    description: str = ""
    default: object = None
    # For features the spec designates as versioned: the tunable parameter name
    # and the list of (version, value) pairs. Empty for single-version features.
    versioned: bool = False
    version_param: str = ""
    version_values: list = field(default_factory=list)


FEATURE_SET_VERSION = "v1.0"

# Candidate features named in feature_spec.md. The two versioned features
# (txn_count_recent, avg_monthly_spend) carry their per-version parameter
# values; the feature store registers one row+parquet per version.
FEATURE_SCHEMA: List[FeatureSpec] = [
    FeatureSpec(
        name="days_since_last_txn",
        dtype="int",
        nullable=False,
        source="data/transactions.db:transactions.txn_timestamp",
        feature_set_version=FEATURE_SET_VERSION,
        description="Days from each customer's last transaction to the as-of date.",
        default=9999,
    ),
    FeatureSpec(
        name="txn_count_recent",
        dtype="int",
        nullable=False,
        source="data/transactions.db:transactions.txn_timestamp",
        feature_set_version=FEATURE_SET_VERSION,
        description="Number of transactions in the trailing window_days days.",
        default=0,
        versioned=True,
        version_param="window_days",
        version_values=[(1, 90), (2, 30), (3, 180)],
    ),
    FeatureSpec(
        name="spend_recent",
        dtype="float",
        nullable=False,
        source="data/transactions.db:transactions.amount,is_returned",
        feature_set_version=FEATURE_SET_VERSION,
        description="Sum of non-returned transaction amount in the trailing window_days days.",
        default=0.0,
    ),
    FeatureSpec(
        name="avg_monthly_spend",
        dtype="float",
        nullable=False,
        source="data/transactions_monthly_agg.parquet:total_amount",
        feature_set_version=FEATURE_SET_VERSION,
        description="Average monthly spend over the trailing window_months calendar months.",
        default=0.0,
        versioned=True,
        version_param="window_months",
        version_values=[(1, 6), (2, 12)],
    ),
    FeatureSpec(
        name="active_months_12m",
        dtype="int",
        nullable=False,
        source="data/transactions_monthly_agg.parquet:txn_month",
        feature_set_version=FEATURE_SET_VERSION,
        description="Count of active months in the trailing 12 calendar months.",
        default=0,
    ),
    FeatureSpec(
        name="return_rate_90d",
        dtype="float",
        nullable=False,
        source="data/transactions.db:transactions.is_returned",
        feature_set_version=FEATURE_SET_VERSION,
        description="Share of transactions that were returns in the trailing 90 days.",
        default=0.0,
    ),
    FeatureSpec(
        name="tenure_days",
        dtype="int",
        nullable=False,
        source="data/customers.csv:signup_date",
        feature_set_version=FEATURE_SET_VERSION,
        description="Days from signup_date to the as-of date.",
        default=0,
    ),
]


# Convenience lookup.
FEATURE_NAMES = [f.name for f in FEATURE_SCHEMA]
FEATURE_BY_NAME = {f.name: f for f in FEATURE_SCHEMA}
VERSIONED_FEATURES = [f.name for f in FEATURE_SCHEMA if f.versioned]
