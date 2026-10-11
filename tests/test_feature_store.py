"""
For each feature the confirmed feature_spec.md designates as versioned,
register its versions, confirm each is independently retrievable by version
number, confirm is_latest correctly identifies the highest version (not an
earlier one), and confirm list_versions returns every version with distinct
parquet_path values that all actually exist on disk.

Uses a throwaway registry DB so the test is hermetic and does not touch the
real feature_store/registry.db.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from feature_store import store
from features.schema import FEATURE_BY_NAME, VERSIONED_FEATURES


@pytest.fixture()
def tmp_db(tmp_path):
    return str(tmp_path / "registry.db")


def _register(feature_name, version, n_customers, tmp_db, value=None):
    """Register a synthetic version with a deterministic value."""
    df = pd.DataFrame({
        "customer_id": range(n_customers),
        feature_name: [float(version * 10 + i) for i in range(n_customers)],
        "as_of_date": pd.Timestamp("2026-08-01"),
    })
    spec = FEATURE_BY_NAME[feature_name]
    # Override VALUES_DIR to live under tmp_path so we don't pollute the repo.
    store.VALUES_DIR = Path(tmp_db).parent / "values"
    store.VALUES_DIR.mkdir(parents=True, exist_ok=True)
    params = {spec.version_param: value if value is not None else version}
    return store.register_version(
        feature_name=feature_name,
        values_df=df,
        description=spec.description,
        source_columns=spec.source,
        transform_summary=f"synthetic v{version}",
        business_rationale=f"test version {version}",
        parameters=params,
        db_path=tmp_db,
    )


def _reset_values_dir():
    store.VALUES_DIR = Path("feature_store/values")


def test_register_and_retrieve_all_versions_of_a_versioned_feature(tmp_db):
    """Every registered version of a versioned feature is independently
    retrievable by version number and returns distinct values."""
    try:
        for name in VERSIONED_FEATURES:
            spec = FEATURE_BY_NAME[name]
            registered = []
            for version, value in spec.version_values:
                v = _register(name, version, n_customers=5, tmp_db=tmp_db, value=value)
                registered.append(v)
            # Every version independently retrievable.
            for v in registered:
                df = store.get_version(name, v, db_path=tmp_db)
                assert len(df) == 5
                assert name in df.columns
                assert "customer_id" in df.columns
            # Distinct versions have distinct value sets.
            vals = [store.get_version(name, v, db_path=tmp_db)[name].tolist() for v in registered]
            for i in range(len(vals) - 1):
                assert vals[i] != vals[i + 1], f"versions of {name} returned identical values"
    finally:
        _reset_values_dir()


def test_is_latest_points_to_highest_version_not_an_earlier_one(tmp_db):
    """get_latest must return the HIGHEST registered version, not an earlier
    one — the most common bug in generated feature-store code."""
    try:
        for name in VERSIONED_FEATURES:
            spec = FEATURE_BY_NAME[name]
            for version, value in spec.version_values:
                _register(name, version, n_customers=4, tmp_db=tmp_db, value=value)
            highest = max(v for v, _ in spec.version_values)
            latest_df = store.get_latest(name, db_path=tmp_db)
            # The latest version's synthetic values are version*10 + i.
            assert latest_df[name].iloc[0] == float(highest * 10 + 0)
            # And is_latest is set on exactly the highest row.
            meta = store.list_versions(name, db_path=tmp_db)
            latest_rows = meta[meta["is_latest"] == 1]
            assert len(latest_rows) == 1
            assert int(latest_rows.iloc[0]["version"]) == highest
    finally:
        _reset_values_dir()


def test_list_versions_returns_distinct_parquet_paths_that_exist(tmp_db):
    """list_versions returns every version, each with a distinct parquet_path
    that actually exists on disk."""
    try:
        for name in VERSIONED_FEATURES:
            spec = FEATURE_BY_NAME[name]
            for version, value in spec.version_values:
                _register(name, version, n_customers=3, tmp_db=tmp_db, value=value)
            meta = store.list_versions(name, db_path=tmp_db)
            assert len(meta) == len(spec.version_values)
            paths = meta["parquet_path"].tolist()
            assert len(set(paths)) == len(paths), f"{name} has duplicate parquet paths"
            for p in paths:
                assert Path(p).exists(), f"parquet path {p} does not exist on disk"
            # Versions descending.
            assert meta["version"].tolist() == sorted(meta["version"].tolist(), reverse=True)
    finally:
        _reset_values_dir()


def test_registering_new_version_does_not_overwrite_existing_file(tmp_db):
    """A new version always gets a NEW file; an existing version's file is
    never overwritten (registry PK + distinct parquet_path)."""
    try:
        name = VERSIONED_FEATURES[0]
        spec = FEATURE_BY_NAME[name]
        v1 = _register(name, 1, n_customers=3, tmp_db=tmp_db, value=spec.version_values[0][1])
        df_v1 = store.get_version(name, v1, db_path=tmp_db).copy()
        v2 = _register(name, 2, n_customers=3, tmp_db=tmp_db, value=spec.version_values[1][1])
        # v1's snapshot must be unchanged on disk.
        df_v1_again = store.get_version(name, v1, db_path=tmp_db)
        assert df_v1[name].tolist() == df_v1_again[name].tolist()
        assert v2 != v1
    finally:
        _reset_values_dir()


def test_parameters_are_json_round_tripped(tmp_db):
    try:
        name = VERSIONED_FEATURES[0]
        spec = FEATURE_BY_NAME[name]
        v = _register(name, 1, n_customers=2, tmp_db=tmp_db, value=spec.version_values[0][1])
        meta = store.list_versions(name, db_path=tmp_db)
        params = json.loads(meta.iloc[0]["parameters"])
        assert params[spec.version_param] == spec.version_values[0][1]
    finally:
        _reset_values_dir()


def test_re_registering_same_parameters_is_idempotent(tmp_db):
    """Re-registering a feature with identical parameters must NOT append a
    new version — it reuses the existing version number and refreshes its
    snapshot in place. Re-running the build is a no-op on the registry's
    version count (otherwise every build run would duplicate every version).
    """
    try:
        name = VERSIONED_FEATURES[0]
        spec = FEATURE_BY_NAME[name]
        value = spec.version_values[0][1]
        v1 = _register(name, 1, n_customers=3, tmp_db=tmp_db, value=value)
        v2 = _register(name, 1, n_customers=3, tmp_db=tmp_db, value=value)  # same params
        assert v2 == v1, "same parameters must reuse the version number"
        meta = store.list_versions(name, db_path=tmp_db)
        assert len(meta) == 1, "no duplicate version row for identical parameters"
        # The refreshed snapshot is still readable and non-empty.
        df = store.get_version(name, v1, db_path=tmp_db)
        assert len(df) == 3
    finally:
        _reset_values_dir()


def test_re_registering_then_adding_new_version_keeps_highest_latest(tmp_db):
    """After an idempotent re-registration, registering a genuinely new
    parameterisation still advances the version and points is_latest at the
    new highest version."""
    try:
        name = VERSIONED_FEATURES[0]
        spec = FEATURE_BY_NAME[name]
        # v1 with param value 0.
        _register(name, 1, n_customers=2, tmp_db=tmp_db, value=spec.version_values[0][1])
        # idempotent re-register of v1.
        _register(name, 1, n_customers=2, tmp_db=tmp_db, value=spec.version_values[0][1])
        # genuinely new param -> v2.
        v_new = _register(name, 2, n_customers=2, tmp_db=tmp_db, value=spec.version_values[1][1])
        assert v_new == 2
        meta = store.list_versions(name, db_path=tmp_db)
        assert len(meta) == 2
        latest = meta[meta["is_latest"] == 1]
        assert len(latest) == 1
        assert int(latest.iloc[0]["version"]) == 2
    finally:
        _reset_values_dir()
