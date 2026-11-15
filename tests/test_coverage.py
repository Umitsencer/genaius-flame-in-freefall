"""Tests for Görev 051 typed evidence coverage, O2-pressure grid, and export metadata."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from genaius.analytics import (
    build_export_payload,
    build_flex_analytics,
    build_material_lab_analytics,
)
from genaius.app_service import AppService
from genaius.coverage import COVERAGE_STATUS_LABELS, assess_unavailable_coverage
from genaius.data.loader import load_core_datasets
from genaius.flex_predictor import FlexPredictionValidationError
from genaius.saffire_case import SaffireCaseLoadError


class CoverageUnitAndIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records, _ = load_core_datasets(ROOT)
        cls.service = AppService(ROOT)

    def test_unavailable_never_collapses_to_no_match(self) -> None:
        cov = assess_unavailable_coverage(
            scope="saffire_case",
            corpus_id="SAFFIRE IV-VI",
            error_detail="Missing file",
        )
        self.assertEqual(cov.status, "unavailable")
        self.assertEqual(cov.ui_label, COVERAGE_STATUS_LABELS["unavailable"])
        self.assertNotEqual(cov.status, "no_match")

        degraded = AppService(
            ROOT,
            saffire_case_loader=lambda _r: (_ for _ in ()).throw(SaffireCaseLoadError("offline")),
            flex_predictor_loader=lambda _r: (_ for _ in ()).throw(FlexPredictionValidationError("offline")),
        )
        env_case = degraded.answer({"query": "VI-3 gas", "scope": "saffire_case"})
        self.assertEqual(env_case["status"], "SAFFIRE_CASE_UNAVAILABLE")
        self.assertEqual(env_case["coverage"]["status"], "unavailable")
        self.assertEqual(env_case["data"]["coverage"]["status"], "unavailable")
        self.assertEqual(env_case["data"]["failure_reason"], "SOURCE_UNAVAILABLE")

        env_flex = degraded.flex_prediction(
            {
                "fuel": "Methanol",
                "o2_mol_frac": 0.21,
                "co2_mol_frac": 0.0,
                "he_mol_frac": 0.0,
                "pressure_atm": 1.0,
                "droplet_initial_diameter_mm": 2.5,
            }
        )
        self.assertEqual(env_flex["status"], "FLEX_PREDICTOR_UNAVAILABLE")
        self.assertEqual(env_flex["coverage"]["status"], "unavailable")

    def test_flex_o2_pressure_grid_zero_interpolation_and_totals(self) -> None:
        flex_all = build_flex_analytics(self.records)
        self.assertEqual(flex_all["total_runs"], 274)
        self.assertEqual(flex_all["corpus_total_runs"], 274)
        self.assertEqual(flex_all["coverage"]["status"], "matching")
        self.assertEqual(flex_all["coverage"]["ui_label"], "MATCHING TESTS FOUND")

        grid = flex_all["o2_pressure_coverage"]
        self.assertEqual(grid["total_psi69_count"], 274)
        self.assertEqual(grid["filtered_with_o2_p_count"], 274)
        self.assertEqual(sum(c["total_psi69_count"] for c in grid["cells"]), 274)
        self.assertEqual(sum(c["filtered_count"] for c in grid["cells"]), 274)
        # Verify sparse cells remain strictly zero (never interpolated)
        self.assertTrue(any(c["total_psi69_count"] == 0 and c["filtered_count"] == 0 for c in grid["cells"]))
        regime_ids = {n["dataset"] for n in grid["cross_regime_separation"]}
        self.assertEqual(regime_ids, {"PSI-69 FLEX", "PSI-25 BASS-II", "SAFFIRE IV-VI"})

        flex_sub = build_flex_analytics(self.records, fuel="Methanol", p_min_atm=2.5, p_max_atm=3.1)
        self.assertEqual(flex_sub["total_runs"], flex_sub["o2_pressure_coverage"]["filtered_with_o2_p_count"])
        self.assertLess(flex_sub["total_runs"], 274)
        self.assertEqual(flex_sub["coverage"]["matching_count"], flex_sub["total_runs"])
        self.assertEqual(flex_sub["coverage"]["total_corpus_count"], 274)

        flex_empty = build_flex_analytics(self.records, fuel="Methanol", o2_min_pct=90.0, o2_max_pct=95.0)
        self.assertEqual(flex_empty["total_runs"], 0)
        self.assertEqual(flex_empty["coverage"]["status"], "no_match")
        self.assertEqual(flex_empty["coverage"]["ui_label"], "NO MATCH IN INDEXED SOURCES")

    def test_material_lab_matching_vs_related_exploration_gap(self) -> None:
        mat21 = build_material_lab_analytics(self.records, target_o2_pct=21.0, window_pct=3.0)
        self.assertEqual(mat21["coverage"]["status"], "matching")
        self.assertEqual(mat21["coverage"]["ui_label"], "MATCHING TESTS FOUND")
        self.assertGreater(mat21["matched_runs"], 0)

        # Window 24 +/- 3% overlaps 21-22.2% without tight <=0.5% match -> related
        mat24 = build_material_lab_analytics(self.records, target_o2_pct=24.0, window_pct=3.0)
        self.assertFalse(mat24["beyond_tested_range"])
        self.assertGreater(mat24["matched_runs"], 0)
        self.assertEqual(mat24["tight_matched_runs"], 0)
        self.assertEqual(mat24["coverage"]["status"], "related")
        self.assertEqual(mat24["coverage"]["ui_label"], "RELATED TESTS ONLY")

        # 34% O2 Moon exploration atmosphere is well beyond max tested (~22.2%) -> 0 matches -> no_match
        mat34 = build_material_lab_analytics(self.records, target_o2_pct=34.0, window_pct=3.0)
        self.assertTrue(mat34["beyond_tested_range"])
        self.assertEqual(mat34["matched_runs"], 0)
        self.assertEqual(mat34["coverage"]["status"], "no_match")
        self.assertEqual(mat34["coverage"]["ui_label"], "NO MATCH IN INDEXED SOURCES")

    def test_flex_predictor_separates_nearest_query_and_support_gate(self) -> None:
        ok_env = self.service.flex_prediction(
            {
                "fuel": "Methanol",
                "o2_mol_frac": 0.21,
                "co2_mol_frac": 0.0,
                "he_mol_frac": 0.0,
                "pressure_atm": 1.0,
                "droplet_initial_diameter_mm": 2.5,
            }
        )
        ok_cov = ok_env["data"]["coverage"]
        self.assertIn(ok_cov["status"], {"matching", "related"})
        self.assertIn(ok_cov["tolerance_policy"]["mode"], {"exact_contract", "nearest_neighbor_only"})
        self.assertIn("in_support", ok_cov["applied_filters"])

        # Unsupported 45% O2 / high pressure should NEVER be labeled "matching"
        ood_env = self.service.flex_prediction(
            {
                "fuel": "Heptane",
                "o2_mol_frac": 0.45,
                "co2_mol_frac": 0.0,
                "he_mol_frac": 0.0,
                "pressure_atm": 3.0,
                "droplet_initial_diameter_mm": 4.0,
            }
        )
        self.assertEqual(ood_env["data"]["status"], "NOT_SUPPORTED")
        ood_cov = ood_env["data"]["coverage"]
        self.assertIn(ood_cov["status"], {"related", "no_match"})
        self.assertNotEqual(ood_cov["status"], "matching")

    def test_core_answer_related_vs_no_match_vs_matching(self) -> None:
        ev_match = self.service.answer({"query": "Heptane burning rate PSI-69", "investigation_id": "PSI-69", "fuel": "Heptane"})
        self.assertEqual(ev_match["data"]["coverage"]["status"], "matching")

        # n-Decane appears in FLEX PDF passages (BM25) but not PSI-69 core table -> related
        ev_rel = self.service.answer({"query": "n-decane burning rate PSI-69", "investigation_id": "PSI-69", "fuel": "n-Decane"})
        self.assertEqual(ev_rel["data"]["coverage"]["status"], "related")

        ev_none = self.service.answer({"fuel": "NoSuchFuel"})
        self.assertEqual(ev_none["data"]["coverage"]["status"], "no_match")
        self.assertEqual(ev_none["data"]["coverage"]["ui_label"], "NO MATCH IN INDEXED SOURCES")

    def test_export_csv_and_json_preserve_header_and_coverage(self) -> None:
        csv_out = build_export_payload(
            self.records,
            investigation_id="PSI-69",
            field_name="burning_rate_mm2_s",
            unit="mm²/s",
            export_format="csv",
        )
        lines = csv_out["content"].splitlines()
        self.assertTrue(lines[0].startswith("investigation_id,record_pk,"))
        self.assertIn("coverage_status", lines[0])
        self.assertIn("coverage_label", lines[0])
        self.assertIn("applied_tolerance", lines[0])

        json_out = build_export_payload(
            self.records,
            investigation_id="PSI-69",
            field_name="burning_rate_mm2_s",
            unit="mm²/s",
            export_format="json",
        )
        json_doc = json.loads(json_out["content"])
        self.assertEqual(json_doc["evidence_coverage"]["status"], "matching")
        self.assertIn("reported", json_doc["provenance_origin_types"])


if __name__ == "__main__":
    unittest.main()
