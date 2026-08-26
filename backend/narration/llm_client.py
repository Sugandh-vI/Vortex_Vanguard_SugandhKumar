"""
Provider-Agnostic LLM Client (Ollama default) + Mock-Mode Fallback
==================================================================

Phase 8. A thin, provider-agnostic interface — `LLMClient.complete()`
— that any OpenAI-compatible backend can satisfy. Default provider is
Ollama (local `ollama serve` pointing at a cloud-backed model such as
`minimax-m3:cloud`), configured entirely via `.env`:

    OLLAMA_BASE_URL   (default http://localhost:11434)
    OLLAMA_MODEL      (default minimax-m3:cloud)
    LLM_MOCK_MODE     (default false; "true" forces mock mode)

If Ollama is unavailable (connection refused / model not pulled /
timeout), the client falls back to MockProvider automatically so the
rest of the pipeline is always testable without a running LLM.

**Design rule (most important in the project):** the LLM is NEVER the
source of quantitative truth. `complete()` takes a text prompt that
already contains only pre-computed facts; the system prompt instructs
the model to use exactly and only those facts and never compute,
infer, or invent numbers. MockProvider implements the same contract
deterministically by constructing its narrative verbatim from the
fact map it is given — so mock mode is a faithful test oracle for the
same payload structure a real model will see.

Usage:
    from narration.llm_client import LLMClient
    client = LLMClient.from_env()          # Ollama or mock (auto)
    text, meta = client.complete(prompt)   # (narrative, usage metadata)

    # Real provider (unavailable in cloud sandbox — for local use):
    #   OLLAMA_BASE_URL=http://localhost:11434 OLLAMA_MODEL=minimax-m3:cloud
"""

from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # dotenv is optional; env vars can be set directly
    pass


# ============================================================
# Configuration constants (env-driven, no hardcoded secrets)
# ============================================================

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "minimax-m3:cloud"
DEFAULT_TIMEOUT_SECONDS = 60


def _env_or(key: str, default: str) -> str:
    return os.environ.get(key, default)


