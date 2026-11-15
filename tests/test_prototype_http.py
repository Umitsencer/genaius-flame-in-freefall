"""Gerçek loopback HTTP istekleri: sözleşme, statik erişim ve hata sınırları."""
import http.client
import json
import threading
import unittest
from pathlib import Path
from genaius.app_service import AppService
from genaius.prototype.server import make_server


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(AppService(Path(__file__).resolve().parents[1]), 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=15)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_root_and_api_are_served(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b'<meta http-equiv="refresh" content="0; url=data.html">', body)
        self.assertIn(b'href="data.html"', body)
        self.assertNotIn(b"story-assets", body)
        self.assertIn("Content-Security-Policy", headers)
        status, _, body = self.request("POST", "/api/search", '{"investigation_id":"PSI-25"}',
                                       {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["data"]["total_runs"], 129)

        status, _, body = self.request(
            "POST",
            "/api/evidence",
            '{"query":"What is the burning rate unit in PSI-69?","top_k":2}',
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["status"], "OK")
        self.assertIsNone(payload["data"]["table_result"])
        self.assertEqual(len(payload["data"]["document_result"]["hits"]), 2)

    def test_scenario_evidence_endpoints_are_strict_and_source_linked(self):
        headers = {"Content-Type": "application/json"}
        status, _, body = self.request(
            "POST",
            "/api/scenario/check",
            json.dumps({
                "fuel": "PMMA",
                "o2_percent": 34.0,
                "pressure_atm": 0.558,
                "gravity_g": 0.166,
                "purpose": "Synthetic lunar habitat coverage check",
                "lang": "en",
            }),
            headers,
        )
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["mode"], "scenario_evidence_check")
        self.assertFalse(result["llm_enabled"])
        self.assertEqual(result["data"]["status"], "GAP")
        self.assertEqual(result["data"]["scope"], "PSI-25 BASS-II (129 runs) + PSI-69 FLEX (274 runs), kept separate")
        nearest = result["data"]["nearest"][0]
        self.assertEqual(nearest["investigation_id"], "PSI-25")
        self.assertTrue(nearest["source_sha256"])
        self.assertIn("pick=PSI-25:", nearest["link"])

        status, _, body = self.request(
            "POST",
            "/api/answer",
            json.dumps({"query": "Was PMMA at 34% O2 tested for a Moon habitat?", "scope": "core"}),
            headers,
        )
        self.assertEqual(status, 200)
        answer = json.loads(body)
        self.assertEqual(answer["mode"], "scenario_check")
        self.assertEqual(answer["data"]["answer_mode"], "scenario_check")
        self.assertFalse(answer["data"]["llm_used"])
        self.assertTrue(answer["data"]["sources"])
        self.assertTrue(all(f["citation_ids"] for f in answer["data"]["findings"]))

        status, _, body = self.request(
            "POST",
            "/api/scenario/report",
            '{"habitat":"moon","lang":"en"}',
            headers,
        )
        self.assertEqual(status, 200)
        report = json.loads(body)["data"]
        self.assertEqual(sum(report["counts"].values()), 4)

        status, _, body = self.request(
            "POST",
            "/api/scenario/grid",
            '{"fuel":"Methanol","gravity_g":0.0,"lang":"en"}',
            headers,
        )
        self.assertEqual(status, 200)
        grid = json.loads(body)["data"]
        self.assertEqual(sum(grid["counts"].values()), len(grid["o2_values"]) * len(grid["pressure_values"]))

        for bad_body in (
            '{"fuel":"PMMA"}',
            '{"fuel":"PMMA","o2_percent":34,"unknown":1}',
            '{"fuel":"PMMA","o2_percent":true}',
            '{"fuel":"PMMA","pressure_atm":0}',
            '{"fuel":"PMMA","lang":"de"}',
        ):
            status, _, response = self.request("POST", "/api/scenario/check", bad_body, headers)
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(response)["status"], "INVALID_INPUT")

    def test_evidence_endpoint_combined_doc_only_abstention_and_errors(self):
        headers = {"Content-Type": "application/json"}

        combined_req = json.dumps({
            "query": "PSI-69 burning rate high pressure",
            "numeric_filters": [{"field_name": "ambient_pressure_kpa", "unit": "mmHg", "min_value": 2200}],
            "summarize_field_name": "burning_rate_mm2_s",
            "summarize_unit": "mm²/s",
            "compare_record_pks": ["PSI-69:10", "PSI-69:12"],
            "top_k": 2,
        })
        status, _, body = self.request("POST", "/api/evidence", combined_req, headers)
        self.assertEqual(status, 200)
        combined = json.loads(body)
        self.assertEqual(combined["status"], "OK")
        self.assertFalse(combined["llm_enabled"])
        self.assertEqual(combined["data"]["mode"], "deterministic_fallback")
        self.assertEqual(combined["data"]["table_result"]["total_runs"], 3)
        self.assertEqual(combined["data"]["field_summary"]["used_measured_count"], 2)
        self.assertEqual(len(combined["data"]["document_result"]["hits"]), 2)
        self.assertEqual({c["source_type"] for c in combined["data"]["citations"]}, {"table_row", "document_chunk"})

        doc_only_req = json.dumps({
            "query": "How does FLEX identify cool flames in NASA TP?",
            "investigation_id": "PSI-69",
            "top_k": 2,
        })
        status, _, body = self.request("POST", "/api/evidence", doc_only_req, headers)
        self.assertEqual(status, 200)
        doc_only = json.loads(body)
        self.assertEqual(doc_only["status"], "OK")
        self.assertEqual(doc_only["data"]["resolved_investigation_id"], "PSI-69")
        self.assertIsNone(doc_only["data"]["table_result"])
        self.assertEqual(len(doc_only["data"]["document_result"]["hits"]), 2)
        self.assertTrue(all(c["source_type"] == "document_chunk" for c in doc_only["data"]["citations"]))

        status, _, body = self.request("POST", "/api/evidence", '{"investigation_id":"PSI-69"}', headers)
        self.assertEqual(status, 200)
        table_only = json.loads(body)
        self.assertEqual(table_only["status"], "OK")
        self.assertEqual(table_only["data"]["table_result"]["total_runs"], 274)
        self.assertIsNone(table_only["data"]["document_result"])

        for query_body, expected_reason in [
            ('{"query":"Show droplet tests","investigation_id":"PSI-39"}', "V12_OUT_OF_SCOPE_STUDY"),
            ('{"query":"Classify droplets with d_ext < 1 mm as cool flames","investigation_id":"PSI-69"}', "V10_COOL_FLAME_INFERENCE"),
            ('{"query":"Extrapolate ISS burning rate to Lunar gravity fire risk score"}', "UNSUPPORTED_RISK_OR_GRAVITY_EXTRAPOLATION"),
        ]:
            status, _, body = self.request("POST", "/api/evidence", query_body, headers)
            self.assertEqual(status, 200)
            abstained = json.loads(body)
            self.assertEqual(abstained["status"], "ABSTAINED")
            self.assertEqual(abstained["data"]["abstention"]["reason_code"], expected_reason)
            self.assertEqual(abstained["data"]["citations"], [])

        status, _, body = self.request(
            "POST",
            "/api/evidence",
            '{"fuel":"NonExistentFuel999"}',
            headers,
        )
        self.assertEqual(status, 200)
        empty = json.loads(body)
        self.assertEqual(empty["status"], "NO_EVIDENCE")
        self.assertEqual(empty["data"]["abstention"]["reason_code"], "NO_MATCHING_EVIDENCE")

        for bad_body in [
            '{bad',
            '{"top_k":NaN}',
            '{"summarize_field_name":"burning_rate_mm2_s"}',
            '{"numeric_filters":[{"field_name":"no_such_field","unit":"kPa"}]}',
            '{"query":"PSI-69","top_k":0}',
            '{"query":"burning rate","investigation_id":""}',
            '{"query":"burning rate","investigation_id":"   "}',
            '{"query":"burning rate","investigation_id":"ABC"}',
            '{"query":"burning rate","investigation_id":"PSI-x"}',
            '{"query":"burning rate","investigation_id":"psi-39"}',
        ]:
            status, _, response = self.request("POST", "/api/evidence", bad_body, headers)
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(response)["status"], "INVALID_INPUT")

    def test_answer_endpoint_contract_abstention_and_validation(self):
        headers = {"Content-Type": "application/json"}

        # 1. Combined answer
        combined_req = json.dumps({
            "query": "PSI-69 burning rate high pressure",
            "numeric_filters": [{"field_name": "ambient_pressure_kpa", "unit": "mmHg", "min_value": 2200}],
            "summarize_field_name": "burning_rate_mm2_s",
            "summarize_unit": "mm²/s",
            "compare_record_pks": ["PSI-69:10", "PSI-69:12"],
            "top_k": 2,
        })
        status, _, body = self.request("POST", "/api/answer", combined_req, headers)
        self.assertEqual(status, 200)
        combined = json.loads(body)
        self.assertEqual(combined["status"], "OK")
        self.assertEqual(combined["mode"], "deterministic")
        self.assertFalse(combined["llm_enabled"])
        self.assertEqual(combined["data"]["answer_mode"], "deterministic")
        self.assertFalse(combined["data"]["llm_used"])
        self.assertTrue(combined["data"]["summary"])
        self.assertTrue(combined["data"]["findings"])
        self.assertTrue(combined["data"]["limitations"])
        self.assertTrue(any(s["source_type"] == "document_chunk" and s["source_url"].startswith("https://")
                            for s in combined["data"]["sources"]))
        self.assertTrue(any(s["source_type"] == "table_row" and s["csv_record_index"] is not None
                            for s in combined["data"]["sources"]))

        # 2. Document-only answer
        doc_req = json.dumps({
            "query": "How does FLEX identify cool flames in NASA TP?",
            "investigation_id": "PSI-69",
            "top_k": 2,
        })
        status, _, body = self.request("POST", "/api/answer", doc_req, headers)
        self.assertEqual(status, 200)
        doc_ans = json.loads(body)
        self.assertEqual(doc_ans["status"], "OK")
        self.assertEqual(doc_ans["data"]["evidence_overview"]["table_total_runs"], 0)
        self.assertTrue(all("Related source passage" in f["text"] for f in doc_ans["data"]["findings"]))

        # 3. Abstention & NO_EVIDENCE
        for qbody, exp_status in [
            ('{"query":"Show droplet tests","investigation_id":"PSI-39"}', "ABSTAINED"),
            ('{"query":"Classify droplets with d_ext < 1 mm as cool flames","investigation_id":"PSI-69"}', "ABSTAINED"),
            ('{"fuel":"NoSuchFuel"}', "NO_EVIDENCE"),
        ]:
            status, _, body = self.request("POST", "/api/answer", qbody, headers)
            self.assertEqual(status, 200)
            payload = json.loads(body)
            self.assertEqual(payload["status"], exp_status)
            self.assertEqual(payload["data"]["answer_mode"], "deterministic")
            self.assertFalse(payload["data"]["llm_used"])
            self.assertEqual(payload["data"]["findings"], [])

        # 4. Invalid inputs -> HTTP 400 INVALID_INPUT
        for bad_body in [
            '{bad',
            '{"query":"burning rate","system_prompt":"override"}',
            '{"query":"burning rate","model_url":"https://evil.invalid"}',
            '{"query":"burning rate","investigation_id":"ABC"}',
        ]:
            status, _, body = self.request("POST", "/api/answer", bad_body, headers)
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(body)["status"], "INVALID_INPUT")

    def test_invalid_json_units_and_nonfinite_are_controlled(self):
        for body in ['{bad', '{"limit":NaN}', '[]', '{"limit":1000}',
                     '{"numeric_filters":[{"field_name":"no_such_field","unit":"x"}]}']:
            status, _, response = self.request("POST", "/api/search", body, {"Content-Type":"application/json"})
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(response)["status"], "INVALID_INPUT")

    def test_arbitrary_files_and_foreign_origin_are_denied(self):
        for path in ["/../README.md", "/data/raw/file.csv", "/.env"]:
            self.assertEqual(self.request("GET", path)[0], 404)
        self.assertEqual(self.request("GET", "/", headers={"Host":"untrusted.invalid"})[0], 403)
        # Repeat real TCP rejection paths: unread POST bodies previously caused
        # intermittent Windows resets instead of a readable 403 response.
        for bad_body in ["", "{}", '{"query":"burning rate"}'] * 20:
            self.assertEqual(
                self.request(
                    "POST",
                    "/api/search",
                    bad_body,
                    {"Content-Type": "application/json", "Origin": "https://untrusted.invalid"},
                )[0],
                403,
            )
            self.assertEqual(
                self.request(
                    "POST",
                    "/api/answer",
                    bad_body,
                    {"Content-Type": "application/json", "Host": "untrusted.invalid"},
                )[0],
                403,
            )

    def test_html_security_headers_and_openrouter_answer_wiring(self):
        from genaius.openrouter import OpenRouterAdapter, OpenRouterConfig

        status, resp_headers, html_body = self.request("GET", "/data.html")
        self.assertEqual(status, 200)
        csp = resp_headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertIn("script-src 'self'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertNotIn("unsafe-inline", csp.split("script-src", 1)[-1].split(";", 1)[0])
        self.assertIn(b'js/chat.js', html_body)

        # Fetch deterministic evidence first to verify what citation ID exists on this query.
        ev_status, _, ev_raw = self.request(
            "POST",
            "/api/evidence",
            json.dumps({"query": "n-decane burning rate PSI-69", "investigation_id": "PSI-69"}),
            {"Content-Type": "application/json"},
        )
        self.assertEqual(ev_status, 200)
        cited_id = json.loads(ev_raw)["data"]["citations"][0]["citation_id"]

        fake_adapter = OpenRouterAdapter(
            OpenRouterConfig(api_key="sk-or-v1-http-wire-test"),
            transport=lambda *_: (
                200,
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": json.dumps(
                                    {
                                        "summary": "HTTP-wired OpenRouter PSI-69 summary.",
                                        "findings": [
                                            {
                                                "text": f"Verified citation {cited_id}.",
                                                "citation_ids": [cited_id],
                                            }
                                        ],
                                        "limitations": ["Grounded only in returned evidence."],
                                    }
                                )
                            },
                        }
                    ]
                },
            ),
        )
        llm_srv = make_server(AppService(Path(__file__).resolve().parents[1], answer_adapter=fake_adapter), 0)
        llm_thread = threading.Thread(target=llm_srv.serve_forever, daemon=True)
        llm_thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", llm_srv.server_port, timeout=10)
            conn.request(
                "POST",
                "/api/answer",
                json.dumps({"query": "n-decane burning rate PSI-69", "investigation_id": "PSI-69"}),
                {"Content-Type": "application/json"},
            )
            r = conn.getresponse()
            raw = r.read().decode("utf-8")
            conn.close()
        finally:
            llm_srv.shutdown()
            llm_srv.server_close()
            llm_thread.join(timeout=3)

        self.assertEqual(r.status, 200)
        payload = json.loads(raw)
        self.assertEqual(payload["status"], "OK")
        self.assertTrue(payload["llm_enabled"])
        self.assertEqual(payload["data"]["answer_mode"], "llm")
        self.assertTrue(payload["data"]["llm_used"])
        self.assertNotIn("sk-or-v1-http-wire-test", raw)

    def test_catalog_http_routes_security_and_503_unavailable(self):
        from genaius.catalog import CatalogLoadError

        headers = {"Content-Type": "application/json"}

        # 1. GET /api/catalog/filters & POST /api/catalog/search happy paths
        status, _, body = self.request("GET", "/api/catalog/filters")
        self.assertEqual(status, 200)
        filters_payload = json.loads(body)
        self.assertEqual(filters_payload["status"], "OK")
        self.assertEqual(filters_payload["mode"], "catalog_lookup_only")
        self.assertFalse(filters_payload["llm_enabled"])
        self.assertEqual(filters_payload["data"]["total_studies"], 24)
        self.assertEqual(filters_payload["data"]["core_investigation_ids"], ["PSI-25", "PSI-69"])

        status, _, body = self.request("POST", "/api/catalog/search", '{"query":"PSI-69"}', headers)
        self.assertEqual(status, 200)
        id_payload = json.loads(body)
        self.assertEqual(id_payload["status"], "OK")
        self.assertEqual(id_payload["data"]["total_matches"], 1)
        self.assertEqual(id_payload["data"]["hits"][0]["psi_id"], "PSI-69")
        self.assertTrue(id_payload["data"]["hits"][0]["entry"]["support"]["queryable_in_core"])

        status, _, body = self.request("POST", "/api/catalog/search", '{"query":"quantum warp"}', headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "NO_MATCH")

        # 2. HTTP 400 INVALID_INPUT on bad JSON, NaN, empty query, invalid types
        for bad_body in ('{bad', '{"top_k":NaN}', '[]', '{"query":"   "}', '{"queryable_in_core":"yes"}', '{"extra":1}'):
            status, _, body = self.request("POST", "/api/catalog/search", bad_body, headers)
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(body)["status"], "INVALID_INPUT")

        # 3. Host and Origin checks apply to catalog routes
        self.assertEqual(self.request("GET", "/api/catalog/filters", headers={"Host": "untrusted.invalid"})[0], 403)
        self.assertEqual(
            self.request(
                "POST",
                "/api/catalog/search",
                "{}",
                {"Content-Type": "application/json", "Origin": "https://untrusted.invalid"},
            )[0],
            403,
        )

        # 4. Controlled 503 CATALOG_UNAVAILABLE without breaking /api/search or leaking internal paths
        degraded_srv = make_server(
            AppService(
                Path(__file__).resolve().parents[1],
                catalog_loader=lambda _r: (_ for _ in ()).throw(CatalogLoadError("C:/secret/catalog.json missing")),
            ),
            0,
        )
        degraded_thread = threading.Thread(target=degraded_srv.serve_forever, daemon=True)
        degraded_thread.start()
        try:
            def req_degraded(method, path, req_body=None, req_headers=None):
                conn = http.client.HTTPConnection("127.0.0.1", degraded_srv.server_port, timeout=10)
                try:
                    conn.request(method, path, body=req_body, headers=req_headers or {})
                    resp = conn.getresponse()
                    return resp.status, resp.read()
                finally:
                    conn.close()

            s_f, b_f = req_degraded("GET", "/api/catalog/filters")
            self.assertEqual(s_f, 503)
            p_f = json.loads(b_f)
            self.assertEqual(p_f["status"], "CATALOG_UNAVAILABLE")
            self.assertNotIn("C:/secret", p_f["message"])

            s_s, b_s = req_degraded("POST", "/api/catalog/search", '{"query":"FLEX"}', headers)
            self.assertEqual(s_s, 503)
            self.assertEqual(json.loads(b_s)["status"], "CATALOG_UNAVAILABLE")

            s_core, b_core = req_degraded("POST", "/api/search", '{"investigation_id":"PSI-25"}', headers)
            self.assertEqual(s_core, 200)
            self.assertEqual(json.loads(b_core)["data"]["total_runs"], 129)
        finally:
            degraded_srv.shutdown()
            degraded_srv.server_close()
            degraded_thread.join(timeout=3)

    def test_analytics_and_export_http_endpoints(self):
        import csv
        import io

        headers = {"Content-Type": "application/json"}
        status, _, body = self.request(
            "POST",
            "/api/analytics",
            json.dumps({
                "investigation_id": "PSI-69",
                "field_name": "burning_rate_mm2_s",
                "unit": "mm²/s",
                "numeric_filters": [{"field_name": "ambient_pressure_kpa", "unit": "mmHg", "min_value": 2200}],
            }),
            headers,
        )
        self.assertEqual(status, 200)
        parsed = json.loads(body)
        self.assertEqual(parsed["status"], "OK")
        self.assertEqual(parsed["mode"], "descriptive_analytics_only")
        self.assertFalse(parsed["llm_enabled"])
        self.assertEqual(parsed["data"]["total_runs"], 3)
        self.assertEqual(parsed["data"]["summary"]["median_value"], 0.385)
        self.assertEqual(len(parsed["data"]["raw_points"]), 3)
        self.assertEqual(parsed["data"]["charts"]["raw_record_points"]["points_key"], "raw_points")

        status, _, body = self.request(
            "POST",
            "/api/export",
            json.dumps({
                "investigation_id": "PSI-69",
                "field_name": "burning_rate_mm2_s",
                "unit": "mm²/s",
                "numeric_filters": [{"field_name": "ambient_pressure_kpa", "unit": "mmHg", "min_value": 2200}],
                "format": "csv",
            }),
            headers,
        )
        self.assertEqual(status, 200)
        exp_csv = json.loads(body)
        self.assertEqual(exp_csv["data"]["format"], "csv")
        rows = list(csv.DictReader(io.StringIO(exp_csv["data"]["content"])))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[2]["test_id"], "12")

        status, _, body = self.request(
            "POST",
            "/api/export",
            json.dumps({
                "investigation_id": "PSI-69",
                "field_name": "burning_rate_mm2_s",
                "unit": "mm²/s",
                "numeric_filters": [{"field_name": "ambient_pressure_kpa", "unit": "mmHg", "min_value": 2200}],
                "format": "json",
            }),
            headers,
        )
        self.assertEqual(status, 200)
        exp_json = json.loads(body)
        self.assertEqual(exp_json["data"]["format"], "json")
        self.assertEqual(exp_json["data"]["total_runs"], 3)
        self.assertEqual(len(json.loads(exp_json["data"]["content"])["records"]), 3)

        status, _, body = self.request(
            "POST",
            "/api/analytics",
            json.dumps({
                "investigation_id": "PSI-69",
                "field_name": "burning_rate_mm2_s",
                "unit": "mm²/s",
                "fuel": "NoSuchFuel",
            }),
            headers,
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "NO_EVIDENCE")

        # Validation & security guards
        for bad_path, bad_body in [
            ("/api/analytics", '{"investigation_id":"PSI-39","field_name":"burning_rate_mm2_s","unit":"mm²/s"}'),
            ("/api/analytics", '{"investigation_id":"PSI-69","field_name":"burning_rate_mm2_s","unit":"ppm"}'),
            ("/api/analytics", '{"investigation_id":"PSI-69","field_name":"burning_rate_mm2_s","unit":"mm²/s","path":"data/a.csv"}'),
            ("/api/export", '{"investigation_id":"PSI-69","field_name":"burning_rate_mm2_s","unit":"mm²/s","format":"xml"}'),
        ]:
            st, _, b = self.request("POST", bad_path, bad_body, headers)
            self.assertEqual(st, 400)
            self.assertEqual(json.loads(b)["status"], "INVALID_INPUT")

        st_nan, _, _ = self.request(
            "POST",
            "/api/analytics",
            '{"investigation_id":"PSI-69","field_name":"burning_rate_mm2_s","numeric_filters":[{"field_name":"ambient_pressure_kpa","min_value":NaN}]}',
            headers,
        )
        self.assertEqual(st_nan, 400)

        st_orig, _, _ = self.request(
            "POST",
            "/api/analytics",
            '{"investigation_id":"PSI-69","field_name":"burning_rate_mm2_s"}',
            {**headers, "Origin": "https://evil.example"},
        )
        self.assertEqual(st_orig, 403)

    def test_cfi_http_routes_security_and_503_unavailable(self):
        from genaius.cfi import CfiLoadError

        headers = {"Content-Type": "application/json"}

        status, _, body = self.request("GET", "/api/cfi/schema")
        self.assertEqual(status, 200)
        schema_doc = json.loads(body)
        self.assertEqual(schema_doc["status"], "OK")
        self.assertEqual(schema_doc["mode"], "cfi_descriptive_only")
        self.assertFalse(schema_doc["llm_enabled"])
        self.assertEqual(schema_doc["data"]["pool_summary"]["candidate_pool_count"], 144)

        status, _, body = self.request("POST", "/api/cfi/analysis", "{}", headers)
        self.assertEqual(status, 200)
        default_doc = json.loads(body)
        self.assertEqual(default_doc["status"], "OK")
        self.assertEqual(len(default_doc["data"]["fuel_groups"]), 3)

        status, _, body = self.request(
            "POST",
            "/api/cfi/analysis",
            '{"pressure_atm":0.5,"fiber":"No","fuel":"75/25 C12H26/iso-dodecane"}',
            headers,
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "NO_EVIDENCE")

        for bad_body in (
            '{"pressure_atm":3.0,"fiber":"Yes"}',
            '{"pressure_atm":1.0,"fiber":"all"}',
            '{"pressure_atm":1.0,"fiber":"Yes","fuel":"Farnesane"}',
            '{"pressure_atm":NaN,"fiber":"Yes"}',
            '{"path":"data/secret.xlsx"}',
        ):
            st, _, b = self.request("POST", "/api/cfi/analysis", bad_body, headers)
            self.assertEqual(st, 400)
            self.assertEqual(json.loads(b)["status"], "INVALID_INPUT")

        self.assertEqual(self.request("GET", "/api/cfi/schema", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(
            self.request(
                "POST",
                "/api/cfi/analysis",
                None,
                {**headers, "Origin": "https://evil.example"},
            )[0],
            403,
        )

        # Controlled 503 CFI_UNAVAILABLE keeps core PSI-25/PSI-69 routes alive without leaking paths
        degraded_srv = make_server(
            AppService(
                Path(__file__).resolve().parents[1],
                cfi_loader=lambda _r: (_ for _ in ()).throw(CfiLoadError("C:/secret/workbook.xlsx missing")),
            ),
            0,
        )
        degraded_thread = threading.Thread(target=degraded_srv.serve_forever, daemon=True)
        degraded_thread.start()
        try:
            def req_degraded(method, path, req_body=None, req_headers=None):
                conn = http.client.HTTPConnection("127.0.0.1", degraded_srv.server_port, timeout=10)
                try:
                    conn.request(method, path, body=req_body, headers=req_headers or {})
                    resp = conn.getresponse()
                    return resp.status, resp.read()
                finally:
                    conn.close()

            s_schema, b_schema = req_degraded("GET", "/api/cfi/schema")
            self.assertEqual(s_schema, 503)
            p_schema = json.loads(b_schema)
            self.assertEqual(p_schema["status"], "CFI_UNAVAILABLE")
            self.assertNotIn("C:/secret", p_schema["message"])

            s_an, b_an = req_degraded("POST", "/api/cfi/analysis", '{"pressure_atm":1.0,"fiber":"Yes"}', headers)
            self.assertEqual(s_an, 503)
            self.assertEqual(json.loads(b_an)["status"], "CFI_UNAVAILABLE")

            s_core, b_core = req_degraded("POST", "/api/search", '{"investigation_id":"PSI-25"}', headers)
            self.assertEqual(s_core, 200)
            self.assertEqual(json.loads(b_core)["data"]["total_runs"], 129)
        finally:
            degraded_srv.shutdown()
            degraded_srv.server_close()
            degraded_thread.join(timeout=3)

    def test_saffire_http_routes_security_and_503_unavailable(self):
        from genaius.saffire import SaffireLoadError

        headers = {"Content-Type": "application/json"}

        status, _, body = self.request("GET", "/api/saffire/schema")
        self.assertEqual(status, 200)
        schema_doc = json.loads(body)
        self.assertEqual(schema_doc["status"], "OK")
        self.assertEqual(schema_doc["mode"], "saffire_reference_only")
        self.assertFalse(schema_doc["llm_enabled"])
        self.assertEqual(schema_doc["data"]["row_separation"]["physical_sample_count"], 9)
        self.assertEqual(schema_doc["data"]["row_separation"]["auxiliary_and_note_row_count"], 6)

        status, _, body = self.request("POST", "/api/saffire/reference", "{}", headers)
        self.assertEqual(status, 200)
        all_doc = json.loads(body)
        self.assertEqual(all_doc["status"], "OK")
        self.assertEqual(all_doc["data"]["total_returned_cards"], 9)

        status, _, body = self.request("POST", "/api/saffire/reference", '{"sample_id":"2-8"}', headers)
        self.assertEqual(status, 200)
        one_doc = json.loads(body)
        self.assertEqual(one_doc["status"], "OK")
        self.assertEqual(one_doc["data"]["cards"][0]["test_conditions"]["thickness"]["raw_value"], "See Fig. 5")

        status, _, body = self.request("POST", "/api/saffire/reference", '{"sample_id":"2-10"}', headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "NO_EVIDENCE")

        for bad_body in (
            '{"sample_id":21}',
            '{"sample_id":""}',
            '{"sample_id":"S1"}',
            '{"sample_id":NaN}',
            '{"path":"data/raw/psi"}',
        ):
            st, _, b = self.request("POST", "/api/saffire/reference", bad_body, headers)
            self.assertEqual(st, 400)
            self.assertEqual(json.loads(b)["status"], "INVALID_INPUT")

        self.assertEqual(self.request("GET", "/api/saffire/schema", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(
            self.request(
                "POST",
                "/api/saffire/reference",
                '{"sample_id":"2-1"}',
                {**headers, "Origin": "https://evil.example"},
            )[0],
            403,
        )

        # Controlled 503 SAFFIRE_UNAVAILABLE keeps core and CFI alive without leaking paths
        degraded_srv = make_server(
            AppService(
                Path(__file__).resolve().parents[1],
                saffire_loader=lambda _r: (_ for _ in ()).throw(SaffireLoadError("C:/secret/saffire.csv missing")),
            ),
            0,
        )
        degraded_thread = threading.Thread(target=degraded_srv.serve_forever, daemon=True)
        degraded_thread.start()
        try:
            def req_degraded(method, path, req_body=None, req_headers=None):
                conn = http.client.HTTPConnection("127.0.0.1", degraded_srv.server_port, timeout=10)
                try:
                    conn.request(method, path, body=req_body, headers=req_headers or {})
                    resp = conn.getresponse()
                    return resp.status, resp.read()
                finally:
                    conn.close()

            s_schema, b_schema = req_degraded("GET", "/api/saffire/schema")
            self.assertEqual(s_schema, 503)
            p_schema = json.loads(b_schema)
            self.assertEqual(p_schema["status"], "SAFFIRE_UNAVAILABLE")
            self.assertNotIn("C:/secret", p_schema["message"])

            s_ref, b_ref = req_degraded("POST", "/api/saffire/reference", '{"sample_id":"2-1"}', headers)
            self.assertEqual(s_ref, 503)
            self.assertEqual(json.loads(b_ref)["status"], "SAFFIRE_UNAVAILABLE")

            s_core, b_core = req_degraded("POST", "/api/search", '{"investigation_id":"PSI-25"}', headers)
            self.assertEqual(s_core, 200)
            self.assertEqual(json.loads(b_core)["data"]["total_runs"], 129)

            s_cfi, b_cfi = req_degraded("GET", "/api/cfi/schema")
            self.assertEqual(s_cfi, 200)
            self.assertEqual(json.loads(b_cfi)["data"]["pool_summary"]["candidate_pool_count"], 144)
        finally:
            degraded_srv.shutdown()
            degraded_srv.server_close()
            degraded_thread.join(timeout=3)

    def test_frontend_static_assets_csp_traversal_and_lab_http_endpoints(self):
        headers = {"Content-Type": "application/json"}

        # 1. Entry fallback + all 4 research pages + shared assets and security.
        for path in ("/", "/index.html", "/fire.html", "/material-lab.html", "/data.html", "/case-saffire.html"):
            st, resp_headers, body = self.request("GET", path)
            self.assertEqual(st, 200, msg=f"GET {path} failed")
            text = body.decode("utf-8")
            self.assertNotIn("<script>document.body", text)
            csp = resp_headers.get("Content-Security-Policy", "")
            self.assertIn("script-src 'self'", csp)
            self.assertNotIn("'unsafe-inline'", csp.split("script-src")[1].split(";")[0])

        st_api, h_api, b_api = self.request("GET", "/js/api.js")
        self.assertEqual(st_api, 200)
        self.assertIn("javascript", h_api.get("Content-Type", ""))
        self.assertIn(b"window", b_api)

        st_img, h_img, b_img = self.request("GET", "/assets/logo.jpg")
        self.assertEqual(st_img, 200)
        self.assertEqual(h_img.get("Content-Type"), "image/jpeg")
        self.assertGreater(len(b_img), 1000)

        for bad_path in ("/../src/genaius/app_service.py", "/js/../../secret", "/assets/nonexistent.png", "/story-assets/index-alY2uMcD.js"):
            st_bad, _, _ = self.request("GET", bad_path)
            self.assertEqual(st_bad, 404)

        # 2. POST /api/analytics/flex
        st_fx, _, b_fx = self.request(
            "POST",
            "/api/analytics/flex",
            json.dumps({"p_min_atm": 2200.0 / 760.0}),
            headers,
        )
        self.assertEqual(st_fx, 200)
        fx = json.loads(b_fx)
        self.assertEqual(fx["status"], "OK")
        self.assertEqual(fx["data"]["total_runs"], 3)
        self.assertAlmostEqual(fx["data"]["field_summaries"]["burning_rate_mm2_s"]["mean_value"], 0.385, places=6)

        st_fx_bad, _, b_fx_bad = self.request("POST", "/api/analytics/flex", '{"unknown":1}', headers)
        self.assertEqual(st_fx_bad, 400)
        self.assertEqual(json.loads(b_fx_bad)["status"], "INVALID_INPUT")

        # 3. POST /api/analytics/materials
        st_mt, _, b_mt = self.request(
            "POST",
            "/api/analytics/materials",
            json.dumps({"target_o2_pct": 34.0, "dedupe_samples": True}),
            headers,
        )
        self.assertEqual(st_mt, 200)
        mt = json.loads(b_mt)
        self.assertEqual(mt["status"], "OK")
        self.assertEqual(mt["data"]["aggregation_mode"], "unique_sample_median")
        self.assertEqual(mt["data"]["total_runs"], 129)
        self.assertEqual(len(mt["data"]["runs"]), 107)
        self.assertTrue(mt["data"]["beyond_tested_range"])

        self.assertEqual(
            self.request("POST", "/api/analytics/materials", '{"flow_restrictor":9}', headers)[0],
            400,
        )
        self.assertEqual(
            self.request(
                "POST",
                "/api/analytics/flex",
                "{}",
                {**headers, "Origin": "https://evil.example"},
            )[0],
            403,
        )

    def test_material_lab_grouping_modes_and_out_of_range_oxygen(self):
        for group_by in ("material_family", "material_shape"):
            for target_o2 in (21.0, 39.0):
                with self.subTest(group_by=group_by, target_o2=target_o2):
                    status, _, body = self.request(
                        "POST", "/api/analytics/materials",
                        json.dumps({
                            "target_o2_pct": target_o2, "window_pct": 3.0,
                            "metric": "delta_co_ppm", "group_by": group_by,
                            "dedupe_samples": False,
                        }),
                        {"Content-Type": "application/json"},
                    )
                    self.assertEqual(status, 200)
                    result = json.loads(body)
                    self.assertEqual(result["status"], "OK")
                    data = result["data"]
                    self.assertEqual(data["group_by"], group_by)
                    self.assertEqual(data["total_runs"], 129)
                    self.assertEqual(data["beyond_tested_range"], target_o2 == 39.0)
                    if target_o2 == 39.0:
                        self.assertEqual(data["matched_runs"], 0)
                    else:
                        self.assertGreater(data["matched_runs"], 0)

    def test_flex_prediction_and_reconciliation_http_endpoints(self) -> None:
        headers = {"Content-Type": "application/json"}

        st_rs, _, b_rs = self.request("GET", "/api/flex/reconciliation")
        self.assertEqual(st_rs, 200)
        rec_env = json.loads(b_rs)
        self.assertEqual(rec_env["status"], "OK")
        self.assertEqual(rec_env["data"]["reconciliation_summary"]["psi69_helium_runs"], 50)
        self.assertEqual(rec_env["data"]["reconciliation_summary"]["table_ix_helium_runs"], 51)

        st_ps, _, b_ps = self.request("GET", "/api/flex/predict/schema")
        self.assertEqual(st_ps, 200)
        ps_env = json.loads(b_ps)
        self.assertEqual(ps_env["status"], "OK")
        self.assertEqual(ps_env["mode"], "flex_condition_prediction_only")

        st_p_ok, _, b_p_ok = self.request(
            "POST",
            "/api/flex/predict",
            json.dumps(
                {
                    "fuel": "Methanol",
                    "o2_mol_frac": 0.21,
                    "co2_mol_frac": 0.0,
                    "he_mol_frac": 0.0,
                    "pressure_atm": 1.0,
                    "droplet_initial_diameter_mm": 2.5,
                }
            ),
            headers,
        )
        self.assertEqual(st_p_ok, 200)
        p_ok_env = json.loads(b_p_ok)
        self.assertEqual(p_ok_env["status"], "OK")
        self.assertIn("burning_rate_mm2_s", p_ok_env["data"]["predictions"])
        self.assertEqual(p_ok_env["data"]["local_explanations"]["status"], "DISABLED_UNRELIABLE")
        self.assertFalse(p_ok_env["data"]["local_explanations"]["published"])
        self.assertEqual(
            p_ok_env["data"]["local_explanations"]["method"],
            "audited_disabled_raw6_interventional_shapley",
        )

        st_map, _, b_map = self.request(
            "POST",
            "/api/flex/predict/map",
            json.dumps(
                {
                    "fuel": "Methanol",
                    "diluent_regime": "Air",
                    "pressure_atm": 1.0,
                    "droplet_initial_diameter_mm": 2.5,
                    "o2_steps": 7,
                    "y_steps": 5,
                }
            ),
            headers,
        )
        self.assertEqual(st_map, 200)
        self.assertEqual(json.loads(b_map)["data"]["total_cells"], 35)

        st_exp_fx, _, b_exp_fx = self.request(
            "POST",
            "/api/flex/predict/export",
            json.dumps(
                {
                    "format": "md",
                    "fuel": "Methanol",
                    "o2_mol_frac": 0.21,
                    "co2_mol_frac": 0.0,
                    "he_mol_frac": 0.0,
                    "pressure_atm": 1.0,
                    "droplet_initial_diameter_mm": 2.5,
                }
            ),
            headers,
        )
        self.assertEqual(st_exp_fx, 200)
        self.assertEqual(json.loads(b_exp_fx)["data"]["format"], "md")

        st_p_ood, _, b_p_ood = self.request(
            "POST",
            "/api/flex/predict",
            json.dumps(
                {
                    "fuel": "Heptane",
                    "o2_mol_frac": 0.21,
                    "co2_mol_frac": 0.10,
                    "he_mol_frac": 0.10,
                    "pressure_atm": 1.0,
                    "droplet_initial_diameter_mm": 2.5,
                }
            ),
            headers,
        )
        self.assertEqual(st_p_ood, 200)
        self.assertEqual(json.loads(b_p_ood)["status"], "NOT_SUPPORTED")

        st_p_bad, _, _ = self.request(
            "POST",
            "/api/flex/predict",
            json.dumps(
                {
                    "fuel": "Methanol",
                    "o2_mol_frac": 0.21,
                    "co2_mol_frac": 0.0,
                    "he_mol_frac": 0.0,
                    "pressure_atm": 1.0,
                    "droplet_initial_diameter_mm": 2.5,
                    "test_end": "Extinction",
                }
            ),
            headers,
        )
        self.assertEqual(st_p_bad, 400)

    def test_saffire_case_http_endpoints_and_ui_route(self) -> None:
        headers = {"Content-Type": "application/json"}

        st_html, h_html, b_html = self.request("GET", "/case-saffire.html")
        self.assertEqual(st_html, 200)
        self.assertIn("text/html", h_html.get("Content-Type", ""))
        self.assertIn(b"What did the fire do to the air?", b_html)

        st_sc, _, b_sc = self.request("GET", "/api/saffire/case/schema")
        self.assertEqual(st_sc, 200)
        sc_env = json.loads(b_sc)
        self.assertEqual(sc_env["status"], "OK")
        self.assertEqual(sc_env["data"]["available_test_ids"], ["IV-1", "V-2", "V-3", "V-4", "VI-2", "VI-3", "VI-4"])

        st_ref, _, b_ref = self.request("POST", "/api/saffire/case", '{"test_id":"VI-3"}', headers)
        self.assertEqual(st_ref, 200)
        ref_env = json.loads(b_ref)
        self.assertEqual(ref_env["data"]["total_matching_records"], 1)
        self.assertEqual(ref_env["data"]["summary"]["vi3_timeline"]["derived_elapsed_ignition_to_threshold_s"], 344.0)

        st_exp, _, b_exp = self.request("POST", "/api/saffire/case/export", '{"format":"csv"}', headers)
        self.assertEqual(st_exp, 200)
        self.assertEqual(json.loads(b_exp)["data"]["record_count"], 7)

        st_ans, _, b_ans = self.request(
            "POST",
            "/api/answer",
            '{"query":"What happened in Saffire VI-3?","scope":"saffire_case","top_k":3}',
            headers,
        )
        self.assertEqual(st_ans, 200)
        ans_env = json.loads(b_ans)
        self.assertEqual(ans_env["status"], "OK")
        self.assertTrue(any(s["citation_id"].startswith("CASE-TBL:") for s in ans_env["data"]["sources"]))

        # Bad parameters -> 400
        self.assertEqual(self.request("POST", "/api/saffire/case", '{"test_id":"BAD"}', headers)[0], 400)
        self.assertEqual(self.request("POST", "/api/saffire/case/export", '{"format":"pdf"}', headers)[0], 400)

        # Controlled 503 SAFFIRE_CASE_UNAVAILABLE keeps core and PSI-99 alive
        from genaius.saffire_case import SaffireCaseLoadError

        degraded_srv = make_server(
            AppService(
                Path(__file__).resolve().parents[1],
                saffire_case_loader=lambda _r: (_ for _ in ()).throw(SaffireCaseLoadError("missing case json")),
            ),
            0,
        )
        degraded_thread = threading.Thread(target=degraded_srv.serve_forever, daemon=True)
        degraded_thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", degraded_srv.server_port, timeout=10)
            try:
                conn.request("GET", "/api/saffire/case/schema")
                r = conn.getresponse()
                self.assertEqual(r.status, 503)
                self.assertEqual(json.loads(r.read())["status"], "SAFFIRE_CASE_UNAVAILABLE")

                conn.request("GET", "/api/schema")
                r_core = conn.getresponse()
                self.assertEqual(r_core.status, 200)
                self.assertEqual(json.loads(r_core.read())["status"], "OK")
            finally:
                conn.close()
        finally:
            degraded_srv.shutdown()
            degraded_srv.server_close()
            degraded_thread.join(timeout=3)

    def test_ai_use_doc_and_answer_coverage_and_audit_http(self):
        # 1. GET /docs/AI_USE.md serves safely as plain text / markdown without path traversal
        status, hdrs, body = self.request("GET", "/docs/AI_USE.md")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertIn("OpenRouter", text)
        self.assertIn("MATCHING TESTS FOUND", text)
        self.assertEqual(self.request("GET", "/docs/../../.env")[0], 404)

        # 2. /api/export preserves CSV line-1 header and adds coverage columns
        headers = {"Content-Type": "application/json"}
        st_csv, _, b_csv = self.request(
            "POST",
            "/api/export",
            '{"investigation_id":"PSI-69","field_name":"burning_rate_mm2_s","unit":"mm\\u00b2/s","format":"csv"}',
            headers,
        )
        self.assertEqual(st_csv, 200)
        csv_lines = json.loads(b_csv)["data"]["content"].splitlines()
        self.assertTrue(csv_lines[0].startswith("investigation_id,record_pk,"))
        self.assertIn("coverage_status", csv_lines[0])

        # 3. /api/answer returns coverage + numerical_audit + failure_reason (including HTTP 429)
        from genaius.openrouter import OpenRouterAdapter, OpenRouterConfig

        quota_adapter = OpenRouterAdapter(
            OpenRouterConfig(api_key="sk-or-v1-http-quota-test"),
            transport=lambda *_: (429, {"error": {"message": "Too many requests"}}),
        )
        quota_srv = make_server(AppService(Path(__file__).resolve().parents[1], answer_adapter=quota_adapter), 0)
        quota_thread = threading.Thread(target=quota_srv.serve_forever, daemon=True)
        quota_thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", quota_srv.server_port, timeout=10)
            conn.request(
                "POST",
                "/api/answer",
                json.dumps({"query": "VI-3 gas release", "scope": "saffire_case"}),
                {"Content-Type": "application/json"},
            )
            r = conn.getresponse()
            raw = r.read().decode("utf-8")
            conn.close()
        finally:
            quota_srv.shutdown()
            quota_srv.server_close()
            quota_thread.join(timeout=3)

        self.assertEqual(r.status, 200)
        ans = json.loads(raw)
        self.assertEqual(ans["data"]["answer_mode"], "deterministic_fallback")
        self.assertEqual(ans["data"]["failure_reason"], "LLM_QUOTA_EXCEEDED")
        self.assertEqual(ans["data"]["coverage"]["status"], "matching")
        self.assertNotIn("sk-or-v1-http-quota-test", raw)

        # 4. /api/answer scope='auto' routes Saffire VI-3 over HTTP while preserving scope='core' V12 boundary
        st_auto, _, body_auto = self.request(
            "POST",
            "/api/answer",
            json.dumps({"query": "What happened in Saffire VI-3?", "scope": "auto"}),
            headers,
        )
        self.assertEqual(st_auto, 200)
        auto_ans = json.loads(body_auto)
        self.assertEqual(auto_ans["status"], "OK")
        self.assertEqual(auto_ans["data"]["scope_routing"]["resolved_scope"], "saffire_case")

        st_core, _, body_core = self.request(
            "POST",
            "/api/answer",
            json.dumps({"query": "What happened in Saffire VI-3?", "scope": "core"}),
            headers,
        )
        self.assertEqual(st_core, 200)
        core_ans = json.loads(body_core)
        self.assertEqual(core_ans["status"], "ABSTAINED")
        self.assertEqual(core_ans["data"]["abstention"]["reason_code"], "V12_OUT_OF_SCOPE_STUDY")


if __name__ == "__main__":
    unittest.main()
