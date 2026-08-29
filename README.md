# BusinessIntelligence.ai — KPI Intelligence-to-Action Engine

**Team Vortex Vanguard** · Accenture Innovation Challenge 2026 · Round 2 · Problem Track 3

A deterministic KPI intelligence-to-action engine that detects material metric movements, identifies root causes through statistical decomposition, scores its own confidence, and generates persona-specific narratives using a tightly-scoped LLM narrator. **All quantitative logic is deterministic Python — the LLM never computes a number, it only narrates pre-computed JSON.**

---

## Table of Contents

- [Problem Statement](#problem-statement)
- [Core Design Principle](#core-design-principle)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Key Features](#key-features)
- [The Four Demo Scenarios](#the-four-demo-scenarios)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Running the Demo](#running-the-demo)
- [What's Implemented](#whats-implemented)
- [Team](#team)

---

## Problem Statement

Most businesses track KPIs across fragmented systems with different refresh cadences and granularities. When a metric moves, the "right" explanation depends on who's asking and what they plan to do about it — a CFO and a Category Manager need different depth, different framing, and different actions from the same underlying movement.

This prototype answers eight requirements from the brief:

1. Detect and prioritize material KPI movements
2. Reconcile data and business context across heterogeneous sources
3. Identify and rank explanatory drivers using appropriate analytical methods
4. Generate persona-specific narratives supported by traceable evidence
5. Communicate uncertainty and abstain when evidence is insufficient or contradictory
6. Recommend practical actions grounded in business levers, constraints, and decision rights
7. Learn from analyst and business-user feedback
8. Operate within realistic security, cost, latency, and scalability constraints

## Core Design Principle

> **The LLM is never the source of quantitative truth.**

Every number — anomaly scores, driver contributions, confidence levels, expected impact ranges — is computed by deterministic code (pandas/numpy/statistics). The LLM's only job is to turn an already-computed, structured JSON payload into readable, persona-specific prose, under a system prompt that strictly forbids introducing any fact or number not present in that JSON.

This is enforced, not just claimed: every narrative is run through a **grounding validator** that extracts every number in the LLM's output and checks it against the exact set of numbers present in the JSON it was given. A narrative that invents or miscalculates a number fails validation. This pass/fail result is visible in the UI on every insight card.

## Architecture

**"Deterministic Core, LLM Narrator"**

```
Raw data (3 sources, 3 grains)
        │
        ▼
 Reconciliation ──► aligns daily/weekly/monthly sources, tracks freshness
        │
        ▼
   Detection ──────► rolling z-score anomaly detection + materiality filter
        │
        ▼
 Decomposition ────► price-volume-mix, contribution ranking, cohort analysis
        │
        ▼
  Confidence ───────► High / Medium / Low / Abstain scoring, all thresholds
        │             from a versioned semantic contract
        ▼
Access Control ─────► persona → KPI permission gate, enforced BEFORE narration
        │
        ▼
    Actions ────────► driver → lever → action → impact → owner, rules-based
        │
        ▼
  LLM Narration ────► persona-conditioned prose, grounded against the JSON above
        │
        ▼
   Feedback ────────► thumbs up/down per insight, feeds re-ranking over time
        │
        ▼
  Telemetry ────────► latency, token usage, cost — all from real response metadata
```

This "boring middle, smart edges" design was chosen deliberately over a full multi-agent LLM orchestration approach, which introduces reliability and rate-limit risk on a free-tier API during a live demo — and, more importantly, makes it much harder to prove the numbers are trustworthy.

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI |
| Analytics | pandas, numpy, SQLite |
| LLM | Ollama (local, cloud-backed model — provider-agnostic client, works with any OpenAI-compatible backend) |
| Frontend | React + Vite + Tailwind CSS + Recharts |
| Config | `.env` via python-dotenv — no hardcoded keys, no paid API keys anywhere in this codebase |
| Containerization | None — plain venv + `requirements.txt` for a local prototype |

## Key Features

- **Semantic KPI contract** (`kpi_contracts.yaml`) — single source of truth for KPI definitions, formulas, source lineage, materiality thresholds, persona access rules, and confidence-level criteria. Every insight the system produces traces back to specific fields in this contract.
- **Rolling z-score anomaly detection** with a materiality filter combining % change and $ impact.
- **Price-volume-mix decomposition** for revenue-type movements, contribution ranking for others, cohort analysis for churn.
- **Confidence scoring that separates arithmetic explanation from business explanation** — a decomposition can sum to 100% mathematically while still leaving the real-world cause unknown (e.g. a volume drop with no assignable reason). This distinction is what drives High vs. Medium confidence, not just the math.
- **Fail-closed access control** — persona permissions resolve entirely from the contract; an unknown persona or KPI is blocked by default, and every denial is logged to an auditable SQLite log.
- **Rules-based action recommendations** — driver → controllable lever → action → expected impact → owner → monitoring plan, matched by rule specificity, never LLM-generated.
- **Feedback-weighted re-ranking** — thumbs up/down per insight adjusts a Bayesian-shrunk feedback factor (clamped 0.5–1.5) that re-ranks the feed without ever touching the underlying evidence-based confidence score.
- **Full telemetry** — real latency, real token counts from LLM response metadata, and a free-tier-honest cost model with an at-scale cost projection.

## The Four Demo Scenarios

The synthetic dataset (90 days, 3 sources, 4 KPIs) deliberately engineers four scripted moments to exercise every part of the brief:

1. **Multi-factor Revenue dip (Week 7)** — a real price cut combines with an unexplained volume drop. Price-volume-mix decomposition explains part of it and is transparent about the rest — a Medium confidence, "partially explained" scenario.
2. **Sparse-history KPI** — a new product category launches with too little history for a reliable baseline. The engine correctly reports "insufficient history" rather than forcing a score.
3. **Low-confidence abstain** — a simulated data sync failure leaves ~30% of a month's customer records null. Churn appears to move, but the engine abstains rather than trust incomplete data.
4. **Role-based access control** — Gross Margin % is restricted to the CFO persona. A Category Manager attempting to view it sees a clearly-labeled blocked state, and the denial is logged.

## Project Structure

```
/backend
  /data           synthetic data generator + raw output
  /contracts      kpi_contracts.yaml, action_rules.yaml + loaders
  /engine         detection, reconciliation, decomposition, confidence,
                  access_control, actions, feedback, telemetry
  /narration      provider-agnostic LLM client + prompt/grounding logic
  /api            FastAPI app — live endpoints for meta/timeseries/insights/feedback
/frontend
  React + Tailwind dashboard — KPI charts, insight feed, persona switcher,
  telemetry panel, feedback voting
```

## Getting Started

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python data/generate_synthetic_data.py
uvicorn api.main:app --reload
```

The API serves on `http://localhost:8000`. Health check: `GET /health`.

### LLM Setup (optional — a mock-mode fallback is always available)

```bash
ollama serve
ollama pull minimax-m3:cloud
```

If Ollama isn't running, set `LLM_MOCK_MODE=true` in `.env` — the system runs fully end-to-end with a clearly-labeled `[MOCK]` narrator so the rest of the pipeline is always testable.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Runs on `http://localhost:5173` and proxies API calls to the backend.

## Running the Demo

1. Open the dashboard and switch between the **CFO** and **Category Manager** personas using the header switcher.
2. Walk through the insight feed — each card shows the confidence badge, decomposition drivers with attribution weights, and a grounded/ungrounded indicator on the narrative.
3. Try Gross Margin % as the Category Manager — it appears as a locked card with the access decision and its source in the contract.
4. Vote thumbs up/down on an insight and watch the feed re-rank live.
5. Check the telemetry panel for real latency, token counts, and cost.

## What's Implemented

- [x] Synthetic multi-source, multi-grain dataset with 4 scripted scenarios
- [x] Versioned semantic KPI contract with lineage and materiality thresholds
- [x] Rolling z-score anomaly detection with materiality filtering
- [x] Price-volume-mix / contribution / cohort decomposition
- [x] Confidence scoring (High/Medium/Low/Abstain) separating arithmetic vs. business explanation
- [x] Fail-closed, contract-driven, audit-logged access control
- [x] Rules-based action recommendation engine
- [x] Provider-agnostic LLM narration layer with a machine-checked grounding validator
- [x] Persona-conditioned narratives (CFO vs. Category Manager)
- [x] Feedback capture and confidence-weighted feed re-ranking
- [x] Full telemetry (latency, real token usage, free-tier-honest cost model)
- [x] Live React dashboard wired end-to-end to the backend

## Team

**Team Name:** Vortex Vanguard
**Idea:** BusinessIntelligence.ai

| Name | College | Stream | Graduation |
|---|---|---|---|
| Sugandh Kumar (Team Leader) | IIT Bombay | Chemical Engineering | 2028 |
| Anubhav Yadav | IIT Bombay | Metallurgical Engineering and Materials Science | 2028 |
| Devounkar Giri | IIT Bombay | Chemical Engineering | 2028 |

---

*Prototype built for the Accenture Innovation Challenge 2026, Round 2, Problem Track 3.*
