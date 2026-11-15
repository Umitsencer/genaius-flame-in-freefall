"""Paket D: Tests for the unified table + BM25 evidence service and abstention gate."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from genaius.data.contracts import (
    DATASET_SPECS,
    ExperimentRecord,
    POSITION_DEFINITION,
    SourceLocation,
    TypedMeasurement,
)
from genaius.data.loader import parse_measurement_value
from genaius.data.query import COMPARISON_BOUNDARY_NOTE, NumericRangeFilter
from genaius.retrieval.bm25 import BM25_SCORE_DISCLAIMER, build_bm25_index
from genaius.service import (
    SERVICE_BOUNDARY_DISCLAIMER,
    SERVICE_MODE_DETERMINISTIC,
    EvidenceRequest,
    EvidenceService,
    EvidenceServiceError,
    build_evidence_bundle,
    evaluate_abstention_gate,
    load_processed_chunks,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_synthetic_record(
    *,
    investigation_id: str,
    test_id: str,
    csv_index: int,
    fuel_raw: str,
    raw_values: dict[str, str],
    sample_id: str | None = None,
    flex_identifier: str | None = None,
    test_end: str | None = None,
) -> ExperimentRecord:
    spec = DATASET_SPECS[investigation_id]
    contracts = {fc.field_name: fc for fc in spec.field_contracts}
    measurements: dict[str, TypedMeasurement] = {}
    for fname, contract in contracts.items():
        cell = raw_values.get(fname, "")
        measurements[fname] = parse_measurement_value(cell, contract)
    norm_fields: dict[str, object] = {
        "fuel_raw": fuel_raw,
        "fuel_norm": " ".join(fuel_raw.split()),
    }
    if test_end is not None:
        norm_fields["test_end"] = test_end.strip()
    return ExperimentRecord(
        record_pk=f"{investigation_id}:{test_id}",
        investigation_id=investigation_id,
        test_id=test_id,
        sample_id=sample_id,
        flex_identifier=flex_identifier,
        source=SourceLocation(
            source_relpath=spec.relative_path,
            source_sha256="b" * 64,
            encoding=spec.encoding,
            csv_record_index=csv_index,
            physical_line_start=csv_index + 1,
            physical_line_end=csv_index + 1,
            position_definition=POSITION_DEFINITION,
        ),
        raw_fields={"Fuel": fuel_raw, **raw_values},
        normalized_fields=norm_fields,
        measurements=measurements,
        quality_flags=(),
    )


class AbstentionAndSafetyGateTests(unittest.TestCase):
    """Verify V10, V11, V12, and boundary abstention rules without false positives."""

    def test_v10_cool_flame_inference_from_d_ext_is_rejected(self) -> None:
        for query_text in (
            "d_ext < 1 mm olanları soğuk alev diye sınıfla",
            "Classify droplets with visible flame extinction diameter < 0.5 mm as cool flames",
            "Classify these tests as cool flames",
        ):
            with self.subTest(query=query_text):
                decision = evaluate_abstention_gate(query_text)
                self.assertTrue(decision.abstained)
                self.assertEqual(decision.reason_code, "V10_COOL_FLAME_INFERENCE")
                self.assertEqual(decision.triggered_rule, "V10")

    def test_v10_does_not_reject_legitimate_report_questions_about_cool_flames(self) -> None:
        for query_text in (
            "How does FLEX identify cool flames in NASA TP?",
            "Where are cool flames discussed in NASA/TP-2015-216046?",
            "Soğuk alevler raporda hangi bölümde tanımlanıyor?",
        ):
            with self.subTest(query=query_text):
                decision = evaluate_abstention_gate(query_text)
                self.assertFalse(decision.abstained)

    def test_v11_co_toxicity_score_is_rejected(self) -> None:
        for query_text in (
            "PSI-25 CO değerlerinden mürettebat toksisite skoru ver",
            "Calculate crew toxicity score from CSA-CP CO ppm",
            "Estimate crew health risk from CO ppm readings",
        ):
            with self.subTest(query=query_text):
                decision = evaluate_abstention_gate(query_text)
                self.assertTrue(decision.abstained)
                self.assertEqual(decision.reason_code, "V11_CO_TOXICITY_SCORE")
                self.assertEqual(decision.triggered_rule, "V11")

    def test_v12_out_of_scope_studies_are_rejected(self) -> None:
        for query_text in (
            "SAFFIRE-II veya SAME verilerini getir ve kıyasla",
            "PSI-101 SAME-R duman testlerini listele",
            "PSI-26 BASS-1 deneyini karşılaştır",
            "ACME ve SPICE alev deneylerini özetle",
            "Show CFI droplet tests",
            "Compare SLICE and DAFT",
            "Check SoFIE and FLEX-2J",
            "Inspect PSI-181 data",
        ):
            with self.subTest(query=query_text):
                decision = evaluate_abstention_gate(query_text)
                self.assertTrue(decision.abstained)
                self.assertEqual(decision.reason_code, "V12_OUT_OF_SCOPE_STUDY")
                self.assertEqual(decision.triggered_rule, "V12")

        param_decision = evaluate_abstention_gate("Nomex testleri", investigation_id="PSI-99")
        self.assertTrue(param_decision.abstained)
        self.assertEqual(param_decision.reason_code, "V12_OUT_OF_SCOPE_STUDY")

        cfi_decision = evaluate_abstention_gate("Show tests", investigation_id="PSI-39")
        self.assertTrue(cfi_decision.abstained)
        self.assertEqual(cfi_decision.reason_code, "V12_OUT_OF_SCOPE_STUDY")

        for bad_inv in ("", "   ", "ABC", "PSI-x", "PSI-0", "psi-39", " PSI-69 "):
            with self.subTest(bad_investigation_id=bad_inv):
                with self.assertRaises(EvidenceServiceError):
                    evaluate_abstention_gate("Show tests", investigation_id=bad_inv)

        pk_decision = evaluate_abstention_gate(None, compare_record_pks=("PSI-39:1206", "PSI-69:10"))
        self.assertTrue(pk_decision.abstained)
        self.assertEqual(pk_decision.reason_code, "V12_OUT_OF_SCOPE_STUDY")

    def test_risk_score_and_partial_gravity_extrapolation_are_rejected(self) -> None:
        for query_text in (
            "Malzemeler için birleşik yangın risk skoru hesapla",
            "Calculate a unified fire risk score for habitats",
            "Produce a material safety ranking across PSI-25 and PSI-69",
            "ISS verilerini Ay habitatı 1/6g ve Mars 3/8g koşullarına uyarla",
        ):
            with self.subTest(query=query_text):
                decision = evaluate_abstention_gate(query_text)
                self.assertTrue(decision.abstained)
                self.assertEqual(decision.reason_code, "UNSUPPORTED_RISK_OR_GRAVITY_EXTRAPOLATION")


class EvidenceServiceIntegrationTests(unittest.TestCase):
    """Verify combined table + BM25 evidence bundling, contracts, and edge cases."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.chunks = load_processed_chunks(REPO_ROOT)
        cls.bm25_index = build_bm25_index(cls.chunks)
        cls.records = (
            _make_synthetic_record(
                investigation_id="PSI-25",
                test_id="F1",
                csv_index=23,
                fuel_raw="Nomex",
                sample_id="101",
                raw_values={
                    "flow_restrictor": "0",
                    "total_frames_shot": "500",
                    "initial_o2_vol_pct": "21.0",
                    "final_o2_vol_pct": "20.5",
                    "initial_co2_vol_pct": "0.4",
                    "final_co2_vol_pct": "0.6",
                    "initial_co_ppm": "0",
                    "final_co_ppm": "25",
                },
            ),
            _make_synthetic_record(
                investigation_id="PSI-25",
                test_id="F2",
                csv_index=24,
                fuel_raw="Nomex",
                sample_id="101",
                raw_values={
                    "flow_restrictor": "1",
                    "total_frames_shot": "450",
                    "initial_o2_vol_pct": "21.2",
                    "final_o2_vol_pct": "20.8",
                    "initial_co2_vol_pct": "0.4",
                    "final_co2_vol_pct": "0.5",
                    "initial_co_ppm": "-1",
                    "final_co_ppm": "OR",
                },
            ),
            _make_synthetic_record(
                investigation_id="PSI-69",
                test_id="10",
                csv_index=10,
                fuel_raw="Methanol",
                flex_identifier="193F001",
                test_end="Extinction",
                raw_values={
                    "ambient_pressure_kpa": "2319",
                    "initial_o2_flex_mol_pct": "0.21",
                    "initial_n2_flex_mol_pct": "0.09",
                    "initial_co2_flex_mol_pct": "0.70",
                    "initial_he_flex_mol_pct": "0.00",
                    "droplet_initial_diameter_mm": "3.86",
                    "visible_flame_extinction_diameter_mm": "2.15",
                    "burning_rate_mm2_s": "0.37",
                    "burn_time_s": "14.2",
                },
            ),
            _make_synthetic_record(
                investigation_id="PSI-69",
                test_id="11",
                csv_index=11,
                fuel_raw="Methanol",
                flex_identifier="193F002",
                test_end="Extinction",
                raw_values={
                    "ambient_pressure_kpa": "2318",
                    "initial_o2_flex_mol_pct": "0.21",
                    "initial_n2_flex_mol_pct": "0.09",
                    "initial_co2_flex_mol_pct": "0.70",
                    "initial_he_flex_mol_pct": "0.00",
                    "droplet_initial_diameter_mm": "3.03",
                    "visible_flame_extinction_diameter_mm": "1.90",
                    "burning_rate_mm2_s": "0.40",
                    "burn_time_s": "~9",
                },
            ),
            _make_synthetic_record(
                investigation_id="PSI-69",
                test_id="12",
                csv_index=12,
                fuel_raw="Heptane",
                flex_identifier="193F003",
                test_end="Disruption",
                raw_values={
                    "ambient_pressure_kpa": "2320",
                    "initial_o2_flex_mol_pct": "0.21",
                    "initial_n2_flex_mol_pct": "0.09",
                    "initial_co2_flex_mol_pct": "0.70",
                    "initial_he_flex_mol_pct": "0.00",
                    "droplet_initial_diameter_mm": "2.74",
                    "visible_flame_extinction_diameter_mm": "–",
                    "burning_rate_mm2_s": "",
                    "burn_time_s": "",
                },
            ),
        )
        cls.service = EvidenceService(records=cls.records, bm25_index=cls.bm25_index)

    def test_processed_chunks_count_and_manifest_integrity(self) -> None:
        self.assertEqual(len(self.chunks), 503)
        self.assertEqual({c.investigation_id for c in self.chunks}, {"PSI-25", "PSI-69"})

        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp) / "data" / "processed"
            proc.mkdir(parents=True)
            (proc / "psi_document_chunks.json").write_text("{bad json", encoding="utf-8")
            with self.assertRaises(EvidenceServiceError):
                load_processed_chunks(tmp)

    def test_combined_table_filter_summary_comparison_and_bm25_v1_v4_v8(self) -> None:
        req = EvidenceRequest(
            query="PSI-69 Burning rate unit definition",
            numeric_filters=(
                NumericRangeFilter(
                    field_name="ambient_pressure_kpa",
                    unit="mmHg",
                    min_value=2200.0,
                ),
            ),
            summarize_field_name="burning_rate_mm2_s",
            summarize_unit="mm²/s",
            compare_record_pks=("PSI-69:10", "PSI-69:11", "PSI-69:12"),
            top_k=3,
        )
        bundle = self.service.query(req)

        self.assertFalse(bundle.abstention.abstained)
        self.assertEqual(bundle.mode, SERVICE_MODE_DETERMINISTIC)
        self.assertEqual(bundle.resolved_investigation_id, "PSI-69")

        assert bundle.table_result is not None
        self.assertEqual(bundle.table_result.total_runs, 3)
        self.assertEqual(bundle.table_result.unique_flex_identifier_count, 3)

        assert bundle.field_summary is not None
        self.assertEqual(bundle.field_summary.unit, "mm²/s")
        self.assertEqual(bundle.field_summary.used_measured_count, 2)
        self.assertEqual(bundle.field_summary.excluded_by_status.get("missing"), 1)
        self.assertAlmostEqual(bundle.field_summary.mean_value or 0.0, 0.385, places=6)

        assert bundle.comparison_result is not None
        self.assertEqual(len(bundle.comparison_result.rows), 3)

        assert bundle.document_result is not None
        self.assertGreater(bundle.document_result.total_hits_returned, 0)
        for hit in bundle.document_result.hits:
            self.assertEqual(hit.investigation_id, "PSI-69")
            self.assertEqual(hit.document_id, "FLEX_TP_2015")

        source_types = {c.source_type for c in bundle.citations}
        self.assertEqual(source_types, {"table_row", "document_chunk"})
        self.assertIn("TBL:PSI-69:10", [c.citation_id for c in bundle.citations])

        self.assertIn(SERVICE_BOUNDARY_DISCLAIMER, bundle.disclaimers)
        self.assertIn(COMPARISON_BOUNDARY_NOTE, bundle.disclaimers)
        self.assertIn(BM25_SCORE_DISCLAIMER, bundle.disclaimers)

        llm_payload = bundle.to_llm_payload()
        self.assertEqual(len(llm_payload["table_summary"]["matched_rows"]), 3)
        row_12 = next(r for r in llm_payload["table_summary"]["matched_rows"] if r["record_pk"] == "PSI-69:12")
        self.assertEqual(row_12["measurements"]["burning_rate_mm2_s"]["status"], "missing")

        serialized = json.dumps(bundle.to_dict(), ensure_ascii=False, allow_nan=False)
        llm_serialized = json.dumps(llm_payload, ensure_ascii=False, allow_nan=False)
        self.assertGreater(len(serialized), 100)
        self.assertGreater(len(llm_serialized), 100)

    def test_document_only_query_does_not_attach_spurious_table_rows(self) -> None:
        req = EvidenceRequest(
            query="What is the burning rate unit in PSI-69?",
            top_k=3,
        )
        bundle = self.service.query(req)
        self.assertFalse(bundle.abstention.abstained)
        self.assertEqual(bundle.resolved_investigation_id, "PSI-69")
        self.assertIsNone(bundle.table_result)
        assert bundle.document_result is not None
        self.assertGreater(bundle.document_result.total_hits_returned, 0)
        self.assertEqual([c for c in bundle.citations if c.source_type == "table_row"], [])
        self.assertGreater(sum(1 for c in bundle.citations if c.source_type == "document_chunk"), 0)

    def test_cross_study_compare_record_pks_allowed_and_preserves_units(self) -> None:
        req = EvidenceRequest(compare_record_pks=("PSI-25:F1", "PSI-69:10"))
        bundle = self.service.query(req)
        self.assertFalse(bundle.abstention.abstained)
        assert bundle.comparison_result is not None
        self.assertEqual(len(bundle.comparison_result.rows), 2)
        self.assertTrue(any("cross_study_units_preserved" in w for w in bundle.warnings))
        row_25 = next(r for r in bundle.comparison_result.rows if r["investigation_id"] == "PSI-25")
        self.assertEqual(row_25["measurements"]["burning_rate_mm2_s"]["status"], "not_applicable")

    def test_cross_layer_alignment_from_fuel_and_sample_counts_v2_v3_v6(self) -> None:
        req = EvidenceRequest(
            query="Final CO aralık dışı OR ne demek?",
            fuel="Nomex",
            use_bilingual_aliases=True,
            top_k=3,
        )
        bundle = self.service.query(req)
        self.assertFalse(bundle.abstention.abstained)
        self.assertEqual(bundle.resolved_investigation_id, "PSI-25")

        assert bundle.table_result is not None
        self.assertEqual(bundle.table_result.total_runs, 2)
        self.assertEqual(bundle.table_result.unique_sample_count, 1)

        assert bundle.document_result is not None
        self.assertGreater(bundle.document_result.total_hits_returned, 0)
        for hit in bundle.document_result.hits:
            self.assertEqual(hit.investigation_id, "PSI-25")

    def test_corpus_unavailable_still_serves_table_evidence(self) -> None:
        table_only = EvidenceService(records=self.records, bm25_index=None)
        bundle = table_only.query(EvidenceRequest(query="Nomex", fuel="Nomex"))
        self.assertFalse(bundle.abstention.abstained)
        assert bundle.table_result is not None
        self.assertEqual(bundle.table_result.total_runs, 2)
        self.assertIsNone(bundle.document_result)
        self.assertTrue(any(w.startswith("corpus_unavailable:") for w in bundle.warnings))

    def test_abstained_bundle_returns_no_speculative_results(self) -> None:
        req = EvidenceRequest(
            query="SAFFIRE-II ve SAME deneylerini getir ve kıyasla",
            fuel="Nomex",
        )
        bundle = self.service.query(req)
        self.assertTrue(bundle.abstention.abstained)
        self.assertEqual(bundle.abstention.reason_code, "V12_OUT_OF_SCOPE_STUDY")
        self.assertIsNone(bundle.table_result)
        self.assertIsNone(bundle.document_result)
        self.assertEqual(bundle.citations, ())

    def test_empty_evidence_triggers_no_matching_evidence_abstention(self) -> None:
        req = EvidenceRequest(
            query="xyzqwertynonexistenttoken12345",
            fuel="NonExistentFuel999",
        )
        bundle = self.service.query(req)
        self.assertTrue(bundle.abstention.abstained)
        self.assertEqual(bundle.abstention.reason_code, "NO_MATCHING_EVIDENCE")

    def test_conflicting_fields_and_invalid_bounds_raise_service_error(self) -> None:
        with self.assertRaises(EvidenceServiceError):
            build_evidence_bundle(
                EvidenceRequest(investigation_id="PSI-25", test_end="Extinction"),
                records=self.records,
                bm25_index=self.bm25_index,
            )
        with self.assertRaises(EvidenceServiceError):
            build_evidence_bundle(
                EvidenceRequest(query=None, top_k=0),
                records=self.records,
                bm25_index=self.bm25_index,
            )
        for bad_inv in ("", "   ", "ABC", "PSI-x", "PSI-0", "psi-25"):
            with self.subTest(bad_investigation_id=bad_inv):
                with self.assertRaises(EvidenceServiceError):
                    build_evidence_bundle(
                        EvidenceRequest(query="burning rate", investigation_id=bad_inv),
                        records=self.records,
                        bm25_index=self.bm25_index,
                    )

    def test_intent_routing_and_out_of_scope_vs_malformed_ids(self) -> None:
        # 1. query + supported investigation_id -> docs only, no table_result or table citations
        doc_bundle = self.service.query(
            EvidenceRequest(
                query="How does FLEX identify cool flames in NASA TP?",
                investigation_id="PSI-69",
                top_k=2,
            )
        )
        self.assertFalse(doc_bundle.abstention.abstained)
        self.assertEqual(doc_bundle.resolved_investigation_id, "PSI-69")
        self.assertIsNone(doc_bundle.table_result)
        assert doc_bundle.document_result is not None
        self.assertEqual(doc_bundle.document_result.total_hits_returned, 2)
        self.assertEqual([c for c in doc_bundle.citations if c.source_type == "table_row"], [])

        # 2. run_table_query=False suppresses table filtering even when value filters are given
        no_table_bundle = self.service.query(
            EvidenceRequest(
                query="burning rate",
                investigation_id="PSI-69",
                fuel="Methanol",
                run_table_query=False,
                top_k=2,
            )
        )
        self.assertFalse(no_table_bundle.abstention.abstained)
        self.assertIsNone(no_table_bundle.table_result)
        self.assertEqual([c for c in no_table_bundle.citations if c.source_type == "table_row"], [])

        # 3. query + investigation_id + explicit summarize_field_name keeps summary active without table dump
        summary_bundle = self.service.query(
            EvidenceRequest(
                query="burning rate",
                investigation_id="PSI-69",
                summarize_field_name="burning_rate_mm2_s",
                summarize_unit="mm²/s",
                top_k=2,
            )
        )
        self.assertFalse(summary_bundle.abstention.abstained)
        self.assertIsNone(summary_bundle.table_result)
        assert summary_bundle.field_summary is not None
        self.assertEqual(summary_bundle.field_summary.used_measured_count, 2)
        self.assertEqual([c for c in summary_bundle.citations if c.source_type == "table_row"], [])

        # 4. Out-of-scope canonical PSI-<pos_int> abstains cleanly under V12
        psi39_bundle = self.service.query(
            EvidenceRequest(query="Show droplet tests", investigation_id="PSI-39")
        )
        self.assertTrue(psi39_bundle.abstention.abstained)
        self.assertEqual(psi39_bundle.abstention.reason_code, "V12_OUT_OF_SCOPE_STUDY")
        self.assertEqual(psi39_bundle.citations, ())


