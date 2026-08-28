"""
Insight Feed Service — Phase 12
================================

Shared construction of the insight feed and KPI timeseries, used by BOTH:
  - the live API endpoints (backend/api/main.py), and
  - the sample snapshot exporter (backend/data/export_frontend_sample.py).

One code path for both — no duplicated feed logic to drift.

Everything here is deterministic pipeline output + Phase 6 access control.
Narration is performed through the passed `TelemetryCollector.narrate()`
(the caller decides which LLM client the collector uses via its env config),
so the LLM never contributes a number — it only turns the already-computed
structured facts into persona-specific prose, and every call is recorded
in telemetry (real vs mock, tokens, grounding outcome).

Feed ordering (Phase 12, per the Phase 9 design):
  scored insights are ranked by effective_rank = Phase-5 score x
  feedback_factor(kpi, confidence_level, persona), ties broken by
  pipeline order; abstains (score = None) sink to the bottom in pipeline
  order. With zero votes the factor is exactly 1.0, so a no-feedback feed
  is ranked by the Phase-5 score alone — deterministic and traceable.

Narration caching:
  `build_insights(..., narratives={insight_id: narrative_dict})` reuses any
  narrative already present in the dict and only calls the LLM for insights
  that are missing — so a feed rebuild after a feedback vote is pure
  re-ranking with zero additional LLM calls.
"""

import pandas as pd

from engine.access_control import PermissionGuard
from engine.detection import prepare_daily_kpi, prepare_monthly_churn
from engine.feedback import adjusted_score, feedback_factor, insight_id
from engine.telemetry import TelemetryCollector
from narration.llm_client import LLMClient
from narration.prompts import pipeline_to_facts


# ============================================================
# Timeseries (chart data + markers, all pipeline-derived)
# ============================================================

def build_timeseries(sales: pd.DataFrame, roster: pd.DataFrame, result: dict) -> dict:
    """Daily/monthly series + chart markers, all pipeline-derived."""
    detection = result["detection"]

    # Week-7 anomaly band: expand the min/max anomaly dates to the full
    # Mon-Sun week of the scripted event.
    event_dates = [
        a.period for a in detection.anomalies
        if a.kpi_name in ("Revenue", "Units Sold", "Gross Margin %")
        and a.period.startswith("2024-05-1")
    ]
    band = {}
    if event_dates:
        sd = pd.to_datetime(min(event_dates))
        se = pd.to_datetime(max(event_dates))
        band = {
            "type": "anomaly_band",
            "start": (sd - pd.Timedelta(days=sd.weekday())).strftime("%Y-%m-%d"),
            "end": (se - pd.Timedelta(days=se.weekday()) + pd.Timedelta(days=6)).strftime("%Y-%m-%d"),
            "label": "Week 7 event (scripted multi-factor dip)",
        }

    launch = {}
    for f in detection.sparse_history_flags:
        if f.category == "Sports & Outdoors" and f.earliest_date:
            launch = {"type": "launch", "date": f.earliest_date,
                      "label": f"{f.category} launch (sparse history)"}
            break

    def _points(series: pd.DataFrame, value_col: str = "value") -> list:
        return [
            {"date": str(r["date"])[:10], "value": round(float(r[value_col]), 2)}
            for _, r in series.iterrows()
        ]

    ts: dict = {}
    for kpi in ("Revenue", "Units Sold", "Gross Margin %"):
        entry = {
            "grain": "daily",
            "unit": "USD" if kpi == "Revenue" else ("units" if kpi == "Units Sold" else "percent"),
            "points": _points(prepare_daily_kpi(sales, kpi)),
            "markers": [m for m in (band, launch) if m],
        }
        if kpi == "Revenue":
            cat = (
                sales.groupby(["date", "product_category"])["revenue"].sum().reset_index()
            )
            entry["by_category"] = {
                c: [
                    {"date": str(r["date"])[:10], "value": round(float(r["revenue"]), 2)}
                    for _, r in g.iterrows()
                ]
                for c, g in cat.groupby("product_category")
            }
        ts[kpi] = entry

    churn = prepare_monthly_churn(roster)
    ts["Customer Churn Rate"] = {
        "grain": "monthly",
        "unit": "percent",
        "points": [
            {"period": r["month"], "value": round(float(r["value"]), 2)}
            for _, r in churn.iterrows()
        ],
        "completeness": {
            r["month"]: round(float(r["data_completeness"]), 4) for _, r in churn.iterrows()
        },
        "markers": [],
    }
    return ts


# ============================================================
# Insight feed (per persona)
# ============================================================

def _vote_counts(feedback_store, persona: str) -> dict:
    """Per-(kpi_name, confidence_status) vote counts for one persona."""
    counts: dict = {}
    if feedback_store is None:
        return counts
    for row in feedback_store.fetch(persona=persona):
        key = (row["kpi_name"], row["confidence_status"])
        e = counts.setdefault(key, {"up": 0, "down": 0})
        e["up" if row["rating"] == "up" else "down"] += 1
    return counts


