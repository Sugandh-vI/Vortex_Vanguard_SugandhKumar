"""
Action Recommendation Engine
============================

Phase 7. Deterministic driver → lever → action → expected impact →
owner → confidence → monitoring-plan recommendations, driven entirely
by the lookup/rules table in `contracts/action_rules.yaml`.

The LLM is NOT involved: the rules table provides lever/owner/action
text, the engine computes expected-impact math and inherits confidence
from Phase 5. Phase 8 narration will only render these results.

Matching design (no if/else chains):
  - Every rule is keyed by (kpi, driver, component, direction,
    categories) with `None` meaning "any".
  - For each DriverContribution the engine scores all candidate rules by
    SPECIFICITY — the number of specified matching fields (kpi, driver,
    component, direction, categories). The highest score wins; ties
    break by YAML declaration order.
  - Rules whose gates fail (min abs contribution / min contribution %)
    are excluded before scoring.
  - No match -> the `defaults` rule (investigate & monitor, not
    actionable). So every driver always resolves to a traceable
    recommendation.

Expected impact is math, not prose:
  expected_impact = |driver contribution| × recovery factor range
  (unit from the KPI materiality contract; percentage-point metrics stay
  in percentage points). Correlation / informational drivers carry
  `None` impact with an explicit note.

Confidence is inherited from Phase 5:
  - Scored anomalies (high/medium/low): the Phase 5 status + score and
    the driver's attribution weight are attached to each recommendation.
  - Abstained anomalies (e.g. June churn): business recommendations are
    marked `actionable: false` with an abstain note; operational
    data-quality recovery actions (repair the roster sync) stay
    actionable — fixing broken evidence is always safe to recommend.

Usage:
    from engine.actions import recommend_all, run_actions
    plan = run_actions(sales_df, marketing_df, roster_df, contract)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, asdict
from typing import Optional

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from contracts.action_rules_loader import ActionRulesStore
from contracts.loader import ContractStore
from engine.confidence import (
    ConfidenceResult,
    ConfidenceResultSet,
    STATUS_ABSTAIN,
    analyze,
)
from engine.decomposition import DecompositionResult, DriverContribution, decompose_all
from engine.detection import DetectionResult, run_detection
from engine.reconciliation import reconcile


# ============================================================
# Data structures
# ============================================================


@dataclass
class ActionRecommendation:
    """One driver → lever → action recommendation."""

    kpi_name: str
    period: str
    driver_name: str
    driver_type: str
    analytical_method: str
    component: Optional[str]          # price_effect / volume_effect / ...
    direction: str                    # driver movement direction
    category: Optional[str]           # category context (if any)
    contribution_value: float
    contribution_pct: float
    lever: str
    owner: str
    actions: list[str]
    expected_impact: Optional[dict]   # {value_min, value_max, unit, basis, note} | None
    monitoring_plan: list[str]
    actionable: bool
    confidence: dict                  # {status, score, attribution_weight, note}
    source_rule: str                  # action_rules.yaml#<rule_id>
    rationale: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SuggestionSet:
    """All recommendations for one anomaly, with its confidence context."""

    kpi_name: str
    period: str
    category: Optional[str] = None
    confidence_status: str = ""
    confidence_score: Optional[float] = None
    abstain_note: Optional[str] = None
    recommendations: list[ActionRecommendation] = field(default_factory=list)

    @property
    def has_actionable(self) -> bool:
        return any(r.actionable for r in self.recommendations)

    def to_dict(self) -> dict:
        return {
            "kpi_name": self.kpi_name,
            "period": self.period,
            "category": self.category,
            "confidence_status": self.confidence_status,
            "confidence_score": self.confidence_score,
            "abstain_note": self.abstain_note,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "has_actionable": self.has_actionable,
        }


@dataclass
class ActionPlan:
    """Full Phase 7 output for one analysis run."""

    sets: list[SuggestionSet] = field(default_factory=list)

    def get_set(self, kpi_name: str, period: str) -> Optional[SuggestionSet]:
        for s in self.sets:
            if s.kpi_name == kpi_name and s.period == period:
                return s
        return None

    @property
    def total_recommendations(self) -> int:
        return sum(len(s.recommendations) for s in self.sets)

    @property
    def actionable_count(self) -> int:
        return sum(
            1 for s in self.sets for r in s.recommendations if r.actionable
        )

    def to_dict(self) -> dict:
        return {
            "summary": {
                "anomalies_covered": len(self.sets),
                "total_recommendations": self.total_recommendations,
                "actionable_count": self.actionable_count,
            },
            "sets": [s.to_dict() for s in self.sets],
        }


# ============================================================
# Driver context extraction (category / cohort)
# ============================================================


def _driver_category(driver: DriverContribution) -> Optional[str]:
    """Category context for a driver, if any (contribution or PVM detail)."""
    detail = driver.detail if isinstance(driver.detail, dict) else {}
    cat = detail.get("category")
    if cat:
        return str(cat)

    # PVM: dominant category by the driver's own effect component
    component = str(detail.get("component", ""))
    effect_key = {
        "price_effect": "price_effect",
        "volume_effect": "volume_effect",
        "mix_interaction": "mix_effect",
    }.get(component)
    by_cat = detail.get("by_category")
    if effect_key and isinstance(by_cat, list) and by_cat:
        best = max(by_cat, key=lambda row: abs(float(row.get(effect_key, 0) or 0)))
        if abs(float(best.get(effect_key, 0) or 0)) > 0:
            return str(best["category"])
    return None


def _focus_cohort(driver: DriverContribution) -> Optional[tuple[str, float]]:
    """
    Highest-churn tenure cohort (among cohorts with >= 50 members), for
    the customer_tenure driver. Returns (bucket_label, churn_rate).
    """
    detail = driver.detail if isinstance(driver.detail, dict) else {}
    cohorts = detail.get("cohorts")
    if not isinstance(cohorts, list) or not cohorts:
        return None
    eligible = [c for c in cohorts if int(c.get("total", 0) or 0) >= 50]
    if not eligible:
        return None
    best = max(eligible, key=lambda c: float(c.get("churn_rate", 0) or 0))
    return str(best["bucket"]), float(best["churn_rate"])


# ============================================================
# Rule matching (specificity scoring — no if/else chains)
# ============================================================


def _rule_specificity(rule: dict, kpi: str, driver: DriverContribution,
                      category: Optional[str]) -> Optional[int]:
    """
    Return the specificity score of a rule for this driver, or None if the
    rule does not apply (a hard mismatch).

    Score = number of specified fields that match. Fields:
      kpi, driver, component, direction, categories.
    """
    score = 0

    if rule.get("kpi") != kpi:
        return None
    score += 1

    if rule.get("driver") != driver.driver_name:
        return None
    score += 1

    component = str(driver.detail.get("component", "")) if isinstance(driver.detail, dict) else ""
    rule_component = rule.get("component")
    if rule_component is not None:
        if rule_component != component:
            return None
        score += 1

    rule_direction = rule.get("direction")
    if rule_direction is not None:
        if rule_direction != driver.direction:
            return None
        score += 1

    rule_cats = rule.get("categories")
    if rule_cats:
        if category is None or category not in rule_cats:
            return None
        score += 1

    return score


def _passes_gates(rule: dict, driver: DriverContribution) -> bool:
    """Check a rule's contribution gates (abs value and % of movement)."""
    gates = rule.get("gates") or {}
    if not gates:
        return True

    abs_min = gates.get("min_abs_contribution")
    if abs_min is not None and abs(float(driver.contribution_value)) < float(abs_min):
        return False

    pct_min = gates.get("min_contribution_pct")
    if pct_min is not None and abs(float(driver.contribution_pct)) < float(pct_min):
        return False
    return True


