"""
Driver Decomposition Engine
=============================

Decomposes detected KPI movements into contributing drivers using
deterministic analytical methods:

  1. Price-Volume-Mix decomposition for Revenue
  2. Contribution breakdown for Units Sold (additive by category)
  3. Margin decomposition for Gross Margin %
  4. Period-over-period with data quality for Churn Rate
  5. Marketing correlation analysis (supporting driver)

The LLM is NOT involved here — this is purely deterministic math.
All results include the analytical method used, so downstream modules
can display the exact decomposition methodology.

Usage:
    from engine.decomposition import decompose_anomaly
    result = decompose_anomaly(anomaly, sales_df, marketing_df, roster_df, contract)
"""

from __future__ import annotations

import sys
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from contracts.loader import ContractStore
from engine.detection import AnomalyResult
from engine.reconciliation import spread_weekly_to_daily


# ============================================================
# Data structures
# ============================================================


@dataclass
class DriverContribution:
    """A single driver's contribution to a KPI movement."""
    driver_name: str
    driver_type: str              # controllable / semi_controllable / uncontrollable
    contribution_value: float     # absolute contribution ($ or units or pp)
    contribution_pct: float       # % of total movement explained by this driver
    direction: str                # "increase" or "decrease"
    analytical_method: str        # price_volume_mix / contribution / correlation / etc.
    detail: dict = field(default_factory=dict)  # method-specific breakdown data
    source_table: Optional[str] = None
    source_column: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DecompositionResult:
    """Full decomposition output for a single anomaly."""
    kpi_name: str
    period: str
    total_movement: float         # absolute change that we're decomposing
    total_movement_pct: float     # % change
    drivers: list[DriverContribution]
    explained_pct: float          # sum of |driver contributions| / |total| * 100
    unexplained_residual: float   # what's left after all drivers
    unexplained_pct: float        # residual as % of total movement
    analytical_methods_used: list[str]
    lineage: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ============================================================
# Price-Volume-Mix Decomposition (Revenue)
# ============================================================


