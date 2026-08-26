#!/usr/bin/env python3
"""
test_real_narration.py — Real Ollama narration harness (run LOCALLY).

Verifies the Phase 8 real-LLM path against your local `ollama serve`
instance, using the same scenarios and personas used for mock-mode
testing:
  - Week 7 Revenue (2024-05-13)
  - Week 7 Gross Margin % (2024-05-13)
  - June Churn abstain (2024-06)
  - personas: CFO and Category Manager (6 LLM calls total)

REQUIREMENTS (local machine — this harness is NOT runnable here):
  - `ollama serve` running and the cloud model pulled:
        ollama pull minimax-m3:cloud
  - backend/.env with:
        OLLAMA_BASE_URL=http://localhost:11434
        OLLAMA_MODEL=minimax-m3:cloud
        LLM_MOCK_MODE=false
  - Generated data in backend/data/raw/ (the script tells you how to
    regenerate if missing).

The script REFUSES to run in mock mode and refuses a silent mock
fallback: if the client does not report provider=ollama / mock=False it
prints FATAL and exits 2. A real call that fails mid-run is reported as
a per-scenario FAIL, not hidden.

Run from backend/ with the venv active:
    python test_real_narration.py
"""

from __future__ import annotations

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import pandas as pd

from contracts.loader import ContractStore
from engine.detection import run_detection
from engine.confidence import analyze
from engine.actions import run_actions
from narration.prompts import pipeline_to_facts, build_prompt, narrative_is_grounded
from narration.llm_client import (
    LLMClient,
    LLMError,
    OllamaProvider,
    ollama_base_url,
    ollama_model,
)

# ------------------------------------------------------------
# Scenarios & personas (same as mock-mode verification)
# ------------------------------------------------------------
SCENARIOS = [
    ("Revenue", "2024-05-13"),
    ("Gross Margin %", "2024-05-13"),
    ("Customer Churn Rate", "2024-06"),
]
PERSONAS = ["CFO", "Category Manager"]

RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
DATA_FILES = {
    "sales_transactions.csv": os.path.join(RAW_DIR, "sales_transactions.csv"),
    "marketing_spend.csv": os.path.join(RAW_DIR, "marketing_spend.csv"),
    "customer_roster.csv": os.path.join(RAW_DIR, "customer_roster.csv"),
}

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------


def fatal(message: str, hints: list | None = None) -> None:
    print("\n" + "!" * 72)
    print("FATAL: " + message)
    for hint in hints or []:
        print("  - " + hint)
    print("!" * 72)
    sys.exit(2)


def build_context() -> dict:
    """Load data and run the deterministic pipeline once for all scenarios."""
    missing = [name for name, path in DATA_FILES.items() if not os.path.exists(path)]
    if missing:
        fatal(
            "Generated data files are missing.",
            [
                f"Missing in backend/data/raw/: {', '.join(missing)}",
                "Generate them first:  cd backend && python data/generate_synthetic_data.py",
            ],
        )

    sales = pd.read_csv(DATA_FILES["sales_transactions.csv"], parse_dates=["date"])
    marketing = pd.read_csv(DATA_FILES["marketing_spend.csv"])
    roster = pd.read_csv(DATA_FILES["customer_roster.csv"])
    store = ContractStore()

    detection = run_detection(sales, roster, store)
    confidence_set = analyze(sales, marketing, roster, store)
    plan = run_actions(sales, marketing, roster, store)

    anomaly_by_key = {(a.kpi_name, a.period): a for a in detection.anomalies}
    conf_by_key = {}
    for c in confidence_set.results:
        if c.category is None:  # aggregate anomalies only (our test scenarios)
            conf_by_key[(c.kpi_name, c.period)] = c

    return {
        "sales": sales,
        "marketing": marketing,
        "roster": roster,
        "store": store,
        "detection": detection,
        "confidence_set": confidence_set,
        "plan": plan,
        "anomaly_by_key": anomaly_by_key,
        "conf_by_key": conf_by_key,
    }


