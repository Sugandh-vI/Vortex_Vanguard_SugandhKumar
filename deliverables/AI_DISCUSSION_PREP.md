# AI Discussion Prep — BusinessIntelligence.ai

Spoken-word rehearsal notes for Accenture Innovation Challenge 2026, “Solution Discussion with AI.”
Problem Track 3. Team Vortex Vanguard. Prototype: KPI Intelligence-to-Action Engine.

Study this out loud. Short paragraphs. Numbers you can say without looking.

---

## 1. 60-second project pitch

Say this, then stop talking.

> Businesses track KPIs across systems that don’t share a grain or a refresh cadence. When a metric moves, the “right” explanation depends on who’s asking — a CFO wants dollar impact and margin, a Category Manager wants volume and next steps. Most LLM dashboards fail here because the model becomes the analyst: it invents drivers, rounds numbers, and sounds confident when the data is broken.
>
> We built the opposite. A deterministic Python core does every quantitative job — reconcile three sources, detect material movements, decompose them, score confidence, gate access, recommend actions, and record feedback. The LLM never computes a number. It only narrates a pre-computed JSON payload, under a system prompt that forbids inventing facts. We don’t take that on trust: a grounding validator extracts every number in the narrative and fails the card if anything isn’t in that JSON.
>
> What makes this defensible is honesty under pressure. Week 7 revenue is 100% explained arithmetically by price-volume-mix, but we score it Medium because the volume drop is measured and the cause is not in our data. June churn *looks* like it jumped to 17%, and we abstain because completeness is 70%. A new category with 11 days of history gets “insufficient history,” not a fake z-score. Gross Margin is CFO-only, blocked before the LLM ever sees it.
>
> So the prototype isn’t “ChatGPT on a KPI.” It’s an intelligence-to-action engine with a narrator that cannot be the source of truth.

If they ask you to go shorter: **problem is fragmented KPIs + persona-dependent explanations; principle is LLM never computes; proof is grounding + abstain + access control.**

---

## 2. Architecture walkthrough in plain English

Walk the pipeline as a story, not a diagram. Pause after each stage. If they interrupt, you can drop into any stage.

**Setup.** 90 days of synthetic data, April 1 to June 29 2024. Three sources, three grains: daily `sales_transactions`, weekly `marketing_spend`, monthly `customer_roster`. Four KPIs: Revenue, Units Sold, Gross Margin % (CFO only), Customer Churn Rate. Two personas. A versioned YAML contract is the single source of truth for formulas, lineage, materiality, access, and confidence thresholds.

### Reconciliation

“First we make the sources talk to each other. Weekly marketing is spread uniformly across seven days — we document that as a prototype choice, not a claim of day-of-week reality. Monthly churn stays monthly; we never interpolate a monthly metric into a fake daily series. We compute freshness per source in hours. That freshness later caps confidence: stale-but-present data can still speak, it just speaks quieter.”

### Detection

“Daily KPIs use a 21-day rolling z-score, current day excluded from its own baseline so the spike can’t hide itself. Flag if |z| > 2 *and* the movement is material — 5% or $5,000 for revenue, whichever fires. Monthly churn only has three months, so z-score is the wrong tool; we do period-over-period and carry completeness along for the ride. Sparse history is an explicit state, not an empty feed. Sports & Outdoors has 11 days; the contract wants 21; we raise a flag rather than invent a baseline.”

### Decomposition

“Method is chosen from the contract, not from the model.

- Revenue → classic price-volume-mix: price effect (P1−P0)×V0, volume P0×(V1−V0), mix the interaction.
- Units → additive contribution by category.
- Margin → counterfactual: what would GM% be if only price changed.
- Churn → completeness check plus tenure cohorts.
- Marketing → Pearson correlation, labeled ‘supporting signal, not causation,’ and it is *excluded* from the explained-% sum.”

### Confidence

“This is the intellectual center of the prototype. Arithmetic explained % is not business explained %. PVM always sums to 100% — that’s accounting, not understanding. Each driver gets an attribution weight: 1.0 if we know the cause from the data (a price cut), 0.5 if we measured it but don’t know why (volume), 0.0 if it’s mechanical or informational (mix interaction, correlation, completeness). Business-explained is the weighted share. High / Medium / Low are a top-down contract test on explained %, freshness, and history. Score is the weakest of those three dimensions. Abstain is checked first: completeness below gate, insufficient history, or contradictory drivers. Abstain has no score. Stale data alone does *not* abstain — it floors at Low. Broken evidence is different from old evidence.”