def _price_volume_mix(
    sales_df: pd.DataFrame,
    anomaly: AnomalyResult,
    window_days: int = 21,
) -> list[DriverContribution]:
    """
    Classic price-volume-mix decomposition for Revenue.

    Compares the anomaly period to a baseline period (prior N days).
    For each category:
      - Price effect  = (P1 - P0) × V0  (price changed, volume held constant)
      - Volume effect = P0 × (V1 - V0)  (volume changed, price held constant)
      - Mix effect    = (P1 - P0) × (V1 - V0)  (interaction term)

    Aggregates across categories to get total price/volume/mix contributions.
    """
    df = sales_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    event_date = pd.to_datetime(anomaly.period)

    # Baseline: prior window_days
    baseline_start = event_date - pd.Timedelta(days=window_days)
    baseline_end = event_date - pd.Timedelta(days=1)

    baseline = df[(df["date"] >= baseline_start) & (df["date"] <= baseline_end)]
    current = df[df["date"] == event_date]

    if baseline.empty or current.empty:
        return []

    # Aggregate baseline to daily averages per category
    n_baseline_days = baseline["date"].nunique()
    base_by_cat = baseline.groupby("product_category").agg(
        total_units=("units_sold", "sum"),
        total_revenue=("revenue", "sum"),
    ).reset_index()
    base_by_cat["avg_daily_units"] = base_by_cat["total_units"] / n_baseline_days
    base_by_cat["avg_price"] = base_by_cat["total_revenue"] / base_by_cat["total_units"]

    # Current day per category
    curr_by_cat = current.groupby("product_category").agg(
        units=("units_sold", "sum"),
        revenue=("revenue", "sum"),
    ).reset_index()
    curr_by_cat["price"] = curr_by_cat["revenue"] / curr_by_cat["units"]

    # Merge
    merged = pd.merge(
        base_by_cat[["product_category", "avg_daily_units", "avg_price"]],
        curr_by_cat[["product_category", "units", "price"]],
        on="product_category",
        how="outer",
    ).fillna(0)

    total_price_effect = 0.0
    total_volume_effect = 0.0
    total_mix_effect = 0.0
    cat_details = []

    for _, row in merged.iterrows():
        p0 = row["avg_price"]
        p1 = row["price"]
        v0 = row["avg_daily_units"]
        v1 = row["units"]

        price_eff = (p1 - p0) * v0
        volume_eff = p0 * (v1 - v0)
        mix_eff = (p1 - p0) * (v1 - v0)

        total_price_effect += price_eff
        total_volume_effect += volume_eff
        total_mix_effect += mix_eff

        cat_details.append({
            "category": row["product_category"],
            "baseline_price": round(p0, 2),
            "current_price": round(p1, 2),
            "baseline_volume": round(v0, 1),
            "current_volume": round(v1, 1),
            "price_effect": round(price_eff, 2),
            "volume_effect": round(volume_eff, 2),
            "mix_effect": round(mix_eff, 2),
        })

    total_movement = anomaly.absolute_change
    drivers = []

    # Price driver
    drivers.append(DriverContribution(
        driver_name="unit_price",
        driver_type="controllable",
        contribution_value=round(total_price_effect, 2),
        contribution_pct=round(abs(total_price_effect) / abs(total_movement) * 100, 1)
            if total_movement != 0 else 0,
        direction="decrease" if total_price_effect < 0 else "increase",
        analytical_method="price_volume_mix",
        detail={"by_category": [d for d in cat_details], "component": "price_effect"},
        source_table="sales_transactions",
        source_column="unit_price",
    ))

    # Volume driver
    drivers.append(DriverContribution(
        driver_name="units_sold",
        driver_type="semi_controllable",
        contribution_value=round(total_volume_effect, 2),
        contribution_pct=round(abs(total_volume_effect) / abs(total_movement) * 100, 1)
            if total_movement != 0 else 0,
        direction="decrease" if total_volume_effect < 0 else "increase",
        analytical_method="price_volume_mix",
        detail={"by_category": [d for d in cat_details], "component": "volume_effect"},
        source_table="sales_transactions",
        source_column="units_sold",
    ))

    # Mix interaction
    if abs(total_mix_effect) > 1.0:  # Only include if non-trivial
        drivers.append(DriverContribution(
            driver_name="product_mix",
            driver_type="semi_controllable",
            contribution_value=round(total_mix_effect, 2),
            contribution_pct=round(abs(total_mix_effect) / abs(total_movement) * 100, 1)
                if total_movement != 0 else 0,
            direction="decrease" if total_mix_effect < 0 else "increase",
            analytical_method="price_volume_mix",
            detail={"component": "mix_interaction"},
            source_table="sales_transactions",
            source_column="product_category",
        ))

    return drivers


# ============================================================
# Contribution Breakdown (Units Sold — additive by category)
# ============================================================


