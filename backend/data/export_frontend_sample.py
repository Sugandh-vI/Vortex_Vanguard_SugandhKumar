"""
Frontend Sample Data Exporter — Phase 11
=========================================

Generates the sample data snapshot the Phase 11 dashboard renders when
the Phase 12 live endpoints are not (yet) available.

Runs the REAL deterministic pipeline (detection → reconciliation →
decomposition → confidence → actions, instrumented by Phase 10) plus
clearly-labeled MOCK narration per persona, applies Phase 6 access
control (Category Manager never receives Gross Margin % — those
insights are recorded as blocked decisions instead), and writes:

    frontend/src/data/sample/meta.json
    frontend/src/data/sample/timeseries.json
    frontend/src/data/sample/insights_cfo.json
    frontend/src/data/sample/insights_category_manager.json
    frontend/src/data/sample/telemetry.json

Every number in the output is pipeline-derived — nothing is invented
here. Narration text is mock (LLM_MOCK_MODE forced) and carries the
[MOCK] label + mock: true flags, so the UI can never present it as a
real LLM output.

Usage (from backend/ with the venv active):
    python data/export_frontend_sample.py
"""

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))      # backend/data
BACKEND_DIR = os.path.dirname(BASE_DIR)                    # backend
ROOT_DIR = os.path.dirname(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)
os.environ["LLM_MOCK_MODE"] = "true"  # sample data must never call a real LLM

import pandas as pd

from contracts.loader import ContractStore
from engine.detection import prepare_daily_kpi, prepare_monthly_churn
from engine.access_control import PermissionGuard
from engine.telemetry import TelemetryCollector, instrument_pipeline
from narration.llm_client import LLMClient
from narration.prompts import pipeline_to_facts

RAW_DIR = os.path.join(BASE_DIR, "raw")
OUT_DIR = os.path.join(ROOT_DIR, "frontend", "src", "data", "sample")
PERSONAS = ["CFO", "Category Manager"]


def _load():
    sales = pd.read_csv(os.path.join(RAW_DIR, "sales_transactions.csv"), parse_dates=["date"])
    marketing = pd.read_csv(os.path.join(RAW_DIR, "marketing_spend.csv"))
    roster = pd.read_csv(os.path.join(RAW_DIR, "customer_roster.csv"))
    return sales, marketing, roster


def _timeseries(sales: pd.DataFrame, roster: pd.DataFrame, result) -> dict:
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


def _insights_for_persona(persona: str, result, collector) -> dict:
    """Access-filtered, narrated (mock) insight feed for one persona."""
    conf: list = result["confidence"].results
    plan = result["actions"]
    anomaly_by = {
        (a.kpi_name, a.period, None): a for a in result["detection"].anomalies
    }

    guard = PermissionGuard(persona, auto_log=False)
    insights: list = []
    blocked: dict = {}
    rank = 0

    for r in conf:
        decision = guard.check_kpi(r.kpi_name, auto_log=False)
        if not decision.allowed:
            # Phase 6: dedupe — one blocked decision per KPI (mirrors the
            # access log's bulk-filter behavior).
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

        rank += 1
        anomaly = anomaly_by.get((r.kpi_name, r.period, r.category))
        sset = plan.get_set(r.kpi_name, r.period) if anomaly is not None else None

        # Drivers come from the decomposition (contribution + pct); the
        # attribution weight comes from the Phase 5 result.
        dec = next(
            (d for d in result["decomposition"]
             if d.kpi_name == r.kpi_name and d.period == r.period),
            None,
        )
        weights = {
            d["driver_name"]: d["attribution_weight"]
            for d in (r.attribution_detail or [])
        }
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

        facts = pipeline_to_facts(r, sset, anomaly, persona)
        resp, grounded, violations = collector.narrate(
            LLMClient.from_env(persona), facts, persona
        )

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

        insights.append({
            "insight_id": f"{r.kpi_name}|{r.period}" + (f"|{r.category}" if r.category else ""),
            "rank": rank,
            "kpi_name": r.kpi_name,
            "period": r.period,
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
            "drivers": drivers,
            "recommendations": recommendations,
            "narrative": {
                "text": resp.text,
                "provider": resp.provider,
                "model": resp.model,
                "mock": resp.mock,
                "grounded": grounded,
                "violations": violations,
                "persona": persona,
                "usage": resp.usage,
            },
        })

    return {
        "persona": persona,
        "sample": True,
        "insights": insights,
        "blocked": list(blocked.values()),
        "source": "sample-pipeline-snapshot (Phase 12 serves this live)",
    }


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    sales, marketing, roster = _load()
    store = ContractStore()

    collector = TelemetryCollector()
    result = instrument_pipeline(collector, sales, marketing, roster, store)

    # --- meta ---
    meta = {
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "window": {
            "start": str(sales["date"].min())[:10],
            "end": str(sales["date"].max())[:10],
        },
        "personas": PERSONAS,
        "source_freshness": result["reconciliation"].source_freshness,
        "sample": True,
        "note": (
            "Sample snapshot generated by the deterministic pipeline with "
            "mock narration (clearly labeled). Phase 12 serves this data live."
        ),
    }

    # --- per-persona insight feeds (instrumented mock narration fills telemetry) ---
    feeds = {p: _insights_for_persona(p, result, collector) for p in PERSONAS}

    # --- telemetry snapshot from this very run ---
    telemetry = collector.snapshot()

    def _write(name: str, obj) -> None:
        path = os.path.join(OUT_DIR, name)
        with open(path, "w") as f:
            json.dump(obj, f, indent=2, default=str)
        print(f"  wrote {path} ({os.path.getsize(path):,} bytes)")

    print(f"Pipeline: {result['total_ms']} ms "
          f"({len(result['detection'].anomalies)} anomalies, "
          f"{len(result['confidence'].results)} confidence results, "
          f"{result['actions'].total_recommendations} recommendations)")
    _write("meta.json", meta)
    _write("timeseries.json", _timeseries(sales, roster, result))
    for p in PERSONAS:
        _write(f"insights_{p.lower().replace(' ', '_')}.json", feeds[p])
    _write("telemetry.json", telemetry)

    for p in PERSONAS:
        f = feeds[p]
        print(f"{p}: {len(f['insights'])} insights, "
              f"{len(f['blocked'])} blocked KPI(s) {sorted(f['blocked'])}")
    print("✅ Frontend sample data exported")


if __name__ == "__main__":
    main()
