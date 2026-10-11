#!/usr/bin/env python3
"""
Generate FEATURE_LINEAGE.md from `features/schema.py`, `feature_store/registry.db`,
and the spec — for every feature, across every stored version. This file is
regeneratable from code + the registry (run this script), not hand-maintained
prose that can drift from the implementation.

For the spec-defined versioning exercise specifically, every registered
version of every versioned feature appears as its own distinct entry with
its own rationale and parquet path — not collapsed into one entry showing
only the latest.
"""

import json
import sys
from pathlib import Path

# Make the repo root importable when this script is run directly.
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pandas as pd

from features.schema import FEATURE_BY_NAME, FEATURE_SCHEMA, VERSIONED_FEATURES
from feature_store import store

OUT_PATH = "outputs/artifacts/FEATURE_LINEAGE.md"


def _row_md(meta_row, spec) -> list[str]:
    params = json.loads(meta_row["parameters"]) if meta_row["parameters"] else {}
    return [
        f"#### {meta_row['feature_name']} v{meta_row['version']}",
        "",
        f"- **Description**: {meta_row['description']}",
        f"- **Source**: {meta_row['source_columns']}",
        f"- **Transform**: {meta_row['transform_summary']}",
        f"- **Business rationale**: {meta_row['business_rationale']}",
        f"- **Parameters**: `{params}`",
        f"- **Feature-store location**: table `feature_registry` row "
        f"(`feature_name`={meta_row['feature_name']!r}, `version`={meta_row['version']}), "
        f"`parquet_path`=`{meta_row['parquet_path']}`, `is_latest`={int(meta_row['is_latest'])}",
        "",
    ]


def main() -> None:
    all_rows = store.list_all_features()
    sections = [
        "# FEATURE_LINEAGE.md",
        "",
        "Auto-generated from `features/schema.py`, `feature_store/registry.db`, and the "
        "spec — regenerate with `python scripts/generate_lineage.py`. Every feature, across "
        "every stored version, is documented as its own entry (versioned features are NOT "
        "collapsed into a single latest-only entry).",
        "",
    ]

    # Group rows by feature name, ordered by the schema order; versions ascending.
    by_name = {name: [] for name in [f.name for f in FEATURE_SCHEMA]}
    for _, r in all_rows.iterrows():
        by_name.setdefault(r["feature_name"], []).append(r)
    for name in by_name:
        by_name[name].sort(key=lambda r: int(r["version"]))

    for spec in FEATURE_SCHEMA:
        name = spec.name
        sections.append(f"## {name}")
        sections.append("")
        is_versioned = name in VERSIONED_FEATURES
        sections.append(
            f"_Versioned: {'yes' if is_versioned else 'no'}_  |  "
            f"_dtype: {spec.dtype}_  |  _nullable: {spec.nullable}_  |  "
            f"_default: `{spec.default}`_"
        )
        sections.append("")
        rows = by_name.get(name, [])
        if not rows:
            sections.append(f"_No registered version found for `{name}` — run "
                            f"`scripts/build_training_features.py` first._")
            sections.append("")
            continue
        for r in rows:
            sections.extend(_row_md(r, spec))

    out = Path(OUT_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(sections), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
