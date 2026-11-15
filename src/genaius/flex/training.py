"""FLEX model training and grouped-CV evaluation with scikit-learn (optional `train` extra).

Replaces the former hand-written Ridge normal equations, gradient-descent logistic
regression, CART/random-forest and metric code. What is *not* replaced, because it is
our evaluation protocol rather than a standard algorithm:

* the pre-test feature maps (`flex.model`, shared with runtime inference);
* `balanced_group_folds` — deterministic group→fold assignment balanced by target mean
  (the recorded v1 folds are in `data/processed/flex_cv_folds_v1.json`); it is NOT
  `GroupKFold`, and switching would silently change the evaluation protocol.

Pipelines are `feature map → StandardScaler (fit inside each training fold) → estimator`.
Penalty mapping (derived, not assumed): legacy Ridge minimised ||y−Xw−b||² + l2·||w||² on
standardised features → `Ridge(alpha=l2)` is the same objective. Legacy logistic used
(1/n)[Σ logloss + (l2/2)||w||²] but stopped after 2500 fixed gradient steps; the converged
optimum of that objective is `LogisticRegression(C=1/l2)`, so coefficients and scores differ
where the old optimiser had not converged. Trees/forests keep depth/leaf/feature limits but
use scikit-learn's RNG and tie-breaking, so they are not bit-identical either.

Runtime inference never imports this module: the exported JSON keeps the same
weights/means/stds layout as v1 and is evaluated by `flex.model`.
"""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

try:  # optional dependency group: pip install -r requirements-train.txt
    import numpy as np
    import sklearn
    from sklearn.base import BaseEstimator
    from sklearn.dummy import DummyClassifier, DummyRegressor
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.metrics import (
        accuracy_score,
        brier_score_loss,
        confusion_matrix,
        mean_absolute_error,
        precision_score,
        r2_score,
        recall_score,
        roc_auc_score,
        root_mean_squared_error,
    )
    from sklearn.model_selection import cross_val_predict
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import FunctionTransformer, StandardScaler
    from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor
except ImportError as exc:  # pragma: no cover - exercised only without the train extra
    raise ImportError(
        "FLEX training needs the optional 'train' dependencies: pip install -r requirements-train.txt"
    ) from exc

from .artifacts import _artifact_digest
from .common import (
    CALIBRATION_AND_SCOPE_DISCLAIMER,
    DEFAULT_EVAL_REPORT_REL_PATH,
    DEFAULT_MODEL_ARTIFACT_REL_PATH,
    MODEL_ARTIFACT_SCHEMA_VERSION,
    MODEL_VERSION,
    PSI69_CSV_REL_PATH,
)
from .dataset import FlexPreparedRow, _build_support_reference, prepare_psi69_training_dataset
from .model import _clf_phys10, _linear6_features, _poly12_features, _reg_phys8

SKLEARN_MODEL_VERSION = MODEL_VERSION
SKLEARN_MODEL_ARTIFACT_REL_PATH = DEFAULT_MODEL_ARTIFACT_REL_PATH
SKLEARN_EVAL_REPORT_REL_PATH = DEFAULT_EVAL_REPORT_REL_PATH
SEED = 42
N_FOLDS = 5

FeatureMap = Callable[[list[list[float]]], list[list[float]]]


def balanced_group_folds(groups: Sequence[str], y: Sequence[float], k: int = N_FOLDS) -> list[list[int]]:
    """Deterministic group-preserving folds balanced by per-group target mean (v1 protocol)."""
    grouped: dict[str, list[int]] = defaultdict(list)
    for idx, g in enumerate(groups):
        grouped[g].append(idx)
    ranked = sorted(
        ((sum(y[i] for i in idxs) / len(idxs), -len(idxs), g, idxs) for g, idxs in grouped.items()),
        key=lambda item: (item[0], item[1], item[2]),
    )
    folds: list[list[int]] = [[] for _ in range(k)]
    for pos, (_, _, _, idxs) in enumerate(ranked):
        block, slot = divmod(pos, k)
        folds[slot if block % 2 == 0 else (k - 1 - slot)].extend(idxs)
    return [sorted(f) for f in folds]


