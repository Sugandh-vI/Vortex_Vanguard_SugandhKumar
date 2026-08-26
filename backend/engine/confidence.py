"""
Confidence Scoring & Abstention Engine
======================================

Phase 5. Assigns High / Medium / Low / Abstain confidence to every
detected anomaly, plus explicit abstain / "insufficient history" outcomes
for sparse KPIs and categories (e.g. the newly launched "Sports &
Outdoors" category).

Inputs — all pre-computed by deterministic code (no LLM):
  - AnomalyResult           (engine/detection.py)
  - DecompositionResult     (engine/decomposition.py)
  - SparseHistoryFlag       (engine/detection.py)
  - source_freshness dict   (engine/reconciliation.py)
  - ContractStore           (contracts/loader.py)

Confidence rests on three dimensions, all with thresholds taken from the
semantic contract (kpi_contracts.yaml → confidence.levels):

  1. Business-explained %   — NOT the arithmetic explained %. PVM sums to
     100% by construction, but that only means every dollar is accounted
     for; it does NOT mean we know the business cause. The Week 7 price
     cut is a known cause; the volume drop is measured but its cause
     (competitor promo) is not in our data. Drivers therefore carry an
     attribution weight (see ATTRIBUTION below) and the business-explained
     % is the weighted share of the movement whose cause is actually known.
  2. Data freshness          — staleness hours of the KPI's primary source
     (from reconciliation), compared to each level's max staleness.
  3. History depth           — number of prior periods, compared to each
     level's min history (days for daily KPIs, months for monthly KPIs).

Abstain triggers (checked first; ANY hit → Abstain, no score):
  - data completeness below the KPI's data_quality_requirements minimum
    (e.g. June churn: 70.2% < 90% → abstain),
  - insufficient history (detection's sparse-history minimum: 21 days for
    daily KPIs, 3 months for monthly KPIs),
  - contradictory signals (opposing quantified drivers of similar
    magnitude — future-proofing hook, not triggered by current data).

Level determination is top-down: a KPI is High only if it meets ALL of
High's criteria, else Medium, else Low, else Low (floor). The numerical
`score` is the weakest-link (minimum) of the three dimension scores, so
it can never exceed the dimension that is most limiting.

Usage:
    from engine.confidence import analyze
    results = analyze(sales_df, marketing_df, roster_df, store)
    # -> ConfidenceResultSet
"""

from __future__ import annotations

import sys
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from contracts.loader import ContractStore
from engine.detection import (
    AnomalyResult,
    DetectionResult,
    SparseHistoryFlag,
    run_detection,
)
from engine.decomposition import DecompositionResult, DriverContribution, decompose_all
from engine.reconciliation import reconcile


# ============================================================
# Driver attribution weights (business-explained %)
# ============================================================
#
# Deterministic heuristic mapping (analytical_method, component) ->
# "how much of this driver's contribution reflects a KNOWN business
# cause, as opposed to a measured-but-unexplained movement":
#
#   1.0  CAUSAL      — we know the cause from the data (a price change is
#                      a directly observed, controllable business event).
#   0.5  MEASURED    — the movement is quantified and localized, but the
#                      underlying cause is unknown (volume drop, category
#                      contribution deltas, cost/mix residual).
#   0.0  INFO        — informational, mechanical, or non-causal (mix
#                      interaction term, correlation, cohorts, completeness).
#
# These weights are deliberately coarse and proto-visible; they implement
# the design decision recorded in the Phase 4 log: "PVM explains 100%
# mathematically ... but the volume drop itself is the 'unexplained' part
# in business terms ... Phase 5 will mark this as medium confidence due to
# the unexplained volume driver."

ATTRIBUTION_WEIGHTS: dict[tuple[str, str], float] = {
    ("price_volume_mix", "price_effect"): 1.0,       # known cause (price cut)
    ("price_volume_mix", "volume_effect"): 0.5,      # measured, cause unknown
    ("price_volume_mix", "mix_interaction"): 0.0,    # mechanical interaction
    ("margin_decomposition", "unit_price"): 1.0,     # price cut → margin
    ("margin_decomposition", "unit_cost"): 0.5,      # cost/mix residual
    ("contribution", "category"): 0.5,               # localized, cause unknown
    ("correlation", ""): 0.0,                        # supporting signal only
    ("data_quality_check", ""): 0.0,                 # meta-driver
    ("cohort_analysis", ""): 0.0,                    # informational
    ("time_series", ""): 0.0,                        # seasonality pattern
}

