"""scikit-learn FLEX eğitimi (Görev 056): aynı protokol, aynı split, v1'in üzerine yazmama.

Eğitim bağımlılıkları (requirements-train.txt) yoksa testler atlanır; çalışma zamanı testleri
scikit-learn gerektirmez.
"""
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HAS_TRAIN = importlib.util.find_spec("sklearn") is not None and importlib.util.find_spec("numpy") is not None
PSI69 = ROOT / "data/raw/psi/experimental_tables/PSI-69/PSI-69_Experimental table_FLEX.csv"


class RuntimeIsolationTests(unittest.TestCase):
    def test_runtime_never_imports_ml_libraries(self):
        code = (
            "import sys; sys.path.insert(0, %r); import genaius.app_service, genaius.api.app, genaius.flex_predictor; "
            "print(int('sklearn' in sys.modules), int('numpy' in sys.modules))" % str(ROOT / "src")
        )
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(out, ["0", "0"])

    def test_no_pickle_model_files_are_shipped(self):
        found = [p for ext in ("*.pkl", "*.pickle", "*.joblib") for p in (ROOT / "data").rglob(ext)]
        self.assertEqual(found, [])


@unittest.skipUnless(HAS_TRAIN, "train extra (scikit-learn, numpy) not installed")
@unittest.skipUnless(PSI69.is_file(), "PSI-69 raw CSV not downloaded")
class SklearnTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from genaius.flex.training import train_and_evaluate_flex_models

        cls.artifact, cls.report, cls.details = train_and_evaluate_flex_models(ROOT)
        cls.v1_report = json.loads((ROOT / "data/processed/flex_eval_report.json").read_text(encoding="utf-8"))  # legacy v1
        cls.legacy = json.loads((ROOT / "data/processed/flex_cv_oof_v1.json").read_text(encoding="utf-8"))["views"]

    def test_same_records_and_folds_as_v1_protocol(self):
        for view, new in self.details.items():
            with self.subTest(view=view):
                self.assertEqual(new["record_pks"], self.legacy[view]["record_pks"])
                self.assertEqual(new["folds"], self.legacy[view]["folds"])

    def test_selected_linear_models_reproduce_v1_cv_metrics(self):
        reg_keys = ("mae", "rmse", "r2")
        clf_keys = ("roc_auc", "brier_score", "accuracy", "confusion_matrix", "false_positive_rate_on_non_extinction")
        for view, bench in self.report["benchmarks"].items():
            name, keys = ("ridge_phys8", reg_keys) if view.startswith("regression") else ("logit_phys10", clf_keys)
            old = self.v1_report["benchmarks"][view]["models"][name]
            new = bench["models"][name]
            for key in keys:
                with self.subTest(view=view, metric=key):
                    if isinstance(old[key], float):
                        self.assertAlmostEqual(new[key], old[key], delta=1e-3)
                    else:
                        self.assertEqual(new[key], old[key])

    def test_active_v2_is_versioned_apart_from_preserved_v1_and_uses_runtime_json_layout(self):
        # Görev 058 activated v2; v1 stays on disk under its own version/path and is never overwritten.
        from genaius.flex.common import (LEGACY_V1_MODEL_ARTIFACT_REL_PATH, LEGACY_V1_MODEL_VERSION,
                                         MODEL_VERSION)
        from genaius.flex.training import SKLEARN_MODEL_ARTIFACT_REL_PATH

        self.assertNotEqual(MODEL_VERSION, LEGACY_V1_MODEL_VERSION)
        self.assertNotEqual(SKLEARN_MODEL_ARTIFACT_REL_PATH, LEGACY_V1_MODEL_ARTIFACT_REL_PATH)
        v1 = json.loads((ROOT / LEGACY_V1_MODEL_ARTIFACT_REL_PATH).read_text(encoding="utf-8"))
        self.assertEqual(v1["model_version"], LEGACY_V1_MODEL_VERSION)
        for key in ("regression_model", "classification_model"):
            self.assertEqual(len(self.artifact[key]["weights"]), len(v1[key]["weights"]))
            self.assertEqual(len(self.artifact[key]["means"]), len(v1[key]["means"]))
        self.assertIn("scikit-learn", self.artifact["training_library"])

if __name__ == "__main__":
    unittest.main()
