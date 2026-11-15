"""FLEX inference: input validation, joint-support gating, Shapley explanations, condition map."""

from __future__ import annotations

import math
from typing import Any, Callable

from ..schemas.requests import FlexConditionIn, FlexConditionMapIn, parse_request
from .common import (
    FlexPredictionValidationError,
    GAS_SUM_MAX,
    GAS_SUM_MIN,
    MMHG_PER_ATM,
    MMHG_PER_KPA,
    RAW_INPUT_LABELS,
    RAW_INPUT_NAMES,
    SUPPORTED_FUELS,
    _FORBIDDEN_DOMAIN_TERMS,
    _diluent_regime,
)
from .model import (
    _clf_phys10,
    _predict_logistic_probs_and_logits,
    _predict_ridge,
    _reg_phys8,
)


def _normalize_fuel(raw: str) -> str:
    fuel_clean = raw.strip()
    lowered = fuel_clean.lower()
    if lowered == "methanol":
        return "Methanol"
    if lowered in {"heptane", "n-heptane"}:
        return "Heptane"
    return fuel_clean


def _pressure_mmhg(cond: Any) -> float:
    """Exactly one pressure value (or several that agree within 2 mmHg), converted to mmHg."""
    converted = [
        val * factor
        for val, factor in (
            (cond.pressure_mmhg, 1.0),
            (cond.pressure_atm, MMHG_PER_ATM),
            (cond.pressure_kpa, MMHG_PER_KPA),
        )
        if val is not None
    ]
    if not converted:
        raise FlexPredictionValidationError(
            "One pressure field is required: pressure_mmhg, pressure_atm, or pressure_kpa."
        )
    if len(converted) > 1 and max(abs(converted[0] - other) for other in converted[1:]) > 2.0:
        raise FlexPredictionValidationError("Multiple pressure units supplied with conflicting values.")
    return converted[0]


