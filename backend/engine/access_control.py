"""
Access Control Engine — Persona → KPI/Column Permission Filter
==============================================================

Phase 6. Enforces the semantic contract's `persona_access` rules BEFORE
any data reaches the narration layer — a blocked KPI must never be part
of the JSON payload handed to the LLM, and every access attempt
(allowed or denied) is written to a structured SQLite access log that
the UI (Phase 11) can render as a visible "blocked" state.

Design principles:
  - ZERO hardcoded permission lists. All rules come from the semantic
    contract (kpi_contracts.yaml → per-KPI `persona_access`).
  - Fail closed: unknown personas and unknown KPIs are denied.
  - KPI-level enforcement via `persona_access`, plus an optional
    column-level restriction mechanism driven by an optional per-KPI
    `column_restrictions` block in the contract (currently unused by
    the synthetic dataset — implemented so a sensitive column can be
    added to the contract without code changes).
  - Every `check_kpi()` call produces an `AccessDecision` and, by
    default, a row in the `access_log` table.

Concrete scenario (Event 4): persona "Category Manager" requesting
KPI "Gross Margin %" → blocked, logged with full detail.

Usage:
    from engine.access_control import PermissionGuard
    guard = PermissionGuard("Category Manager")
    decision = guard.check_kpi("Gross Margin %")   # blocked, logged
    guard.fetch_log()                              # last entries first
"""

from __future__ import annotations

import os
import sqlite3
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Iterable, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from contracts.loader import ContractStore, KPINotFoundError


# ============================================================
# Actions & sources
# ============================================================

ACTION_ALLOWED = "allowed"
ACTION_BLOCKED = "blocked"

SOURCE_PERSONA_ACCESS = "kpi_contracts.yaml:persona_access"
SOURCE_UNKNOWN_PERSONA = "kpi_contracts.yaml:unknown_persona"
SOURCE_UNKNOWN_KPI = "kpi_contracts.yaml:unknown_kpi"

# Default log location (gitignored via backend/data/raw/*.db)
DEFAULT_LOG_DB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "raw", "access_log.db",
)


# ============================================================
# Data structures
# ============================================================


@dataclass
class AccessDecision:
    """Outcome of one access-control check against a persona + KPI."""

    persona: str
    kpi_name: str
    allowed: bool
    action: str                    # "allowed" | "blocked"
    reason: str                    # human-readable
    timestamp: str                 # ISO-8601 UTC
    source: str                    # contract provenance of the rule
    restricted_columns: list = field(default_factory=list)  # stripped columns (if any)

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================
# Access log store (SQLite)
# ============================================================