def _contribution_breakdown(
    sales_df: pd.DataFrame,
    anomaly: AnomalyResult,
    value_column: str = "units_sold",
    window_days: int = 21,
) -> list[DriverContribution]:
    """
    Additive contribution breakdown by product category.

    Total ΔUnits = Σ(ΔUnits per category)
    Each category's contribution = ΔUnits_cat / ΔUnits_total × 100%
    """
    df = sales_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    event_date = pd.to_datetime(anomaly.period)

    baseline_start = event_date - pd.Timedelta(days=window_days)
    baseline_end = event_date - pd.Timedelta(days=1)

    baseline = df[(df["date"] >= baseline_start) & (df["date"] <= baseline_end)]
    current = df[df["date"] == event_date]

    if baseline.empty or current.empty:
        return []

    n_baseline_days = baseline["date"].nunique()

    # Baseline daily average per category
    base_by_cat = baseline.groupby("product_category")[value_column].sum().reset_index()
    base_by_cat.columns = ["product_category", "total"]
    base_by_cat["daily_avg"] = base_by_cat["total"] / n_baseline_days

    # Current day per category
    curr_by_cat = current.groupby("product_category")[value_column].sum().reset_index()
    curr_by_cat.columns = ["product_category", "current"]

    merged = pd.merge(base_by_cat, curr_by_cat, on="product_category", how="outer").fillna(0)
    merged["delta"] = merged["current"] - merged["daily_avg"]

    total_delta = anomaly.absolute_change
    drivers = []

    for _, row in merged.iterrows():
        cat = row["product_category"]
        delta = row["delta"]
        if abs(delta) < 0.5:  # skip negligible contributions
            continue

        pct = abs(delta) / abs(total_delta) * 100 if total_delta != 0 else 0

        drivers.append(DriverContribution(
            driver_name=f"product_mix",
            driver_type="semi_controllable",
            contribution_value=round(delta, 2),
            contribution_pct=round(pct, 1),
            direction="decrease" if delta < 0 else "increase",
            analytical_method="contribution",
            detail={
                "category": cat,
                "baseline_daily_avg": round(row["daily_avg"], 1),
                "current_value": round(row["current"], 1),
                "delta": round(delta, 1),
            },
            source_table="sales_transactions",
            source_column=value_column,
        ))

    # Sort by absolute contribution (largest first)
    drivers.sort(key=lambda d: abs(d.contribution_value), reverse=True)
    return drivers


# ============================================================
# Margin Decomposition (Gross Margin %)
# ============================================================


def _margin_decomposition(
    sales_df: pd.DataFrame,
    anomaly: AnomalyResult,
    window_days: int = 21,
) -> list[DriverContribution]:
    """
    Decompose Gross Margin % movement into price and cost components.

    GM% = (Revenue - Cost) / Revenue = 1 - (Cost/Revenue)

    Changes in GM% come from:
    1. Price changes (revenue side)
    2. Cost changes (cost side)
    3. Mix shifts (category composition)
    """
    df = sales_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    event_date = pd.to_datetime(anomaly.period)

    baseline_start = event_date - pd.Timedelta(days=window_days)
    baseline_end = event_date - pd.Timedelta(days=1)

    baseline = df[(df["date"] >= baseline_start) & (df["date"] <= baseline_end)]
    current = df[df["date"] == event_date]

    if baseline.empty or current.empty:
        return []

    # Baseline averages per category
    n_baseline_days = baseline["date"].nunique()
    base_by_cat = baseline.groupby("product_category").agg(
        total_rev=("revenue", "sum"),
        total_cost=("cost", "sum"),
        total_units=("units_sold", "sum"),
    ).reset_index()
    base_by_cat["avg_price"] = base_by_cat["total_rev"] / base_by_cat["total_units"]
    base_by_cat["avg_cost_per_unit"] = base_by_cat["total_cost"] / base_by_cat["total_units"]
    base_by_cat["avg_daily_units"] = base_by_cat["total_units"] / n_baseline_days

    # Current day
    curr_by_cat = current.groupby("product_category").agg(
        rev=("revenue", "sum"),
        cost=("cost", "sum"),
        units=("units_sold", "sum"),
    ).reset_index()
    curr_by_cat["price"] = curr_by_cat["rev"] / curr_by_cat["units"]
    curr_by_cat["cost_per_unit"] = curr_by_cat["cost"] / curr_by_cat["units"]

    # Overall baseline GM%
    base_total_rev = baseline.groupby("date")["revenue"].sum().mean()
    base_total_cost = baseline.groupby("date")["cost"].sum().mean()
    base_gm_pct = (base_total_rev - base_total_cost) / base_total_rev * 100

    # Current GM%
    curr_total_rev = current["revenue"].sum()
    curr_total_cost = current["cost"].sum()
    curr_gm_pct = (curr_total_rev - curr_total_cost) / curr_total_rev * 100

    gm_change = curr_gm_pct - base_gm_pct  # in percentage points

    # Counterfactual: what would GM% be if only price changed (cost stays baseline)?
    # And vice versa
    merged = pd.merge(
        base_by_cat[["product_category", "avg_price", "avg_cost_per_unit", "avg_daily_units"]],
        curr_by_cat[["product_category", "price", "cost_per_unit", "units"]],
        on="product_category",
        how="outer",
    ).fillna(0)

    # Simulate: current volume & current price, but baseline cost
    sim_rev_price_only = (merged["price"] * merged["units"]).sum()
    sim_cost_price_only = (merged["avg_cost_per_unit"] * merged["units"]).sum()
    gm_price_only = (sim_rev_price_only - sim_cost_price_only) / sim_rev_price_only * 100 \
        if sim_rev_price_only > 0 else base_gm_pct

    # Price contribution = change in GM% due to price alone
    price_contribution_pp = gm_price_only - base_gm_pct

    # Cost contribution = remaining change
    cost_contribution_pp = gm_change - price_contribution_pp

    drivers = []
    total_abs = abs(gm_change) if gm_change != 0 else 1

    drivers.append(DriverContribution(
        driver_name="unit_price",
        driver_type="controllable",
        contribution_value=round(price_contribution_pp, 3),
        contribution_pct=round(abs(price_contribution_pp) / total_abs * 100, 1),
        direction="decrease" if price_contribution_pp < 0 else "increase",
        analytical_method="margin_decomposition",
        detail={
            "baseline_gm_pct": round(base_gm_pct, 2),
            "current_gm_pct": round(curr_gm_pct, 2),
            "counterfactual_gm_pct_price_only": round(gm_price_only, 2),
        },
        source_table="sales_transactions",
        source_column="unit_price",
    ))

    drivers.append(DriverContribution(
        driver_name="unit_cost",
        driver_type="semi_controllable",
        contribution_value=round(cost_contribution_pp, 3),
        contribution_pct=round(abs(cost_contribution_pp) / total_abs * 100, 1),
        direction="decrease" if cost_contribution_pp < 0 else "increase",
        analytical_method="margin_decomposition",
        detail={
            "component": "cost_and_mix_effect",
        },
        source_table="sales_transactions",
        source_column="cost",
    ))

    return drivers


