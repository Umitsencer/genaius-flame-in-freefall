"""Physics-informed feature maps and JSON-coefficient inference (no ML library at runtime)."""

from __future__ import annotations

import math
from typing import Any

from .common import MMHG_PER_ATM


def _reg_phys8(rows: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for h, o2, co2, he, p_mmhg, d0 in rows:
        lnp = math.log(p_mmhg / MMHG_PER_ATM)
        out.append([h, o2, co2, he, lnp, d0, o2 * h, he * h])
    return out


def _clf_phys10(rows: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for h, o2, co2, he, p_mmhg, d0 in rows:
        lnp = math.log(p_mmhg / MMHG_PER_ATM)
        out.append([h, o2, co2, he, lnp, d0, o2 * h, co2 * h, he * h, d0 * h])
    return out


def _linear6_features(rows: list[list[float]]) -> list[list[float]]:
    return [[h, o2, co2, he, p_mmhg / MMHG_PER_ATM, d0] for h, o2, co2, he, p_mmhg, d0 in rows]


def _poly12_features(rows: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for h, o2, co2, he, p_mmhg, d0 in rows:
        patm = p_mmhg / MMHG_PER_ATM
        lnp = math.log(patm)
        out.append([h, o2, co2, he, patm, d0, lnp, o2 * o2, o2 * h, co2 * h, he * h, d0 * h])
    return out


def _standardize_apply(X: list[list[float]], means: list[float], stds: list[float]) -> list[list[float]]:
    d = len(means)
    return [[(row[j] - means[j]) / stds[j] for j in range(d)] for row in X]


def _predict_ridge(model: dict[str, Any], X: list[list[float]]) -> list[float]:
    w = model["weights"]
    Z = _standardize_apply(X, model["means"], model["stds"])
    return [w[0] + sum(w[j + 1] * row[j] for j in range(len(row))) for row in Z]


def _sigmoid(z: float) -> float:
    if z >= 35.0:
        return 1.0
    if z <= -35.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def _predict_logistic_probs_and_logits(
    model: dict[str, Any],
    X: list[list[float]],
) -> tuple[list[float], list[float]]:
    w = model["weights"]
    Z = _standardize_apply(X, model["means"], model["stds"])
    logits = [w[0] + sum(w[j + 1] * row[j] for j in range(len(row))) for row in Z]
    probs = [_sigmoid(z) for z in logits]
    return probs, logits


# Small pure-stdlib CART/Random-Forest baseline comparators for CV verification
