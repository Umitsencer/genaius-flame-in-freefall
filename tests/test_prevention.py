"""Görev 058: ortak önleme özeti — katman ayrımı, uydurma yok, skor yok."""
import json
import re
import unittest
from pathlib import Path

from genaius.app_service import AppService

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless((ROOT / "data/raw/psi").is_dir(), "raw data not downloaded")
class PreventionSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = AppService(ROOT)
        cls.summary = cls.svc.prevention_summary()["data"]

    def test_four_topics_with_separated_layers(self):
        self.assertEqual([t["topic"] for t in self.summary["topics"]],
                         ["atmosphere", "material", "flow", "detection_suppression"])
        for t in self.summary["topics"]:
            for key in ("computed", "source_findings", "not_in_sources", "engineering_interpretation"):
                self.assertIn(key, t)
            self.assertTrue(t["not_in_sources"])
            for i in t["engineering_interpretation"]:
                self.assertIn("not a NASA finding", i["label"])

    def test_no_scores_and_no_partial_gravity_evidence(self):
        text = json.dumps(self.summary).lower()
        self.assertNotRegex(text, r"risk score\"|safety score\"|\"score\":")
        for t in self.summary["topics"]:
            for c in t["computed"] + t["source_findings"]:
                self.assertIsNone(re.search(r"\b(moon|mars|lunar)\b", c["text"].lower()), c["text"])

    def test_chatbot_uses_same_payload_without_llm(self):
        env = self.svc.answer({"query": "How can we prevent fires in spacecraft?", "scope": "auto"})
        self.assertEqual(env["data"]["answer_mode"], "prevention_summary")
        self.assertFalse(env["data"]["llm_used"])
        self.assertEqual(env["data"]["prevention_summary"], self.summary)


if __name__ == "__main__":
    unittest.main()
