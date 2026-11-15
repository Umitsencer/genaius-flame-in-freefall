"""Unit and grounded RAG tests for the standalone SAFFIRE IV–VI case study module."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import unittest

from genaius.answering import generate_grounded_answer
from genaius.saffire_case import (
    SAFFIRE_CASE_ID,
    SAFFIRE_CASE_MODE,
    VALID_TEST_IDS,
    build_saffire_case_evidence_bundle,
    build_saffire_case_schema,
    compute_po2_kpa,
    compute_vi3_threshold_delta_s,
    evaluate_case_abstention_gate,
    export_saffire_case,
    load_saffire_case_dataset,
    run_saffire_case_reference,
)
from genaius.retrieval.bm25 import build_bm25_index
from genaius.retrieval.documents import load_retrieval_corpus
from genaius.service import EvidenceRequest, build_evidence_bundle, load_core_datasets

ROOT = Path(__file__).resolve().parents[1]


class CaseFindingOrderTests(unittest.TestCase):
    def test_topic_order_preserves_every_finding_and_citation(self):
        from genaius.answering.deterministic import _lead_case_finding
        from genaius.answering.models import AnswerFinding

        conditions = AnswerFinding('Saffire VI-3 conditions: PMMA.', ('CASE-TBL:VI-3',))
        gases = AnswerFinding('VI-3 gas/calorimetry: ΔCO=308 ppm.', ('CASE-TBL:VI-3',))
        timing = AnswerFinding('Selected threshold crossed at 981 s.', ('CASE-DET:DET-A',))
        original = [conditions, gases, timing]
        for query, first in [('When was the threshold crossed?', timing),
                             ('Compare gas emissions', gases),
                             ('What pressure was used?', conditions)]:
            result = _lead_case_finding(query, original)
            self.assertIs(result[0], first)
            self.assertCountEqual(result, original)
        self.assertEqual(original, [conditions, gases, timing])


class _MockCaseAdapter:
    """Deterministic adapter returning strict cited JSON for any valid SAFFIRE case prompt."""

    class config:
        model = "nvidia/nemotron-3.5-super-vl:free"

    def generate(self, adapter_input) -> str:
        allowed = list(getattr(adapter_input, "allowed_citation_ids", ()))
        chosen = allowed[:2] if len(allowed) >= 2 else allowed
        findings = []
        if chosen:
            findings.append(
                {
                    "text": f"Grounded directly on SAFFIRE IV–VI case evidence ({', '.join(chosen)}).",
                    "citation_ids": chosen,
                }
            )
        return json.dumps(
            {
                "summary": f"Bounded case-study summary grounded in {', '.join(chosen)}.",
                "findings": findings,
                "limitations": [
                    "Derived metrics (pO2_kPa, 344 s delta) are tagged separately from raw NASA values.",
                    "Unreported V-3/V-4 gas/calorimetry cells remain null and are not extrapolated to human survival.",
                ],
            }
        )


class SaffireCaseModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = load_saffire_case_dataset(ROOT)
        cls.datasets, _ = load_core_datasets(ROOT)
        chunks, _ = load_retrieval_corpus(ROOT, strict=False)
        cls.doc_index = build_bm25_index(chunks)

    def test_selected_mass_threshold_is_not_ionization_calibration(self) -> None:
        reference = json.loads((ROOT / "data/processed/saffire_case_reference.json").read_text(encoding="utf-8"))
        detection = next(item for item in reference["detection_evidence"] if item["evidence_id"] == "DET-A")
        self.assertEqual(detection["reported_metrics"]["alarm_threshold_time_s"], 981.0)
        self.assertEqual(detection["reported_metrics"]["alarm_threshold_mg_m3"], 1.0)
        self.assertIn("ionization-detector voltage", detection["summary"])
        self.assertIn("not a demonstrated calibrated", detection["limitations"])
        source_text = next(item["source_text"] for item in reference["passages"] if item["chunk_id"] == "SC-NTRS20240002981-P5-ALARM")
        self.assertIn("not a verbatim quotation", source_text)
        self.assertNotIn("FFD ionization smoke detector reached threshold", source_text)

    def test_dataset_provenance_nulls_and_derived_math(self) -> None:
        self.assertEqual(tuple(self.dataset.records_by_id.keys()), VALID_TEST_IDS)
        self.assertEqual(len(self.dataset.source_sha256), 64)

        # Derived pO2 arithmetic
        self.assertAlmostEqual(compute_po2_kpa(86.4, 21.8), 18.84, places=2)
        self.assertAlmostEqual(compute_po2_kpa(71.3, 25.4), 18.11, places=2)
        self.assertIsNone(compute_po2_kpa(None, 21.0))

        # Derived VI-3 ignition-to-threshold delta (981 - 637 = 344 s)
        self.assertEqual(compute_vi3_threshold_delta_s(637, 981), 344.0)
        self.assertIsNone(compute_vi3_threshold_delta_s(637, None))

        # V-3 and V-4 must keep gas/calorimetry strictly None while keeping Table 1 conditions
        for tid, expected_p, expected_o2 in (("V-3", 71.3, 25.4), ("V-4", 72.6, 25.7)):
            rec = self.dataset.records_by_id[tid]
            self.assertFalse(rec["gas_calorimetry_reported"])
            self.assertEqual(rec["ambient_pressure_kpa"], expected_p)
            self.assertEqual(rec["oxygen_mol_percent"], expected_o2)
            for field in (
                "burn_duration_s",
                "o2_peak_heat_release_w",
                "o2_total_heat_release_kj",
                "fuel_avg_heat_release_w",
                "fuel_total_heat_release_kj",
                "max_temp_sfu_outlet_c",
                "max_temp_ffd_c",
                "co2_increase_ppm",
                "co2_partial_pressure_increase_mmhg",
                "co_increase_ppm",
            ):
                self.assertIsNone(rec[field], msg=f"{tid}.{field} must stay None, never coerced to 0")
            self.assertIsNone(rec["derived"]["threshold_comparisons"]["co_exceeds_24h_smac_100ppm"])

        # VI-3 verified metrics & flow transitions
        vi3 = self.dataset.records_by_id["VI-3"]
        self.assertEqual(vi3["co2_increase_ppm"], 8539.0)
        self.assertEqual(vi3["co_increase_ppm"], 308.0)
        self.assertAlmostEqual(vi3["co2_partial_pressure_increase_mmhg"], 3.51, places=2)
        self.assertTrue(vi3["derived"]["threshold_comparisons"]["co_exceeds_24h_smac_100ppm"])
        self.assertFalse(vi3["derived"]["threshold_comparisons"]["co_exceeds_1h_smac_425ppm"])
        self.assertTrue(vi3["derived"]["threshold_comparisons"]["co2_exceeds_1h_limit_3mmhg"])
        steps = [p.get("time_start_s") for p in vi3["flow_protocol"]]
        self.assertIn(1120.0, steps)
        self.assertIn(1420.0, steps)

        # VI-2 dual calorimetry agreement & unresolved paywall note
        vi2 = self.dataset.records_by_id["VI-2"]
        self.assertEqual(vi2["o2_peak_heat_release_w"], 3217)
        self.assertEqual(vi2["o2_total_heat_release_kj"], 580)
        self.assertEqual(vi2["fuel_avg_heat_release_w"], 3650)
        self.assertEqual(vi2["fuel_total_heat_release_kj"], 409)

        schema = build_saffire_case_schema(self.dataset)
        unresolved_ids = {u["id"] for u in schema["unresolved_items"]}
        self.assertIn("UNRES-FSJ-PAYWALL", unresolved_ids)
        src_ids = {s["source_id"] for s in schema["verified_sources"]}
        self.assertTrue({"NTRS-20240002981", "NTRS-20210011521", "NTRS-20220009167", "NIST-1335761", "LOCAL-SAME2-20130000422", "FSJ-2018-ABSTRACT"}.issubset(src_ids))

    def test_filter_and_export_preserve_nulls_and_boundaries(self) -> None:
        v5 = run_saffire_case_reference(self.dataset, flight="Saffire V")
        self.assertEqual(v5["status"], "OK")
        self.assertEqual([r["test_id"] for r in v5["records"]], ["V-2", "V-3", "V-4"])

        thick = run_saffire_case_reference(self.dataset, fuel_group="thick_pmma")
        self.assertEqual([r["test_id"] for r in thick["records"]], ["V-3", "V-4", "VI-3", "VI-4"])

        csv_out = export_saffire_case(self.dataset, fmt="csv")
        self.assertEqual(csv_out["record_count"], 7)
        lines = csv_out["content"].splitlines()
        self.assertTrue(any(line.startswith("# BOUNDARY:") for line in lines))
        data_lines = [line for line in lines if not line.startswith("#")]
        rows = list(csv.DictReader(io.StringIO("\n".join(data_lines))))
        v3_row = next(r for r in rows if r["test_id"] == "V-3")
        self.assertEqual(v3_row["co_increase_ppm"], "")
        self.assertEqual(v3_row["burn_duration_s"], "")
        self.assertEqual(v3_row["derived_po2_kpa"], "18.11")

        json_out = export_saffire_case(self.dataset, fmt="json", test_id="VI-3")
        parsed = json.loads(json_out["content"])
        self.assertEqual(parsed["total_matching_records"], 1)
        self.assertTrue(parsed["what_this_does_not_establish"])

    def test_abstention_gates_and_eight_sample_case_questions(self) -> None:
        # 1. Core scope stays isolated when scope='core' (default)
        core_req = EvidenceRequest(query="What did Saffire VI-3 do to cabin air?", scope="core")
        core_bundle = build_evidence_bundle(core_req, records=self.datasets, bm25_index=self.doc_index)
        self.assertTrue(core_bundle.abstention.abstained)
        self.assertEqual(core_bundle.abstention.reason_code, "V12_OUT_OF_SCOPE_STUDY")

        # 2. Case abstention gates fire on safety/cert/partial-g/pooling, NOT descriptive limits
        for unsafe_q in (
            "Is VI-3 safe for crew breathing?",
            "Certify cabin habitability after burning PMMA",
            "Predict Mars 3/8g fire gases from Saffire VI",
            "Can SAFFIRE IV-VI be pooled with PSI-25 403 runs?",
        ):
            self.assertTrue(evaluate_case_abstention_gate(unsafe_q).abstained, msg=f"Should abstain: {unsafe_q}")

        safe_comp = evaluate_case_abstention_gate(
            "How do VI-2 and VI-3 CO increases compare against NASA 24-h and 1-h SMAC limits?"
        )
        self.assertFalse(safe_comp.abstained)

        # 3. Verify all 8 expected sample questions work cleanly in scope='saffire_case'
        supported_questions = [
            "What happened in Saffire-VI test VI-3?",
            "Do thin textile fires and thick PMMA fires produce the same gases?",
            "Why are V-3 and V-4 missing gas and calorimetry values?",
            "How do the reported CO and CO2 increases compare to NASA reference limits?",
            "Do spacecraft smoke detectors see all particles equally?",
            "Why do VI-2 O2 calorimetry and fuel mass-loss calorimetry differ?",
        ]
        for q in supported_questions:
            req = EvidenceRequest(query=q, scope="saffire_case", top_k=4)
            bundle = build_saffire_case_evidence_bundle(req, dataset=self.dataset)
            self.assertEqual(bundle.mode, SAFFIRE_CASE_MODE)
            self.assertFalse(bundle.abstention.abstained, msg=f"Unexpected abstention on: {q}")
            self.assertEqual(bundle.resolved_investigation_id, SAFFIRE_CASE_ID)
            self.assertTrue(bundle.citations, msg=f"Missing citations on: {q}")

            # Deterministic fallback
            det = generate_grounded_answer(bundle, llm_adapter=None)
            self.assertEqual(det.answer_mode, "deterministic")
            self.assertFalse(det.llm_used)
            self.assertTrue(det.sources)
            self.assertTrue(any(s.source_url for s in det.sources))

            # Mocked adapter with CASE-TBL / CASE-DET / DOC citation validator
            llm_ans = generate_grounded_answer(bundle, llm_adapter=_MockCaseAdapter())
            self.assertEqual(llm_ans.answer_mode, "llm")
            self.assertTrue(llm_ans.llm_used)
            self.assertTrue(llm_ans.findings)

        # Question 7 & 8: abstained queries via full pipeline return status=ABSTAINED cleanly
        for blocked_q in (
            "Is VI-3 safe for crew survival without scrubbing?",
            "Can we extrapolate Saffire VI smoke detection to Lunar 1/6g habitats?",
        ):
            req = EvidenceRequest(query=blocked_q, scope="saffire_case")
            bundle = build_saffire_case_evidence_bundle(req, dataset=self.dataset)
            ans = generate_grounded_answer(bundle, llm_adapter=_MockCaseAdapter())
            self.assertEqual(ans.status, "ABSTAINED")
            self.assertFalse(ans.llm_used)


class SaffireCaseFocusTests(unittest.TestCase):
    def test_vi3_query_separates_indirect_detector_studies_unless_asked(self) -> None:
        from genaius.saffire_case import build_saffire_case_evidence_bundle, load_saffire_case_dataset
        from genaius.service import EvidenceRequest

        dataset = load_saffire_case_dataset()
        vi3_bundle = build_saffire_case_evidence_bundle(
            EvidenceRequest(query="What happened in Saffire VI-3?", scope="saffire_case"),
            dataset=dataset,
        )
        cp = vi3_bundle.case_payload or {}
        primary_det_ids = {d["evidence_id"] for d in cp.get("detection_evidence", [])}
        related_det_ids = {d["evidence_id"] for d in cp.get("related_research", [])}
        self.assertIn("DET-A", primary_det_ids)
        self.assertNotIn("DET-B", primary_det_ids)
        self.assertNotIn("DET-C", primary_det_ids)
        self.assertIn("DET-B", related_det_ids)
        self.assertIn("DET-C", related_det_ids)
        hit_ids = {h.chunk_id for h in (vi3_bundle.document_result.hits if vi3_bundle.document_result else ())}
        self.assertNotIn("SC-NTRS20210011521-V3-V4", hit_ids)
        self.assertNotIn("SC-NIST-1335761-SAME", hit_ids)
        self.assertNotIn("SC-NTRS20220009167-FORTENBERRY", hit_ids)

        comp_bundle = build_saffire_case_evidence_bundle(
            EvidenceRequest(
                query="Compare Saffire VI-3 smoke aerosol particle detectors with SAME",
                scope="saffire_case",
            ),
            dataset=dataset,
        )
        comp_det_ids = {d["evidence_id"] for d in (comp_bundle.case_payload or {}).get("detection_evidence", [])}
        self.assertIn("DET-B", comp_det_ids)
        self.assertIn("DET-C", comp_det_ids)


if __name__ == "__main__":
    unittest.main()
