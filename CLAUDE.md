# CLAUDE.md — BusinessIntelligence.ai Prototype

**Project:** KPI Intelligence-to-Action Engine — Accenture Innovation Challenge 2026, Round 2, Problem Track 3
**This file is the single source of truth for this project.** Read this fully before writing any code.

---

## 1. Context — What This Project Is

We are building a prototype for the **BusinessIntelligence.ai** track of the Accenture Innovation Challenge Round 2. The brief asked us to design and demonstrate a working prototype of a **KPI intelligence-to-action engine** — a tool that explains what changed in a business metric, identifies likely root causes, and recommends next steps in plain language, aimed at solving the real-world problem that businesses track KPIs across fragmented systems with different refresh cadences, and the "right" explanation for a movement depends on who's asking.

### The core design principle (this is the most important rule in this whole document)

**The LLM is NEVER the source of quantitative truth.** All detection, calculation, decomposition, scoring, and access control must be done with deterministic code (math/stats/rules). The LLM's ONLY job is to take already-computed, structured JSON output and turn it into readable, persona-specific prose — and it must not introduce any fact, number, or claim that isn't present in the JSON it was given. This separation is what the judges are explicitly testing for, and it must be visibly demonstrable at every step (we will log/display which parts of each output came from code vs. from the LLM).

### Budget constraint — read this carefully

This project must be built with **$0 cost**. No OpenAI or Anthropic API keys are available or should ever be used in this codebase. The only LLM calls allowed are via a **local Ollama instance** pointing at a cloud-backed model (e.g., `minimax-m3:cloud` via `ollama serve`), which is free-tier. The `llm_client.py` module must be **provider-agnostic** (a simple interface that any OpenAI-compatible backend could satisfy), so the actual provider is a config detail, not hardcoded. If Ollama is unavailable or a model isn't yet pulled, the system should still run in a "mock LLM" mode that returns a clearly-labeled placeholder narrative, so the rest of the pipeline is always testable without a running model.

---

## 2. The Approach We Chose (and why)

We evaluated four architecture options and chose the following, deliberately rejecting a full multi-agent orchestration approach because it introduces LLM rate-limit and reliability risk on a free API tier during a live demo.

**Chosen approach: "Deterministic Core, LLM Narrator."**

- Detection, reconciliation, driver decomposition, confidence scoring, and access control are all done in plain Python (pandas/numpy/stats) — no LLM involved.
- A single, tightly-scoped LLM call (via Ollama) takes the final structured JSON output and renders it into persona-specific natural language, constrained by a system prompt that forbids introducing facts not present in the JSON.
- A visible "LLM vs non-LLM" breakdown is shown for every insight, satisfying the brief's explicit requirement to distinguish these.

---

## 3. What the Original Brief Asked For (do not lose sight of this)

Round 2 Objective — design and demonstrate a working prototype of a KPI intelligence-to-action engine that:

1. Detects and prioritises material KPI movements.
2. Reconciles data and business context across heterogeneous sources.
3. Identifies and ranks explanatory drivers using appropriate analytical methods.
4. Generates persona-specific narratives supported by traceable evidence.
5. Communicates uncertainty and abstains when evidence is insufficient or contradictory.
6. Recommends practical actions grounded in business levers, constraints and decision rights.
7. Has a mechanism to learn from analyst and business-user feedback.
8. Operates within realistic security, cost, latency and scalability constraints.

### Minimum Prototype Expectations (from the brief — all of these must eventually be demonstrable)

- Three to five connected KPIs across two or three data sources with different grains or refresh cadences.
- A lightweight KPI/semantic contract covering definitions, calculations, drivers, thresholds, lineage, and access restrictions.
- At least two personas receiving different insight narratives or recommended actions.
- One multi-factor KPI movement with known or simulated underlying drivers.
- One low-confidence scenario in which the engine requests clarification or abstains.
- One sparse-history or newly launched KPI scenario.
- One role-based security or entitlement scenario.
- Evidence showing source freshness, analytical method, contribution, confidence, and lineage.
- A clear breakdown of LLM versus non-LLM processing.
- Runtime telemetry covering latency, model calls, token usage, and estimated cost.

---

## 4. Our Concrete Design (KPIs, Sources, Personas, Data Story)

### KPI Set (4 KPIs, 3 sources, mixed grains)

| KPI | Grain | Source table | Visibility |
|---|---|---|---|
| Revenue | Daily | `sales_transactions` | Both personas |
| Units Sold | Daily | `sales_transactions` | Both personas |
| Gross Margin % | Daily (derived) | `sales_transactions` | **CFO only** (this is our access-control demo) |
| Customer Churn Rate | Monthly | `customer_roster` | Both personas |

Supporting (non-KPI) source:
- `marketing_spend` — Weekly, per channel — used only as a driver input for Revenue/Units explanations.

This gives us 3 source tables with 3 different refresh cadences (daily / weekly / monthly), feeding 4 KPIs — matching the brief's "3-5 KPIs, 2-3 sources, different grains" requirement.

### Personas

- **CFO** — sees all 4 KPIs (including Gross Margin %). Gets short, dollar-impact-first narratives.
- **Category Manager** — sees Revenue, Units Sold, Churn — NOT Gross Margin (blocked, logged, and visibly shown as blocked in the UI). Gets more operational, product-line-level narratives.

### The Data Story — ~90 days of synthetic daily data, with scripted events

We are NOT relying on random noise to accidentally produce a good demo. We are deliberately engineering four guaranteed moments into the synthetic data generator:

1. **Multi-factor Revenue dip — Week 7.** A 10% price cut on one product category coincides with an unexplained extra volume drop (simulating a competitor promo we have no data on). Price-volume-mix decomposition should explain part of the dip (the price cut) but leave a residual unexplained — this is our "partial confidence, transparent about what's known vs unknown" moment.
2. **Sparse-history KPI — Day 80 onward.** A new product category launches ~10 days before the demo's "current date," with too little history for a reliable baseline. The system must say "insufficient history to assess" rather than force a score.
3. **Low-confidence / abstain scenario — Month 3, Churn.** The customer roster data for the most recent month has a chunk of missing/null records (simulated sync failure). Churn appears to move, but data completeness is too low to trust it — engine must abstain and ask a clarifying question rather than guess.
4. **Access control — Gross Margin %, always.** No special data needed; this is a permissions rule. Category Manager persona attempting to view Gross Margin should see it blocked/redacted, and the block should be logged.

All other weeks should have small, realistic natural noise so the scripted anomalies stand out statistically rather than everything looking chaotic.

---

## 5. Tech Stack

