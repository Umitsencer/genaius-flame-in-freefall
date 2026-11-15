"""FLEX predictor constants, errors and small shared helpers."""

from __future__ import annotations

from pathlib import Path

MODEL_ARTIFACT_SCHEMA_VERSION = "1.0.0"
# Active runtime model (Görev 058): accepted on target-agnostic grouped CV. v1 files are kept unchanged.
MODEL_VERSION = "flex_phys_v2_sklearn"
LEGACY_V1_MODEL_VERSION = "flex_phys_v1"
DEFAULT_MODEL_ARTIFACT_REL_PATH = Path("data/processed/flex_condition_models_v2_sklearn.json")
DEFAULT_EVAL_REPORT_REL_PATH = Path("data/processed/flex_eval_report_v2_sklearn.json")
LEGACY_V1_MODEL_ARTIFACT_REL_PATH = Path("data/processed/flex_condition_models.json")
LEGACY_V1_EVAL_REPORT_REL_PATH = Path("data/processed/flex_eval_report.json")
PSI69_CSV_REL_PATH = Path("data/raw/psi/experimental_tables/PSI-69/PSI-69_Experimental table_FLEX.csv")

MMHG_PER_ATM = 760.0
MMHG_PER_KPA = 7.50061683
JOINT_DISTANCE_THRESHOLD_STD = 1.50
GAS_SUM_MIN = 0.98
GAS_SUM_MAX = 1.01

RAW_INPUT_NAMES: tuple[str, ...] = (
    "fuel_is_heptane",
    "o2_mol_frac",
    "co2_mol_frac",
    "he_mol_frac",
    "pressure_mmhg",
    "droplet_initial_diameter_mm",
)
RAW_INPUT_LABELS: dict[str, str] = {
    "fuel_is_heptane": "Fuel (Heptane vs Methanol)",
    "o2_mol_frac": "Initial O2 mole fraction",
    "co2_mol_frac": "Initial CO2 mole fraction",
    "he_mol_frac": "Initial He mole fraction",
    "pressure_mmhg": "Ambient pressure (mmHg)",
    "droplet_initial_diameter_mm": "Initial droplet diameter d0 (mm)",
}

SUPPORTED_FUELS: tuple[str, ...] = ("Methanol", "Heptane")
_FORBIDDEN_DOMAIN_TERMS: tuple[str, ...] = (
    "bass",
    "saffire",
    "cfi",
    "solid",
    "cotton",
    "pmma",
    "nomex",
    "ultem",
    "acrylic",
    "lunar",
    "moon",
    "mars",
    "martian",
    "cabin",
    "spacecraft fire",
    "normal gravity",
    "1g",
    "partial gravity",
)

CALIBRATION_AND_SCOPE_DISCLAIMER = (
    "Trained exclusively on NASA/PSI-69 FLEX single free-floating droplet microgravity tests "
    "(Methanol and Heptane only). Extinction score reflects empirical test frequency against "
    "Completion + Disruption (excluding post-test variables and FLEX-114 P=0 anomaly); it is NOT a "
    "calibrated spacecraft fire-safety probability and has a grouped-CV false-positive rate of ~40% "
    "on Non-Extinction tests (confounded by Section 5.2 needle-contamination Disruptions and rare Completions). "
    "Local Shapley contributions reflect observational association, not causal proof."
)


class FlexPredictorError(RuntimeError):
    """Raised when the FLEX model artifact is missing, corrupt, or invalid."""


class FlexPredictionValidationError(ValueError):
    """Raised on malformed request schema or syntactically invalid input values."""


def _diluent_regime(co2: float, he: float) -> str:
    if co2 > 0.0 and he > 0.0:
        return "CO2+He"
    if co2 > 0.0:
        return "CO2"
    if he > 0.0:
        return "He"
    return "Air"


def _nominal_pressure_bin(mmhg: float) -> str:
    atm = mmhg / MMHG_PER_ATM
    for label, target in (
        ("0.70atm", 0.70),
        ("1.00atm", 1.00),
        ("1.50atm", 1.50),
        ("2.00atm", 2.00),
        ("2.72atm", 2.72),
        ("3.05atm", 3.05),
    ):
        if abs(atm - target) < 0.12:
            return label
    return f"{round(atm, 2):.2f}atm"
