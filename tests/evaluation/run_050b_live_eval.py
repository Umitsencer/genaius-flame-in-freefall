"""Bounded live/deterministic acceptance check for Görev 050-B Sections 5 & 6.

Enforces a hard cap of <= 6 total OpenRouter `:free` completions:
- 3 SAFFIRE IV-VI case questions (VI-3 gas increases, 344 s timing meaning, crew non-extrapolation)
- 3 FLEX prediction explanation questions (Methanol Air supported, Methanol He supported, Heptane Air 3 atm NOT_SUPPORTED)

Zero retries, zero paid fallback, zero secret logging.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from genaius.app_service import AppService
from genaius.openrouter import create_openrouter_adapter_from_env, inspect_openrouter_env_status


class _QuotaBoundedAdapter:
    """Wrap OpenRouter adapter to strictly cap total live calls and detect upstream blocks."""

    def __init__(self, inner: Any, *, max_calls: int = 6) -> None:
        self.inner = inner
        self.max_calls = max_calls
        self.calls_attempted = 0
        self.blocked_error: str | None = None

    def generate(self, adapter_input: Any) -> Any:
        if self.calls_attempted >= self.max_calls:
            raise RuntimeError(f"Bounded live evaluation cap reached ({self.max_calls}).")
        self.calls_attempted += 1
        try:
            return self.inner.generate(adapter_input)
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or "rate" in msg.lower() or "quota" in msg.lower() or "credit" in msg.lower():
                self.blocked_error = msg[:160]
            raise


def run_eval() -> dict[str, Any]:
    env_status = inspect_openrouter_env_status(ROOT)
    base_adapter = create_openrouter_adapter_from_env(ROOT, strict=False)
    bounded = _QuotaBoundedAdapter(base_adapter, max_calls=6) if base_adapter is not None else None
    svc = AppService(ROOT, answer_adapter=bounded)

    cases: list[tuple[str, dict[str, Any], list[str]]] = [
        (
            "saffire_vi3_gases",
            {
                "query": "In Saffire VI-3, what gas concentration increases were measured (CO2, CO, O2) and why are V-3/V-4 gas results absent?",
                "scope": "saffire_case",
                "top_k": 4,
            },
            ["CASE-TBL:VI-3"],
        ),
        (
            "saffire_vi3_344s",
            {
                "query": "In Saffire VI-3, what does the derived 344 s value represent from ignition to the 1 mg/m3 alarm threshold?",
                "scope": "saffire_case",
                "top_k": 4,
            },
            ["CASE-DET:DET-A", "CASE-TBL:VI-3"],
        ),
        (
            "saffire_crew_exposure_limit",
            {
                "query": "What do Saffire IV-VI gas measurements tell us without predicting crew exposure or cabin safety certification?",
                "scope": "saffire_case",
                "top_k": 4,
            },
            ["CASE-TBL:"],
        ),
        (
            "flex_meth_air_explain",
            {
                "query": "Explain these FLEX model estimates for Methanol 21% O2 Air vs nearest measured PSI-69 tests and candidate false-positive limits.",
                "scope": "flex_prediction",
                "flex_condition": {
                    "fuel": "Methanol",
                    "o2_mol_frac": 0.21,
                    "co2_mol_frac": 0.0,
                    "he_mol_frac": 0.0,
                    "pressure_atm": 1.0,
                    "droplet_initial_diameter_mm": 2.5,
                },
                "top_k": 3,
            },
            ["MODEL:ridge_phys8", "TBL:PSI-69:"],
        ),
        (
            "flex_meth_he_explain",
            {
                "query": "Explain why Helium-diluted Methanol predictions here have higher burning rate estimates and why raw-6 Shapley bars are disabled.",
                "scope": "flex_prediction",
                "flex_condition": {
                    "fuel": "Methanol",
                    "o2_mol_frac": 0.21,
                    "co2_mol_frac": 0.0,
                    "he_mol_frac": 0.39,
                    "pressure_atm": 1.0,
                    "droplet_initial_diameter_mm": 2.5,
                },
                "top_k": 3,
            },
            ["MODEL:ridge_phys8", "TBL:PSI-69:"],
        ),
        (
            "flex_air_3atm_ood_explain",
            {
                "query": "Explain why Heptane Air at 3 atm returns NOT_SUPPORTED instead of emitting a burning-rate prediction.",
                "scope": "flex_prediction",
                "flex_condition": {
                    "fuel": "Heptane",
                    "o2_mol_frac": 0.21,
                    "co2_mol_frac": 0.0,
                    "he_mol_frac": 0.0,
                    "pressure_atm": 3.0,
                    "droplet_initial_diameter_mm": 2.5,
                },
                "top_k": 3,
            },
            ["MODEL:ridge_phys8"],
        ),
    ]

    results = []
    for name, payload, required_prefixes in cases:
        ans = svc.answer(payload)
        data = ans["data"]
        cits = [s["citation_id"] for s in data.get("sources", [])]
        matched_prefixes = all(any(c.startswith(pref) for c in cits) for pref in required_prefixes)
        results.append(
            {
                "case": name,
                "status": ans["status"],
                "answer_mode": data.get("answer_mode"),
                "llm_used": data.get("llm_used"),
                "summary": data.get("summary", "")[:260],
                "finding_count": len(data.get("findings", [])),
                "required_citations_ok": matched_prefixes,
            }
        )

    blocked = bool(bounded and bounded.blocked_error)
    return {
        "openrouter_configured": base_adapter is not None,
        "model": env_status.get("model"),
        "calls_attempted": bounded.calls_attempted if bounded else 0,
        "upstream_blocked": blocked,
        "blocked_reason": bounded.blocked_error if bounded else ("OpenRouter disabled" if base_adapter is None else None),
        "results": results,
    }


if __name__ == "__main__":
    out = run_eval()
    print(json.dumps(out, indent=2, ensure_ascii=False))