def match_rule(
    kpi: str,
    driver: DriverContribution,
    rules_store: ActionRulesStore,
) -> tuple[dict, str]:
    """
    Select the best rule for a driver.

    Returns (rule_dict, source_reference) — `rule_dict` is the best
    matching rule or the store's defaults fallback.
    """
    category = _driver_category(driver)

    best: Optional[dict] = None
    best_score = -1
    for rule in rules_store.rules:
        score = _rule_specificity(rule, kpi, driver, category)
        if score is None or score <= best_score:
            continue
        if not _passes_gates(rule, driver):
            continue
        best = rule
        best_score = score

    if best is None:
        return rules_store.defaults, "action_rules.yaml#defaults"
    return best, f"action_rules.yaml#{best['id']}"


# ============================================================
# Rendering helpers (bounded token substitution only)
# ============================================================


def _render_text(text: str, context: dict) -> str:
    """Replace {token} placeholders with pre-computed context values."""
    out = text
    for key, value in context.items():
        if value is None:
            continue
        out = out.replace("{" + key + "}", str(value))
    return out


def _render_items(items: list, context: dict) -> list[str]:
    return [_render_text(str(i), context) for i in items]


# ============================================================
# Expected impact math
# ============================================================


def _expected_impact(
    rule: dict,
    driver: DriverContribution,
    contract: ContractStore,
    kpi: str,
) -> Optional[dict]:
    """Compute expected impact = |contribution| × recovery factors."""
    spec = rule.get("expected_impact") or {}
    recovery = spec.get("recovery")
    if not recovery:
        return {
            "value_min": None,
            "value_max": None,
            "unit": None,
            "basis": "not_quantified",
            "note": spec.get("note", "No quantified impact for this recommendation."),
        }

    magnitude = abs(float(driver.contribution_value))
    lo = round(magnitude * float(recovery["min"]), 2)
    hi = round(magnitude * float(recovery["max"]), 2)

    unit = contract.get_materiality(kpi).get("impact_unit", contract.get_unit(kpi))
    return {
        "value_min": lo,
        "value_max": hi,
        "unit": unit,
        "basis": "driver_contribution_x_recovery_factor",
        "note": spec.get("note", ""),
    }