### Access control

“Persona permissions resolve only from the contract. Unknown persona or unknown KPI fails closed. Category Manager requesting Gross Margin is blocked, logged to SQLite, and the blocked KPI is stripped from the JSON before narration. The LLM cannot leak what it never received. The UI shows a lock card with the reason and the contract source.”

### Actions

“Not generated by the LLM. A YAML rules table: driver → lever → owner → actions → monitoring. Matching is specificity scoring, not if/else. Expected impact is math: |driver contribution| × a recovery-factor range. If we abstained, business levers become non-actionable; data-quality repair stays actionable — fixing broken evidence is always safe to recommend.”

### Narration

“One tightly scoped LLM call. Hybrid system prompt: fact bible + eight hard rules + persona addendum. CFO is dollar-first and short; Category Manager is operational and a bit longer. Temperature 0.2. Then a machine check: every numeric token in the output must exist in the facts JSON, after normalizing currency, commas, and decimal padding. Empty or truncated replies fail. Real vs mock is labeled on the card. Mock is not a stub — it narrates from the same facts dict.”

### Feedback

“Thumbs up/down per insight per persona. It is a *trust label*, never evidence. Phase-5 confidence does not move. Abstain stays abstain. Factor is 2 × Beta(1,1) posterior mean of the up-rate for that (KPI × level × persona), clamped 0.5–1.5. Zero votes → factor exactly 1.0, so no-feedback behavior is identical to pre-feedback. Feed rank = score × factor; abstains sink last. Systematic down-votes are a calibration signal for a human to edit the YAML, not a cue to retrain a model.”

### Telemetry

“We wrap the pipeline, we don’t patch it. Five deterministic stages timed. Token counts come from Ollama response metadata, never estimated on our side. Mock tokens live in a separate bucket and are never billed. Default cost is $0 because we are on free-tier Ollama, with an at-scale projection knob if you plug in paid rates. The UI shows LLM vs non-LLM on every card and in the panel.”

**One-liner if they want the whole thing in a breath:** *reconcile grains → detect with z-score and materiality → decompose with the right method → score business-explained confidence and abstain when evidence is broken → fail-closed access → rules-based actions → grounded narration → feedback re-ranks, never rewrites truth → telemetry proves the split.*

---

## 3. “Why did you choose X over Y”

Rehearse these as answers, not essays. Lead with the choice, then one reason that would matter to a judge, then the honest cost.

### Why “Deterministic Core, LLM Narrator” over multi-agent orchestration

We evaluated four architecture options. The one we rejected hardest is a planner/analyst/critic multi-agent stack.

- Live demo on a free-tier API: rate limits and flaky agents will fail you in front of judges.
- More importantly, once several LLMs are allowed to “think,” you cannot prove which number came from math.
- The brief *explicitly* asks for a visible LLM vs non-LLM breakdown. A deterministic core makes that a property of the system, not a slide.

Cost we accepted: the narrator cannot discover a driver that isn’t in the JSON. That’s a feature. If a cause isn’t in the data, we say so.

### Why Ollama (and not a paid OpenAI/Anthropic API)

Budget was $0. No paid keys anywhere, ever.

- Started toward Groq, switched to Ollama: `ollama serve` + `minimax-m3:cloud`, no separate API key.
- Client is provider-agnostic. Swap `.env`, keep the interface. Provider is a config detail, not an architecture bet.
- Mock-mode fallback is mandatory. Pipeline is always testable if the model is down.

Cost we accepted: real-model latency 13–45 seconds per narrative, and reasoning models can burn the token budget on thinking. We raised `num_predict` to 4096 and added a thinking-off switch after we saw empty replies.

### Why rolling z-score over STL / Isolation Forest / “just % change”

Phase 3 allowed rolling z-score *or* STL residuals. We chose rolling z-score.

- 90 days, one scripted shock: STL seasonal extraction is overkill and harder to explain live.
- Z-score answers “is this unusual versus recent history?” in one number judges can inspect.
- Window = 21 days, same as the sparse-history bar. Threshold = 2.0 (~95th percentile). Current day shifted out of the baseline.
- Monthly churn: z-score is the *wrong* method with n=3, so we didn’t force it. Period-over-period plus completeness.

Why not % change alone: a 5% move on a $200 day is noise; a 3% move on $57k is real money. Materiality is OR of % and absolute impact.

