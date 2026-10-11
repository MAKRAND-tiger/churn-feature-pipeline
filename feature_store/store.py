"""
Local feature store API: a SQLite metadata/version registry
(`feature_store/registry.db`, table `feature_registry`) plus one parquet
value snapshot per registered version
(`feature_store/values/<feature_name>__v<version>.parquet`).

SQLite + parquet only — no mlflow, feast, or any other feature-store library.

Registry schema (table `feature_registry`):
  feature_name   TEXT    e.g. recent_spend_adjusted_90d
  version        INTEGER starts at 1, increments per feature_name
  created_at     TEXT    ISO-8601
  description    TEXT    human-readable
  source_columns TEXT    e.g. data/transactions.db:transactions.amount,txn_timestamp
  transform_summary TEXT short prose
  business_rationale TEXT why this feature/version exists
  parameters     TEXT    JSON dict of tunable params ({} if none)
  parquet_path   TEXT    relative path to this version's value snapshot
  is_latest      INTEGER 0/1, exactly one row per feature_name is 1
Primary key: (feature_name, version).

All reads resolve the parquet path via the registry — never hardcode a
parquet filename outside this module. A new version always gets a new row and
a new file; `is_latest` is flipped atomically with the new insert. An existing
version's row or file is never overwritten.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REGISTRY_DB = "feature_store/registry.db"
VALUES_DIR = Path("feature_store/values")

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS feature_registry (
    feature_name        TEXT NOT NULL,
    version              INTEGER NOT NULL,
    created_at           TEXT NOT NULL,
    description          TEXT,
    source_columns       TEXT,
    transform_summary    TEXT,
    business_rationale   TEXT,
    parameters           TEXT,
    parquet_path         TEXT NOT NULL,
    is_latest            INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (feature_name, version)
)
"""


def _connect(db_path: str = REGISTRY_DB) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(_CREATE_SQL)
    conn.commit()
    return conn


def _set_latest_to_max(conn, feature_name: str) -> None:
    """Set is_latest=1 on the highest-version row for feature_name and 0 on
    every other row for that feature. Robust to registration order.
    """
    conn.execute(
        "UPDATE feature_registry SET is_latest=0 WHERE feature_name=?",
        (feature_name,),
    )
    conn.execute(
        """UPDATE feature_registry SET is_latest=1
           WHERE feature_name=? AND version=(
               SELECT MAX(version) FROM feature_registry WHERE feature_name=?
           )""",
        (feature_name, feature_name),
    )


def register_version(
    feature_name: str,
    values_df: pd.DataFrame,
    description: str,
    source_columns: str,
    transform_summary: str,
    business_rationale: str,
    parameters: dict,
    db_path: str = REGISTRY_DB,
) -> int:
    """Write a parquet snapshot, upsert the registry row, set is_latest, and
    return the version number.

    Idempotent by parameters: if a version of this feature with an identical
    `parameters` dict is already registered, its version number is reused and
    its snapshot/metadata is refreshed in place (same version, same file) —
    re-running the build does NOT append duplicate versions. A genuinely new
    parameterisation gets a new version number (MAX+1) and a new file; an
    existing version's file is never clobbered by a different version.
    """
    VALUES_DIR.mkdir(parents=True, exist_ok=True)
    params_json = json.dumps(parameters, sort_keys=True)
    conn = _connect(db_path)
    try:
        cur = conn.cursor()

        # Idempotency: same feature + same parameters => same logical version.
        cur.execute(
            "SELECT version, parquet_path FROM feature_registry "
            "WHERE feature_name=? AND parameters=? "
            "ORDER BY version DESC LIMIT 1",
            (feature_name, params_json),
        )
        existing = cur.fetchone()

        conn.execute("BEGIN")
        if existing is not None:
            # Same logical version: refresh its snapshot in place and update its
            # metadata row in place (no new version, no new file).
            version, parquet_path = existing
            values_df.to_parquet(parquet_path, index=False)
            conn.execute(
                """UPDATE feature_registry SET created_at=?, description=?,
                   source_columns=?, transform_summary=?, business_rationale=?,
                   parameters=?, parquet_path=?
                   WHERE feature_name=? AND version=?""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    description,
                    source_columns,
                    transform_summary,
                    business_rationale,
                    params_json,
                    parquet_path,
                    feature_name,
                    version,
                ),
            )
            _set_latest_to_max(conn, feature_name)
            conn.commit()
            return version

        # Genuinely new parameterisation: next version number for this feature.
        cur.execute(
            "SELECT COALESCE(MAX(version), 0) FROM feature_registry WHERE feature_name=?",
            (feature_name,),
        )
        next_version = cur.fetchone()[0] + 1

        parquet_path = str(VALUES_DIR / f"{feature_name}__v{next_version}.parquet")
        if Path(parquet_path).exists():
            raise FileExistsError(
                f"Refusing to overwrite existing version snapshot {parquet_path} — "
                f"a new version must get a new file."
            )

        # Write the value snapshot (customer_id, feature value, as_of_date).
        values_df.to_parquet(parquet_path, index=False)

        conn.execute(
            """INSERT INTO feature_registry
            (feature_name, version, created_at, description, source_columns,
             transform_summary, business_rationale, parameters, parquet_path, is_latest)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                feature_name,
                next_version,
                datetime.now(timezone.utc).isoformat(),
                description,
                source_columns,
                transform_summary,
                business_rationale,
                params_json,
                parquet_path,
            ),
        )
        _set_latest_to_max(conn, feature_name)
        conn.commit()
        return next_version
    finally:
        conn.close()


def _resolve_parquet_path(feature_name: str, version: int | None, db_path: str) -> str:
    conn = _connect(db_path)
    try:
        if version is None:
            row = conn.execute(
                "SELECT parquet_path FROM feature_registry WHERE feature_name=? AND is_latest=1",
                (feature_name,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT parquet_path FROM feature_registry WHERE feature_name=? AND version=?",
                (feature_name, version),
            ).fetchone()
        if row is None:
            if version is None:
                raise KeyError(f"No registered version for feature {feature_name!r}")
            raise KeyError(f"No version {version} for feature {feature_name!r}")
        return row[0]
    finally:
        conn.close()


def get_latest(feature_name: str, db_path: str = REGISTRY_DB) -> pd.DataFrame:
    """Return the DataFrame for the version currently flagged is_latest = 1."""
    path = _resolve_parquet_path(feature_name, None, db_path)
    return pd.read_parquet(path)


def get_version(feature_name: str, version: int, db_path: str = REGISTRY_DB) -> pd.DataFrame:
    """Return the DataFrame for a specific (feature_name, version)."""
    path = _resolve_parquet_path(feature_name, version, db_path)
    return pd.read_parquet(path)


def list_versions(feature_name: str, db_path: str = REGISTRY_DB) -> pd.DataFrame:
    """Return every registered version's metadata row for feature_name, most
    recent first (version descending).
    """
    conn = _connect(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT * FROM feature_registry WHERE feature_name=? ORDER BY version DESC",
            conn,
            params=(feature_name,),
        )
        return df
    finally:
        conn.close()


def list_all_features(db_path: str = REGISTRY_DB) -> pd.DataFrame:
    """Return registry rows for every feature (all versions), useful for
    generating FEATURE_LINEAGE.md.
    """
    conn = _connect(db_path)
    try:
        return pd.read_sql_query(
            "SELECT * FROM feature_registry ORDER BY feature_name, version DESC",
            conn,
        )
    finally:
        conn.close()