def _cv_splits(folds: list[list[int]], n: int) -> list[tuple[np.ndarray, np.ndarray]]:
    splits = []
    for test in folds:
        mask = np.ones(n, dtype=bool)
        mask[test] = False
        splits.append((np.flatnonzero(mask), np.asarray(test)))
    return splits


def _features(fn: FeatureMap) -> FunctionTransformer:
    # The same pure-Python feature maps the runtime uses: one definition of every feature.
    return FunctionTransformer(lambda X: np.asarray(fn(np.asarray(X).tolist()), dtype=float), validate=False)


def _linear(fn: FeatureMap, estimator: BaseEstimator) -> Pipeline:
    return Pipeline([("features", _features(fn)), ("scale", StandardScaler()), ("model", estimator)])


def _logit(fn: FeatureMap, l2: float) -> Pipeline:
    return _linear(fn, LogisticRegression(C=1.0 / l2, solver="lbfgs", max_iter=20000, tol=1e-10))


REGRESSION_SPECS: dict[str, tuple[Callable[[], BaseEstimator], float | None]] = {
    "dummy_mean": (lambda: DummyRegressor(strategy="mean"), None),
    "ridge_linear6": (lambda: _linear(_linear6_features, Ridge(alpha=1.0)), 1.0),
    "ridge_phys8": (lambda: _linear(_reg_phys8, Ridge(alpha=2.0)), 2.0),
    "ridge_poly12": (lambda: _linear(_poly12_features, Ridge(alpha=5.0)), 5.0),
    "tree_d4_leaf5": (lambda: DecisionTreeRegressor(max_depth=4, min_samples_leaf=5, random_state=SEED), None),
    "forest_80_d5": (
        lambda: RandomForestRegressor(n_estimators=80, max_depth=5, min_samples_leaf=5, max_features=4,
                                      bootstrap=True, random_state=SEED),
        None,
    ),
}
CLASSIFICATION_SPECS: dict[str, tuple[Callable[[], BaseEstimator], float | None]] = {
    "majority": (lambda: DummyClassifier(strategy="prior"), None),
    "logit_linear6": (lambda: _logit(_linear6_features, 1.0), 1.0),
    "logit_phys10": (lambda: _logit(_clf_phys10, 2.0), 2.0),
    "logit_poly12": (lambda: _logit(_poly12_features, 5.0), 5.0),
    "tree_d4_leaf5": (lambda: DecisionTreeClassifier(max_depth=4, min_samples_leaf=5, random_state=SEED), None),
    "forest_80_d5": (
        lambda: RandomForestClassifier(n_estimators=80, max_depth=5, min_samples_leaf=5, max_features=4,
                                       bootstrap=True, random_state=SEED),
        None,
    ),
}


def regression_metrics(y_true: Sequence[float], y_pred: Sequence[float]) -> dict[str, float]:
    return {
        "mae": round(float(mean_absolute_error(y_true, y_pred)), 4),
        "rmse": round(float(root_mean_squared_error(y_true, y_pred)), 4),
        "r2": round(float(r2_score(y_true, y_pred)), 4),
    }


def _auc(y_true: Sequence[int], y_prob: Sequence[float]) -> float | None:
    return round(float(roc_auc_score(y_true, y_prob)), 4) if len(set(y_true)) == 2 else None


