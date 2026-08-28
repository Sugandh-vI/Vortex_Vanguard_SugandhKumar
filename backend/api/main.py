"""
BusinessIntelligence.ai — KPI Intelligence-to-Action Engine
FastAPI application entry point.

Phase 12: the dashboard goes fully live.
  - At startup the deterministic pipeline runs ONCE, instrumented on the
    default telemetry collector (so GET /telemetry is populated with real
    stage timings for this process).
  - GET /api/meta, /api/timeseries serve the cached pipeline output.
  - GET /api/insights?persona= serves the access-filtered feed; narration
    is done LAZILY per persona on first request (cached per insight_id —
    a rebuild after a feedback vote never re-calls the LLM).
  - POST /api/feedback + GET /api/feedback/summary wire Phase 9's
    FeedbackStore; votes re-rank that persona's feed via
    effective_rank = Phase-5 score x feedback_factor.

The LLM is never the source of quantitative truth: every number in these
responses comes from the deterministic pipeline; narration is prose only
(and clearly labeled mock when no real model is available).
"""

import os
import sys
import threading
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Allow imports from the backend root (contracts/, engine/, narration/)
# regardless of the cwd uvicorn is started from.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from contracts.loader import ContractStore
from engine.feedback import (
    FeedbackStore,
    attach_feedback_context,
    feedback_factor,
    insight_id,
)
from engine.telemetry import get_default_collector, instrument_pipeline
from api.insights_service import build_insights, build_timeseries

RAW_DIR = os.path.join(BACKEND_DIR, "data", "raw")


# ============================================================
# Application state
# ============================================================

class AppState:
    """Holds the one-time pipeline run + per-persona feed caches."""

    def __init__(self) -> None:
        # RLock: endpoint handlers may re-enter via feed rebuilds.
        self.lock = threading.RLock()
        self.result = None          # instrumented pipeline result dict
        self.meta = None
        self.timeseries = None
        self.narratives: dict = {}  # persona -> {insight_id: narrative dict}
        self.feeds: dict = {}       # persona -> feed dict
        self.feedback: FeedbackStore | None = None
        self.started = False


STATE = AppState()


def _known_personas(contract: ContractStore) -> list[str]:
    """Union of persona_access across all contract KPIs (stable order)."""
    personas: set = set()
    for kpi in contract.list_kpis():
        personas.update(contract.get_kpi(kpi).get("persona_access", []))
    return sorted(personas)