DEFAULT_ATTRIBUTION_WEIGHT = 0.5   # quantified & localized, cause unknown

# Minimum share (of gross driver |sum|) each opposing side needs before we
# call the driver signals "contradictory"; and the net/gross ratio below
# which they are considered to cancel out.
CONTRADICTION_MIN_SIDE_SHARE = 0.20
CONTRADICTION_MAX_NET_GROSS = 0.50


# ============================================================
# Data structures
# ============================================================

# Status vocabulary
STATUS_HIGH = "high"
STATUS_MEDIUM = "medium"
STATUS_LOW = "low"
STATUS_ABSTAIN = "abstain"
VALID_STATUSES = {STATUS_HIGH, STATUS_MEDIUM, STATUS_LOW, STATUS_ABSTAIN}

# Machine-readable abstain reason codes
ABSTAIN_DATA_QUALITY = "data_completeness_below_threshold"
ABSTAIN_INSUFFICIENT_HISTORY = "insufficient_history"
ABSTAIN_CONTRADICTORY = "contradictory_signals"


@dataclass
class ConfidenceResult:
    """
    Confidence assessment for one anomaly (or one sparse-history flag).

    `status` is authoritative (driven by the contract thresholds);
    `score` (0-100) is the weakest-link dimension score for display/ranking.
    """

    kpi_name: str
    period: Optional[str]                # anomaly period or sparse flag latest date
    category: Optional[str]              # None for aggregate; category for per-category
    status: str                          # high | medium | low | abstain
    score: Optional[float] = None        # None for abstain
    business_explained_pct: Optional[float] = None   # weighted, cause-known share
    arithmetic_explained_pct: Optional[float] = None # raw decomposition explained %
    data_staleness_hours: Optional[float] = None
    history_points: Optional[int] = None
    history_unit: Optional[str] = None   # "days" | "months"
    history_required: Optional[int] = None  # sparse-history minimum (abstain bar)
    data_completeness: Optional[float] = None
    level_thresholds: dict = field(default_factory=dict)  # per-level criteria + passed
    attribution_detail: list = field(default_factory=list)  # per-driver weight trace
    reasons: list = field(default_factory=list)   # human-readable
    abstain_reasons: list = field(default_factory=list)  # machine codes
    insufficient_history: bool = False
    contradiction_detail: Optional[dict] = None
    message: str = ""

    def to_dict(self) -> dict:
        """Convert to a plain dict for JSON serialization."""
        return asdict(self)


@dataclass
class ConfidenceResultSet:
    """Container for all confidence results from one analysis run."""

    results: list[ConfidenceResult] = field(default_factory=list)

    def get_status(self, kpi_name: str, category: Optional[str] = None) -> Optional[str]:
        """Status for a KPI (+ optional category). Returns None if unknown."""
        for r in self.results:
            if r.kpi_name == kpi_name and r.category == category:
                return r.status
        return None

    def get_results_for_kpi(self, kpi_name: str) -> list[ConfidenceResult]:
        return [r for r in self.results if r.kpi_name == kpi_name]

    def get_abstained(self) -> list[ConfidenceResult]:
        return [r for r in self.results if r.status == STATUS_ABSTAIN]

    def get_scored(self) -> list[ConfidenceResult]:
        return [r for r in self.results if r.status != STATUS_ABSTAIN]

    def to_dict(self) -> list[dict]:
        return [r.to_dict() for r in self.results]


# ============================================================
# Attribution weight lookup
# ============================================================


