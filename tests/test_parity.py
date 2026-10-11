"""
The parity test that matters most for this pipeline: build features for the
same customer via the "training" path (historical as-of date, batch of many
customers) and via the "scoring" path (single customer_id, same as-of date),
and assert the resulting feature values are identical.

If these two paths can't be driven through the same test with the same expected
output, the parity guarantee in feature_spec.md isn't real — fix features/build.py,
not this test.
"""

import pandas as pd

from features import build as build_mod
from features.schema import FEATURE_NAMES

AS_OF = "2026-08-01"


def _values_for_customer(df: pd.DataFrame, customer_id: int) -> dict:
    row = df[df["customer_id"] == customer_id].iloc[0]
    return {c: row[c] for c in FEATURE_NAMES}


def test_training_and_scoring_paths_agree_for_same_customer():
    """Build the full training feature set (batch) and the single-customer
    scoring set at the same as-of date, then assert every feature value matches
    exactly for a customer sampled from the middle of the customer base.
    """
    # Training path: full customer base (no customer_ids).
    train = build_mod.build_features(as_of=AS_OF)

    # Pick a real customer from the middle of the base to test on.
    customer_id = int(train["customer_id"].iloc[len(train) // 2])

    # Scoring path: the same build_features, only differing by customer_ids.
    score = build_mod.build_features(as_of=AS_OF, customer_ids=[customer_id])

    train_vals = _values_for_customer(train, customer_id)
    score_vals = _values_for_customer(score, customer_id)

    assert set(train_vals.keys()) == set(score_vals.keys()) == set(FEATURE_NAMES)
    for name in FEATURE_NAMES:
        tv, sv = train_vals[name], score_vals[name]
        # Exact equality for ints; close for floats (they come from the same
        # code path so should be bit-identical, but use a tight tolerance to
        # avoid float-formatting noise).
        if isinstance(tv, float) or isinstance(sv, float):
            assert tv == sv, f"{name}: train={tv!r} != score={sv!r}"
        else:
            assert tv == sv, f"{name}: train={tv!r} != score={sv!r}"


def test_training_and_scoring_agree_for_a_zero_activity_customer():
    """Parity must also hold for a customer with zero transactions — the
    zero-activity default must be identical on both paths (a common divergence
    point where a reindex bug leaves NaN on one path but not the other).
    """
    train = build_mod.build_features(as_of=AS_OF)
    # Find a customer that has zero activity (days_since_last_txn == sentinel).
    zero_custs = train[train["days_since_last_txn"] == 9999]["customer_id"]
    assert len(zero_custs) > 0, "expected at least one zero-activity customer in the data"
    customer_id = int(zero_custs.iloc[0])

    score = build_mod.build_features(as_of=AS_OF, customer_ids=[customer_id])
    train_vals = _values_for_customer(train, customer_id)
    score_vals = _values_for_customer(score, customer_id)
    for name in FEATURE_NAMES:
        assert train_vals[name] == score_vals[name], (
            f"parity broken for zero-activity customer on {name}: "
            f"train={train_vals[name]!r} != score={score_vals[name]!r}"
        )


def test_scoring_multiple_customers_matches_training_for_those_ids():
    """Scoring a batch of customer_ids must reproduce the training-path values
    for every one of them (parity holds for a subset, not just a single id).
    """
    train = build_mod.build_features(as_of=AS_OF)
    sample_ids = train["customer_id"].iloc[[0, len(train) // 4, len(train) // 2, -1]].astype(int).tolist()
    score = build_mod.build_features(as_of=AS_OF, customer_ids=sample_ids)

    # Same set of customers, same order-ish; compare by customer_id.
    score_by_id = score.set_index("customer_id")
    for cid in sample_ids:
        for name in FEATURE_NAMES:
            assert train.set_index("customer_id").loc[cid, name] == score_by_id.loc[cid, name], (
                f"parity broken for customer {cid} on {name}"
            )