def _load_raw():
    sales = pd.read_csv(os.path.join(RAW_DIR, "sales_transactions.csv"), parse_dates=["date"])
    marketing = pd.read_csv(os.path.join(RAW_DIR, "marketing_spend.csv"))
    roster = pd.read_csv(os.path.join(RAW_DIR, "customer_roster.csv"))
    return sales, marketing, roster


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run the instrumented pipeline once at startup (BI_SKIP_PIPELINE=true
    disables it, e.g. for endpoint-shape tests that don't need data)."""
    if os.environ.get("BI_SKIP_PIPELINE", "").strip().lower() != "true":
        sales, marketing, roster = _load_raw()
        contract = ContractStore()
        collector = get_default_collector()
        result = instrument_pipeline(collector, sales, marketing, roster, contract)
        with STATE.lock:
            STATE.result = result
            STATE.timeseries = build_timeseries(sales, roster, result)
            STATE.meta = {
                "generated_at": pd.Timestamp.now("UTC").isoformat(),
                "window": {
                    "start": str(sales["date"].min())[:10],
                    "end": str(sales["date"].max())[:10],
                },
                "personas": _known_personas(contract),
                "source_freshness": result["reconciliation"].source_freshness,
                "sample": False,
                "note": (
                    "Live pipeline (Phase 12). Narration is produced lazily "
                    "per persona on first feed request; mock mode is clearly "
                    "labeled when no real model is available."
                ),
            }
            STATE.feedback = FeedbackStore(os.environ.get("FEEDBACK_DB") or None)
            STATE.started = True
    yield
    with STATE.lock:
        STATE.started = False


app = FastAPI(
    title="BusinessIntelligence.ai",
    description="KPI Intelligence-to-Action Engine — Deterministic Core, LLM Narrator",
    version="0.2.0",
    lifespan=lifespan,
)

# Allow frontend dev server to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_started() -> None:
    if not STATE.started:
        raise HTTPException(status_code=503, detail="Pipeline not initialized yet.")


def _personas() -> list[str]:
    _require_started()
    return STATE.meta["personas"]


# ============================================================
# Basic endpoints
# ============================================================

@app.get("/health")
def health_check():
    """Basic health-check endpoint to confirm the API is running."""
    return {
        "status": "healthy",
        "service": "BusinessIntelligence.ai",
        "version": "0.2.0",
        "pipeline_ready": STATE.started,
    }


@app.get("/telemetry")
def telemetry_snapshot():
    """
    Runtime telemetry (Phase 10): per-stage pipeline latency, LLM call
    metrics (latency, token usage from model response metadata, real vs
    mock), grounding outcomes, and the estimated cost-at-scale figure.

    Populated by the startup pipeline run and by every lazy narration
    (Phase 12), all recorded on this process's default collector.
    """
    return get_default_collector().snapshot()


# ============================================================
# Data endpoints (Phase 12 — consumed by the dashboard client)
# ============================================================

@app.get("/api/meta")
def api_meta():
    """Data window, personas, and source freshness from reconciliation."""
    _require_started()
    with STATE.lock:
        return STATE.meta


@app.get("/api/timeseries")
def api_timeseries():
    """KPI series + chart markers (anomaly band, launch, completeness)."""
    _require_started()
    with STATE.lock:
        return STATE.timeseries


@app.get("/api/insights")
def api_insights(persona: str):
    """
    The insight feed for one persona:
      - Phase 6 access control (Category Manager never receives Gross
        Margin % — those insights come back as `blocked` decisions);
      - Phase 5 confidence + decomposition + actions, verbatim;
      - narration via the default collector (real model or labeled mock),
        cached per insight_id so rebuilds never re-call the LLM;
      - Phase 9 feedback factor applied: feed is ordered by
        effective_rank = score x feedback_factor (abstains last).
    """
    _require_started()
    if persona not in _personas():
        raise HTTPException(
            status_code=400,
            detail=f"Unknown persona '{persona}' — known: {_personas()}.",
        )
    collector = get_default_collector()
    with STATE.lock:
        feed = STATE.feeds.get(persona)
        if feed is None:
            feed = build_insights(
                persona,
                STATE.result,
                collector,
                STATE.feedback,
                narratives=STATE.narratives.setdefault(persona, {}),
            )
            STATE.feeds[persona] = feed
        return feed


# ============================================================
# Feedback endpoints (Phase 9 store, wired in Phase 12)
# ============================================================

class FeedbackPayload(BaseModel):
    insight_id: str
    persona: str
    rating: str  # "up" | "down"
    note: str | None = None


@app.post("/api/feedback")
def api_feedback(payload: FeedbackPayload):
    """
    Record a thumbs up/down for one insight. The confidence context
    (status + score + category) is derived SERVER-SIDE from the pipeline
    result, never from the client. Returns the vote plus the updated
    feedback block for that insight in this persona's feed.
    """
    _require_started()
    with STATE.lock:
        target = None
        for r in STATE.result["confidence"].results:
            if insight_id(r.kpi_name, str(r.period), r.category) == payload.insight_id:
                target = r
                break
        if target is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown insight_id '{payload.insight_id}' — not in the "
                       f"current pipeline output.",
            )

        ctx = attach_feedback_context(target, payload.persona)
        try:
            row_id = STATE.feedback.record(
                ctx["kpi_name"],
                ctx["period"],
                ctx["persona"],
                payload.rating,
                category=ctx["category"],
                note=payload.note,
                confidence_status=ctx["confidence_status"],
                confidence_score=ctx["confidence_score"],
                insight_id=ctx["insight_id"],
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        # Rebuild that persona's feed: re-rank only — all narratives are
        # already cached, so this issues zero additional LLM calls.
        collector = get_default_collector()
        feed = build_insights(
            ctx["persona"],
            STATE.result,
            collector,
            STATE.feedback,
            narratives=STATE.narratives.setdefault(ctx["persona"], {}),
        )
        STATE.feeds[ctx["persona"]] = feed

        voted = next(
            (i for i in feed["insights"] if i["insight_id"] == ctx["insight_id"]),
            None,
        )
        return {
            "ok": True,
            "row_id": row_id,
            "insight_id": ctx["insight_id"],
            "persona": ctx["persona"],
            "rating": payload.rating,
            "feedback": voted["feedback"] if voted else None,
        }


@app.get("/api/feedback/summary")
def api_feedback_summary(persona: str | None = None):
    """
    Phase 9 calibration-signal table: votes per insight and the per-
    (KPI x confidence level x persona) up-rate + feedback factor.
    Abstain rows are counted but excluded from factor computation
    (user opinion cannot repair broken evidence).
    """
    _require_started()
    if persona is not None and persona not in _personas():
        raise HTTPException(
            status_code=400,
            detail=f"Unknown persona '{persona}' — known: {_personas()}.",
        )
    with STATE.lock:
        rows = STATE.feedback.fetch(persona=persona)

    by_insight: dict = {}
    by_key: dict = {}
    for row in rows:
        iid = row["insight_id"]
        e = by_insight.setdefault(iid, {
            "insight_id": iid,
            "kpi_name": row["kpi_name"],
            "period": row["period"],
            "category": row["category"],
            "ups": 0,
            "downs": 0,
            "total": 0,
            "personas": [],
        })
        e["ups" if row["rating"] == "up" else "downs"] += 1
        e["total"] += 1
        if row["persona"] not in e["personas"]:
            e["personas"].append(row["persona"])

        key = f"{row['kpi_name']}|{row['confidence_status']}|{row['persona']}"
        k = by_key.setdefault(key, {"ups": 0, "downs": 0})
        k["ups" if row["rating"] == "up" else "downs"] += 1

    for e in by_insight.values():
        e["agreement"] = round(e["ups"] / e["total"], 3) if e["total"] else None

    calib = []
    for key, k in sorted(by_key.items()):
        kpi, status, p = key.split("|", 2)
        total = k["ups"] + k["downs"]
        calib.append({
            "kpi_name": kpi,
            "confidence_status": status,
            "persona": p,
            "ups": k["ups"],
            "downs": k["downs"],
            "total": total,
            "up_rate": round(k["ups"] / total, 3) if total else None,
            "feedback_factor": None if status == "abstain" else feedback_factor(k["ups"], k["downs"]),
            "excluded_from_factor": status == "abstain",
        })

    return {
        "persona": persona,
        "by_insight": list(by_insight.values()),
        "by_kpi_status_persona": calib,
    }