def _driver_attribution_weight(driver: DriverContribution) -> float:
    """Return the attribution weight for a single driver contribution."""
    method = driver.analytical_method
    component = ""
    if isinstance(driver.detail, dict):
        component = str(driver.detail.get("component", ""))

    # contribution / margin decomposition carry component info; for
    # contribution the component is absent ("category" is in detail), so
    # key on the method alone.
    if method == "price_volume_mix":
        return ATTRIBUTION_WEIGHTS.get(
            (method, component),
            DEFAULT_ATTRIBUTION_WEIGHT,
        )
    if method == "margin_decomposition":
        if driver.driver_name == "unit_price":
            return ATTRIBUTION_WEIGHTS[(method, "unit_price")]
        return ATTRIBUTION_WEIGHTS[(method, "unit_cost")]
    if method in ("contribution",):
        return ATTRIBUTION_WEIGHTS[(method, "category")]
    return ATTRIBUTION_WEIGHTS.get((method, ""), DEFAULT_ATTRIBUTION_WEIGHT)


# ============================================================
# Business-explained % (weighted by attribution)
# ============================================================


def compute_business_explained_pct(
    decomposition: DecompositionResult,
) -> tuple[float, list[dict]]:
    """
    Compute the business-explained % of the movement.

    Weighted signed sum of driver contributions by attribution weight,
    normalized by |total movement|. Returns (business_explained_pct,
    attribution_detail) with the per-driver trace for transparency.
    """
    total = float(decomposition.total_movement)
    detail: list[dict] = []
    if total == 0:
        return 0.0, detail

    weighted_sum = 0.0
    for d in decomposition.drivers:
        w = _driver_attribution_weight(d)
        contribution = float(d.contribution_value)
        weighted_sum += contribution * w
        detail.append({
            "driver_name": d.driver_name,
            "analytical_method": d.analytical_method,
            "component": str(d.detail.get("component", "")) if isinstance(d.detail, dict) else "",
            "contribution_value": round(contribution, 4),
            "attribution_weight": w,
            "weighted_contribution": round(contribution * w, 4),
        })

    pct = abs(weighted_sum) / abs(total) * 100
    return round(min(100.0, float(pct)), 1), detail


# ============================================================
# Contradictory-signal detection (future-proofing hook)
# ============================================================


def _detect_contradiction(
    drivers: list[DriverContribution],
    total_movement: float,
) -> Optional[dict]:
    """
    Detect contradictory driver signals.

    Returns a detail dict if two opposing quantified drivers are each a
    material share (>= CONTRADICTION_MIN_SIDE_SHARE) of the gross driver
    magnitude AND their net is small relative to gross
    (< CONTRADICTION_MAX_NET_GROSS). Otherwise None.
    """
    quant = [
        d for d in drivers
        if d.analytical_method not in ("correlation", "data_quality_check", "cohort_analysis")
        and abs(float(d.contribution_value)) > 1e-9
    ]
    if len(quant) < 2:
        return None

    gross = sum(abs(float(d.contribution_value)) for d in quant)
    if gross <= 0:
        return None

    pos = [d for d in quant if float(d.contribution_value) > 0]
    neg = [d for d in quant if float(d.contribution_value) < 0]
    if not pos or not neg:
        return None

    pos_share = sum(abs(float(d.contribution_value)) for d in pos) / gross
    neg_share = sum(abs(float(d.contribution_value)) for d in neg) / gross
    net = abs(sum(float(d.contribution_value) for d in quant))

    if pos_share >= CONTRADICTION_MIN_SIDE_SHARE and neg_share >= CONTRADICTION_MIN_SIDE_SHARE \
            and net / gross < CONTRADICTION_MAX_NET_GROSS:
        return {
            "gross_driver_abs_sum": round(float(gross), 2),
            "net_driver_sum": round(float(sum(float(d.contribution_value) for d in quant)), 2),
            "net_gross_ratio": round(float(net / gross), 3),
            "positive_share": round(float(pos_share), 3),
            "negative_share": round(float(neg_share), 3),
            "note": "Opposing quantified drivers of similar magnitude — signals are contradictory.",
        }
    return None


# ============================================================
# Level determination (top-down, contract thresholds)
# ============================================================


