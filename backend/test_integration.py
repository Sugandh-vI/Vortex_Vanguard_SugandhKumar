"""
Integration tests — Phase 12 (live endpoints)
=============================================

Runs the REAL FastAPI app (TestClient + lifespan) with the real pipeline
and FORCED mock narration (LLM_MOCK_MODE=true), using a TEMPORARY feedback
DB (FEEDBACK_DB) so the dev database is never polluted.

Covers: startup pipeline + /api/meta, /api/timeseries, /api/insights per
persona (access filter, narration caching, effective-rank ordering),
POST/GET feedback (Phase 9 factor + re-ranking, abstain exclusion,
fail-closed validation), and /telemetry population.

Usage (from backend/ with the venv active):
    python test_integration.py
"""

import os
import sys
import tempfile

# --- environment: forced mock narration + isolated feedback DB ---
os.environ["LLM_MOCK_MODE"] = "true"
_TMP = tempfile.mkdtemp(prefix="bi_integration_")
os.environ["FEEDBACK_DB"] = os.path.join(_TMP, "feedback.db")

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)

from fastapi.testclient import TestClient  # noqa: E402
from api.main import app  # noqa: E402

PASSED = 0


def check(name: str, cond: bool) -> None:
    global PASSED
    if not cond:
        raise AssertionError(f"FAILED: {name}")
    PASSED += 1
    print(f"  ✓ {name}")


def group(title: str) -> None:
    print(f"\n[{title}]")