def classification_metrics(
    y_true: Sequence[int], y_prob: Sequence[float], raw_ends: Sequence[str] | None = None
) -> dict[str, Any]:
    y_true = np.asarray(y_true, dtype=int)
    y_prob = np.asarray(y_prob, dtype=float)
    pred = (y_prob >= 0.5).astype(int)
    tn, fp, fn, tp = (int(v) for v in confusion_matrix(y_true, pred, labels=[0, 1]).ravel())
    out: dict[str, Any] = {
        "n": int(len(y_true)),
        "positive_extinction": int(y_true.sum()),
        "negative_non_extinction": int(len(y_true) - y_true.sum()),
        "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "accuracy": round(float(accuracy_score(y_true, pred)), 4),
        "precision": round(float(precision_score(y_true, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, pred, zero_division=0)), 4),
        "false_positive_rate_on_non_extinction": round(fp / (fp + tn), 4) if (fp + tn) else 0.0,
        "roc_auc": _auc(y_true.tolist(), y_prob.tolist()),
        "brier_score": round(float(brier_score_loss(y_true, y_prob)), 4),
    }
    if raw_ends is not None:
        ends = np.asarray(raw_ends)
        out["false_positives_by_true_end"] = {
            end: f"{int(((ends == end) & (pred == 1)).sum())}/{int((ends == end).sum())}"
            for end in ("Disruption", "Completion")
        }
    return out


def _oof_predictions(
    make: Callable[[], BaseEstimator], X: np.ndarray, y: np.ndarray, folds: list[list[int]], *, proba: bool
) -> np.ndarray:
    method = "predict_proba" if proba else "predict"
    pred = cross_val_predict(make(), X, y, cv=_cv_splits(folds, len(y)), method=method)
    return pred[:, 1] if proba else pred


def evaluate_regression_cv(rows: list[FlexPreparedRow], group_attr: str) -> dict[str, Any]:
    X = np.asarray([r.raw6() for r in rows], dtype=float)
    y = np.asarray([float(r.burning_rate_mm2_s) for r in rows], dtype=float)
    folds = balanced_group_folds([getattr(r, group_attr) for r in rows], y.tolist())
    models: dict[str, Any] = {}
    oof_all: dict[str, list[float]] = {}
    for name, (make, _l2) in REGRESSION_SPECS.items():
        oof = _oof_predictions(make, X, y, folds, proba=False)
        fold_r2 = [regression_metrics(y[f], oof[f])["r2"] for f in folds]
        models[name] = {**regression_metrics(y, oof), "fold_r2": fold_r2,
                        "fold_r2_std": round(float(np.std(fold_r2)), 4)}
        oof_all[name] = oof.tolist()
    return {"n": len(y), "unique_groups": len({getattr(r, group_attr) for r in rows}), "models": models,
            "_folds": folds, "_oof": oof_all}


def evaluate_classification_cv(rows: list[FlexPreparedRow], group_attr: str) -> dict[str, Any]:
    X = np.asarray([r.raw6() for r in rows], dtype=float)
    y = np.asarray([r.y_extinction for r in rows], dtype=int)
    ends = [r.test_end for r in rows]
    folds = balanced_group_folds([getattr(r, group_attr) for r in rows], y.tolist())
    models: dict[str, Any] = {}
    oof_all: dict[str, list[float]] = {}
    for name, (make, _l2) in CLASSIFICATION_SPECS.items():
        oof = _oof_predictions(make, X, y, folds, proba=True)
        fold_auc = [_auc(y[f].tolist(), oof[f].tolist()) for f in folds]
        valid = [v for v in fold_auc if v is not None]
        models[name] = {**classification_metrics(y, oof, raw_ends=ends), "fold_auc": fold_auc,
                        "fold_auc_std": round(float(np.std(valid)), 4) if valid else None}
        oof_all[name] = oof.tolist()
    return {"n": len(y), "unique_groups": len({getattr(r, group_attr) for r in rows}), "models": models,
            "_folds": folds, "_oof": oof_all}


def _export_linear(pipe: Pipeline, l2: float, n_train: int) -> dict[str, Any]:
    """Same JSON layout as v1: weights=[intercept, *coef] on standardised features."""
    scaler: StandardScaler = pipe.named_steps["scale"]
    est = pipe.named_steps["model"]
    coef = np.ravel(est.coef_)
    intercept = float(np.ravel([est.intercept_])[0])
    out = {
        "weights": [intercept, *(float(c) for c in coef)],
        "means": [float(m) for m in scaler.mean_],
        "stds": [float(s) for s in scaler.scale_],
        "l2": l2,
        "n_train": n_train,
    }
    if isinstance(est, Ridge):
        out["sklearn_estimator"] = {"class": "Ridge", "alpha": float(est.alpha)}
    else:
        out["sklearn_estimator"] = {"class": "LogisticRegression", "C": float(est.C), "solver": est.solver,
                                    "n_iter": int(np.ravel(est.n_iter_)[0])}
    return out


