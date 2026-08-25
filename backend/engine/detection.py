"""
Detection Engine — Anomaly / Materiality Detection
====================================================

Detects material KPI movements using rolling z-score anomaly detection
for daily KPIs and period-over-period change detection for monthly KPIs.
Applies materiality filters from the semantic contract (% change AND/OR
absolute impact thresholds).

The LLM is NOT involved here — this is purely deterministic detection.

Usage:
    from engine.detection import run_detection
    from contracts.loader import ContractStore

    store = ContractStore()
    results = run_detection(sales_df, roster_df, store)
    # -> list[AnomalyResult]
"""

from __future__ import annotations

import sys
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd

# Allow imports from the backend root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from contracts.loader import ContractStore


# ============================================================
# Configuration defaults
# ============================================================

DEFAULT_ROLLING_WINDOW = 21     # 3 weeks for daily KPIs
DEFAULT_ZSCORE_THRESHOLD = 2.0  # ~95th percentile
MIN_WINDOW_POINTS = 7           # need ≥7 points to compute a reliable baseline


# ============================================================
# Data structures
# ============================================================


@dataclass
class AnomalyResult:
    """Structured output for a single detected KPI anomaly."""

    kpi_name: str
    period: str                   # date string (YYYY-MM-DD) or month (YYYY-MM)
    period_type: str              # "daily" or "monthly"
    current_value: float
    baseline_value: float         # rolling mean or prior-period value
    baseline_std: Optional[float] # rolling std dev (None for monthly)
    absolute_change: float
    pct_change: float             # percentage change vs baseline
    z_score: Optional[float]      # None if insufficient history
    direction: str                # "increase" or "decrease"

    # Materiality assessment
    is_material: bool
    materiality_details: dict = field(default_factory=dict)

    # Detection metadata
    detection_method: str = ""    # "rolling_zscore" or "period_over_period"
    data_points_used: int = 0
    insufficient_history: bool = False

    # Data quality (populated for churn)
    data_completeness: Optional[float] = None

    def to_dict(self) -> dict:
        """Convert to a plain dict for JSON serialization."""
        return asdict(self)


@dataclass
class SparseHistoryFlag:
    """
    Explicit flag for KPIs or categories with insufficient history.

    This is distinct from "no anomaly detected" — it means the engine
    cannot reliably assess this KPI because there aren't enough data
    points to establish a baseline. Phase 5 (confidence) uses this
    to trigger abstention, and Phase 11 (UI) displays it as a specific
    state (not just an empty card).
    """
    kpi_name: str
    category: Optional[str]      # None for aggregate KPI, category name for per-category
    grain: str                   # "daily" or "monthly"
    data_points_available: int
    data_points_required: int
    message: str                 # human-readable explanation
    latest_date: Optional[str] = None   # most recent data point date
    earliest_date: Optional[str] = None # first data point date

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DetectionResult:
    """
    Container for the full output of the detection engine.

    Downstream modules (confidence, decomposition, narration, UI) should
    consume this rather than raw anomaly lists, because it separates:
      - anomalies: material KPI movements that were detected
      - sparse_history_flags: KPIs/categories where detection couldn't run
        due to insufficient history (explicit state, not just absence)
    """
    anomalies: list[AnomalyResult]
    sparse_history_flags: list[SparseHistoryFlag]

    def get_anomalies_for_kpi(self, kpi_name: str) -> list[AnomalyResult]:
        return [a for a in self.anomalies if a.kpi_name == kpi_name]

    def get_sparse_flags_for_kpi(self, kpi_name: str) -> list[SparseHistoryFlag]:
        return [f for f in self.sparse_history_flags if f.kpi_name == kpi_name]

    def is_sparse(self, kpi_name: str, category: Optional[str] = None) -> bool:
        """
        Check if a KPI has a sparse-history flag.

        Args:
            kpi_name: KPI to check.
            category: If None, checks for aggregate-level sparsity only.
                      If a category name, checks for that specific category.
        """
        for f in self.sparse_history_flags:
            if f.kpi_name == kpi_name and f.category == category:
                return True
        return False

    def has_any_sparse(self, kpi_name: str) -> bool:
        """Check if a KPI has ANY sparse-history flag (aggregate or per-category)."""
        return any(f.kpi_name == kpi_name for f in self.sparse_history_flags)


