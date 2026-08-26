"""
Narration Prompts — Hybrid System Prompt (Hard Fact Constraint)
===============================================================

Phase 8. Builds the prompt sent to the LLM narrator: a **hybrid** main
system message plus a per-persona addendum, with the factual payload
injected as a single `{facts}` JSON slot. The narrator receives ONLY
pre-computed facts (Phase 5 confidence + Phase 6 access-filtered +
Phase 7 recommendations) and is hard-constrained to reference exactly
those facts — never to compute, infer, round, or invent numbers.

`pipeline_to_facts()` is the deterministic fact-map builder that turns
the pipeline output (confidence result + action plan for one anomaly)
into the flat, machine-checkable `facts` dict used both for prompt
injection AND mock-output grounding. Its `grounded_assertions` list
records every number with its `source_path` provenance, which is what
the strictness test asserts against (no number in output outside this
set, no arithmetic).

Usage:
    from narration.prompts import build_prompt, pipeline_to_facts
    facts = pipeline_to_facts(conf_result, suggestion_set)
    prompt = build_prompt(facts, persona="CFO")
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional


# ============================================================
# System prompt — the hard constraint (most important text)
# ============================================================

_SYSTEM_INTRO = """
You are a business-analytics narrator for a KPI intelligence-to-action engine.
Your ONLY job: render the enclosed facts JSON into clear, persona-appropriate
prose. You are NOT an analyst, NOT a calculator, and NOT a decision-maker.
""".strip()

_SYSTEM_ALLOWED = """
ALLOWED FACT SOURCES — the "fact bible":
  The facts JSON below is the complete and exclusive set of facts you may
  reference. Every number you may use appears verbatim in these exact fields:
    - kpi_name, period
    - baseline_value, current_value, change, pct_change, direction
    - confidence.status, confidence.score, confidence.message
    - drivers[].driver_name, drivers[].contribution_value, drivers[].contribution_pct
    - explained_pct, unexplained_pct
    - recommendations[].lever, recommendations[].owner, recommendations[].actions,
      recommendations[].expected_impact{value_min,value_max,unit},
      recommendations[].monitoring_plan
    - abstain_reasons, sparse message (if present)