def build_insights(
    persona: str,
    result: dict,
    collector: TelemetryCollector,
    feedback_store=None,
    narratives: dict | None = None,
) -> dict:
    """Access-filtered, narrated insight feed for one persona.

    `result` is the instrumented pipeline result dict (see
    engine.telemetry.instrument_pipeline). `narratives` is an optional
    cache dict (insight_id -> narrative dict); present entries are reused
    as-is, missing ones are narrated via collector.narrate() and stored.
    """
    conf: list = result["confidence"].results
    plan = result["actions"]
    anomaly_by = {(a.kpi_name, a.period, None): a for a in result["detection"].anomalies}
    if narratives is None:
        narratives = {}

    guard = PermissionGuard(persona, auto_log=False)
    votes = _vote_counts(feedback_store, persona)

    items: list = []
    blocked: dict = {}

    for orig_index, r in enumerate(conf):
        decision = guard.check_kpi(r.kpi_name, auto_log=False)
        if not decision.allowed:
            # Phase 6: dedupe — one blocked decision per KPI.
            blocked.setdefault(r.kpi_name, {
                "kpi_name": r.kpi_name,
                "decision": {
                    "action": decision.action,
                    "reason": decision.reason,
                    "source": decision.source,
                    "timestamp": decision.timestamp,
                },
            })
            continue

        iid = insight_id(r.kpi_name, str(r.period), r.category)
        anomaly = anomaly_by.get((r.kpi_name, r.period, r.category))
        sset = plan.get_set(r.kpi_name, r.period) if anomaly is not None else None

        # Drivers come from the decomposition (contribution + pct); the
        # attribution weight comes from the Phase 5 result.
        dec = next(
            (d for d in result["decomposition"]
             if d.kpi_name == r.kpi_name and d.period == r.period),
            None,
        )
        weights = {d["driver_name"]: d["attribution_weight"] for d in (r.attribution_detail or [])}
        drivers = [
            {
                "driver_name": d.driver_name,
                "contribution_value": d.contribution_value,
                "contribution_pct": d.contribution_pct,
                "analytical_method": d.analytical_method,
                "attribution_weight": weights.get(d.driver_name),
            }
            for d in (dec.drivers if dec is not None else [])
        ]

        recommendations = []
        if sset is not None:
            for rec in sset.recommendations:
                recommendations.append({
                    "driver_name": rec.driver_name,
                    "lever": rec.lever,
                    "owner": rec.owner,
                    "actions": rec.actions,
                    "expected_impact": rec.expected_impact,
                    "monitoring_plan": rec.monitoring_plan,
                    "actionable": rec.actionable,
                    "confidence_status": rec.confidence.get("status"),
                    "source_rule": rec.source_rule,
                })

        # --- narration (cached; LLM never touches the numbers above) ---
        narrative = narratives.get(iid)
        if narrative is None:
            facts = pipeline_to_facts(r, sset, anomaly, persona)
            resp, grounded, violations = collector.narrate(
                LLMClient.from_env(persona), facts, persona
            )
            narrative = {
                "text": resp.text,
                "provider": resp.provider,
                "model": resp.model,
                "mock": resp.mock,
                "grounded": grounded,
                "violations": violations,
                "persona": persona,
                "usage": resp.usage,
            }
            narratives[iid] = narrative

        # --- Phase 9 feedback factor (trust label, never evidence) ---
        abstain = str(r.status) == "abstain"
        v = votes.get((r.kpi_name, str(r.status)), {"up": 0, "down": 0})
        factor = None if abstain else feedback_factor(v["up"], v["down"])
        effective = (
            None if (abstain or r.score is None)
            else adjusted_score(r.score, factor)
        )

        items.append({
            "insight_id": iid,
            "rank": 0,  # assigned after ordering
            "kpi_name": r.kpi_name,
            "period": str(r.period),
            "category": r.category,
            "insufficient_history": bool(r.insufficient_history),
            "anomaly": (
                {
                    "baseline_value": anomaly.baseline_value,
                    "current_value": anomaly.current_value,
                    "absolute_change": anomaly.absolute_change,
                    "pct_change": anomaly.pct_change,
                    "z_score": anomaly.z_score,
                    "direction": anomaly.direction,
                    "data_points_used": anomaly.data_points_used,
                    "data_completeness": anomaly.data_completeness,
                }
                if anomaly is not None else None
            ),
            "confidence": {
                "status": r.status,
                "score": r.score,
                "business_explained_pct": r.business_explained_pct,
                "arithmetic_explained_pct": r.arithmetic_explained_pct,
                "data_staleness_hours": r.data_staleness_hours,
                "history_points": r.history_points,
                "history_unit": r.history_unit,
                "history_required": r.history_required,
                "data_completeness": r.data_completeness,
                "message": r.message,
                "reasons": r.reasons,
                "abstain_reasons": r.abstain_reasons,
            },
            "effective_rank": effective,
            "feedback": {
                "up": v["up"],
                "down": v["down"],
                "feedback_factor": factor,
                "excluded_from_factor": abstain,
            },
            "drivers": drivers,
            "recommendations": recommendations,
            "narrative": narrative,
            "_orig_index": orig_index,
        })

    # Order: scored by effective_rank desc (ties: pipeline order);
    # abstains (score None) sink to the bottom in pipeline order.
    scored = [i for i in items if i["effective_rank"] is not None]
    abstained = [i for i in items if i["effective_rank"] is None]
    scored.sort(key=lambda i: (-i["effective_rank"], i["_orig_index"]))
    ordered = scored + abstained

    for rank, item in enumerate(ordered, start=1):
        item["rank"] = rank
        del item["_orig_index"]

    return {
        "persona": persona,
        "sample": False,
        "insights": ordered,
        "blocked": list(blocked.values()),
        "source": "live pipeline (Phase 12)",
    }
