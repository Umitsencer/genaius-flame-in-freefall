"""Görev 058 FLEX model acceptance on target-agnostic grouped CV; activates v2 only if accepted.

    python scripts/research/evaluate_flex_group_holdout.py --repo-root .

Requires `requirements-train.txt`. Writes the active v2 artifact + report and
data/processed/flex_acceptance_v2.json. The legacy v1 files are never modified.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    args = ap.parse_args(argv)
    root = Path(args.repo_root).resolve()
    sys.path.insert(0, str(root / "src"))
    from genaius.flex.artifacts import load_flex_predictor_bundle
    from genaius.flex.common import (DEFAULT_EVAL_REPORT_REL_PATH, DEFAULT_MODEL_ARTIFACT_REL_PATH,
                                     LEGACY_V1_EVAL_REPORT_REL_PATH, LEGACY_V1_MODEL_ARTIFACT_REL_PATH)
    from genaius.flex.training import build_accepted_artifact

    v1_before = (root / LEGACY_V1_MODEL_ARTIFACT_REL_PATH).read_bytes()
    artifact, report, acc = build_accepted_artifact(root)
    (root / DEFAULT_MODEL_ARTIFACT_REL_PATH).write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    (root / DEFAULT_EVAL_REPORT_REL_PATH).write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = {
        "accepted": acc["accepted"], "active_model_version": artifact["model_version"],
        "active_artifact_digest_sha256": artifact["artifact_digest_sha256"],
        "acceptance_checks": acc["acceptance_checks"], "critical_false_extinction": acc["critical_false_extinction"],
        "nested_choices": {k: v["nested_selected_hyperparameter_per_fold"] for k, v in acc["views"].items()},
        "legacy_v1_unchanged": (root / LEGACY_V1_MODEL_ARTIFACT_REL_PATH).read_bytes() == v1_before,
        "legacy_v1_report": LEGACY_V1_EVAL_REPORT_REL_PATH.as_posix(),
    }
    (root / "data/processed/flex_acceptance_v2.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    load_flex_predictor_bundle(root)  # active artifact must verify
    print(json.dumps(summary, indent=1)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
