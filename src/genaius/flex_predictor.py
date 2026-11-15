"""Compatibility import path for the FLEX predictor; the implementation lives in `genaius.flex`.

Runtime inference uses the signed v1 JSON artifact (`data/processed/flex_condition_models.json`).
Training/evaluation is in `genaius.flex.training` (scikit-learn) and is not imported here.
"""
from __future__ import annotations

from .flex.artifacts import load_flex_predictor_bundle
from .flex.common import (
    CALIBRATION_AND_SCOPE_DISCLAIMER,
    DEFAULT_EVAL_REPORT_REL_PATH,
    DEFAULT_MODEL_ARTIFACT_REL_PATH,
    MODEL_ARTIFACT_SCHEMA_VERSION,
    MODEL_VERSION,
    PSI69_CSV_REL_PATH,
    SUPPORTED_FUELS,
    FlexPredictionValidationError,
    FlexPredictorError,
)
from .flex.dataset import FlexPreparedRow, prepare_psi69_training_dataset
from .flex.inference import (
    build_flex_prediction_schema,
    check_flex_support,
    run_flex_condition_map,
    run_flex_prediction,
    validate_prediction_payload,
)
from .flex.reports import build_flex_prediction_evidence_bundle, build_flex_research_summary_export

__all__ = [
    "CALIBRATION_AND_SCOPE_DISCLAIMER",
    "DEFAULT_EVAL_REPORT_REL_PATH",
    "DEFAULT_MODEL_ARTIFACT_REL_PATH",
    "FlexPredictionValidationError",
    "FlexPredictorError",
    "FlexPreparedRow",
    "MODEL_ARTIFACT_SCHEMA_VERSION",
    "MODEL_VERSION",
    "PSI69_CSV_REL_PATH",
    "SUPPORTED_FUELS",
    "build_flex_prediction_evidence_bundle",
    "build_flex_prediction_schema",
    "build_flex_research_summary_export",
    "check_flex_support",
    "load_flex_predictor_bundle",
    "prepare_psi69_training_dataset",
    "run_flex_condition_map",
    "run_flex_prediction",
    "validate_prediction_payload",
]