def _determine_level(
    business_pct: float,
    staleness_hours: Optional[float],
    history_points: int,
    is_monthly: bool,
    levels: dict,
) -> tuple[str, dict]:
    """
    Determine High/Medium/Low by testing each level top-down.

    A level is reached only if ALL of its criteria pass:
      min_explained_pct, max_data_staleness_hours, min_history_*.
    Freshness is treated as a pass when unknown (None) — recorded as such.
    """
    checks: dict[str, dict] = {}
    for name in (STATUS_HIGH, STATUS_MEDIUM, STATUS_LOW):
        cfg = levels.get(name, {})
        h_key = "min_history_months" if is_monthly else "min_history_days"
        explained_ok = business_pct >= float(cfg.get("min_explained_pct", 0))
        staleness_max = cfg.get("max_data_staleness_hours")
        freshness_ok = staleness_hours is None or (
            staleness_max is not None and staleness_hours <= float(staleness_max)
        )
        history_min = cfg.get(h_key)
        history_ok = history_min is None or history_points >= int(history_min)

        checks[name] = {
            "min_explained_pct": float(cfg.get("min_explained_pct", 0)),
            "max_data_staleness_hours": (
                float(staleness_max) if staleness_max is not None else None
            ),
            h_key: int(history_min) if history_min is not None else None,
            "passed": bool(explained_ok and freshness_ok and history_ok),
        }
        if checks[name]["passed"]:
            return name, checks

    return STATUS_LOW, checks  # Low is the floor; no separate "below low" state


# ============================================================
# Dimension scores (weakest-link `score`)
# ============================================================


def _dimension_scores(
    business_pct: float,
    staleness_hours: Optional[float],
    history_points: int,
    is_monthly: bool,
    levels: dict,
) -> tuple[float, float, float]:
    """
    Compute explained / freshness / history dimension scores (0-100).

    Freshness scale: linear from 100 (0h) to 0 (>= 720h, the Low level's
    max staleness). History scale: linear from 0 to 100 at the High
    level's minimum history.
    """
    explained_score = min(100.0, float(business_pct))
    if staleness_hours is None:
        freshness_score = 100.0  # unknown freshness treated as neutral
    else:
        freshness_score = min(
            100.0,
            max(0.0, 100.0 * (1.0 - float(staleness_hours) / 720.0)),
        )

    high_cfg = levels.get(STATUS_HIGH, {})
    h_key = "min_history_months" if is_monthly else "min_history_days"
    high_req = float(high_cfg.get(h_key, 30 if not is_monthly else 3))
    history_score = min(100.0, max(0.0, history_points / high_req * 100.0)) if high_req > 0 else 100.0

    return (
        round(float(explained_score), 1),
        round(float(freshness_score), 1),
        round(float(history_score), 1),
    )


# ============================================================
# Single-anomaly scoring
# ============================================================


def _staleness_for_kpi(anomaly: AnomalyResult, contract: ContractStore,
                       source_freshness: dict) -> Optional[float]:
    """Staleness hours for the KPI's primary source, or None if unknown."""
    kpi_meta = contract.get_kpi(anomaly.kpi_name)
    sources = kpi_meta.get("source_tables") or []
    if not sources:
        return None
    src = sources[0]
    if src not in source_freshness:
        return None
    raw = source_freshness[src].get("staleness_hours")
    return float(raw) if raw is not None else None