- **Language:** Python 3.11+ for all backend/analytics logic.
- **Data handling:** pandas, numpy for time series and decomposition math; SQLite (via `sqlite3` or SQLAlchemy) for storing the synthetic tables — no external DB needed.
- **API layer:** FastAPI, serving both the analytics engine and the LLM narration endpoint.
- **LLM:** Ollama (local `ollama serve` pointing at a cloud-backed model such as `minimax-m3:cloud`). The `llm_client.py` module exposes a provider-agnostic interface (any OpenAI-compatible backend works), so the actual provider is a `.env` config detail. A mock-mode fallback must exist for when no model is available.
- **Config/secrets:** `.env` file for `OLLAMA_BASE_URL` (default `http://localhost:11434`), `OLLAMA_MODEL` (default `minimax-m3:cloud`), loaded via `python-dotenv`. Never hardcode keys. `.env` must be in `.gitignore`.
- **Frontend:** React + Tailwind CSS, built as a lightweight custom "mini Power BI" dashboard — KPI trend charts, an insight feed with confidence badges, a persona switcher, and a telemetry panel. (No third-party BI tool is used — we are building this ourselves.)
- **No Docker.** We are not containerizing this project — plain venv + requirements.txt is sufficient for a local prototype and a screen-recorded demo.
- **Version control:** Git/GitHub from the start of the project, committed incrementally per phase (see Section 8).

---

## 6. Folder Structure

Set this up exactly as follows before writing any feature code:

```
/project-root
  /backend
    /data
      generate_synthetic_data.py       # builds the 90-day scripted dataset
      /raw                             # output CSVs/SQLite db land here (gitignored if large)
    /contracts
      kpi_contracts.yaml                # semantic contract: definitions, formulas, sources, lineage, access roles
    /engine
      detection.py                      # anomaly/materiality detection
      reconciliation.py                 # joins across sources/grains
      decomposition.py                  # price-volume-mix / contribution ranking
      confidence.py                     # confidence scoring + abstention logic
      access_control.py                 # persona -> KPI/column permission filter
      actions.py                        # driver -> lever -> action lookup
      telemetry.py                      # latency/token/cost tracking wrapper
    /narration
      llm_client.py                     # Provider-agnostic LLM client (Ollama default) + mock-mode fallback
      prompts.py                        # system prompts, persona-conditioned templates
    /api
      main.py                           # FastAPI app, all endpoints
    requirements.txt
    .env.example
  /frontend
    (React + Tailwind app — structure to be created by the agent following frontend-design conventions)
  /docs
    (proposal/pitch supporting material — not code)
  CLAUDE.md                             # this file
  README.md                             # short human-facing project overview (separate from this file)
  .gitignore
```

---

## 7. Data & Contract Schema Requirements

- `sales_transactions`: daily grain, columns should include date, product_category, units_sold, unit_price, revenue (derived), cost (for margin), region — enough to support price-volume-mix decomposition.
- `marketing_spend`: weekly grain, columns for week_start, channel, spend.
- `customer_roster`: monthly grain, columns for month, customer_id, status (active/churned), signup_date — with the Month-3 null-record gap deliberately injected.
- `kpi_contracts.yaml`: one entry per KPI containing — name, definition (plain English), formula, source table(s), grain, refresh cadence, owner/persona access, known driver list, materiality thresholds (% and $), and lineage (which raw columns feed it).

Every insight the system produces must be traceable back to specific fields in this contract — this is what "evidence: source freshness, analytical method, contribution, confidence, lineage" means in the brief, and it must show up literally in the JSON/UI, not just conceptually.

---

## 8. Build Phases — IMPORTANT: DO NOT BUILD EVERYTHING AT ONCE

Work through the phases below **one at a time, in order**. After finishing a phase, **stop and wait for explicit confirmation** before starting the next phase, even if the next phase seems obvious or small. Do not pre-build later phases "while you're at it."

### Phase 0 — Project Setup
- Create the folder structure exactly as in Section 6.
- Set up `requirements.txt`, `.env.example`, `.gitignore`.
- Initialize git.
- Confirm the venv runs and FastAPI serves a basic health-check endpoint.

### Phase 1 — Synthetic Data Generation
- Build `generate_synthetic_data.py` implementing the exact data story in Section 4 (90 days, 4 scripted events, realistic baseline noise elsewhere).
- Output to SQLite and/or CSV in `/backend/data/raw`.
- Write a short script or notebook cell that plots the raw data so we can visually confirm the 4 scripted events are actually visible before moving on.

### Phase 2 — Semantic Contract
- Build `kpi_contracts.yaml` per Section 7.
- Build a loader/validator for it in Python.

### Phase 3 — Detection Engine
- Rolling z-score or STL-residual based anomaly detection.
- Materiality filter combining % change and $ impact, using thresholds from the contract.

### Phase 4 — Reconciliation + Driver Decomposition
- Join logic across the 3 sources despite differing grains.
- Price-volume-mix decomposition for Revenue-type movements.
- Simple contribution/correlation ranking for other KPIs.

### Phase 5 — Confidence Scoring & Abstention
- Implement the High/Medium/Low/Abstain logic based on % of movement explained, data freshness, and history depth.
- Must correctly trigger abstain on the Month-3 churn scenario and "insufficient history" on the new product.

### Phase 6 — Access Control
- Persona → KPI/column permission filter, enforced BEFORE any data reaches the narration layer.
- Must correctly block Gross Margin for Category Manager persona and log the block.

### Phase 7 — Action Recommendation
- Driver → controllable lever → action → expected impact → owner → confidence → monitoring plan, as a lookup/rules table (not LLM-generated).

### Phase 8 — LLM Narration Layer
- Provider-agnostic LLM client (`llm_client.py`) with Ollama as the default backend and mock-mode fallback.
- System prompt strictly constraining the model to only use facts present in the JSON payload it's given.
- Persona-conditioned templates (CFO vs Category Manager tone/depth).

### Phase 9 — Feedback Loop
- Simple thumbs up/down capture per insight, logged (SQLite table is fine).
- A small explanation in the UI/docs of how this would feed back into confidence weighting over time (does not need real retraining for the prototype).

### Phase 10 — Telemetry
- Wrap the LLM call and the analytics pipeline to record latency, token usage (from LLM response metadata), and an estimated cost-at-scale figure, exposed via an API endpoint and shown in the UI.

### Phase 11 — Frontend Dashboard
- KPI trend charts, insight feed with confidence badges, persona switcher, LLM-vs-non-LLM indicator per card, access-blocked state, telemetry panel.
- Follow the frontend-design conventions for a clean, non-templated look — this is a judged prototype, it should look considered, not default Bootstrap-y.

### Phase 12 — Integration, Polish, Demo Script
- Wire frontend to backend end-to-end.
- Verify all four scripted scenarios are reliably reachable via clicks in the UI (not buried in logs).
- Prepare a short internal "demo path" (which buttons to click, in what order) for the video recording.

---

## 9. Iteration Logging Instructions (READ THIS EVERY TIME)

At the end of **every work session/iteration**, append a new dated section to the bottom of this file (do not overwrite or remove previous entries — this file is a running log). Use this exact format:

