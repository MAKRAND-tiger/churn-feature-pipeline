# FEATURE_LINEAGE.md

Auto-generated from `features/schema.py`, `feature_store/registry.db`, and the spec — regenerate with `python scripts/generate_lineage.py`. Every feature, across every stored version, is documented as its own entry (versioned features are NOT collapsed into a single latest-only entry).

## days_since_last_txn

_Versioned: no_  |  _dtype: int_  |  _nullable: False_  |  _default: `9999`_

#### days_since_last_txn v1

- **Description**: Days from each customer's last transaction to the as-of date.
- **Source**: data/transactions.db:transactions.txn_timestamp
- **Transform**: as_of - max(txn_timestamp), in days; params={'feature_set_version': 'v1.0'}
- **Business rationale**: Days from each customer's last transaction to the as-of date. (default parameters).
- **Parameters**: `{'feature_set_version': 'v1.0'}`
- **Feature-store location**: table `feature_registry` row (`feature_name`='days_since_last_txn', `version`=1), `parquet_path`=`feature_store\values\days_since_last_txn__v1.parquet`, `is_latest`=1

## txn_count_recent

_Versioned: yes_  |  _dtype: int_  |  _nullable: False_  |  _default: `0`_

#### txn_count_recent v1

- **Description**: Number of transactions in the trailing window_days days.
- **Source**: data/transactions.db:transactions.txn_timestamp
- **Transform**: count(*) over trailing window_days; params={'window_days': 90, 'feature_set_version': 'v1.0'}
- **Business rationale**: Initial 90-day frequency window as the default engagement horizon.
- **Parameters**: `{'feature_set_version': 'v1.0', 'window_days': 90}`
- **Feature-store location**: table `feature_registry` row (`feature_name`='txn_count_recent', `version`=1), `parquet_path`=`feature_store\values\txn_count_recent__v1.parquet`, `is_latest`=0

#### txn_count_recent v2

- **Description**: Number of transactions in the trailing window_days days.
- **Source**: data/transactions.db:transactions.txn_timestamp
- **Transform**: count(*) over trailing window_days; params={'window_days': 30, 'feature_set_version': 'v1.0'}
- **Business rationale**: Shortened to 30 days after churn-window analysis showed recent disengagement is most predictive within a single month.
- **Parameters**: `{'feature_set_version': 'v1.0', 'window_days': 30}`
- **Feature-store location**: table `feature_registry` row (`feature_name`='txn_count_recent', `version`=2), `parquet_path`=`feature_store\values\txn_count_recent__v2.parquet`, `is_latest`=0

#### txn_count_recent v3

- **Description**: Number of transactions in the trailing window_days days.
- **Source**: data/transactions.db:transactions.txn_timestamp
- **Transform**: count(*) over trailing window_days; params={'window_days': 180, 'feature_set_version': 'v1.0'}
- **Business rationale**: Widened to 180 days as a stability baseline capturing longer-term habits for comparison against the 30-day signal.
- **Parameters**: `{'feature_set_version': 'v1.0', 'window_days': 180}`
- **Feature-store location**: table `feature_registry` row (`feature_name`='txn_count_recent', `version`=3), `parquet_path`=`feature_store\values\txn_count_recent__v3.parquet`, `is_latest`=1

## spend_recent

_Versioned: no_  |  _dtype: float_  |  _nullable: False_  |  _default: `0.0`_

#### spend_recent v1

- **Description**: Sum of non-returned transaction amount in the trailing window_days days.
- **Source**: data/transactions.db:transactions.amount,is_returned
- **Transform**: sum(amount where is_returned=0) over trailing window_days; params={'feature_set_version': 'v1.0'}
- **Business rationale**: Sum of non-returned transaction amount in the trailing window_days days. (default parameters).
- **Parameters**: `{'feature_set_version': 'v1.0'}`
- **Feature-store location**: table `feature_registry` row (`feature_name`='spend_recent', `version`=1), `parquet_path`=`feature_store\values\spend_recent__v1.parquet`, `is_latest`=1