def score_anomaly(
    anomaly: AnomalyResult,
    decomposition: Optional[DecompositionResult],
    contract: ContractStore,
    source_freshness: dict,
) -> ConfidenceResult:
    """
    Score a single anomaly into High / Medium / Low / Abstain.

    `decomposition` may be None defensively; absences are treated as
    zero business-explained (never as an error).
    """
    cfg = contract.get_confidence_config()
    levels = cfg.get("levels", {})
    sparse_cfg = contract.get_sparse_history_config()
    is_monthly = anomaly.period_type == "monthly"
    hist_key = "monthly_kpi_min_months" if is_monthly else "daily_kpi_min_days"
    hist_min = int(sparse_cfg.get(hist_key, 3 if is_monthly else 21))

    staleness = _staleness_for_kpi(anomaly, contract, source_freshness)
    # History depth = number of PRIOR periods available when the anomaly was
    # detected (this is the baseline the detection engine actually used, and
    # matches detection's own sparse-history bar).
    history_points = int(anomaly.data_points_used)
    history_unit = "months" if is_monthly else "days"

    completeness = None
    if anomaly.data_completeness is not None:
        completeness = float(anomaly.data_completeness)

    if decomposition is None:
        business_pct = 0.0
        arithmetic_pct = 0.0
        attr_detail: list[dict] = []
        drivers: list[DriverContribution] = []
    else:
        business_pct, attr_detail = compute_business_explained_pct(decomposition)
        arithmetic_pct = float(decomposition.explained_pct)
        drivers = decomposition.drivers

    # ---- Abstain triggers (ANY hit -> abstain) ----
    abstain_reasons: list[str] = []
    reason_msgs: list[str] = []

    dq = contract.get_data_quality_requirements(anomaly.kpi_name)
    if dq and completeness is not None:
        min_completeness = float(dq.get("min_completeness", 0.9))
        if completeness < min_completeness:
            abstain_reasons.append(ABSTAIN_DATA_QUALITY)
            reason_msgs.append(
                f"Data completeness {completeness * 100:.1f}% is below the "
                f"{min_completeness * 100:.0f}% required — the movement cannot be trusted."
            )

    if bool(anomaly.insufficient_history):
        abstain_reasons.append(ABSTAIN_INSUFFICIENT_HISTORY)
        reason_msgs.append(
            f"Baseline history is only {history_points} {history_unit} "
            f"(minimum {hist_min}) — cannot reliably assess this movement."
        )

    contradiction = _detect_contradiction(drivers, float(anomaly.absolute_change))
    if contradiction:
        abstain_reasons.append(ABSTAIN_CONTRADICTORY)
        reason_msgs.append(
            "Driver signals contradict each other — the explanation is not reliable."
        )

    if abstain_reasons:
        message = "Abstained: " + " ".join(reason_msgs)
        return ConfidenceResult(
            kpi_name=anomaly.kpi_name,
            period=anomaly.period,
            category=None,
            status=STATUS_ABSTAIN,
            score=None,
            business_explained_pct=business_pct,
            arithmetic_explained_pct=arithmetic_pct,
            data_staleness_hours=staleness,
            history_points=history_points,
            history_unit=history_unit,
            history_required=hist_min,
            data_completeness=completeness,
            level_thresholds={},
            attribution_detail=attr_detail,
            reasons=reason_msgs,
            abstain_reasons=abstain_reasons,
            insufficient_history=bool(anomaly.insufficient_history),
            contradiction_detail=contradiction,
            message=message,
        )

    # ---- Level determination ----
    status, checks = _determine_level(business_pct, staleness, history_points,
                                      is_monthly, levels)
    exp_score, fresh_score, hist_score = _dimension_scores(
        business_pct, staleness, history_points, is_monthly, levels
    )
    score = round(min(exp_score, fresh_score, hist_score), 1)

    staleness_txt = f"{staleness:.0f}h" if staleness is not None else "unknown"
    reasons = [
        f"Business-explained {business_pct:.1f}% of the movement (arithmetic: {arithmetic_pct:.1f}%)",
        f"Data staleness: {staleness_txt}",
        f"History depth: {history_points} {history_unit} of baseline",
    ]

    # Explain which (if any) higher level was capped by which criterion
    caps = []
    for name in (STATUS_HIGH, STATUS_MEDIUM):
        if name == status:
            break
        chk = checks.get(name, {})
        if chk and not chk.get("passed", True):
            cap_reasons = []
            if business_pct < float(chk.get("min_explained_pct", 0)):
                cap_reasons.append(
                    f"business-explained {business_pct:.1f}% < {chk['min_explained_pct']:.0f}%"
                )
            if staleness is not None and chk.get("max_data_staleness_hours") is not None \
                    and staleness > float(chk["max_data_staleness_hours"]):
                cap_reasons.append(f"staleness {staleness:.0f}h > {chk['max_data_staleness_hours']:.0f}h")
            if chk.get("min_history_days") is not None and not is_monthly \
                    and history_points < int(chk["min_history_days"]):
                cap_reasons.append(f"history {history_points}d < {chk['min_history_days']}d")
            if chk.get("min_history_months") is not None and is_monthly \
                    and history_points < int(chk["min_history_months"]):
                cap_reasons.append(f"history {history_points}mo < {chk['min_history_months']}mo")
            if cap_reasons:
                caps.append(f"below {name}: {', '.join(cap_reasons)}")
    if caps:
        reasons.append("Not " + "; ".join(caps))

    if status == STATUS_HIGH:
        message = (
            f"High confidence — {business_pct:.1f}% of the movement is business-explained, "
            f"data is fresh ({staleness_txt}) and history is sufficient ({history_points} {history_unit})."
        )
    elif status == STATUS_MEDIUM:
        message = (
            f"Medium confidence — {business_pct:.1f}% business-explained; "
            f"a material part of the movement is measured but its cause is unknown."
        )
    else:
        message = (
            f"Low confidence — only {business_pct:.1f}% of the movement is business-explained."
        )

    return ConfidenceResult(
        kpi_name=anomaly.kpi_name,
        period=anomaly.period,
        category=None,
        status=status,
        score=score,
        business_explained_pct=business_pct,
        arithmetic_explained_pct=arithmetic_pct,
        data_staleness_hours=staleness,
        history_points=history_points,
        history_unit=history_unit,
        history_required=hist_min,
        data_completeness=completeness,
        level_thresholds=checks,
        attribution_detail=attr_detail,
        reasons=reasons,
        abstain_reasons=[],
        insufficient_history=False,
        contradiction_detail=None,
        message=message,
    )