class RealCoreEvidenceServiceTests(unittest.TestCase):
    """Integration tests against the real 403 CSV runs and 503 NASA report chunks."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.service = EvidenceService.from_repo(REPO_ROOT)

    def test_real_dataset_counts_and_high_pressure_flex_bundle(self) -> None:
        self.assertEqual(len(self.service.records), 403)
        assert self.service.bm25_index is not None
        self.assertEqual(len(self.service.bm25_index.chunks), 503)

        bundle = self.service.query(
            EvidenceRequest(
                query="PSI-69 burning rate high pressure",
                numeric_filters=(
                    NumericRangeFilter(field_name="ambient_pressure_kpa", unit="mmHg", min_value=2200.0),
                ),
                summarize_field_name="burning_rate_mm2_s",
                summarize_unit="mm²/s",
                compare_record_pks=("PSI-69:10", "PSI-69:11", "PSI-69:12"),
                top_k=3,
            )
        )
        self.assertFalse(bundle.abstention.abstained)
        assert bundle.table_result is not None
        self.assertEqual(bundle.table_result.total_runs, 3)
        assert bundle.field_summary is not None
        self.assertEqual(bundle.field_summary.used_measured_count, 2)
        self.assertEqual(bundle.field_summary.excluded_by_status["missing"], 1)
        assert bundle.document_result is not None
        self.assertEqual(bundle.document_result.total_hits_returned, 3)

    def test_real_document_query_never_dumps_274_rows_and_cross_study_compare_works(self) -> None:
        doc_bundle = self.service.query(EvidenceRequest(query="What is the burning rate unit in PSI-69?", top_k=3))
        self.assertIsNone(doc_bundle.table_result)
        self.assertEqual([c for c in doc_bundle.citations if c.source_type == "table_row"], [])

        scoped_doc_bundle = self.service.query(
            EvidenceRequest(
                query="How does FLEX identify cool flames in NASA TP?",
                investigation_id="PSI-69",
                top_k=2,
            )
        )
        self.assertFalse(scoped_doc_bundle.abstention.abstained)
        self.assertEqual(scoped_doc_bundle.resolved_investigation_id, "PSI-69")
        self.assertIsNone(scoped_doc_bundle.table_result)
        assert scoped_doc_bundle.document_result is not None
        self.assertEqual(scoped_doc_bundle.document_result.total_hits_returned, 2)
        self.assertEqual([c for c in scoped_doc_bundle.citations if c.source_type == "table_row"], [])

        table_only_bundle = self.service.query(EvidenceRequest(investigation_id="PSI-69"))
        self.assertFalse(table_only_bundle.abstention.abstained)
        assert table_only_bundle.table_result is not None
        self.assertEqual(table_only_bundle.table_result.total_runs, 274)
        self.assertIsNone(table_only_bundle.document_result)

        cross_bundle = self.service.query(EvidenceRequest(compare_record_pks=("PSI-25:B1", "PSI-69:10")))
        self.assertFalse(cross_bundle.abstention.abstained)
        assert cross_bundle.comparison_result is not None
        self.assertEqual(len(cross_bundle.comparison_result.rows), 2)


if __name__ == "__main__":
    unittest.main()
