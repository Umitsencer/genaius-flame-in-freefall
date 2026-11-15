"""Pre-registered deterministic & mocked-OpenRouter evaluation suite (3 smoke + 10 eval cases)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from genaius.app_service import AppService
from genaius.openrouter import OpenRouterAdapter, OpenRouterConfig

CASES_PATH = Path(__file__).resolve().parent / "eval_cases.json"


class PreRegisteredRagEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        cls.cases = cls.spec["cases"]
        cls.det_service = AppService(ROOT)

    def test_evaluation_spec_shape_and_budget(self) -> None:
        self.assertLessEqual(len(self.cases), self.spec["live_request_budget_max"])
        self.assertEqual(sum(1 for c in self.cases if c["tier"] == "smoke"), 3)
        self.assertEqual(sum(1 for c in self.cases if c["tier"] == "eval"), 10)
        ids = [c["id"] for c in self.cases]
        self.assertEqual(len(ids), len(set(ids)))

    def test_deterministic_baselines_across_all_13_cases(self) -> None:
        for case in self.cases:
            with self.subTest(case_id=case["id"]):
                ev_env = self.det_service.evidence(dict(case["request"]))
                ev = ev_env["data"]
                ans_env = self.det_service.answer(dict(case["request"]))
                ans = ans_env["data"]

                self.assertEqual(ans_env["status"], case["expected_status"])
                self.assertFalse(ans_env["llm_enabled"])
                self.assertEqual(ans["answer_mode"], "deterministic")

                if case["expected_status"] == "ABSTAINED":
                    self.assertTrue(ans["abstention"]["abstained"])
                    self.assertEqual(ans["abstention"]["reason_code"], case["expected_reason_code"])
                    self.assertEqual(ans["findings"], [])
                    self.assertEqual(ans["sources"], [])
                    continue

                source_ids = [s["citation_id"] for s in ans["sources"]]
                for prefix in case.get("required_citation_prefixes", []):
                    self.assertTrue(
                        any(cid.startswith(prefix) for cid in source_ids),
                        f"{case['id']} missing citation prefix {prefix!r} in {source_ids}",
                    )

                if "expected_total_runs" in case:
                    self.assertEqual(ev["table_result"]["total_runs"], case["expected_total_runs"])
                if "expected_summary_used_count" in case:
                    self.assertEqual(ev["field_summary"]["used_total_count"], case["expected_summary_used_count"])
                if "expected_summary_max" in case:
                    self.assertAlmostEqual(ev["field_summary"]["max_value"], case["expected_summary_max"], places=3)
                if "expected_summary_mean" in case:
                    self.assertAlmostEqual(
                        ev["field_summary"]["mean_value"],
                        case["expected_summary_mean"],
                        places=3,
                    )
                if "expected_compare_count" in case:
                    self.assertEqual(len(ev["comparison_result"]["rows"]), case["expected_compare_count"])
                for needle in case.get("required_summary_substrings", []):
                    self.assertIn(needle, ans["summary"])

                if case["id"] == "eval_09_missing_vs_measured_burning_rate":
                    row0 = ev["comparison_result"]["rows"][0]
                    rate_m = row0["measurements"]["burning_rate_mm2_s"]
                    self.assertEqual(rate_m["status"], "missing")
                    self.assertIsNone(rate_m["normalized_value"])

    def test_mocked_openrouter_adapter_preserves_citations_boundaries_and_fallback(self) -> None:
        calls: list[dict] = []

        def _mock_transport(method: str, url: str, headers: dict, body: bytes | None, timeout: float):
            payload = json.loads((body or b"{}").decode("utf-8"))
            calls.append({"url": url, "headers": headers, "payload": payload})
            user_msg = payload["messages"][1]["content"]
            marker = "BEGIN_EVIDENCE_BUNDLE_JSON\n"
            end_marker = "\nEND_EVIDENCE_BUNDLE_JSON"
            bundle_json = user_msg.split(marker, 1)[1].split(end_marker, 1)[0]
            bundle_dict = json.loads(bundle_json)
            allowed = bundle_dict["allowed_citation_ids"]
            user_q = payload["messages"][1]["content"]
            if "IGNORE PREVIOUS INSTRUCTIONS" in user_q:
                # Simulated prompt-injected response attempting to forge a fake citation
                content_obj = {
                    "summary": "Forged unsafe rating.",
                    "findings": [{"text": "PMMA safety score 10/10.", "citation_ids": ["DOC:FAKE:999"]}],
                    "limitations": [],
                }
            else:
                content_obj = {
                    "summary": f"Grounded OpenRouter summary citing {allowed[0]}.",
                    "findings": [
                        {
                            "text": "Verified NASA evidence finding anchored to retrieved citations.",
                            "citation_ids": allowed[:2] if len(allowed) >= 2 else allowed[:1],
                        }
                    ],
                    "limitations": [
                        "Bounded to verified PSI-25/PSI-69 evidence bundle; not a safety rating or Mars/Moon extrapolation."
                    ],
                }
            return (
                200,
                {
                    "id": "gen-mock",
                    "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content_obj)}}],
                },
            )

        cfg = OpenRouterConfig(api_key="sk-or-v1-eval-suite-synthetic-key")
        adapter = OpenRouterAdapter(config=cfg, transport=_mock_transport)
        svc = AppService(ROOT, answer_adapter=adapter)
        schema = svc.schema()
        self.assertTrue(schema["llm_enabled"])
        self.assertEqual(schema["data"]["llm_model"], cfg.model)

        for case in self.cases:
            with self.subTest(case_id=case["id"]):
                before_calls = len(calls)
                ans_env = svc.answer(dict(case["request"]))
                ans = ans_env["data"]
                invoked = len(calls) > before_calls
                self.assertEqual(invoked, case["expect_llm_invoked"])
                self.assertEqual(ans_env["status"], case["expected_status"])

                if case.get("simulate_injection_violation"):
                    self.assertEqual(ans["answer_mode"], case["expected_mode_under_injection"])
                    self.assertFalse(ans["llm_used"])
                    self.assertTrue(any(w.startswith("llm_fallback:") for w in ans["warnings"]))
                    self.assertNotIn("DOC:FAKE:999", json.dumps(ans))
                elif case["expect_llm_invoked"]:
                    self.assertEqual(ans["answer_mode"], "llm")
                    self.assertTrue(ans["llm_used"])
                    self.assertTrue(ans["sources"])
                else:
                    self.assertEqual(ans["answer_mode"], "deterministic")
                    self.assertFalse(ans["llm_used"])


if __name__ == "__main__":
    unittest.main()
