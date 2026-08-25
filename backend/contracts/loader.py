"""
KPI Contract Loader & Validator
================================

Loads `kpi_contracts.yaml`, validates its structure, and provides
typed accessor methods for the rest of the engine to query KPI
definitions, persona access rules, thresholds, drivers, and lineage.

Usage:
    from contracts.loader import ContractStore
    store = ContractStore()              # auto-loads from default path
    store = ContractStore("path/to.yaml")  # or specify a path

    store.list_kpis()                    # -> ["Revenue", "Units Sold", ...]
    store.get_kpi("Revenue")             # -> full KPI dict
    store.is_accessible("Gross Margin %", "Category Manager")  # -> False
    store.get_kpis_for_persona("CFO")    # -> [all 4 KPIs]
    store.get_materiality("Revenue")     # -> {"pct_change": 5.0, ...}
    store.get_drivers("Revenue")         # -> [driver dicts]
    store.get_lineage("Revenue")         # -> {"primary": [...], "supporting": [...]}
    store.get_source_meta("sales_transactions")  # -> source dict
    store.get_confidence_config()        # -> confidence levels dict
    store.get_sparse_history_config()    # -> sparse history thresholds
"""

import os
from typing import Any, Optional

import yaml


# ============================================================
# Validation schema — required fields per section
# ============================================================

_REQUIRED_KPI_FIELDS = {
    "name",
    "definition",
    "formula",
    "source_tables",
    "grain",
    "refresh_cadence",
    "persona_access",
    "known_drivers",
    "materiality_thresholds",
    "lineage",
}

_REQUIRED_DRIVER_FIELDS = {
    "name",
    "type",
    "description",
}

_REQUIRED_SOURCE_FIELDS = {
    "grain",
    "refresh_cadence",
    "key_columns",
}

_REQUIRED_MATERIALITY_FIELDS = {
    "pct_change",
    "impact_unit",
}

_VALID_DRIVER_TYPES = {"controllable", "semi_controllable", "uncontrollable"}


# ============================================================
# Exceptions
# ============================================================


class ContractValidationError(Exception):
    """Raised when the contract YAML fails validation."""
    pass


class KPINotFoundError(KeyError):
    """Raised when a requested KPI is not in the contract."""
    pass


# ============================================================
# ContractStore
# ============================================================


