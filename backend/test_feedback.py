#!/usr/bin/env python3
"""
test_feedback.py — Phase 9 feedback loop regression tests.

Covers (no LLM, no network, temp SQLite DB only):
  (a) insight_id derivation (aggregate vs per-category)
  (b) record + fetch round-trip, field fidelity, newest-first ordering
  (c) persistence across store reopens
  (d) fail-closed validation: invalid rating, unknown persona, unknown
      KPI, insight_id mismatch, period format vs KPI grain
  (e) attach_feedback_context tie-back from a Phase 5 ConfidenceResult
  (f) feedback_factor / adjusted_score math (the weighting design)
  (g) summary aggregation incl. abstain exclusion from factor computation
  (h) JSON-serializability of all outputs

Run from backend/ with the venv active:
    python test_feedback.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from contracts.loader import ContractStore
from engine.confidence import ConfidenceResult
from engine.feedback import (
    FeedbackStore,
    attach_feedback_context,
    feedback_factor,
    adjusted_score,
    insight_id,
)


def _expect_raises(fn, label: str, fragment: str) -> None:
    try:
        fn()
    except ValueError as e:
        assert fragment.lower() in str(e).lower(), (
            f"{label}: error message missing {fragment!r}: {e}"
        )
        print(f"  PASS  {label} -> rejected: {str(e)[:70]}...")
        return
    raise AssertionError(f"{label}: expected ValueError, none raised")


def main() -> int:
    print("Phase 9 feedback loop regression tests")
    store_dir = tempfile.mkdtemp(prefix="feedback_test_")
    db_path = os.path.join(store_dir, "feedback_test.db")
    store = FeedbackStore(db_path=db_path)

    # ---------------------------------------------------------
    # (a) insight_id derivation
    # ---------------------------------------------------------
    assert insight_id("Revenue", "2024-05-13") == "Revenue|2024-05-13"
    assert (
        insight_id("Revenue", "2024-06-29", "Sports & Outdoors")
        == "Revenue|2024-06-29|Sports & Outdoors"
    )
    assert insight_id("Customer Churn Rate", "2024-06") == "Customer Churn Rate|2024-06"
    print("  PASS  insight_id derivation (aggregate + per-category + monthly)")

    # ---------------------------------------------------------
    # (b) record + fetch round-trip
    # ---------------------------------------------------------
    r1 = store.record(
        "Revenue", "2024-05-13", "CFO", "up",
        confidence_status="medium", confidence_score=72.7,
    )
    r2 = store.record(
        "Revenue", "2024-05-13", "Category Manager", "down",
        note="volume cause still unconfirmed",
        confidence_status="medium", confidence_score=72.7,
    )
    r3 = store.record(
        "Customer Churn Rate", "2024-06", "CFO", "up",
        confidence_status="abstain", confidence_score=None,
    )
    assert r1 < r2 < r3
    rows = store.fetch()
    assert len(rows) == 3
    newest = rows[0]
    assert newest["id"] == r3 and newest["rating"] == "up"
    assert newest["confidence_score"] is None  # abstain
    assert newest["confidence_status"] == "abstain"
    assert newest["insight_id"] == "Customer Churn Rate|2024-06"

    cm_row = store.fetch(persona="Category Manager", rating="down")[0]
    assert cm_row["note"] == "volume cause still unconfirmed"
    assert cm_row["insight_id"] == "Revenue|2024-05-13"
    assert cm_row["confidence_score"] == 72.7
    assert store.fetch(insight_id="Revenue|2024-05-13") and len(
        store.fetch(insight_id="Revenue|2024-05-13")
    ) == 2  # same insight, two personas -> two rows, same id
    assert len(store.fetch(limit=2)) == 2
    print("  PASS  record + fetch round-trip, filters, newest-first, 2 personas/1 insight")

    # ---------------------------------------------------------
    # (c) persistence across reopens
    # ---------------------------------------------------------
    store2 = FeedbackStore(db_path=db_path)
    assert len(store2.fetch()) == 3
    assert store2.fetch(limit=1)[0]["id"] == r3
    print("  PASS  persistence across store reopens")

    # ---------------------------------------------------------
    # (d) fail-closed validation
    # ---------------------------------------------------------
    _expect_raises(
        lambda: store.record("Revenue", "2024-05-13", "CFO", "sideways"),
        "invalid rating", "invalid rating")
    _expect_raises(
        lambda: store.record("Revenue", "2024-05-13", "Hacker", "up"),
        "unknown persona", "unknown persona")
    _expect_raises(
        lambda: store.record("Secret KPI", "2024-05-13", "CFO", "up"),
        "unknown KPI", "unknown kpi")
    _expect_raises(
        lambda: store.record(
            "Revenue", "2024-05-13", "CFO", "up",
            insight_id="Revenue|2024-05-14"),
        "insight_id mismatch", "does not match")
    _expect_raises(
        lambda: store.record("Customer Churn Rate", "2024-06-01", "CFO", "up"),
        "daily date on monthly KPI", "YYYY-MM")
    _expect_raises(
        lambda: store.record("Revenue", "2024-05", "CFO", "up"),
        "month string on daily KPI", "YYYY-MM-DD")
    _expect_raises(
        lambda: store.record("Revenue", "2024-05-13", "CFO", "up",
                             confidence_status="maybe"),
        "invalid confidence_status", "confidence_status")
    # nothing new was persisted by the rejected writes
    assert len(store.fetch()) == 3
    print("  PASS  fail-closed validation (7 negative cases, no partial writes)")

    # ---------------------------------------------------------
    # (e) attach_feedback_context tie-back
    # ---------------------------------------------------------
    conf_rev = ConfidenceResult(
        kpi_name="Revenue", period="2024-05-13", category=None,
        status="medium", score=72.7, business_explained_pct=72.7,
        arithmetic_explained_pct=100.0,
        message="Medium confidence",
    )
    ctx = attach_feedback_context(conf_rev, "Category Manager")
    assert ctx == {
        "insight_id": "Revenue|2024-05-13",
        "kpi_name": "Revenue",
        "period": "2024-05-13",
        "category": None,
        "persona": "Category Manager",
        "confidence_status": "medium",
        "confidence_score": 72.7,
    }
    # and the context records cleanly with insight_id cross-check
    store.record(
        ctx["kpi_name"], ctx["period"], ctx["persona"], "down",
        category=ctx["category"],
        confidence_status=ctx["confidence_status"],
        confidence_score=ctx["confidence_score"],
        insight_id=ctx["insight_id"],
    )
    assert len(store.fetch(insight_id="Revenue|2024-05-13")) == 3

    conf_sports = ConfidenceResult(
        kpi_name="Revenue", period="2024-06-29", category="Sports & Outdoors",
        status="abstain", score=None, insufficient_history=True,
        message="Insufficient history",
    )
    ctx_s = attach_feedback_context(conf_sports, "CFO")
    assert ctx_s["insight_id"] == "Revenue|2024-06-29|Sports & Outdoors"
    assert ctx_s["confidence_score"] is None
    store.record(
        ctx_s["kpi_name"], ctx_s["period"], ctx_s["persona"], "up",
        category=ctx_s["category"],
        confidence_status=ctx_s["confidence_status"],
        confidence_score=ctx_s["confidence_score"],
        insight_id=ctx_s["insight_id"],
    )
    print("  PASS  attach_feedback_context tie-back (anomaly + sparse flag)")

    # ---------------------------------------------------------
    # (f) feedback_factor / adjusted_score math
    # ---------------------------------------------------------
    assert feedback_factor(0, 0) == 1.0                 # neutral prior
    assert feedback_factor(1, 1) == 1.0                 # symmetric
    assert feedback_factor(3, 1) == round(2 * 4 / 6, 3) # 1.333
    assert feedback_factor(5, 0) == 1.5                 # 1.714 clamped at hi
    assert feedback_factor(0, 5) == 0.5                 # 0.286 clamped at lo
    assert feedback_factor(2, 8) == 0.5                 # heavy downs -> floor
    try:
        feedback_factor(-1, 0)
        raise AssertionError("negative votes accepted")
    except ValueError:
        pass

    assert adjusted_score(None, 1.5) is None
    assert adjusted_score(72.7, 1.0) == 72.7            # neutral = unchanged
    assert adjusted_score(72.7, 1.5) == 100.0           # clamp at 100
    assert adjusted_score(30.0, 0.5) == 15.0            # clamp at 0 side
    assert adjusted_score(50.0, 1.3) == 65.0
    assert adjusted_score(50.0, 1.333) in (66.6, 66.7)  # 66.65 float boundary
    print("  PASS  feedback_factor / adjusted_score math")

    # ---------------------------------------------------------
    # (g) summary aggregation incl. abstain exclusion
    # ---------------------------------------------------------
    # current votes:
    #   Revenue|2024-05-13: CFO up(medium), CM down(medium), CM down(medium)
    #   Customer Churn Rate|2024-06: CFO up(abstain)
    #   Revenue|2024-06-29|Sports & Outdoors: CFO up(abstain)
    s = store.summary()
    by_iid = {e["insight_id"]: e for e in s["by_insight"]}
    assert by_iid["Revenue|2024-05-13"]["total"] == 3
    assert by_iid["Revenue|2024-05-13"]["ups"] == 1
    assert by_iid["Revenue|2024-05-13"]["downs"] == 2
    assert by_iid["Revenue|2024-05-13"]["agreement"] == round(1 / 3, 3)
    assert set(by_iid["Revenue|2024-05-13"]["personas"]) == {"CFO", "Category Manager"}

    by_key = {
        (e["kpi_name"], e["confidence_status"], e["persona"]): e
        for e in s["by_kpi_status_persona"]
    }
    cm_med = by_key[("Revenue", "medium", "Category Manager")]
    assert cm_med["ups"] == 0 and cm_med["downs"] == 2
    assert cm_med["up_rate"] == 0.0
    assert cm_med["feedback_factor"] == 0.5  # clamped floor, not excluded
    assert cm_med["excluded_from_factor"] is False

    churn_abstain = by_key[("Customer Churn Rate", "abstain", "CFO")]
    assert churn_abstain["ups"] == 1 and churn_abstain["downs"] == 0
    assert churn_abstain["up_rate"] == 1.0
    assert churn_abstain["feedback_factor"] is None
    assert churn_abstain["excluded_from_factor"] is True
    print("  PASS  summary aggregation (per-insight + per KPI/level/persona, abstain excluded)")

    # ---------------------------------------------------------
    # (h) JSON-serializability
    # ---------------------------------------------------------
    json.dumps(rows)
    json.dumps(store.fetch())
    json.dumps(s)
    json.dumps(attach_feedback_context(conf_rev, "CFO"))
    print("  PASS  all outputs JSON-serializable")

    shutil.rmtree(store_dir, ignore_errors=True)
    print("\nALL FEEDBACK LOOP TESTS PASSED ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
