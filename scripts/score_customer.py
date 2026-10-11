#!/usr/bin/env python3
"""
Builds features for one or more specific customer_ids as of a given date, using
the scoring path of the SAME shared build_features(as_of, ...) entry point used
by build_training_features.py.

The train/score parity guarantee depends on there being exactly one code path:
this script passes `customer_ids` to build_features, which is the ONLY allowed
difference between training and scoring. No feature logic is duplicated here.
"""

import argparse
import sys
from pathlib import Path

# Make the repo root importable when this script is run directly.
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pandas as pd

from features import build as build_mod
from features.schema import FEATURE_NAMES


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--customer-id",
        type=int,
        action="append",
        required=True,
        help="Customer ID to score. May be passed multiple times.",
    )
    parser.add_argument(
        "--as-of",
        default="2026-08-01",
        help="As-of date for feature computation (default: 2026-08-01).",
    )
    args = parser.parse_args()
    customer_ids = list(dict.fromkeys(args.customer_id))  # dedupe, preserve order

    # Scoring path: build_features with an explicit customer_ids list. This is
    # the ONLY difference from the training path — the same code, same as_of
    # threading, same transforms.
    try:
        features = build_mod.build_features(
            as_of=args.as_of, customer_ids=customer_ids
        )
    except ValueError as e:
        # A nonexistent customer_id -> clear error, not a silent empty result.
        print(f"ERROR: {e}", flush=True)
        raise SystemExit(1)

    print(f"Scoring {len(features)} customer(s) as of {args.as_of}:\n")
    cols = ["customer_id", "as_of_date"] + FEATURE_NAMES
    print(features[cols].to_string(index=False))


if __name__ == "__main__":
    main()