def _strip_private(cv: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in cv.items() if not k.startswith("_")}


def train_and_evaluate_flex_models(repo_root: str | Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Grouped-CV benchmarks + final fit. Returns (artifact, eval_report, cv_details)."""
    root = Path(repo_root).resolve()
    prep = prepare_psi69_training_dataset(root)
    rows_clf: list[FlexPreparedRow] = prep["rows_clf"]
    rows_reg: list[FlexPreparedRow] = prep["rows_reg"]

    cv = {
        "regression_group_atm_p": evaluate_regression_cv(rows_reg, "group_atm_p"),
        "regression_group_fuel_atm_p": evaluate_regression_cv(rows_reg, "group_fuel_atm_p"),
        "classification_group_atm_p": evaluate_classification_cv(rows_clf, "group_atm_p"),
        "classification_group_fuel_atm_p": evaluate_classification_cv(rows_clf, "group_fuel_atm_p"),
        "classification_sensitivity_excluding_disruption": evaluate_classification_cv(
            [r for r in rows_clf if r.test_end != "Disruption"], "group_atm_p"
        ),
    }

    X_reg_raw6 = [r.raw6() for r in rows_reg]
    y_reg = [float(r.burning_rate_mm2_s) for r in rows_reg]
    reg_pipe = REGRESSION_SPECS["ridge_phys8"][0]().fit(np.asarray(X_reg_raw6), np.asarray(y_reg))
    X_clf_raw6 = [r.raw6() for r in rows_clf]
    y_clf = [r.y_extinction for r in rows_clf]
    clf_pipe = CLASSIFICATION_SPECS["logit_phys10"][0]().fit(np.asarray(X_clf_raw6), np.asarray(y_clf))

    eligibility_summary = {
        "psi69_total_rows": prep["total_records"],
        "classification_usable_rows": len(rows_clf),
        "classification_excluded": prep["excluded_clf"],
        "regression_usable_rows": len(rows_reg),
        "regression_excluded": prep["excluded_reg"],
        "post_test_leakage_excluded": [
            "burn_time_s",
            "visible_flame_extinction_diameter_mm",
            "burning_rate_mm2_s",
            "test_end",
        ],
    }
    reg_cv = cv["regression_group_atm_p"]["models"]
    clf_cv = cv["classification_group_atm_p"]["models"]
    best_reg_baseline = max(reg_cv[m]["r2"] for m in ("dummy_mean", "tree_d4_leaf5", "forest_80_d5"))
    best_clf_baseline = max((clf_cv[m]["roc_auc"] or 0.0) for m in ("majority", "tree_d4_leaf5", "forest_80_d5"))
    library = {"scikit-learn": sklearn.__version__, "numpy": np.__version__}
    eval_report = {
        "schema_version": MODEL_ARTIFACT_SCHEMA_VERSION,
        "model_version": SKLEARN_MODEL_VERSION,
        "training_data_sha256": prep["csv_sha256"],
        "training_library": library,
        "eligibility": eligibility_summary,
        "acceptance_decisions": {
            # Candidate only: computed from this run, never copied from the v1 report.
            "burning_rate_regression": {
                "accepted": reg_cv["ridge_phys8"]["r2"] > best_reg_baseline,
                "selected_model": "ridge_phys8",
                "reason": (
                    f"Grouped-CV (atm+P) R² {reg_cv['ridge_phys8']['r2']} vs best dummy/tree/forest "
                    f"baseline {best_reg_baseline}."
                ),
            },
            "extinction_classification": {
                "accepted": (clf_cv["logit_phys10"]["roc_auc"] or 0.0) > best_clf_baseline,
                "selected_model": "logit_phys10",
                "reason": (
                    f"Grouped-CV (atm+P) ROC-AUC {clf_cv['logit_phys10']['roc_auc']} and Brier "
                    f"{clf_cv['logit_phys10']['brier_score']} vs best majority/tree/forest AUC {best_clf_baseline}; "
                    "calibration and disruption-confounding warnings still apply."
                ),
            },
        },
        "benchmarks": {name: _strip_private(view) for name, view in cv.items()},
    }
    artifact: dict[str, Any] = {
        "schema_version": MODEL_ARTIFACT_SCHEMA_VERSION,
        "model_version": SKLEARN_MODEL_VERSION,
        "training_data_path": PSI69_CSV_REL_PATH.as_posix(),
        "training_data_sha256": prep["csv_sha256"],
        "training_library": library,
        "disclaimer": CALIBRATION_AND_SCOPE_DISCLAIMER,
        "eligibility": eligibility_summary,
        "regression_model": {
            **_export_linear(reg_pipe, 2.0, len(y_reg)),
            "name": "ridge_phys8",
            "target": "burning_rate_mm2_s",
            "unit": "mm^2/s",
            "transformed_features": ["fuel_is_heptane", "o2", "co2", "he", "ln(P/760)", "d0", "o2*fuel", "he*fuel"],
            "accepted": eval_report["acceptance_decisions"]["burning_rate_regression"]["accepted"],
            "cv_group_atm_p": reg_cv["ridge_phys8"],
            "cv_group_fuel_atm_p": cv["regression_group_fuel_atm_p"]["models"]["ridge_phys8"],
        },
        "classification_model": {
            **_export_linear(clf_pipe, 2.0, len(y_clf)),
            "name": "logit_phys10",
            "target": "test_end == Extinction",
            "threshold": 0.5,
            "transformed_features": ["fuel_is_heptane", "o2", "co2", "he", "ln(P/760)", "d0", "o2*fuel",
                                     "co2*fuel", "he*fuel", "d0*fuel"],
            "accepted": eval_report["acceptance_decisions"]["extinction_classification"]["accepted"],
            "cv_group_atm_p": clf_cv["logit_phys10"],
            "cv_group_fuel_atm_p": cv["classification_group_fuel_atm_p"]["models"]["logit_phys10"],
            "cv_sensitivity_no_disruption": cv["classification_sensitivity_excluding_disruption"]["models"]["logit_phys10"],
        },
        "support_reference": _build_support_reference(rows_clf),
        "background_reg_raw6": X_reg_raw6,
        "background_clf_raw6": X_clf_raw6,
    }
    artifact["artifact_digest_sha256"] = _artifact_digest(artifact)
    details = {name: {"record_pks": [r.record_pk for r in (rows_reg if name.startswith("regression") else
                                                           ([r for r in rows_clf if r.test_end != "Disruption"]
                                                            if name.endswith("disruption") else rows_clf))],
                      "folds": view["_folds"], "oof": view["_oof"]}
               for name, view in cv.items()}
    return artifact, eval_report, details


def save_sklearn_candidate(repo_root: str | Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path, Path]:
    """Write the accepted v2 artifact/report (target-agnostic metrics); never touches the v1 files.

    Returns (artifact, report, legacy_cv_details, model_path, eval_path); the legacy details hold the
    target-balanced-fold OOF predictions used only for the 056 library-migration comparison.
    """
    root = Path(repo_root).resolve()
    artifact, report, _acc = build_accepted_artifact(root)
    _a, _r, details = train_and_evaluate_flex_models(root)
    model_path = root / SKLEARN_MODEL_ARTIFACT_REL_PATH
    eval_path = root / SKLEARN_EVAL_REPORT_REL_PATH
    model_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    eval_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return artifact, report, details, model_path, eval_path


# ---------------------------------------------------------------------------------------------
# Görev 058: target-agnostic grouped evaluation (acceptance protocol)
# ---------------------------------------------------------------------------------------------
# `balanced_group_folds` assigns groups to folds using the *target* mean, so its results are kept
# as a legacy model-selection view and are not treated as an independent test. The acceptance
# protocol below assigns whole condition groups to folds with sklearn `GroupKFold` (by group size
# only, never by target). Hyperparameters are either the fixed v1 values or chosen by an inner
# GroupKFold on the outer-training groups only, so tuning never sees the outer test fold.
#
# Acceptance rule (fixed before the run): the primary model must beat every baseline
# (dummy/tree/forest) on pooled outer R² (regression) and ROC-AUC (classification), and the
# classifier's Brier score must beat the majority baseline, under BOTH grouping schemes. The
# false-extinction count (Non-Extinction runs scored ≥ 0.5) is always reported.

from sklearn.model_selection import GroupKFold  # noqa: E402

ALPHA_GRID = (0.5, 1.0, 2.0, 5.0, 10.0)
C_GRID = (2.0, 1.0, 0.5, 0.2, 0.1)
INNER_FOLDS = 4


def _outer_splits(groups: Sequence[str]) -> list[tuple[np.ndarray, np.ndarray]]:
    return list(GroupKFold(n_splits=N_FOLDS).split(np.zeros(len(groups)), groups=np.asarray(groups)))


def _inner_select(make: Callable[[float], BaseEstimator], grid: Sequence[float], X: np.ndarray, y: np.ndarray,
                  groups: np.ndarray, *, proba: bool) -> float:
    inner = list(GroupKFold(n_splits=INNER_FOLDS).split(X, groups=groups))
    best, best_loss = grid[0], float("inf")
    for value in grid:
        pred = cross_val_predict(make(value), X, y, cv=inner, method="predict_proba" if proba else "predict")
        if proba:
            p = np.clip(pred[:, 1], 1e-12, 1 - 1e-12)
            loss = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
        else:
            loss = float(np.mean((y - pred) ** 2))
        if loss < best_loss - 1e-12:
            best, best_loss = value, loss
    return best


def _outer_predict(task: str, rows: list[FlexPreparedRow], group_attr: str) -> dict[str, Any]:
    X = np.asarray([r.raw6() for r in rows], dtype=float)
    groups = np.asarray([getattr(r, group_attr) for r in rows])
    if task == "regression":
        y = np.asarray([float(r.burning_rate_mm2_s) for r in rows])
        specs = {k: v[0] for k, v in REGRESSION_SPECS.items()}
        primary, feat, grid = "ridge_phys8", _reg_phys8, ALPHA_GRID
        tuned_make = lambda a: _linear(feat, Ridge(alpha=a))  # noqa: E731
    else:
        y = np.asarray([r.y_extinction for r in rows])
        specs = {k: v[0] for k, v in CLASSIFICATION_SPECS.items()}
        primary, feat, grid = "logit_phys10", _clf_phys10, C_GRID
        tuned_make = lambda c: _logit(feat, 1.0 / c)  # noqa: E731  (_logit takes l2 = 1/C)
    splits = _outer_splits(groups)
    oof = {name: np.zeros(len(y)) for name in [*specs, f"{primary}_nested_tuned"]}
    chosen: list[float] = []
    for train, test in splits:
        for name, make in specs.items():
            est = make().fit(X[train], y[train])
            oof[name][test] = est.predict_proba(X[test])[:, 1] if task == "classification" else est.predict(X[test])
        value = _inner_select(tuned_make, grid, X[train], y[train], groups[train], proba=task == "classification")
        chosen.append(value)
        est = tuned_make(value).fit(X[train], y[train])
        oof[f"{primary}_nested_tuned"][test] = (est.predict_proba(X[test])[:, 1] if task == "classification"
                                                else est.predict(X[test]))
    ends = [r.test_end for r in rows]
    models = {}
    for name, pred in oof.items():
        if task == "regression":
            fold = [regression_metrics(y[t], pred[t])["r2"] for _, t in splits]
            models[name] = {**regression_metrics(y, pred), "fold_r2": fold, "fold_r2_std": round(float(np.std(fold)), 4)}
        else:
            fold = [_auc(y[t].tolist(), pred[t].tolist()) for _, t in splits]
            valid = [v for v in fold if v is not None]
            models[name] = {**classification_metrics(y, pred, raw_ends=ends), "fold_auc": fold,
                            "fold_auc_std": round(float(np.std(valid)), 4) if valid else None}
    return {
        "n": int(len(y)), "unique_groups": int(len(set(groups))), "fold_assignment": "sklearn GroupKFold (group size only)",
        "models": models, "nested_selected_hyperparameter_per_fold": chosen,
        "hyperparameter_name": "alpha" if task == "regression" else "C",
        "_splits": [[int(i) for i in t] for _, t in splits],
    }


def evaluate_target_agnostic(repo_root: str | Path) -> dict[str, Any]:
    """Acceptance evaluation on target-agnostic group folds; returns views + decision."""
    prep = prepare_psi69_training_dataset(Path(repo_root).resolve())
    rows_clf, rows_reg = prep["rows_clf"], prep["rows_reg"]
    views = {
        "regression_group_atm_p": _outer_predict("regression", rows_reg, "group_atm_p"),
        "regression_group_fuel_atm_p": _outer_predict("regression", rows_reg, "group_fuel_atm_p"),
        "classification_group_atm_p": _outer_predict("classification", rows_clf, "group_atm_p"),
        "classification_group_fuel_atm_p": _outer_predict("classification", rows_clf, "group_fuel_atm_p"),
        "classification_sensitivity_excluding_disruption": _outer_predict(
            "classification", [r for r in rows_clf if r.test_end != "Disruption"], "group_atm_p"),
    }
    checks = []
    for name in ("regression_group_atm_p", "regression_group_fuel_atm_p"):
        m = views[name]["models"]
        best = max(m[b]["r2"] for b in ("dummy_mean", "tree_d4_leaf5", "forest_80_d5"))
        checks.append({"view": name, "metric": "r2", "primary": m["ridge_phys8"]["r2"], "best_baseline": best,
                       "pass": m["ridge_phys8"]["r2"] > best})
    for name in ("classification_group_atm_p", "classification_group_fuel_atm_p"):
        m = views[name]["models"]
        best = max((m[b]["roc_auc"] or 0.0) for b in ("majority", "tree_d4_leaf5", "forest_80_d5"))
        checks.append({"view": name, "metric": "roc_auc", "primary": m["logit_phys10"]["roc_auc"], "best_baseline": best,
                       "pass": (m["logit_phys10"]["roc_auc"] or 0.0) > best})
        checks.append({"view": name, "metric": "brier_score", "primary": m["logit_phys10"]["brier_score"],
                       "best_baseline": m["majority"]["brier_score"],
                       "pass": m["logit_phys10"]["brier_score"] < m["majority"]["brier_score"]})
    critical = {name: {"false_extinction_fp": views[name]["models"]["logit_phys10"]["confusion_matrix"]["fp"],
                       "non_extinction_runs": views[name]["models"]["logit_phys10"]["negative_non_extinction"],
                       "rate": views[name]["models"]["logit_phys10"]["false_positive_rate_on_non_extinction"],
                       "by_true_end": views[name]["models"]["logit_phys10"].get("false_positives_by_true_end")}
                for name in views if name.startswith("classification")}
    return {"views": views, "acceptance_checks": checks, "accepted": all(c["pass"] for c in checks),
            "critical_false_extinction": critical, "training_data_sha256": prep["csv_sha256"]}


def build_accepted_artifact(repo_root: str | Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """v2 artifact whose stored metrics come from the target-agnostic protocol (never copied from v1).

    Weights are the full-data fit of the fixed v1 hyperparameters (alpha=2, C=0.5); the nested
    inner-CV choice is reported alongside to show the fixed values were not tuned on test folds.
    Raises if the pre-declared acceptance rule fails, so a rejected model can never be activated.
    """
    root = Path(repo_root).resolve()
    artifact, legacy_report, _details = train_and_evaluate_flex_models(root)
    acc = evaluate_target_agnostic(root)
    if not acc["accepted"]:
        raise RuntimeError("FLEX v2 candidate failed the target-agnostic acceptance rule; not activated.")
    if acc["training_data_sha256"] != artifact["training_data_sha256"]:
        raise RuntimeError("Training data changed between fit and evaluation.")
    views = {name: {k: v for k, v in view.items() if not k.startswith("_")} for name, view in acc["views"].items()}
    clf_atm = views["classification_group_atm_p"]["models"]["logit_phys10"]
    fp_end = clf_atm.get("false_positives_by_true_end", {})
    disclaimer = (
        "Trained exclusively on NASA/PSI-69 FLEX single free-floating droplet microgravity tests (Methanol and "
        "Heptane only), pre-test inputs only. The extinction score reflects empirical test frequency against "
        "Completion + Disruption; it is NOT a calibrated spacecraft fire-safety probability. On target-agnostic "
        f"grouped CV (GroupKFold over O2/diluent/pressure groups) it scores {clf_atm['confusion_matrix']['fp']} of "
        f"{clf_atm['negative_non_extinction']} Non-Extinction tests as Extinction "
        f"({clf_atm['false_positive_rate_on_non_extinction']:.0%}; Disruption {fp_end.get('Disruption')}, "
        f"Completion {fp_end.get('Completion')}). Local Shapley contributions reflect observational association, "
        "not causal proof."
    )
    reg_views = (views["regression_group_atm_p"]["models"], views["regression_group_fuel_atm_p"]["models"])
    clf_views = (views["classification_group_atm_p"]["models"], views["classification_group_fuel_atm_p"]["models"],
                 views["classification_sensitivity_excluding_disruption"]["models"])
    artifact["disclaimer"] = disclaimer
    artifact["evaluation_protocol"] = "target_agnostic_groupkfold_v1"
    artifact["regression_model"].update(accepted=True, cv_group_atm_p=reg_views[0]["ridge_phys8"],
                                        cv_group_fuel_atm_p=reg_views[1]["ridge_phys8"])
    artifact["classification_model"].update(accepted=True, cv_group_atm_p=clf_views[0]["logit_phys10"],
                                            cv_group_fuel_atm_p=clf_views[1]["logit_phys10"],
                                            cv_sensitivity_no_disruption=clf_views[2]["logit_phys10"])
    artifact["artifact_digest_sha256"] = _artifact_digest(artifact)
    report = {
        "schema_version": MODEL_ARTIFACT_SCHEMA_VERSION,
        "model_version": SKLEARN_MODEL_VERSION,
        "training_data_sha256": artifact["training_data_sha256"],
        "training_library": artifact["training_library"],
        "evaluation_protocol": "target_agnostic_groupkfold_v1",
        "eligibility": legacy_report["eligibility"],
        "acceptance_decisions": {
            "rule": ("Primary model must beat dummy/tree/forest on pooled outer R² (regression) and ROC-AUC "
                     "(classification) and beat the majority Brier score, under both grouping schemes."),
            "checks": acc["acceptance_checks"],
            "accepted": True,
            "burning_rate_regression": {"accepted": True, "selected_model": "ridge_phys8",
                                        "reason": "Passed target-agnostic grouped-CV acceptance checks."},
            "extinction_classification": {"accepted": True, "selected_model": "logit_phys10",
                                          "reason": "Passed checks; false-extinction rate reported as a mandatory caveat."},
        },
        "critical_false_extinction": acc["critical_false_extinction"],
        "grouping_note": (
            "Folds assign whole O2/diluent/pressure (atm+P) or fuel+atm+P condition groups with sklearn GroupKFold, "
            "which never looks at the target. Hyperparameters are fixed (alpha=2, C=0.5); a nested inner GroupKFold "
            "choice per outer fold is reported for comparison. This is internal grouped cross-validation on PSI-69, "
            "not external validation."
        ),
        "benchmarks": views,
        "legacy_target_balanced_folds": {
            "note": "Folds assigned by per-group target mean (Görev 049 protocol). Kept for traceability only; "
                    "not an independent test.",
            "benchmarks": legacy_report["benchmarks"],
        },
    }
    return artifact, report, acc
