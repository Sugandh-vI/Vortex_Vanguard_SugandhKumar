#!/usr/bin/env python3
"""
test_grounding_normalization.py — Grounding validator regression tests.

Covers the formatting-normalization semantics of `narrative_is_grounded`:
  (a) currency symbols ($57,146.52 / 57,146.52)
  (b) decimal padding (1,562.00 == 1,562 == 1562.0)
  (c) sign placement (-$3,031.58 == -3,031.58 == -3031.58)
and the two hard-FAIL rules (empty narrative, invented number).

Run from backend/ with the venv active:
    python test_grounding_normalization.py
"""

from __future__ import annotations

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from narration.prompts import (
    narrative_is_grounded,
    grounding_detail,
    _canonical_token,
)

# ------------------------------------------------------------
# Fixture: the same grounded assertions the pipeline emits for
# Revenue @ 2024-05-13 (uses the real values from Phase 4).
# ------------------------------------------------------------
REVENUE_FACTS = {
    "grounded_assertions": [
        {"name": "kpi_name", "value": "Revenue", "source_path": "kpi_name"},
        {"name": "period", "value": "2024-05-13", "source_path": "period"},
        {"name": "baseline", "value": 57146.52, "source_path": "facts.baseline_value"},
        {"name": "current", "value": 49397.52, "source_path": "facts.current_value"},
        {"name": "change", "value": -7749.0, "source_path": "facts.change"},
        {"name": "pct_change", "value": -13.56, "source_path": "facts.pct_change"},
        {"name": "driver_price", "value": -3031.58, "source_path": "drivers[0].contribution_value"},
        {"name": "driver_volume", "value": -5206.68, "source_path": "drivers[1].contribution_value"},
        {"name": "impact_min", "value": 1562.0, "source_path": "recommendations[1].expected_impact.value_min"},
        {"name": "impact_max", "value": 2603.34, "source_path": "recommendations[1].expected_impact.value_max"},
    ],
    "confidence": {"status": "medium", "score": 72.7},
}


def _expect_grounded(text: str, label: str) -> None:
    ok, violations = narrative_is_grounded(text, REVENUE_FACTS)
    if not ok:
        raise AssertionError(f"{label}: expected GROUNDED, got {violations}")
    print(f"  PASS  {label}")


def _expect_violation(text: str, want: str, label: str) -> None:
    ok, violations = narrative_is_grounded(text, REVENUE_FACTS)
    if ok:
        raise AssertionError(f"{label}: expected FAIL, narrative passed")
    if want not in violations:
        raise AssertionError(f"{label}: expected {want!r} in violations, got {violations}")
    print(f"  PASS  {label} -> {violations}")


def main() -> int:
    print("grounding normalization regression tests")

    # --- currency + padding + sign placement (the exact Run 1 forms) ---
    _expect_grounded(
        "Revenue decreased by $7,749.00 from $57,146.52 to $49,397.52, "
        "a change of -13.56 percent. The price effect was -$3,031.58 and "
        "the volume effect was -$5,206.68.",
        "dollar signs + .00 padding + sign before $",
    )
    # naked magnitude with word-carried direction (a decrease of $7,749.00)
    _expect_grounded(
        "Revenue moved from 57,146.52 to 49,397.52, a decrease of 7749.0 "
        "and a change of -13.56 percent this period.",
        "signless magnitude accepted",
    )
    # padding variant for impact min
    _expect_grounded(
        "The expected impact on this lever is $1,562.00 to $2,603.34 per "
        "the recommended actions in the plan.",
        "trailing .00 padding on impact min",
    )
    # no commas version
    _expect_grounded(
        "Revenue moved from 57146.52 to 49397.52, a change of -7749.0 or "
        "-13.56 percent, driven by -3031.58 price and -5206.68 volume.",
        "bare unformatted numbers (Run 2 style)",
    )

    # --- sign consistency: explicit '-' on a negative fact ok, '+' on a
    #     negative fact is a sign flip -> violation ---
    _expect_grounded(
        "The unit price driver contributed -$3,031.58 to the movement and "
        "that is the main lever to review this period.",
        "explicit minus before currency matches negative fact",
    )
    _expect_violation(
        "The unit price driver contributed +$3,031.58 to the movement this "
        "period and that is the main lever to review now.",
        "+$3,031.58",
        "explicit plus on a negative fact is a sign flip",
    )

    # --- invented number still fails ---
    _expect_violation(
        "Revenue moved from $57,146.52 to $49,397.52, a decrease of "
        "$999,999 this period and that is a very big swing.",
        "$999,999",
        "invented magnitude",
    )

    # --- empty / near-empty still hard-fail ---
    for bad, label in [("", "empty string"), ("   \n\t", "whitespace"), ("[MOCK]", "placeholder")]:
        ok, violations = narrative_is_grounded(bad, REVENUE_FACTS)
        if ok or not violations[0].startswith("NARRATIVE_TOO_SHORT"):
            raise AssertionError(f"{label}: expected NARRATIVE_TOO_SHORT, got {ok} {violations}")
        print(f"  PASS  {label} -> hard FAIL")

    # --- canonical helper sanity ---
    assert _canonical_token("$7,749.00") == ("7749", "7749", False)
    assert _canonical_token("-$3,031.58") == ("3031.58", "-3031.58", True)
    assert _canonical_token("−$5,206.68") == ("5206.68", "-5206.68", True)  # unicode minus
    assert _canonical_token("+$489.25") == ("489.25", "489.25", True)
    assert _canonical_token("1,562.00") == ("1562", "1562", False)
    print("  PASS  _canonical_token normalization")

    # --- grounding_detail trace ---
    d = grounding_detail(
        "Revenue decreased by $7,749.00 and price -$3,031.58 this period.",
        REVENUE_FACTS,
    )
    assert any(tok.endswith("7,749.00") for tok in d["normalized"]), d
    assert any(tok.endswith("3,031.58") for tok in d["normalized"]), d
    print(f"  PASS  grounding_detail trace (exact={d['exact']}, normalized={d['normalized']})")

    print("\nALL GROUNDING NORMALIZATION TESTS PASSED ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
