"""Spot-check evidence: dump the feature-store registry. Run from repo root."""
import pandas as pd
from feature_store import store

pd.set_option("display.max_rows", None)
pd.set_option("display.width", 200)
df = store.list_all_features()
print("=== feature_registry (all versions) ===")
print(df.to_string(index=False))
print("\n--- is_latest per feature ---")
print(
    df[df.is_latest == 1][["feature_name", "version", "parquet_path"]]
    .to_string(index=False)
)
print("\n--- version count per feature ---")
print(df.groupby("feature_name")["version"].max().to_string())