class ContractStore:
    """
    Loads, validates, and provides access to the KPI semantic contract.

    All engine modules should use this class to look up KPI definitions,
    access rules, thresholds, drivers, and lineage — never by hardcoding
    these values elsewhere.
    """

    def __init__(self, yaml_path: Optional[str] = None):
        if yaml_path is None:
            yaml_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "kpi_contracts.yaml",
            )
        self._path = yaml_path
        self._raw = self._load(yaml_path)
        self._validate()

        # Build lookup index: KPI name -> KPI dict
        self._kpi_index: dict[str, dict] = {}
        for kpi in self._raw["kpis"]:
            self._kpi_index[kpi["name"]] = kpi

    # --------------------------------------------------------
    # Loading
    # --------------------------------------------------------

    @staticmethod
    def _load(path: str) -> dict:
        """Load and parse the YAML file."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Contract file not found: {path}")
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ContractValidationError("Contract YAML must be a mapping at root level.")
        return data

    # --------------------------------------------------------
    # Validation
    # --------------------------------------------------------

    def _validate(self) -> None:
        """Validate the full contract structure."""
        errors: list[str] = []

        # --- Top-level keys ---
        if "kpis" not in self._raw:
            errors.append("Missing top-level 'kpis' key.")
        if "sources" not in self._raw:
            errors.append("Missing top-level 'sources' key.")

        if errors:
            raise ContractValidationError("\n".join(errors))

        # --- Validate sources ---
        for src_name, src in self._raw["sources"].items():
            missing = _REQUIRED_SOURCE_FIELDS - set(src.keys())
            if missing:
                errors.append(f"Source '{src_name}' missing fields: {missing}")

        # --- Validate each KPI ---
        kpi_names = set()
        for i, kpi in enumerate(self._raw["kpis"]):
            prefix = f"KPI #{i+1}"
            if "name" in kpi:
                prefix = f"KPI '{kpi['name']}'"

            # Required fields
            missing = _REQUIRED_KPI_FIELDS - set(kpi.keys())
            if missing:
                errors.append(f"{prefix} missing fields: {missing}")
                continue

            # Unique names
            if kpi["name"] in kpi_names:
                errors.append(f"{prefix} has duplicate name.")
            kpi_names.add(kpi["name"])

            # Source tables must be defined in sources
            for src in kpi.get("source_tables", []):
                if src not in self._raw["sources"]:
                    errors.append(f"{prefix} references unknown source '{src}'.")

            # Persona access must be a list
            if not isinstance(kpi.get("persona_access"), list):
                errors.append(f"{prefix}: 'persona_access' must be a list.")

            # Validate drivers
            for j, driver in enumerate(kpi.get("known_drivers", [])):
                d_missing = _REQUIRED_DRIVER_FIELDS - set(driver.keys())
                if d_missing:
                    errors.append(f"{prefix} driver #{j+1} missing: {d_missing}")
                if driver.get("type") and driver["type"] not in _VALID_DRIVER_TYPES:
                    errors.append(
                        f"{prefix} driver '{driver.get('name')}' has invalid type "
                        f"'{driver['type']}'. Must be one of {_VALID_DRIVER_TYPES}."
                    )

            # Validate materiality thresholds
            mat = kpi.get("materiality_thresholds", {})
            mat_missing = _REQUIRED_MATERIALITY_FIELDS - set(mat.keys())
            if mat_missing:
                errors.append(f"{prefix} materiality missing: {mat_missing}")

            # Validate lineage
            lineage = kpi.get("lineage", {})
            if "primary" not in lineage:
                errors.append(f"{prefix} lineage missing 'primary' key.")

        if errors:
            raise ContractValidationError(
                f"Contract validation failed with {len(errors)} error(s):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

    # --------------------------------------------------------
    # KPI accessors
    # --------------------------------------------------------

    def list_kpis(self) -> list[str]:
        """Return a list of all KPI names in the contract."""
        return list(self._kpi_index.keys())

    def get_kpi(self, name: str) -> dict[str, Any]:
        """Return the full KPI definition dict. Raises KPINotFoundError if not found."""
        if name not in self._kpi_index:
            raise KPINotFoundError(f"KPI '{name}' not found in contract. Available: {self.list_kpis()}")
        return self._kpi_index[name]

    # --------------------------------------------------------
    # Persona / access control
    # --------------------------------------------------------

    def is_accessible(self, kpi_name: str, persona: str) -> bool:
        """Check if a persona is allowed to see a given KPI."""
        kpi = self.get_kpi(kpi_name)
        return persona in kpi["persona_access"]

    def get_kpis_for_persona(self, persona: str) -> list[str]:
        """Return the list of KPI names accessible to a persona."""
        return [
            name for name, kpi in self._kpi_index.items()
            if persona in kpi["persona_access"]
        ]

    # --------------------------------------------------------
    # Materiality thresholds
    # --------------------------------------------------------

    def get_materiality(self, kpi_name: str) -> dict[str, Any]:
        """Return the materiality thresholds for a KPI."""
        return self.get_kpi(kpi_name)["materiality_thresholds"]

    # --------------------------------------------------------
    # Drivers
    # --------------------------------------------------------

    def get_drivers(self, kpi_name: str) -> list[dict[str, Any]]:
        """Return the list of known drivers for a KPI."""
        return self.get_kpi(kpi_name)["known_drivers"]

    # --------------------------------------------------------
    # Lineage
    # --------------------------------------------------------

    def get_lineage(self, kpi_name: str) -> dict[str, Any]:
        """Return the lineage (primary + supporting column references) for a KPI."""
        return self.get_kpi(kpi_name)["lineage"]

    # --------------------------------------------------------
    # Source metadata
    # --------------------------------------------------------

    def get_source_meta(self, source_name: str) -> dict[str, Any]:
        """Return metadata for a data source."""
        sources = self._raw.get("sources", {})
        if source_name not in sources:
            raise KeyError(f"Source '{source_name}' not found. Available: {list(sources.keys())}")
        return sources[source_name]

    def list_sources(self) -> list[str]:
        """Return all source table names."""
        return list(self._raw.get("sources", {}).keys())

    # --------------------------------------------------------
    # Confidence & sparse-history config
    # --------------------------------------------------------

    def get_confidence_config(self) -> dict[str, Any]:
        """Return the confidence scoring configuration."""
        return self._raw.get("confidence", {})

    def get_sparse_history_config(self) -> dict[str, Any]:
        """Return the sparse-history thresholds."""
        return self._raw.get("sparse_history", {})

    # --------------------------------------------------------
    # Data quality requirements (per-KPI, optional)
    # --------------------------------------------------------

    def get_data_quality_requirements(self, kpi_name: str) -> Optional[dict[str, Any]]:
        """Return data quality gate requirements for a KPI, if any."""
        return self.get_kpi(kpi_name).get("data_quality_requirements")

    # --------------------------------------------------------
    # Formula & definition (for narration layer)
    # --------------------------------------------------------

    def get_formula(self, kpi_name: str) -> str:
        """Return the formula string for a KPI."""
        return self.get_kpi(kpi_name)["formula"]

    def get_definition(self, kpi_name: str) -> str:
        """Return the plain-English definition for a KPI."""
        return self.get_kpi(kpi_name)["definition"]

    def get_grain(self, kpi_name: str) -> str:
        """Return the grain (daily/monthly) for a KPI."""
        return self.get_kpi(kpi_name)["grain"]

    def get_unit(self, kpi_name: str) -> str:
        """Return the unit (USD, units, percent) for a KPI."""
        return self.get_kpi(kpi_name).get("unit", "unknown")

    # --------------------------------------------------------
    # String representation
    # --------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"ContractStore(path='{self._path}', "
            f"kpis={self.list_kpis()}, "
            f"sources={self.list_sources()})"
        )
