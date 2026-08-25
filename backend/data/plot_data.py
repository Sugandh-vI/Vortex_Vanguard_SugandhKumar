"""
Plot the synthetic data to visually confirm the 4 scripted events.

Generates a multi-panel figure saved as PNG:
  1. Total daily Revenue — Week 7 dip should be clearly visible
  2. Electronics: Price + Units around Week 7 — shows price cut and volume drop
  3. Revenue by category — shows when "Sports & Outdoors" appears (Day 80)
  4. Monthly Churn Rate + Data Completeness — Month 3 null issue visible
  5. Daily Gross Margin % — shows margin compression during Week 7

Usage:
    python plot_data.py
"""

import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw")
PLOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw")

# Event markers
WEEK7_START = datetime(2024, 5, 13)
WEEK7_END = datetime(2024, 5, 19)
NEW_PRODUCT_DATE = datetime(2024, 6, 19)


def load_data():
    """Load CSV data."""
    sales = pd.read_csv(os.path.join(RAW_DIR, "sales_transactions.csv"), parse_dates=["date"])
    marketing = pd.read_csv(os.path.join(RAW_DIR, "marketing_spend.csv"))
    roster = pd.read_csv(os.path.join(RAW_DIR, "customer_roster.csv"))
    return sales, marketing, roster