```
## Iteration Log — [Phase Name] — [Date]

### What was done
- (bullet list of concretely what was built/changed this iteration)

### Key decisions made
- (any judgment calls made, e.g., specific threshold values chosen, library choices, naming decisions)

### What remains
- (what's left in this phase, if anything, or confirmation the phase is fully complete)

### Next phase (pending confirmation)
- (name the next phase from Section 8 — do NOT start it until explicitly told to proceed)
```

This log is how we track project state across sessions, so keep entries factual and specific — not vague ("improved things") but concrete ("added STL-decomposition-based anomaly detection in detection.py, threshold set to 2.5 std devs based on visual inspection of baseline noise").

---

## 10. Ground Rules Recap

- No paid API keys (OpenAI/Anthropic) anywhere in this codebase, ever.
- Only Ollama (or compatible provider) is used for LLM calls, with a working mock-mode fallback.
- LLM never computes numbers — only narrates already-computed JSON.
- No Docker.
- Build and confirm one phase at a time — do not jump ahead.
- Append an iteration log entry to this file at the end of every session, in the exact format in Section 9.

---

## Iteration Log — Phase 0 (Project Setup) — 2026-08-25

### What was done
- Created the full folder structure exactly as specified in Section 6: `/backend/data/`, `/backend/data/raw/`, `/backend/contracts/`, `/backend/engine/`, `/backend/narration/`, `/backend/api/`, `/frontend/`, `/docs/`.
- Created placeholder files for all future modules: `detection.py`, `reconciliation.py`, `decomposition.py`, `confidence.py`, `access_control.py`, `actions.py`, `telemetry.py`, `llm_client.py`, `prompts.py`, `generate_synthetic_data.py`, `kpi_contracts.yaml`.
- Created `requirements.txt` with: fastapi, uvicorn, python-dotenv, pandas, numpy, sqlalchemy, pyyaml, httpx.
- Created `.env.example` with `OLLAMA_BASE_URL=http://localhost:11434` and `OLLAMA_MODEL=minimax-m3:cloud` placeholders.
- Created `.gitignore` covering Python, .env, IDE files, data outputs (CSV/SQLite), and frontend build artifacts.
- Created `README.md` with a human-facing project overview.
- Built `backend/api/main.py` with a FastAPI app and `/health` endpoint returning `{"status":"healthy","service":"BusinessIntelligence.ai","version":"0.1.0"}`.
- Set up Python venv at `backend/venv/`, installed all dependencies successfully.
- Verified FastAPI health-check endpoint responds correctly (HTTP 200, correct JSON).
- Initialized git repository, committed all files (20 files, root commit `0389fd0`).

### Key decisions made
- Used `.gitkeep` files to preserve empty directories (`raw/`, `docs/`, `frontend/`) in git.
- Added CORS middleware with `allow_origins=["*"]` to the FastAPI app so the React frontend can connect during development.
- Pinned minimum versions in requirements.txt (e.g., `fastapi>=0.104.0`) rather than exact pins, for flexibility on a prototype.

### What remains
- Phase 0 is fully complete. All checklist items verified.

### Next phase (pending confirmation)
- Phase 1 — Synthetic Data Generation

---

## Iteration Log — Phase 1 (Synthetic Data Generation) — 2026-08-25

### What was done
- Built `backend/data/generate_synthetic_data.py` implementing the full data story from Section 4:
  - **sales_transactions** (1,484 rows): daily grain, 5 categories × 4 regions × 90 days. Columns: date, product_category, region, units_sold, unit_price, revenue, cost.
  - **marketing_spend** (52 rows): weekly grain, 13 weeks × 4 channels. Columns: week_start, channel, spend.
  - **customer_roster** (3,053 rows): monthly grain, 3 months × ~1,000+ customers. Columns: month, customer_id, status, signup_date.
- All 4 scripted events implemented and verified in plots:
  - **Event 1 — Week 7 Revenue dip (May 13-19):** Electronics price cut from ~$150 to ~$135 (10%) + 20% volume drop. Total daily revenue drops from ~$57K to ~$48K. Gross margin compresses from ~37.7% to ~34.8%. Both price and volume components clearly visible in isolation.
  - **Event 2 — Sparse history (Day 80+, Jun 19):** "Sports & Outdoors" category appears with only 11 days of data. Revenue ~$1,800-$2,100/day. Clearly too few data points for reliable baseline.
  - **Event 3 — Month 3 churn abstain (June):** 309 of 1,036 records (29.8%) have null status. Apparent churn rate jumps to 17.1% (from 4.5%/9.7% in prior months), but 30% data incompleteness makes it untrustworthy.
  - **Event 4 — Gross Margin access control:** No data manipulation needed — this is a permissions rule for later phases.
- Baseline noise is small and realistic: ~5% std dev daily, plus weekend patterns (Electronics/Home dip, Grocery/Apparel bump) and a 0.1%/day growth trend. Scripted anomalies stand out clearly against baseline.
- Output saved to both CSV and SQLite in `backend/data/raw/`.
- Built `backend/data/plot_data.py` — 6-panel verification plot saved as `data_verification_plots.png`.
- Committed to git (commit `4c9e144`).