Why not Isolation Forest: opaque, needs a story for every feature, bad oral-defense tool.

### Why price-volume-mix (and not a regression / SHAP / LLM-proposed drivers)

Revenue is price × volume. PVM is the identity:

`ΔR = (P1−P0)×V0 + P0×(V1−V0) + (P1−P0)×(V1−V0)`

- It *has* to add up. That’s how we can say “arithmetically 100%, business-explained 72.7%” without hand-waving.
- Drivers come from the contract (`decomposition_method: price_volume_mix`), not from the model “noticing” Electronics.
- SHAP on 90 days of synthetic data would look sophisticated and prove nothing.
- LLM-proposed drivers are exactly the failure mode the brief is hunting.

Other KPIs get the method that fits: contribution for additive units, counterfactual margin split, cohorts + completeness for churn.

### Why arithmetic-explained ≠ business-explained

This is the line to land.

> PVM explaining 100% of the dollars is necessary and not sufficient. It means every dollar is *accounted for*. It does not mean we know *why* volume fell.

Week 7: we injected a 10% Electronics price cut (known, in the sales table) *and* a 20% volume drop (competitor promo, **not in any table**). If we treated arithmetic 100% as High confidence, we’d be lying with math.

Weights, deliberately coarse:

| Weight | Meaning | Example |
|---|---|---|
| 1.0 | Cause is in the data | price_effect, unit_price → margin |
| 0.5 | Measured, cause unknown | volume_effect, category contribution, cost residual |
| 0.0 | Mechanical / informational | mix interaction, correlation, cohort, completeness |

Week 7 Revenue: |−3,031.58×1.0 + −5,206.68×0.5 + 489.25×0.0| / 7,749 = **72.7% → Medium**. Margin on the same day is **High**, because the price cut *is* the cause of the GM compression.

### Why fail-closed access control (and not fail-open / LLM redaction)

- Contract is the only source of permission lists. Zero hardcoded roles in Python.
- Unknown persona (`Hacker`) and unknown KPI (`Secret KPI`) deny.
- Enforcement is *before* narration. Redacting in the prompt is theater; models leak.
- Every denial is logged. UI lock card cites `kpi_contracts.yaml:persona_access`.
- Column-level restrictions exist as a hook and are unused — we didn’t fake a column we don’t have.

Cost: a missing YAML row blocks rather than degrades. For a judged security scenario, that’s the right bias.

### Why Beta(1,1) feedback weighting (and not retraining / multiplying raw up-rate)

The brief asks to *learn from feedback*. It does not ask us to pretend 12 thumbs retrain a model.

- Feedback is a trust label on (insight, persona). It never mutates numbers or Phase-5 status.
- `factor = 2 × (ups+1)/(ups+downs+2)`, clamped [0.5, 1.5].
- Beta(1,1) is a uniform prior: with no votes, posterior mean is 0.5, times 2 is **exactly 1.0**.
- One vote cannot swing the feed. Two CM downs clamp at 0.5. One CFO up → 1.333.
- Abstain votes are recorded (did the user *want* us to abstain?) but excluded from the factor — opinion cannot repair broken evidence.
- Calibration path if “high” keeps getting downs: a human edits contract thresholds / attribution weights. YAML change, not a retrain.

### Why no Docker

Local prototype, screen-recorded demo, venv + `requirements.txt`. Docker would have been ceremony. Optional packaging was explicitly out of scope at Phase 12.

If they push “how would you ship it?”: containerize API + worker, put contracts in config, swap SQLite for Postgres, put Ollama or a hosted compatible endpoint behind the same client. That’s a deployment story, not a missing architecture.

### Other decisions worth having in your pocket

**21-day window, not 14.** Sparse bar and detection window share a number. Sports & Outdoors at 11 days is cleanly under, not borderline.

**Revenue materiality $5,000 not $10,000.** Daily baseline ~$56k. $10k would need an ~18% swing. $5k ≈ 9% of baseline, catches Week 7 without flagging noise.

**Materiality is OR, not AND.** Large-%/small-$ and small-%/large-$ both matter.

**Uniform /7 marketing spread.** Production would weight by day-of-week. Prototype documents the shortcut.

**Fixed cost per unit, not % of selling price.** So the Week 7 price cut actually compresses margin — that’s the CFO signal.

**Staleness floors to Low, never Abstain.** Abstain is for broken evidence. Old data is still data; we just distrust it.

**History = prior periods at detection time** (`data_points_used`). Avoids off-by-one vs the 21-day bar.

