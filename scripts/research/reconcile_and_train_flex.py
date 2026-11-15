"""Reproducible CLI for PSI-69 vs NASA/TP-2015-216046 reconciliation and FLEX model training.

Usage (training needs `pip install -r requirements-train.txt`):
    python scripts/research/reconcile_and_train_flex.py --repo-root .

Since Görev 056 training uses scikit-learn and writes the *candidate* artifact
(`flex_condition_models_v2_sklearn.json`); the active v1 artifact is only verified, never
overwritten. Use scripts/research/compare_flex_sklearn.py for the v1-vs-v2 comparison.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap_src(repo_root: Path) -> None:
    src_dir = repo_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile FLEX Table IX vs PSI-69 and train/evaluate FLEX models.")
    parser.add_argument("--repo-root", default=".", help="Workspace root directory containing data/ and src/.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON summary to stdout.")
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve()
    _bootstrap_src(root)

    from genaius.flex_reconciliation import save_flex_reconciliation
    from genaius.flex.artifacts import load_flex_predictor_bundle
    from genaius.flex.training import (
        SKLEARN_EVAL_REPORT_REL_PATH,
        SKLEARN_MODEL_ARTIFACT_REL_PATH,
        save_sklearn_candidate,
    )

    recon, recon_path = save_flex_reconciliation(root)
    artifact, report, _details, model_path, eval_path = save_sklearn_candidate(root)
    load_flex_predictor_bundle(root)  # active v1 artifact must still verify
    verified = load_flex_predictor_bundle(
        root, model_rel_path=SKLEARN_MODEL_ARTIFACT_REL_PATH, eval_rel_path=SKLEARN_EVAL_REPORT_REL_PATH
    )

    summary = {
        "reconciliation_path": str(recon_path),
        "reconciliation_summary": recon["reconciliation_summary"],
        "model_artifact_path": str(model_path),
        "eval_report_path": str(eval_path),
        "artifact_digest_sha256": verified["artifact_digest_sha256"],
        "training_data_sha256": verified["training_data_sha256"],
        "acceptance_decisions": report["acceptance_decisions"],
        "regression_ridge_phys8_atm_p": artifact["regression_model"]["cv_group_atm_p"],
        "regression_ridge_phys8_fuel_atm_p": artifact["regression_model"]["cv_group_fuel_atm_p"],
        "classification_logit_phys10_atm_p": artifact["classification_model"]["cv_group_atm_p"],
        "classification_logit_phys10_fuel_atm_p": artifact["classification_model"]["cv_group_fuel_atm_p"],
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Reconciliation written: {recon_path}")
        print(
            f"  PSI-69 CSV={recon['reconciliation_summary']['psi69_csv_rows']} (He={recon['reconciliation_summary']['psi69_helium_runs']}) vs "
            f"Table IX={recon['reconciliation_summary']['table_ix_rows']} (He={recon['reconciliation_summary']['table_ix_helium_runs']}); "
            f"TP-only={recon['reconciliation_summary']['table_ix_only_labels']}; "
            f"shared mismatches={recon['reconciliation_summary']['shared_row_value_mismatches']}"
        )
        print(f"Model artifact written: {model_path} (sha256={verified['artifact_digest_sha256'][:16]}...)")
        print(f"Evaluation report written: {eval_path}")
        reg_m = artifact["regression_model"]["cv_group_atm_p"]
        clf_m = artifact["classification_model"]["cv_group_atm_p"]
        print(f"  Regression (ridge_phys8, atm+P CV): R2={reg_m['r2']}, MAE={reg_m['mae']}, RMSE={reg_m['rmse']}")
        print(
            f"  Classification (logit_phys10, atm+P CV): AUC={clf_m['roc_auc']}, Acc={clf_m['accuracy']}, "
            f"Brier={clf_m['brier_score']}, FP={clf_m['confusion_matrix']['fp']}/{clf_m['negative_non_extinction']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
