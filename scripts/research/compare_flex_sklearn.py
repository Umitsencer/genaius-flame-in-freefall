"""Train the scikit-learn FLEX candidate and compare it with the v1 reference on identical splits.

    python scripts/research/compare_flex_sklearn.py --repo-root .

Requires `pip install -r requirements-train.txt`. Writes (never overwrites v1):
  data/processed/flex_condition_models_v2_sklearn.json
  data/processed/flex_eval_report_v2_sklearn.json
  data/processed/flex_sklearn_migration_comparison.json
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

LEGACY_OOF_REL = Path("data/processed/flex_cv_oof_v1.json")
COMPARISON_REL = Path("data/processed/flex_sklearn_migration_comparison.json")
PRIMARY = {"regression": "ridge_phys8", "classification": "logit_phys10"}


def _grid() -> list[dict]:
    out = []
    for fuel, o2, co2, he, p, d0 in itertools.product(
        ["Heptane", "Methanol"], [0.14, 0.18, 0.21, 0.3, 0.4], [0.0, 0.2], [0.0, 0.3], [0.7, 1.0, 2.0], [2.0, 3.0, 4.0]
    ):
        if o2 + co2 + he <= 1:
            out.append({"fuel": fuel, "o2_mol_frac": o2, "co2_mol_frac": co2, "he_mol_frac": he,
                        "pressure_atm": p, "droplet_initial_diameter_mm": d0})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    args = ap.parse_args(argv)
    root = Path(args.repo_root).resolve()
    sys.path.insert(0, str(root / "src"))

    from genaius.flex.artifacts import load_flex_predictor_bundle
    from genaius.flex.inference import run_flex_prediction
    from genaius.flex.training import (
        SKLEARN_EVAL_REPORT_REL_PATH,
        SKLEARN_MODEL_ARTIFACT_REL_PATH,
        classification_metrics,
        regression_metrics,
        save_sklearn_candidate,
    )

    from genaius.flex.common import LEGACY_V1_EVAL_REPORT_REL_PATH, LEGACY_V1_MODEL_ARTIFACT_REL_PATH

    v1 = load_flex_predictor_bundle(root, model_rel_path=LEGACY_V1_MODEL_ARTIFACT_REL_PATH,
                                    eval_rel_path=LEGACY_V1_EVAL_REPORT_REL_PATH)
    v1_report = v1["_eval_report"]
    legacy = json.loads((root / LEGACY_OOF_REL).read_text(encoding="utf-8"))["views"]
    _artifact, v2_report, details, model_path, eval_path = save_sklearn_candidate(root)
    v2 = load_flex_predictor_bundle(root, model_rel_path=SKLEARN_MODEL_ARTIFACT_REL_PATH,
                                    eval_rel_path=SKLEARN_EVAL_REPORT_REL_PATH)

    views: dict[str, dict] = {}
    for view, new in details.items():
        old = legacy[view]
        if old["record_pks"] != new["record_pks"] or old["folds"] != new["folds"]:
            raise SystemExit(f"{view}: records/folds differ from the v1 protocol; comparison invalid.")
        y = old["y"]
        task = "regression" if view.startswith("regression") else "classification"
        per_model = {}
        for name, old_pred in old["oof"].items():
            new_pred = new["oof"][name]
            diffs = [abs(a - b) for a, b in zip(old_pred, new_pred)]
            entry = {
                "v1_reported": v1_report["benchmarks"][view]["models"][name],
                "v1_recomputed_from_saved_oof": (regression_metrics(y, old_pred) if task == "regression"
                                                 else classification_metrics(y, old_pred)),
                "v2_sklearn": v2_report["legacy_target_balanced_folds"]["benchmarks"][view]["models"][name],
                "oof_abs_diff_max": round(max(diffs), 6),
                "oof_abs_diff_mean": round(sum(diffs) / len(diffs), 6),
            }
            if task == "classification":
                flips = [pk for pk, a, b in zip(old["record_pks"], old_pred, new_pred) if (a >= 0.5) != (b >= 0.5)]
                old_fp = {pk for pk, t, a in zip(old["record_pks"], y, old_pred) if t == 0 and a >= 0.5}
                new_fp = {pk for pk, t, b in zip(old["record_pks"], y, new_pred) if t == 0 and b >= 0.5}
                old_fn = {pk for pk, t, a in zip(old["record_pks"], y, old_pred) if t == 1 and a < 0.5}
                new_fn = {pk for pk, t, b in zip(old["record_pks"], y, new_pred) if t == 1 and b < 0.5}
                entry["decision_flips"] = flips
                entry["false_extinction_fp"] = {"v1": len(old_fp), "v2": len(new_fp),
                                                "new_in_v2": sorted(new_fp - old_fp), "resolved_in_v2": sorted(old_fp - new_fp)}
                entry["missed_extinction_fn"] = {"v1": len(old_fn), "v2": len(new_fn),
                                                 "new_in_v2": sorted(new_fn - old_fn), "resolved_in_v2": sorted(old_fn - new_fn)}
            per_model[name] = entry
        views[view] = {"n": len(y), "primary_model": PRIMARY[task], "models": per_model}

    # Final fitted models: coefficient deltas and runtime-inference deltas on the same inputs.
    coef = {}
    for key in ("regression_model", "classification_model"):
        w1, w2 = v1[key]["weights"], v2[key]["weights"]
        coef[key] = {"v1_weights": w1, "v2_weights": w2,
                     "max_abs_weight_diff": round(max(abs(a - b) for a, b in zip(w1, w2)), 6),
                     "v2_estimator": v2[key].get("sklearn_estimator")}
    grid = _grid()
    k_diff, s_diff, status_flips, label_flips = [], [], 0, 0
    for cond in grid:
        a, b = run_flex_prediction(v1, cond), run_flex_prediction(v2, cond)
        status_flips += a["status"] != b["status"]
        if a["status"] == b["status"] == "OK":
            ka, kb = a["predictions"]["burning_rate_mm2_s"]["value"], b["predictions"]["burning_rate_mm2_s"]["value"]
            sa, sb = a["predictions"]["extinction_likelihood"]["score"], b["predictions"]["extinction_likelihood"]["score"]
            k_diff.append(abs(ka - kb))
            s_diff.append(abs(sa - sb))
            label_flips += a["predictions"]["extinction_likelihood"]["predicted_label"] != b["predictions"]["extinction_likelihood"]["predicted_label"]
    comparison = {
        "purpose": "Library-migration check on the legacy (target-balanced) folds; see flex_acceptance_v2.json for the target-agnostic acceptance that activated v2.",
        "v1_model_version": v1["model_version"],
        "v2_model_version": v2["model_version"],
        "v2_training_library": v2.get("training_library"),
        "same_records_and_folds": True,
        "cv_views": views,
        "final_model_coefficients": coef,
        "runtime_inference_grid": {
            "conditions": len(grid),
            "support_status_flips": status_flips,
            "ok_in_both": len(k_diff),
            "burning_rate_abs_diff_max": round(max(k_diff), 6) if k_diff else None,
            "extinction_score_abs_diff_max": round(max(s_diff), 6) if s_diff else None,
            "extinction_label_flips": label_flips,
        },
    }
    (root / COMPARISON_REL).write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    print(f"v2 artifact: {model_path}\nv2 report: {eval_path}\ncomparison: {root / COMPARISON_REL}")
    for view, data in views.items():
        m = data["models"][data["primary_model"]]
        keys = ("r2", "mae", "rmse") if view.startswith("regression") else ("roc_auc", "brier_score", "accuracy")
        print(view, data["primary_model"], {k: (m["v1_reported"][k], m["v2_sklearn"][k]) for k in keys})
    print("grid:", comparison["runtime_inference_grid"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