**Attribution weights live in `confidence.py`, not the YAML.** Kept Phase 5 self-contained. Honest future: promote them into the contract so business owns them.

**Action matching = specificity, not if/else.** Add a lever = add a YAML row. Ties break by declaration order (Electronics rule sits above generic units).

**Action gates = ≥5% of movement.** Below that, investigate-and-monitor defaults. All default hits in the demo are 0–4.3% share.

**Expected impact is |contribution| × recovery range**, unit from the contract. Not LLM prose.

**On abstain, only operational recovery is actionable.** June churn: “fix the roster sync” yes; “launch a retention campaign” no.

**Mock is a faithful oracle, labeled `[MOCK]`.** Demo ran mock because 49 real calls would take many minutes. Real path is tested: 6/6 grounded against live Ollama.

**Empty narrative is a hard fail.** First real-Ollama run: empty string “passed” grounding because no numbers = no violations. We now require ≥10 words and treat `done_reason=length` as fail.

**Grounding matches magnitude, not string format.** `$7,749.00` vs `-7749.0` was a validator bug, not a hallucination. Sign-consistency still flags `+$3,031` on a negative fact.

**Telemetry wraps, doesn’t patch.** Same entry points as the uninstrumented pipeline. Tokens only from response metadata. Cost default $0, projection from *real* call averages only.

**Startup pipeline (~0.6s) + lazy narration, cached forever.** Votes re-rank with zero extra LLM calls. Confidence on a vote is derived server-side — the client cannot forge the badge into the log.

**Score × factor ordering replaced detection-priority ordering.** Deliberate Phase-9 wiring, not a regression.

**Recharts over custom SVG; no component library.** Bundle stays honest. Per-KPI “good direction” (churn up = bad).

---

## 4. Likely hard questions, with answers you can say

### “How is this different from just asking ChatGPT to explain a KPI?”

Three failures ChatGPT will happily commit, and we structurally cannot:

1. **Invent a number.** Grounding validator fails the card.
2. **Invent a cause.** Competitor promo is not in the JSON, so the narrator is forbidden from asserting it. We say volume is quantified and unexplained.
3. **Talk past broken data.** June churn looks like 17%. ChatGPT will explain 17%. We abstain at 70.2% completeness.

Also: persona is not a prompt vibe. Category Manager never receives Gross Margin in the payload. Access is not “please don’t mention margin.”

### “What happens if the LLM ignores your system prompt?”

Assume it will, some of the time.

- Grounding is *code*, not a request. Invented or recomputed numbers → `grounded=false`, violations listed, chip in the UI.
- Empty / truncated / reasoning-only output → hard fail (≥10 words, `done_reason` exposed).
- Causal claims without attribution are prompt-forbidden; we do **not** have a full natural-language NLI checker. Own that: numbers are machine-checked; “because of X” in words is a residual risk. Mitigation is a small allowed fact set and temperature 0.2.
- Blocked KPIs never enter the prompt, so ignore-the-prompt cannot leak Gross Margin to a Category Manager.
- Mock path proves the payload is sufficient without a model. Real path: 6/6 grounded, persona-differentiated, abstain rendered as abstain.

### “How would this scale to real enterprise volumes?”

Separate three things: analytics, narration, governance.

- **Analytics.** Current run is ~0.6s on 1,484 sales rows. Detection and PVM are O(days × categories) pandas. At warehouse scale you pre-aggregate daily KPI series in the warehouse (Snowflake/BigQuery), run z-scores on those series, and decompose only the material anomalies — not every raw transaction on every request. We already run the deterministic pipeline *once at boot* and serve from that result.
- **Narration.** That’s the real cost. Live Ollama was 13–45s and 2.7k–3.5k prompt tokens per insight. We already lazy-narrate per persona and cache by `insight_id`. At scale: narrate only the top-N material insights, batch, or switch the same provider-agnostic client to a cheaper hosted endpoint. Telemetry already projects cost at 1,000 calls from *real* token averages.
- **Governance.** YAML contracts and SQLite logs are prototype. Production: contract service, policy engine (OPA-style) on persona→KPI, append-only audit, row-level security in the warehouse so the engine never sees blocked columns.

Do not claim we tested a billion-row warehouse. Claim the *seams* are right: compute once, narrate few, gate before generate.

### “How do you validate the z-score threshold isn’t arbitrary?”

It *is* a choice, and we treated it as a contract-level choice, not a trained hyperparameter.

