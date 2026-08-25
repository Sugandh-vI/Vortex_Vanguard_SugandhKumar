"""
Synthetic Data Generator for BusinessIntelligence.ai
====================================================

Generates ~90 days of data across 3 source tables with 4 scripted events:

1. Multi-factor Revenue dip — Week 7 (May 13-19, 2024):
   10% price cut on Electronics + unexplained 20% volume drop (competitor promo).
   Price-volume-mix decomposition should explain part (price) but leave residual (volume).

2. Sparse-history KPI — Day 80+ (Jun 19, 2024):
   New "Sports & Outdoors" category launches with only ~11 days of history.
   System must say "insufficient history" rather than force a score.

3. Low-confidence / abstain — Month 3 (June), Churn:
   ~30% of customer_roster records have null status (simulated sync failure).
   Churn appears to increase, but data completeness is too low to trust.

4. Access control — Gross Margin % (permissions rule, no data manipulation needed).

Output: CSV files + SQLite database in /backend/data/raw/.
"""

import os
import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# ============================================================
# Reproducibility
# ============================================================
np.random.seed(42)

# ============================================================
# Date range configuration
# ============================================================
START_DATE = datetime(2024, 4, 1)
NUM_DAYS = 90  # Apr 1 – Jun 29, 2024
END_DATE = START_DATE + timedelta(days=NUM_DAYS - 1)  # Jun 29

# Week 7: days 43-49 (0-indexed 42-48), i.e. May 13-19, 2024
WEEK7_START_DAY = 42   # 0-indexed
WEEK7_END_DAY = 48     # 0-indexed (inclusive)

# New product launch: day 80 (0-indexed 79), i.e. Jun 19, 2024
NEW_PRODUCT_LAUNCH_DAY = 79  # 0-indexed

# ============================================================
# Product categories & regions
# ============================================================
CATEGORIES = ["Electronics", "Apparel", "Home & Kitchen", "Grocery"]
NEW_CATEGORY = "Sports & Outdoors"
REGIONS = ["North", "South", "East", "West"]
REGION_WEIGHTS = {"North": 0.35, "South": 0.25, "East": 0.20, "West": 0.20}

# ============================================================
# Category baseline configurations
# base_units: total daily units across all regions
# base_price: unit selling price ($)
# base_cost: unit cost ($) — fixed, does NOT change with price cuts
# noise_std: standard deviation of daily noise (fraction)
# weekend_mult: weekend (Sat/Sun) volume multiplier
# ============================================================
CATEGORY_CONFIG = {
    "Electronics": {
        "base_units": 200,
        "base_price": 149.99,
        "base_cost": 97.50,   # GM% ≈ 35%
        "noise_std": 0.05,
        "weekend_mult": 0.85,
    },
    "Apparel": {
        "base_units": 300,
        "base_price": 39.99,
        "base_cost": 22.00,   # GM% ≈ 45%
        "noise_std": 0.06,
        "weekend_mult": 1.10,
    },
    "Home & Kitchen": {
        "base_units": 150,
        "base_price": 59.99,
        "base_cost": 36.00,   # GM% ≈ 40%
        "noise_std": 0.05,
        "weekend_mult": 0.88,
    },
    "Grocery": {
        "base_units": 500,
        "base_price": 9.99,
        "base_cost": 7.00,    # GM% ≈ 30%
        "noise_std": 0.04,
        "weekend_mult": 1.15,
    },
}

NEW_CATEGORY_CONFIG = {
    "base_units": 50,
    "base_price": 34.99,
    "base_cost": 20.00,       # GM% ≈ 43%
    "noise_std": 0.08,        # higher noise — new category is volatile
    "weekend_mult": 1.05,
}

# Slight overall growth trend: +0.1% per day
DAILY_TREND = 0.001

# ============================================================
# Marketing channels (weekly)
# ============================================================
CHANNELS = ["Digital", "TV", "Print", "Social"]
CHANNEL_BASE_SPEND = {
    "Digital": 15000,
    "TV": 25000,
    "Print": 5000,
    "Social": 10000,
}
MARKETING_NOISE_STD = 0.10  # ±10% weekly variation

# ============================================================
# Customer roster (monthly)
# ============================================================
NUM_BASE_CUSTOMERS = 1000
BASE_MONTHLY_CHURN_RATE = 0.05    # 5% monthly churn (Months 1-2)
MONTH3_CHURN_RATE = 0.08          # 8% — genuine increase in Month 3
MONTH3_NULL_FRACTION = 0.30       # 30% of June records get null status
NEW_CUSTOMERS_PER_MONTH = (15, 30)  # range for random new signups

