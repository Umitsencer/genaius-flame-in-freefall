"""Görev 058: bilimsel açıklama ile desteklenmeyen güvenlik/yerçekimi çıkarımının ayrımı."""
import unittest
from pathlib import Path

from genaius.app_service import AppService
from genaius.saffire_case import evaluate_case_abstention_gate
from genaius.service import evaluate_abstention_gate

ROOT = Path(__file__).resolve().parents[1]

BLOCKED_CORE = {
    "How does Mars safety compare with ISS smoke rules?": "UNSUPPORTED_RISK_OR_GRAVITY_EXTRAPOLATION",
    "Would these results hold on the Moon?": "UNSUPPORTED_RISK_OR_GRAVITY_EXTRAPOLATION",
    "Is PMMA safe for astronauts?": "UNSUPPORTED_SAFETY_JUDGMENT",
    "Which material is safest?": "UNSUPPORTED_SAFETY_JUDGMENT",
    "Does the ISS meet fire safety rules?": "UNSUPPORTED_SAFETY_JUDGMENT",
    "Could this fire have killed the crew?": "UNSUPPORTED_SAFETY_JUDGMENT",
}
ALLOWED = (
    "What fire safety experiments did NASA run?",
    "How was smoke detected in the tests?",
    "What was the highest oxygen level tested on solid materials?",
    "How much CO did Nomex produce?",
    "Does microgravity change flame spread?",
    "Bir ayda kaç test yapıldı?",
)


class ClaimBoundaryTests(unittest.TestCase):
    def test_core_gate_blocks_inference_not_explanation(self):
        for q, code in BLOCKED_CORE.items():
            with self.subTest(q=q):
                self.assertEqual(evaluate_abstention_gate(q).reason_code, code)
        for q in ALLOWED:
            with self.subTest(q=q):
                self.assertFalse(evaluate_abstention_gate(q).abstained)
                self.assertFalse(evaluate_case_abstention_gate(q).abstained)

    def test_case_gate_uses_same_rule(self):
        self.assertEqual(evaluate_case_abstention_gate("Did Saffire V-3 kill the crew?").reason_code,
                         "CASE_HUMAN_SAFETY_OR_CERTIFICATION_BOUNDARY")
        self.assertEqual(evaluate_case_abstention_gate("Predict Mars 3/8g fire gases from Saffire VI").reason_code,
                         "CASE_PARTIAL_GRAVITY_BOUNDARY")


@unittest.skipUnless((ROOT / "data/raw/psi").is_dir(), "raw data not downloaded")
class ClaimBoundaryServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = AppService(ROOT)

    def test_auto_scope_answers_abstain_without_llm(self):
        for q in ("How does Mars safety compare with ISS smoke rules?", "Did Saffire V-3 kill the crew?"):
            with self.subTest(q=q):
                env = self.svc.answer({"query": q, "scope": "auto"})
                self.assertEqual(env["status"], "ABSTAINED")
                self.assertFalse(env["data"]["llm_used"])
                self.assertIn("What the sources support", env["data"]["abstention"]["explanation"])

    def test_scopes_stay_isolated(self):
        env = self.svc.answer({"query": "combine BASS-II and FLEX results", "scope": "auto"})
        self.assertEqual(env["data"]["abstention"]["reason_code"], "CROSS_STUDY_POOLING_NOT_SUPPORTED")


if __name__ == "__main__":
    unittest.main()