# ============================================================
# Confidence inheritance (Phase 5)
# ============================================================


def _confidence_for_driver(
    confidence: ConfidenceResult,
    driver: DriverContribution,
) -> dict:
    """Attach the anomaly's Phase 5 confidence + driver attribution weight."""
    attribution_weight = None
    for item in confidence.attribution_detail or []:
        if item.get("driver_name") == driver.driver_name:
            attribution_weight = item.get("attribution_weight")
            break

    note = (
        "Anomaly abstained — this driver's quantified recommendation is "
        "NOT actionable until confidence is restored."
        if confidence.status == STATUS_ABSTAIN else ""
    )
    return {
        "status": confidence.status,
        "score": confidence.score,
        "attribution_weight": attribution_weight,
        "note": note,
    }


# ============================================================
# Per-anomaly recommendation
# ============================================================


def recommend_anomaly(
    kpi_name: str,
    period: str,
    decomposition: DecompositionResult,
    confidence: ConfidenceResult,
    rules_store: ActionRulesStore,
    contract: ContractStore,
) -> SuggestionSet:
    """Build the SuggestionSet for one anomaly from its decomposition."""
    abstain_note = None
    if confidence.status == STATUS_ABSTAIN:
        abstain_note = (
            "Evidence is insufficient (data quality / history / contradictory "
            "signals) — only operational recovery actions are recommended; "
            "business levers are not actionable until confidence is restored."
        )

    recommendations: list[ActionRecommendation] = []

    for driver in decomposition.drivers:
        rule, source = match_rule(kpi_name, driver, rules_store)
        category = _driver_category(driver)

        # Render context for text placeholders
        context: dict = {"category": category}
        if driver.driver_name == "customer_tenure":
            cohort = _focus_cohort(driver)
            if cohort:
                context["cohort"] = cohort[0]
                context["cohort_rate"] = round(cohort[1], 1)

        actions = _render_items(rule.get("actions", []), context)
        monitoring = _render_items(rule.get("monitoring", []), context)

        impact = _expected_impact(rule, driver, contract, kpi_name)

        # Abstain => business levers become non-actionable (operational
        # recovery rules, e.g. data quality, remain actionable).
        actionable = bool(rule.get("actionable", False))
        if confidence.status == STATUS_ABSTAIN:
            is_operational_recovery = driver.driver_name == "data_completeness"
            actionable = actionable and is_operational_recovery

        conf = _confidence_for_driver(confidence, driver)

        recommendations.append(ActionRecommendation(
            kpi_name=kpi_name,
            period=period,
            driver_name=driver.driver_name,
            driver_type=driver.driver_type,
            analytical_method=driver.analytical_method,
            component=str(driver.detail.get("component", "")) if isinstance(driver.detail, dict) else "",
            direction=driver.direction,
            category=category,
            contribution_value=round(float(driver.contribution_value), 4),
            contribution_pct=round(float(driver.contribution_pct), 1),
            lever=rule.get("lever", rules_store.defaults.get("lever", "Investigate & Monitor")),
            owner=rule.get("owner", rules_store.defaults.get("owner", "Analytics Owner")),
            actions=actions,
            expected_impact=impact,
            monitoring_plan=monitoring,
            actionable=actionable,
            confidence=conf,
            source_rule=source,
            rationale=(
                f"Driver '{driver.driver_name}' ({driver.analytical_method}) "
                f"matched rule {source}; contribution "
                f"{driver.contribution_value:+.2f} ({driver.contribution_pct:.1f}% "
                f"of the movement)."
            ),
        ))

    return SuggestionSet(
        kpi_name=kpi_name,
        period=period,
        category=None,
        confidence_status=confidence.status,
        confidence_score=confidence.score,
        abstain_note=abstain_note,
        recommendations=recommendations,
    )


