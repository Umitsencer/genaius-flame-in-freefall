"""Deterministic unit tests for Görev 051 numerical audit & failure taxonomy."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from genaius.answering import GroundedLLMAdapter, generate_grounded_answer
from genaius.numerical_audit import (
    FAILURE_INPUT_BUDGET,
    FAILURE_LLM_QUOTA,
    FAILURE_LLM_UNAVAILABLE,
    FAILURE_NONE,
    FAILURE_NUMERICAL_VALIDATION,
    FAILURE_OUTPUT_VALIDATION,
    NumericalAuditError,
    audit_grounded_answer_numbers,
    extract_bundle_facts,
)
from genaius.openrouter import OpenRouterHTTPError
from genaius.service import EvidenceRequest, EvidenceService


class _FakeAdapter(GroundedLLMAdapter):
    def __init__(self, response=None, exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc

    def generate(self, bounded_input):
        if self.exc is not None:
            raise self.exc
        return self.response


class NumericalAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from genaius.app_service import AppService

        cls.app = AppService(ROOT)
        cls.core_svc = EvidenceService(records=cls.app.records, bm25_index=cls.app.index)

    def _saffire_bundle(self, query: str = "all SAFFIRE IV V VI gas calorimetry"):
        return self.app._build_evidence_bundle({"query": query, "scope": "saffire_case", "top_k": 3})[0]

    def _flex_pred_bundle(self):
        return self.app._build_evidence_bundle(
            {
                "query": "Explain Methanol 21% O2 FLEX model prediction",
                "scope": "flex_prediction",
                "flex_condition": {
                    "fuel": "Methanol",
                    "o2_mol_frac": 0.21,
                    "co2_mol_frac": 0.0,
                    "he_mol_frac": 0.0,
                    "pressure_atm": 1.0,
                    "droplet_initial_diameter_mm": 2.5,
                },
            }
        )[0]

    def test_saffire_pass_precision_and_derived_344s(self) -> None:
        bundle = self._saffire_bundle()
        facts, meta = extract_bundle_facts(bundle)
        self.assertIn("V-3", meta["unreported_gas_tests"])
        self.assertIn("V-4", meta["unreported_gas_tests"])
        self.assertTrue(any(f.value == 344.0 and f.origin_type == "derived" for f in facts))

        # VI-3 reports 8539 ppm CO2 at 54.6 kPa ambient pressure + derived 344 s
        report = audit_grounded_answer_numbers(
            summary="In SAFFIRE VI-3, elapsed ignition-to-threshold time is derived as 344 s (981 - 637 s).",
            findings=[
                {
                    "text": "VI-3 compartment post-fire delta CO2 was 8539 ppm at 54.6 kPa cabin pressure in Table 2 [CASE-TBL:VI-3].",
                    "citation_ids": ["CASE-TBL:VI-3"],
                }
            ],
            bundle=bundle,
            facts=facts,
            metadata=meta,
        )
        self.assertEqual(report.status, "passed")
        self.assertGreaterEqual(len(report.matched_fact_ids), 2)

    def test_rejects_out_of_precision_value(self) -> None:
        bundle = self._saffire_bundle()
        with self.assertRaises(NumericalAuditError):
            # 54.6 kPa misreported as 54.8 kPa is outside 0.5 * 10^-1 = 0.05 tolerance
            audit_grounded_answer_numbers(
                summary="VI-3 ambient pressure was 54.8 kPa.",
                findings=[],
                bundle=bundle,
            )

    def test_rejects_wrong_unit_and_wrong_derived_subtraction(self) -> None:
        bundle = self._saffire_bundle()
        with self.assertRaises(NumericalAuditError) as ctx_u:
            # 54.6 is kPa in VI-3, NOT atm!
            audit_grounded_answer_numbers(
                summary="Cabin ambient pressure was 54.6 atm.",
                findings=[],
                bundle=bundle,
            )
        self.assertIn("Unit mismatch", str(ctx_u.exception))

        with self.assertRaises(NumericalAuditError):
            # Wrong subtraction 350 s instead of 344 s
            audit_grounded_answer_numbers(
                summary="Derived VI-3 elapsed time was 350 s.",
                findings=[],
                bundle=bundle,
            )

    def test_rejects_test_attribution_swap_and_zero_coercion(self) -> None:
        bundle = self._saffire_bundle()
        # V-2 reported delta CO = 83 ppm, NOT VI-3's 308 ppm -> attributing 83 ppm solely to VI-3 fails!
        with self.assertRaises(NumericalAuditError) as ctx_tid:
            audit_grounded_answer_numbers(
                summary="In VI-3, post-fire CO rose by 83 ppm.",
                findings=[],
                bundle=bundle,
            )
        self.assertIn("Test attribution mismatch", str(ctx_tid.exception))

        # Unreported V-3/V-4 must never be coerced to 0 ppm
        with self.assertRaises(NumericalAuditError) as ctx_zero:
            audit_grounded_answer_numbers(
                summary="In V-3, Table 2 CO2 increase was 0 ppm.",
                findings=[],
                bundle=bundle,
            )
        self.assertIn("Coerces unreported", str(ctx_zero.exception))

    def test_rejects_delta_co2_exposure_conflation(self) -> None:
        bundle = self._saffire_bundle()
        with self.assertRaises(NumericalAuditError):
            audit_grounded_answer_numbers(
                summary="VI-3 compartment delta CO2 of 1639 ppm proves a crew exposure limit ruling.",
                findings=[],
                bundle=bundle,
            )

    def test_rejects_initial_final_diameter_swap_on_core_flex(self) -> None:
        # PSI-69 run with distinct initial diameter and extinction diameter
        bundle = self.core_svc.query(
            EvidenceRequest(query="Heptane droplet burning rate", investigation_id="PSI-69", fuel="Heptane", top_k=3)
        )
        # Find a run in bundle where initial diameter != final extinction diameter
        rec = next(
            r for r in bundle.table_result.records
            if r.measurements.get("droplet_initial_diameter_mm")
            and r.measurements.get("visible_flame_extinction_diameter_mm")
            and r.measurements["droplet_initial_diameter_mm"].normalized_value is not None
            and r.measurements["visible_flame_extinction_diameter_mm"].normalized_value is not None
            and abs(
                r.measurements["droplet_initial_diameter_mm"].normalized_value
                - r.measurements["visible_flame_extinction_diameter_mm"].normalized_value
            ) > 0.25
        )
        # Make sure extinction value doesn't happen to match another run's initial diameter in this tiny slice by testing with a 1-record slice
        one_svc = EvidenceService(records=(rec,), bm25_index=None)
        one_bundle = one_svc.query(EvidenceRequest(query="Heptane droplet", investigation_id="PSI-69", fuel="Heptane"))
        d0 = rec.measurements["droplet_initial_diameter_mm"].normalized_value
        d_ext = rec.measurements["visible_flame_extinction_diameter_mm"].normalized_value
        with self.assertRaises(NumericalAuditError) as ctx_swap:
            audit_grounded_answer_numbers(
                summary=f"Test {rec.record_pk} had an initial droplet diameter of {d_ext:.2f} mm.",
                findings=[],
                bundle=one_bundle,
            )
        self.assertIn("Initial/final diameter swap", str(ctx_swap.exception))
        # Correct pairing passes!
        ok_rep = audit_grounded_answer_numbers(
            summary=f"Test {rec.record_pk} started at initial diameter {d0:.2f} mm.",
            findings=[],
            bundle=one_bundle,
        )
        self.assertEqual(ok_rep.status, "passed")

    def test_flex_model_distinction_and_wrong_fraction_denominator(self) -> None:
        bundle = self._flex_pred_bundle()
        with self.assertRaises(NumericalAuditError):
            audit_grounded_answer_numbers(
                summary="The ridge_phys8 output was measured by NASA as an experimental test value.",
                findings=[],
                bundle=bundle,
            )
        with self.assertRaises(NumericalAuditError):
            audit_grounded_answer_numbers(
                summary="False positives occurred in 33/999 runs.",
                findings=[],
                bundle=bundle,
            )

    def test_failure_taxonomy_on_generate_grounded_answer(self) -> None:
        bundle = self._saffire_bundle()
        cited = next(c.citation_id for c in bundle.citations if c.citation_id.startswith("CASE-TBL:"))

        # 1. Numerical audit failure -> fallback without silent edit
        num_fail = generate_grounded_answer(
            bundle,
            llm_adapter=_FakeAdapter(
                response=json.dumps(
                    {
                        "summary": "VI-3 elapsed time was 999.9 s.",
                        "findings": [{"text": "Cited claim [CASE-TBL:VI-3].", "citation_ids": [cited]}],
                        "limitations": [],
                    }
                )
            ),
        )
        self.assertEqual(num_fail.answer_mode, "deterministic_fallback")
        self.assertEqual(num_fail.failure_reason, FAILURE_NUMERICAL_VALIDATION)
        self.assertEqual(num_fail.numerical_audit["status"], "failed_fallback")
        self.assertNotIn("999.9", num_fail.summary)

        # 2. HTTP 429 quota exceeded -> LLM_QUOTA_EXCEEDED
        quota_fail = generate_grounded_answer(
            bundle,
            llm_adapter=_FakeAdapter(exc=OpenRouterHTTPError(429, "Rate limit exceeded")),
        )
        self.assertEqual(quota_fail.answer_mode, "deterministic_fallback")
        self.assertEqual(quota_fail.failure_reason, FAILURE_LLM_QUOTA)

        # 3. Output validation failed -> OUTPUT_VALIDATION_FAILED
        out_fail = generate_grounded_answer(bundle, llm_adapter=_FakeAdapter(response="{not json"))
        self.assertEqual(out_fail.failure_reason, FAILURE_OUTPUT_VALIDATION)

        # 4. Input budget exceeded -> INPUT_BUDGET_EXCEEDED
        from genaius.answering import AdapterInputBudgetError

        with mock.patch(
            "genaius.answering.pipeline.build_bounded_adapter_input",
            side_effect=AdapterInputBudgetError("Too big"),
        ):
            budget_fail = generate_grounded_answer(bundle, llm_adapter=_FakeAdapter(response="{}"))
        self.assertEqual(budget_fail.failure_reason, FAILURE_INPUT_BUDGET)

        # 5. Generic error -> LLM_UNAVAILABLE
        unavail_fail = generate_grounded_answer(bundle, llm_adapter=_FakeAdapter(exc=RuntimeError("network down")))
        self.assertEqual(unavail_fail.failure_reason, FAILURE_LLM_UNAVAILABLE)

        # 6. Clean pass -> FAILURE_NONE
        clean_ok = generate_grounded_answer(
            bundle,
            llm_adapter=_FakeAdapter(
                response=json.dumps(
                    {
                        "summary": "SAFFIRE VI-3 elapsed time from ignition to alarm threshold was 344 s.",
                        "findings": [
                            {
                                "text": f"VI-3 CO2 increase was 8539 ppm ({cited}).",
                                "citation_ids": [cited],
                            }
                        ],
                        "limitations": ["No crew toxicity ruling."],
                    }
                )
            ),
        )
        self.assertEqual(clean_ok.answer_mode, "llm")
        self.assertEqual(clean_ok.failure_reason, FAILURE_NONE)
        self.assertEqual(clean_ok.numerical_audit["status"], "passed")

    def test_valid_comma_numbers_standards_and_percent_units_pass(self) -> None:
        # 1. SAFFIRE valid answer with comma-formatted ppm, NASA-STD-3001, JSC 20584, 3/8g
        s_bundle = self._saffire_bundle()
        s_rep = audit_grounded_answer_numbers(
            summary="SAFFIRE VI-3 at 54.6 kPa released 8,539 ppm CO2; NASA-STD-3001 (3 mmHg CO2) and JSC 20584 thresholds provide context only (not 3/8g or crew safety).",
            findings=[{"text": "Ignition at 637 s and alarm threshold at 981 s give derived 344 s.", "citation_ids": ["CASE-TBL:VI-3"]}],
            bundle=s_bundle,
        )
        self.assertEqual(s_rep.status, "passed")

        # 2. Core PSI-25 vol% / PSI-69 mol% unit wording without false rejection
        core_b, _, _ = self.app._build_evidence_bundle(
            {
                "query": "PSI-25 initial O2 vol%",
                "investigation_id": "PSI-25",
                "numeric_filters": [
                    {"field_name": "initial_o2_vol_pct", "unit": "% vol", "min_value": 10.0, "max_value": 30.0}
                ],
                "top_k": 3,
            }
        )
        self.assertIsNotNone(core_b.table_result)
        rec = core_b.table_result.records[0]
        o2_pct = rec.measurements["initial_o2_vol_pct"].normalized_value
        c_rep = audit_grounded_answer_numbers(
            summary=f"PSI-25 run {rec.record_pk} tested at {o2_pct:.1f} vol% initial O2.",
            findings=[],
            bundle=core_b,
        )
        self.assertEqual(c_rep.status, "passed")

        # 3. FLEX predictor non-extinction FP rate (taken from the active model's own CV metrics) passes
        f_bundle = self._flex_pred_bundle()
        from genaius.flex_predictor import load_flex_predictor_bundle
        cm = load_flex_predictor_bundle(self.app.root)["classification_model"]["cv_group_atm_p"]
        fp, neg = cm["confusion_matrix"]["fp"], cm["negative_non_extinction"]
        f_rep = audit_grounded_answer_numbers(
            summary=f"logit_phys10 had {fp}/{neg} ({100 * fp / neg:.1f}%) false positives across Non-Extinction runs.",
            findings=[],
            bundle=f_bundle,
        )
        self.assertEqual(f_rep.status, "passed")

        # 4. Applied numeric filter threshold (e.g. >= 2200 mmHg) does not false-reject
        flt_b, _, _ = self.app._build_evidence_bundle(
            {
                "query": "FLEX tests at pressure >= 2200 mmHg",
                "investigation_id": "PSI-69",
                "numeric_filters": [{"field_name": "ambient_pressure_kpa", "unit": "mmHg", "min_value": 2200}],
                "summarize_field_name": "burn_time_s",
                "summarize_unit": "s",
            }
        )
        flt_rep = audit_grounded_answer_numbers(
            summary="Across 3 PSI-69 FLEX runs matching ambient pressure >= 2200 mmHg, mean burn time is 15.05 s.",
            findings=[],
            bundle=flt_b,
        )
        self.assertEqual(flt_rep.status, "passed")


if __name__ == "__main__":
    unittest.main()
