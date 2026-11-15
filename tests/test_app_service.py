"""Gerçek çekirdek verilerle servis entegrasyon kontrolleri."""
import unittest
from pathlib import Path
from genaius.app_service import AppService

ROOT = Path(__file__).resolve().parents[1]


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = AppService(ROOT)

    def test_unrelated_question_never_uses_selected_flex_condition_or_llm(self):
        from unittest.mock import Mock
        adapter = Mock()
        adapter.generate.side_effect = AssertionError("Out-of-domain request reached LLM")
        svc = AppService(ROOT, answer_adapter=adapter)
        condition = {
            "fuel": "Methanol", "o2_mol_frac": 0.21, "co2_mol_frac": 0.0,
            "he_mol_frac": 0.0, "pressure_atm": 1.0, "droplet_initial_diameter_mm": 2.5,
        }
        for scope in ("auto", "core", "saffire_case", "flex_prediction"):
            for query in (
                "ford focus 1.6 tdsi triger kayışı değişimi", "When should I replace my timing belt?",
                "hatay usülü soslu dürüm tarifi", "How do I bake sourdough bread?",
                "Yarın Kırklareli hava durumu nasıl?", "What stocks should I buy?",
                "Bana bir aşk şiiri yaz", "Who won the football match?", "asdkjxyz",
            ):
                with self.subTest(scope=scope, query=query):
                    request = {"query": query, "scope": scope, "flex_condition": condition}
                    for handler in (svc.answer, svc.evidence):
                        result = handler(request)
                        self.assertEqual(result["status"], "ABSTAINED")
                        self.assertEqual(result["data"]["abstention"]["reason_code"], "OUT_OF_DOMAIN_QUERY")
                        self.assertEqual(result["data"]["coverage"]["status"], "no_match")
                        self.assertEqual(result["data"]["coverage"]["total_corpus_count"], 0)
                        if handler == svc.answer:
                            self.assertFalse(result["data"]["llm_used"])
                            self.assertEqual(result["data"]["sources"], [])
        adapter.generate.assert_not_called()

    def test_topic_gate_recognizes_research_and_only_bounded_followups(self):
        from genaius.scope_router import _question_has_domain_support
        from genaius.schemas.requests import EvidenceRequestIn
        for query in (
            "What was the highest oxygen level tested on solid materials?",
            "Compare PMMA film at 21% and 22.2% oxygen", "How much CO did Nomex produce?",
            "What happened in Saffire VI-3?", "Yanma hızını ve oksijen etkisini açıkla",
            "What is the ridge model estimate?", "How does smoke detection work?",
            "Hangi malzemeler var?", "CO ne kadar ölçüldü?", "Yanıcılık nasıl değişiyor?",
        ):
            self.assertTrue(_question_has_domain_support(EvidenceRequestIn(query=query)), query)
        for query in ("Explain these results", "What does this mean?", "Bu sonuçları açıkla", "Neden?"):
            self.assertFalse(_question_has_domain_support(EvidenceRequestIn(query=query)), query)
            self.assertTrue(_question_has_domain_support(EvidenceRequestIn(
                query=query, flex_condition={"fuel": "Methanol"},
            )), query)

    def test_schema_reports_real_counts_and_capabilities(self):
        result = self.service.schema()
        self.assertFalse(result["llm_enabled"])
        self.assertEqual({d["id"]: d["run_count"] for d in result["data"]["datasets"]},
                         {"PSI-25": 129, "PSI-69": 274})
        self.assertEqual(result["data"]["chunk_count"], 503)

    def test_filter_pressure_and_preserve_missing_burning_rate(self):
        s = self.service
        result = s.search({"investigation_id": "PSI-69", "numeric_filters": [
            {"field_name": "ambient_pressure_kpa", "unit": "mmHg", "min_value": 2200}]})
        self.assertEqual(result["data"]["total_runs"], 3)
        ids = [r["test_id"] for r in result["data"]["records"]]
        self.assertEqual(set(ids), {"10", "11", "12"})
        detail = s.detail({"record_pk": "PSI-69:12"})["data"]
        rate = detail["measurements"]["burning_rate_mm2_s"]
        self.assertEqual(rate["status"], "missing")
        self.assertIsNone(rate["normalized_value"])
        self.assertEqual(len(detail["source"]["source_sha256"]), 64)

    def test_reject_wrong_units_and_unknown_fields(self):
        with self.assertRaises(ValueError):
            self.service.search({"invented": True})
        with self.assertRaises(ValueError):
            self.service.search({"investigation_id": "PSI-69", "numeric_filters": [
                {"field_name": "ambient_pressure_kpa", "unit": "banana", "min_value": 1}]})
        with self.assertRaises(ValueError):
            self.service.search({"limit": True})

    def test_empty_is_not_zero_measurement_and_paging_is_explicit(self):
        result = self.service.search({"investigation_id": "PSI-69", "fuel": "synthetic_nonexistent_fuel"})
        self.assertEqual(result["status"], "NO_EVIDENCE")
        self.assertEqual(result["data"]["records"], [])
        page = self.service.search({"investigation_id": "PSI-69", "limit": 2, "offset": 2})["data"]
        self.assertEqual(page["total_runs"], 274)
        self.assertEqual(page["returned_count"], 2)

    def test_comparison_preserves_test_identity_and_boundary(self):
        result = self.service.compare({"record_pks": ["PSI-69:10", "PSI-69:12"]})["data"]
        self.assertEqual([r["test_id"] for r in result["details"]], ["10", "12"])
        self.assertIn("not a safety ranking", result["boundary_note"])
        with self.assertRaises(ValueError):
            self.service.compare({"record_pks": ["PSI-69:10", "PSI-69:10"]})

    def test_document_hits_have_traceable_locations_not_generated_answer(self):
        result = self.service.documents({"query": "burning rate", "investigation_id": "PSI-69"})
        self.assertFalse(result["llm_enabled"])
        self.assertEqual(result["status"], "OK")
        for hit in result["data"]["hits"]:
            self.assertEqual(hit["investigation_id"], "PSI-69")
            self.assertTrue(hit["source_url"].startswith("https://"))
            self.assertGreater(hit["pdf_page_start"], 0)
            self.assertTrue(hit["source_text"])

    def test_missing_corpus_keeps_table_search_available(self):
        old = self.service.index
        try:
            self.service.index = None
            self.assertEqual(self.service.documents({"query": "oxygen"})["status"], "CORPUS_UNAVAILABLE")
            self.assertEqual(self.service.search({"investigation_id": "PSI-25"})["data"]["total_runs"], 129)
        finally:
            self.service.index = old

    def test_unified_evidence_bundle_and_abstention(self):
        bundle = self.service.evidence({
            "query": "PSI-69 burning rate",
            "numeric_filters": [{"field_name": "ambient_pressure_kpa", "unit": "mmHg", "min_value": 2200}],
            "summarize_field_name": "burning_rate_mm2_s",
            "summarize_unit": "mm²/s",
            "compare_record_pks": ["PSI-69:10", "PSI-69:12"],
            "top_k": 3,
        })
        self.assertEqual(bundle["status"], "OK")
        self.assertFalse(bundle["llm_enabled"])
        self.assertEqual(bundle["data"]["mode"], "deterministic_fallback")
        self.assertEqual(bundle["data"]["table_result"]["total_runs"], 3)
        self.assertEqual(bundle["data"]["field_summary"]["excluded_by_status"]["missing"], 1)
        self.assertEqual(len(bundle["data"]["document_result"]["hits"]), 3)
        self.assertTrue(bundle["data"]["document_result"]["hits"][0]["source_url"].startswith("https://"))
        citation_types = {c["source_type"] for c in bundle["data"]["citations"]}
        self.assertEqual(citation_types, {"table_row", "document_chunk"})
        self.assertTrue(all(len(c["source_sha256"]) == 64 and c["locator_label"] for c in bundle["data"]["citations"]))

        abstained = self.service.evidence({"query": "Compare SAFFIRE-II and CFI experiments"})
        self.assertEqual(abstained["status"], "ABSTAINED")
        self.assertEqual(abstained["data"]["abstention"]["reason_code"], "V12_OUT_OF_SCOPE_STUDY")
        self.assertEqual(abstained["data"]["citations"], [])

    def test_evidence_doc_only_cool_flame_separation_and_abstention_gates(self):
        # Default run_table_query=True with query + investigation_id must NOT attach spurious table rows.
        doc_only = self.service.evidence({
            "query": "How does FLEX identify cool flames in NASA TP?",
            "investigation_id": "PSI-69",
            "top_k": 2,
        })
        self.assertEqual(doc_only["status"], "OK")
        self.assertFalse(doc_only["llm_enabled"])
        self.assertEqual(doc_only["data"]["resolved_investigation_id"], "PSI-69")
        self.assertIsNone(doc_only["data"]["table_result"])
        self.assertIsNone(doc_only["data"]["field_summary"])
        self.assertIsNone(doc_only["data"]["comparison_result"])
        self.assertEqual(len(doc_only["data"]["document_result"]["hits"]), 2)
        self.assertTrue(all(c["source_type"] == "document_chunk" for c in doc_only["data"]["citations"]))

        # No query + investigation_id preserves full table listing.
        table_only = self.service.evidence({"investigation_id": "PSI-69"})
        self.assertEqual(table_only["status"], "OK")
        self.assertEqual(table_only["data"]["table_result"]["total_runs"], 274)
        self.assertIsNone(table_only["data"]["document_result"])

        # Explicit run_table_query=False skips table filtering even with fuel provided.
        suppressed = self.service.evidence({
            "query": "burning rate",
            "investigation_id": "PSI-69",
            "fuel": "Methanol",
            "run_table_query": False,
            "top_k": 2,
        })
        self.assertEqual(suppressed["status"], "OK")
        self.assertIsNone(suppressed["data"]["table_result"])
        self.assertEqual(len(suppressed["data"]["document_result"]["hits"]), 2)

        # Canonical unsupported PSI-<positive_int> abstains cleanly under V12.
        psi39 = self.service.evidence({"query": "Show droplet tests", "investigation_id": "PSI-39"})
        self.assertEqual(psi39["status"], "ABSTAINED")
        self.assertEqual(psi39["data"]["abstention"]["reason_code"], "V12_OUT_OF_SCOPE_STUDY")
        self.assertEqual(psi39["data"]["citations"], [])

        v10 = self.service.evidence({
            "query": "Classify droplets with d_ext < 1 mm as cool flames",
            "investigation_id": "PSI-69",
        })
        self.assertEqual(v10["status"], "ABSTAINED")
        self.assertEqual(v10["data"]["abstention"]["reason_code"], "V10_COOL_FLAME_INFERENCE")
        self.assertEqual(v10["data"]["citations"], [])

        risk = self.service.evidence({"query": "Extrapolate ISS burning rate to Lunar gravity fire risk score"})
        self.assertEqual(risk["status"], "ABSTAINED")
        self.assertEqual(risk["data"]["abstention"]["reason_code"], "UNSUPPORTED_RISK_OR_GRAVITY_EXTRAPOLATION")
        self.assertEqual(risk["data"]["citations"], [])

        v11 = self.service.evidence({"query": "Calculate CO toxicity hazard score for cabin smoke"})
        self.assertEqual(v11["status"], "ABSTAINED")
        self.assertEqual(v11["data"]["abstention"]["reason_code"], "V11_CO_TOXICITY_SCORE")
        self.assertEqual(v11["data"]["citations"], [])

    def test_evidence_no_evidence_and_validation_errors(self):
        from genaius.service import EvidenceServiceError

        empty = self.service.evidence({
            # An explicit structured filter still has NO_EVIDENCE semantics;
            # unrelated free-text questions are now rejected before retrieval.
            "fuel": "NonExistentFuel999",
        })
        self.assertEqual(empty["status"], "NO_EVIDENCE")
        self.assertEqual(empty["data"]["abstention"]["reason_code"], "NO_MATCHING_EVIDENCE")
        self.assertEqual(empty["data"]["citations"], [])

        invalid_payloads = [
            {"query": "PSI-69", "unexpected_key": 1},
            {"summarize_field_name": "burning_rate_mm2_s"},
            {"query": "PSI-69", "top_k": 0},
            {"numeric_filters": [{"field_name": "no_such_field", "unit": "kPa"}]},
            {"investigation_id": "PSI-25", "test_end": "Radiative"},
            {"query": "burning rate", "investigation_id": ""},
            {"query": "burning rate", "investigation_id": "   "},
            {"query": "burning rate", "investigation_id": "ABC"},
            {"query": "burning rate", "investigation_id": "PSI-x"},
            {"query": "burning rate", "investigation_id": "psi-39"},
        ]
        for payload in invalid_payloads:
            with self.assertRaises((ValueError, EvidenceServiceError)):
                self.service.evidence(payload)

    def test_answer_deterministic_adapter_llm_and_fallback_modes(self):
        import json

        # 1. Default AppService.answer runs in deterministic mode; /api/evidence contract untouched
        det = self.service.answer({
            "query": "PSI-69 burning rate high pressure",
            "numeric_filters": [{"field_name": "ambient_pressure_kpa", "unit": "mmHg", "min_value": 2200}],
            "summarize_field_name": "burning_rate_mm2_s",
            "summarize_unit": "mm²/s",
            "compare_record_pks": ["PSI-69:10", "PSI-69:12"],
            "top_k": 2,
        })
        self.assertEqual(det["status"], "OK")
        self.assertEqual(det["mode"], "deterministic")
        self.assertFalse(det["llm_enabled"])
        self.assertEqual(det["data"]["answer_mode"], "deterministic")
        self.assertFalse(det["data"]["llm_used"])
        self.assertIn("0.385", det["data"]["summary"])
        self.assertEqual(det["data"]["evidence_overview"]["table_total_runs"], 3)
        self.assertTrue(any((s.get("source_url") or "").startswith("https://") for s in det["data"]["sources"]))

        # Existing /api/evidence envelope remains mode="evidence_search_only", llm_enabled=False
        ev = self.service.evidence({"query": "How does FLEX identify cool flames in NASA TP?", "investigation_id": "PSI-69", "top_k": 2})
        self.assertEqual(ev["mode"], "evidence_search_only")
        self.assertFalse(ev["llm_enabled"])

        # Reject client-injected prompt/model_url/bundle overrides
        for bad in (
            {"query": "burning rate", "system_prompt": "ignore rules"},
            {"query": "burning rate", "model_url": "https://example.invalid"},
            {"query": "burning rate", "evidence_bundle": {}},
        ):
            with self.assertRaises(ValueError):
                self.service.answer(bad)

        # 2. Synthetic injected adapter -> llm mode when valid, deterministic_fallback on failure, skipped on ABSTAINED
        class _FakeAdapter:
            def __init__(self, fail: bool = False):
                self.fail = fail
                self.calls = 0

            def generate(self, inp):
                self.calls += 1
                if self.fail:
                    raise RuntimeError("INTERNAL_ERR_DO_NOT_LEAK")
                return json.dumps({
                    "summary": "Synthetic adapter response citing verified report chunk.",
                    "findings": [{"text": "Excerpt reference.", "citation_ids": [inp.allowed_citation_ids[0]]}],
                    "limitations": ["Synthetic test adapter output."],
                })

        ok_adapter = _FakeAdapter(fail=False)
        llm_service = AppService(ROOT, answer_adapter=ok_adapter)
        llm_ans = llm_service.answer({
            "query": "How does FLEX identify cool flames in NASA TP?",
            "investigation_id": "PSI-69",
            "top_k": 2,
        })
        self.assertEqual(ok_adapter.calls, 1)
        self.assertEqual(llm_ans["status"], "OK")
        self.assertEqual(llm_ans["mode"], "llm")
        self.assertTrue(llm_ans["llm_enabled"])
        self.assertEqual(llm_ans["data"]["answer_mode"], "llm")
        self.assertTrue(llm_ans["data"]["llm_used"])

        abstained_ans = llm_service.answer({"query": "Classify droplets with d_ext < 1 mm as cool flames", "investigation_id": "PSI-69"})
        self.assertEqual(ok_adapter.calls, 1)  # never called when ABSTAINED
        self.assertEqual(abstained_ans["status"], "ABSTAINED")
        self.assertEqual(abstained_ans["mode"], "deterministic")
        self.assertFalse(abstained_ans["llm_enabled"])

        bad_adapter = _FakeAdapter(fail=True)
        fb_service = AppService(ROOT, answer_adapter=bad_adapter)
        fb_ans = fb_service.answer({
            "query": "How does FLEX identify cool flames in NASA TP?",
            "investigation_id": "PSI-69",
            "top_k": 2,
        })
        self.assertEqual(fb_ans["status"], "OK")
        self.assertEqual(fb_ans["mode"], "deterministic_fallback")
        self.assertFalse(fb_ans["llm_enabled"])
        self.assertEqual(fb_ans["data"]["answer_mode"], "deterministic_fallback")
        self.assertFalse(fb_ans["data"]["llm_used"])
        self.assertNotIn("INTERNAL_ERR_DO_NOT_LEAK", json.dumps(fb_ans))

    def test_catalog_endpoints_boundaries_and_unavailable_isolation(self):
        from genaius.catalog import CatalogLoadError

        # 1. Filters & full 24-study listing without query
        filters_res = self.service.catalog_filters()
        self.assertEqual(filters_res["status"], "OK")
        self.assertEqual(filters_res["mode"], "catalog_lookup_only")
        self.assertFalse(filters_res["llm_enabled"])
        self.assertEqual(filters_res["data"]["total_studies"], 24)
        self.assertEqual(filters_res["data"]["core_investigation_ids"], ["PSI-25", "PSI-69"])

        all_res = self.service.catalog_search({})
        self.assertEqual(all_res["status"], "OK")
        self.assertEqual(all_res["data"]["total_matches"], 24)
        self.assertEqual(len({h["psi_id"] for h in all_res["data"]["hits"]}), 24)

        # 2. Core filter returns strictly PSI-25 & PSI-69; PSI-69/FLEX preserves match reason + provenance
        core_res = self.service.catalog_search({"queryable_in_core": True})
        self.assertEqual({h["psi_id"] for h in core_res["data"]["hits"]}, {"PSI-25", "PSI-69"})

        flex_res = self.service.catalog_search({"query": "FLEX"})
        self.assertEqual(flex_res["data"]["hits"][0]["psi_id"], "PSI-69")
        self.assertIn("acronym", flex_res["data"]["hits"][0]["matched_fields"])
        self.assertTrue(flex_res["data"]["hits"][0]["ranking_reason"])
        self.assertTrue(flex_res["data"]["hits"][0]["entry"]["catalog_url"].startswith("https://"))
        self.assertTrue(flex_res["data"]["hits"][0]["entry"]["provenance"]["manifest_sha256"])

        # 3. CFI & SAME-R stay non-core while preserving discrepancies
        cfi_res = self.service.catalog_search({"query": "CFI"})
        cfi_hit = cfi_res["data"]["hits"][0]
        self.assertEqual(cfi_hit["psi_id"], "PSI-39")
        self.assertFalse(cfi_hit["entry"]["support"]["queryable_in_core"])
        self.assertEqual(cfi_hit["entry"]["support"]["support_tier"], "reviewed / descriptive extension proposed")
        self.assertTrue(cfi_hit["entry"]["source_discrepancies"])

        samer_res = self.service.catalog_search({"query": "SAME-R"})
        self.assertEqual(samer_res["data"]["hits"][0]["psi_id"], "PSI-101")
        self.assertFalse(samer_res["data"]["hits"][0]["entry"]["support"]["queryable_in_core"])

        # 4. NO_MATCH vs validation errors (explicit whitespace/empty query, unknown key, invalid bounds)
        no_match = self.service.catalog_search({"query": "nonexistent_warp_propulsion_xyz"})
        self.assertEqual(no_match["status"], "NO_MATCH")
        self.assertEqual(no_match["data"]["hits"], [])

        for bad in (
            {"query": ""},
            {"query": "   "},
            {"unknown_field": 1},
            {"queryable_in_core": "true"},
            {"top_k": 0},
            {"top_k": 51},
        ):
            with self.assertRaises(ValueError):
                self.service.catalog_search(bad)

        # 5. Failing catalog loader never blocks startup or core search/evidence/answer endpoints
        def _broken_loader(_root: Path):
            raise CatalogLoadError("SECRET_LOCAL_PATH C:/private/broken.json")

        degraded = AppService(ROOT, catalog_loader=_broken_loader)
        f_unavail = degraded.catalog_filters()
        s_unavail = degraded.catalog_search({"query": "FLEX"})
        self.assertEqual(f_unavail["status"], "CATALOG_UNAVAILABLE")
        self.assertEqual(s_unavail["status"], "CATALOG_UNAVAILABLE")
        self.assertEqual(f_unavail["mode"], "catalog_lookup_only")
        self.assertFalse(f_unavail["llm_enabled"])
        self.assertNotIn("SECRET_LOCAL_PATH", f_unavail["message"])
        self.assertNotIn("C:/private", s_unavail["message"])

        # Core endpoints keep working while catalog is unavailable
        self.assertEqual(degraded.search({"investigation_id": "PSI-25"})["data"]["total_runs"], 129)
        self.assertEqual(degraded.answer({"query": "burning rate", "investigation_id": "PSI-69", "top_k": 1})["status"], "OK")

    def test_analytics_and_export_service_contracts(self):
        import csv
        import io
        import json

        s = self.service
        res = s.analytics({
            "investigation_id": "PSI-69",
            "field_name": "burning_rate_mm2_s",
            "unit": "mm²/s",
            "numeric_filters": [{"field_name": "ambient_pressure_kpa", "unit": "mmHg", "min_value": 2200}],
        })
        self.assertEqual(res["status"], "OK")
        self.assertEqual(res["mode"], "descriptive_analytics_only")
        self.assertFalse(res["llm_enabled"])
        d = res["data"]
        self.assertEqual(d["total_runs"], 3)
        self.assertEqual(d["summary"]["used_measured_count"], 2)
        self.assertEqual(d["summary"]["mean_value"], 0.385)
        self.assertEqual(d["summary"]["median_value"], 0.385)
        self.assertEqual(d["charts"]["test_end_distribution"]["counts"], [
            {"label": "Extinction", "count": 2},
            {"label": "Disruption", "count": 1},
        ])

        csv_exp = s.export({
            "investigation_id": "PSI-69",
            "field_name": "burning_rate_mm2_s",
            "unit": "mm²/s",
            "numeric_filters": [{"field_name": "ambient_pressure_kpa", "unit": "mmHg", "min_value": 2200}],
            "format": "csv",
        })
        self.assertEqual(csv_exp["status"], "OK")
        self.assertEqual(csv_exp["data"]["total_runs"], 3)
        rows = list(csv.DictReader(io.StringIO(csv_exp["data"]["content"])))
        self.assertEqual([r["test_id"] for r in rows], ["10", "11", "12"])
        self.assertEqual(rows[2]["measurement_status"], "missing")

        json_exp = s.export({
            "investigation_id": "PSI-25",
            "field_name": "initial_co_ppm",
            "unit": "ppm",
            "format": "json",
        })
        self.assertEqual(json_exp["data"]["total_runs"], 129)
        self.assertEqual(len(json.loads(json_exp["data"]["content"])["records"]), 129)

        empty = s.analytics({
            "investigation_id": "PSI-69",
            "field_name": "burning_rate_mm2_s",
            "unit": "mm²/s",
            "fuel": "NoSuchFuel",
        })
        self.assertEqual(empty["status"], "NO_EVIDENCE")
        self.assertEqual(empty["data"]["total_runs"], 0)
        self.assertIsNone(empty["data"]["summary"]["mean_value"])
        self.assertIsNone(empty["data"]["summary"]["median_value"])

        # Reject invalid unit, missing field_name, or cross-study/catalog IDs
        with self.assertRaises(ValueError):
            s.analytics({"investigation_id": "PSI-39", "field_name": "burning_rate_mm2_s"})
        with self.assertRaises(ValueError):
            s.analytics({"investigation_id": "PSI-69", "field_name": "burning_rate_mm2_s", "unit": "ppm"})
        with self.assertRaises(ValueError):
            s.export({"investigation_id": "PSI-69", "field_name": "burning_rate_mm2_s", "format": "xlsx"})

    def test_cfi_service_contracts_and_unavailable_isolation(self):
        from genaius.cfi import CfiLoadError

        s = self.service
        self.assertEqual(s.cfi_status, "ready")

        schema_res = s.cfi_schema()
        self.assertEqual(schema_res["status"], "OK")
        self.assertEqual(schema_res["mode"], "cfi_descriptive_only")
        self.assertFalse(schema_res["llm_enabled"])
        self.assertEqual(schema_res["data"]["investigation_id"], "PSI-39")
        self.assertEqual(schema_res["data"]["pool_summary"]["total_records"], 227)
        self.assertEqual(schema_res["data"]["pool_summary"]["candidate_pool_count"], 144)
        self.assertFalse(schema_res["data"]["scope"]["cfi_report_indexed_in_rag"])

        default_res = s.cfi_analysis({})
        self.assertEqual(default_res["status"], "OK")
        self.assertEqual(default_res["mode"], "cfi_descriptive_only")
        self.assertFalse(default_res["llm_enabled"])
        self.assertEqual(
            [g["fuel"] for g in default_res["data"]["fuel_groups"]],
            ["C12H26", "75/25 C12H26/iso-dodecane", "60/40 C12H26/iso-dodecane"],
        )

        no_ev = s.cfi_analysis({
            "pressure_atm": 0.5,
            "fiber": "No",
            "fuel": "75/25 C12H26/iso-dodecane",
        })
        self.assertEqual(no_ev["status"], "NO_EVIDENCE")
        self.assertEqual(no_ev["data"]["fuel_groups"], [])

        for bad in (
            {"pressure_atm": 3.0, "fiber": "Yes"},
            {"pressure_atm": 1.0, "fiber": None},
            {"pressure_atm": 1.0, "fiber": "all"},
            {"pressure_atm": 1.0, "fiber": "Yes", "fuel": "Farnesane"},
            {"pressure_atm": 1.0, "fiber": "Yes", "sql": "SELECT *"},
        ):
            with self.assertRaises(ValueError):
                s.cfi_analysis(bad)

        degraded = AppService(
            ROOT,
            cfi_loader=lambda _r: (_ for _ in ()).throw(CfiLoadError("C:/secret/missing_openpyxl")),
        )
        self.assertEqual(degraded.cfi_status, "unavailable")
        self.assertEqual(degraded.cfi_schema()["status"], "CFI_UNAVAILABLE")
        self.assertNotIn("C:/secret", degraded.cfi_schema()["message"])
        self.assertEqual(degraded.cfi_analysis({"pressure_atm": 1.0, "fiber": "Yes"})["status"], "CFI_UNAVAILABLE")
        self.assertEqual(degraded.search({"investigation_id": "PSI-25"})["data"]["total_runs"], 129)
        self.assertEqual(degraded.evidence({"query": "Cool flames", "investigation_id": "PSI-39"})["status"], "ABSTAINED")

    def test_saffire_service_contracts_and_unavailable_isolation(self):
        from genaius.saffire import SaffireLoadError

        s = self.service
        self.assertEqual(s.saffire_status, "ready")

        schema_res = s.saffire_schema()
        self.assertEqual(schema_res["status"], "OK")
        self.assertEqual(schema_res["mode"], "saffire_reference_only")
        self.assertFalse(schema_res["llm_enabled"])
        self.assertEqual(schema_res["data"]["investigation_id"], "PSI-99")
        self.assertEqual(schema_res["data"]["row_separation"]["physical_sample_count"], 9)
        self.assertEqual(schema_res["data"]["row_separation"]["auxiliary_and_note_row_count"], 6)
        self.assertFalse(schema_res["data"]["scope"]["queryable_in_core"])
        self.assertFalse(schema_res["data"]["scope"]["indexed_in_rag"])

        all_cards = s.saffire_reference({})
        self.assertEqual(all_cards["status"], "OK")
        self.assertEqual(all_cards["mode"], "saffire_reference_only")
        self.assertFalse(all_cards["llm_enabled"])
        self.assertEqual(all_cards["data"]["total_returned_cards"], 9)

        one_card = s.saffire_reference({"sample_id": "2-7"})
        self.assertEqual(one_card["status"], "OK")
        self.assertEqual(one_card["data"]["total_returned_cards"], 1)
        self.assertEqual(one_card["data"]["cards"][0]["sample_id"], "2-7")

        no_ev = s.saffire_reference({"sample_id": "2-99"})
        self.assertEqual(no_ev["status"], "NO_EVIDENCE")
        self.assertEqual(no_ev["data"]["total_returned_cards"], 0)
        self.assertEqual(no_ev["data"]["cards"], [])

        for bad in (
            {"sample_id": 21},
            {"sample_id": "   "},
            {"sample_id": "../secret"},
            {"unknown": "field"},
            {"path": "data/raw/psi"},
        ):
            with self.assertRaises(ValueError):
                s.saffire_reference(bad)

        degraded = AppService(
            ROOT,
            saffire_loader=lambda _r: (_ for _ in ()).throw(SaffireLoadError("C:/secret/saffire.csv missing")),
        )
        self.assertEqual(degraded.saffire_status, "unavailable")
        self.assertEqual(degraded.saffire_schema()["status"], "SAFFIRE_UNAVAILABLE")
        self.assertNotIn("C:/secret", degraded.saffire_schema()["message"])
        self.assertEqual(degraded.saffire_reference({"sample_id": "2-1"})["status"], "SAFFIRE_UNAVAILABLE")
        # Core (403 runs + 503 chunks), V12 gate, and CFI remain available when SAFFIRE is unavailable
        self.assertEqual(degraded.search({"investigation_id": "PSI-25"})["data"]["total_runs"], 129)
        self.assertEqual(degraded.search({"investigation_id": "PSI-69"})["data"]["total_runs"], 274)
        self.assertEqual(degraded.schema()["data"]["chunk_count"], 503)
        self.assertEqual(degraded.cfi_schema()["data"]["pool_summary"]["candidate_pool_count"], 144)
        self.assertEqual(degraded.evidence({"query": "flammability", "investigation_id": "PSI-99"})["status"], "ABSTAINED")

    def test_flex_and_materials_service_contracts(self):
        s = self.service
        fx = s.analytics_flex({"fuel": "Methanol", "o2_min_pct": 18.0, "o2_max_pct": 24.0})
        self.assertEqual(fx["status"], "OK")
        self.assertEqual(fx["mode"], "descriptive_analytics_only")
        self.assertFalse(fx["llm_enabled"])
        self.assertGreater(fx["data"]["total_runs"], 0)

        fx_empty = s.analytics_flex({"fuel": "Methanol", "o2_min_pct": 40.0, "o2_max_pct": 45.0})
        self.assertEqual(fx_empty["status"], "NO_EVIDENCE")
        self.assertEqual(fx_empty["data"]["total_runs"], 0)

        mt = s.analytics_materials({"target_o2_pct": 34.0, "dedupe_samples": True})
        self.assertEqual(mt["status"], "OK")
        self.assertEqual(mt["data"]["aggregation_mode"], "unique_sample_median")
        self.assertEqual(mt["data"]["total_runs"], 129)
        self.assertEqual(mt["data"]["unique_sample_count"], 107)
        self.assertEqual(len(mt["data"]["runs"]), 107)
        self.assertTrue(mt["data"]["beyond_tested_range"])

        for bad in (
            {"unknown_field": 1},
            {"o2_min_pct": True},
        ):
            with self.assertRaises(ValueError):
                s.analytics_flex(bad)

        for bad_mat in (
            {"target_o2_pct": "21"},
            {"flow_restrictor": 5},
            {"dedupe_samples": "yes"},
        ):
            with self.assertRaises(ValueError):
                s.analytics_materials(bad_mat)

    def test_schema_reports_llm_enabled_when_answer_adapter_configured(self):
        class _DummyAdapter:
            class config:
                model = "google/gemma-4-26b-a4b-it:free"

            def generate(self, adapter_input):
                return "{}"

        svc = AppService(ROOT, answer_adapter=_DummyAdapter())
        schema = svc.schema()
        self.assertTrue(schema["llm_enabled"])
        self.assertEqual(schema["data"]["llm_model"], "google/gemma-4-26b-a4b-it:free")

    def test_flex_prediction_and_reconciliation_service_methods(self) -> None:
        svc = AppService(ROOT)
        recon = svc.flex_reconciliation()
        self.assertEqual(recon["status"], "OK")
        self.assertEqual(recon["mode"], "flex_reconciliation_only")
        self.assertFalse(recon["llm_enabled"])
        self.assertEqual(recon["data"]["reconciliation_summary"]["matched_shared_rows"], 274)
        self.assertEqual(recon["data"]["reconciliation_summary"]["table_ix_only_labels"], ["FLEX-216", "FLEX-230"])

        pred_schema = svc.flex_prediction_schema()
        self.assertEqual(pred_schema["status"], "OK")
        self.assertEqual(pred_schema["mode"], "flex_condition_prediction_only")
        self.assertFalse(pred_schema["llm_enabled"])
        self.assertIn("Methanol", pred_schema["data"]["supported_fuels"])

        pred_ok = svc.flex_prediction(
            {
                "fuel": "Methanol",
                "o2_mol_frac": 0.21,
                "co2_mol_frac": 0.0,
                "he_mol_frac": 0.0,
                "pressure_atm": 1.0,
                "droplet_initial_diameter_mm": 2.5,
            }
        )
        self.assertEqual(pred_ok["status"], "OK")
        self.assertGreater(pred_ok["data"]["predictions"]["burning_rate_mm2_s"]["value"], 0.0)

        pred_ood = svc.flex_prediction(
            {
                "fuel": "Heptane",
                "o2_mol_frac": 0.21,
                "co2_mol_frac": 0.0,
                "he_mol_frac": 0.0,
                "pressure_atm": 3.0,
                "droplet_initial_diameter_mm": 2.5,
            }
        )
        self.assertEqual(pred_ood["status"], "NOT_SUPPORTED")
        self.assertIsNone(pred_ood["data"]["predictions"])

        # Scoped FLEX model explanation keeps MODEL:* separate from TBL:* and preserves V10/safety abstention
        flex_ans = svc.answer(
            {
                "query": "Explain these model results and nearest PSI-69 tests.",
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
        )
        self.assertEqual(flex_ans["status"], "OK")
        cids = [s["citation_id"] for s in flex_ans["data"]["sources"]]
        self.assertIn("MODEL:ridge_phys8", cids)
        self.assertTrue(any(c.startswith("TBL:PSI-69:") for c in cids))

        blocked_flex = svc.answer(
            {
                "query": "Predict spacecraft cabin fire safety rating from these results.",
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
        )
        self.assertEqual(blocked_flex["status"], "ABSTAINED")

    def test_missing_optional_flex_artifacts_preserve_core_services(self) -> None:
        def _fail(_root: Path):
            raise FileNotFoundError("optional artifact missing")

        svc = AppService(ROOT, flex_predictor_loader=_fail, flex_reconciliation_loader=_fail)
        self.assertEqual(svc.schema()["status"], "OK")
        self.assertEqual(svc.flex_prediction_schema()["status"], "FLEX_PREDICTOR_UNAVAILABLE")
        self.assertEqual(svc.flex_reconciliation()["status"], "FLEX_RECONCILIATION_UNAVAILABLE")
        self.assertEqual(
            svc.flex_prediction(
                {
                    "fuel": "Methanol",
                    "o2_mol_frac": 0.21,
                    "co2_mol_frac": 0.0,
                    "he_mol_frac": 0.0,
                    "pressure_atm": 1.0,
                    "droplet_initial_diameter_mm": 2.5,
                }
            )["status"],
            "FLEX_PREDICTOR_UNAVAILABLE",
        )

    def test_saffire_case_service_and_fault_isolation(self) -> None:
        svc = AppService(ROOT)
        # Core schema remains strictly 403 runs (129 + 274)
        schema = svc.schema()
        self.assertEqual(
            {d["id"]: d["run_count"] for d in schema["data"]["datasets"]},
            {"PSI-25": 129, "PSI-69": 274},
        )

        cs = svc.saffire_case_schema()
        self.assertEqual(cs["status"], "OK")
        self.assertEqual(cs["mode"], "saffire_case_reference")
        self.assertEqual(cs["data"]["available_test_ids"], ["IV-1", "V-2", "V-3", "V-4", "VI-2", "VI-3", "VI-4"])

        ref = svc.saffire_case_reference({"test_id": "V-3"})
        self.assertEqual(ref["status"], "OK")
        self.assertEqual(ref["data"]["total_matching_records"], 1)
        self.assertIsNone(ref["data"]["records"][0]["co_increase_ppm"])

        exp = svc.saffire_case_export({"format": "csv", "fuel_group": "thin_textile"})
        self.assertEqual(exp["status"], "OK")
        self.assertEqual(exp["data"]["record_count"], 3)
        self.assertIn("source_locators", exp["data"]["content"])

        # Core evidence stays isolated when scope omitted
        core_ev = svc.evidence({"query": "What did Saffire VI-3 do to cabin air?"})
        self.assertEqual(core_ev["status"], "ABSTAINED")
        self.assertEqual(core_ev["data"]["abstention"]["reason_code"], "V12_OUT_OF_SCOPE_STUDY")

        # Case scope retrieves Saffire case citations and abstains on crew survival
        case_ans = svc.answer({"query": "What happened in Saffire VI-3?", "scope": "saffire_case", "top_k": 4})
        self.assertEqual(case_ans["status"], "OK")
        self.assertEqual(case_ans["data"]["answer_mode"], "deterministic")
        self.assertTrue(any(s["citation_id"].startswith("CASE-TBL:") for s in case_ans["data"]["sources"]))

        blocked = svc.answer({"query": "Is VI-3 safe for crew breathing?", "scope": "saffire_case"})
        self.assertEqual(blocked["status"], "ABSTAINED")

        # Validation errors raise ValueError (mapped to HTTP 400)
        with self.assertRaises(ValueError):
            svc.saffire_case_reference({"test_id": "VI-99"})
        with self.assertRaises(ValueError):
            svc.saffire_case_export({"format": "xlsx"})

        # Fault isolation when case JSON fails to load
        def _broken(_root: Path):
            raise FileNotFoundError("missing case json")

        broken_svc = AppService(ROOT, saffire_case_loader=_broken)
        self.assertEqual(broken_svc.schema()["status"], "OK")
        self.assertEqual(broken_svc.saffire_case_schema()["status"], "SAFFIRE_CASE_UNAVAILABLE")
        self.assertEqual(broken_svc.saffire_case_reference({})["status"], "SAFFIRE_CASE_UNAVAILABLE")
        self.assertEqual(broken_svc.saffire_case_export({"format": "json"})["status"], "SAFFIRE_CASE_UNAVAILABLE")

    def test_global_auto_scope_routing_and_guardrail_matrix(self) -> None:
        from genaius.saffire_case import SaffireCaseLoadError

        svc = AppService(ROOT)

        # 1. Global auto routes unambiguous SAFFIRE VI-3 query to saffire_case
        vi3_auto = svc.answer({"query": "What happened in Saffire VI-3?", "scope": "auto"})
        self.assertEqual(vi3_auto["status"], "OK")
        self.assertEqual(vi3_auto["data"]["scope_routing"]["resolved_scope"], "saffire_case")
        self.assertTrue(vi3_auto["data"]["scope_routing"]["auto_routed"])
        self.assertTrue(any(s["citation_id"].startswith("CASE-TBL:") for s in vi3_auto["data"]["sources"]))

        # 2. Explicit scope='core' preserves strict V12_OUT_OF_SCOPE_STUDY isolation
        vi3_core = svc.answer({"query": "What happened in Saffire VI-3?", "scope": "core"})
        self.assertEqual(vi3_core["status"], "ABSTAINED")
        self.assertEqual(vi3_core["data"]["abstention"]["reason_code"], "V12_OUT_OF_SCOPE_STUDY")

        # 3a. Ambiguous bare "Saffire" asks for scope clarification (0 LLM calls, no silent core fallback)
        ambig = svc.answer({"query": "What did Saffire show about microgravity flames?", "scope": "auto"})
        self.assertEqual(ambig["status"], "ABSTAINED")
        self.assertFalse(ambig["llm_enabled"])
        self.assertEqual(ambig["data"]["abstention"]["reason_code"], "SCOPE_CLARIFICATION_REQUIRED")
        self.assertEqual(ambig["data"]["scope_routing"]["resolved_scope"], "clarification")
        self.assertNotEqual(ambig["data"]["coverage"]["status"], "no_match")
        opts = {o["scope"] for o in ambig["data"]["scope_routing"]["scope_options"]}
        self.assertEqual(opts, {"saffire_case", "core", "psi99_cards"})

        # 3b. Explicit PSI-99 / SAFFIRE-II directs to reference inventory without pooling
        psi99 = svc.answer({"query": "Tell me about SAFFIRE-II PSI-99 results", "scope": "auto"})
        self.assertEqual(psi99["status"], "ABSTAINED")
        self.assertEqual(psi99["data"]["abstention"]["reason_code"], "SCOPE_CLARIFICATION_REQUIRED")
        self.assertIn("data.html#s-saffire", psi99["data"]["abstention"]["explanation"])

        # 4. Cross-study pooling across separated experiments is refused cleanly without LLM
        pooled = svc.answer({"query": "Combine BASS-II, FLEX, and Saffire VI-3 into one dataset", "scope": "auto"})
        self.assertEqual(pooled["status"], "ABSTAINED")
        self.assertFalse(pooled["llm_enabled"])
        self.assertEqual(pooled["data"]["abstention"]["reason_code"], "CROSS_STUDY_POOLING_NOT_SUPPORTED")

        # 5. Clear BASS-II / FLEX / PSI-25 / PSI-69 queries route to core
        flex_auto = svc.answer({"query": "Burning rate for Methanol in FLEX PSI-69", "scope": "auto", "fuel": "Methanol"})
        self.assertEqual(flex_auto["status"], "OK")
        self.assertEqual(flex_auto["data"]["scope_routing"]["resolved_scope"], "core")

        # 6. Safety certification abstains under auto just like explicit scopes
        unsafe = svc.answer({"query": "Is Saffire VI-3 safe for crew breathing without scrubbing?", "scope": "auto"})
        self.assertEqual(unsafe["status"], "ABSTAINED")
        self.assertFalse(unsafe["llm_enabled"])

        # 7. Unavailable saffire_case returns SAFFIRE_CASE_UNAVAILABLE, never silent core fallback
        degraded = AppService(
            ROOT,
            saffire_case_loader=lambda _r: (_ for _ in ()).throw(SaffireCaseLoadError("offline")),
        )
        unavail = degraded.answer({"query": "What happened in Saffire VI-3?", "scope": "auto"})
        self.assertEqual(unavail["status"], "SAFFIRE_CASE_UNAVAILABLE")
        self.assertEqual(unavail["coverage"]["status"], "unavailable")
        self.assertEqual(unavail["data"]["failure_reason"], "SOURCE_UNAVAILABLE")

        # 8. Contextual query with PSI-25 filter (exact Material Lab payload) preserves active context on core route
        ctx_core = svc.answer({
            "query": "Explain these results",
            "scope": "auto",
            "investigation_id": "PSI-25",
            "numeric_filters": [{"field_name": "initial_o2_vol_pct", "unit": "% vol", "min_value": 18, "max_value": 24}],
        })
        self.assertEqual(ctx_core["status"], "OK")
        self.assertEqual(ctx_core["data"]["scope_routing"]["resolved_scope"], "core")
        self.assertTrue(any(s["citation_id"].startswith("TBL:PSI-25:") for s in ctx_core["data"]["sources"]))


if __name__ == "__main__":
    unittest.main()
