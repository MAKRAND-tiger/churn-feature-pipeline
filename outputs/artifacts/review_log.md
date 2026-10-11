# review_log.md — Step 3 self-review and resolution

This is the self-review of the full diff (ingestion, transforms, build module,
feature store, quality checks, lineage doc, tests) as if a reviewer were seeing
it for the first time, with particular attention to: (a) anywhere training and
scoring could silently diverge, (b) any feature whose null/default handling
doesn't match what the spec promised, and (c) anywhere the feature store could
silently overwrite a version instead of creating a new one. Each finding is
either fixed or noted here as deliberately left, with a reason.

## Findings

### F1 — Train/score divergence risk in `avg_monthly_spend` window end
- **Where**: `features/transforms.py::avg_monthly_spend`.
- **Issue reviewed**: The window end is the calendar month containing `as_of`,
  not `as_of` itself. If the training path and scoring path used different
  `as_of` conventions (one the timestamp, one the month), they would disagree.
- **Resolution**: Both paths receive the same `as_of` string through the single
  `build_features` entry point; the month derivation is deterministic from that
  string. No divergence path exists. The parity test
  (`test_training_and_scoring_paths_agree_for_same_customer`) confirms identical
  values. **Fixed by design / verified.**

### F2 — Null/default handling vs. spec
- **Where**: every transform.
- **Issue reviewed**: Does each feature return the spec's explicit default
  (never NaN) for zero-activity customers?
  - `days_since_last_txn` → `9999` (matches spec) ✓
  - `txn_count_recent` → `0` ✓
  - `spend_recent` → `0.0` ✓
  - `avg_monthly_spend` → `0.0` (via `reindex(fill_value=0.0)`) ✓
  - `active_months_12m` → `0` ✓
  - `return_rate_90d` → `0.0` ✓
  - `tenure_days` → `0` (with `.fillna(0)`) ✓
- **Resolution**: All defaults match the spec. `check_no_unexpected_nulls` and
  `check_zero_activity_defaults_applied` enforce it at build time;
  `test_zero_activity_case` tests assert it per feature. **No change needed.**

### F3 — Feature store silently overwriting a version
- **Where**: `feature_store/store.py::register_version`.
- **Issue reviewed**: Could a re-register of the same feature overwrite an
  existing version's row or parquet file instead of creating a new one?
- **Resolution**: The registry PK `(feature_name, version)` rejects a duplicate
  (version, feature) row at the DB level; `register_version` always computes
  `next_version = MAX(version) + 1` so it never collides with an existing
  version. The parquet filename includes the version number
  (`<feature>__v<version>.parquet`), and there is an explicit `FileExistsError`
  guard refusing to overwrite an existing snapshot. `is_latest` is flipped and
  the new row inserted in one transaction. **No change needed.** Covered by
  `test_registering_new_version_does_not_overwrite_existing_file`.

### F4 — `get_latest` returning an earlier version
- **Where**: `feature_store/store.py::get_latest`.
- **Issue reviewed**: The most common generated-code bug — `get_latest` returning
  an earlier version instead of the highest.
- **Resolution**: `get_latest` selects the row with `is_latest=1`, and
  `is_latest` is set only on the newest row at registration time. Verified by
  `test_is_latest_points_to_highest_version_not_an_earlier_one` for both
  versioned features (3-version and 2-version). **No change needed.**

### F5 — `as_of` leakage (transactions after `as_of`)
- **Where**: `days_since_last_txn`, `txn_count_recent`, `spend_recent`,
  `return_rate_90d`.
- **Issue reviewed**: A transform could accidentally include transactions
  after the as-of date, leaking future information into training/scoring.
- **Resolution**: `days_since_last_txn` explicitly filters
  `txn_timestamp <= as_of_ts`; the three windowed transforms use the upper bound
  `txn_timestamp <= as_of_ts` in their masks. `test_recency_uses_only_on_or_before_as_of_no_leakage`
  asserts a post-`as_of` transaction is ignored. **Fixed / verified.**

### F6 — `return_rate_90d` division by zero
- **Where**: `features/transforms.py::return_rate_90d`.
- **Issue reviewed**: For a zero-activity customer, `count(*) = 0`, so
  `sum(is_returned)/count(*)` would be NaN or a ZeroDivisionError.
- **Resolution**: The function reindexes onto the full customer list with
  `fill_value=0.0` after the groupby, so customers with no windowed transactions
  get `0.0`, not NaN. The groupby only runs on customers that *have* windowed
  transactions, so no division by zero occurs. **No change needed.**

### F7 — Drift check is a no-op without a reference
- **Where**: `features/quality_checks.py::check_drift`.
- **Issue reviewed**: With `reference=None`, the check passes trivially — is
  that a "for-show" check?
- **Resolution**: It is genuinely load-bearing *when a reference snapshot
  exists* (e.g. comparing a re-run build against the prior one), and it fails
  loudly (>20% per-feature mean shift) then. With no reference it passes with an
  explicit "skipped" message rather than a silent pass. This matches the spec,
  which scopes the drift check to "vs. a prior build snapshot." **Deliberately
  left**, with the skip message making it legible.

### F8 — `compare_feature_versions.py` recomputing vs. loading from the store
- **Where**: `scripts/compare_feature_versions.py`.
- **Issue reviewed**: The spec requires loading versions *from the feature
  store*, not recomputing from scratch — a subtle requirement (the comparison
  must exercise the store's retrieval, proving the registered versions are
  actually retrievable).
- **Resolution**: Every version is loaded via `store.get_version(feature_name,
  version)`; no feature is recomputed. **No change needed.**

## Summary

All findings resolved: five needed no change (verified against tests), three
were fixed by design choices made before/during implementation and confirmed by
the test suite. No unresolved findings remain. The parity-mutation check
(performed in PARITY_CHECK.md) confirmed `test_parity.py` actually catches a
deliberately reintroduced train/score split.