- 2.0 ≈ 95th percentile under a normal baseline. We wanted Week 7 (Revenue z=−3.53, GM z=−16.1) in, and not 24-anomalies-of-chaos across 90 days × 4 KPIs.
- We inspect the baseline: GM% daily std is **0.1812 pp**. A 2.92 pp drop is ~16× normal variation — the −16.1 is real, not a bug.
- Materiality sits *on top* of z-score, so a statistically weird $12 wiggle does not become an insight.
- Thresholds live in code defaults + contract materiality, both reviewable. Feedback that systematically down-votes a level is the calibration loop to revisit them.
- We did **not** do walk-forward precision/recall against labeled anomalies, because we *scripted* the anomalies. Own that: the threshold is justified by statistical convention + visual check + the scripted story, not by an ROC on production data. Next step: hold out real incidents, sweep 1.5 / 2.0 / 2.5, report precision at the feed cutoff.

### “Walk me through end-to-end for the Week 7 revenue anomaly.”

Memorize this sequence. Speak it slowly.

1. **Data (May 13–19).** Electronics selling price cut 10% (~$150 → ~$135). Cost per unit unchanged, so margin compresses on purpose. Units on Electronics also drop 20% — competitor promo, **not in any table**. Other categories keep ~5% noise.
2. **Reconcile.** Sales daily; marketing spread /7; freshness 0h at window end.
3. **Detect.** 21-day rolling mean of revenue ≈ **$57,146.52**. May 13 actual **$49,397.52**. Δ **−$7,749 (−13.56%)**, **z = −3.53**. Passes |z|>2 and materiality (5% and $5k). Ranked with GM (z=−16.1) and Units (z=−2.36).
4. **Decompose PVM vs prior 21 days.**
   - Price (known): **−$3,031.58 (39.1%)**
   - Volume (unknown cause): **−$5,206.68 (67.2%)**
   - Mix interaction: **+$489.25 (6.3%)**
   - Arithmetic explained: **100%**
5. **Confidence.** Weights 1.0 / 0.5 / 0.0 → business-explained **72.7%**. Fresh, 42 days of history. High wants ≥80% explained → **Medium, score 72.7**. Message says a material part is measured but cause unknown. We do *not* name a competitor.
6. **Access.** Both personas allowed on Revenue. GM on the same day is CFO-only.
7. **Actions.** Price → Pricing & Promotions, CFO owner, expected recovery **$1,213–$1,819**. Volume → Demand & Competitive Response, Category Manager, **$1,562–$2,603**, note: “assumes the cause is found.” Mix → not actionable.
8. **Narrate.** Facts JSON only. Grounding must accept `$7,749.00` as the same number as −7749. CFO leads with dollars; CM leads with volume/category.
9. **Feedback (demo).** Badge stays Medium / 72.7. CFO 👍 → factor **1.333**, effective **96.9**, rises in feed. CM 👎👎 → factor **0.5**, effective **36.4**, sinks. Same insight, two trust labels.
10. **Telemetry.** Decomposition is most of the ~0.6s pipeline. Narration is the slow/expensive bit, cached after first request.

### “What’s the weakest part of this system and how would you fix it?”

Pick one, own it, then the fix. Don’t list seven.

**Best single answer:** attribution weights are a coarse heuristic (1.0 / 0.5 / 0.0) living in code, not in the contract, and they are not learned.

Fix with more time: promote weights into `kpi_contracts.yaml` so finance owns them; start every driver at 0.5; let the Beta feedback table *propose* (not auto-apply) a weight change when a level is systematically down-voted; add an optional known-event calendar (price changes, promos) so “known cause” is data, not a method name.

**Runner-up if they already bought the weights story:** grounding does not check sign expressed only in words (“an increase of $7,749” on a decrease). Fix: require the narrative to copy `direction` verbatim, or run a tiny constrained decoder / JSON-mode narrator.

### “Isn’t this just rules-based BI with a chatbot glued on?”

Yes, the core *is* rules and stats — on purpose. The brief’s hard requirements are detection, reconciliation, drivers, uncertainty, actions, access, feedback, telemetry. LLMs are worse than pandas at all of those. The glue is the part that’s easy to fake and we didn’t: grounding, abstain, fail-closed access, LLM-vs-non-LLM telemetry. If they want “AI,” the AI is *constrained generation over a typed evidence object*, which is how you put language models next to money.

### “Why should I trust synthetic data?”