# ============================================================
# Output
# ============================================================
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw")


# ============================================================
# Generator functions
# ============================================================


def generate_sales_transactions() -> pd.DataFrame:
    """
    Generate daily sales_transactions table.

    Columns: date, product_category, region, units_sold, unit_price, revenue, cost

    Scripted events injected:
    - Event 1: Week 7, Electronics — 10% price cut + 20% volume drop
    - Event 2: Day 80+, "Sports & Outdoors" category appears with sparse history
    """
    rows = []

    for day_idx in range(NUM_DAYS):
        date = START_DATE + timedelta(days=day_idx)
        is_weekend = date.weekday() >= 5  # Saturday=5, Sunday=6

        # Determine active categories
        active_cats = list(CATEGORIES)
        if day_idx >= NEW_PRODUCT_LAUNCH_DAY:
            active_cats.append(NEW_CATEGORY)

        for category in active_cats:
            cfg = NEW_CATEGORY_CONFIG if category == NEW_CATEGORY else CATEGORY_CONFIG[category]

            for region, weight in REGION_WEIGHTS.items():
                # --- Base units for this region ---
                base_units = cfg["base_units"] * weight

                # Apply slight daily growth trend
                trend_factor = 1.0 + DAILY_TREND * day_idx

                # Apply weekend multiplier
                weekend_factor = cfg["weekend_mult"] if is_weekend else 1.0

                # Apply random daily noise
                noise_factor = 1.0 + np.random.normal(0, cfg["noise_std"])

                units = base_units * trend_factor * weekend_factor * noise_factor
                units = max(1, int(round(units)))

                # --- Price ---
                price = cfg["base_price"]
                # Tiny daily price jitter (±0.5%)
                price *= (1.0 + np.random.normal(0, 0.005))
                price = round(price, 2)

                # --- Cost per unit (fixed, independent of selling price) ---
                cost_per_unit = cfg["base_cost"]
                # Tiny cost jitter (±1%)
                cost_per_unit *= (1.0 + np.random.normal(0, 0.01))
                cost_per_unit = round(cost_per_unit, 2)

                # ===== EVENT 1: Week 7 Electronics =====
                if category == "Electronics" and WEEK7_START_DAY <= day_idx <= WEEK7_END_DAY:
                    # 10% selling price cut (cost stays the same → margin compression)
                    price = round(price * 0.90, 2)
                    # 20% volume drop (unexplained — competitor promo)
                    units = max(1, int(round(units * 0.80)))

                # --- Derived columns ---
                revenue = round(units * price, 2)
                total_cost = round(units * cost_per_unit, 2)

                rows.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "product_category": category,
                    "region": region,
                    "units_sold": units,
                    "unit_price": price,
                    "revenue": revenue,
                    "cost": total_cost,
                })

    df = pd.DataFrame(rows)
    print(f"  sales_transactions: {len(df)} rows, "
          f"date range {df['date'].min()} to {df['date'].max()}, "
          f"categories: {sorted(df['product_category'].unique())}")
    return df


def generate_marketing_spend() -> pd.DataFrame:
    """
    Generate weekly marketing_spend table.

    Columns: week_start, channel, spend
    """
    rows = []
    # Start from the Monday on or before START_DATE
    first_monday = START_DATE - timedelta(days=START_DATE.weekday())
    week_start = first_monday

    while week_start <= END_DATE:
        for channel in CHANNELS:
            base = CHANNEL_BASE_SPEND[channel]
            noise = 1.0 + np.random.normal(0, MARKETING_NOISE_STD)
            spend = round(max(0, base * noise), 2)

            rows.append({
                "week_start": week_start.strftime("%Y-%m-%d"),
                "channel": channel,
                "spend": spend,
            })

        week_start += timedelta(weeks=1)

    df = pd.DataFrame(rows)
    print(f"  marketing_spend:    {len(df)} rows, "
          f"{len(df) // len(CHANNELS)} weeks × {len(CHANNELS)} channels")
    return df