class AccessLogStore:
    """
    SQLite-backed audit log for access-control decisions.

    Schema (Phase 11 renders blocked states from these fields):
      id, timestamp, persona, kpi_name, action, allowed,
      reason, source, restricted_columns
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = os.path.abspath(db_path or DEFAULT_LOG_DB)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS access_log (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp          TEXT    NOT NULL,
                    persona            TEXT    NOT NULL,
                    kpi_name           TEXT    NOT NULL,
                    action             TEXT    NOT NULL,
                    allowed            INTEGER NOT NULL,
                    reason             TEXT    NOT NULL,
                    source             TEXT    NOT NULL,
                    restricted_columns TEXT    NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_access_log_persona_kpi "
                "ON access_log (persona, kpi_name)"
            )
            conn.commit()

    def record(self, decision: AccessDecision) -> int:
        """Insert one decision; returns the new row id."""
        cols = ",".join(
            str(c) for c in decision.restricted_columns
        ) if decision.restricted_columns else ""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO access_log
                    (timestamp, persona, kpi_name, action, allowed,
                     reason, source, restricted_columns)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.timestamp,
                    decision.persona,
                    decision.kpi_name,
                    decision.action,
                    1 if decision.allowed else 0,
                    decision.reason,
                    decision.source,
                    cols,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def fetch(
        self,
        limit: Optional[int] = None,
        persona: Optional[str] = None,
        kpi_name: Optional[str] = None,
        action: Optional[str] = None,
    ) -> list[dict]:
        """
        Fetch log entries (newest first), optionally filtered.

        Returns plain dicts — JSON-serializable for the API/UI.
        """
        query = "SELECT * FROM access_log"
        conditions: list[str] = []
        params: list = []
        if persona is not None:
            conditions.append("persona = ?")
            params.append(persona)
        if kpi_name is not None:
            conditions.append("kpi_name = ?")
            params.append(kpi_name)
        if action is not None:
            conditions.append("action = ?")
            params.append(action)
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
                "persona": r["persona"],
                "kpi_name": r["kpi_name"],
                "action": r["action"],
                "allowed": bool(r["allowed"]),
                "reason": r["reason"],
                "source": r["source"],
                "restricted_columns": (
                    [c for c in r["restricted_columns"].split(",") if c]
                    if r["restricted_columns"] else []
                ),
            }
            for r in rows
        ]


# ============================================================
# Permission guard
# ============================================================


class PermissionGuard:
    """
    Persona-aware access controller driven entirely by the contract.

    Construct once per persona per request, then:
        guard.check_kpi("Gross Margin %")      # AccessDecision (logged)
        guard.allowed_kpis()                   # full allowed list
        guard.filter_kpis([...])               # list -> allowed subset
        guard.filter_results(confidence_set)   # filtered ConfidenceResultSet
    """

    def __init__(
        self,
        persona: str,
        contract: Optional[ContractStore] = None,
        log: Optional[AccessLogStore] = None,
        auto_log: bool = True,
    ):
        self.persona = persona
        self.contract = contract or ContractStore()
        self.log = log or AccessLogStore()
        self.auto_log = auto_log

    # --------------------------------------------------------
    # Contract-driven helpers
    # --------------------------------------------------------

    def known_personas(self) -> list[str]:
        """All personas referenced anywhere in the contract (union, ordered)."""
        found: list[str] = []
        for kpi in self.contract.list_kpis():
            for p in self.contract.get_kpi(kpi).get("persona_access", []):
                if p not in found:
                    found.append(p)
        return found

    def restricted_columns_for(self, kpi_name: str,
                               persona: Optional[str] = None) -> list[str]:
        """
        Columns to strip for a persona, from the optional per-KPI
        `column_restrictions` contract block.

        Contract shape (optional, currently unused by the dataset):
            column_restrictions:
              Category Manager: [unit_cost]
        Returns [] when no restriction is declared (fail-open for
        columns is acceptable because absence means no sensitive
        columns are defined; KPI-level access is always fail-closed).
        """
        kpi = self.contract.get_kpi(kpi_name)
        restrictions = kpi.get("column_restrictions") or {}
        target = persona or self.persona
        return [str(c) for c in restrictions.get(target, [])]

    # --------------------------------------------------------
    # Decision logic (fail closed)
    # --------------------------------------------------------

    def _decision(self, kpi_name: str, allowed: bool, action: str,
                  reason: str, source: str,
                  restricted_columns: Optional[list] = None) -> AccessDecision:
        return AccessDecision(
            persona=self.persona,
            kpi_name=kpi_name,
            allowed=allowed,
            action=action,
            reason=reason,
            timestamp=datetime.now(timezone.utc).isoformat(),
            source=source,
            restricted_columns=restricted_columns or [],
        )

    def _known_persona(self) -> bool:
        return self.persona in self.known_personas()

    def check_kpi(self, kpi_name: str, auto_log: Optional[bool] = None) -> AccessDecision:
        """
        Check whether `self.persona` may access `kpi_name`.

        Fail closed: unknown persona or unknown KPI → blocked.
        Result is logged unless auto_log=False.
        """
        log_this = self.auto_log if auto_log is None else auto_log

        # Unknown persona -> deny (fail closed)
        if not self._known_persona():
            decision = self._decision(
                kpi_name,
                allowed=False,
                action=ACTION_BLOCKED,
                reason=(
                    f"Persona '{self.persona}' is not a known persona in the "
                    f"contract (known: {', '.join(self.known_personas())}). "
                    f"Access denied — fail closed."
                ),
                source=SOURCE_UNKNOWN_PERSONA,
            )
            if log_this:
                self.log.record(decision)
            return decision

        # Unknown KPI -> deny (fail closed)
        try:
            kpi = self.contract.get_kpi(kpi_name)
        except KPINotFoundError:
            decision = self._decision(
                kpi_name,
                allowed=False,
                action=ACTION_BLOCKED,
                reason=(
                    f"KPI '{kpi_name}' is not defined in the contract and "
                    f"cannot be granted. Access denied — fail closed."
                ),
                source=SOURCE_UNKNOWN_KPI,
            )
            if log_this:
                self.log.record(decision)
            return decision

        # Contract persona_access rule
        persona_list = kpi.get("persona_access", [])
        allowed = self.persona in persona_list
        restricted = self.restricted_columns_for(kpi_name, self.persona)

        if allowed:
            reason = (
                f"Persona '{self.persona}' may access KPI '{kpi_name}' "
                f"(contract persona_access)."
            )
            if restricted:
                reason += f" Columns redacted: {', '.join(restricted)}."
        else:
            reason = (
                f"Persona '{self.persona}' is NOT granted access to KPI "
                f"'{kpi_name}' (contract persona_access lists: "
                f"{', '.join(persona_list) or 'no one'}). Blocked before "
                f"narration."
            )

        decision = self._decision(
            kpi_name,
            allowed=allowed,
            action=ACTION_ALLOWED if allowed else ACTION_BLOCKED,
            reason=reason,
            source=SOURCE_PERSONA_ACCESS,
            restricted_columns=restricted,
        )
        if log_this:
            self.log.record(decision)
        return decision

    # --------------------------------------------------------
    # Bulk filtering
    # --------------------------------------------------------

    def allowed_kpis(self) -> list[str]:
        """Full list of KPIs this persona may access (per contract)."""
        return self.contract.get_kpis_for_persona(self.persona)

    def filter_kpis(self, kpi_names: Iterable[str]) -> list[str]:
        """
        Return the subset of `kpi_names` this persona may access.

        Each denied KPI produces a logged AccessDecision (deduplicated
        per KPI_name, so bulk calls do not flood the log). Denials are
        never dropped — the block must always be auditable.
        """
        seen: set[str] = set()
        allowed: list[str] = []
        for name in kpi_names:
            if name in seen:
                continue
            seen.add(name)
            decision = self.check_kpi(name, auto_log=False)
            if decision.allowed:
                allowed.append(name)
            else:
                self.log.record(decision)
        return allowed

    def filter_results(self, results) -> object:
        """
        Filter a ConfidenceResultSet (or any iterable of results with
        `.kpi_name`) to only the KPIs this persona may access.

        This is the gate the narration/pipeline layer must run BEFORE
        building the LLM payload — blocked KPI data never reaches it.
        Denied KPIs are logged (one entry per KPI, deduplicated).
        """
        # Local import to avoid a hard dependency at module import time.
        from engine.confidence import ConfidenceResultSet

        allowed_kpis = set(self.allowed_kpis())
        seen: set[str] = set()
        kept = []
        for r in results.results if isinstance(results, ConfidenceResultSet) else results:
            if r.kpi_name in allowed_kpis:
                kept.append(r)
            elif r.kpi_name not in seen:
                seen.add(r.kpi_name)
                self.log.record(self.check_kpi(r.kpi_name, auto_log=False))
        if isinstance(results, ConfidenceResultSet):
            return ConfidenceResultSet(results=kept)
        return kept

    def apply_column_filter(self, kpi_name: str, dataframe):
        """
        Strip contract-declared restricted columns from a DataFrame for
        this persona. No-op unless the KPI declares `column_restrictions`.
        """
        restricted = set(self.restricted_columns_for(kpi_name, self.persona))
        if not restricted:
            return dataframe
        cols = [c for c in dataframe.columns if c not in restricted]
        return dataframe[cols]

    def fetch_log(self, **kwargs) -> list[dict]:
        """Convenience passthrough to the underlying log store."""
        return self.log.fetch(**kwargs)


# ============================================================
# Convenience single-call API
# ============================================================


def enforce_access(
    persona: str,
    kpi_name: str,
    contract: Optional[ContractStore] = None,
    log: Optional[AccessLogStore] = None,
) -> AccessDecision:
    """One-shot check: returns (and logs) an AccessDecision."""
    return PermissionGuard(persona, contract=contract, log=log).check_kpi(kpi_name)