def validate_prediction_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Shape/type/bounds via `FlexConditionIn`; FLEX gas-balance and pressure rules here."""
    cond = parse_request(FlexConditionIn, payload, error_cls=FlexPredictionValidationError)
    o2, co2, he = cond.o2_mol_frac, cond.co2_mol_frac, cond.he_mol_frac
    if cond.n2_mol_frac is None:
        n2 = round(1.0 - (o2 + co2 + he), 6)
        if (o2 + co2 + he) > GAS_SUM_MAX:
            raise FlexPredictionValidationError(
                f"o2 + co2 + he exceeds {GAS_SUM_MAX}; N2 balance would be negative."
            )
    else:
        n2 = cond.n2_mol_frac
    gas_sum = o2 + n2 + co2 + he
    if cond.n2_mol_frac is not None and not (GAS_SUM_MIN <= gas_sum <= GAS_SUM_MAX):
        raise FlexPredictionValidationError(
            f"o2 + n2 + co2 + he must sum within [{GAS_SUM_MIN}, {GAS_SUM_MAX}]; got {gas_sum:.4f}."
        )
    return {
        "fuel": _normalize_fuel(cond.fuel),
        "o2_mol_frac": o2,
        "co2_mol_frac": co2,
        "he_mol_frac": he,
        "n2_mol_frac": n2,
        "gas_sum": round(gas_sum, 4),
        "pressure_mmhg": round(_pressure_mmhg(cond), 4),
        "droplet_initial_diameter_mm": cond.droplet_initial_diameter_mm,
        "diluent_regime": _diluent_regime(co2, he),
        "domain_context": cond.domain_context.strip() if cond.domain_context is not None else None,
    }


def _standardized_distance(
    parsed: dict[str, Any],
    ref_run: dict[str, Any],
    stds: list[float],
) -> float:
    q = [
        parsed["o2_mol_frac"],
        parsed["co2_mol_frac"],
        parsed["he_mol_frac"],
        parsed["pressure_mmhg"],
        parsed["droplet_initial_diameter_mm"],
    ]
    r = [
        ref_run["o2_mol_frac"],
        ref_run["co2_mol_frac"],
        ref_run["he_mol_frac"],
        ref_run["pressure_mmhg"],
        ref_run["droplet_initial_diameter_mm"],
    ]
    return math.sqrt(sum(((q[j] - r[j]) / stds[j]) ** 2 for j in range(5)))


def check_flex_support(bundle: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    """Evaluate hard domain rules and joint experimental support against PSI-69 runs."""
    reasons: list[str] = []
    ctx = (parsed.get("domain_context") or "").lower()
    if any(term in ctx for term in _FORBIDDEN_DOMAIN_TERMS):
        reasons.append(
            "out_of_domain_context: models apply strictly to NASA FLEX free-floating Methanol/Heptane droplets in microgravity (never BASS-II solids, SAFFIRE, Lunar/Mars gravity, or spacecraft cabin fires)."
        )

    fuel = parsed["fuel"]
    if fuel not in SUPPORTED_FUELS:
        reasons.append(f"unsupported_fuel: '{fuel}' is outside tested PSI-69 fuels {list(SUPPORTED_FUELS)}.")

    if parsed["co2_mol_frac"] > 0.0 and parsed["he_mol_frac"] > 0.0:
        reasons.append("unsupported_mixed_diluents: zero NASA FLEX tests combine CO2 and He dilution simultaneously.")

    support_ref = bundle["support_reference"]
    n2_lo, n2_hi = support_ref["n2_bounds"]
    if not (n2_lo - 1e-6 <= parsed["n2_mol_frac"] <= n2_hi + 1e-6):
        reasons.append(
            f"n2_outside_tested_range: N2={parsed['n2_mol_frac']:.3f} outside tested [{n2_lo}, {n2_hi}]."
        )

    stds = support_ref["global_feature_stds"]
    ref_runs = support_ref["reference_runs"]
    dil = parsed["diluent_regime"]
    same_regime_runs = [r for r in ref_runs if r["fuel"] == fuel and r["diluent_regime"] == dil]

    env_key = f"{fuel}|{dil}"
    envelope = support_ref["regime_envelopes"].get(env_key)
    if envelope is None:
        if fuel in SUPPORTED_FUELS and dil != "CO2+He":
            reasons.append(f"missing_regime_envelope: no PSI-69 experiments exist for {fuel} under {dil}.")
    else:
        for fname, bounds in envelope["bounds"].items():
            val = parsed[fname]
            if not (bounds["min"] - 1e-6 <= val <= bounds["max"] + 1e-6):
                reasons.append(
                    f"outside_joint_regime_bounds: {fname}={val} outside tested {fuel}+{dil} range [{bounds['min']}, {bounds['max']}]."
                )

    candidates = same_regime_runs if same_regime_runs else ([r for r in ref_runs if r["fuel"] == fuel] or ref_runs)
    scored = sorted(
        ((_standardized_distance(parsed, ref, stds), ref) for ref in candidates),
        key=lambda item: (item[0], int(item[1]["test_id"])),
    )
    nearest_dist = scored[0][0]
    threshold = float(support_ref["distance_threshold_std"])
    if nearest_dist > threshold:
        reasons.append(
            f"outside_joint_condition_density: nearest same-fuel/diluent FLEX run is {nearest_dist:.3f} std away (threshold {threshold:.2f} std)."
        )

    nearest_list = [
        {
            **ref,
            "standardized_distance": round(dist, 4),
        }
        for dist, ref in scored[:5]
    ]

    return {
        "supported": len(reasons) == 0,
        "status": "SUPPORTED" if not reasons else "NOT_SUPPORTED",
        "reasons": reasons,
        "nearest_distance_std": round(nearest_dist, 4),
        "distance_threshold_std": threshold,
        "nearest_experiments": nearest_list,
    }


def _compute_raw6_shapley(
    predict_batch: Callable[[list[list[float]]], list[float]],
    x_raw6: list[float],
    bg_raw6: list[list[float]],
) -> tuple[float, float, list[dict[str, Any]]]:
    """Compute exact 2^6 interventional Shapley values over the 6 raw user inputs."""
    d = 6
    n_bg = len(bg_raw6)
    coalition_means = [0.0] * (1 << d)
    for mask in range(1 << d):
        batch = [[x_raw6[j] if (mask >> j) & 1 else bg[j] for j in range(d)] for bg in bg_raw6]
        preds = predict_batch(batch)
        coalition_means[mask] = sum(preds) / n_bg

    base = coalition_means[0]
    full = coalition_means[(1 << d) - 1]
    fact = [math.factorial(k) for k in range(d + 1)]
    phi = [0.0] * d
    for j in range(d):
        bit = 1 << j
        for mask in range(1 << d):
            if mask & bit:
                continue
            sz = mask.bit_count()
            weight = fact[sz] * fact[d - sz - 1] / fact[d]
            phi[j] += weight * (coalition_means[mask | bit] - coalition_means[mask])

    contributions = sorted(
        [
            {
                "feature": RAW_INPUT_NAMES[j],
                "label": RAW_INPUT_LABELS[RAW_INPUT_NAMES[j]],
                "input_value": round(x_raw6[j], 6),
                "shapley_contribution": round(phi[j], 6),
            }
            for j in range(d)
        ],
        key=lambda item: abs(item["shapley_contribution"]),
        reverse=True,
    )
    return base, full, contributions


def _build_model_structure(model: dict[str, Any], *, equation_hint: str) -> dict[str, Any]:
    """Expose standardized coefficients and feature transforms from a fitted linear/logistic model."""
    features = list(model.get("transformed_features", ()))
    weights = list(model.get("weights", ()))
    means = list(model.get("means", ()))
    stds = list(model.get("stds", ()))
    coef_rows = []
    for idx, fname in enumerate(features):
        coef_rows.append(
            {
                "feature": fname,
                "standardized_weight": round(float(weights[idx + 1]), 6),
                "train_mean": round(float(means[idx]), 6),
                "train_std": round(float(stds[idx]), 6),
            }
        )
    coef_rows.sort(key=lambda item: abs(item["standardized_weight"]), reverse=True)
    return {
        "name": model["name"],
        "l2_penalty": model.get("l2"),
        "n_train": model.get("n_train"),
        "intercept": round(float(weights[0]), 6),
        "equation_hint": equation_hint,
        "transformed_features": features,
        "coefficients": coef_rows,
    }


def _transformed_feature_contributions(
    model: dict[str, Any],
    x_transformed: list[float],
    *,
    contribution_unit: str,
) -> dict[str, Any]:
    """Exact additive decomposition of the standardized linear predictor (no out-of-domain counterfactuals)."""
    w = model["weights"]
    means = model["means"]
    stds = model["stds"]
    features = list(model["transformed_features"])
    items = []
    linear_sum = float(w[0])
    for idx, fname in enumerate(features):
        z = (float(x_transformed[idx]) - float(means[idx])) / float(stds[idx])
        contrib = float(w[idx + 1]) * z
        linear_sum += contrib
        items.append(
            {
                "feature": fname,
                "transformed_value": round(float(x_transformed[idx]), 6),
                "standardized_z": round(z, 4),
                "standardized_weight": round(float(w[idx + 1]), 6),
                "linear_contribution": round(contrib, 6),
            }
        )
    items.sort(key=lambda item: abs(item["linear_contribution"]), reverse=True)
    return {
        "unit": contribution_unit,
        "intercept": round(float(w[0]), 6),
        "linear_predictor": round(linear_sum, 6),
        "contributions": items,
    }


def _audit_raw6_shapley_counterfactuals(
    bundle: dict[str, Any],
    x_raw6: list[float],
    bg_raw6: list[list[float]],
) -> dict[str, Any]:
    """Audit whether independent 2^6 raw-input coalitions produce physically invalid counterfactuals."""
    support_ref = bundle["support_reference"]
    n2_lo, n2_hi = support_ref["n2_bounds"]
    envelopes = support_ref["regime_envelopes"]
    total = 0
    neg_n2 = 0
    bad_sum = 0
    mixed_dil = 0
    oob_regime = 0
    any_violation = 0

    for mask in range(1 << 6):
        m0 = mask & 1
        m1 = (mask >> 1) & 1
        m2 = (mask >> 2) & 1
        m3 = (mask >> 3) & 1
        m4 = (mask >> 4) & 1
        m5 = (mask >> 5) & 1
        for bg in bg_raw6:
            total += 1
            h = x_raw6[0] if m0 else bg[0]
            o2 = x_raw6[1] if m1 else bg[1]
            co2 = x_raw6[2] if m2 else bg[2]
            he = x_raw6[3] if m3 else bg[3]
            p_mmhg = x_raw6[4] if m4 else bg[4]
            d0 = x_raw6[5] if m5 else bg[5]

            implied_n2 = 1.0 - (o2 + co2 + he)
            has_neg_n2 = implied_n2 < -1e-6
            has_bad_sum = (o2 + co2 + he) > GAS_SUM_MAX or not (GAS_SUM_MIN <= o2 + co2 + he + implied_n2 <= GAS_SUM_MAX)
            has_mixed = co2 > 0.0 and he > 0.0
            fuel = "Heptane" if h > 0.5 else "Methanol"
            dil = _diluent_regime(co2, he)
            env = envelopes.get(f"{fuel}|{dil}")
            has_oob = env is None or not (n2_lo - 1e-6 <= implied_n2 <= n2_hi + 1e-6)
            if env is not None:
                bnds = env["bounds"]
                if (
                    not (bnds["o2_mol_frac"]["min"] - 1e-6 <= o2 <= bnds["o2_mol_frac"]["max"] + 1e-6)
                    or not (bnds["co2_mol_frac"]["min"] - 1e-6 <= co2 <= bnds["co2_mol_frac"]["max"] + 1e-6)
                    or not (bnds["he_mol_frac"]["min"] - 1e-6 <= he <= bnds["he_mol_frac"]["max"] + 1e-6)
                    or not (bnds["pressure_mmhg"]["min"] - 1e-6 <= p_mmhg <= bnds["pressure_mmhg"]["max"] + 1e-6)
                    or not (bnds["droplet_initial_diameter_mm"]["min"] - 1e-6 <= d0 <= bnds["droplet_initial_diameter_mm"]["max"] + 1e-6)
                ):
                    has_oob = True

            if has_neg_n2:
                neg_n2 += 1
            if has_bad_sum:
                bad_sum += 1
            if has_mixed:
                mixed_dil += 1
            if has_oob:
                oob_regime += 1
            if has_neg_n2 or has_bad_sum or has_mixed or has_oob:
                any_violation += 1

    return {
        "total_coalition_evals": total,
        "negative_n2_count": neg_n2,
        "gas_sum_violation_count": bad_sum,
        "mixed_co2_he_count": mixed_dil,
        "unsupported_regime_or_bounds_count": oob_regime,
        "any_violation_count": any_violation,
        "any_violation_share": round(any_violation / total, 4) if total else 0.0,
    }


def _extract_benchmark_views(bundle: dict[str, Any]) -> dict[str, Any] | None:
    report = bundle.get("_eval_report")
    if not isinstance(report, dict):
        return None
    return {
        "acceptance_decisions": report.get("acceptance_decisions", {}),
        "benchmarks": report.get("benchmarks", {}),
        "grouping_note": report.get("grouping_note") or (
            "atm+P (47 groups) and fuel+atm+P (78 regression / 80 classification groups) are two cross-validation "
            "grouping schemes over the same PSI-69 dataset used for model selection—NOT two independent external "
            "validation test sets."
        ),
        "evaluation_protocol": report.get("evaluation_protocol", "legacy_target_balanced_folds"),
        "critical_false_extinction": report.get("critical_false_extinction"),
        "oof_predictions_available": False,
        "oof_unavailable_reason": (
            "Individual out-of-fold row predictions are not persisted in the active model artifact or its evaluation "
            "report; only pooled CV metrics and per-fold R²/AUC ranges are stored. In-sample "
            "training-set scatters are omitted to avoid presenting training fit as generalization."
        ),
    }


def build_flex_prediction_schema(bundle: dict[str, Any]) -> dict[str, Any]:
    """Return input contract, per-regime joint bounds, model structures, and CV benchmarks."""
    reg = bundle["regression_model"]
    clf = bundle["classification_model"]
    fp_breakdown = clf["cv_group_atm_p"].get("false_positives_by_true_end", {})
    return {
        "model_version": bundle["model_version"],
        "training_data_sha256": bundle["training_data_sha256"],
        "disclaimer": bundle["disclaimer"],
        "supported_fuels": list(SUPPORTED_FUELS),
        "input_fields": [
            {"name": "fuel", "type": "string", "allowed": list(SUPPORTED_FUELS)},
            {"name": "o2_mol_frac", "type": "float", "unit": "mole_fraction"},
            {"name": "co2_mol_frac", "type": "float", "unit": "mole_fraction", "note": "Mutually exclusive with he_mol_frac > 0"},
            {"name": "he_mol_frac", "type": "float", "unit": "mole_fraction", "note": "Mutually exclusive with co2_mol_frac > 0"},
            {"name": "n2_mol_frac", "type": "float|null", "unit": "mole_fraction", "note": "Optional; computed as 1 - (O2 + CO2 + He) if omitted"},
            {"name": "pressure_mmhg", "type": "float", "unit": "mmHg", "aliases": ["pressure_atm", "pressure_kpa"]},
            {"name": "droplet_initial_diameter_mm", "type": "float", "unit": "mm"},
        ],
        "joint_support_gate": {
            "distance_metric": bundle["support_reference"]["distance_metric"],
            "distance_threshold_std": bundle["support_reference"]["distance_threshold_std"],
            "gas_sum_bounds": bundle["support_reference"]["gas_sum_bounds"],
            "n2_bounds": bundle["support_reference"]["n2_bounds"],
            "regime_envelopes": bundle["support_reference"]["regime_envelopes"],
        },
        "eligibility": bundle["eligibility"],
        "oof_predictions_available": False,
        "oof_unavailable_reason": (
            "Individual out-of-fold row predictions are not saved in the signed model/eval artifacts; "
            "full-dataset in-sample predictions are intentionally withheld from performance visuals."
        ),
        "shapley_audit_policy": {
            "raw6_interventional_shapley_enabled": False,
            "status": "DISABLED_UNRELIABLE",
            "reason": (
                "Swapping the 6 raw inputs independently across all empirical FLEX rows violates gas conservation "
                "(producing negative implied N2 or O2+CO2+He+N2 sums outside [0.98, 1.01]), creates mixed CO2+He "
                "mixtures (0 NASA tests), and generates out-of-envelope conditions (e.g., high-pressure Air). "
                "Instead, the UI displays validated transformed-feature structure and nearest real PSI-69 tests."
            ),
        },
        "models": {
            "burning_rate_regression": {
                "name": reg["name"],
                "model_family": "L2-regularized linear regression (Ridge, 8 transformed features)",
                "selection_status": "Selected among evaluated candidates (not claimed globally optimal or physical law)",
                "target": reg["target"],
                "unit": reg["unit"],
                "accepted": reg["accepted"],
                "cv_group_atm_p": reg["cv_group_atm_p"],
                "cv_group_fuel_atm_p": reg["cv_group_fuel_atm_p"],
                "structure": _build_model_structure(
                    reg,
                    equation_hint="K_hat (mm^2/s) = w0 + sum(w_j * ((x_trans_j - mean_j) / std_j)); clamped at >= 0 in UI output",
                ),
            },
            "extinction_classification": {
                "name": clf["name"],
                "model_family": "L2-regularized binary logistic classification (10 transformed features)",
                "selection_status": "Selected among evaluated candidates (discriminative empirical score, not a calibrated fire-safety probability)",
                "target": clf["target"],
                "threshold": clf["threshold"],
                "accepted": clf["accepted"],
                "cv_group_atm_p": clf["cv_group_atm_p"],
                "cv_group_fuel_atm_p": clf["cv_group_fuel_atm_p"],
                "cv_sensitivity_no_disruption": clf["cv_sensitivity_no_disruption"],
                "non_extinction_fp_warning": {
                    "fp": clf["cv_group_atm_p"]["confusion_matrix"]["fp"],
                    "negative_non_extinction": clf["cv_group_atm_p"]["negative_non_extinction"],
                    "fpr": clf["cv_group_atm_p"]["false_positive_rate_on_non_extinction"],
                    "by_true_end": fp_breakdown,
                },
                "confounding_note": (
                    "Non-Extinction pools Completion and Disruption; NASA/TP-2015-216046 Section 5.2 "
                    "notes fuel-needle contamination likely contributed to Methanol Disruptions and "
                    "is inconclusive for Heptane."
                ),
                "structure": _build_model_structure(
                    clf,
                    equation_hint="score = sigmoid(w0 + sum(w_j * ((x_trans_j - mean_j) / std_j)))",
                ),
            },
        },
        "evaluation_benchmarks": _extract_benchmark_views(bundle),
    }


def run_flex_prediction(bundle: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Validate inputs, enforce joint-support gating, audit raw6 SHAP, and return predictions + structure."""
    parsed = validate_prediction_payload(payload)
    support = check_flex_support(bundle, parsed)
    raw6 = [
        1.0 if parsed["fuel"] == "Heptane" else 0.0,
        parsed["o2_mol_frac"],
        parsed["co2_mol_frac"],
        parsed["he_mol_frac"],
        parsed["pressure_mmhg"],
        parsed["droplet_initial_diameter_mm"],
    ]

    from ..coverage import assess_flex_predictor_coverage

    if not support["supported"]:
        out_unsup = {
            "status": "NOT_SUPPORTED",
            "model_version": bundle["model_version"],
            "training_data_sha256": bundle["training_data_sha256"],
            "normalized_input": parsed,
            "support": support,
            "predictions": None,
            "local_explanations": None,
            "disclaimer": bundle["disclaimer"],
        }
        out_unsup["coverage"] = assess_flex_predictor_coverage(out_unsup).to_dict()
        return out_unsup

    reg_model = bundle["regression_model"]
    clf_model = bundle["classification_model"]

    x_reg = _reg_phys8([raw6])[0]
    x_clf = _clf_phys10([raw6])[0]
    k_pred = _predict_ridge(reg_model, [x_reg])[0]
    ext_probs, _ = _predict_logistic_probs_and_logits(clf_model, [x_clf])
    ext_score = ext_probs[0]

    counterfactual_audit = _audit_raw6_shapley_counterfactuals(
        bundle,
        raw6,
        bundle["background_clf_raw6"],
    )

    k_pred_clamped = max(0.0, k_pred)
    predicted_class = "Extinction" if ext_score >= clf_model["threshold"] else "Non-Extinction"
    fp_count = clf_model["cv_group_atm_p"]["confusion_matrix"]["fp"]
    neg_count = clf_model["cv_group_atm_p"]["negative_non_extinction"]

    result = {
        "status": "OK",
        "model_version": bundle["model_version"],
        "training_data_sha256": bundle["training_data_sha256"],
        "normalized_input": parsed,
        "support": support,
        "predictions": {
            "burning_rate_mm2_s": {
                "value": round(k_pred_clamped, 4),
                "raw_model_output": round(k_pred, 4),
                "unit": "mm^2/s",
                "model": reg_model["name"],
                "model_family": "L2-regularized linear regression (Ridge)",
                "group_cv_mae": reg_model["cv_group_atm_p"]["mae"],
                "group_cv_rmse": reg_model["cv_group_atm_p"]["rmse"],
                "group_cv_r2": reg_model["cv_group_atm_p"]["r2"],
                "group_fuel_cv_r2": reg_model["cv_group_fuel_atm_p"]["r2"],
            },
            "extinction_likelihood": {
                "score": round(ext_score, 4),
                "predicted_label": predicted_class,
                "decision_threshold": clf_model["threshold"],
                "model": clf_model["name"],
                "model_family": "L2-regularized binary logistic classification",
                "group_cv_roc_auc": clf_model["cv_group_atm_p"]["roc_auc"],
                "group_fuel_cv_roc_auc": clf_model["cv_group_fuel_atm_p"]["roc_auc"],
                "group_cv_brier": clf_model["cv_group_atm_p"]["brier_score"],
                "false_positive_rate_on_non_extinction": clf_model["cv_group_atm_p"]["false_positive_rate_on_non_extinction"],
                "false_positives_by_true_end": clf_model["cv_group_atm_p"].get("false_positives_by_true_end", {}),
                "calibration_warning": (
                    "Uncalibrated empirical FLEX frequency score (not spacecraft fire-safety probability). "
                    f"At threshold 0.50, grouped-CV false positive count on Non-Extinction runs is {fp_count}/{neg_count}."
                ),
            },
        },
        "local_explanations": {
            "status": "DISABLED_UNRELIABLE",
            "published": False,
            "method": "audited_disabled_raw6_interventional_shapley",
            "note": (
                "Raw-6 interventional Shapley bars are disabled after auditing 2^6 empirical background swaps: "
                f"{counterfactual_audit['any_violation_count']}/{counterfactual_audit['total_coalition_evals']} "
                f"({counterfactual_audit['any_violation_share'] * 100:.1f}%) coalition evaluations produced invalid gas sums, "
                "negative implied N2, unsupported CO2+He mixtures, or out-of-envelope conditions. "
                "Instead, exact transformed-feature additive terms within the fitted model structure are reported below."
            ),
            "counterfactual_audit": counterfactual_audit,
            "transformed_feature_contributions": {
                "burning_rate_mm2_s": _transformed_feature_contributions(
                    reg_model,
                    x_reg,
                    contribution_unit="mm^2/s relative to ridge intercept (training mean target)",
                ),
                "extinction_likelihood": _transformed_feature_contributions(
                    clf_model,
                    x_clf,
                    contribution_unit="log-odds relative to logistic intercept",
                ),
            },
        },
        "disclaimer": bundle["disclaimer"],
    }
    result["coverage"] = assess_flex_predictor_coverage(result).to_dict()
    return result


