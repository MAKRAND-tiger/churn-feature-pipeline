"""
Pure I/O loaders for the three heterogeneous raw sources described in
`data_dictionary.md`:
  - `customers.csv`                (flat file / customer profile)
  - `data/transactions.db`          (SQLite, row-level `transactions` table)
  - `transactions_monthly_agg.parquet` (pre-aggregated customer x month extract)

No feature logic belongs here — only loading and basic type coercion, so ingestion
can be unit-tested and swapped independently of `transforms.py`.
"""

from pathlib import Path

import pandas as pd


def load_customers(path: str = "data/customers.csv") -> pd.DataFrame:
    """Load customers.csv.

    Reads the customer profile CSV and parses `signup_date` as a real date.
    Returns one row per customer_id, unmodified otherwise.
    """
    df = pd.read_csv(path, parse_dates=["signup_date"])
    # Defensive: ensure customer_id is an int and churned is a clean 0/1 int.
    df["customer_id"] = df["customer_id"].astype(int)
    df["churned"] = df["churned"].astype(int)
    return df


def load_transactions(path: str = "data/transactions.db") -> pd.DataFrame:
    """Load the row-level `transactions` table from the SQLite database.

    Connects with sqlite3 (via pandas.read_sql), casts `txn_timestamp` to a real
    datetime (SQLite stores it as ISO-8601 text) and `is_returned` to a clean
    0/1 int. Returns the full row-level frame — does not aggregate here.
    """
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        df = pd.read_sql("SELECT * FROM transactions", conn, parse_dates=["txn_timestamp"])
    finally:
        conn.close()
    df["customer_id"] = df["customer_id"].astype(int)
    df["is_returned"] = df["is_returned"].astype(int)
    return df


def load_monthly_agg(path: str = "data/transactions_monthly_agg.parquet") -> pd.DataFrame:
    """Load the pre-aggregated customer x month parquet extract.

    Reads the parquet file with pandas and parses `txn_month` as a date
    (first-of-month). Returns as-is — remember customers/months with zero
    activity have no row (sparse representation).
    """
    df = pd.read_parquet(path)
    df["customer_id"] = df["customer_id"].astype(int)
    df["txn_month"] = pd.to_datetime(df["txn_month"])
    return df