def generate_customer_roster() -> pd.DataFrame:
    """
    Generate monthly customer_roster table.

    Columns: month, customer_id, status (active/churned/null), signup_date

    Scripted event:
    - Event 3: Month 3 (June) — 30% of records get null status (sync failure),
      AND the true churn rate is bumped to 8% (so the movement is real but unverifiable).
    """
    months = ["2024-04", "2024-05", "2024-06"]
    month_churn_rates = [BASE_MONTHLY_CHURN_RATE, BASE_MONTHLY_CHURN_RATE, MONTH3_CHURN_RATE]

    # Generate base customer pool with staggered signup dates
    customer_ids = [f"CUST-{i:04d}" for i in range(1, NUM_BASE_CUSTOMERS + 1)]
    signup_dates = {}
    for cid in customer_ids:
        # Random signup 30-365 days before start
        days_before = np.random.randint(30, 366)
        signup_dates[cid] = (START_DATE - timedelta(days=int(days_before))).strftime("%Y-%m-%d")

    # Track cumulative churn
    churned_set = set()
    rows = []
    next_cust_id = NUM_BASE_CUSTOMERS + 1

    for month_idx, (month, churn_rate) in enumerate(zip(months, month_churn_rates)):
        # Add new customers each month (except month 1)
        if month_idx > 0:
            new_count = np.random.randint(*NEW_CUSTOMERS_PER_MONTH)
            for _ in range(new_count):
                cid = f"CUST-{next_cust_id:04d}"
                customer_ids.append(cid)
                signup_dates[cid] = f"{month}-01"
                next_cust_id += 1

        for cid in customer_ids:
            # Once churned, stays churned
            if cid in churned_set:
                status = "churned"
            else:
                # Roll for churn this month
                if np.random.random() < churn_rate:
                    churned_set.add(cid)
                    status = "churned"
                else:
                    status = "active"

            row = {
                "month": month,
                "customer_id": cid,
                "status": status,
                "signup_date": signup_dates[cid],
            }

            # === EVENT 3: Month 3 null injection ===
            if month_idx == 2 and np.random.random() < MONTH3_NULL_FRACTION:
                row["status"] = None  # Simulated sync failure — null status

            rows.append(row)

    df = pd.DataFrame(rows)

    # Print summary stats
    for month in months:
        month_df = df[df["month"] == month]
        total = len(month_df)
        nulls = month_df["status"].isna().sum()
        active = (month_df["status"] == "active").sum()
        churned = (month_df["status"] == "churned").sum()
        print(f"  customer_roster [{month}]: {total} rows, "
              f"active={active}, churned={churned}, null={nulls} "
              f"({nulls/total*100:.1f}% missing)")

    return df


def save_data(
    sales_df: pd.DataFrame,
    marketing_df: pd.DataFrame,
    roster_df: pd.DataFrame,
) -> None:
    """Save all tables to CSV and SQLite in the raw output directory."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # --- CSV ---
    sales_df.to_csv(os.path.join(OUTPUT_DIR, "sales_transactions.csv"), index=False)
    marketing_df.to_csv(os.path.join(OUTPUT_DIR, "marketing_spend.csv"), index=False)
    roster_df.to_csv(os.path.join(OUTPUT_DIR, "customer_roster.csv"), index=False)

    # --- SQLite ---
    db_path = os.path.join(OUTPUT_DIR, "kpi_data.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    sales_df.to_sql("sales_transactions", conn, if_exists="replace", index=False)
    marketing_df.to_sql("marketing_spend", conn, if_exists="replace", index=False)
    roster_df.to_sql("customer_roster", conn, if_exists="replace", index=False)
    conn.close()

    print(f"\nAll data saved to: {OUTPUT_DIR}/")
    print(f"  - sales_transactions.csv ({len(sales_df)} rows)")
    print(f"  - marketing_spend.csv    ({len(marketing_df)} rows)")
    print(f"  - customer_roster.csv    ({len(roster_df)} rows)")
    print(f"  - kpi_data.db            (SQLite with all 3 tables)")


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("BusinessIntelligence.ai — Synthetic Data Generator")
    print("=" * 60)
    print(f"\nDate range: {START_DATE.strftime('%Y-%m-%d')} to {END_DATE.strftime('%Y-%m-%d')} ({NUM_DAYS} days)")
    print(f"Week 7 event: {(START_DATE + timedelta(days=WEEK7_START_DAY)).strftime('%Y-%m-%d')} to "
          f"{(START_DATE + timedelta(days=WEEK7_END_DAY)).strftime('%Y-%m-%d')}")
    print(f"New category launch: {(START_DATE + timedelta(days=NEW_PRODUCT_LAUNCH_DAY)).strftime('%Y-%m-%d')}")
    print()

    print("Generating sales_transactions...")
    sales = generate_sales_transactions()

    print("\nGenerating marketing_spend...")
    marketing = generate_marketing_spend()

    print("\nGenerating customer_roster...")
    roster = generate_customer_roster()

    save_data(sales, marketing, roster)
    print("\n✅ Data generation complete!")
