import sqlite3
import pandas as pd

print("=== TRANSACTIONS DB ===")
conn = sqlite3.connect("data/transactions.db")
df = pd.read_sql("SELECT * FROM transactions", conn, parse_dates=["txn_timestamp"])
conn.close()
print("rows:", len(df))
print("dtypes:")
print(df.dtypes)
print("head:")
print(df.head())
print("is_returned values:", sorted(df["is_returned"].unique().tolist()))
print("txn_timestamp range:", df["txn_timestamp"].min(), "->", df["txn_timestamp"].max())
print("amount stats:")
print(df["amount"].describe())
print("category values:", df["category"].value_counts().to_dict())
print("channel values:", df["channel"].value_counts().to_dict())
print("unique customer_id in txns:", df["customer_id"].nunique())
print("returned amount stats:")
print(df[df["is_returned"] == 1]["amount"].describe() if (df["is_returned"] == 1).any() else "none")

print("\n=== MONTHLY AGG PARQUET ===")
m = pd.read_parquet("data/transactions_monthly_agg.parquet")
print("shape:", m.shape)
print("cols:", list(m.columns))
print("dtypes:")
print(m.dtypes)
print("head:")
print(m.head())
print("txn_month range:", m["txn_month"].min(), "->", m["txn_month"].max())
print("unique customer_id in agg:", m["customer_id"].nunique())
print("total_amount stats:")
print(m["total_amount"].describe())
print("return_count sum:", m["return_count"].sum())
print("txn_count sum:", m["txn_count"].sum())

print("\n=== CUSTOMERS CSV ===")
cust = pd.read_csv("data/customers.csv", parse_dates=["signup_date"])
print("shape:", cust.shape)
print("dtypes:")
print(cust.dtypes)
print("head:")
print(cust.head())
print("churned:", cust["churned"].value_counts().to_dict())
print("channels:", cust["acquisition_channel"].value_counts().to_dict())
print("regions:", cust["region"].value_counts().to_dict())
print("signup_date range:", cust["signup_date"].min(), "->", cust["signup_date"].max())
print("customer_id range:", cust["customer_id"].min(), "->", cust["customer_id"].max())

print("\n=== CROSS-SOURCE CHECKS ===")
cust_ids = set(cust["customer_id"].tolist())
txn_cust = set(df["customer_id"].unique().tolist())
agg_cust = set(m["customer_id"].unique().tolist())
print("customers with zero txn rows:", len(cust_ids - txn_cust))
print("customers with zero agg rows:", len(cust_ids - agg_cust))
print("txn customers not in customers:", len(txn_cust - cust_ids))
print("agg customers not in customers:", len(agg_cust - cust_ids))

# Spot-check disagreement between row-level and monthly agg at the edges
print("\n=== SPOT-CHECK: monthly total vs agg total (by customer-month) ===")
df["txn_month"] = df["txn_timestamp"].dt.to_period("M").dt.to_timestamp()
rl = df.groupby(["customer_id", "txn_month"]).agg(
    txn_count_rl=("amount", "size"),
    spend_rl=("amount", "sum"),
    return_count_rl=("is_returned", "sum"),
).reset_index()
merged = rl.merge(m, on=["customer_id", "txn_month"], how="outer", suffixes=("_rl", ""))
diff_count = merged[(merged["txn_count_rl"].fillna(-1) != merged["txn_count"].fillna(-1))]
print("customer-months where txn_count row-level != agg:", len(diff_count))
print(diff_count.head(10))
diff_spend = merged[(merged["spend_rl"].fillna(-999) != merged["total_amount"].fillna(-999))]
print("customer-months where spend row-level != total_amount:", len(diff_spend))
print(diff_spend.head(10))
diff_ret = merged[(merged["return_count_rl"].fillna(-1) != merged["return_count"].fillna(-1))]
print("customer-months where return_count row-level != agg:", len(diff_ret))
print(diff_ret.head(10))

# Amount returned is negative?
print("\n=== returned amount sign ===")
print(df.groupby("is_returned")["amount"].describe())
