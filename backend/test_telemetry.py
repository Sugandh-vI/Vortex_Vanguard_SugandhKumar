#!/usr/bin/env python3
"""
test_telemetry.py — Phase 10 telemetry regression tests.

Covers (no real LLM — mock provider only):
  (a) stage timing (context manager + direct record), aggregates
  (b) real-shaped LLMResponse recording (tokens verbatim from usage)
  (c) mock LLMResponse recording (separate counters, never real/costed)
  (d) cost math at custom rates + cost-at-scale projection
  (e) truncation + grounding-fail counters
  (f) instrument_pipeline on the real dataset — 5 stages recorded,
      output parity with the uninstrumented pipeline
  (g) narrate() end-to-end via MockProvider (grounded + recorded)
  (h) GET /telemetry endpoint (FastAPI TestClient)
  (i) JSONL persistence (opt-in)
  (j) JSON-serializability of the full snapshot

Run from backend/ with the venv active:
    python test_telemetry.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

os.environ["LLM_MOCK_MODE"] = "true"

import pandas as pd

from contracts.loader import ContractStore
from narration.llm_client import LLMClient, LLMResponse
from narration.prompts import pipeline_to_facts
from engine.detection import run_detection
from engine.confidence import analyze
from engine.actions import run_actions
from engine.telemetry import TelemetryCollector, instrument_pipeline, get_default_collector


def _real_response(prompt_t: int = 3528, completion_t: int = 2818,
                   latency: float = 43066.0, model: str = "minimax-m3:cloud",
                   truncated: bool = False) -> LLMResponse:
    return LLMResponse(
        text="Revenue decreased by $7,749.00 from $57,146.52 to $49,397.52 "
             "(-13.56%), driven by a -5,206.68 volume effect and a -3,031.58 "
             "price effect. Confidence is medium at 72.7 business-explained.",
        usage={
            "prompt_tokens": prompt_t,
            "completion_tokens": completion_t,
            "total_tokens": prompt_t + completion_t,
            "model": model,
            "provider": "ollama",
            "source": "llm_response_metadata",
        },
        provider="ollama",
        model=model,
        latency_ms=latency,
        mock=False,
        meta={
            "done_reason": "stop" if not truncated else "length",
            "truncated_by_length": truncated,
            "content_chars": 2032,
        },
    )


def _mock_response() -> LLMResponse:
    return LLMResponse(
        text="[MOCK] Revenue (2024-05-13): moved decrease from 57146.52 to "
             "49397.52 (change -7749.0, -13.56%). Drivers: unit_price "
             "-3031.58, units_sold -5206.68.",
        usage={
            "prompt_tokens": 3100, "completion_tokens": 400, "total_tokens": 3500,
            "model": "mock-llm", "provider": "mock",
            "source": "mock_estimate", "mock": True,
        },
        provider="mock",
        model="mock-llm",
        latency_ms=12.3,
        mock=True,
    )


def main() -> int:
    print("Phase 10 telemetry regression tests")

    # ---------------------------------------------------------
    # (a) stage timing
    # ---------------------------------------------------------
    c = TelemetryCollector()
    with c.stage("detection"):
        time.sleep(0.005)
    c.record_stage("detection", 1.0)
    snap = c.snapshot()
    d = snap["stages"]["detection"]
    assert d["count"] == 2 and d["total_ms"] >= 5.0
    assert d["min_ms"] == 1.0 and d["max_ms"] >= 5.0
    assert abs(d["avg_ms"] - d["total_ms"] / 2) < 0.06  # 1dp rounding
    with c.stage("reconciliation"):
        pass
    assert c.snapshot()["stages"]["reconciliation"]["count"] == 1
    print("  PASS  stage timing (context manager + direct, min/avg/max)")

    # ---------------------------------------------------------
    # (b) real-shaped LLMResponse recording
    # ---------------------------------------------------------
    c.record_llm_call(_real_response(), persona="CFO", grounded=True)
    L = c.snapshot()["llm"]
    assert L["calls"] == 1 and L["real_calls"] == 1 and L["mock_calls"] == 0
    assert L["tokens"] == {"prompt": 3528, "completion": 2818, "total": 6346}
    assert L["usage_sources"] == ["llm_response_metadata"]
    assert L["grounding"] == {"checked": 1, "passed": 1, "failed": 0, "violations": 0}
    assert L["by_persona"]["CFO"]["calls"] == 1
    assert L["by_persona"]["CFO"]["real_tokens"] == 6346
    assert L["by_model"]["minimax-m3:cloud"]["calls"] == 1
    assert L["estimated_cost_usd"] == 0.0  # default rates = free tier
    assert c.snapshot()["cost_at_scale"]["pricing"] == "free_tier"
    print("  PASS  real LLMResponse recording (tokens verbatim, free-tier cost)")

    # ---------------------------------------------------------
    # (c) mock LLMResponse recording
    # ---------------------------------------------------------
    c.record_llm_call(_mock_response(), persona="CFO", grounded=True)
    L = c.snapshot()["llm"]
    assert L["calls"] == 2 and L["mock_calls"] == 1 and L["real_calls"] == 1
    assert L["tokens"] == {"prompt": 3528, "completion": 2818, "total": 6346}  # unchanged
    assert L["mock_tokens"] == {"prompt": 3100, "completion": 400, "total": 3500}
    assert "mock_estimate" in L["usage_sources"]
    assert L["by_persona"]["CFO"]["calls"] == 2
    assert L["by_persona"]["CFO"]["real_tokens"] == 6346  # mock tokens not billed
    print("  PASS  mock recording (separate counters, excluded from real tokens)")

    # ---------------------------------------------------------
    # (d) cost math + at-scale projection (custom rates)
    # ---------------------------------------------------------
    pr = TelemetryCollector(input_rate_per_1m=2.0, output_rate_per_1m=3.0)
    cost = pr.record_llm_call(_real_response(prompt_t=1_000_000, completion_t=1_000_000))
    assert cost == 5.0, cost  # 1M*2/1M + 1M*3/1M
    proj = pr.project_cost_at_scale(1000)
    assert proj["avg_tokens_per_call"] == 2_000_000.0
    assert proj["projected_cost_usd"] == 5000.0
    assert pr.pricing_label() == "custom_rates"
    # free-tier collector: zero real calls -> projection unavailable
    empty = TelemetryCollector()
    p0 = empty.project_cost_at_scale(1000)
    assert p0["projected_cost_usd"] is None and "No real LLM calls" in p0["note"]
    print("  PASS  cost math (per-call + at-scale projection + free-tier note)")

    # ---------------------------------------------------------
    # (e) truncation + grounding-fail counters
    # ---------------------------------------------------------
    ct = TelemetryCollector()
    ct.record_llm_call(_real_response(truncated=True), persona="CFO", grounded=False,
                       violations=["$999,999"])
    Lt = ct.snapshot()["llm"]
    assert Lt["truncated"] == 1
    assert Lt["grounding"] == {"checked": 1, "passed": 0, "failed": 1, "violations": 1}
    ev = ct.snapshot()["events"][-1]
    assert ev["type"] == "llm" and ev["violations"] == ["$999,999"]
    print("  PASS  truncation + grounding-fail counters + event detail")

    # ---------------------------------------------------------
    # (f) instrument_pipeline — real dataset, parity with uninstrumented
    # ---------------------------------------------------------
    raw = os.path.join(BASE_DIR, "data", "raw")
    if not os.path.exists(os.path.join(raw, "sales_transactions.csv")):
        subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, "data", "generate_synthetic_data.py")],
            check=True, capture_output=True,
        )
    sales = pd.read_csv(os.path.join(raw, "sales_transactions.csv"), parse_dates=["date"])
    marketing = pd.read_csv(os.path.join(raw, "marketing_spend.csv"))
    roster = pd.read_csv(os.path.join(raw, "customer_roster.csv"))
    store = ContractStore()

    cp = TelemetryCollector()
    results = instrument_pipeline(cp, sales, marketing, roster, store)
    expected_stages = {"detection", "reconciliation", "decomposition",
                       "confidence", "actions"}
    assert expected_stages <= set(cp.snapshot()["stages"].keys())
    for name, ms in results["stage_latencies_ms"].items():
        assert ms >= 0.0
    assert results["total_ms"] >= min(results["stage_latencies_ms"].values())

    # Parity with the uninstrumented entry points
    plain_det = run_detection(sales, roster, store)
    plain_conf = analyze(sales, marketing, roster, store)
    plain_plan = run_actions(sales, marketing, roster, store)
    assert len(results["detection"].anomalies) == len(plain_det.anomalies) == 24
    assert (results["detection"].anomalies[0].z_score
            == plain_det.anomalies[0].z_score)
    assert len(results["confidence"].results) == len(plain_conf.results) == 27
    assert results["actions"].total_recommendations == plain_plan.total_recommendations == 78
    assert len(results["decomposition"]) == 24
    lp = cp.snapshot()["last_pipeline"]
    assert lp and expected_stages <= set(lp["stages"].keys()) and lp["total_ms"] > 0
    print("  PASS  instrument_pipeline (5 stages timed, output parity 24/27/78)")

    # ---------------------------------------------------------
    # (g) narrate() end-to-end via MockProvider
    # ---------------------------------------------------------
    cn = TelemetryCollector()
    client = LLMClient.from_env(persona="CFO")
    a = next(a for a in results["detection"].anomalies
             if a.kpi_name == "Revenue" and a.period == "2024-05-13")
    conf_r = next(r for r in results["confidence"].results
                  if r.kpi_name == "Revenue" and r.period == "2024-05-13")
    facts = pipeline_to_facts(
        conf_r, results["actions"].get_set("Revenue", "2024-05-13"), a, "CFO"
    )
    resp, grounded, violations = cn.narrate(client, facts, "CFO")
    assert resp.mock and grounded is True and violations == []
    Ln = cn.snapshot()["llm"]
    assert Ln["mock_calls"] == 1 and Ln["real_calls"] == 0
    assert Ln["grounding"]["passed"] == 1
    assert Ln["tokens"]["total"] == 0  # mock tokens never count as real
    ev_n = cn.snapshot()["events"][-1]
    assert ev_n["prompt_chars"] > 0 and ev_n["grounded"] is True
    print("  PASS  narrate() end-to-end (mock provider, grounded, recorded)")

    # ---------------------------------------------------------
    # (h) GET /telemetry endpoint
    # ---------------------------------------------------------
    from fastapi.testclient import TestClient
    from api.main import app

    default = get_default_collector()
    default.record_stage("endpoint_probe", 1.0)
    client_http = TestClient(app)
    r = client_http.get("/health")
    assert r.status_code == 200
    r = client_http.get("/telemetry")
    assert r.status_code == 200
    body = r.json()
    for key in ("stages", "llm", "cost_at_scale", "generated_at", "events"):
        assert key in body
    assert body["stages"]["endpoint_probe"]["count"] == 1
    json.dumps(body)  # endpoint payload is JSON-safe
    print("  PASS  GET /telemetry endpoint (200, correct shape, JSON-safe)")

    # ---------------------------------------------------------
    # (i) JSONL persistence (opt-in)
    # ---------------------------------------------------------
    tmpdir = tempfile.mkdtemp(prefix="telemetry_test_")
    jl = os.path.join(tmpdir, "telemetry.jsonl")
    cj = TelemetryCollector(jsonl_path=jl)
    cj.record_stage("s1", 2.0)
    cj.record_llm_call(_mock_response(), persona="CFO")
    cj.record_pipeline(10.0, {"s1": 2.0})
    lines = [json.loads(x) for x in open(jl) if x.strip()]
    assert [e["type"] for e in lines] == ["stage", "llm", "pipeline"]
    shutil.rmtree(tmpdir, ignore_errors=True)
    print("  PASS  JSONL persistence (opt-in, one line per event)")

    # ---------------------------------------------------------
    # (j) full snapshot JSON-serializable
    # ---------------------------------------------------------
    json.dumps(cp.snapshot())
    json.dumps(cn.snapshot())
    json.dumps(get_default_collector().snapshot())
    print("  PASS  snapshot JSON-serializable (all collectors)")

    print("\nALL TELEMETRY TESTS PASSED ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
