"""
Action Rules Loader & Validator
===============================

Loads `action_rules.yaml` (Phase 7 deterministic driver → lever → action
lookup table), validates its structure, and exposes typed accessors for
the recommendation engine in `engine/actions.py`.

The rules are the single source of truth for WHAT to recommend; the
engine only matches drivers to rules and computes expected-impact math.

Usage:
    from contracts.action_rules_loader import ActionRulesStore
    store = ActionRulesStore()                # default path
    store.rules                              # list[dict] in YAML order
    store.defaults                           # fallback rule dict
"""

from __future__ import annotations

import os
from typing import Any, Optional

import yaml


# ============================================================
# Exceptions
# ============================================================


class ActionRulesValidationError(Exception):
    """Raised when action_rules.yaml fails validation."""
    pass


class ActionRuleNotFoundError(KeyError):
    """Raised when a rule id is not present (informational)."""
    pass


# ============================================================
# Validation schema
# ============================================================

_REQUIRED_RULE_FIELDS = {
    "id",
    "kpi",
    "driver",
    "lever",
    "owner",
    "actions",
}

_VALID_DIRECTIONS = {"increase", "decrease"}


# ============================================================
# ActionRulesStore
# ============================================================


class ActionRulesStore:
    """
    Loads, validates, and provides the action recommendation rules.

    No matching logic lives here — matching (specificity scoring, gates,
    defaults fallback) is the engine's job in `engine/actions.py`.
    """

    def __init__(self, yaml_path: Optional[str] = None):
        if yaml_path is None:
            yaml_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "action_rules.yaml",
            )
        self._path = yaml_path
        self._raw = self._load(yaml_path)
        self._validate()
        self._defaults: dict[str, Any] = self._raw.get("defaults", {}) or {}
        self._rules: list[dict[str, Any]] = list(self._raw.get("rules", []) or [])
        self._by_id = {r["id"]: r for r in self._rules}

    # --------------------------------------------------------
    # Loading & validation
    # --------------------------------------------------------

    @staticmethod
    def _load(path: str) -> dict:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Action rules file not found: {path}")
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ActionRulesValidationError("Action rules YAML must be a mapping at root level.")
        return data

    def _validate(self) -> None:
        errors: list[str] = []

        version = self._raw.get("version")
        if version is None:
            errors.append("Missing top-level 'version' key.")

        defaults = self._raw.get("defaults")
        if defaults is None:
            errors.append("Missing top-level 'defaults' block (fallback rule required).")
        else:
            # The defaults block is the universal fallback, so it is NOT
            # KPI/driver-scoped — it only needs the generic fields.
            required = {"id", "lever", "owner", "actions", "actionable"}
            missing = required - set(defaults.keys())
            if missing:
                errors.append(f"defaults missing fields: {missing}")
            if not defaults.get("actions"):
                errors.append("defaults must declare a non-empty 'actions' list.")

        rules = self._raw.get("rules")
        if rules is None:
            errors.append("Missing top-level 'rules' list.")
        elif not isinstance(rules, list):
            errors.append("'rules' must be a list.")
        else:
            seen_ids: set[str] = set()
            for i, rule in enumerate(rules):
                prefix = f"rule #{i + 1}"
                if not isinstance(rule, dict):
                    errors.append(f"{prefix} must be a mapping.")
                    continue
                if "id" in rule:
                    prefix = f"rule '{rule['id']}'"

                missing = _REQUIRED_RULE_FIELDS - set(rule.keys())
                if missing:
                    errors.append(f"{prefix} missing fields: {missing}")

                if "id" in rule:
                    if rule["id"] in seen_ids:
                        errors.append(f"{prefix} has duplicate id.")
                    seen_ids.add(rule["id"])

                if "direction" in rule and rule["direction"] not in _VALID_DIRECTIONS:
                    errors.append(
                        f"{prefix} has invalid direction '{rule['direction']}'. "
                        f"Must be one of {_VALID_DIRECTIONS}."
                    )

                if not rule.get("actions"):
                    errors.append(f"{prefix} must declare a non-empty 'actions' list.")

                recovery = (rule.get("expected_impact") or {}).get("recovery")
                if recovery is not None:
                    if not isinstance(recovery, dict):
                        errors.append(f"{prefix} expected_impact.recovery must be a mapping.")
                    else:
                        for k in ("min", "max"):
                            if k not in recovery:
                                errors.append(f"{prefix} expected_impact.recovery missing '{k}'.")

                if "gates" in rule and not isinstance(rule["gates"], dict):
                    errors.append(f"{prefix} 'gates' must be a mapping.")

        if errors:
            raise ActionRulesValidationError(
                f"Action rules validation failed with {len(errors)} error(s):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

    # --------------------------------------------------------
    # Accessors
    # --------------------------------------------------------

    @property
    def rules(self) -> list[dict[str, Any]]:
        """All rules in YAML declaration order (tie-break order)."""
        return self._rules

    @property
    def defaults(self) -> dict[str, Any]:
        """The fallback rule (investigate & monitor)."""
        return self._defaults

    def get_rule(self, rule_id: str) -> dict[str, Any]:
        """Fetch a rule by id. Raises ActionRuleNotFoundError if absent."""
        if rule_id not in self._by_id:
            raise ActionRuleNotFoundError(
                f"Action rule '{rule_id}' not found. Available: {list(self._by_id.keys())}"
            )
        return self._by_id[rule_id]

    def list_rule_ids(self) -> list[str]:
        return list(self._by_id.keys())

    def __repr__(self) -> str:
        return (
            f"ActionRulesStore(path='{self._path}', "
            f"rules={len(self._rules)}, defaults={'yes' if self._defaults else 'no'})"
        )