### Key decisions made
- Used **fixed cost per unit** (not a % of selling price) so the Week 7 price cut visibly compresses gross margin — this creates an interesting signal for the CFO persona later.
- Category baselines: Electronics ~$30K/day (200 units × $150), Apparel ~$12K/day (300 × $40), Home ~$9K/day (150 × $60), Grocery ~$5K/day (500 × $10). Total ~$56K/day.
- Month 3 churn: bumped true churn rate from 5% → 8% (genuine movement) AND injected 30% nulls. This ensures the engine has a real signal to detect but insufficient data quality to trust it — perfect for the abstain scenario.
- New category "Sports & Outdoors" (not just "Sports") for clarity in labels.
- `np.random.seed(42)` for full reproducibility.
- Installed matplotlib as an additional dependency for plotting (not in requirements.txt since it's only needed for data verification, not the production app).

### What remains
- Phase 1 is fully complete. All 4 events verified visually in the plots.

### Next phase (pending confirmation)
- Phase 2 — Semantic Contract

---

## Iteration Log — Phase 2 (Semantic Contract) — 2026-08-25

### What was done
- Built `backend/contracts/kpi_contracts.yaml` — comprehensive semantic contract with all fields specified in Section 7:
  - **4 KPIs defined**: Revenue, Units Sold, Gross Margin %, Customer Churn Rate.
  - **3 data sources documented**: sales_transactions (daily), marketing_spend (weekly), customer_roster (monthly) — each with grain, refresh cadence, key columns, and description.
  - Per-KPI fields: name, definition (plain English), formula, source_tables, grain, refresh_cadence, unit, persona_access, known_drivers (with type/source_column/decomposition_method), materiality_thresholds (pct_change + absolute_impact + impact_unit), lineage (primary + supporting column refs).
  - **Access control**: Gross Margin % `persona_access` explicitly lists only CFO — Category Manager excluded with a comment explaining this is Event 4.
  - **Data quality gate**: Customer Churn Rate has `data_quality_requirements.min_completeness: 0.90` — engine must abstain when completeness drops below 90%.
  - **Confidence scoring config**: High/Medium/Low/Abstain levels with thresholds for explained %, data staleness, and history depth.
  - **Sparse-history config**: `daily_kpi_min_days: 21`, `monthly_kpi_min_months: 3` — Sports & Outdoors (11 days) will correctly trigger "insufficient history."
- Built `backend/contracts/loader.py` — `ContractStore` class with:
  - YAML loading and full schema validation (checks required fields on KPIs, drivers, materiality; validates driver types; verifies source table references exist; raises `ContractValidationError` with detailed errors).
  - Typed accessor methods: `list_kpis()`, `get_kpi()`, `is_accessible()`, `get_kpis_for_persona()`, `get_materiality()`, `get_drivers()`, `get_lineage()`, `get_source_meta()`, `get_confidence_config()`, `get_sparse_history_config()`, `get_data_quality_requirements()`, `get_formula()`, `get_definition()`, `get_grain()`, `get_unit()`.
  - Custom exceptions: `ContractValidationError`, `KPINotFoundError`.
- Verified all accessor methods return correct data:
  - CFO sees all 4 KPIs; Category Manager sees 3 (Gross Margin % blocked) ✅
  - Revenue materiality: 5% or $5,000 ✅
  - Churn data quality: min_completeness=0.90 (our Month 3 has 70% → will trigger abstain) ✅
  - Revenue drivers: unit_price, units_sold, product_mix, marketing_spend ✅
  - Lineage traces back to specific table.column pairs ✅
- Verified negative test cases: KPINotFoundError, ContractValidationError on bad YAML, FileNotFoundError — all work ✅
- Committed to git (commit `a5a8134`).

### Key decisions made
- Added `decomposition_method` field to each driver (e.g., `price_volume_mix`, `correlation`, `contribution`, `cohort_analysis`) so Phases 4-5 can look up which analytical method to apply per driver, directly from the contract.
- Included `unit` field per KPI (USD, units, percent) for display and narration formatting.
- Set Revenue materiality at 5% / $5,000 (not $10,000) because our daily baseline is ~$56K, so $10K would require an ~18% swing to trigger — too high. $5K ≈ 9% of baseline, reasonable for flagging the Week 7 event.
- Sparse history threshold set at 21 days (not 14) for daily KPIs — Sports & Outdoors with 11 days is well below this, giving a clean "insufficient history" trigger without being borderline.
- Confidence `abstain` triggers include `contradictory_signals` as a future-proofing hook.

### What remains
- Phase 2 is fully complete. Contract validated, loader tested.

### Next phase (pending confirmation)
- Phase 3 — Detection Engine

---

## Iteration Log — Phase 3 (Detection Engine) — 2026-08-25

### What was done
- Built `backend/engine/detection.py` — complete anomaly detection module with:
  - **`AnomalyResult` dataclass**: structured output per detected anomaly, carrying all metadata for downstream modules (kpi_name, period, current/baseline values, absolute/pct change, z-score, direction, materiality details, detection method, data_points_used, insufficient_history flag, data_completeness).
  - **`prepare_daily_kpi()`**: aggregates `sales_transactions` into daily KPI time series for Revenue (`SUM(revenue)`), Units Sold (`SUM(units_sold)`), and Gross Margin % (`(rev-cost)/rev * 100`).
  - **`prepare_monthly_churn()`**: computes monthly churn rate + data completeness from `customer_roster`, tracking null records for the abstain scenario.
  - **`_detect_daily_anomalies()`**: rolling z-score detection with configurable window (default 21 days) and threshold (default 2.0). Computes rolling mean/std excluding the current point (shift(1)), then flags days where |z| > threshold AND materiality conditions are met.
  - **Materiality filter**: combines % change threshold AND/OR absolute $ impact threshold from the contract. Must pass at least one to be flagged.
  - **`_detect_monthly_anomalies()`**: period-over-period comparison for monthly KPIs (only 3 months, z-score impractical). Computes z-score when ≥2 prior months exist. Tracks data completeness per month.
  - **`_rank_anomalies()`**: priority ranking by severity = |z_score| × |pct_change|.
  - **`run_detection()`**: main entry point — runs detection across all 4 KPIs, returns priority-ranked list.
  - **`detect_by_category()`**: per-category detection using base KPI thresholds, with a slightly lower z-score threshold (−0.5) to catch category-level movements diluted at aggregate level.

- Verified against synthetic data — **all scripted events detected correctly**:
  - **Event 1 (Week 7)**: 9 anomalies — Revenue (4 hits, z=−3.53, pct=−13.6%), Gross Margin (4 hits, z=−16.1, pct=−7.8%), Units Sold (1 hit, z=−2.36, pct=−5.1%). Per-category: Electronics has 6 Week 7 hits (z=−3.06, pct=−24.7%), other categories show no Week 7 signal. ✅
  - **Event 2 (Sparse history)**: Sports & Outdoors — zero anomalies detected (too few data points to build a baseline, rolling window needs ≥7 points but Sports only has 11 total days). ✅
  - **Event 3 (Month 3 churn)**: Detected churn increase from 9.7% → 17.1% (Δ=+7.3pp, z=2.69), with `data_completeness=70%` correctly tracked for downstream abstain logic. ✅
  - **Event 4**: No detection needed — access control is a permissions rule.

- Fixed a bug: `detect_by_category()` was passing category-qualified names (e.g., `Revenue [Apparel]`) to contract lookups. Added `contract_kpi_name` parameter to `_detect_daily_anomalies()` to separate the display label from the contract lookup name.

- Committed to git (commit `4e016e6`).

### Key decisions made
- **Rolling window = 21 days**: matches 3 business weeks and aligns with the sparse-history threshold. Long enough for stable baselines, short enough to react to trends.
- **Z-score threshold = 2.0**: roughly 95th percentile for normal distribution. Catches Week 7 events (z=−3.53 for Revenue, z=−16.1 for Gross Margin) while keeping false positives manageable (24 total anomalies across 90 days × 4 KPIs).
- **Materiality = OR logic**: an anomaly is material if it exceeds EITHER the % threshold OR the $ threshold. This ensures both large-percentage-small-dollar and small-percentage-large-dollar movements are caught.
- **Per-category threshold −0.5**: slightly more sensitive at category level since individual category movements are larger in percentage terms but get diluted in the aggregate.
- **Shift(1) on rolling stats**: the baseline excludes the current day's value, preventing the anomaly from dampening its own z-score.

### What remains
- Phase 3 is fully complete. All scripted events verified.

### Next phase (pending confirmation)
- Phase 4 — Reconciliation + Driver Decomposition

---

## Iteration Log — Phase 4 (Reconciliation + Driver Decomposition) — 2026-08-25

### What was done
- Built `backend/engine/reconciliation.py`:
  - **`spread_weekly_to_daily()`**: converts weekly marketing spend to daily by dividing by 7 (uniform spread, explicitly documented).
  - **`align_monthly_to_window()`**: filters monthly roster data to months overlapping the analysis window (churn stays at monthly grain, no interpolation).
  - **`compute_source_freshness()`**: calculates staleness (hours) for each source relative to analysis date, with fresh/stale status. Feeds into Phase 5 confidence scoring and Phase 11 telemetry panel.
  - **`reconcile()`**: main entry point — aligns all 3 sources to a common analysis window, returns `ReconciliationResult` with aligned DataFrames + freshness metadata.

- Built `backend/engine/decomposition.py` with 5 analytical methods:
  - **`_price_volume_mix()`** (Revenue): classic PVM decomposition comparing anomaly day to rolling baseline. For each category: price_effect = (P1−P0)×V0, volume_effect = P0×(V1−V0), mix_effect = (P1−P0)×(V1−V0). Week 7 result: price −$3,032 (39.1%), volume −$5,207 (67.2%), mix +$489 (6.3%).
  - **`_contribution_breakdown()`** (Units Sold): additive ΔUnits by category. Identifies which categories drove the movement.
  - **`_margin_decomposition()`** (Gross Margin %): counterfactual analysis — "what would GM% be if only price changed?" Separates price contribution (−2.97pp) from cost contribution (+0.06pp). Electronics price cut accounts for ~102% of the margin compression.
  - **`_churn_decomposition()`** (Customer Churn Rate): data completeness assessment + tenure cohort breakdown. Completeness = 70.2%, fails 90% quality gate. Cohort analysis shows 3-6mo tenure bucket has highest churn (22.1%).
  - **`_marketing_correlation()`**: Pearson correlation between daily marketing spend and KPI values over a lookback window. Supporting signal only — explicitly labeled as "correlation, not causation."
  - **`decompose_anomaly()`** + **`decompose_all()`**: main entry points dispatching to the right method per KPI.

- Also fixed a Phase 3 issue before starting Phase 4:
  - Added `SparseHistoryFlag` dataclass and `DetectionResult` container to `detection.py`. Sports & Outdoors now has explicit sparse-history flags (3 flags — one per daily KPI), distinct from "no anomaly found".
  - Fixed `is_sparse()` to match on category exactly (passing `category=None` checks aggregate-level sparsity only). Added `has_any_sparse()` for broader checks.
  - Verified z=−16.1 for GM% on May 13 is genuine, not an artifact: rolling std = 0.1812 (GM% is naturally very stable at ±0.18pp daily), and the 2.92pp drop is 16× the normal variation.

- Committed to git (commit `8ff1cc4`).

### Key decisions made
- **PVM explains 100% mathematically** (price+volume+mix add up to total), but the volume drop itself is the "unexplained" part in business terms — we know Electronics units dropped 20%, but the engine has no data on why (competitor promo). This is exactly the "partial confidence, transparent about what's known vs unknown" scenario the brief asks for. Phase 5 will mark this as "medium confidence" due to the unexplained volume driver.
- **Marketing correlation not included in explained_%**: it's tagged as `analytical_method: correlation` and excluded from the quantitative decomposition sum. It's a supporting signal, not a causal claim.
- **Churn cohort breakdown uses tenure buckets** (<3mo, 3-6mo, 6-12mo, >12mo) rather than individual customer-level analysis — appropriate for a prototype and directly useful for actionable insights.
- **Weekly marketing spread is uniform** (/7). In production you'd weight by day-of-week, but for a prototype this is explicitly documented and sufficient.
- **GM% margin decomposition uses counterfactual approach**: simulates "what if only price changed but cost stayed at baseline?" to isolate price effect from cost effect. This correctly shows the Electronics price cut as the dominant margin driver.

### What remains
- Phase 4 is fully complete. All decomposition methods verified against scripted events.

### Next phase (pending confirmation)
- Phase 5 — Confidence Scoring & Abstention

---

## Iteration Log — Spec Change (LLM Provider: Groq → Ollama) — 2026-08-26

### What changed
- Replaced all references to Groq API / Llama 3.3 70B with **Ollama** (local `ollama serve` pointing at a cloud-backed model such as `minimax-m3:cloud`).
- Updated CLAUDE.md Sections 1, 2, 5, 6, 8, 10, and Ground Rules. Updated `requirements.txt` (`groq` → `ollama`), `.env.example` (`GROQ_API_KEY` → `OLLAMA_BASE_URL` + `OLLAMA_MODEL`), `README.md`, and `llm_client.py` placeholder comment.
- Added spec requirement: `llm_client.py` must expose a **provider-agnostic interface** (any OpenAI-compatible backend works), so the actual provider is a `.env` config detail, not hardcoded.
- Mock-mode fallback requirement is **unchanged** — system must be fully testable without a running LLM.

### Why
- Ollama's cloud backend provides free-tier access to strong models (minimax-m3) without needing a separate API key — just `ollama serve` + `ollama pull minimax-m3:cloud`.
- Provider-agnostic interface means we can swap to Groq, OpenAI, or any other backend with a single `.env` change if needed during the demo.

### No code changes to engine modules
- This is a doc/config-only change. Phases 1-4 (data, contract, detection, decomposition) are unaffected since they don't touch the LLM layer.

---

## Iteration Log — Bug Fix (Churn Decomposition JSON Serialization) — 2026-08-26

### What was done
- Fixed `_churn_decomposition()` in `backend/engine/decomposition.py`: numpy scalars leaking into the `DriverContribution.detail` dict (`null_records` as `np.int64`, `passes_quality_gate` as `np.bool_`, plus `np.float64` on `completeness_pct` / `contribution_value` / cohort `churn_rate`) were causing `json.dumps()` to raise `TypeError: Object of type int64 is not JSON serializable` on the June churn decomposition.
- Cast all of them to native Python types with `int()` / `float()` / `bool()`; the cohort breakdown rows already cast `total`/`churned` with `int()` and are untouched.
- Verified: all 24 decompositions (Revenue, Units Sold, Gross Margin %, Customer Churn Rate) now serialize to JSON cleanly; June churn detail shows `total_records=1036 (int)`, `null_records=309 (int)`, `passes_quality_gate=False (bool)`, `completeness_pct=70.2 (float)`.

### Key decisions made
- Scoped fix to `_churn_decomposition()` only — this was the single function leaking non-serializable scalars (all other decomposition outputs already passed `json.dumps`). No API/serialization helper was added.
- Left `prior_df` (computed but unused in `_churn_decomposition()`) untouched — out of scope for this bug fix.

### What remains
- Bug fix is fully complete and verified.

### Next phase (pending confirmation)
- Phase 5 — Confidence Scoring & Abstention

---

## Iteration Log — Phase 5 (Confidence Scoring & Abstention) — 2026-08-26

### What was done
- Built `backend/engine/confidence.py` (placeholder → full module):
  - **`ConfidenceResult`** dataclass: kpi_name, period, category, status (high/medium/low/abstain), 0–100 `score`, `business_explained_pct`, `arithmetic_explained_pct`, `data_staleness_hours`, `history_points`/`history_unit`/`history_required`, `data_completeness`, `level_thresholds` (per-level criteria + pass/fail), `attribution_detail` (per-driver weight trace), `reasons`, `abstain_reasons`, `insufficient_history`, `contradiction_detail`, `message`. All values are native Python types — JSON-serializable.
  - **`ConfidenceResultSet`** container + `analyze(...)` convenience pipeline (detection → reconciliation → decomposition → confidence) and `score_all(...)` batch entry point.
  - **Business-explained % (the core design point):** PVM sums to 100% arithmetically, so that number is NOT used as the confidence input. Each driver contribution carries an **attribution weight**: `1.0` = known business cause (price_effect in PVM, unit_price in margin decomposition), `0.5` = measured & localized but cause unknown (volume_effect, contribution breakdowns, cost/mix residual), `0.0` = informational/mechanical (mix interaction, correlation, cohort, completeness). `business_explained_pct = |Σ contribution × weight| / |total movement|`. Documented as a deterministic heuristic in code with a full comment.
  - **Level determination (top-down, all thresholds from the contract):** High requires explained ≥80% AND staleness ≤48h AND history ≥30 days (≥3 months); Medium ≥50% / ≤168h / ≥14d (≥2mo); Low ≥20% / ≤720h / ≥7d (≥1mo). Level tests read the contract `confidence.levels` config directly; `score` = weakest-link min of the three dimension scores (explained / freshness / history).
  - **Abstain triggers (checked first, ANY hit → abstain, no score):** (a) data completeness below the KPI's `data_quality_requirements.min_completeness` (churn 0.90), (b) insufficient history — from detection's `insufficient_history` flag (21 days / 3 months per `sparse_history` config), (c) contradictory signals — deterministic rule: two opposing quantified drivers each ≥20% of gross driver magnitude with net <50% of gross (future-proofing hook; does not trigger on current data).
  - Sparse-history flags (Sports & Outdoors, 11/21 days) become explicit `abstain` results with `abstain_reasons=["insufficient_history"]` and the contract's label message — a distinct, visible state, not "no anomaly".
  - Freshness feeds in from `reconciliation.source_freshness` via the KPI's primary source; `analyze(as_of_date=...)` exercises the staleness dimension (verified: as-of 45 days after data end → staleness 1080h → Revenue capped to Low with score 0).
- Verified against the synthetic data (27 results): Week 7 Revenue May 13 → **medium** (business_explained 72.7%, arithmetic 100.0%); Week 7 Gross Margin → **high** (100.0%); Week 7 Units → **medium** (50.0%); **June churn → abstain** (completeness 70.2% < 90%); **Sports & Outdoors → abstain** (insufficient history 11/21); May churn → abstain (1 prior month < 3); early Units anomalies (12/20 prior days) → abstain (insufficient history). All 27 results `json.dumps`-clean; every assertion script passed.

### Key decisions made
- **Arithmetic ≠ business explained:** the volume drop is the "unknown cause" (competitor promo) so Week 7 Revenue is Medium, not High, despite PVM = 100%. Weights (1.0 / 0.5 / 0.0) are deliberately coarse, deterministic, documented in code, and produce the Phase 4 log's promised "medium confidence due to the unexplained volume driver".
- **Level = contract membership test, top-down** (all criteria must pass); `score` is a secondary weakest-link metric for display/ranking, not the level source — a Medium due to 100h staleness keeps its contract-correct badge.
- **History depth = prior periods at detection time** (`data_points_used`), matching detection's own sparse-history bar — avoids the "21 days vs minimum 21" off-by-one ambiguity and keeps the abstain message truthful.
- **Staleness beyond 720h floors to Low (deliberate design decision, not a default):** Abstain is reserved for broken evidence (data-quality failure, insufficient history, contradictory signals); stale-but-present data still carries a usable signal ("here's what we found, trust it less because it's old"), so staleness alone caps at Low with score 0. The contract lists no staleness abort trigger and none will be added.
- Attribution weights live in `confidence.py` as a documented table rather than in the contract, to keep Phase 5 self-contained; they could be promoted into `kpi_contracts.yaml` later if the contract should own them.
- Per-category anomalies from `detect_by_category()` are not scored (they are not part of `DetectionResult`); only per-category *sparse flags* are. Aggregates are scored — sufficient for the brief's scenarios.

### What remains
- Phase 5 is fully complete per Section 8 (High/Medium/Low/Abstain logic, churn abstain, new-product insufficient history). No open issues.
- Future: Phase 8 narration will consume `ConfidenceResult` messages/reasons; Phase 11 UI will render the badge + threshold transparency.

### Next phase (pending confirmation)
- Phase 6 — Access Control (persona → KPI/column permission filter enforced before narration; must block Gross Margin % for Category Manager and log the block)

---

## Iteration Log — Phase 6 (Access Control) — 2026-08-26

### What was done
- Built `backend/engine/access_control.py` (placeholder → full module):
  - **`AccessDecision`** dataclass: persona, kpi_name, allowed, action (`allowed`/`blocked`), human-readable reason, ISO-8601 UTC timestamp, `source` (provenance of the rule), `restricted_columns` (stripped columns, empty for current dataset). JSON-serializable.
  - **`AccessLogStore`** — SQLite audit log at `backend/data/raw/access_log.db` (gitignored via `*.db`). Schema: `id, timestamp, persona, kpi_name, action, allowed, reason, source, restricted_columns` + index on (persona, kpi_name). `fetch(limit, persona, kpi_name, action)` returns newest-first plain dicts for the API/UI. Persists across store instances (verified by reopening the DB).
  - **`PermissionGuard`** (constructed per persona + request): `check_kpi()` → AccessDecision (logged by default), `allowed_kpis()`, `filter_kpis()` (deduped, denies always logged), `filter_results()` — gates a `ConfidenceResultSet` to the persona's accessible KPIs **before narration** (local import keeps the module dependency-light), and `apply_column_filter()`/`restricted_columns_for()` — optional column-level redaction driven by a per-KPI `column_restrictions` contract block (none declared in the YAML today → no-op, mechanism ready).
  - **`enforce_access()`** convenience one-shot API.
  - Zero hardcoded permission lists: everything resolves through `ContractStore.is_accessible()` / `get_kpis_for_persona()` / the contract's `persona_access` (and optional `column_restrictions`). Unknown persona and unknown KPI both **fail closed** (blocked + logged + reason).
- Verified end-to-end against the synthetic pipeline (detection → decomposition → confidence → guard):
  - **Event 4 scenario:** Category Manager → `Gross Margin %` returns `allowed=False, action=blocked`, reason names the contract as source (`persona_access lists: CFO`), UTC timestamp captured, one `access_log` row (reopen persistence confirmed). ✅
  - **CFO** → all 4 KPIs allowed (27/27 results). **Category Manager** → `filter_results(analyze(...))` returns 22/27 results; all 5 Gross Margin % results (4 anomalies + 1 Sports & Outdoors sparse flag) are excluded from the payload and one deduplicated block is logged. ✅
  - Fail-closed: persona `Hacker` (not in contract) and KPI `Secret KPI` both blocked + logged. ✅
  - `filter_kpis()` dedupes to 1 block for repeated `Gross Margin %` requests. `apply_column_filter()` no-ops on current contract. All decision/log/payload JSON serialization checks pass; module compiles.
- Committed to `arena/01a03d54-vortex-vanguard-sugandhkumar` and pushed (branch-only; main untouched).

### Key decisions made
- **Gate before narration, enforced at the results level:** `filter_results()` strips blocked KPIs from the `ConfidenceResultSet` the LLM payload would be built from — blocked KPI data never reaches the narration layer (explicitly also true for sparse-history flags of blocked KPIs).
- **Denials are never dropped:** bulk filters dedupe per KPI per call to avoid log flooding, but every denial is persisted — the UI's "blocked" state must always be auditable.
- **Log DB path** defaults to `backend/data/raw/access_log.db` (overridable in the constructor); no new dependency (stdlib `sqlite3`), and `backend/data/raw/*.db` is already gitignored.
- **Column-level filtering is contract-driven but currently unused:** the contract has no sensitive columns, so `column_restrictions` is an implemented hook, not a hardcoded denylist; nothing was added to the YAML.
- **Fail-closed posture:** unknown persona/KPI → block, because the contract is the only source of truth and absence of a rule must not grant access.

### What remains
- Phase 6 is fully complete per Section 8 (persona → KPI permission filter, GM% blocked for Category Manager, block logged). No open issues.
- Phase 11 UI will read `access_log` rows (persona/kpi/action/reason/timestamp) to render the blocked state; no UI code yet.

### Next phase (pending confirmation)
- Phase 7 — Action Recommendation (driver → controllable lever → action → expected impact → owner → confidence → monitoring plan, as a lookup/rules table, not LLM-generated)

---

## Iteration Log — Phase 7 (Action Recommendation) — 2026-08-26

### What was done
- Built the Phase 7 rules table + loader + engine (all deterministic, no LLM):
  - **`backend/contracts/action_rules.yaml`** (new) — 15 rules + a `defaults` fallback block. Each rule: `id, kpi, driver, component (optional), direction (optional), categories (optional), gates, lever, owner, actions, expected_impact (recovery factors + note), monitoring, actionable`.
  - **`backend/contracts/action_rules_loader.py`** (new) — `ActionRulesStore` with YAML validation (required fields, unique ids, valid directions, non-empty actions, recovery min/max, defaults block) and `ActionRulesValidationError` / `ActionRuleNotFoundError`.
  - **`backend/engine/actions.py`** (new) — `ActionRecommendation`, `SuggestionSet`, `ActionPlan` dataclasses (JSON-safe); `match_rule()` specificity scorer; `recommend_anomaly()`, `recommend_all()`, `run_actions()` pipeline (detection → reconciliation → decomposition → confidence → actions).
- **Matching design (no if/else chains):** for each `DriverContribution`, candidate rules are scored by the number of specified fields that match (`kpi`, `driver`, `component`, `direction`, `categories`); highest score wins, ties break by YAML declaration order, gates (≥5% of the movement) filter before scoring, and no match falls back to `defaults` (investigate & monitor, not actionable). Adding an action = adding a YAML row.
- **Expected impact is math:** `|driver contribution| × recovery factor range` (per rule), unit from the contract's materiality `impact_unit` (USD / units / percentage_points); correlation & informational drivers get `basis: not_quantified` with a note.
- **Confidence inherited from Phase 5:** status + score attached per recommendation, plus the driver's attribution weight from `ConfidenceResult.attribution_detail`. Abstained anomalies get `actionable: false` on business levers (with an explicit `abstain_note`); operational recovery (data-quality repair) stays actionable — fixing broken evidence is always safe.
- **Placeholder rendering** (`{category}`, `{cohort}`, `{cohort_rate}`) is bounded token substitution from pre-computed driver detail (dominant PVM category / highest-churn tenure cohort ≥50 members) — never LLM text.
- Verified end-to-end (Week 7 Revenue + Gross Margin + Units Sold + June churn):
  - Revenue May 13: price → `revenue_price_cut_impact` (impact 1212.63–1818.95 USD, conf medium, attribution 1.0); volume → `revenue_volume_drop` (1562.0–2603.34 USD, attribution 0.5, actionable); mix → `revenue_mix_interaction` (not actionable). ✅
  - Gross Margin May 13: price → `margin_price_compression` (1.49–2.38 percentage_points, conf high, attribution 1.0); cost residual (+0.06pp, 1.9% of movement) → defaults investigate & monitor. ✅
  - Units May 13: Electronics → `units_electronics_decline` (beats generic `units_category_decline` on the specificity tie-break); Grocery/Apparel → generic decline rule; Home & Kitchen counter-movement → gain rule. ✅
  - June churn (abstain): data-quality recovery actionable; retention rec rendered with "3-6mo cohort (22.1%)" but flagged actionable=false + abstain note. ✅
  - Coverage: 24 anomalies → 78 recommendations (51 actionable); only 9 fall to `defaults`, ALL negligible (<5% of movement: 0–4.3%). Unit tests for paths absent from demo data (cost ≥5% → `margin_cost_drift`; marketing correlation rule; defaults fallback) + all loader negatives. JSON-serializable; `py_compile` clean.
- Found & fixed during testing: loader initially accepted `defaults.actions: []` (rules got the non-empty check, defaults didn't) → now rejected; also normalized all rule gates from mixed abs-unit/abs-$/pp floors to the single uniform `min_contribution_pct: 5`.

### Key decisions made
- **Gates = "a driver must be ≥5% of the movement to earn a lever-specific recommendation"** — one uniform rule across all KPIs. Below that, the `defaults` investigate-&-monitor fallback (traceable, non-actionable) is the correct output, not a bug (verified: all defaults hits are 0–4.3% share).
- **Rules table lives in `contracts/`** next to the semantic contract (single source of truth), kept separate from `kpi_contracts.yaml` so contract validation stays focused; loaded by its own validated store.
- **Specificity tie-break = YAML order** — deterministic and reviewable; the Electronics rule is declared before the generic Units rule so a category-specific recommendation wins for Electronics.
- **`expected_impact` uses contract materiality units** (`impact_unit`) — "percentage_points" for GM/churn, USD for revenue, units for units — so the UI doesn't need unit mapping.
- **Cost rule only fires when cost is material (≥5%)**: Week 7 GM's +0.06pp residual is intentionally investigate-&-monitor; a cost-driven margin anomaly (not in this dataset) would get the procurement rule (unit-tested).
- Access-control filtering of the ActionPlan is deferred to the Phase 12 API layer (Phase 6 already gates at the results level; recommendations carry kpi_name/period so they filter the same way).

### What remains
- Phase 7 is fully complete per Section 8. No open issues.
- Phase 8 narration will render `ActionPlan` objects (lever/owner/actions/impact/monitoring/confidence) as persona-specific prose; Phase 12 API will order: access filter → narration.

### Next phase (pending confirmation)
- Phase 8 — LLM Narration Layer (provider-agnostic `llm_client.py`, Ollama default with mock-mode fallback, system prompt forbidding facts not in the JSON, persona-conditioned CFO vs Category Manager templates)

---

## Iteration Log — Phase 8 (LLM Narration Layer) — 2026-08-26

### What was done
- **IMPORTANT (environment):** this agent runs in a cloud sandbox with NO access to the user's local `ollama serve`. All testing below is **mock-mode only**. The real Ollama path (`minimax-m3:cloud`) is implemented but NOT claimed as tested — the user will test it locally and report back before this phase is confirmed.
- Built `backend/narration/llm_client.py` (placeholder → full module):
  - `LLMProvider` ABC (provider-agnostic: `complete(prompt) -> LLMResponse`, `is_available()`); any OpenAI-compatible backend fits.
  - `OllamaProvider` — real backend via `POST /api/chat` at `OLLAMA_BASE_URL` (default `http://localhost:11434`), `OLLAMA_MODEL` (default `minimax-m3:cloud`), temperature 0.2, `num_predict` 1024, 60s timeout; `is_available()` pings `/api/tags` (no tokens generated); raises `ProviderUnavailableError` on failure. **Never invoked in this environment.**
  - `MockProvider` — deterministic narrator that parses the `{facts}` JSON out of the prompt and builds a placeholder, clearly-labeled `[MOCK]` narrative **solely from those facts** (no arithmetic, no invented facts), persona-differentiated (CFO vs Category Manager templates + a distinct lens close). Usage metadata is labeled `source: mock_estimate`, `mock: true`.
  - `LLMClient` facade — selection priority: `LLM_MOCK_MODE=true` → mock; Ollama reachable → Ollama; else → mock (auto-fallback). `from_env(persona)`, `describe()` for telemetry/UI, `complete()`.
- Built `backend/narration/prompts.py`:
  - **Hybrid system prompt** (intro + "ALLOWED FACT SOURCES" fact bible + 8 strict rules + per-persona addendum): the fact bible names every exact field the model may reference; the rules forbid computing/rounding/estimating/inferring numbers, forbid causal claims not in the JSON, forbid inventing thresholds/targets/owners/actions, require labeling correlation as non-causal, require explicit abstain language when status is abstain, and mandate a **"VERIFICATION PASS"** (re-read output; delete any claim not in the facts JSON).
  - `pipeline_to_facts(confidence_result, suggestion_set, anomaly, persona)` — the deterministic fact-map builder: flat JSON-safe `facts` with `grounded_assertions` (every number + its `source_path` provenance: e.g. `drivers[0].contribution_value`, `recommendations[0].expected_impact.value_min`). This is the machine-checkable oracle the strictness test asserts against.
  - `build_prompt(facts, persona)` — no numeric literals appear anywhere except inside the facts JSON slot (verified: instruction portion contains only rule enumeration 1-8 and persona length guidance 2-4/3-5, no metric values).
  - `narrative_is_grounded(text, facts)` / `extract_numbers` / `allowed_numbers` / `allowed_string_facts` — strictness oracle for mock output.
- Verified (mock mode, full Phase 5/6/7/8 pipeline):
  - 3 scenarios × 2 personas (Revenue May 13, Gross Margin % May 13, June churn abstain): all narratives **grounded=True** (zero numbers outside the allowed fact set) and **persona-differentiated** (CFO vs Category Manager text differs; correct lens cue present). ✅
  - **Auto-fallback proven**: `OllamaProvider.is_available()` → False in this sandbox; `LLMClient.from_env()` with `LLM_MOCK_MODE=false` falls back to mock; `auto_fallback=False` raises `ProviderUnavailableError` cleanly. ✅
  - Sparse-flag fact path (Sports & Outdoors, no anomaly/no recommendations) works and stays grounded. ✅
  - **Phase 6 × 8 integration**: Category Manager narratives cover all visible anomalies, every narrative grounded, and **no "Gross Margin" content ever appears** (blocked KPI never reaches the LLM); CFO sees all 27 incl. GM. ✅
  - Env defaults match `.env.example` (`http://localhost:11434` / `minimax-m3:cloud`); `py_compile` clean across backend.
- Bugs found & fixed during mock testing: (a) `MockProvider.extract_facts` anchored on the first `{` which matched template braces (`{value_min,...}`) — now anchors on the `FACTS_JSON:` marker with balanced-brace parsing; (b) `_get(d, 'driver_name', 'driver')` passed an extra path key causing empty driver names/values — switched to keyword `default=`; (c) number extractor swallowed trailing punctuation commas and split dates into fragments — tokens now `rstrip(",")` and date/string fragments match against allowed string facts.

### Key decisions made
- **"The specification is the payload":** the prompt contains no numeric literals outside the injected JSON, so the narrator physically has nothing to compute from; the fact bible + verification pass define the allowed evidence set, and `grounded_assertions` (with source_path provenance) makes the constraint machine-checkable without relying on LLM honesty.
- **Mock must be a faithful test oracle, not a stub:** it narrates from the same `facts` dict a real model receives, is persona-differentiated, and is always labeled `[MOCK]` / `mock: true` so the UI can never confuse it with real LLM output (also satisfies the brief's LLM-vs-non-LLM visibility requirement).
- **String facts (confidence.message, abstain reasons, actions, monitoring, lever/owner, period) are part of the allowed evidence:** numbers inside them (e.g. "70.2%", "90%") were computed by deterministic code, so the oracle treats tokens appearing within allowed strings as grounded.
- **Mock usage tokens are labeled `mock_estimate`** — never presented as real token counts (Phase 10 telemetry will consume Ollama's real `prompt_eval_count`/`eval_count` from response metadata).
- Real-provider response shape uses Ollama's `/api/chat` fields (`message.content`, `prompt_eval_count`, `eval_count`); OpenAI-compatible providers can be adapted via the same `LLMProvider` interface (swap in `.env` only, per the Phase 0 spec-change decision).
- Attendance to Section 4's "visible LLM vs non-LLM breakdown": every narrated unit carries `provider` + `mock` flags now; the API/UI wiring for this comes in Phases 10-11.

### What remains
- **Phase 8 code complete; NOT confirmed** — the real Ollama path (local `ollama serve` + `minimax-m3:cloud`) must be tested by the user locally: `cd backend && python -c "from narration.llm_client import LLMClient; print(LLMClient.from_env('CFO').describe())"` should show `provider=ollama, mock=False`. Pending that report, treat Phase 8 as unverified-and-unlocked.
- The narration endpoint (FastAPI route wiring fact-map + persona + access filter) is deferred to Phase 12 (API layer already has `/health` only).

### Next phase (pending confirmation)
- Phase 9 — Feedback Loop (thumbs up/down capture per insight, SQLite log, and an explanation of how it would feed confidence weighting over time)