def run_one(client: LLMClient, ctx: dict, kpi: str, period: str) -> dict:
    """Run ONE real LLM call for (kpi, period) with `client`'s persona."""
    anomaly = ctx["anomaly_by_key"].get((kpi, period))
    confidence = ctx["conf_by_key"].get((kpi, period))
    suggestion = ctx["plan"].get_set(kpi, period)

    if anomaly is None or confidence is None:
        msg = f"No pipeline data found for {kpi} @ {period} — cannot narrate."
        print(msg)
        return {"error": msg}

    # 1) client.describe() — visual confirmation of the REAL provider
    print("Client:", json.dumps(client.describe(), indent=2))

    facts = pipeline_to_facts(confidence, suggestion, anomaly, client.persona)
    prompt = build_prompt(facts, client.persona)
    print(
        f"Prompt: {len(prompt):,} chars | "
        f"grounded assertions: {len(facts['grounded_assertions'])} | "
        f"calling real model '{client.model_name()}' (may take 10-60s)..."
    )

    try:
        resp = client.complete(prompt)
    except LLMError as exc:
        print("LLM CALL FAILED:", exc)
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — report any unexpected failure
        print("UNEXPECTED ERROR:", repr(exc))
        return {"error": repr(exc)}

    # Real-response sanity (no silent mock, no fake metadata)
    sanity = {
        "provider_is_ollama": resp.provider == "ollama",
        "mock_flag_false": resp.mock is False,
        "no_mock_prefix": "[MOCK]" not in resp.text,
        "usage_from_model_metadata": resp.usage.get("source") == "llm_response_metadata",
    }
    print(
        "\nReal-response sanity: " + json.dumps(sanity)
        + f"\nLatency: {resp.latency_ms:.0f} ms | tokens: "
        f"prompt={resp.usage.get('prompt_tokens')}, "
        f"completion={resp.usage.get('completion_tokens')}, "
        f"total={resp.usage.get('total_tokens')} "
        f"(source={resp.usage.get('source')}, mock={resp.usage.get('mock')})"
    )

    # 2) Full real narrative
    print("\n--- NARRATIVE ---")
    print(resp.text)
    print("--- END NARRATIVE ---")

    # 3) Grounding check (strictness oracle) against the real output
    grounded, violations = narrative_is_grounded(resp.text, facts)
    print("\n--- GROUNDING CHECK (narrative_is_grounded) ---")
    if grounded:
        print(
            "PASS — every number in the narrative is present in the allowed "
            "fact set (grounded_assertions)."
        )
    else:
        print(
            f"FAIL — {len(violations)} ungrounded numeric claim(s): {violations}"
        )
        print(
            "Ungrounded claims are numbers the narrator computed, rounded, or "
            "invented; they are NOT in the facts JSON the pipeline provided."
        )

    return {
        "sanity": sanity,
        "sanity_ok": all(sanity.values()),
        "grounded": grounded,
        "violations": violations,
        "narrative": resp.text,
    }


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------


def main() -> int:
    # 0) Hard guard: no mock mode, no silent fallback.
    if os.environ.get("LLM_MOCK_MODE", "false").strip().lower() == "true":
        fatal(
            "LLM_MOCK_MODE=true — this harness requires the REAL Ollama path.",
            ["Set LLM_MOCK_MODE=false in backend/.env (or unset it)."],
        )

    probe = OllamaProvider()
    if not probe.is_available():
        fatal(
            f"Ollama is not reachable at {ollama_base_url()} "
            f"(model: {ollama_model()}).",
            [
                "Start the local server:        ollama serve",
                "Pull the cloud model:          ollama pull minimax-m3:cloud",
                "Check backend/.env: OLLAMA_BASE_URL, OLLAMA_MODEL, LLM_MOCK_MODE=false",
                "Sanity check with:             ollama run minimax-m3:cloud \"hello\"",
            ],
        )

    probe_client = LLMClient.from_env(persona=PERSONAS[0])
    desc = probe_client.describe()
    if desc.get("provider") != "ollama" or desc.get("mock") is not False:
        fatal(
            "Client did not select the real Ollama provider — refusing a silent "
            "mock fallback.",
            [json.dumps(desc, indent=2)],
        )

    print("=" * 72)
    print("REAL OLLAMA NARRATION TEST")
    print(f"  provider: {desc['provider']} | model: {desc['model']} | mock: {desc['mock']}")
    print(f"  scenarios: {len(SCENARIOS)} x personas: {PERSONAS} (6 calls)")
    print("=" * 72)

    ctx = build_context()
    failures: list[dict] = []
    run_no = 0

    for kpi, period in SCENARIOS:
        for persona in PERSONAS:
            run_no += 1
            print("\n" + "#" * 72)
            print(f"# RUN {run_no}/6 — {kpi} @ {period} — persona: {persona}")
            print("#" * 72)
            client = LLMClient.from_env(persona=persona)
            report = run_one(client, ctx, kpi, period)

            if report.get("error"):
                failures.append({"scenario": f"{kpi} @ {period} / {persona}", "error": report["error"]})
                print("\n=> RESULT: FAIL (call error)")
                continue

            ok = report["sanity_ok"] and report["grounded"]
            if not ok:
                failures.append({
                    "scenario": f"{kpi} @ {period} / {persona}",
                    "sanity_ok": report["sanity_ok"],
                    "sanity": report["sanity"],
                    "grounded": report["grounded"],
                    "violations": report["violations"],
                })
            print("\n=> RESULT: " + ("PASS" if ok else "FAIL"))

    # Summary
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    for f in failures:
        print("  FAIL:", json.dumps(f, indent=2, default=str))
    if failures:
        print(f"\n{len(failures)} of {run_no} runs FAILED — inspect the output above.")
        return 1
    print(f"All {run_no} runs PASSED (real Ollama, grounded narratives).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
