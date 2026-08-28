"""
BusinessIntelligence.ai — KPI Intelligence-to-Action Engine
FastAPI application entry point.
"""

import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Allow imports from the backend root (contracts/, engine/, narration/)
# regardless of the cwd uvicorn is started from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.telemetry import get_default_collector

app = FastAPI(
    title="BusinessIntelligence.ai",
    description="KPI Intelligence-to-Action Engine — Deterministic Core, LLM Narrator",
    version="0.1.0",
)

# Allow frontend dev server to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    """Basic health-check endpoint to confirm the API is running."""
    return {
        "status": "healthy",
        "service": "BusinessIntelligence.ai",
        "version": "0.1.0",
    }


@app.get("/telemetry")
def telemetry_snapshot():
    """
    Runtime telemetry (Phase 10): per-stage pipeline latency, LLM call
    metrics (latency, token usage from model response metadata, real vs
    mock), grounding outcomes, and the estimated cost-at-scale figure.

    The panel is populated as instrumented pipeline runs and narrations
    execute in this process (Phase 12 wires those endpoints to record
    via the default collector).
    """
    return get_default_collector().snapshot()