Because we needed four *guaranteed* moments, not a hope that noise produces a good demo. The generator is seeded (42), events are injected, and plots exist to verify them. Production would swap the three tables for warehouse extracts; the contract, detection, PVM, confidence, access, and grounding do not care that the rows were simulated. What synthetic data cannot prove: threshold calibration and driver coverage on messy real joins. Say that.

### “How do you stop prompt injection from a malicious KPI name / user note?”

Facts are structured JSON we built. User feedback is a rating enum plus optional note stored in SQLite, not concatenated into the next prompt. Narration cache key is `insight_id`, not free text. Still a prototype: we did not ship a full injection test harness. Next: treat the facts blob as data (chat `user` vs frozen system), strip tool calls, never interpolate analyst notes into the narrator prompt.

### “Contradiction abstain never fires on your data. Is it vapor?”

It’s a documented future-proofing hook: opposing quantified drivers each ≥20% of gross with net <50% of gross. Current scripted events don’t cancel. We still implemented and unit-shaped it so abstain isn’t only “missing data.” Weak if I claim it as a demo scenario — don’t. It’s a designed third trigger, not Event 3.

---

## 5. Known weaknesses — own them first

Say these as “here’s what I’d spend the next sprint on,” not as confessions at the end.

**Uniform weekly marketing spread.** Spend / 7. Production: day-of-week weights or keep marketing at weekly and correlate at weekly grain. Affects only the supporting correlation driver, which is already excluded from explained-%.

**Coarse 1.0 / 0.5 / 0.0 attribution.** Gets Week 7 to Medium as designed. Not estimated, not in the YAML, not category-specific. A volume drop after a *known* stockout should be 1.0; today it would still be 0.5.

**No real retraining loop.** Feedback re-ranks and produces a calibration table. It does not update z-thresholds, weights, or action recovery factors. By design — we refused to hide a fake learning system. The honest productization is “analyst reviews the down-voted (KPI × level) and edits the contract.”

**Demo used mock narration.** `LLM_MOCK_MODE=true` because 49 real cloud calls are minutes, not seconds. Mock is labeled and grounded. Real Ollama is confirmed 6/6 on the three headline scenarios × two personas. If they ask “was the video using a real model?” — say mock, then offer the 6/6 local run as the evidence the prompt holds.

**Sign-only grounding limitation.** Validator catches invented magnitudes and explicit sign flips on the token. It does **not** catch “increase” vs “decrease” in words. Direction is prompt-constrained, not machine-checked.

**Empty-narrative false pass, caught late.** First real run: 1024-token cap, reasoning model spent the whole budget thinking, content empty, grounding said PASS. Fixed (min words, 4096 tokens, truncation = fail). Mention it — it shows we test the real model, not just the mock.

**Grounding formatter bugs.** `$7,749.00` vs `-7749.0` was us, not the model. We fixed normalization rather than loosening the prompt.

**Churn numpy serialization.** `np.int64` / `np.bool_` blew `json.dumps` on June churn. Cast to native Python. Lesson: deterministic output must be JSON-native or the narrator never even starts.

**Telemetry deadlock.** `snapshot()` held a lock and re-entered `project_cost_at_scale`. Fixed with `RLock`. Small, but it would have hung the panel live.

**UI/API mismatches we had to fix.** `expected_impact` shape `{value_min,value_max}` not `{min,max}` (would have shown NaN). Telemetry panel read flat keys that were nested. Feedback summary incremented `"down"` into a `"downs"` dict. Vite 5.4 rejected the preview host. We treat UI as another consumer of the contract, not a place to invent fields.

**Per-category detection is not scored.** `detect_by_category()` exists for decomposition prep; only aggregate anomalies plus per-category *sparse flags* enter confidence. Fine for the brief; not a full category-insight product.

**May churn also abstains** (1 prior month < 3). Easy to confuse with the June completeness story. June is Event 3 (70.2% completeness). May is history. Don’t mix them.

**Action recovery factors are assumed.** Impact ranges are `|contribution| × {min,max}` from YAML, not elasticity estimates.

**CORS `allow_origins=*` and no Docker / no auth.** Prototype. Production would be identity-aware, not open.

**Attribution weights and contradiction thresholds are code constants.** Contract doesn’t own them yet.

**No browser-persisted votes, no packaging story.** Called out as out of scope at Phase 12.

**Marketing correlation can be absent.** If |r| < 0.3 or <7 points, we omit it rather than force a story.

