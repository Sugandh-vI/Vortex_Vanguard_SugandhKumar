"""
Telemetry — Runtime Latency / Token / Cost Tracking
====================================================

Phase 10. Wraps the LLM call and the analytics pipeline to record:
  - latency per pipeline stage and per LLM call,
  - token usage taken verbatim from LLM response metadata
    (Ollama `prompt_eval_count` / `eval_count`; mock estimates are
    separately labeled and never billed or counted as real),
  - an estimated cost-at-scale figure.

The LLM is NOT involved in telemetry itself — this is deterministic
measurement around existing modules. Nothing in the engine is modified:
`instrument_pipeline()` calls the same entry points the uninstrumented
pipeline uses, just timed.

--------------------------------------------------------------------
Cost model (honest by construction)
--------------------------------------------------------------------
The default provider (Ollama free-tier cloud model) costs $0. Rates are
configurable per 1M tokens:
    TELEMETRY_INPUT_RATE_1M   (default 0.0)
    TELEMETRY_OUTPUT_RATE_1M  (default 0.0)
Per-call estimated cost = (prompt_tokens * input_rate +
completion_tokens * output_rate) / 1e6. With the defaults the estimate
is $0.00 and the pricing label is "free_tier". Setting hypothetical
paid rates shows what the SAME recorded volume would cost at scale —
`project_cost_at_scale(calls)` multiplies the average token usage of
recorded REAL calls by the configured rates. Mock-usage tokens are
excluded from both (they are `mock_estimate`, not billed tokens).

--------------------------------------------------------------------
LLM-vs-non-LLM visibility
--------------------------------------------------------------------
The snapshot separates real vs mock calls, usage sources, and
per-persona / per-model breakdowns — the data behind the brief's
required "visible LLM vs non-LLM breakdown" and the Phase 11
telemetry panel.

Usage:
    from engine.telemetry import get_default_collector, instrument_pipeline

    collector = get_default_collector()
    results = instrument_pipeline(
        collector, sales_df, marketing_df, roster_df, contract
    )   # times all 5 deterministic stages
    collector.narrate(client, facts, persona="CFO")  # timed + grounded + recorded
    collector.snapshot()   # -> JSON-safe dict for the API/UI
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from narration.llm_client import LLMResponse

# Bounded ring of raw events (for debugging / UI timeline)
DEFAULT_EVENT_LIMIT = 200

_ENV_INPUT_RATE = "TELEMETRY_INPUT_RATE_1M"
_ENV_OUTPUT_RATE = "TELEMETRY_OUTPUT_RATE_1M"


def _env_rate(key: str) -> float:
    try:
        return max(0.0, float(os.environ.get(key, "0.0")))
    except ValueError:
        return 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_bucket() -> dict:
    return {"count": 0, "total_ms": 0.0, "min_ms": None, "max_ms": None}


def _empty_tokens() -> dict:
    return {"prompt": 0, "completion": 0, "total": 0}


class TelemetryCollector:
    """
    In-memory, thread-safe telemetry collector.

    - `stage(name)`           context manager: times a code block
    - `record_stage(name, ms)` direct stage recording
    - `record_llm_call(...)`  records one LLMResponse (+grounding)
    - `narrate(client, facts, persona)`  timed prompt -> call -> grounding
    - `record_pipeline(...)`  records a full instrumented pipeline run
    - `snapshot()`            JSON-safe aggregate for the API/UI
    - `project_cost_at_scale(calls)`  cost projection at volume
    """

    def __init__(
        self,
        jsonl_path: Optional[str] = None,
        input_rate_per_1m: Optional[float] = None,
        output_rate_per_1m: Optional[float] = None,
    ):
        # RLock: snapshot() holds the lock while calling
        # project_cost_at_scale(), which re-enters it.
        self._lock = threading.RLock()
        self._stages: dict[str, dict] = {}
        self._llm = {
            "calls": 0,
            "real_calls": 0,
            "mock_calls": 0,
            "total_latency_ms": 0.0,
            "min_latency_ms": None,
            "max_latency_ms": None,
            "tokens": _empty_tokens(),          # real calls only
            "mock_tokens": _empty_tokens(),     # labeled estimates only
            "estimated_cost_usd": 0.0,          # real calls, configured rates
            "grounding": {"checked": 0, "passed": 0, "failed": 0, "violations": 0},
            "truncated": 0,
            "usage_sources": set(),
        }
        self._by_persona: dict[str, dict] = {}
        self._by_model: dict[str, dict] = {}
        self._last_pipeline: Optional[dict] = None
        self._events: deque = deque(maxlen=DEFAULT_EVENT_LIMIT)
        self.created_at = _now_iso()
        self.jsonl_path = jsonl_path
        self._input_rate = (
            float(input_rate_per_1m)
            if input_rate_per_1m is not None else _env_rate(_ENV_INPUT_RATE)
        )
        self._output_rate = (
            float(output_rate_per_1m)
            if output_rate_per_1m is not None else _env_rate(_ENV_OUTPUT_RATE)
        )

    # --------------------------------------------------------
    # Pricing
    # --------------------------------------------------------

    def pricing_label(self) -> str:
        if self._input_rate == 0.0 and self._output_rate == 0.0:
            return "free_tier"
        return "custom_rates"

    def estimate_cost_usd(
        self, prompt_tokens: int, completion_tokens: int
    ) -> float:
        """Estimated USD cost for one call's token usage at configured rates."""
        cost = (
            int(prompt_tokens) * self._input_rate
            + int(completion_tokens) * self._output_rate
        ) / 1_000_000.0
        return round(cost, 6)

    def project_cost_at_scale(self, calls: int) -> dict:
        """
        Estimated USD cost for `calls` narrations at the configured
        rates, based on the AVERAGE token usage of recorded REAL calls.
        Returns None for the projection when no real calls exist (mock
        tokens are estimates, not billed tokens).
        """
        with self._lock:
            real = self._llm["real_calls"]
            tp = self._llm["tokens"]["prompt"]
            tc = self._llm["tokens"]["completion"]

        rates = {
            "input_per_1m_usd": self._input_rate,
            "output_per_1m_usd": self._output_rate,
            "pricing": self.pricing_label(),
        }
        if real == 0:
            return {
                "calls": int(calls),
                "avg_tokens_per_call": None,
                "projected_cost_usd": None,
                "rates": rates,
                "note": (
                    "No real LLM calls recorded yet — projection unavailable "
                    "(mock tokens are estimates, not billed)."
                ),
            }
        avg_p = tp / real
        avg_c = tc / real
        per_call = (avg_p * self._input_rate + avg_c * self._output_rate) / 1_000_000.0
        return {
            "calls": int(calls),
            "avg_tokens_per_call": round(avg_p + avg_c, 1),
            "projected_cost_usd": round(int(calls) * per_call, 4),
            "rates": rates,
            "note": "Based on average token usage of recorded real LLM calls.",
        }

    # --------------------------------------------------------
    # Stage timing
    # --------------------------------------------------------

    @contextmanager
    def stage(self, name: str):
        """Context manager: time a code block as a named pipeline stage."""
        start = time.perf_counter()
        try:
            yield
        finally:
            self.record_stage(name, (time.perf_counter() - start) * 1000.0)

    def record_stage(self, name: str, latency_ms: float, **meta) -> None:
        latency = round(float(latency_ms), 1)
        event = {"ts": _now_iso(), "type": "stage", "name": name,
                 "latency_ms": latency, **meta}
        with self._lock:
            b = self._stages.setdefault(name, _empty_bucket())
            b["count"] += 1
            b["total_ms"] = round(b["total_ms"] + latency, 1)
            b["min_ms"] = latency if b["min_ms"] is None else min(b["min_ms"], latency)
            b["max_ms"] = latency if b["max_ms"] is None else max(b["max_ms"], latency)
            self._events.append(event)
        self._append_jsonl(event)

    # --------------------------------------------------------
    # LLM call recording
    # --------------------------------------------------------

    def record_llm_call(
        self,
        response: LLMResponse,
        persona: Optional[str] = None,
        grounded: Optional[bool] = None,
        violations: Optional[list] = None,
        prompt_chars: Optional[int] = None,
    ) -> float:
        """
        Record one LLM call from its (normalized) response.

        Token counts are taken verbatim from `response.usage` (which the
        provider populates from model response metadata). Mock responses
        are counted separately and NEVER added to real token totals or
        cost. Returns the estimated cost recorded for this call
        (0.0 for mock calls).
        """
        usage = response.usage or {}
        is_mock = bool(getattr(response, "mock", False)) or usage.get("mock") is True
        toks = {
            "prompt": int(usage.get("prompt_tokens", 0) or 0),
            "completion": int(usage.get("completion_tokens", 0) or 0),
            "total": int(
                usage.get("total_tokens", 0)
                or int(usage.get("prompt_tokens", 0) or 0)
                + int(usage.get("completion_tokens", 0) or 0)
            ),
        }
        prompt_t, completion_t, total_t = toks["prompt"], toks["completion"], toks["total"]
        latency = round(float(getattr(response, "latency_ms", 0.0) or 0.0), 1)
        meta = getattr(response, "meta", None) or {}
        truncated = bool(meta.get("truncated_by_length"))
        cost = 0.0 if is_mock else self.estimate_cost_usd(prompt_t, completion_t)

        event = {
            "ts": _now_iso(),
            "type": "llm",
            "provider": getattr(response, "provider", "") or usage.get("provider", ""),
            "model": getattr(response, "model", "") or usage.get("model", ""),
            "persona": persona,
            "mock": is_mock,
            "latency_ms": latency,
            "tokens": {"prompt": prompt_t, "completion": completion_t, "total": total_t},
            "usage_source": usage.get("source", "unknown"),
            "estimated_cost_usd": cost,
            "grounded": grounded,
            "violations": (list(violations or []) if grounded is not None else None),
            "truncated": truncated,
            "done_reason": meta.get("done_reason"),
            "prompt_chars": prompt_chars,
        }

        with self._lock:
            L = self._llm
            L["calls"] += 1
            if is_mock:
                L["mock_calls"] += 1
                for k in toks:
                    L["mock_tokens"][k] += toks[k]
            else:
                L["real_calls"] += 1
                for k in toks:
                    L["tokens"][k] += toks[k]
                L["estimated_cost_usd"] = round(L["estimated_cost_usd"] + cost, 6)
            L["total_latency_ms"] = round(L["total_latency_ms"] + latency, 1)
            L["min_latency_ms"] = (
                latency if L["min_latency_ms"] is None else min(L["min_latency_ms"], latency)
            )
            L["max_latency_ms"] = (
                latency if L["max_latency_ms"] is None else max(L["max_latency_ms"], latency)
            )
            if truncated:
                L["truncated"] += 1
            src = usage.get("source")
            if src:
                L["usage_sources"].add(str(src))
            if grounded is not None:
                L["grounding"]["checked"] += 1
                L["grounding"]["passed" if grounded else "failed"] += 1
                L["grounding"]["violations"] += len(violations or [])
            if persona:
                pb = self._by_persona.setdefault(
                    persona, {"calls": 0, "real_tokens": 0, "total_latency_ms": 0.0}
                )
                pb["calls"] += 1
                pb["total_latency_ms"] = round(pb["total_latency_ms"] + latency, 1)
                if not is_mock:
                    pb["real_tokens"] += total_t
            model = event["model"] or "unknown"
            mb = self._by_model.setdefault(model, {"calls": 0, "real_tokens": 0})
            mb["calls"] += 1
            if not is_mock:
                mb["real_tokens"] += total_t
            self._events.append(event)
        self._append_jsonl(event)
        return cost

    # --------------------------------------------------------
    # Convenience: timed + grounded narration
    # --------------------------------------------------------

    def narrate(self, client, facts: dict, persona: str):
        """
        Build the prompt, make the LLM call, run the grounding check,
        and record the full telemetry — one step for the narration
        layer (Phase 12 endpoints will call this).

        Returns (response, grounded, violations).
        """
        from narration.prompts import build_prompt, narrative_is_grounded

        prompt = build_prompt(facts, persona)
        response = client.complete(prompt)
        grounded, violations = narrative_is_grounded(response.text, facts)
        self.record_llm_call(
            response,
            persona=persona,
            grounded=grounded,
            violations=violations,
            prompt_chars=len(prompt),
        )
        return response, grounded, violations

    # --------------------------------------------------------
    # Pipeline runs
    # --------------------------------------------------------

    def record_pipeline(self, total_ms: float, stages: dict[str, float], **meta) -> None:
        self._last_pipeline = {
            "ts": _now_iso(),
            "total_ms": round(float(total_ms), 1),
            "stages": {k: round(float(v), 1) for k, v in stages.items()},
            **meta,
        }
        self._append_jsonl(
            {"ts": _now_iso(), "type": "pipeline", **self._last_pipeline}
        )

    # --------------------------------------------------------
    # Persistence (opt-in JSONL)
    # --------------------------------------------------------

    def _append_jsonl(self, event: dict) -> None:
        if not self.jsonl_path:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.jsonl_path)), exist_ok=True)
            with open(self.jsonl_path, "a") as f:
                f.write(json.dumps(event, default=str) + "\n")
        except OSError:
            pass  # telemetry must never break the pipeline

    # --------------------------------------------------------
    # Snapshot (JSON-safe aggregate for API/UI)
    # --------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            stages = {}
            for name, b in self._stages.items():
                stages[name] = {
                    "count": b["count"],
                    "total_ms": b["total_ms"],
                    "avg_ms": round(b["total_ms"] / b["count"], 1) if b["count"] else None,
                    "min_ms": b["min_ms"],
                    "max_ms": b["max_ms"],
                }
            L = self._llm
            llm = {
                "calls": L["calls"],
                "real_calls": L["real_calls"],
                "mock_calls": L["mock_calls"],
                "total_latency_ms": L["total_latency_ms"],
                "avg_latency_ms": (
                    round(L["total_latency_ms"] / L["calls"], 1) if L["calls"] else None
                ),
                "min_latency_ms": L["min_latency_ms"],
                "max_latency_ms": L["max_latency_ms"],
                "tokens": dict(L["tokens"]),              # real calls only
                "mock_tokens": dict(L["mock_tokens"]),    # labeled estimates only
                "estimated_cost_usd": L["estimated_cost_usd"],
                "grounding": dict(L["grounding"]),
                "truncated": L["truncated"],
                "usage_sources": sorted(L["usage_sources"]),
                "by_persona": {
                    p: {
                        "calls": v["calls"],
                        "real_tokens": v["real_tokens"],
                        "total_latency_ms": v["total_latency_ms"],
                        "avg_latency_ms": (
                            round(v["total_latency_ms"] / v["calls"], 1)
                            if v["calls"] else None
                        ),
                    }
                    for p, v in self._by_persona.items()
                },
                "by_model": dict(self._by_model),
            }
            cost_at_scale = {
                "input_rate_per_1m_usd": self._input_rate,
                "output_rate_per_1m_usd": self._output_rate,
                "pricing": self.pricing_label(),
                "projected_cost_usd_at_1000_calls": self.project_cost_at_scale(1000)[
                    "projected_cost_usd"
                ],
            }
            events = list(self._events)
            last_pipeline = dict(self._last_pipeline) if self._last_pipeline else None

        return {
            "generated_at": _now_iso(),
            "collector_created_at": self.created_at,
            "stages": stages,
            "last_pipeline": last_pipeline,
            "llm": llm,
            "cost_at_scale": cost_at_scale,
            "events": events,
        }


