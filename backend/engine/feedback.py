"""
Feedback Loop — Thumbs Up/Down Capture Per Insight
===================================================

Phase 9. Captures analyst / business-user thumbs up/down on individual
insights, logs them to a structured SQLite table, and ties every vote
back to the exact insight it was about (which KPI, which period, which
category, which persona — and which confidence badge was displayed).

The LLM is NOT involved — this is a deterministic capture + aggregation
mechanism. No existing module is modified: Phase 5's evidence-based
confidence remains the authoritative prior.

--------------------------------------------------------------------
What is an "insight"?
--------------------------------------------------------------------
An insight is exactly the unit the narration layer (Phase 8) renders:
one (kpi_name, period, category) triple — an aggregate anomaly
(category=None, e.g. "Revenue @ 2024-05-13") or a sparse-history flag
(category set, e.g. "Revenue @ 2024-06-29 [Sports & Outdoors]").
`ConfidenceResult`, `ActionPlan.get_set()` and the narration harness
all key on this triple, so feedback ties back without re-derivation.
The stable, human-readable reference is `insight_id`:
    "Revenue|2024-05-13"            (aggregate)
    "Revenue|2024-06-29|Sports & Outdoors"  (per-category sparse flag)

The same insight shown to two personas is two narratives, so votes are
recorded per (insight_id, persona) — same insight_id, separate rows.

--------------------------------------------------------------------
How this feeds back into confidence weighting (design, prototype-scale)
--------------------------------------------------------------------
1. Feedback is a TRUST LABEL on the (insight, persona) pair — a verdict
   on whether the engine's explanation + recommendations were right and
   useful for that reader. It NEVER mutates stored numbers and NEVER
   mutates the Phase 5 evidence-based confidence: the status stays the
   deterministic prior, and abstain stays abstain.

2. It is consumed in two places:
   (a) FEED RANKING (concrete): effective_rank = phase5_score *
       feedback_factor, where feedback_factor = 2 x the Beta(1,1)
       posterior mean of the up-rate for that (KPI, level, persona),
       clamped to [0.5, 1.5]. With zero votes the factor is exactly
       1.0 — behavior with no feedback is unchanged. A level users
       consistently down-vote sinks in that persona's feed; every shift
       is traceable to specific logged votes.
   (b) CALIBRATION SIGNAL (operational): the per-(KPI x level x
       persona) up-rate table (see FeedbackStore.summary). If "high"
       confidence on a KPI keeps getting thumbs-down, the right
       response is a human review of that KPI's contract parameters
       (attribution weights, thresholds) — an editable YAML change,
       not a model retrain.

3. Guardrails:
   - Abstained insights are EXCLUDED from factor computation (user
     opinion cannot repair broken evidence). Votes ON abstains are
     still recorded — they measure whether abstention matched
     expectations.
   - Feedback is persona-scoped: a Category Manager down-vote adjusts
     the Category Manager's view only.
   - No votes => factor 1.0 => exactly pre-Phase-9 behavior.

4. Why no retraining: a lookup + Beta smoothing over a log table —
   deterministic, explainable, auditable. `feedback_factor()` /
   `adjusted_score()` below are pure, tested functions that make the
   design executable; WIRING them into feed ordering is Phase 12's
   job (Phase 5 is deliberately untouched).

Usage:
    from engine.feedback import FeedbackStore, attach_feedback_context, insight_id

    store = FeedbackStore()
    ctx = attach_feedback_context(confidence_result, persona="CFO")
    store.record(ctx["kpi_name"], ctx["period"], "CFO", "up",
                 category=ctx["category"],
                 confidence_status=ctx["confidence_status"],
                 confidence_score=ctx["confidence_score"])
    store.fetch(insight_id=ctx["insight_id"])
    store.summary()
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from contracts.loader import ContractStore

# ============================================================
# Constants
# ============================================================

RATING_UP = "up"
RATING_DOWN = "down"
VALID_RATINGS = {RATING_UP, RATING_DOWN}

VALID_STATUSES = {"high", "medium", "low", "abstain"}

_DAILY_PERIOD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTHLY_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")

# Default log location (gitignored via backend/data/raw/*.db)
DEFAULT_FEEDBACK_DB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "raw", "feedback.db",
)


# ============================================================
# Insight identity
# ============================================================


def insight_id(kpi_name: str, period: str, category: Optional[str] = None) -> str:
    """
    Deterministic, human-readable reference for one insight.

        "Revenue|2024-05-13"
        "Revenue|2024-06-29|Sports & Outdoors"
    """
    base = f"{kpi_name}|{period}"
    return f"{base}|{category}" if category else base


def _derive_insight_id(kpi_name: str, period: str,
                       category: Optional[str]) -> str:
    """Module-level alias used inside record(), where the `insight_id`
    parameter would otherwise shadow the function above."""
    return insight_id(kpi_name, period, category)


# ============================================================
# Data structures
# ============================================================


@dataclass
class FeedbackRecord:
    """One thumbs up/down on one insight for one persona."""

    insight_id: str
    kpi_name: str
    period: str
    category: Optional[str]          # None for aggregate insights
    persona: str
    rating: str                      # "up" | "down"
    timestamp: str                   # ISO-8601 UTC
    note: Optional[str] = None
    confidence_status: Optional[str] = None   # high/medium/low/abstain as displayed
    confidence_score: Optional[float] = None  # Phase 5 score (None for abstain)

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# Confidence-weighting design — pure, tested, NOT wired in
# ============================================================


def feedback_factor(
    ups: int,
    downs: int,
    lo: float = 0.5,
    hi: float = 1.5,
) -> float:
    """
    Feedback adjustment factor for feed ranking (see module docstring).

    factor = 2 x posterior_mean(Beta(1,1) up-rate) clamped to [lo, hi].
      - Beta(1,1) prior = 50% neutral belief before any votes.
      - 2x scaling maps the (0..1) up-rate onto a factor around 1.0:
        no votes -> exactly 1.0 (neutral, pre-Phase-9 behavior);
        all-up   -> approaches 2.0 (clamped at hi);
        all-down -> approaches 0.0 (clamped at lo).
      - The Beta(1,1) form shrinks toward the neutral prior as votes
        are scarce, so a single vote cannot move the ranking much.
    """
    if ups < 0 or downs < 0:
        raise ValueError("ups/downs must be >= 0")
    if ups + downs == 0:
        return 1.0
    factor = 2.0 * (ups + 1) / (ups + downs + 2)
    return round(min(hi, max(lo, factor)), 3)


def adjusted_score(
    base_score: Optional[float],
    factor: float,
) -> Optional[float]:
    """
    Demonstration of the Phase 12 feed-ranking input:
    effective_rank = clamp(base_score * factor, 0, 100).

    NOT used by any existing module in Phase 9 — the design is
    documented and testable here, wiring happens in Phase 12.
    """
    if base_score is None:
        return None
    return round(min(100.0, max(0.0, float(base_score) * factor)), 1)


# ============================================================
# Feedback store (SQLite)
# ============================================================


class FeedbackStore:
    """
    SQLite-backed store for insight feedback.

    Schema (insight_feedback):
      id, timestamp, insight_id, kpi_name, period, category, persona,
      rating, note, confidence_status, confidence_score
      + index on (insight_id, persona)

    Writes are fail-closed: unknown persona, unknown KPI, malformed
    period (vs the KPI's grain), inconsistent insight_id, or invalid
    rating all raise ValueError BEFORE anything is persisted.
    """

    def __init__(self, db_path: Optional[str] = None,
                 contract: Optional[ContractStore] = None):
        self.db_path = os.path.abspath(db_path or DEFAULT_FEEDBACK_DB)
        self.contract = contract or ContractStore()
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS insight_feedback (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp         TEXT    NOT NULL,
                    insight_id        TEXT    NOT NULL,
                    kpi_name          TEXT    NOT NULL,
                    period            TEXT    NOT NULL,
                    category          TEXT,
                    persona           TEXT    NOT NULL,
                    rating            TEXT    NOT NULL
                        CHECK (rating IN ('up', 'down')),
                    note              TEXT,
                    confidence_status TEXT,
                    confidence_score  REAL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_feedback_insight_persona "
                "ON insight_feedback (insight_id, persona)"
            )
            conn.commit()

    # --------------------------------------------------------
    # Contract-driven helpers
    # --------------------------------------------------------

    def _known_personas(self) -> list[str]:
        """All personas referenced anywhere in the contract (union, ordered)."""
        found: list[str] = []
        for kpi in self.contract.list_kpis():
            for p in self.contract.get_kpi(kpi).get("persona_access", []):
                if p not in found:
                    found.append(p)
        return found

    # --------------------------------------------------------
    # Recording (fail-closed)
    # --------------------------------------------------------

    def record(
        self,
        kpi_name: str,
        period: str,
        persona: str,
        rating: str,
        category: Optional[str] = None,
        note: Optional[str] = None,
        confidence_status: Optional[str] = None,
        confidence_score: Optional[float] = None,
        insight_id: Optional[str] = None,
    ) -> int:
        """
        Record one thumbs up/down. Returns the new row id.

        `insight_id`, when provided, must match the id derived from
        (kpi_name, period, category) — a mismatch means a stale
        reference from the UI/API and is rejected. The stored id is
        always the derived one, so tie-back is guaranteed by
        construction.
        """
        # --- persona (fail closed) ---
        known = self._known_personas()
        if persona not in known:
            raise ValueError(
                f"Unknown persona '{persona}' — not a persona in the "
                f"contract (known: {', '.join(known)})."
            )

        # --- KPI (fail closed) ---
        try:
            kpi = self.contract.get_kpi(kpi_name)
        except KeyError:
            raise ValueError(
                f"Unknown KPI '{kpi_name}' — feedback must reference a "
                f"contract KPI. Available: {self.contract.list_kpis()}."
            )

        # --- rating ---
        if rating not in VALID_RATINGS:
            raise ValueError(
                f"Invalid rating '{rating}' — must be one of "
                f"{sorted(VALID_RATINGS)}."
            )

        # --- period format vs the KPI's grain ---
        if not isinstance(period, str) or not period:
            raise ValueError("period is required (YYYY-MM-DD or YYYY-MM).")
        grain = kpi.get("grain", "")
        if grain == "daily":
            if not _DAILY_PERIOD_RE.match(period):
                raise ValueError(
                    f"Daily KPI '{kpi_name}' requires a YYYY-MM-DD period, "
                    f"got '{period}'."
                )
        elif grain == "monthly":
            if not _MONTHLY_PERIOD_RE.match(period):
                raise ValueError(
                    f"Monthly KPI '{kpi_name}' requires a YYYY-MM period, "
                    f"got '{period}'."
                )

        # --- confidence context sanity ---
        if confidence_status is not None and confidence_status not in VALID_STATUSES:
            raise ValueError(
                f"Invalid confidence_status '{confidence_status}' — must be "
                f"one of {sorted(VALID_STATUSES)} or None."
            )

        # --- insight_id consistency ---
        derived = _derive_insight_id(kpi_name, period, category)
        if insight_id is not None and insight_id != derived:
            raise ValueError(
                f"insight_id '{insight_id}' does not match the derived id "
                f"'{derived}' for (kpi='{kpi_name}', period='{period}', "
                f"category={category!r}) — stale reference rejected."
            )

        ts = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO insight_feedback
                    (timestamp, insight_id, kpi_name, period, category,
                     persona, rating, note, confidence_status,
                     confidence_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    derived,
                    kpi_name,
                    period,
                    category,
                    persona,
                    rating,
                    note,
                    confidence_status,
                    float(confidence_score) if confidence_score is not None else None,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    # --------------------------------------------------------
    # Fetching
    # --------------------------------------------------------

    def fetch(
        self,
        limit: Optional[int] = None,
        insight_id: Optional[str] = None,
        kpi_name: Optional[str] = None,
        period: Optional[str] = None,
        category: Optional[str] = None,
        persona: Optional[str] = None,
        rating: Optional[str] = None,
        confidence_status: Optional[str] = None,
    ) -> list[dict]:
        """Fetch feedback rows (newest first), optionally filtered."""
        query = "SELECT * FROM insight_feedback"
        conditions: list[str] = []
        params: list = []
        for col, val in (
            ("insight_id", insight_id),
            ("kpi_name", kpi_name),
            ("period", period),
            ("persona", persona),
            ("rating", rating),
            ("confidence_status", confidence_status),
        ):
            if val is not None:
                conditions.append(f"{col} = ?")
                params.append(val)
        # Note: category=None is indistinguishable from "no filter"
        # (aggregate insights also have category NULL), so filtering on
        # category is only applied when a value is given.
        if category is not None:
            conditions.append("category = ?")
            params.append(category)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()

        return [
            {
                "id": int(r["id"]),
                "timestamp": r["timestamp"],
                "insight_id": r["insight_id"],
                "kpi_name": r["kpi_name"],
                "period": r["period"],
                "category": r["category"],
                "persona": r["persona"],
                "rating": r["rating"],
                "note": r["note"],
                "confidence_status": r["confidence_status"],
                "confidence_score": (
                    float(r["confidence_score"])
                    if r["confidence_score"] is not None else None
                ),
            }
            for r in rows
        ]

    # --------------------------------------------------------
    # Aggregation (the calibration-signal table)
    # --------------------------------------------------------

    def summary(self) -> dict:
        """
        Aggregate feedback for the calibration explanation:
          - by_insight: votes per insight_id (agreement rate)
          - by_kpi_status_persona: up-rates + feedback factor per
            (KPI, confidence level, persona). Abstain rows are counted
            but EXCLUDED from factor computation (see module docstring).
        JSON-safe (native types only).
        """
        rows = self.fetch()

        by_insight: dict[str, dict] = {}
        by_key: dict[str, dict] = {}
        for row in rows:
            iid = row["insight_id"]
            e = by_insight.setdefault(
                iid,
                {
                    "insight_id": iid,
                    "kpi_name": row["kpi_name"],
                    "period": row["period"],
                    "category": row["category"],
                    "ups": 0,
                    "downs": 0,
                    "total": 0,
                    "personas": [],
                },
            )
            e["ups" if row["rating"] == "up" else "downs"] += 1
            e["total"] += 1
            if row["persona"] not in e["personas"]:
                e["personas"].append(row["persona"])

            key = f"{row['kpi_name']}|{row['confidence_status']}|{row['persona']}"
            k = by_key.setdefault(key, {"ups": 0, "downs": 0})
            k["ups" if row["rating"] == "up" else "downs"] += 1

        for e in by_insight.values():
            e["agreement"] = (
                round(e["ups"] / e["total"], 3) if e["total"] else None
            )

        calib = []
        for key, k in sorted(by_key.items()):
            kpi, status, persona = key.split("|", 2)
            total = k["ups"] + k["downs"]
            factor = None if status == "abstain" else feedback_factor(k["ups"], k["downs"])
            calib.append({
                "kpi_name": kpi,
                "confidence_status": status,
                "persona": persona,
                "ups": k["ups"],
                "downs": k["downs"],
                "total": total,
                "up_rate": round(k["ups"] / total, 3) if total else None,
                "feedback_factor": factor,
                "excluded_from_factor": status == "abstain",
            })

        return {
            "by_insight": list(by_insight.values()),
            "by_kpi_status_persona": calib,
        }


# ============================================================
# Tie-back helper (pipeline output -> feedback payload)
# ============================================================


def attach_feedback_context(
    confidence_result,
    persona: str,
) -> dict:
    """
    Build the ready-to-record feedback payload for one insight, straight
    from the Phase 5 pipeline output.

    Works for both anomalies and sparse-history flags (both are
    ConfidenceResults). The returned dict carries everything the UI/API
    (Phase 12) needs so a click maps to exactly this insight + persona:

        {insight_id, kpi_name, period, category, persona,
         confidence_status, confidence_score}

    Usage:
        ctx = attach_feedback_context(result, persona)
        store.record(ctx["kpi_name"], ctx["period"], persona, "up",
                     category=ctx["category"],
                     confidence_status=ctx["confidence_status"],
                     confidence_score=ctx["confidence_score"],
                     insight_id=ctx["insight_id"])
    """
    period = getattr(confidence_result, "period", None)
    if not period:
        raise ValueError(
            "Cannot attach feedback context: the result has no period "
            "(every narrated insight has one)."
        )
    kpi_name = str(confidence_result.kpi_name)
    category = confidence_result.category
    return {
        "insight_id": insight_id(kpi_name, str(period), category),
        "kpi_name": kpi_name,
        "period": str(period),
        "category": category,
        "persona": persona,
        "confidence_status": str(confidence_result.status),
        "confidence_score": (
            float(confidence_result.score)
            if confidence_result.score is not None else None
        ),
    }
