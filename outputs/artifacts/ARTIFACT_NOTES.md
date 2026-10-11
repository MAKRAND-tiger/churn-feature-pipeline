# ARTIFACT_NOTES.md — self-critique log

This is the honest record of things I got wrong, reconsidered, or had to look
twice at across transforms / build / store / checks. It is not a rubric of
praise — it lists real issues and how they were resolved, and explicitly flags
anything still open.

## Things I got wrong or reconsidered

1. **The monthly aggregate's spend column is `total_amount`, not `monthly_spend`.**
   The example in the starter `feature_spec.md` skeleton referenced a
   `monthly_spend`-style name, and my first draft of `transforms.avg_monthly_spend`
   assumed the aggregate exposed a column by that name. Reading the parquet's
   footer schema showed the real columns are `customer_id`, `txn_month`,
   `txn_count`, `total_amount`, `return_count`. I corrected the transform and
   the spec to use `total_amount`. (If I had not caught this, `avg_monthly_spend`
   would have raised `KeyError` at build time — a loud failure, not a silent one,
   but still a real mistake.)

2. **Returned-amount sign convention — confirmed positive-flagged.**
   On first inspection I could not confirm from the SQLite schema alone whether
   returned transactions store `amount` as positive (flagged by `is_returned=1`)
   or negative (refund). After running the inspection, the returned-amount
   distribution is positive (min 3.0, max 439.76, same sign as non-returned), so
   returns are positive-flagged and `total_amount` in the aggregate INCLUDES
   returned amounts as positive. I defined `spend_recent` to sum only
   non-returned transactions (`is_returned=0`), which is correct under this
   convention and is stated explicitly in `feature_spec.md`.

3. **Zero-activity default for recency: chose `9999` over `NaN` / `-1`.**
   My first instinct was to leave never-active customers at `NaN` for
   `days_since_last_txn`, on the theory that "missing" is the honest value. The
   spec's Domain Context is explicit that zero-activity defaults must never be
   bare null/NaN, and that `as_of`-threaded transforms must produce a real value
   for every customer. I switched to a finite sentinel `9999` (large enough to
   sort to the "most at-risk" end of the distribution, finite so it scales in a
   model). `transforms.NEVER_TRANSACTED_RECENCY` is the named constant; the
   quality check `check_zero_activity_defaults_applied` asserts it is applied
   and never NaN.

4. **`as_of` was initially going to be a module-level default.**
   An early sketch defaulted `as_of` inside the transform signatures
   (`as_of: str = "2026-08-01"`). That would have made the parity guarantee a
   lie — the same function called with no `as_of` from two places would silently
   agree only because both used the same default, and a scoring call that forgot
   to pass `as_of` would compute against the wrong date with no error. I removed
   the default from every transform and made `as_of` a required parameter;
   the default lives only in the CLI scripts, never inside a transform.

5. **`get_latest` correctness — verified it returns the HIGHEST version.**
   The skill flags this as the most common gap in generated feature-store code.
   `register_version` flips `is_latest` to 0 on the prior latest row and sets
   the new row to 1 in the same transaction, and `get_latest` selects the row
   with `is_latest=1`. `test_is_latest_points_to_highest_version_not_an_earlier_one`
   asserts this on the versioned features (3 versions of `txn_count_recent`,
   2 of `avg_monthly_spend`), confirming `get_latest` returns v3 / v2
   respectively, not an earlier one.

6. **Window boundary convention `(as_of - W, as_of]`.**
   I had to pick an inclusive/exclusive convention for the day-windows and make
   it consistent across `txn_count_recent`, `spend_recent`, and `return_rate_90d`.
   I chose `(as_of - window_days, as_of]`: a transaction exactly `window_days`
   before `as_of` is OUTSIDE the window, a transaction exactly at `as_of` is
   INSIDE. `test_txn_count_time_window_boundary_inclusive_of_as_of` and
   `test_spend_time_window_boundary` assert this. This matters for the parity
   test: training and scoring must agree on which edge is in the window, or the
   same transaction would be counted on one path and not the other.

7. **`avg_monthly_spend` window end vs. `as_of` month.**
   I initially wrote the monthly window as ending at `as_of` (the timestamp),
   then realized the aggregate is month-grained, so the natural end is the
   *calendar month containing `as_of`*. I changed it to
   `[as_of_month - (window_months - 1), as_of_month]` and added
   `test_avg_monthly_spend_excludes_future_months` to assert a month strictly
   after the as-of month is excluded.

## Data defects found

No raw source file was modified. If a genuine data defect had been found, it
would be noted here rather than silently patched. The one structural property
worth recording (not a defect, a real feature of the data): the monthly
aggregate is **sparse** (zero-activity customer-months have no row), which
`active_months_12m` relies on by construction.

## Verification status

- All four test files are implemented (not skipped): `test_transforms.py`,
  `test_parity.py`, `test_quality_checks.py`, `test_feature_store.py`.
- `test_parity.py` covers single-customer, zero-activity-customer, and
  multi-customer-batch parity against the training path.
- The parity-mutation check (PARITY_CHECK.md) was performed by deliberately
  reintroducing a train/score split and confirming `test_parity.py` caught it.
- See `review_log.md` for the Step 3 self-review.
