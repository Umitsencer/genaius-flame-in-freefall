"""Signed, non-pickle JSON model artifacts: digest, integrity checks and loading."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .common import (
    DEFAULT_EVAL_REPORT_REL_PATH,
    DEFAULT_MODEL_ARTIFACT_REL_PATH,
    FlexPredictorError,
    MODEL_ARTIFACT_SCHEMA_VERSION,
    PSI69_CSV_REL_PATH,
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _artifact_digest(payload: dict[str, Any]) -> str:
    body = {
        k: v
        for k, v in payload.items()
        if k != "artifact_digest_sha256" and not str(k).startswith("_")
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_flex_predictor_bundle(
    repo_root: str | Path,
    *,
    model_rel_path: Path = DEFAULT_MODEL_ARTIFACT_REL_PATH,
    eval_rel_path: Path = DEFAULT_EVAL_REPORT_REL_PATH,
) -> dict[str, Any]:
    """Load and verify a JSON FLEX model artifact (default: the active v1 artifact) and its report.

    JSON only — no pickle/joblib model files are ever loaded.
    """
    root = Path(repo_root).resolve()
    model_path = root / model_rel_path
    eval_path = root / eval_rel_path
    csv_path = root / PSI69_CSV_REL_PATH
    if not model_path.exists():
        raise FlexPredictorError(f"FLEX model artifact not found: {model_path}")
    if not csv_path.exists():
        raise FlexPredictorError(f"Missing PSI-69 training CSV: {csv_path}")

    artifact = json.loads(model_path.read_text(encoding="utf-8"))
    if artifact.get("schema_version") != MODEL_ARTIFACT_SCHEMA_VERSION:
        raise FlexPredictorError("Unsupported FLEX model artifact schema version.")
    expected_digest = artifact.get("artifact_digest_sha256")
    if not expected_digest or expected_digest != _artifact_digest(artifact):
        raise FlexPredictorError("FLEX model artifact integrity digest mismatch.")
    actual_csv_sha = _sha256_file(csv_path)
    if artifact.get("training_data_sha256") != actual_csv_sha:
        raise FlexPredictorError("FLEX model artifact training_data_sha256 does not match PSI-69 CSV.")
    if eval_path.exists():
        eval_report = json.loads(eval_path.read_text(encoding="utf-8"))
        if eval_report.get("training_data_sha256") != actual_csv_sha:
            raise FlexPredictorError("FLEX evaluation report training_data_sha256 does not match PSI-69 CSV.")
        artifact["_eval_report"] = eval_report
    return artifact