# ============================================================
# Marketing Correlation (supporting driver for Revenue/Units)
# ============================================================


def _marketing_correlation(
    sales_df: pd.DataFrame,
    marketing_df: pd.DataFrame,
    anomaly: AnomalyResult,
    kpi_column: str = "revenue",
    lookback_days: int = 30,
) -> Optional[DriverContribution]:
    """
    Compute correlation between marketing spend and KPI values
    over a lookback window. Returns a driver contribution if the
    correlation is meaningful.

    This is a simple Pearson correlation — not a causal claim.
    The contract tags this as decomposition_method: correlation.
    """
    df_sales = sales_df.copy()
    df_sales["date"] = pd.to_datetime(df_sales["date"])

    daily_mkt = spread_weekly_to_daily(marketing_df)

    event_date = pd.to_datetime(anomaly.period)
    window_start = event_date - pd.Timedelta(days=lookback_days)

    # Daily KPI values
    kpi_daily = df_sales[
        (df_sales["date"] >= window_start) & (df_sales["date"] <= event_date)
    ].groupby("date")[kpi_column].sum().reset_index()
    kpi_daily.columns = ["date", "kpi_value"]

    # Daily total marketing spend
    mkt_daily = daily_mkt[
        (daily_mkt["date"] >= window_start) & (daily_mkt["date"] <= event_date)
    ].groupby("date")["spend"].sum().reset_index()
    mkt_daily.columns = ["date", "total_spend"]

    # Merge
    merged = pd.merge(kpi_daily, mkt_daily, on="date", how="inner")

    if len(merged) < 7:  # need enough points for meaningful correlation
        return None

    corr = merged["kpi_value"].corr(merged["total_spend"])

    if pd.isna(corr) or abs(corr) < 0.3:  # below threshold
        return None

    return DriverContribution(
        driver_name="marketing_spend",
        driver_type="controllable",
        contribution_value=0.0,  # correlation, not a $ value
        contribution_pct=0.0,    # informational, not part of decomposition sum
        direction="correlated" if corr > 0 else "inverse_correlated",
        analytical_method="correlation",
        detail={
            "pearson_r": round(corr, 3),
            "lookback_days": lookback_days,
            "data_points": len(merged),
            "note": "Correlation does not imply causation. Included as a supporting signal.",
        },
        source_table="marketing_spend",
        source_column="spend",
    )