## avg_monthly_spend

_Versioned: yes_  |  _dtype: float_  |  _nullable: False_  |  _default: `0.0`_

#### avg_monthly_spend v1

- **Description**: Average monthly spend over the trailing window_months calendar months.
- **Source**: data/transactions_monthly_agg.parquet:total_amount
- **Transform**: sum(total_amount over window_months) / window_months; params={'window_months': 6, 'feature_set_version': 'v1.0'}
- **Business rationale**: Initial 6-month average monthly spend window.
- **Parameters**: `{'feature_set_version': 'v1.0', 'window_months': 6}`
- **Feature-store location**: table `feature_registry` row (`feature_name`='avg_monthly_spend', `version`=1), `parquet_path`=`feature_store\values\avg_monthly_spend__v1.parquet`, `is_latest`=0

#### avg_monthly_spend v2

- **Description**: Average monthly spend over the trailing window_months calendar months.
- **Source**: data/transactions_monthly_agg.parquet:total_amount
- **Transform**: sum(total_amount over window_months) / window_months; params={'window_months': 12, 'feature_set_version': 'v1.0'}
- **Business rationale**: Widened to 12 months to smooth out seasonal spend swings the 6-month window over-weighted.
- **Parameters**: `{'feature_set_version': 'v1.0', 'window_months': 12}`
- **Feature-store location**: table `feature_registry` row (`feature_name`='avg_monthly_spend', `version`=2), `parquet_path`=`feature_store\values\avg_monthly_spend__v2.parquet`, `is_latest`=1

## active_months_12m

_Versioned: no_  |  _dtype: int_  |  _nullable: False_  |  _default: `0`_

#### active_months_12m v1

- **Description**: Count of active months in the trailing 12 calendar months.
- **Source**: data/transactions_monthly_agg.parquet:txn_month
- **Transform**: count of active customer-months in trailing window_months; params={'feature_set_version': 'v1.0'}
- **Business rationale**: Count of active months in the trailing 12 calendar months. (default parameters).
- **Parameters**: `{'feature_set_version': 'v1.0'}`
- **Feature-store location**: table `feature_registry` row (`feature_name`='active_months_12m', `version`=1), `parquet_path`=`feature_store\values\active_months_12m__v1.parquet`, `is_latest`=1

## return_rate_90d

_Versioned: no_  |  _dtype: float_  |  _nullable: False_  |  _default: `0.0`_

#### return_rate_90d v1

- **Description**: Share of transactions that were returns in the trailing 90 days.
- **Source**: data/transactions.db:transactions.is_returned
- **Transform**: sum(is_returned) / count(*) over trailing 90 days; params={'feature_set_version': 'v1.0'}
- **Business rationale**: Share of transactions that were returns in the trailing 90 days. (default parameters).
- **Parameters**: `{'feature_set_version': 'v1.0'}`
- **Feature-store location**: table `feature_registry` row (`feature_name`='return_rate_90d', `version`=1), `parquet_path`=`feature_store\values\return_rate_90d__v1.parquet`, `is_latest`=1

## tenure_days

_Versioned: no_  |  _dtype: int_  |  _nullable: False_  |  _default: `0`_

#### tenure_days v1

- **Description**: Days from signup_date to the as-of date.
- **Source**: data/customers.csv:signup_date
- **Transform**: as_of - signup_date, in days; params={'feature_set_version': 'v1.0'}
- **Business rationale**: Days from signup_date to the as-of date. (default parameters).
- **Parameters**: `{'feature_set_version': 'v1.0'}`
- **Feature-store location**: table `feature_registry` row (`feature_name`='tenure_days', `version`=1), `parquet_path`=`feature_store\values\tenure_days__v1.parquet`, `is_latest`=1