def plot_all(sales: pd.DataFrame, roster: pd.DataFrame):
    """Generate the 5-panel verification plot."""
    fig, axes = plt.subplots(3, 2, figsize=(18, 16))
    fig.suptitle(
        "BusinessIntelligence.ai — Synthetic Data: 4 Scripted Events Verification",
        fontsize=16, fontweight="bold", y=0.98
    )

    # ================================================================
    # Panel 1: Total Daily Revenue
    # ================================================================
    ax1 = axes[0, 0]
    daily_rev = sales.groupby("date")["revenue"].sum().reset_index()
    ax1.plot(daily_rev["date"], daily_rev["revenue"], color="#2563eb", linewidth=1.2, alpha=0.9)
    ax1.axvspan(WEEK7_START, WEEK7_END, color="red", alpha=0.15, label="Week 7 Event")
    ax1.axvline(NEW_PRODUCT_DATE, color="green", linestyle="--", alpha=0.7, label="Sports Launch (Day 80)")
    ax1.set_title("① Total Daily Revenue — Week 7 Dip Visible", fontweight="bold")
    ax1.set_ylabel("Revenue ($)")
    ax1.legend(fontsize=8)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax1.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    ax1.tick_params(axis="x", rotation=30)
    ax1.grid(axis="y", alpha=0.3)

    # ================================================================
    # Panel 2: Electronics Price + Units during Week 7
    # ================================================================
    ax2 = axes[0, 1]
    elec = sales[sales["product_category"] == "Electronics"]
    elec_daily_price = elec.groupby("date")["unit_price"].mean().reset_index()
    elec_daily_units = elec.groupby("date")["units_sold"].sum().reset_index()

    color_price = "#dc2626"
    color_units = "#2563eb"

    ax2.plot(elec_daily_price["date"], elec_daily_price["unit_price"],
             color=color_price, linewidth=1.5, label="Avg Unit Price ($)")
    ax2.set_ylabel("Unit Price ($)", color=color_price)
    ax2.tick_params(axis="y", labelcolor=color_price)

    ax2b = ax2.twinx()
    ax2b.plot(elec_daily_units["date"], elec_daily_units["units_sold"],
              color=color_units, linewidth=1.2, alpha=0.7, label="Units Sold")
    ax2b.set_ylabel("Units Sold", color=color_units)
    ax2b.tick_params(axis="y", labelcolor=color_units)

    ax2.axvspan(WEEK7_START, WEEK7_END, color="red", alpha=0.15)
    ax2.set_title("② Electronics: Price Cut + Volume Drop (Week 7)", fontweight="bold")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax2.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    ax2.tick_params(axis="x", rotation=30)

    # Combined legend
    lines1, labels1 = ax2.get_legend_handles_labels()
    lines2, labels2 = ax2b.get_legend_handles_labels()
    ax2.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="lower left")

    # ================================================================
    # Panel 3: Revenue by Category — Sports appears Day 80
    # ================================================================
    ax3 = axes[1, 0]
    cat_daily_rev = sales.groupby(["date", "product_category"])["revenue"].sum().reset_index()
    cat_pivot = cat_daily_rev.pivot(index="date", columns="product_category", values="revenue").fillna(0)

    colors = {
        "Electronics": "#2563eb",
        "Apparel": "#7c3aed",
        "Home & Kitchen": "#ea580c",
        "Grocery": "#16a34a",
        "Sports & Outdoors": "#dc2626",
    }
    for cat in cat_pivot.columns:
        ax3.plot(cat_pivot.index, cat_pivot[cat], label=cat,
                 color=colors.get(cat, "gray"), linewidth=1.2, alpha=0.85)

    ax3.axvline(NEW_PRODUCT_DATE, color="red", linestyle="--", alpha=0.7, label="Sports Launch")
    ax3.axvspan(WEEK7_START, WEEK7_END, color="red", alpha=0.08)
    ax3.set_title("③ Revenue by Category — Sports & Outdoors Appears Day 80", fontweight="bold")
    ax3.set_ylabel("Revenue ($)")
    ax3.legend(fontsize=7, ncol=2)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax3.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    ax3.tick_params(axis="x", rotation=30)
    ax3.grid(axis="y", alpha=0.3)

    # ================================================================
    # Panel 4: Monthly Churn Rate + Data Completeness
    # ================================================================
    ax4 = axes[1, 1]
    months = ["2024-04", "2024-05", "2024-06"]
    month_labels = ["Apr 2024", "May 2024", "Jun 2024"]

    churn_rates = []
    completeness = []
    for m in months:
        m_df = roster[roster["month"] == m]
        total = len(m_df)
        nulls = m_df["status"].isna().sum()
        non_null = m_df[m_df["status"].notna()]
        churned = (non_null["status"] == "churned").sum()
        rate = churned / len(non_null) * 100 if len(non_null) > 0 else 0
        comp = (total - nulls) / total * 100

        churn_rates.append(rate)
        completeness.append(comp)

    x = range(len(months))
    bars1 = ax4.bar([i - 0.15 for i in x], churn_rates, 0.3, color="#dc2626", alpha=0.8, label="Apparent Churn Rate (%)")
    ax4.set_ylabel("Churn Rate (%)", color="#dc2626")
    ax4.tick_params(axis="y", labelcolor="#dc2626")

    ax4b = ax4.twinx()
    bars2 = ax4b.bar([i + 0.15 for i in x], completeness, 0.3, color="#2563eb", alpha=0.6, label="Data Completeness (%)")
    ax4b.set_ylabel("Data Completeness (%)", color="#2563eb")
    ax4b.set_ylim(0, 110)
    ax4b.tick_params(axis="y", labelcolor="#2563eb")

    ax4.set_xticks(list(x))
    ax4.set_xticklabels(month_labels)
    ax4.set_title("④ Monthly Churn Rate vs Data Completeness — Month 3 Issue", fontweight="bold")

    # Add value labels on bars
    for bar, val in zip(bars1, churn_rates):
        ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                 f"{val:.1f}%", ha="center", fontsize=9, fontweight="bold", color="#dc2626")
    for bar, val in zip(bars2, completeness):
        ax4b.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                  f"{val:.0f}%", ha="center", fontsize=9, fontweight="bold", color="#2563eb")

    lines1, labels1 = ax4.get_legend_handles_labels()
    lines2, labels2 = ax4b.get_legend_handles_labels()
    ax4.legend(lines1 + lines2, labels1 + labels2, fontsize=8)

    # ================================================================
    # Panel 5: Daily Gross Margin % — margin compression during Week 7
    # ================================================================
    ax5 = axes[2, 0]
    # Gross Margin % = (Revenue - Cost) / Revenue * 100
    daily_financials = sales.groupby("date").agg({"revenue": "sum", "cost": "sum"}).reset_index()
    daily_financials["gross_margin_pct"] = (
        (daily_financials["revenue"] - daily_financials["cost"]) / daily_financials["revenue"] * 100
    )

    ax5.plot(daily_financials["date"], daily_financials["gross_margin_pct"],
             color="#16a34a", linewidth=1.2)
    ax5.axvspan(WEEK7_START, WEEK7_END, color="red", alpha=0.15, label="Week 7 (margin compression)")
    ax5.axvline(NEW_PRODUCT_DATE, color="green", linestyle="--", alpha=0.7)
    ax5.set_title("⑤ Daily Gross Margin % — Compression During Week 7 Price Cut", fontweight="bold")
    ax5.set_ylabel("Gross Margin (%)")
    ax5.legend(fontsize=8)
    ax5.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax5.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    ax5.tick_params(axis="x", rotation=30)
    ax5.grid(axis="y", alpha=0.3)

    # ================================================================
    # Panel 6: Sports & Outdoors — Sparse History Close-up
    # ================================================================
    ax6 = axes[2, 1]
    sports = sales[sales["product_category"] == "Sports & Outdoors"]
    if not sports.empty:
        sports_daily = sports.groupby("date").agg(
            {"revenue": "sum", "units_sold": "sum"}
        ).reset_index()

        ax6.bar(sports_daily["date"], sports_daily["revenue"],
                color="#dc2626", alpha=0.7, width=0.8, label="Daily Revenue")
        ax6.set_title(
            f"⑥ Sports & Outdoors — Only {len(sports_daily)} Days of History (Sparse!)",
            fontweight="bold"
        )
        ax6.set_ylabel("Revenue ($)")
        ax6.legend(fontsize=8)
        ax6.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax6.tick_params(axis="x", rotation=30)
        ax6.grid(axis="y", alpha=0.3)

        # Annotate that this is insufficient for baseline
        ax6.annotate(
            "Too few days for\nreliable baseline",
            xy=(sports_daily["date"].iloc[len(sports_daily)//2],
                sports_daily["revenue"].max() * 0.9),
            fontsize=11, color="#dc2626", fontweight="bold",
            ha="center",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="yellow", alpha=0.7),
        )
    else:
        ax6.text(0.5, 0.5, "No Sports data found", ha="center", va="center",
                 transform=ax6.transAxes, fontsize=14)

    # ================================================================
    # Save
    # ================================================================
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plot_path = os.path.join(PLOT_DIR, "data_verification_plots.png")
    plt.savefig(plot_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"\nPlot saved to: {plot_path}")
    return plot_path


if __name__ == "__main__":
    print("Loading data and generating verification plots...")
    sales, marketing, roster = load_data()
    plot_path = plot_all(sales, roster)
    print(f"✅ Done! Open {plot_path} to verify the 4 scripted events.")