# ============================================================
# Sparse-history flags -> explicit abstain results
# ============================================================


def _score_sparse_flag(
    flag: SparseHistoryFlag,
    contract: ContractStore,
) -> ConfidenceResult:
    """Turn a SparseHistoryFlag into an explicit Abstain ConfidenceResult."""
    sparse_cfg = contract.get_sparse_history_config()
    label = sparse_cfg.get(
        "label", "Insufficient history — cannot reliably assess this KPI movement."
    )
    message = flag.message or label
    history_unit = "months" if flag.grain == "monthly" else "days"

    return ConfidenceResult(
        kpi_name=flag.kpi_name,
        period=flag.latest_date,
        category=flag.category,
        status=STATUS_ABSTAIN,
        score=None,
        business_explained_pct=None,
        arithmetic_explained_pct=None,
        data_staleness_hours=None,
        history_points=int(flag.data_points_available),
        history_unit=history_unit,
        history_required=int(flag.data_points_required),
        data_completeness=None,
        level_thresholds={},
        attribution_detail=[],
        reasons=[message],
        abstain_reasons=[ABSTAIN_INSUFFICIENT_HISTORY],
        insufficient_history=True,
        contradiction_detail=None,
        message=message,
    )


# ============================================================
# Batch scoring (entry point)
# ============================================================


def score_all(
    anomalies: list[AnomalyResult],
    decompositions: list[DecompositionResult],
    sparse_flags: list[SparseHistoryFlag],
    contract: ContractStore,
    source_freshness: dict,
) -> ConfidenceResultSet:
    """
    Score every anomaly and every sparse-history flag.

    Anomaly order is preserved (already priority-ranked by detection);
    sparse-history abstains are appended afterwards.
    """
    dec_by_key = {(d.kpi_name, d.period): d for d in decompositions}
    results: list[ConfidenceResult] = []
    for a in anomalies:
        dec = dec_by_key.get((a.kpi_name, a.period))
        results.append(score_anomaly(a, dec, contract, source_freshness))

    for flag in sparse_flags:
        results.append(_score_sparse_flag(flag, contract))

    return ConfidenceResultSet(results=results)


# ============================================================
# Convenience pipeline: detection -> reconciliation ->
# decomposition -> confidence
# ============================================================


def analyze(
    sales_df: pd.DataFrame,
    marketing_df: pd.DataFrame,
    roster_df: pd.DataFrame,
    contract: ContractStore,
    as_of_date: Optional[str] = None,
) -> ConfidenceResultSet:
    """
    Run the full deterministic pipeline and return confidence results.

    `as_of_date` defaults to the latest data date; it is used as the
    reference for source freshness (feed in demo's "current date" to
    simulate staleness).
    """
    detection: DetectionResult = run_detection(sales_df, roster_df, contract)
    rec = reconcile(sales_df, marketing_df, roster_df, window_end=as_of_date)
    decs = decompose_all(detection.anomalies, sales_df, marketing_df, roster_df, contract)
    return score_all(
        detection.anomalies,
        decs,
        detection.sparse_history_flags,
        contract,
        rec.source_freshness,
    )
