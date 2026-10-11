#!/usr/bin/env python3
"""
Builds features for the full training population as of a given date, runs the
data-quality checks, writes a versioned parquet feature snapshot, and registers
every candidate feature into the feature store.

For each feature the spec designates as versioned, EVERY version is registered
(not just the latest) — each with its own parameter value, rationale, and
parquet snapshot. Single-version candidate features are registered once at
their default parameter.
"""

import argparse
import json
import sys
from pathlib import Path

# Make the repo root importable when this script is run directly, so
# `from features import ...` resolves regardless of the working directory.
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pandas as pd

from features import build as build_mod
from features import quality_checks
from features.schema import (
    FEATURE_BY_NAME,
    FEATURE_NAMES,
    FEATURE_SET_VERSION,
    VERSIONED_FEATURES,
)
from feature_store import store


def _register_feature(
    feature_name: str,
    values_df: pd.DataFrame,
    parameters: dict,
    rationale: str,
) -> int:
    """Register one version of one feature into the store."""
    spec = FEATURE_BY_NAME[feature_name]
    return store.register_version(
        feature_name=feature_name,
        values_df=values_df[["customer_id", feature_name, "as_of_date"]],
        description=spec.description,
        source_columns=spec.source,
        transform_summary=_transform_summary(feature_name, parameters),
        business_rationale=rationale,
        parameters=parameters,
    )


def _transform_summary(feature_name: str, parameters: dict) -> str:
    """One-line prose summary of the computation, parameterized."""
    summaries = {
        "days_since_last_txn": "as_of - max(txn_timestamp), in days",
        "txn_count_recent": "count(*) over trailing window_days",
        "spend_recent": "sum(amount where is_returned=0) over trailing window_days",
        "avg_monthly_spend": "sum(total_amount over window_months) / window_months",
        "active_months_12m": "count of active customer-months in trailing window_months",
        "return_rate_90d": "sum(is_returned) / count(*) over trailing 90 days",
        "tenure_days": "as_of - signup_date, in days",
    }
    base = summaries.get(feature_name, FEATURE_BY_NAME[feature_name].description)
    if parameters:
        return f"{base}; params={parameters}"
    return base


def _version_rationale(feature_name: str, version: int, value) -> str:
    """Business reason a given version differs from the prior one."""
    if feature_name == "txn_count_recent":
        reasons = {
            1: "Initial 90-day frequency window as the default engagement horizon.",
            2: "Shortened to 30 days after churn-window analysis showed recent disengagement is most predictive within a single month.",
            3: "Widened to 180 days as a stability baseline capturing longer-term habits for comparison against the 30-day signal.",
        }
        return reasons.get(version, f"window_days={value}")
    if feature_name == "avg_monthly_spend":
        reasons = {
            1: "Initial 6-month average monthly spend window.",
            2: "Widened to 12 months to smooth out seasonal spend swings the 6-month window over-weighted.",
        }
        return reasons.get(version, f"window_months={value}")
    return f"version {version}: param={value}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of",
        default="2026-08-01",
        help="As-of date for feature computation (default: 2026-08-01).",
    )
    parser.add_argument(
        "--out",
        default="outputs/features_train.parquet",
        help="Path to write the full feature snapshot parquet.",
    )
    args = parser.parse_args()
    as_of = args.as_of

    print(f"Building training features as of {as_of} ...")
    features = build_mod.build_features(as_of=as_of)

    # Quality checks before writing anything.
    expected_rows = len(features)
    qc = quality_checks.run_all_checks(features, expected_rows=expected_rows)
    print("Quality-check summary:")
    for name in qc["checks"]:
        print(f"  - {name}: {'PASS' if qc[name]['passed'] else 'FAIL'} — {qc[name]['message']}")
    if not qc["passed"]:
        print("Quality checks FAILED — not writing output or registering features.")
        sys.exit(1)

    # Write the full feature snapshot.
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(out_path, index=False)
    print(f"Wrote feature snapshot for {len(features)} customers to {out_path}")

    # Register every candidate feature into the store. Versioned features get
    # EVERY version (each rebuilt with its own parameter value); single-version
    # features are registered once at their default parameter.
    version_params = build_mod.versioned_feature_params()

    for name in FEATURE_NAMES:
        spec = FEATURE_BY_NAME[name]
        if spec.versioned:
            for version, value in version_params[name]:
                ver_features = build_mod.build_features(
                    as_of=as_of, version_overrides={name: value}
                )
                params = {spec.version_param: value, "feature_set_version": FEATURE_SET_VERSION}
                rationale = _version_rationale(name, version, value)
                v = _register_feature(name, ver_features, params, rationale)
                print(
                    f"  registered {name} v{v} ({spec.version_param}={value}) -> "
                    f"feature_store/values/{name}__v{v}.parquet"
                )
        else:
            params = {"feature_set_version": FEATURE_SET_VERSION}
            rationale = f"{spec.description} (default parameters)."
            v = _register_feature(name, features, params, rationale)
            print(
                f"  registered {name} v{v} -> "
                f"feature_store/values/{name}__v{v}.parquet"
            )

    print("\nDone. Feature store populated.")

    # Regenerate lineage docs from the registry now that it is populated.
    try:
        from scripts import generate_lineage
        generate_lineage.main()
    except Exception as e:  # lineage is best-effort after the build succeeds
        print(f"(lineage generation skipped: {e})")


if __name__ == "__main__":
    main()