def ollama_base_url() -> str:
    return _env_or("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).rstrip("/")


def ollama_model() -> str:
    return _env_or("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)


def mock_mode_enforced() -> bool:
    """True if LLM_MOCK_MODE=true — force mock, never touch a real LLM."""
    return os.environ.get("LLM_MOCK_MODE", "false").strip().lower() == "true"


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() in ("1", "true", "yes")


# ============================================================
# Exceptions
# ============================================================


class LLMError(Exception):
    """Base error for LLM provider failures."""


class ProviderUnavailableError(LLMError):
    """Raised when the configured provider cannot be reached (mock fallback covers this)."""


class PromptError(ValueError):
    """Raised when a prompt or payload is malformed (missing fact map etc.)."""


# ============================================================
# Provider interface
# ============================================================


class LLMProvider(ABC):
    """Provider-agnostic interface. Any OpenAI-compatible backend fits."""

    name: str = "base"

    @abstractmethod
    def complete(self, prompt: str) -> "LLMResponse":
        """Return a completed response for `prompt`."""

    def is_available(self) -> bool:
        """Cheap availability probe (default: assume available)."""
        return True


@dataclass
class LLMResponse:
    """Normalized provider response: text + usage metadata."""

    text: str
    usage: dict = field(default_factory=dict)  # prompt_tokens, completion_tokens, ...
    provider: str = ""
    model: str = ""
    latency_ms: float = 0.0
    raw: Any = None
    mock: bool = False


# ============================================================
# Ollama provider (real; only usable where `ollama serve` runs)
# ============================================================


class OllamaProvider(LLMProvider):
    """Ollama backend via its HTTP API (OpenAI-compatible chat shape)."""

    name = "ollama"

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ):
        self.base_url = (base_url or ollama_base_url()).rstrip("/")
        self.model = model or ollama_model()
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens

    def is_available(self) -> bool:
        """Ping /api/tags — cheap, does not generate tokens."""
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    def complete(self, prompt: str) -> LLMResponse:
        start = time.perf_counter()
        try:
            resp = httpx.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {
                        "temperature": self.temperature,
                        "num_predict": self.max_tokens,
                    },
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            raise ProviderUnavailableError(
                f"Ollama at {self.base_url} unreachable: {e}"
            ) from e

        content = ""
        message = data.get("message") or {}
        content = message.get("content", "")
        if not content and isinstance(data.get("response"), str):
            content = data["response"]

        usage = data.get("prompt_eval_count", 0) or 0
        usage = {
            "prompt_tokens": int(data.get("prompt_eval_count", 0) or 0),
            "completion_tokens": int(data.get("eval_count", 0) or 0),
            "total_tokens": int(
                (data.get("prompt_eval_count", 0) or 0)
                + (data.get("eval_count", 0) or 0)
            ),
            "model": self.model,
            "provider": self.name,
            "source": "llm_response_metadata",  # never computed client-side
        }
        return LLMResponse(
            text=content,
            usage=usage,
            provider=self.name,
            model=self.model,
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
            raw=data,
            mock=False,
        )


# ============================================================
# Mock provider (deterministic test oracle — no real LLM)
# ============================================================


class MockProvider(LLMProvider):
    """
    Deterministic mock narrator.

    Produces a plain-language narrative built ONLY from the fact map it
    is handed (parsed from the prompt's `{facts}` slot). It performs no
    arithmetic and invents no facts — it mirrors the contract a real
    model must follow, so mock mode is a faithful test oracle for the
    payload structure (Phase 5/6/7 pipeline output) without a running
    model.

    Output is persona-differentiated through deterministic templates
    (CFO vs Category Manager) and reports `mock: true` so it is always
    clearly labeled as placeholder output in the UI/telemetry.
    """

    name = "mock"

    def __init__(self, persona: str = "CFO", model: str = "mock-llm"):
        self.persona = persona
        self.model = model

    def is_available(self) -> bool:
        return True  # mock is always available

    # -----------------------------------------------------
    # Fact map extraction (the single factual source)
    # ------------------------------------------------------

    @staticmethod
    def extract_facts(prompt: str) -> dict:
        """
        Pull the JSON `{facts}` block from the prompt (pre-computed data).

        The prompt may contain template braces elsewhere
        (e.g. `expected_impact{value_min,...}`), so we anchor on the
        FACTS_JSON marker and parse starting at the first `{` after it.
        """
        marker = "FACTS_JSON:"
        if marker not in prompt:
            raise PromptError("MockProvider: prompt has no FACTS_JSON marker.")
        seg = prompt.split(marker, 1)[1].strip()

        # Strip fenced code block markers if present.
        if seg.startswith("```"):
            seg = seg.split("\n", 1)[1] if "\n" in seg else seg
            seg = seg.rsplit("```", 1)[0].strip()

        # Anchor on the first JSON object start after the marker.
        start = seg.find("{")
        if start == -1:
            raise PromptError("MockProvider: no JSON object after FACTS_JSON marker.")
        try:
            return json.loads(seg[start:])
        except Exception:
            # Fall back to a balanced-brace scan in case trailing text
            # (e.g. the final instruction line) follows the JSON.
            depth = 0
            for i in range(start, len(seg)):
                ch = seg[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(seg[start:i + 1])
                        except Exception:
                            break
        raise PromptError("MockProvider could not parse the facts JSON in the prompt.")

    # -----------------------------------------------------
    # Persona templates
    # ------------------------------------------------------

    @staticmethod
    def _get(facts: dict, *path, default: Any = "") -> Any:
        cur = facts
        for key in path:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(key, default)
        return cur

    @staticmethod
    def _fmt(value: Any) -> str:
        if isinstance(value, float):
            return f"{value:,.2f}".rstrip("0").rstrip(".")
        if isinstance(value, (int,)):
            return f"{value:,}"
        return str(value)

    def _narrative(self, facts: dict) -> str:
        kpi = str(self._get(facts, "kpi_name", default="the KPI"))
        period = str(self._get(facts, "period", default="this period"))
        current = self._get(facts, "current_value", default="")
        baseline = self._get(facts, "baseline_value", default="")
        change = self._get(facts, "change", default="")
        pct = self._get(facts, "pct_change", default="")
        direction = str(self._get(facts, "direction", default=""))
        status = str(self._get(facts, "confidence", "status", default=""))

        headline = (
            f"[MOCK] {kpi} ({period}): moved {direction} "
            f"from {self._fmt(baseline)} to {self._fmt(current)} "
            f"(change {self._fmt(change)}, {self._fmt(pct)}%)."
        )

        body_parts: list[str] = []
        drivers = self._get(facts, "drivers", default=[]) or []
        if drivers:
            parts = []
            for d in drivers:
                driver_name = self._get(d, "driver_name", default="driver")
                value = self._get(d, "contribution_value", default=0)
                parts.append(f"{driver_name} {self._fmt(value)}")
            body_parts.append("Drivers: " + ", ".join(parts) + ".")
        explained = self._get(facts, "explained_pct", default="")
        if explained != "":
            body_parts.append(f"Model explains {self._fmt(explained)}% of the movement.")

        actions = self._get(facts, "actions", "recommendations", default=[]) or []
        if actions:
            action_text = "; ".join(
                str(a) for a in actions[:3]
            )
            body_parts.append(f"Recommended actions: {action_text}.")

        conf_note = self._get(facts, "confidence", "message", default="")
        if conf_note:
            body_parts.append(f"Confidence: {conf_note}")

        body = " ".join(body_parts)

        if self.persona == "CFO":
            tone = (
                "From the CFO lens, the dollar impact leads: this movement "
                "matters to margin and cash position first."
            )
        else:
            tone = (
                "From the Category Manager lens, the operational drivers "
                "matter: what moved volume and what the category team can do."
            )
        return f"{headline}\n{body}\n{tone}"

    def complete(self, prompt: str) -> LLMResponse:
        start = time.perf_counter()
        facts = self.extract_facts(prompt)
        text = self._narrative(facts)
        # Mock token usage is derived from payload size only, and is
        # explicitly labeled as an estimate (never presented as real).
        usage = {
            "prompt_tokens": max(0, len(prompt) // 4),
            "completion_tokens": max(0, len(text) // 4),
            "total_tokens": (len(prompt) + len(text)) // 4,
            "model": self.model,
            "provider": self.name,
            "source": "mock_estimate",
            "mock": True,
        }
        return LLMResponse(
            text=text,
            usage=usage,
            provider=self.name,
            model=self.model,
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
            raw={"mock": True, "persona": self.persona},
            mock=True,
        )


# ============================================================
# Client facade (provider-agnostic entry point)
# ============================================================


class LLMClient:
    """
    Wraps a provider behind one interface: `complete(prompt)`.

    Selection (from .env, in priority order):
      1. LLM_MOCK_MODE=true  -> MockProvider (forced)
      2. Ollama reachable    -> OllamaProvider
      3. otherwise           -> MockProvider (automatic fallback)
    """

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        persona: str = "CFO",
        auto_fallback: bool = True,
    ):
        self.persona = persona
        self.auto_fallback = auto_fallback
        self.provider = provider or self._select_provider()
        self.mock = isinstance(self.provider, MockProvider)
        self.last_response: Optional[LLMResponse] = None

    @classmethod
    def from_env(cls, persona: str = "CFO") -> "LLMClient":
        return cls(provider=None, persona=persona)

    def _select_provider(self) -> LLMProvider:
        if mock_mode_enforced():
            return MockProvider(persona=self.persona)
        provider = OllamaProvider()
        if provider.is_available():
            return provider
        if self.auto_fallback:
            # Log-free fallback: mock mode is visible via response.mock=True
            return MockProvider(persona=self.persona)
        raise ProviderUnavailableError(
            f"Ollama not available at {ollama_base_url()} and auto-fallback disabled."
        )

    def complete(self, prompt: str) -> LLMResponse:
        resp = self.provider.complete(prompt)
        self.last_response = resp
        return resp

    # Convenience config accessors (exposed for telemetry/narration)
    def provider_name(self) -> str:
        return self.provider.name

    def model_name(self) -> str:
        return getattr(self.provider, "model", "")

    def describe(self) -> dict:
        return {
            "provider": self.provider.name,
            "model": self.model_name(),
            "mock": self.mock,
            "persona": self.persona,
        }