""".strip()

_SYSTEM_RULES = """
STRICT RULES (violations are defects):
  1. USE ONLY these facts. Do not use any number, date, metric, or claim that is
     not present in the facts JSON.
  2. NEVER compute, estimate, round, sum, difference, average, multiply, or
     extrapolate any number. Copy numbers exactly as given.
  3. NEVER introduce a causal claim (e.g. "because of X", "the price cut caused
     the drop") unless the facts JSON states that attribution. When the JSON
     says a driver is measured-but-unknown, say it is quantifiable but its
     cause is not yet confirmed.
  4. NEVER invent thresholds, benchmarks, targets, predictions, or KPIs. If the
     facts do not contain an expected impact or a monitoring step, omit it.
  5. NEVER claim correlation is causation. If marketing correlation is present,
     label it as a supporting signal only.
  6. If confidence.status is "abstain", state clearly that the engine abstains
     (evidence insufficient) and list the abstain reasons; do not quantify or
     recommend business actions beyond what the facts mark actionable.
  7. NEVER make up owners, actions, or monitoring plans — use exactly the
     lever/owner/actions/monitoring_plan fields.
  8. Keep the output grounded: prefer the exact wording of confidence.message
     and abstain reasons for those sections.

VERIFICATION PASS — before returning, re-read your output. Any claim whose
number or phrase is not in the facts JSON must be deleted. If the facts JSON has
no value for a field, say nothing about it.
""".strip()

_PERSONA_SYSTEMS = {
    "CFO": """
PERSONA — Chief Financial Officer (CFO):
  - Lead with dollar impact and margin/money implications.
  - Be concise and executive: 2-4 sentences per section.
  - Tone: confident, decision-oriented, grounded in the numbers.
  - Emphasize: materiality ($), confidence, and expected financial recovery.
  - Do NOT add financial jargon or metrics absent from the facts JSON.
""".strip(),
    "Category Manager": """
PERSONA — Category Manager:
  - Lead with operational and category-level context (volume, categories,
    drivers) and what the category team can do.
  - Be practical and slightly more detailed: 3-5 sentences per section.
  - Tone: collaborative, action-oriented, grounded in the numbers.
  - Emphasize: drivers, categories, owners, and concrete next steps.
  - Do NOT add product-level or category-level claims absent from the facts JSON.
""".strip(),
}


# ============================================================
# Fact-map builder (deterministic)
# ============================================================


def _num(value: Any) -> Optional[float]:
    """Coerce to float if numeric, else None."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def pipeline_to_facts(
    confidence_result: Any,
    suggestion_set: Any = None,
    anomaly: Any = None,
    persona: str = "CFO",
) -> dict:
    """
    Build the flat fact map + grounded_assertions for one anomaly.
    `confidence_result` is a Phase 5 ConfidenceResult; `suggestion_set`
    is an optional Phase 7 SuggestionSet (same kpi/period); `anomaly` is
    an optional Phase 3 AnomalyResult providing the raw movement values
    (baseline/current/change/pct/direction). Returns a JSON-safe dict
    whose `grounded_assertions` records every number with its source
    path — this is the strictness-test oracle.
    """
    facts: dict[str, Any] = {
        "kpi_name": str(confidence_result.kpi_name),
        "period": str(confidence_result.period or ""),
        "confidence": {
            "status": str(confidence_result.status),
            "score": confidence_result.score,
            "message": str(confidence_result.message or ""),
        },
        "abstain_reasons": list(confidence_result.abstain_reasons or []),
        "insufficient_history": bool(confidence_result.insufficient_history),
        "category": confidence_result.category,
        "source": "deterministic-pipeline",   # no code/LLM origin confusion
        "generated_by": "phase5_confidence+phase7_actions",
    }

    # Raw movement values come from the Phase 3 anomaly (some abstains
    # and sparse flags have no anomaly, in which case we omit them).
    if anomaly is not None:
        facts["baseline_value"] = float(anomaly.baseline_value)
        facts["current_value"] = float(anomaly.current_value)
        facts["change"] = float(anomaly.absolute_change)
        facts["pct_change"] = float(anomaly.pct_change)
        facts["direction"] = str(anomaly.direction)
    if confidence_result.business_explained_pct is not None:
        facts["explained_pct"] = float(confidence_result.business_explained_pct)
    if confidence_result.arithmetic_explained_pct is not None:
        facts["arithmetic_explained_pct"] = float(confidence_result.arithmetic_explained_pct)
    if confidence_result.data_completeness is not None:
        facts["data_completeness"] = float(confidence_result.data_completeness)
    if confidence_result.history_points is not None:
        facts["history_points"] = int(confidence_result.history_points)
    if confidence_result.history_required is not None:
        facts["history_required"] = int(confidence_result.history_required)

    # Drivers (from decomposition attribution detail)
    drivers = []
    for item in confidence_result.attribution_detail or []:
        drivers.append({
            "driver_name": str(item.get("driver_name", "")),
            "contribution_value": float(item.get("contribution_value", 0.0)),
            "contribution_pct": float(item.get("contribution_pct", 0.0)),
        })
    facts["drivers"] = drivers

    # Recommendations (Phase 7)
    recs = []
    if suggestion_set is not None:
        for r in suggestion_set.recommendations:
            impact = r.expected_impact or {}
            recs.append({
                "lever": str(r.lever),
                "owner": str(r.owner),
                "driver_name": str(r.driver_name),
                "actions": [str(a) for a in r.actions],
                "expected_impact": {
                    "value_min": _num(impact.get("value_min")),
                    "value_max": _num(impact.get("value_max")),
                    "unit": str(impact.get("unit") or ""),
                },
                "monitoring_plan": [str(m) for m in r.monitoring_plan],
                "actionable": bool(r.actionable),
            })
    facts["recommendations"] = recs

    # Grounded assertions (source_path provenance) — the test oracle
    grounded: list[dict] = []

    def _g(name: str, value: Any, path: str) -> None:
        if value is None:
            return
        grounded.append({
            "name": name,
            "value": value,
            "source_path": path,
        })

    _g("kpi_name", facts["kpi_name"], "kpi_name")
    _g("period", facts["period"], "period")
    for key in ("baseline_value", "current_value", "change", "pct_change",
                "direction", "explained_pct", "arithmetic_explained_pct",
                "data_completeness", "history_points", "history_required"):
        _g(key, facts.get(key), f"facts.{key}")
    _g("confidence_status", facts["confidence"]["status"], "confidence.status")
    _g("confidence_score", facts["confidence"]["score"], "confidence.score")
    _g("confidence_message", facts["confidence"]["message"], "confidence.message")
    for i, reason in enumerate(facts.get("abstain_reasons", [])):
        _g(f"abstain_reason[{i}]", reason, f"abstain_reasons[{i}]")
    for i, d in enumerate(drivers):
        _g(f"driver[{i}].value", d["contribution_value"], f"drivers[{i}].contribution_value")
        _g(f"driver[{i}].pct", d["contribution_pct"], f"drivers[{i}].contribution_pct")
        _g(f"driver[{i}].name", d["driver_name"], f"drivers[{i}].driver_name")
    for i, rec in enumerate(recs):
        _g(f"rec[{i}].impact_min", rec["expected_impact"]["value_min"],
           f"recommendations[{i}].expected_impact.value_min")
        _g(f"rec[{i}].impact_max", rec["expected_impact"]["value_max"],
           f"recommendations[{i}].expected_impact.value_max")
        _g(f"rec[{i}].lever", rec["lever"], f"recommendations[{i}].lever")
        _g(f"rec[{i}].owner", rec["owner"], f"recommendations[{i}].owner")
        for j, action in enumerate(rec["actions"]):
            _g(f"rec[{i}].action[{j}]", action, f"recommendations[{i}].actions[{j}]")
        for j, mon in enumerate(rec["monitoring_plan"]):
            _g(f"rec[{i}].monitor[{j}]", mon, f"recommendations[{i}].monitoring_plan[{j}]")
    facts["grounded_assertions"] = grounded

    return facts