# ============================================================
# Churn decomposition (data quality + period-over-period)
# ============================================================


def _churn_decomposition(
    roster_df: pd.DataFrame,
    anomaly: AnomalyResult,
) -> list[DriverContribution]:
    """
    Decompose churn rate movement with data quality awareness.

    For monthly churn, decomposition is limited to:
    - Data completeness assessment
    - Cohort-level breakdown (by tenure bucket)
    """
    df = roster_df.copy()
    current_month = anomaly.period
    months = sorted(df["month"].unique())
    current_idx = months.index(current_month) if current_month in months else -1

    if current_idx < 1:
        return []

    prior_month = months[current_idx - 1]
    curr_df = df[df["month"] == current_month]
    prior_df = df[df["month"] == prior_month]

    # Data completeness
    curr_total = len(curr_df)
    curr_nulls = curr_df["status"].isna().sum()
    curr_completeness = (curr_total - curr_nulls) / curr_total if curr_total > 0 else 0

    drivers = []

    # Data completeness driver
    # NOTE: all numpy scalars (np.int64 / np.float64 / np.bool_) are cast to
    # native Python types so the result is JSON-serializable (the narration
    # layer and API receive this dict directly).
    drivers.append(DriverContribution(
        driver_name="data_completeness",
        driver_type="uncontrollable",
        contribution_value=float(round(curr_completeness, 4)),
        contribution_pct=0.0,  # meta-driver, not part of additive decomposition
        direction="decrease" if curr_completeness < 0.9 else "stable",
        analytical_method="data_quality_check",
        detail={
            "total_records": int(curr_total),
            "null_records": int(curr_nulls),
            "completeness_pct": float(round(curr_completeness * 100, 1)),
            "threshold_pct": 90.0,
            "passes_quality_gate": bool(curr_completeness >= 0.9),
        },
        source_table="customer_roster",
        source_column="status",
    ))

    # Tenure cohort breakdown (only on non-null records)
    curr_valid = curr_df[curr_df["status"].notna()].copy()
    if not curr_valid.empty and "signup_date" in curr_valid.columns:
        curr_valid["signup_date"] = pd.to_datetime(curr_valid["signup_date"])
        ref_date = pd.to_datetime(current_month + "-01")
        curr_valid["tenure_days"] = (ref_date - curr_valid["signup_date"]).dt.days

        # Bucket into tenure groups
        bins = [0, 90, 180, 365, float("inf")]
        labels = ["<3mo", "3-6mo", "6-12mo", ">12mo"]
        curr_valid["tenure_bucket"] = pd.cut(
            curr_valid["tenure_days"], bins=bins, labels=labels, right=False
        )

        cohort_churn = curr_valid.groupby("tenure_bucket", observed=True).agg(
            total=("status", "count"),
            churned=("status", lambda x: (x == "churned").sum()),
        ).reset_index()
        cohort_churn["churn_rate"] = cohort_churn["churned"] / cohort_churn["total"] * 100

        drivers.append(DriverContribution(
            driver_name="customer_tenure",
            driver_type="uncontrollable",
            contribution_value=0.0,
            contribution_pct=0.0,
            direction="informational",
            analytical_method="cohort_analysis",
            detail={
                "cohorts": [
                    {
                        "bucket": row["tenure_bucket"],
                        "total": int(row["total"]),
                        "churned": int(row["churned"]),
                        "churn_rate": float(round(row["churn_rate"], 1)),
                    }
                    for _, row in cohort_churn.iterrows()
                ],
            },
            source_table="customer_roster",
            source_column="signup_date",
        ))

    return drivers


