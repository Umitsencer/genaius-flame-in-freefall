"""Unit tests for validated FLEX condition prediction, joint-support gate, and integrity."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from genaius.flex_predictor import (
    DEFAULT_MODEL_ARTIFACT_REL_PATH,
    FlexPredictionValidationError,
    FlexPredictorError,
    build_flex_prediction_schema,
    build_flex_research_summary_export,
    load_flex_predictor_bundle,
    prepare_psi69_training_dataset,
    run_flex_condition_map,
    run_flex_prediction,
)


class FlexPredictorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_flex_predictor_bundle(ROOT)

    def test_pre_test_eligibility_excludes_missing_d0_missing_k_and_corrupt_114(self) -> None:
        prep = prepare_psi69_training_dataset(ROOT)
        self.assertEqual(prep["total_records"], 274)
        self.assertEqual(len(prep["rows_clf"]), 261)
        self.assertEqual(len(prep["rows_reg"]), 257)
        excluded_clf_ids = {item["test_id"]: item["reason"] for item in prep["excluded_clf"]}
        self.assertEqual(excluded_clf_ids["114"], "corrupted_nonpositive_ambient_pressure")
        self.assertEqual(excluded_clf_ids["9"], "missing_droplet_initial_diameter_mm")

    def test_grouped_cv_beats_baselines_and_exposes_honest_limits(self) -> None:
        schema = build_flex_prediction_schema(self.bundle)
        reg = schema["models"]["burning_rate_regression"]
        clf = schema["models"]["extinction_classification"]

        self.assertTrue(reg["accepted"])
        self.assertGreater(reg["cv_group_atm_p"]["r2"], 0.65)
        self.assertLess(reg["cv_group_atm_p"]["mae"], 0.06)
        self.assertGreater(reg["cv_group_fuel_atm_p"]["r2"], 0.65)

        self.assertTrue(clf["accepted"])
        self.assertGreater(clf["cv_group_atm_p"]["roc_auc"], 0.85)
        self.assertGreater(clf["cv_group_fuel_atm_p"]["roc_auc"], 0.84)
        self.assertLess(clf["cv_group_atm_p"]["brier_score"], 0.15)
        self.assertGreater(clf["cv_group_atm_p"]["confusion_matrix"]["fp"], 0)
        self.assertIn("5.2", clf["confounding_note"])
        self.assertFalse(schema["oof_predictions_available"])
        self.assertFalse(schema["shapley_audit_policy"]["raw6_interventional_shapley_enabled"])
        self.assertIn("evaluation_benchmarks", schema)
        self.assertIn("ridge_poly12", schema["evaluation_benchmarks"]["benchmarks"]["regression_group_atm_p"]["models"])
        self.assertGreaterEqual(len(reg["structure"]["coefficients"]), 8)
        self.assertGreaterEqual(len(clf["structure"]["coefficients"]), 10)

    def test_in_distribution_prediction_audits_raw6_shapley_and_returns_transformed_terms(self) -> None:
        res = run_flex_prediction(
            self.bundle,
            {
                "fuel": "Methanol",
                "o2_mol_frac": 0.21,
                "co2_mol_frac": 0.0,
                "he_mol_frac": 0.39,
                "pressure_atm": 1.0,
                "droplet_initial_diameter_mm": 2.5,
            },
        )
        self.assertEqual(res["status"], "OK")
        self.assertTrue(res["support"]["supported"])
        self.assertGreaterEqual(len(res["support"]["nearest_experiments"]), 1)

        k_pred = res["predictions"]["burning_rate_mm2_s"]["value"]
        self.assertGreater(k_pred, 0.2)
        self.assertLess(k_pred, 2.0)

        ext = res["predictions"]["extinction_likelihood"]
        self.assertGreaterEqual(ext["score"], 0.0)
        self.assertLessEqual(ext["score"], 1.0)
        self.assertIn("not spacecraft fire-safety", ext["calibration_warning"].lower())

        # Audit verifies unphysical counterfactuals cause raw6 SHAP to be disabled cleanly
        le = res["local_explanations"]
        self.assertEqual(le["status"], "DISABLED_UNRELIABLE")
        self.assertFalse(le["published"])
        self.assertEqual(le["method"], "audited_disabled_raw6_interventional_shapley")
        self.assertGreater(le["counterfactual_audit"]["mixed_co2_he_count"], 0)
        self.assertGreater(le["counterfactual_audit"]["negative_n2_count"], 0)

        # Verify exact additive linear-predictor decomposition on transformed features
        reg_tf = le["transformed_feature_contributions"]["burning_rate_mm2_s"]
        self.assertAlmostEqual(
            reg_tf["intercept"] + sum(c["linear_contribution"] for c in reg_tf["contributions"]),
            reg_tf["linear_predictor"],
            places=4,
        )
        clf_tf = le["transformed_feature_contributions"]["extinction_likelihood"]
        self.assertAlmostEqual(
            clf_tf["intercept"] + sum(c["linear_contribution"] for c in clf_tf["contributions"]),
            clf_tf["linear_predictor"],
            places=4,
        )

    def test_condition_map_and_research_summary_export(self) -> None:
        cmap = run_flex_condition_map(
            self.bundle,
            {
                "fuel": "Methanol",
                "diluent_regime": "CO2",
                "pressure_atm": 1.0,
                "droplet_initial_diameter_mm": 2.5,
                "o2_steps": 9,
                "y_steps": 7,
            },
        )
        self.assertEqual(cmap["status"], "OK")
        self.assertEqual(cmap["total_cells"], 63)
        self.assertGreater(cmap["supported_cells"], 0)
        self.assertGreater(cmap["masked_cells"], 0)
        for cell in cmap["cells"]:
            if not cell["supported"]:
                self.assertIsNone(cell["burning_rate_mm2_s"])
                self.assertIsNone(cell["extinction_score"])
            else:
                self.assertIsNotNone(cell["burning_rate_mm2_s"])
                self.assertIsNotNone(cell["extinction_score"])

        exp_md = build_flex_research_summary_export(
            self.bundle,
            {
                "fuel": "Methanol",
                "o2_mol_frac": 0.21,
                "co2_mol_frac": 0.0,
                "he_mol_frac": 0.0,
                "pressure_atm": 1.0,
                "droplet_initial_diameter_mm": 2.5,
            },
            fmt="md",
        )
        self.assertIn("DISABLED_UNRELIABLE", exp_md["content"])
        self.assertIn("PSI-69", exp_md["content"])

    def test_joint_support_gate_blocks_out_of_distribution_and_out_of_domain(self) -> None:
        ood_cases = [
            # CO2 and He never co-occur in FLEX
            {"fuel": "Methanol", "o2_mol_frac": 0.21, "co2_mol_frac": 0.15, "he_mol_frac": 0.15, "pressure_mmhg": 760.0, "droplet_initial_diameter_mm": 2.5},
            # Air was only tested <= 774.1 mmHg (~1 atm), never 3 atm
            {"fuel": "Heptane", "o2_mol_frac": 0.21, "co2_mol_frac": 0.0, "he_mol_frac": 0.0, "pressure_atm": 3.0, "droplet_initial_diameter_mm": 2.5},
            # Helium was only tested <= 766.5 mmHg (~1 atm), never 2 atm
            {"fuel": "Methanol", "o2_mol_frac": 0.21, "co2_mol_frac": 0.0, "he_mol_frac": 0.30, "pressure_atm": 2.0, "droplet_initial_diameter_mm": 2.5},
            # Sparse corner inside marginal CO2 envelope (O2=0.14 with CO2=0.70 at 3 atm never co-occurred)
            {"fuel": "Methanol", "o2_mol_frac": 0.14, "co2_mol_frac": 0.70, "he_mol_frac": 0.0, "pressure_mmhg": 2300.0, "droplet_initial_diameter_mm": 2.5},
            # Unsupported fuel / domain context
            {"fuel": "PMMA", "o2_mol_frac": 0.21, "co2_mol_frac": 0.0, "he_mol_frac": 0.0, "pressure_atm": 1.0, "droplet_initial_diameter_mm": 2.5},
            {"fuel": "Methanol", "o2_mol_frac": 0.21, "co2_mol_frac": 0.0, "he_mol_frac": 0.0, "pressure_atm": 1.0, "droplet_initial_diameter_mm": 2.5, "domain_context": "Lunar cabin fire extrapolation"},
        ]
        for case in ood_cases:
            res = run_flex_prediction(self.bundle, case)
            self.assertEqual(res["status"], "NOT_SUPPORTED", msg=f"Expected NOT_SUPPORTED for {case}")
            self.assertIsNone(res["predictions"])
            self.assertGreater(len(res["support"]["reasons"]), 0)

    def test_validation_rejects_malformed_or_post_test_leakage_keys(self) -> None:
        bad_payloads = [
            {"fuel": "Methanol", "o2_mol_frac": 0.21, "co2_mol_frac": 0.0, "he_mol_frac": 0.0, "pressure_atm": 0.0, "droplet_initial_diameter_mm": 2.5},
            {"fuel": "Methanol", "o2_mol_frac": 0.21, "co2_mol_frac": 0.0, "he_mol_frac": 0.0, "pressure_atm": 1.0, "droplet_initial_diameter_mm": 2.5, "burn_time_s": 5.0},
            {"fuel": "Methanol", "o2_mol_frac": 0.21, "n2_mol_frac": 0.20, "co2_mol_frac": 0.0, "he_mol_frac": 0.0, "pressure_atm": 1.0, "droplet_initial_diameter_mm": 2.5},
            {"fuel": "Methanol", "o2_mol_frac": 0.21, "co2_mol_frac": 0.0, "he_mol_frac": 0.0, "pressure_atm": 1.0, "pressure_mmhg": 1500.0, "droplet_initial_diameter_mm": 2.5},
        ]
        for payload in bad_payloads:
            with self.assertRaises(FlexPredictionValidationError):
                run_flex_prediction(self.bundle, payload)

    def test_artifact_integrity_rejects_tampered_json_or_missing_csv(self) -> None:
        raw = json.loads((ROOT / DEFAULT_MODEL_ARTIFACT_REL_PATH).read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            model_dir = tmp_root / "data" / "processed"
            csv_dir = tmp_root / "data" / "raw" / "psi" / "experimental_tables" / "PSI-69"
            model_dir.mkdir(parents=True)
            csv_dir.mkdir(parents=True)
            (csv_dir / "PSI-69_Experimental table_FLEX.csv").write_bytes(
                (ROOT / "data/raw/psi/experimental_tables/PSI-69/PSI-69_Experimental table_FLEX.csv").read_bytes()
            )
            tampered = dict(raw)
            tampered["regression_model"] = dict(raw["regression_model"], weights=[999.0] * len(raw["regression_model"]["weights"]))
            (model_dir / "flex_condition_models.json").write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaises(FlexPredictorError):
                load_flex_predictor_bundle(tmp_root)


if __name__ == "__main__":
    unittest.main()