# ============================================================
# Prompt construction
# ============================================================


def build_prompt(facts: dict, persona: str = "CFO") -> str:
    """
    Build the full LLM prompt: hybrid system instruction + facts JSON.

    No numeric literals appear anywhere except inside the facts JSON
    slot — the narrator physically has nothing to compute from.
    """
    persona_system = _PERSONA_SYSTEMS.get(persona, _PERSONA_SYSTEMS["CFO"])
    facts_json = json.dumps(facts, indent=2, default=str)
    return (
        f"{_SYSTEM_INTRO}\n\n"
        f"{_SYSTEM_ALLOWED}\n\n"
        f"{_SYSTEM_RULES}\n\n"
        f"{persona_system}\n\n"
        f"===\n"
        f"FACTS_JSON:\n```json\n{facts_json}\n```\n"
        f"===\n"
        f"Write the narrative for the {persona} persona now. Ground every "
        f"number exactly in FACTS_JSON.\n"
    )


# ============================================================
# Strictness validator (mock-only oracle; also useful in tests)
# ============================================================


_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def extract_numbers(text: str) -> set[str]:
    """
    All numeric tokens in a narrative (excludes the JSON slot).

    Trailing punctuation commas are trimmed (a comma after a number is
    a separator, not part of the token).
    """
    return {tok.rstrip(",") for tok in _NUMBER_RE.findall(text)}


def allowed_numbers(facts: dict) -> set[str]:
    """
    The explicit set of numbers the narrator may reference, from
    grounded_assertions (values normalized). Any token outside this set
    means the narrator invented or computed a number.
    """
    allowed: set[str] = set()
    for a in facts.get("grounded_assertions", []):
        v = a["value"]
        if isinstance(v, bool):
            continue
        if isinstance(v, float):
            allowed.add(f"{v:,.2f}".rstrip("0").rstrip("."))
        elif isinstance(v, int):
            allowed.add(f"{v:,}")
        allowed.add(str(v))
    return allowed


def allowed_string_facts(facts: dict) -> set[str]:
    """
    Non-numeric fact strings (e.g. the period "2024-05-13"). Date-like
    facts legitimately appear in narrative text; numeric extractors split
    them into fragments ("2024", "-05", "-13"), so substring matching
    against these is part of grounding.
    """
    return {
        str(a["value"])
        for a in facts.get("grounded_assertions", [])
        if isinstance(a["value"], str)
    }


def narrative_is_grounded(text: str, facts: dict) -> tuple[bool, list[str]]:
    """
    Strictness check: every numeric token in `text` must be grounded in
    the fact set (either an exact allowed number, or a fragment of an
    allowed string fact such as the period). Returns (ok, violations).
    Used to be *sure* mock output is grounded; in production this is the
    test harness for the prompt contract the real LLM is asked to follow.
    """
    allowed = allowed_numbers(facts)
    strings = allowed_string_facts(facts)
    violations = []
    for tok in extract_numbers(text):
        tok = tok.rstrip(",")
        if tok in allowed:
            continue
        if any(tok in s for s in strings):
            continue
        violations.append(tok)
    return (len(violations) == 0, violations)