with TestClient(app) as c:
    # ------------------------------------------------------------------
    group("1. Startup — /health, /api/meta")
    h = c.get("/health").json()
    check("health ok + pipeline ready", h["status"] == "healthy" and h["pipeline_ready"] is True)

    meta = c.get("/api/meta").json()
    check("meta sample flag false", meta["sample"] is False)
    check("meta personas", meta["personas"] == ["CFO", "Category Manager"])
    check("meta window", meta["window"] == {"start": "2024-04-01", "end": "2024-06-29"})
    check(
        "meta freshness (3 sources, all fresh)",
        set(meta["source_freshness"]) == {"sales_transactions", "marketing_spend", "customer_roster"}
        and all(v["status"] == "fresh" for v in meta["source_freshness"].values()),
    )

    # ------------------------------------------------------------------
    group("2. /api/timeseries")
    ts = c.get("/api/timeseries").json()
    check("4 KPI series", set(ts) == {"Revenue", "Units Sold", "Gross Margin %", "Customer Churn Rate"})
    check("Revenue 90 daily points", len(ts["Revenue"]["points"]) == 90)
    check("Revenue by-category (5)", len(ts["Revenue"]["by_category"]) == 5)
    bands = [m for m in ts["Revenue"]["markers"] if m["type"] == "anomaly_band"]
    check("week-7 band 2024-05-13..2024-05-19",
          bool(bands) and bands[0]["start"] == "2024-05-13" and bands[0]["end"] == "2024-05-19")
    launches = [m for m in ts["Revenue"]["markers"] if m["type"] == "launch"]
    check("Sports launch marker 2024-06-19",
          bool(launches) and launches[0]["date"] == "2024-06-19")
    churn = ts["Customer Churn Rate"]
    check("churn monthly, 3 months", len(churn["points"]) == 3 and churn["grain"] == "monthly")
    june_comp = churn["completeness"]["2024-06"]
    check("June churn completeness ≈ 70.2%", 0.69 < june_comp < 0.71)

    # ------------------------------------------------------------------
    group("3. /api/insights — CFO (no votes yet)")
    cfo = c.get("/api/insights", params={"persona": "CFO"}).json()
    check("CFO 27 insights", len(cfo["insights"]) == 27)
    check("CFO 0 blocked", cfo["blocked"] == [])
    check("all narratives mock + grounded",
          all(n["narrative"]["mock"] is True and n["narrative"]["grounded"] is True
              for n in cfo["insights"]))
    effs = [n["effective_rank"] for n in cfo["insights"]]
    scored = [e for e in effs if e is not None]
    check("no-vote feed = Phase-5 score order (monotone, abstains last)",
          all(a >= b for a, b in zip(scored, scored[1:]))
          and effs[-6:] == [None] * 6)
    check("rank 1 = Gross Margin % @ 2024-05-13 (z -16.1)",
          cfo["insights"][0]["insight_id"] == "Gross Margin %|2024-05-13"
          and cfo["insights"][0]["anomaly"]["z_score"] == -16.1)
    check("rank numbers 1..27", [n["rank"] for n in cfo["insights"]] == list(range(1, 28)))
    check("feedback block present (zero votes, factor 1.0)",
          cfo["insights"][1]["feedback"] == {"up": 0, "down": 0,
                                             "feedback_factor": 1.0,
                                             "excluded_from_factor": False})

    # ------------------------------------------------------------------
    group("4. /api/insights — Category Manager (access control)")
    cm_before = c.get("/api/insights", params={"persona": "Category Manager"}).json()
    check("CM 22 insights", len(cm_before["insights"]) == 22)
    check("CM blocked = [Gross Margin %]",
          [b["kpi_name"] for b in cm_before["blocked"]] == ["Gross Margin %"])
    check("no GM% insight in CM feed",
          all(n["kpi_name"] != "Gross Margin %" for n in cm_before["insights"]))
    check("blocked decision carries reason + contract source",
          "NOT granted access" in cm_before["blocked"][0]["decision"]["reason"]
          and "persona_access" in cm_before["blocked"][0]["decision"]["source"])
    cm_rev_before = next(n for n in cm_before["insights"] if n["insight_id"] == "Revenue|2024-05-13")
    check("CM Revenue|2024-05-13 rank 3 before votes (72.7)",
          cm_rev_before["rank"] == 3 and cm_rev_before["effective_rank"] == 72.7)

    # ------------------------------------------------------------------
    group("5. Unknown persona → 400")
    check("insights: unknown persona 400",
          c.get("/api/insights", params={"persona": "Intern"}).status_code == 400)

    # ------------------------------------------------------------------
    group("6. POST /api/feedback — CFO up-vote (Phase 9 factor 1.333 → 96.9)")
    r = c.post("/api/feedback", json={
        "insight_id": "Revenue|2024-05-13", "persona": "CFO", "rating": "up",
    })
    check("vote recorded", r.status_code == 200 and r.json()["ok"] is True)
    body = r.json()
    check("CFO factor 1.333, effective 96.9",
          body["feedback"]["feedback_factor"] == 1.333
          and body["insight_id"] == "Revenue|2024-05-13")
    cfo2 = c.get("/api/insights", params={"persona": "CFO"}).json()
    rev = next(n for n in cfo2["insights"] if n["insight_id"] == "Revenue|2024-05-13")
    check("CFO feed re-ranked: effective 96.9 (72.7 x 1.333)", rev["effective_rank"] == 96.9)
    check("vote counts visible", rev["feedback"]["up"] == 1 and rev["feedback"]["down"] == 0)

    # ------------------------------------------------------------------
    group("7. POST /api/feedback — CM two down-votes (factor 0.5 → 36.4, sinks)")
    for _ in range(2):
        rr = c.post("/api/feedback", json={
            "insight_id": "Revenue|2024-05-13", "persona": "Category Manager", "rating": "down",
        })
        check(f"CM down-vote recorded (row {rr.json().get('row_id')})", rr.status_code == 200)
    cm_after = c.get("/api/insights", params={"persona": "Category Manager"}).json()
    rev_c = next(n for n in cm_after["insights"] if n["insight_id"] == "Revenue|2024-05-13")
    check("CM factor 0.5, effective 36.4",
          rev_c["feedback"]["feedback_factor"] == 0.5 and rev_c["effective_rank"] == 36.4)
    check("insight sank in CM feed", rev_c["rank"] > cm_rev_before["rank"])
    scored_after = [n["effective_rank"] for n in cm_after["insights"] if n["effective_rank"] is not None]
    check("CM feed still monotone after re-rank",
          all(a >= b for a, b in zip(scored_after, scored_after[1:])))
    check("abstains still last in CM feed",
          all(n["confidence"]["status"] == "abstain"
              for n in cm_after["insights"]
              if n["effective_rank"] is None)
          and cm_after["insights"][-1]["effective_rank"] is None)
    # The factor is per (KPI, level, persona): other medium Revenue insights
    # for CM moved too — design, not a bug.
    rev_other = next(n for n in cm_after["insights"] if n["insight_id"] == "Revenue|2024-05-14")
    check("factor applies to (Revenue, medium, CM) level: 73.2 → 36.6",
          rev_other["effective_rank"] == 36.6)

    # ------------------------------------------------------------------
    group("8. Abstain vote — recorded but excluded from factor")
    r = c.post("/api/feedback", json={
        "insight_id": "Customer Churn Rate|2024-06", "persona": "Category Manager", "rating": "down",
    })
    check("abstain vote recorded", r.status_code == 200 and r.json()["ok"] is True)
    check("abstain feedback excluded_from_factor",
          r.json()["feedback"]["excluded_from_factor"] is True
          and r.json()["feedback"]["feedback_factor"] is None)
    summ = c.get("/api/feedback/summary", params={"persona": "Category Manager"}).json()
    churn_calib = next(x for x in summ["by_kpi_status_persona"]
                       if x["kpi_name"] == "Customer Churn Rate")
    check("summary: churn abstain excluded",
          churn_calib["confidence_status"] == "abstain"
          and churn_calib["excluded_from_factor"] is True
          and churn_calib["feedback_factor"] is None)

    # ------------------------------------------------------------------
    group("9. /api/feedback/summary — calibration table")
    rev_calib = next(x for x in summ["by_kpi_status_persona"]
                     if x["kpi_name"] == "Revenue" and x["confidence_status"] == "medium")
    check("CM (Revenue, medium): 0 up / 2 down → factor 0.5",
          rev_calib["ups"] == 0 and rev_calib["downs"] == 2
          and rev_calib["up_rate"] == 0.0 and rev_calib["feedback_factor"] == 0.5)
    summ_cfo = c.get("/api/feedback/summary", params={"persona": "CFO"}).json()
    cfo_rev = next(x for x in summ_cfo["by_kpi_status_persona"]
                   if x["kpi_name"] == "Revenue" and x["confidence_status"] == "medium")
    check("CFO (Revenue, medium): 1 up / 0 down → factor 1.333",
          cfo_rev["ups"] == 1 and cfo_rev["downs"] == 0 and cfo_rev["feedback_factor"] == 1.333)
    check("by_insight tracks the vote",
          any(e["insight_id"] == "Revenue|2024-05-13" and e["ups"] == 1 and e["downs"] == 0
              for e in summ_cfo["by_insight"]))
    summ_all = c.get("/api/feedback/summary").json()
    check("summary (all personas) includes both personas",
          {x["persona"] for x in summ_all["by_kpi_status_persona"]} == {"CFO", "Category Manager"})

    # ------------------------------------------------------------------
    group("10. Fail-closed validation")
    check("unknown persona → 400",
          c.post("/api/feedback", json={
              "insight_id": "Revenue|2024-05-13", "persona": "Intern", "rating": "up",
          }).status_code == 400)
    check("unknown insight_id → 404",
          c.post("/api/feedback", json={
              "insight_id": "Revenue|1999-01-01", "persona": "CFO", "rating": "up",
          }).status_code == 404)
    check("invalid rating → 400",
          c.post("/api/feedback", json={
              "insight_id": "Revenue|2024-05-13", "persona": "CFO", "rating": "sideways",
          }).status_code == 400)
    check("summary: unknown persona → 400",
          c.get("/api/feedback/summary", params={"persona": "Intern"}).status_code == 400)

    # ------------------------------------------------------------------
    group("11. Narration cache — re-fetch never re-calls the LLM")
    tel1 = c.get("/telemetry").json()
    calls_after_both = tel1["llm"]["calls"]
    check("49 narrations so far (27 CFO + 22 CM), all mock",
          calls_after_both == 49 and tel1["llm"]["mock_calls"] == 49)
    c.get("/api/insights", params={"persona": "CFO"})
    c.get("/api/insights", params={"persona": "Category Manager"})
    tel2 = c.get("/telemetry").json()
    check("no extra LLM calls after re-fetches (cache hit)",
          tel2["llm"]["calls"] == 49)

    # ------------------------------------------------------------------
    group("12. /telemetry — populated by the live run")
    stages = tel2["stages"]
    check("5 instrumented stages",
          set(stages) == {"detection", "reconciliation", "decomposition", "confidence", "actions"})
    check("stage counts sane", all(s["count"] >= 1 and s["total_ms"] > 0 for s in stages.values()))
    check("grounding 49/49 passed, 0 violations",
          tel2["llm"]["grounding"]["passed"] == 49
          and tel2["llm"]["grounding"]["checked"] == 49
          and tel2["llm"]["grounding"]["violations"] == 0)
    check("last_pipeline recorded",
          tel2["last_pipeline"]["total_ms"] > 0)
    check("mock tokens recorded separately (real tokens stay 0)",
          tel2["llm"]["tokens"]["total"] == 0 and tel2["llm"]["mock_tokens"]["total"] > 0)
    check("cost: free tier, $0", tel2["cost_at_scale"]["pricing"] == "free_tier")

print(f"\n✅ All integration checks passed ({PASSED} assertions)")
