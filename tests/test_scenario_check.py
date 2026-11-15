import unittest
from pathlib import Path

from genaius.data.loader import load_core_datasets
from genaius.schemas.scenario import ScenarioCheckRequest
from genaius.scenario_check import (GRID_O2, GRID_P, ScenarioChecker, answer_payload, coverage_grid,
                                    parse_question, parse_report_question, report_answer_payload)

ROOT = Path(__file__).resolve().parents[1]


class ScenarioCheckTests(unittest.TestCase):
    def test_optional_purpose_accepts_blank_but_fuel_stays_required(self):
        for purpose in (None, '', '   '):
            request = ScenarioCheckRequest(fuel='Methanol', o2_percent=21, purpose=purpose)
            self.assertIsNone(request.purpose)
        self.assertEqual(ScenarioCheckRequest(fuel='Methanol', o2_percent=21, purpose=' demo ').purpose, 'demo')
        with self.assertRaises(ValueError):
            ScenarioCheckRequest(fuel='   ', o2_percent=21)

    @classmethod
    def setUpClass(cls):
        records, _ = load_core_datasets(ROOT)
        cls.c = ScenarioChecker(records)

    def test_data_loaded(self):
        self.assertEqual(len(self.c.material), 129)
        self.assertEqual(len(self.c.flex), 274)

    def test_pmma_moon_34_is_gap(self):
        r = self.c.check("PMMA", 34, 0.558, 0.166)
        self.assertEqual(r["status"], "GAP")
        text = " ".join(r["differences"])
        self.assertIn("22.2", text)
        self.assertIn("partial-gravity", text)

    def test_pmma_air_micro_is_tested(self):
        r = self.c.check("PMMA", 21, None, 0)
        self.assertEqual(r["status"], "TESTED")
        self.assertGreater(r["matching_tests"], 0)

    def test_pmma_pressure_not_recorded_is_partial(self):
        r = self.c.check("PMMA", 21, 1.0, 0)
        self.assertEqual(r["status"], "PARTIAL")
        self.assertIn("do not record pressure", " ".join(r["differences"]))

    def test_moon_gravity_at_matching_o2_is_partial(self):
        self.assertEqual(self.c.check("PMMA", 21, None, 0.166)["status"], "PARTIAL")

    def test_flex_methanol_with_pressure(self):
        r = self.c.check("methanol", 21, 1.0, 0)
        self.assertEqual(r["status"], "TESTED")
        self.assertTrue(all(n["pressure_atm"] is not None for n in r["nearest"]))

    def test_unknown_fuel_is_gap(self):
        self.assertEqual(self.c.check("titanium", 21)["status"], "GAP")
        self.assertEqual(self.c.check("silicone", 21)["status"], "GAP")

    def test_parse_question_moon_pmma(self):
        p = parse_question("Is PMMA at 34% O2 on the Moon at 8.2 psi covered by NASA tests?")
        self.assertEqual((p["fuel"], p["o2"], p["gravity_g"]), ("PMMA", 34.0, 0.166))
        self.assertAlmostEqual(p["pressure_atm"], 0.558, places=3)

    def test_parse_question_ignores_other_questions(self):
        self.assertIsNone(parse_question("What is the highest oxygen tested for PMMA at 21% O2?"))
        self.assertIsNone(parse_question("How does PMMA burn?"))
        self.assertIsNone(parse_question("Tell me about 34% oxygen"))
        self.assertIsNone(parse_question("PMMA at 21% oxygen results"))  # no coverage cue, pressure or gravity

    def test_parse_question_cue_only(self):
        self.assertEqual(parse_question("Was heptane at 21% oxygen tested?")["fuel"], "Heptane")

    def test_answer_payload_shape(self):
        d = answer_payload(self.c.check("PMMA", 34, 0.558, 0.166))
        self.assertEqual(d["answer_mode"], "scenario_check")
        self.assertTrue(d["summary"].startswith("GAP — PMMA"))
        self.assertFalse(d["llm_used"])
        self.assertTrue(d["sources"])
        self.assertTrue(all(s["source_type"] == "table_row" for s in d["sources"]))
        self.assertTrue(all(f["citation_ids"] for f in d["findings"]))

    def test_turkish_question_and_answer(self):
        p = parse_question("PMMA %34 oksijende, Ay yerçekiminde ve 8,2 psi basınçta NASA testlerinde var mı?")
        self.assertEqual((p["fuel"], p["o2"], p["gravity_g"], p["lang"]), ("PMMA", 34.0, 0.166, "tr"))
        self.assertAlmostEqual(p["pressure_atm"], 0.558, places=3)
        d = answer_payload(self.c.check(**p))
        self.assertTrue(d["summary"].startswith("GAP — PMMA"))
        self.assertIn("kısmi yerçekimi", d["summary"])
        self.assertIn("İndekslenen", d["summary"])
        self.assertTrue(self.c.check("PMMA", 34, 0.558, 0.166)["differences"][0].startswith("Oxygen 34%"))  # key reason first
        self.assertIn("%13.6", d["summary"].replace(",", "."))

    def test_grid_warnings(self):
        nomex = coverage_grid(self.c, "Nomex", 0.0)
        self.assertEqual(len(nomex["warnings"]), 1)           # no pressure recorded for Nomex
        self.assertIn("no pressure", nomex["warnings"][0])
        self.assertEqual(coverage_grid(self.c, "Methanol", 0.0)["warnings"], [])   # FLEX records pressure, micro-g
        earth = coverage_grid(self.c, "Methanol", 1.0)
        self.assertEqual(len(earth["warnings"]), 1)
        self.assertIn("1 g", earth["warnings"][0])
        both = coverage_grid(self.c, "PMMA", 0.166, lang="tr")
        self.assertEqual(len(both["warnings"]), 2)
        self.assertIn("basınç kaydı yok", both["warnings"][0])

    def test_turkish_variants(self):
        self.assertEqual(parse_question("Metanol 34% oksijende test edilmiş mi?")["fuel"], "Methanol")
        self.assertEqual(parse_question("Nomex için %21 oksijen mikro yerçekiminde denenmiş mi?")["gravity_g"], 0.0)
        self.assertEqual(parse_question("SIBAL %20,8 oksijen Mars'ta test edildi mi?")["gravity_g"], 0.378)
        self.assertIsNone(parse_question("Silikon %30 oksijen Mars'ta test edildi mi?"))
        self.assertIsNone(parse_question("PMMA için en yüksek oksijen yüzdesi nedir %21 oksijen"))
        self.assertIsNone(parse_question("PMMA nasıl yanar?"))

    def test_english_unchanged_language(self):
        self.assertEqual(parse_question("Was heptane at 21% oxygen tested?")["lang"], "en")

    def test_habitat_report(self):
        r = self.c.habitat_report("moon")
        self.assertEqual([x["fuel"] for x in r["rows"]], ["PMMA", "Nomex", "SIBAL", "Methanol"])
        # methanol has FLEX tests at 34% O2 (but not at 0.166 g / 0.558 atm), the solids stop at 22.2% O2
        self.assertEqual(r["counts"], {"TESTED": 0, "PARTIAL": 1, "GAP": 3})
        self.assertEqual({x["fuel"]: x["status"] for x in r["rows"]}["Methanol"], "PARTIAL")
        self.assertIn("0 of 4 materials are TESTED, 1 PARTIAL, 3 GAP", r["summary"])
        self.assertTrue(r["hypothetical"])
        tr = self.c.habitat_report("mars", lang="tr")
        self.assertIn("malzemeden", tr["summary"])
        iss = self.c.habitat_report("iss")
        self.assertEqual(iss["counts"], {"TESTED": 1, "PARTIAL": 2, "GAP": 1})
        with self.assertRaises(ValueError):
            self.c.habitat_report("venus")

    def test_report_question(self):
        self.assertEqual(parse_report_question("Which materials are covered for a Moon habitat?")["habitat"], "moon")
        self.assertEqual(parse_report_question("Mars habitatı için hangi malzemeler test edilmiş?")["habitat"], "mars")
        self.assertEqual(parse_report_question("Mars habitatı için hangi malzemeler test edilmiş?")["lang"], "tr")
        self.assertIsNone(parse_report_question("What is a habitat?"))
        self.assertIsNone(parse_report_question("Is PMMA at 34% O2 in a Moon habitat tested?"))
        self.assertEqual(report_answer_payload(self.c.habitat_report("moon"))["answer_mode"], "scenario_check")

    def test_coverage_grid(self):
        g = coverage_grid(self.c, "PMMA", 0.0)
        self.assertEqual(len(g["cells"]), len(GRID_P))
        self.assertEqual(len(g["cells"][0]), len(GRID_O2))
        self.assertEqual(sum(g["counts"].values()), len(GRID_P) * len(GRID_O2))
        self.assertGreater(g["counts"]["GAP"], 0)
        # same rules as check(): 45% O2 for PMMA is a gap, 20% is not
        self.assertEqual(g["cells"][0][-1], "GAP")
        self.assertNotEqual(g["cells"][0][GRID_O2.index(20.0)], "GAP")


if __name__ == "__main__":
    unittest.main()