# ============================================================
# Instrumented analytics pipeline
# ============================================================


def instrument_pipeline(
    collector: TelemetryCollector,
    sales_df,
    marketing_df,
    roster_df,
    contract,
    rules_store=None,
    as_of_date: Optional[str] = None,
) -> dict:
    """
    Run the full deterministic pipeline with per-stage timing.

    Calls the SAME entry points the uninstrumented pipeline uses
    (run_detection / reconcile / decompose_all / score_all /
    recommend_all) — no engine module is modified. Records each stage
    plus a `pipeline` event with the stage breakdown.

    Returns:
        {detection, reconciliation, decomposition, confidence, actions,
         stage_latencies_ms, total_ms}
    """
    from engine.detection import run_detection
    from engine.reconciliation import reconcile
    from engine.decomposition import decompose_all
    from engine.confidence import score_all
    from engine.actions import recommend_all

    wall_start = time.perf_counter()
    stage_latencies: dict[str, float] = {}

    def _timed(name: str, fn):
        start = time.perf_counter()
        out = fn()
        ms = (time.perf_counter() - start) * 1000.0
        collector.record_stage(name, ms)
        stage_latencies[name] = ms
        return out

    detection = _timed("detection", lambda: run_detection(sales_df, roster_df, contract))
    reconciliation = _timed(
        "reconciliation",
        lambda: reconcile(sales_df, marketing_df, roster_df, window_end=as_of_date),
    )
    decomposition = _timed(
        "decomposition",
        lambda: decompose_all(
            detection.anomalies, sales_df, marketing_df, roster_df, contract
        ),
    )
    confidence = _timed(
        "confidence",
        lambda: score_all(
            detection.anomalies,
            decomposition,
            detection.sparse_history_flags,
            contract,
            reconciliation.source_freshness,
        ),
    )
    actions = _timed(
        "actions",
        lambda: recommend_all(detection, decomposition, confidence, contract, rules_store),
    )

    total_ms = (time.perf_counter() - wall_start) * 1000.0
    collector.record_pipeline(total_ms, stage_latencies)

    return {
        "detection": detection,
        "reconciliation": reconciliation,
        "decomposition": decomposition,
        "confidence": confidence,
        "actions": actions,
        "stage_latencies_ms": {k: round(v, 1) for k, v in stage_latencies.items()},
        "total_ms": round(total_ms, 1),
    }


# ============================================================
# Default collector (used by the API endpoint)
# ============================================================

_DEFAULT_COLLECTOR: Optional[TelemetryCollector] = None
_DEFAULT_LOCK = threading.Lock()


def get_default_collector() -> TelemetryCollector:
    """Process-wide default collector for the FastAPI /telemetry endpoint."""
    global _DEFAULT_COLLECTOR
    if _DEFAULT_COLLECTOR is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_COLLECTOR is None:
                _DEFAULT_COLLECTOR = TelemetryCollector()
    return _DEFAULT_COLLECTOR