def _linspace(lo: float, hi: float, steps: int) -> list[float]:
    if steps <= 1:
        return [round(lo, 4)]
    span = hi - lo
    return [round(lo + span * i / (steps - 1), 4) for i in range(steps)]


def run_flex_condition_map(bundle: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a bounded 2D O2 vs diluent/pressure slice with strict joint-support masking (no gap interpolation)."""
    cond = parse_request(FlexConditionMapIn, payload, error_cls=FlexPredictionValidationError)
    fuel = _normalize_fuel(cond.fuel)
    if fuel not in SUPPORTED_FUELS:
        raise FlexPredictionValidationError(f"fuel must be one of {list(SUPPORTED_FUELS)}.")
    diluent_regime = cond.diluent_regime
    pressure_mmhg = _pressure_mmhg(cond)
    d0_mm = cond.droplet_initial_diameter_mm
    o2_steps, y_steps = cond.o2_steps, cond.y_steps

    o2_vals = _linspace(0.11, 0.36, o2_steps)
    if diluent_regime == "CO2":
        y_kind = "co2_mol_frac"
        y_label = "Added CO2 mole fraction"
        y_unit = "mole_fraction"
        y_vals = _linspace(0.0, 0.72, y_steps)
    elif diluent_regime == "He":
        y_kind = "he_mol_frac"
        y_label = "Added He mole fraction"
        y_unit = "mole_fraction"
        y_vals = _linspace(0.0, 0.62, y_steps)
    else:
        y_kind = "pressure_atm"
        y_label = "Ambient pressure (atm)"
        y_unit = "atm"
        y_vals = _linspace(0.4, 3.1, y_steps)

    reg_model = bundle["regression_model"]
    clf_model = bundle["classification_model"]
    cells: list[dict[str, Any]] = []
    supported_count = 0

    for yv in y_vals:
        for o2v in o2_vals:
            co2v = yv if y_kind == "co2_mol_frac" else 0.0
            hev = yv if y_kind == "he_mol_frac" else 0.0
            p_cell_mmhg = (yv * MMHG_PER_ATM) if y_kind == "pressure_atm" else pressure_mmhg
            n2v = round(1.0 - (o2v + co2v + hev), 6)

            if n2v < 0.0 or (o2v + co2v + hev) > GAS_SUM_MAX:
                cells.append(
                    {
                        "o2_mol_frac": o2v,
                        "y_value": yv,
                        "co2_mol_frac": co2v,
                        "he_mol_frac": hev,
                        "n2_mol_frac": n2v,
                        "pressure_atm": round(p_cell_mmhg / MMHG_PER_ATM, 3),
                        "supported": False,
                        "reasons": ["gas_balance_exceeds_unity: O2 + CO2 + He > 1.01 (negative N2 balance)."],
                        "burning_rate_mm2_s": None,
                        "extinction_score": None,
                    }
                )
                continue

            parsed = {
                "fuel": fuel,
                "o2_mol_frac": o2v,
                "co2_mol_frac": co2v,
                "he_mol_frac": hev,
                "n2_mol_frac": n2v,
                "gas_sum": round(o2v + co2v + hev + n2v, 4),
                "pressure_mmhg": round(p_cell_mmhg, 4),
                "droplet_initial_diameter_mm": d0_mm,
                "diluent_regime": _diluent_regime(co2v, hev),
                "domain_context": None,
            }
            sup = check_flex_support(bundle, parsed)
            if not sup["supported"]:
                cells.append(
                    {
                        "o2_mol_frac": o2v,
                        "y_value": yv,
                        "co2_mol_frac": co2v,
                        "he_mol_frac": hev,
                        "n2_mol_frac": n2v,
                        "pressure_atm": round(p_cell_mmhg / MMHG_PER_ATM, 3),
                        "supported": False,
                        "reasons": sup["reasons"][:3],
                        "burning_rate_mm2_s": None,
                        "extinction_score": None,
                    }
                )
                continue

            supported_count += 1
            raw6 = [1.0 if fuel == "Heptane" else 0.0, o2v, co2v, hev, p_cell_mmhg, d0_mm]
            k_val = max(0.0, _predict_ridge(reg_model, _reg_phys8([raw6]))[0])
            ext_p, _ = _predict_logistic_probs_and_logits(clf_model, _clf_phys10([raw6]))
            cells.append(
                {
                    "o2_mol_frac": o2v,
                    "y_value": yv,
                    "co2_mol_frac": co2v,
                    "he_mol_frac": hev,
                    "n2_mol_frac": n2v,
                    "pressure_atm": round(p_cell_mmhg / MMHG_PER_ATM, 3),
                    "supported": True,
                    "reasons": [],
                    "burning_rate_mm2_s": round(k_val, 4),
                    "extinction_score": round(ext_p[0], 4),
                }
            )

    ref_runs = bundle["support_reference"]["reference_runs"]
    slice_runs = []
    for r in ref_runs:
        if r["fuel"] != fuel:
            continue
        if diluent_regime == "Air" and r["diluent_regime"] != "Air":
            continue
        if diluent_regime == "CO2" and r["diluent_regime"] not in ("CO2", "Air"):
            continue
        if diluent_regime == "He" and r["diluent_regime"] not in ("He", "Air"):
            continue
        y_run = (
            r["co2_mol_frac"]
            if y_kind == "co2_mol_frac"
            else (r["he_mol_frac"] if y_kind == "he_mol_frac" else round(r["pressure_mmhg"] / MMHG_PER_ATM, 3))
        )
        p_diff_atm = abs(r["pressure_mmhg"] - pressure_mmhg) / MMHG_PER_ATM
        d_diff_mm = abs(r["droplet_initial_diameter_mm"] - d0_mm)
        within_slice = (p_diff_atm <= 0.35 if y_kind != "pressure_atm" else True) and d_diff_mm <= 0.8
        slice_runs.append(
            {
                "test_id": r["test_id"],
                "record_pk": r["record_pk"],
                "fuel": r["fuel"],
                "diluent_regime": r["diluent_regime"],
                "o2_mol_frac": r["o2_mol_frac"],
                "co2_mol_frac": r["co2_mol_frac"],
                "he_mol_frac": r["he_mol_frac"],
                "pressure_mmhg": r["pressure_mmhg"],
                "pressure_atm": round(r["pressure_mmhg"] / MMHG_PER_ATM, 3),
                "droplet_initial_diameter_mm": r["droplet_initial_diameter_mm"],
                "y_value": y_run,
                "test_end": r["test_end"],
                "burning_rate_mm2_s": r["burning_rate_mm2_s"],
                "within_slice_window": within_slice,
            }
        )

    return {
        "status": "OK",
        "model_version": bundle["model_version"],
        "slice": {
            "fuel": fuel,
            "diluent_regime": diluent_regime,
            "pressure_mmhg": round(pressure_mmhg, 2),
            "pressure_atm": round(pressure_mmhg / MMHG_PER_ATM, 3),
            "droplet_initial_diameter_mm": round(d0_mm, 3),
            "x_axis": {"key": "o2_mol_frac", "label": "Initial O2 mole fraction", "values": o2_vals},
            "y_axis": {"key": y_kind, "label": y_label, "unit": y_unit, "values": y_vals},
        },
        "total_cells": len(cells),
        "supported_cells": supported_count,
        "masked_cells": len(cells) - supported_count,
        "cells": cells,
        "real_experiments": slice_runs,
        "boundary_note": (
            "Cells marked supported=False are outside NASA/PSI-69 joint experimental support and remain masked "
            "(null predictions, zero interpolation across gaps). Real PSI-69 points reflect measured experimental outcomes."
        ),
    }
