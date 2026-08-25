"""
Reconciliation — Cross-Source Join Logic
=========================================

Joins data across the 3 source tables despite differing grains:
  - sales_transactions: daily
  - marketing_spend: weekly
  - customer_roster: monthly

The reconciliation module aligns these to a common time frame so
driver decomposition can correlate marketing spend with revenue/units
and churn with business metrics.

The LLM is NOT involved here — this is purely deterministic join logic.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd


# ============================================================
# Data structures
# ============================================================


@dataclass
class ReconciliationResult:
    """Output of cross-source reconciliation for a given analysis window."""
    window_start: str
    window_end: str

    # Aligned daily sales data (aggregated or per-category)
    daily_sales: pd.DataFrame

    # Marketing spend spread to daily grain
    daily_marketing: pd.DataFrame

    # Monthly churn data (kept at monthly grain)
    monthly_churn: pd.DataFrame

    # Source freshness metadata
    source_freshness: dict

    def to_metadata_dict(self) -> dict:
        """Return reconciliation metadata (no DataFrames) for JSON serialization."""
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "daily_sales_rows": len(self.daily_sales),
            "daily_marketing_rows": len(self.daily_marketing),
            "monthly_churn_rows": len(self.monthly_churn),
            "source_freshness": self.source_freshness,
        }


# ============================================================
# Grain alignment functions
# ============================================================


def spread_weekly_to_daily(
    marketing_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Spread weekly marketing spend evenly across 7 days.

    Input: week_start, channel, spend
    Output: date, channel, spend (daily, = weekly / 7)

    This is a simple uniform spread. In production you'd weight by
    day-of-week patterns, but for this prototype uniform is sufficient
    and explicitly documented.
    """
    rows = []
    for _, row in marketing_df.iterrows():
        week_start = pd.to_datetime(row["week_start"])
        daily_spend = row["spend"] / 7.0

        for day_offset in range(7):
            rows.append({
                "date": week_start + pd.Timedelta(days=day_offset),
                "channel": row["channel"],
                "spend": round(daily_spend, 2),
                "original_week_start": row["week_start"],
                "grain_note": "weekly_spread_to_daily",
            })

    df = pd.DataFrame(rows)
    return df.sort_values("date").reset_index(drop=True)


def align_monthly_to_window(
    roster_df: pd.DataFrame,
    window_start: str,
    window_end: str,
) -> pd.DataFrame:
    """
    Filter monthly churn data to months overlapping the analysis window.

    Monthly data stays at monthly grain — we don't interpolate to daily
    because churn is inherently a monthly metric. Instead we note which
    months overlap the window.
    """
    df = roster_df.copy()
    # Convert window to month strings for comparison
    ws = pd.to_datetime(window_start)
    we = pd.to_datetime(window_end)

    # Include months that overlap with the window
    start_month = ws.strftime("%Y-%m")
    end_month = we.strftime("%Y-%m")

    mask = (df["month"] >= start_month) & (df["month"] <= end_month)
    return df[mask].copy()


# ============================================================
# Source freshness computation
# ============================================================


def compute_source_freshness(
    sales_df: pd.DataFrame,
    marketing_df: pd.DataFrame,
    roster_df: pd.DataFrame,
    as_of_date: Optional[str] = None,
) -> dict:
    """
    Compute how fresh each source is relative to the analysis date.

    Returns a dict with staleness info per source, which feeds into
    confidence scoring (Phase 5) and is shown in the UI telemetry panel.
    """
    sales = sales_df.copy()
    sales["date"] = pd.to_datetime(sales["date"])
    mkt = marketing_df.copy()
    mkt["week_start"] = pd.to_datetime(mkt["week_start"])

    if as_of_date:
        ref_date = pd.to_datetime(as_of_date)
    else:
        ref_date = sales["date"].max()

    # Sales: latest date
    sales_latest = sales["date"].max()
    sales_staleness_hours = (ref_date - sales_latest).total_seconds() / 3600

    # Marketing: latest week_start + 6 days (end of that week)
    mkt_latest = mkt["week_start"].max() + pd.Timedelta(days=6)
    mkt_staleness_hours = max(0, (ref_date - mkt_latest).total_seconds() / 3600)

    # Roster: latest month → assume available on 1st of next month
    roster_latest_month = roster_df["month"].max()
    roster_latest_date = pd.to_datetime(roster_latest_month + "-01") + pd.offsets.MonthEnd(0)
    roster_staleness_hours = max(0, (ref_date - roster_latest_date).total_seconds() / 3600)

    return {
        "sales_transactions": {
            "latest_data": sales_latest.strftime("%Y-%m-%d"),
            "staleness_hours": round(sales_staleness_hours, 1),
            "grain": "daily",
            "status": "fresh" if sales_staleness_hours < 48 else "stale",
        },
        "marketing_spend": {
            "latest_data": mkt_latest.strftime("%Y-%m-%d"),
            "staleness_hours": round(mkt_staleness_hours, 1),
            "grain": "weekly",
            "status": "fresh" if mkt_staleness_hours < 168 else "stale",
        },
        "customer_roster": {
            "latest_data": roster_latest_month,
            "staleness_hours": round(roster_staleness_hours, 1),
            "grain": "monthly",
            "status": "fresh" if roster_staleness_hours < 720 else "stale",
        },
    }


# ============================================================
# Main reconciliation entry point
# ============================================================


def reconcile(
    sales_df: pd.DataFrame,
    marketing_df: pd.DataFrame,
    roster_df: pd.DataFrame,
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
) -> ReconciliationResult:
    """
    Reconcile the 3 source tables into aligned datasets for analysis.

    Steps:
    1. Filter sales to the analysis window.
    2. Spread weekly marketing to daily grain.
    3. Filter monthly churn to overlapping months.
    4. Compute source freshness.

    The output is a ReconciliationResult with aligned DataFrames
    that the decomposition module can consume directly.
    """
    sales = sales_df.copy()
    sales["date"] = pd.to_datetime(sales["date"])

    # Default window: full date range
    if window_start is None:
        window_start = sales["date"].min().strftime("%Y-%m-%d")
    if window_end is None:
        window_end = sales["date"].max().strftime("%Y-%m-%d")

    ws = pd.to_datetime(window_start)
    we = pd.to_datetime(window_end)

    # 1. Filter sales to window
    sales_window = sales[(sales["date"] >= ws) & (sales["date"] <= we)].copy()

    # 2. Spread marketing to daily
    daily_mkt = spread_weekly_to_daily(marketing_df)
    daily_mkt_window = daily_mkt[
        (daily_mkt["date"] >= ws) & (daily_mkt["date"] <= we)
    ].copy()

    # 3. Align monthly churn
    monthly_churn = align_monthly_to_window(roster_df, window_start, window_end)

    # 4. Source freshness
    freshness = compute_source_freshness(
        sales_df, marketing_df, roster_df, as_of_date=window_end
    )

    return ReconciliationResult(
        window_start=window_start,
        window_end=window_end,
        daily_sales=sales_window,
        daily_marketing=daily_mkt_window,
        monthly_churn=monthly_churn,
        source_freshness=freshness,
    )