**Temperature 0.2 is not zero.** Residual linguistic drift remains; that’s why grounding exists.

---

## 6. Key numbers to have on hand

Do not fumble these. The feed rank of Revenue on a fresh demo (no votes) is **not** 1 — GM May 13 is rank 1 because score 100 beats 72.7.

### Dataset

| | |
|---|---|
| Window | 2024-04-01 → 2024-06-29 (**90 days**) |
| Sources / grains | sales daily, marketing weekly, roster monthly |
| Seed | `np.random.seed(42)` |
| Sales rows | **1,484** |
| Marketing | **52** rows (13 weeks × 4 channels) |
| Roster | **3,053** rows |
| Categories | Electronics, Apparel, Home & Kitchen, Grocery; **Sports & Outdoors** from Jun 19 |
| Daily revenue baseline | ~**$56–57k** |
| Pipeline | **24 anomalies / 27 confidence results / 78 recommendations** |
| CFO feed | **27 insights, 0 blocked** |
| Category Manager | **22 insights, 1 blocked KPI (Gross Margin %)** |
| Status mix (CFO) | high 4, medium 13, low 3, abstain 7 |
| Deterministic runtime | ~**0.64s** (decomp ~570ms, detect ~38ms, actions ~14ms, confidence <1ms) |

### Detection / contract knobs

| | |
|---|---|
| Rolling window | **21 days** |
| Z threshold | **2.0** (category-level 1.5) |
| Min points to score a day | **7** |
| Sparse daily / monthly | **21 days / 3 months** |
| Revenue materiality | **5% OR $5,000** |
| Units materiality | **5% OR 100 units** |
| GM / churn materiality | **2 pp** |
| Churn completeness gate | **90%** |
| Confidence High | explained ≥80%, stale ≤48h, history ≥30d / 3mo |
| Medium | ≥50%, ≤168h, ≥14d / 2mo |
| Low | ≥20%, ≤720h, ≥7d / 1mo |
| Action gate | driver ≥**5%** of movement |

### Event 1 — Week 7 multi-factor dip (May 13–19, 2024)

Scripted: Electronics **10% price cut** + **20% volume drop**.

**Headline day — Monday 2024-05-13**

**Revenue** — Medium 72.7 (this is the “partially explained” story)

| | |
|---|---|
| Baseline → current | **$57,146.52 → $49,397.52** |
| Change | **−$7,749.00 (−13.56%)** |
| z | **−3.53** |
| History | 42 days |
| PVM price | **−$3,031.58 (39.1%)**, weight **1.0** |
| PVM volume | **−$5,206.68 (67.2%)**, weight **0.5** |
| PVM mix | **+$489.25 (6.3%)**, weight **0.0** |
| Arithmetic explained | **100%** |
| Business explained | **72.7%** |
| Price recovery action | **$1,212.63–$1,818.95** |
| Volume recovery action | **$1,562.00–$2,603.34** |

**Gross Margin %** — High 100 (CFO only; z people remember)

| | |
|---|---|
| Baseline → current | **37.53% → 34.62%** |
| Change | **−2.92 pp (−7.78%)** |
| z | **−16.1** |
| Rolling std | **0.1812 pp** (so 2.92 is ~16σ — genuine) |
| Price contribution | **−2.973 pp (101.9%)**, weight 1.0 |
| Cost residual | **+0.056 pp (1.9%)** → defaults, not a lever |
| Recovery | **1.49–2.38 pp** |

**Units Sold** — Medium 50

| | |
|---|---|
| Baseline → current | **1,208.81 → 1,147** |
| Change | **−61.81 (−5.11%)** |
| z | **−2.36** |
| Mix (Electronics / Grocery / Apparel / Home & Kitchen) | **−32.14 / −23.62 / −10.43 / +4.38** |

Other Week-7 Revenue hits (if they click around): May 14 z=−2.49 (−12.03%); May 15 z=−2.23 (−12.33%); May 18 z=−2.08 (−14.22%). All Medium, business-explained ~68–73%.

GM also flags May 14–16 (z −3.97, −2.86, −2.19), all High.

### Event 2 — Sparse history, Sports & Outdoors

| | |
|---|---|
| Launch | **2024-06-19** (day 80) |
| History at window end | **11 / 21 days** |
| Latest flagged | **2024-06-29** |
| Daily revenue (order of mag.) | **~$1,800–$2,100** |
| Output | **3 ABSTAIN cards** (Revenue, Units, GM) — no z-score, no drivers, no business actions |
| Message | “Category 'Sports & Outdoors' has only 11 days of data.” |

