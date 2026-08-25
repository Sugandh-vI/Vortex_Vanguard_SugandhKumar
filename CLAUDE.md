# CLAUDE.md — BusinessIntelligence.ai Prototype

**Project:** KPI Intelligence-to-Action Engine — Accenture Innovation Challenge 2026, Round 2, Problem Track 3
**This file is the single source of truth for this project.** Read this fully before writing any code.

---

## 1. Context — What This Project Is

We are building a prototype for the **BusinessIntelligence.ai** track of the Accenture Innovation Challenge Round 2. The brief asked us to design and demonstrate a working prototype of a **KPI intelligence-to-action engine** — a tool that explains what changed in a business metric, identifies likely root causes, and recommends next steps in plain language, aimed at solving the real-world problem that businesses track KPIs across fragmented systems with different refresh cadences, and the "right" explanation for a movement depends on who's asking.

### The core design principle (this is the most important rule in this whole document)

**The LLM is NEVER the source of quantitative truth.** All detection, calculation, decomposition, scoring, and access control must be done with deterministic code (math/stats/rules). The LLM's ONLY job is to take already-computed, structured JSON output and turn it into readable, persona-specific prose — and it must not introduce any fact, number, or claim that isn't present in the JSON it was given. This separation is what the judges are explicitly testing for, and it must be visibly demonstrable at every step (we will log/display which parts of each output came from code vs. from the LLM).

### Budget constraint — read this carefully

This project must be built with **$0 cost**. No OpenAI or Anthropic API keys are available or should ever be used in this codebase. The only LLM calls allowed are via the **Groq API** (free tier), using an open model such as `llama-3.3-70b-versatile`. If Groq is unavailable or a key isn't yet supplied, the system should still run in a "mock LLM" mode that returns a clearly-labeled placeholder narrative, so the rest of the pipeline is always testable without a key.

---

## 2. The Approach We Chose (and why)

We evaluated four architecture options and chose the following, deliberately rejecting a full multi-agent orchestration approach because it introduces LLM rate-limit and reliability risk on a free API tier during a live demo.

**Chosen approach: "Deterministic Core, LLM Narrator."**

- Detection, reconciliation, driver decomposition, confidence scoring, and access control are all done in plain Python (pandas/numpy/stats) — no LLM involved.
- A single, tightly-scoped LLM call (via Groq) takes the final structured JSON output and renders it into persona-specific natural language, constrained by a system prompt that forbids introducing facts not present in the JSON.
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
- **LLM:** Groq API via the `groq` Python SDK. Model: `llama-3.3-70b-versatile` for narration; a mock-mode fallback must exist for when no `GROQ_API_KEY` is set.
- **Frontend:** React + Tailwind CSS, built as a lightweight custom "mini Power BI" dashboard — KPI trend charts, an insight feed with confidence badges, a persona switcher, and a telemetry panel. (No third-party BI tool is used — we are building this ourselves.)
- **Config/secrets:** `.env` file for `GROQ_API_KEY`, loaded via `python-dotenv`. Never hardcode keys. `.env` must be in `.gitignore`.
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
      llm_client.py                     # Groq client wrapper + mock-mode fallback
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
- Groq client wrapper with mock-mode fallback.
- System prompt strictly constraining the model to only use facts present in the JSON payload it's given.
- Persona-conditioned templates (CFO vs Category Manager tone/depth).

### Phase 9 — Feedback Loop
- Simple thumbs up/down capture per insight, logged (SQLite table is fine).
- A small explanation in the UI/docs of how this would feed back into confidence weighting over time (does not need real retraining for the prototype).

### Phase 10 — Telemetry
- Wrap the LLM call and the analytics pipeline to record latency, token usage (from Groq response), and an estimated cost-at-scale figure, exposed via an API endpoint and shown in the UI.

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
- Only Groq is used for LLM calls, with a working mock-mode fallback.
- LLM never computes numbers — only narrates already-computed JSON.
- No Docker.
- Build and confirm one phase at a time — do not jump ahead.
- Append an iteration log entry to this file at the end of every session, in the exact format in Section 9.

---

## Iteration Log — Phase 0 (Project Setup) — 2026-08-25

### What was done
- Created the full folder structure exactly as specified in Section 6: `/backend/data/`, `/backend/data/raw/`, `/backend/contracts/`, `/backend/engine/`, `/backend/narration/`, `/backend/api/`, `/frontend/`, `/docs/`.
- Created placeholder files for all future modules: `detection.py`, `reconciliation.py`, `decomposition.py`, `confidence.py`, `access_control.py`, `actions.py`, `telemetry.py`, `llm_client.py`, `prompts.py`, `generate_synthetic_data.py`, `kpi_contracts.yaml`.
- Created `requirements.txt` with: fastapi, uvicorn, python-dotenv, pandas, numpy, sqlalchemy, groq, pyyaml, httpx.
- Created `.env.example` with `GROQ_API_KEY=` placeholder.
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
