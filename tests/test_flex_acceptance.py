"""Görev 058 FLEX kabulü: hedefe bakmayan grup değerlendirmesi, aktif sürüm tutarlılığı."""
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HAS_TRAIN = importlib.util.find_spec("sklearn") is not None
PSI69 = ROOT / "data/raw/psi/experimental_tables/PSI-69/PSI-69_Experimental table_FLEX.csv"


@unittest.skipUnless(PSI69.is_file(), "PSI-69 raw CSV not downloaded")
class ActiveArtifactConsistencyTests(unittest.TestCase):
    def test_active_weights_metrics_and_disclaimer_belong_to_one_version(self):
        from genaius.flex.artifacts import load_flex_predictor_bundle
        from genaius.flex.common import MODEL_VERSION
        from genaius.flex.inference import build_flex_prediction_schema

        bundle = load_flex_predictor_bundle(ROOT)
        report = bundle["_eval_report"]
        self.assertEqual(bundle["model_version"], MODEL_VERSION)
        self.assertEqual(report["model_version"], MODEL_VERSION)
        self.assertEqual(bundle["evaluation_protocol"], report["evaluation_protocol"])
        clf = bundle["classification_model"]
        # UI metrics come from the same report as the weights (never copied from v1).
        self.assertEqual(clf["cv_group_atm_p"], report["benchmarks"]["classification_group_atm_p"]["models"]["logit_phys10"])
        fp = clf["cv_group_atm_p"]["confusion_matrix"]["fp"]
        self.assertIn(f"{fp} of", bundle["disclaimer"])
        v1 = json.loads((ROOT / "data/processed/flex_eval_report.json").read_text(encoding="utf-8"))
        self.assertNotEqual(report["benchmarks"]["classification_group_atm_p"],
                            v1["benchmarks"]["classification_group_atm_p"])
        schema = build_flex_prediction_schema(bundle)
        self.assertEqual(schema["model_version"], MODEL_VERSION)
        self.assertIn("GroupKFold", schema["evaluation_benchmarks"]["grouping_note"])

    def test_acceptance_record_matches_active_artifact(self):
        acc = json.loads((ROOT / "data/processed/flex_acceptance_v2.json").read_text(encoding="utf-8"))
        art = json.loads((ROOT / "data/processed/flex_condition_models_v2_sklearn.json").read_text(encoding="utf-8"))
        self.assertTrue(acc["accepted"])
        self.assertTrue(all(c["pass"] for c in acc["acceptance_checks"]))
        self.assertEqual(acc["active_artifact_digest_sha256"], art["artifact_digest_sha256"])
        self.assertIn("classification_group_atm_p", acc["critical_false_extinction"])


@unittest.skipUnless(HAS_TRAIN and PSI69.is_file(), "train extra or PSI-69 CSV missing")
class TargetAgnosticProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from genaius.flex.training import evaluate_target_agnostic

        cls.acc = evaluate_target_agnostic(ROOT)

    def test_folds_are_group_disjoint_and_do_not_depend_on_target(self):
        from genaius.flex.dataset import prepare_psi69_training_dataset
        from genaius.flex.training import _outer_splits

        rows = prepare_psi69_training_dataset(ROOT)["rows_clf"]
        groups = [r.group_atm_p for r in rows]
        splits = _outer_splits(groups)
        # Same groups with shuffled targets must give identical folds (assignment ignores y).
        self.assertEqual([list(t) for _, t in splits], [list(t) for _, t in _outer_splits(list(groups))])
        for train, test in splits:
            self.assertFalse({groups[i] for i in train} & {groups[i] for i in test})

    def test_primary_models_pass_and_critical_errors_are_reported(self):
        self.assertTrue(self.acc["accepted"])
        crit = self.acc["critical_false_extinction"]["classification_group_atm_p"]
        self.assertGreater(crit["false_extinction_fp"], 0)
        self.assertIn("Completion", crit["by_true_end"])


if __name__ == "__main__":
    unittest.main()