### Event 3 — June churn abstain

| | |
|---|---|
| Injected | true churn 5%→**8%** AND **30% null** statuses |
| June roster | **1,036** rows, **309** null (**29.8%** missing) → completeness **0.7017 = 70.2%** |
| Apparent churn | May **9.73%** → June **17.06%** (**+7.33 pp**, z=**2.69**) |
| Gate | 70.2% < **90%** → **ABSTAIN**, no score |
| Actionable | **Data Quality & Pipeline** (Data Engineering Lead) — backfill nulls, monitor 90% gate |
| Not actionable | Customer Retention on **3–6mo cohort at 22.1% churn** — rendered, flagged off |
| Don’t confuse | May churn 4.5%→9.73% also abstains, but for **1 month of history**, not completeness |

### Event 4 — Access control

Category Manager → Gross Margin % → **blocked before narration**. Reason cites contract `persona_access lists: CFO`. Logged. Lock card in feed *and* KPI grid. CFO sees all 4 GM insights (4 Week-7/nearby highs + 1 Sports sparse).

### Feedback demo numbers (Phase 9, live)

On **Revenue | 2024-05-13**, badge always Medium **72.7**:

| Persona | Votes | Factor | Effective | What you see |
|---|---|---|---|---|
| (none) | 0 | **1.000** | **72.7** | unchanged |
| CFO | 1 👍 | **1.333** | **96.9** | rises |
| Category Manager | 2 👎 | **0.5** (clamp) | **36.4** | sinks (demo: rank 3 → 14) |

Abstain 👍/👎 records, excluded from factor. Formula if they ask: `2 × (ups+1)/(ups+downs+2)`.

### Narration / LLM facts

| | |
|---|---|
| Default model | `minimax-m3:cloud` via Ollama `localhost:11434` |
| Temperature | **0.2** |
| Token cap | **4096** (was 1024 — that caused empty replies) |
| Real 6-scenario run | all PASS, `done_reason=stop`, mock=false |
| Real latency | **13.5–44.9 s** |
| Real prompt / completion | **2,685–3,543 / 742–2,822** tokens |
| Thinking chars observed | **847–10,423** |
| Cost model | default **$0 free_tier**; mock tokens never billed |

### Grounding one-liners

- Allowed numbers = grounded_assertions from the facts JSON.
- `$7,749.00`, `-$5,206.68`, `$1,562.00` must match −7749 / −5206.68 / 1562.
- Signless magnitude + word “decrease” is allowed; `+$3,031.58` on a negative fact is not.
- <10 words → fail.

---

## 7. One clarifying question to ask back

Ask **one**. Then shut up.

> “Should I treat this discussion as a defense of the trust architecture — deterministic numbers, abstain, grounding, fail-closed access — or do you want me to spend the time on how we’d productionize the same seams onto an enterprise stack, Snowflake-scale volumes and existing persona directories included?”

Why this one: it shows you know the prototype already answers the brief, you know what’s *not* proven (warehouse scale, IdP, elasticity), and you will not waste the interview on the wrong altitude.

If they already said “walk me through Week 7,” don’t ask this — they picked altitude. Optional backup if they invite questions later:

> “For a real rollout, would you rather we ingest a known-event calendar so ‘known cause’ is data rather than a heuristic weight, or keep the engine event-agnostic and only raise unexplained volume for a human?”

---

## Rehearsal checklist (day-of)

1. Say the 60-second pitch once, standing, without notes.
2. Walk Week 7 Revenue end-to-end with the exact dollars and 72.7 vs 100.
3. Contrast GM High (price *is* the cause) vs Revenue Medium (volume cause missing) vs June abstain (data broken) vs Sports abstain (history missing) vs CM lock (not entitled).
4. Answer “how is this not ChatGPT?” in four sentences.
5. Own three weaknesses: coarse weights, mock demo, sign-only grounding.
6. Ask the clarifying question if they haven’t set the frame.
7. If you blank on a number: say the *relationship* (arithmetic 100, business 73, Medium) rather than guessing $7,749 vs $7,479.

Do not apologize for being a prototype. Do not claim the LLM found the competitor promo. Do not say we retrain on thumbs. Do not call z=−16.1 a bug.

The sentence that should still be in their notes when you leave:

**The LLM never computes. When the math is complete and the business cause isn’t, we say Medium. When the evidence is broken, we shut up.**