# ============================================================
# Main decomposition entry point
# ============================================================


def decompose_anomaly(
    anomaly: AnomalyResult,
    sales_df: pd.DataFrame,
    marketing_df: pd.DataFrame,
    roster_df: pd.DataFrame,
    contract: ContractStore,
) -> DecompositionResult:
    """
    Decompose a single detected anomaly into its contributing drivers.

    Selects the appropriate analytical method based on the KPI:
    - Revenue → price-volume-mix decomposition
    - Units Sold → contribution breakdown by category
    - Gross Margin % → margin decomposition (price vs cost)
    - Customer Churn Rate → data quality + cohort analysis

    Returns a DecompositionResult with all drivers, the % of movement
    explained, and the unexplained residual.
    """
    kpi = anomaly.kpi_name
    drivers: list[DriverContribution] = []
    methods: list[str] = []

    if kpi == "Revenue":
        # Primary: price-volume-mix
        pvm_drivers = _price_volume_mix(sales_df, anomaly)
        drivers.extend(pvm_drivers)
        methods.append("price_volume_mix")

        # Supporting: marketing correlation
        mkt_driver = _marketing_correlation(sales_df, marketing_df, anomaly, "revenue")
        if mkt_driver:
            drivers.append(mkt_driver)
            methods.append("correlation")

    elif kpi == "Units Sold":
        # Primary: contribution by category
        contrib_drivers = _contribution_breakdown(sales_df, anomaly, "units_sold")
        drivers.extend(contrib_drivers)
        methods.append("contribution")

        # Supporting: marketing correlation
        mkt_driver = _marketing_correlation(sales_df, marketing_df, anomaly, "units_sold")
        if mkt_driver:
            drivers.append(mkt_driver)
            methods.append("correlation")

    elif kpi == "Gross Margin %":
        # Margin decomposition
        margin_drivers = _margin_decomposition(sales_df, anomaly)
        drivers.extend(margin_drivers)
        methods.append("margin_decomposition")

    elif kpi == "Customer Churn Rate":
        # Churn decomposition
        churn_drivers = _churn_decomposition(roster_df, anomaly)
        drivers.extend(churn_drivers)
        methods.append("data_quality_check")
        methods.append("cohort_analysis")

    # Compute explained % and residual
    total_movement = anomaly.absolute_change
    # Sum of driver contributions (excluding informational/correlation drivers)
    quantitative_drivers = [
        d for d in drivers
        if d.analytical_method not in ("correlation", "data_quality_check", "cohort_analysis")
    ]
    explained_sum = sum(d.contribution_value for d in quantitative_drivers)
    unexplained = total_movement - explained_sum if total_movement != 0 else 0

    explained_pct = (abs(explained_sum) / abs(total_movement) * 100) if total_movement != 0 else 0
    unexplained_pct = 100 - min(explained_pct, 100)

    # Build lineage from contract
    lineage = {}
    try:
        lineage = contract.get_lineage(kpi)
    except Exception:
        pass

    return DecompositionResult(
        kpi_name=kpi,
        period=anomaly.period,
        total_movement=round(total_movement, 2),
        total_movement_pct=round(anomaly.pct_change, 2),
        drivers=drivers,
        explained_pct=round(explained_pct, 1),
        unexplained_residual=round(unexplained, 2),
        unexplained_pct=round(unexplained_pct, 1),
        analytical_methods_used=methods,
        lineage=lineage,
    )


def decompose_all(
    anomalies: list[AnomalyResult],
    sales_df: pd.DataFrame,
    marketing_df: pd.DataFrame,
    roster_df: pd.DataFrame,
    contract: ContractStore,
) -> list[DecompositionResult]:
    """Decompose all detected anomalies. Returns a list of DecompositionResults."""
    return [
        decompose_anomaly(a, sales_df, marketing_df, roster_df, contract)
        for a in anomalies
    ]
