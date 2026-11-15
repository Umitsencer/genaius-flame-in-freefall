"""Görev 058: tablodan doğrudan cevap — ham CSV'den bağımsız doğrulama, sıfır LLM çağrısı."""
import csv
import unittest
from pathlib import Path

from genaius.app_service import AppService

ROOT = Path(__file__).resolve().parents[1]
PSI25 = ROOT / "data/raw/psi/experimental_tables/PSI-25/PSI-25_Experimental table_BASS-II.csv"
O2 = "Calibrated  initial O2 % by vol "


class _CountingAdapter:
    def __init__(self):
        self.calls = 0

    def generate(self, adapter_input):
        self.calls += 1
        raise AssertionError("LLM must not be called for table answers")


def _raw_rows():
    with PSI25.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


@unittest.skipUnless(PSI25.is_file(), "PSI-25 raw CSV not downloaded")
class TableAnswerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = _CountingAdapter()
        cls.svc = AppService(ROOT, answer_adapter=cls.adapter)
        cls.raw = _raw_rows()

    def ask(self, q, **extra):
        return self.svc.answer({"query": q, "scope": "auto", **extra})

    def test_highest_oxygen_solid_matches_raw_csv_and_uses_initial_column(self):
        vals = [(float(r[O2]), r["Test #"]) for r in self.raw if r[O2].strip()]
        top = max(v for v, _ in vals)
        expected_ids = {t for v, t in vals if v == top}
        env = self.ask("What was the highest oxygen level tested on solid materials?")
        d = env["data"]
        self.assertEqual(d["answer_mode"], "table_computed")
        self.assertFalse(d["llm_used"])
        self.assertEqual(d["computed_table"]["value"], top)
        self.assertEqual(d["computed_table"]["field"], "initial_o2_vol_pct")
        self.assertEqual({r["test_id"] for r in d["computed_table"]["rows"]}, expected_ids)
        self.assertEqual(len(d["citation_ids"]), len(expected_ids))  # no top_k / citation cap

    def test_pmma_film_groups_list_every_matching_raw_record(self):
        env = self.ask("Compare PMMA film at 21% and 22.2% oxygen")
        groups = {g["initial_o2_vol_pct"]: {x["test_id"] for x in g["records"]} for g in env["data"]["computed_table"]["groups"]}
        for level in (21.0, 22.2):
            raw_ids = {r["Test #"] for r in self.raw if r[O2].strip() and abs(float(r[O2]) - level) < 0.05
                       and ("film" in r["Fuel Sample Material"].lower() or "micron" in r["Fuel Sample Material"].lower())}
            self.assertEqual(groups[level], raw_ids, level)
        self.assertTrue({"B6", "B8", "B9"} <= groups[21.0])
        self.assertTrue({"B1", "B2", "B3", "B4", "B5", "B7"} <= groups[22.2])

    def test_nomex_co_separates_statuses_and_never_zero_fills(self):
        d = self.ask("How much CO did Nomex produce?")["data"]
        t = d["computed_table"]
        raw = [r for r in self.raw if "nomex" in r["Fuel Sample Material"].lower()]
        self.assertEqual(t["runs"], len(raw))
        missing_final = sum(1 for r in raw if r["Final CO (ppm)"].strip().lower() in ("", "none"))
        self.assertEqual(t["final_status_counts"].get("missing", 0), missing_final)
        for row in t["rows"]:
            if row["final_co_status"] != "measured":
                self.assertIsNone(row["final_co"])
                self.assertIsNone(row["delta_co"])
        self.assertIn("not a produced gas mass", " ".join(d["limitations"]).replace("neither is a produced gas mass", "not a produced gas mass"))
        self.assertTrue(all(s["record_pk"] for s in d["sources"]))

    def test_zero_llm_calls_and_non_table_questions_continue(self):
        self.adapter.calls = 0
        for q in ("What was the highest oxygen level tested on solid materials?",
                  "Compare PMMA film at 21% and 22.2% oxygen", "How much CO did Nomex produce?"):
            self.assertEqual(self.ask(q)["data"]["llm_calls"], 0)
        self.assertEqual(self.adapter.calls, 0)
        env = self.svc.answer({"query": "What is the burning rate unit in PSI-69?", "scope": "auto"})
        self.assertNotEqual(env["data"]["answer_mode"], "table_computed")

    def test_explicit_study_and_structured_requests_are_respected(self):
        env = self.svc.answer({"query": "What was the highest oxygen level tested on solid materials?",
                               "investigation_id": "PSI-69", "scope": "core"})
        self.assertNotEqual(env["data"].get("answer_mode"), "table_computed")
        env = self.svc.answer({"query": "highest oxygen", "scope": "saffire_case"})
        self.assertNotEqual(env["data"].get("answer_mode"), "table_computed")


if __name__ == "__main__":
    unittest.main()
