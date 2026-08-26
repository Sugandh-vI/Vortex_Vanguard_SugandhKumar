# BusinessIntelligence.ai — KPI Intelligence-to-Action Engine

Prototype for the Accenture Innovation Challenge 2026, Round 2, Problem Track 3.

A deterministic KPI intelligence-to-action engine that detects material metric movements, identifies root causes via statistical decomposition, and generates persona-specific narratives using a tightly-scoped LLM narrator (Ollama cloud backend). All quantitative logic is deterministic Python — the LLM only narrates pre-computed JSON.

## Quick Start

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# Ensure ollama is running: ollama serve
# Pull a cloud model: ollama pull minimax-m3:cloud
uvicorn api.main:app --reload
```

## Tech Stack

- **Backend:** Python 3.11+, FastAPI, pandas, numpy, SQLite
- **LLM:** Ollama (local serve + cloud-backed model, e.g., `minimax-m3:cloud`), with mock-mode fallback
- **Frontend:** React + Tailwind CSS (custom dashboard)

## Architecture Principle

> The LLM is NEVER the source of quantitative truth. Detection, calculation, decomposition, scoring, and access control are all deterministic code. The LLM only narrates already-computed structured JSON.

See `CLAUDE.md` for the full project specification and build log.