# ============================================================
# KPI time-series preparation
# ============================================================


def prepare_daily_kpi(
    sales_df: pd.DataFrame,
    kpi_name: str,
) -> pd.DataFrame:
    """
    Aggregate sales_transactions into a daily KPI time series.

    Returns DataFrame with columns: [date, value]
    """
    df = sales_df.copy()
    df["date"] = pd.to_datetime(df["date"])

    if kpi_name == "Revenue":
        daily = df.groupby("date")["revenue"].sum().reset_index()
        daily.columns = ["date", "value"]

    elif kpi_name == "Units Sold":
        daily = df.groupby("date")["units_sold"].sum().reset_index()
        daily.columns = ["date", "value"]

    elif kpi_name == "Gross Margin %":
        daily = df.groupby("date").agg(
            total_revenue=("revenue", "sum"),
            total_cost=("cost", "sum"),
        ).reset_index()
        daily["value"] = (
            (daily["total_revenue"] - daily["total_cost"])
            / daily["total_revenue"] * 100
        )
        daily = daily[["date", "value"]]

    else:
        raise ValueError(f"Unknown daily KPI: {kpi_name}")

    return daily.sort_values("date").reset_index(drop=True)


def prepare_monthly_churn(
    roster_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute monthly churn rate + data completeness from customer_roster.

    Returns DataFrame with columns: [month, value, data_completeness, total_records, null_records]
    """
    df = roster_df.copy()
    rows = []

    for month in sorted(df["month"].unique()):
        m_df = df[df["month"] == month]
        total = len(m_df)
        null_count = m_df["status"].isna().sum()
        non_null = m_df[m_df["status"].notna()]
        churned = (non_null["status"] == "churned").sum()
        completeness = (total - null_count) / total if total > 0 else 0.0
        churn_rate = (churned / len(non_null) * 100) if len(non_null) > 0 else 0.0

        rows.append({
            "month": month,
            "value": round(churn_rate, 2),
            "data_completeness": round(completeness, 4),
            "total_records": total,
            "null_records": null_count,
        })

    return pd.DataFrame(rows)


# ============================================================
# Anomaly detection: Rolling Z-Score (daily KPIs)
# ============================================================


def _detect_daily_anomalies(
    kpi_series: pd.DataFrame,
    kpi_name: str,
    contract: ContractStore,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    zscore_threshold: float = DEFAULT_ZSCORE_THRESHOLD,
    contract_kpi_name: Optional[str] = None,
) -> list[AnomalyResult]:
    """
    Detect anomalies in a daily KPI series using rolling z-scores.

    For each day, compute:
      z = (value - rolling_mean) / rolling_std

    Flag as anomaly if |z| > threshold AND materiality conditions are met.

    Args:
        contract_kpi_name: If set, use this name for contract lookups
            (thresholds, sparse history) instead of kpi_name. Useful for
            per-category detection where kpi_name is 'Revenue [Apparel]'
            but thresholds come from 'Revenue'.
    """
    results = []
    lookup_name = contract_kpi_name or kpi_name
    mat = contract.get_materiality(lookup_name)
    pct_threshold = mat["pct_change"]
    abs_threshold = mat.get("absolute_impact")

    df = kpi_series.copy()
    df = df.sort_values("date").reset_index(drop=True)

    # Compute rolling statistics (excluding the current point)
    df["rolling_mean"] = df["value"].rolling(
        window=rolling_window, min_periods=MIN_WINDOW_POINTS
    ).mean().shift(1)

    df["rolling_std"] = df["value"].rolling(
        window=rolling_window, min_periods=MIN_WINDOW_POINTS
    ).std().shift(1)

    # Z-score
    df["z_score"] = np.where(
        df["rolling_std"] > 0,
        (df["value"] - df["rolling_mean"]) / df["rolling_std"],
        0.0,
    )

    # Percent change vs rolling mean
    df["pct_change"] = np.where(
        df["rolling_mean"] > 0,
        ((df["value"] - df["rolling_mean"]) / df["rolling_mean"]) * 100,
        0.0,
    )

    df["abs_change"] = df["value"] - df["rolling_mean"]

    # Check sparse history for the overall KPI
    sparse_config = contract.get_sparse_history_config()
    min_days = sparse_config.get("daily_kpi_min_days", 21)
    lookup_name = contract_kpi_name or kpi_name

    for idx, row in df.iterrows():
        # Skip rows without enough baseline data
        if pd.isna(row["rolling_mean"]):
            continue

        z = row["z_score"]
        pct = row["pct_change"]
        abs_chg = row["abs_change"]

        # --- Z-score gate ---
        if abs(z) < zscore_threshold:
            continue

        # --- Materiality filter ---
        pct_material = abs(pct) >= pct_threshold
        abs_material = (
            abs_threshold is not None
            and abs_threshold is not None
            and abs(abs_chg) >= abs_threshold
        )

        # Must pass EITHER threshold to be considered material
        is_material = pct_material or abs_material

        if not is_material:
            continue

        # Check if there's enough history up to this point
        data_points = idx  # number of prior days available
        insufficient = data_points < min_days

        direction = "increase" if abs_chg > 0 else "decrease"
        date_str = row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"])

        results.append(AnomalyResult(
            kpi_name=kpi_name,
            period=date_str,
            period_type="daily",
            current_value=round(row["value"], 2),
            baseline_value=round(row["rolling_mean"], 2),
            baseline_std=round(row["rolling_std"], 4),
            absolute_change=round(abs_chg, 2),
            pct_change=round(pct, 2),
            z_score=round(z, 2),
            direction=direction,
            is_material=True,
            materiality_details={
                "pct_change_threshold": pct_threshold,
                "pct_change_actual": round(abs(pct), 2),
                "pct_material": pct_material,
                "abs_impact_threshold": abs_threshold,
                "abs_impact_actual": round(abs(abs_chg), 2),
                "abs_material": abs_material,
            },
            detection_method="rolling_zscore",
            data_points_used=data_points,
            insufficient_history=insufficient,
        ))

    return results


# ============================================================
# Anomaly detection: Period-over-period (monthly KPIs)
# ============================================================


def _detect_monthly_anomalies(
    churn_series: pd.DataFrame,
    kpi_name: str,
    contract: ContractStore,
) -> list[AnomalyResult]:
    """
    Detect anomalies in the monthly churn rate using period-over-period comparison.

    With only 3 months of data, rolling z-scores aren't meaningful.
    Instead, compare each month to the prior month and flag if the
    change exceeds the materiality threshold.
    """
    results = []
    mat = contract.get_materiality(kpi_name)
    pct_threshold = mat["pct_change"]  # This is in percentage points for churn

    sparse_config = contract.get_sparse_history_config()
    min_months = sparse_config.get("monthly_kpi_min_months", 3)

    df = churn_series.sort_values("month").reset_index(drop=True)

    for idx in range(1, len(df)):
        current = df.iloc[idx]
        prior = df.iloc[idx - 1]

        current_val = current["value"]
        prior_val = prior["value"]
        abs_change = current_val - prior_val

        # For percentage metrics, "pct_change" is in percentage points
        pct_change = abs_change  # already in pp for a % metric

        # For relative change (used for z-score-like comparison with 3 months)
        # Compute z-score if we have ≥2 prior months
        z_score = None
        if idx >= 2:
            prior_values = df["value"].iloc[:idx].values
            mean = np.mean(prior_values)
            std = np.std(prior_values, ddof=1) if len(prior_values) > 1 else 0
            if std > 0:
                z_score = round((current_val - mean) / std, 2)

        # Materiality: does the pp change exceed the threshold?
        is_material = abs(pct_change) >= pct_threshold

        if not is_material:
            continue

        # Check sparse history
        months_available = idx + 1  # including current
        insufficient = months_available < min_months

        direction = "increase" if abs_change > 0 else "decrease"

        results.append(AnomalyResult(
            kpi_name=kpi_name,
            period=current["month"],
            period_type="monthly",
            current_value=round(current_val, 2),
            baseline_value=round(prior_val, 2),
            baseline_std=None,
            absolute_change=round(abs_change, 2),
            pct_change=round(pct_change, 2),
            z_score=z_score,
            direction=direction,
            is_material=True,
            materiality_details={
                "pct_change_threshold_pp": pct_threshold,
                "pct_change_actual_pp": round(abs(pct_change), 2),
                "pct_material": True,
            },
            detection_method="period_over_period",
            data_points_used=idx,
            insufficient_history=insufficient,
            data_completeness=round(current["data_completeness"], 4),
        ))

    return results


# ============================================================
# Priority ranking
# ============================================================


def _rank_anomalies(anomalies: list[AnomalyResult]) -> list[AnomalyResult]:
    """
    Rank detected anomalies by priority (most severe first).

    Priority score = |z_score| * materiality_pct * recency_weight
    For monthly KPIs without z-scores, use pct_change as a proxy.
    """
    def _score(a: AnomalyResult) -> float:
        z = abs(a.z_score) if a.z_score is not None else abs(a.pct_change) / 2
        pct = abs(a.pct_change)
        return z * max(pct, 1.0)

    return sorted(anomalies, key=_score, reverse=True)


# ============================================================
# Main entry point
# ============================================================


def check_sparse_history(
    sales_df: pd.DataFrame,
    roster_df: pd.DataFrame,
    contract: ContractStore,
) -> list[SparseHistoryFlag]:
    """
    Scan all KPIs and per-category series for insufficient history.

    Returns explicit SparseHistoryFlag objects for every KPI or category
    where there aren't enough data points to establish a reliable baseline.
    This is distinct from "no anomaly found" — it's an explicit state that
    downstream modules (confidence, UI) key off.
    """
    flags: list[SparseHistoryFlag] = []
    sparse_config = contract.get_sparse_history_config()
    min_daily = sparse_config.get("daily_kpi_min_days", 21)
    min_monthly = sparse_config.get("monthly_kpi_min_months", 3)
    sparse_label = sparse_config.get(
        "label", "Insufficient history — cannot reliably assess this KPI movement."
    )

    df = sales_df.copy()
    df["date"] = pd.to_datetime(df["date"])

    # --- Check aggregate daily KPIs ---
    daily_kpis = ["Revenue", "Units Sold", "Gross Margin %"]
    for kpi_name in daily_kpis:
        series = prepare_daily_kpi(df, kpi_name)
        n_days = len(series)
        if n_days < min_daily:
            flags.append(SparseHistoryFlag(
                kpi_name=kpi_name,
                category=None,
                grain="daily",
                data_points_available=n_days,
                data_points_required=min_daily,
                message=sparse_label,
                earliest_date=str(series["date"].min())[:10],
                latest_date=str(series["date"].max())[:10],
            ))

    # --- Check per-category daily KPIs ---
    for cat in sorted(df["product_category"].unique()):
        cat_df = df[df["product_category"] == cat]
        n_days = cat_df["date"].nunique()
        if n_days < min_daily:
            cat_dates = sorted(cat_df["date"].unique())
            for kpi_name in daily_kpis:
                flags.append(SparseHistoryFlag(
                    kpi_name=kpi_name,
                    category=cat,
                    grain="daily",
                    data_points_available=n_days,
                    data_points_required=min_daily,
                    message=f"{sparse_label} Category '{cat}' has only {n_days} days of data.",
                    earliest_date=str(cat_dates[0])[:10],
                    latest_date=str(cat_dates[-1])[:10],
                ))

    # --- Check monthly KPIs ---
    roster = roster_df.copy()
    n_months = roster["month"].nunique()
    if n_months < min_monthly:
        flags.append(SparseHistoryFlag(
            kpi_name="Customer Churn Rate",
            category=None,
            grain="monthly",
            data_points_available=n_months,
            data_points_required=min_monthly,
            message=sparse_label,
            earliest_date=roster["month"].min(),
            latest_date=roster["month"].max(),
        ))

    return flags


def run_detection(
    sales_df: pd.DataFrame,
    roster_df: pd.DataFrame,
    contract: ContractStore,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    zscore_threshold: float = DEFAULT_ZSCORE_THRESHOLD,
) -> DetectionResult:
    """
    Run anomaly detection across all KPIs.

    Returns a DetectionResult containing:
      - anomalies: priority-ranked list of AnomalyResults (most severe first)
      - sparse_history_flags: explicit flags for KPIs/categories with
        insufficient history (distinct from "no anomaly found")
    """
    all_anomalies: list[AnomalyResult] = []

    # --- Daily KPIs from sales_transactions ---
    daily_kpis = ["Revenue", "Units Sold", "Gross Margin %"]
    for kpi_name in daily_kpis:
        series = prepare_daily_kpi(sales_df, kpi_name)
        anomalies = _detect_daily_anomalies(
            series, kpi_name, contract, rolling_window, zscore_threshold
        )
        all_anomalies.extend(anomalies)

    # --- Monthly KPIs from customer_roster ---
    churn_series = prepare_monthly_churn(roster_df)
    churn_anomalies = _detect_monthly_anomalies(
        churn_series, "Customer Churn Rate", contract
    )
    all_anomalies.extend(churn_anomalies)

    # Rank by severity
    ranked = _rank_anomalies(all_anomalies)

    # --- Check sparse history ---
    sparse_flags = check_sparse_history(sales_df, roster_df, contract)

    return DetectionResult(
        anomalies=ranked,
        sparse_history_flags=sparse_flags,
    )


# ============================================================
# Convenience: per-category detection (for decomposition prep)
# ============================================================


def detect_by_category(
    sales_df: pd.DataFrame,
    kpi_name: str,
    contract: ContractStore,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    zscore_threshold: float = DEFAULT_ZSCORE_THRESHOLD,
) -> dict[str, list[AnomalyResult]]:
    """
    Run anomaly detection per product_category for a daily sales KPI.

    Returns: {category_name: [AnomalyResult, ...]}
    Useful for decomposition to identify which categories drove an aggregate anomaly.
    """
    df = sales_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    results_by_cat: dict[str, list[AnomalyResult]] = {}

    for cat in sorted(df["product_category"].unique()):
        cat_df = df[df["product_category"] == cat]

        if kpi_name == "Revenue":
            cat_series = cat_df.groupby("date")["revenue"].sum().reset_index()
            cat_series.columns = ["date", "value"]
        elif kpi_name == "Units Sold":
            cat_series = cat_df.groupby("date")["units_sold"].sum().reset_index()
            cat_series.columns = ["date", "value"]
        elif kpi_name == "Gross Margin %":
            cat_agg = cat_df.groupby("date").agg(
                rev=("revenue", "sum"), cost=("cost", "sum")
            ).reset_index()
            cat_agg["value"] = (cat_agg["rev"] - cat_agg["cost"]) / cat_agg["rev"] * 100
            cat_series = cat_agg[["date", "value"]]
        else:
            continue

        cat_series = cat_series.sort_values("date").reset_index(drop=True)

        # Use a smaller threshold for category-level detection
        # to catch movements that are diluted at aggregate level
        anomalies = _detect_daily_anomalies(
            cat_series,
            f"{kpi_name} [{cat}]",
            contract,
            rolling_window,
            zscore_threshold=max(1.5, zscore_threshold - 0.5),
            contract_kpi_name=kpi_name,  # use base KPI name for threshold lookups
        )
        if anomalies:
            results_by_cat[cat] = anomalies

    return results_by_cat