# ============================================================
# Batch entry points
# ============================================================


def recommend_all(
    detection: DetectionResult,
    decompositions: list[DecompositionResult],
    confidence_set: ConfidenceResultSet,
    contract: ContractStore,
    rules_store: Optional[ActionRulesStore] = None,
) -> ActionPlan:
    """
    Build recommendations for every anomaly that has both a
    decomposition and a confidence result.

    Sparse-history flags (Sports & Outdoors) have no decomposition and
    therefore no recommendations — the Phase 5 abstain result is the
    complete output for those.
    """
    rules_store = rules_store or ActionRulesStore()
    dec_by_key = {(d.kpi_name, d.period): d for d in decompositions}
    conf_by_key = {}
    for c in confidence_set.results:
        conf_by_key[(c.kpi_name, c.period, c.category)] = c

    sets: list[SuggestionSet] = []
    for a in detection.anomalies:
        dec = dec_by_key.get((a.kpi_name, a.period))
        conf = conf_by_key.get((a.kpi_name, a.period, None))
        if dec is None or conf is None:
            continue
        sets.append(recommend_anomaly(a.kpi_name, a.period, dec, conf,
                                      rules_store, contract))

    return ActionPlan(sets=sets)


def run_actions(
    sales_df: pd.DataFrame,
    marketing_df: pd.DataFrame,
    roster_df: pd.DataFrame,
    contract: ContractStore,
    rules_store: Optional[ActionRulesStore] = None,
    as_of_date: Optional[str] = None,
) -> ActionPlan:
    """
    Full deterministic pipeline: detection → reconciliation →
    decomposition → confidence → action recommendations.
    """
    rules_store = rules_store or ActionRulesStore()
    detection = run_detection(sales_df, roster_df, contract)
    rec = reconcile(sales_df, marketing_df, roster_df, window_end=as_of_date)
    decompositions = decompose_all(
        detection.anomalies, sales_df, marketing_df, roster_df, contract
    )
    confidence_set = analyze(sales_df, marketing_df, roster_df, contract,
                             as_of_date=as_of_date)
    return recommend_all(detection, decompositions, confidence_set, contract,
                         rules_store)
