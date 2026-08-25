"""
BusinessIntelligence.ai — KPI Intelligence-to-Action Engine
FastAPI application entry point.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
