"""FLEX research-summary export and the separated evidence bundle for grounded answers."""

from __future__ import annotations

import json
from typing import Any

from .common import (
    DEFAULT_MODEL_ARTIFACT_REL_PATH,
    FlexPredictionValidationError,
    MMHG_PER_ATM,
)
from .inference import (
    run_flex_prediction,
)


def build_flex_research_summary_export(
    bundle: dict[str, Any],
    payload: dict[str, Any],
    *,
    fmt: str = "md",
) -> dict[str, Any]:
    """Build a traceable Condition Research Summary separating measured, predicted, derived, and limits."""
    fmt_clean = fmt.strip().lower()
    if fmt_clean not in ("md", "json"):
        raise FlexPredictionValidationError("format must be 'md' or 'json'.")

    pred_result = run_flex_prediction(bundle, payload)
    ni = pred_result["normalized_input"]
    sup = pred_result["support"]
    preds = pred_result["predictions"]
    exps = pred_result["local_explanations"]
    tag = f"{ni['fuel'].lower()}_o2_{round(ni['o2_mol_frac'] * 100)}pct_{ni['diluent_regime'].lower()}"

    if fmt_clean == "json":
        report_obj = {
            "report_type": "GeNAIus_FLEX_Condition_Research_Summary",
            "model_version": pred_result["model_version"],
            "training_data_sha256": pred_result["training_data_sha256"],
            "validated_pre_test_inputs": {
                "fuel": ni["fuel"],
                "o2_mol_frac": ni["o2_mol_frac"],
                "co2_mol_frac": ni["co2_mol_frac"],
                "he_mol_frac": ni["he_mol_frac"],
                "derived_n2_balance": ni["n2_mol_frac"],
                "diluent_regime": ni["diluent_regime"],
                "pressure_mmhg": ni["pressure_mmhg"],
                "droplet_initial_diameter_mm": ni["droplet_initial_diameter_mm"],
            },
            "support_verdict": {
                "status": pred_result["status"],
                "supported": sup["supported"],
                "nearest_distance_std": sup["nearest_distance_std"],
                "distance_threshold_std": sup["distance_threshold_std"],
                "reasons": sup["reasons"],
            },
            "model_estimates_only": preds,
            "explanation_audit": exps,
            "measured_nearest_psi69_runs": sup["nearest_experiments"],
            "sources_and_limits": {
                "primary_dataset": "NASA PSI-69 FLEX Experimental Table (CC0 1.0)",
                "technical_report": "NASA/TP-2015-216046",
                "disclaimer": pred_result["disclaimer"],
            },
        }
        return {
            "status": "OK",
            "format": "json",
            "filename": f"flex_condition_summary_{tag}.json",
            "content": json.dumps(report_obj, indent=2, ensure_ascii=False),
            "summary_payload": report_obj,
        }

    lines = [
        "# GeNAIus FLEX Pre-Test Condition Research Summary",
        "",
        f"- **Model version:** `{pred_result['model_version']}`",
        f"- **PSI-69 CSV SHA-256:** `{pred_result['training_data_sha256']}`",
        f"- **Support gate verdict:** **{pred_result['status']}** (nearest standardized distance `{sup['nearest_distance_std']}` std; threshold `{sup['distance_threshold_std']}` std)",
        "",
        "## 1. Validated Pre-Test Inputs & Derived Balance",
        f"- Fuel: `{ni['fuel']}`",
        f"- O2 mole fraction: `{ni['o2_mol_frac']:.4f}`",
        f"- CO2 mole fraction: `{ni['co2_mol_frac']:.4f}`",
        f"- He mole fraction: `{ni['he_mol_frac']:.4f}`",
        f"- N2 remainder (derived `1 - O2 - CO2 - He`): `{ni['n2_mol_frac']:.4f}` (`diluent_regime={ni['diluent_regime']}`)",
        f"- Ambient pressure: `{ni['pressure_mmhg']:.2f} mmHg` (`{ni['pressure_mmhg'] / MMHG_PER_ATM:.3f} atm`)",
        f"- Initial droplet diameter (d0): `{ni['droplet_initial_diameter_mm']:.3f} mm`",
        "",
        "## 2. Model Estimates (NOT Physical Law / NOT Fire-Safety Rating)",
    ]
    if preds is None:
        lines.append("- **No predictions emitted:** Condition is outside joint PSI-69 experimental support.")
        for r in sup["reasons"]:
            lines.append(f"  - Reason: {r}")
    else:
        br = preds["burning_rate_mm2_s"]
        ex = preds["extinction_likelihood"]
        lines.extend(
            [
                f"- **A. Burning-rate constant estimate (`{br['model']}`):** `{br['value']:.4f} mm^2/s` (raw model output `{br['raw_model_output']:.4f}`; grouped-CV MAE `{br['group_cv_mae']}`, RMSE `{br['group_cv_rmse']}`, `R^2={br['group_cv_r2']}` in atm+P)",
                f"- **B. Extinction score (`{ex['model']}`):** `{ex['score']:.4f}` -> class `{ex['predicted_label']}` at threshold `{ex['decision_threshold']}` (grouped-CV ROC-AUC `{ex['group_cv_roc_auc']}`, Brier `{ex['group_cv_brier']}`, Non-Extinction false-positive warning: `{ex['calibration_warning']}`)",
                "",
                "## 3. Model Explanation & Audit Notice",
                f"- Raw-6 Shapley status: **{exps['status']}** (`published={exps['published']}`)",
                f"- Audit detail: {exps['note']}",
            ]
        )
    lines.extend(["", "## 4. Nearest Measured NASA PSI-69 Runs (Reference Evidence Only)"])
    for run in sup["nearest_experiments"]:
        k_str = f"{run['burning_rate_mm2_s']} mm^2/s" if run.get("burning_rate_mm2_s") is not None else "missing"
        lines.append(
            f"- **{run['record_pk']}** (FLEX-{run['test_id']}): fuel=`{run['fuel']}`, O2=`{run['o2_mol_frac']}`, "
            f"CO2=`{run['co2_mol_frac']}`, He=`{run['he_mol_frac']}`, P=`{run['pressure_mmhg']} mmHg`, "
            f"d0=`{run['droplet_initial_diameter_mm']} mm`, end=`{run['test_end']}`, K=`{k_str}`, "
            f"dist=`{run['standardized_distance']} std`"
        )
    lines.extend(
        [
            "",
            "## 5. Sources & Boundaries",
            "- Measured reference table: `data/raw/psi/experimental_tables/PSI-69/PSI-69_Experimental table_FLEX.csv` (NASA PSI-69, CC0 1.0).",
            "- Experimental report context: `NASA/TP-2015-216046` (Section 5.2 notes fuel-needle Disruption confounding).",
            f"- Scope boundary: {pred_result['disclaimer']}",
        ]
    )
    return {
        "status": "OK",
        "format": "md",
        "filename": f"flex_condition_summary_{tag}.md",
        "content": "\n".join(lines) + "\n",
    }


def build_flex_prediction_evidence_bundle(
    request: Any,
    *,
    bundle: dict[str, Any],
    flex_condition: dict[str, Any],
    records_by_pk: dict[str, Any],
    bm25_index: Any | None,
) -> Any:
    """Build a strictly separated EvidenceBundle for explaining FLEX model outputs alongside nearest PSI-69 runs."""
    from ..data.query import QueryResult
    from ..retrieval.bm25 import BM25_SCORE_DISCLAIMER
    from ..service import (
        SERVICE_BOUNDARY_DISCLAIMER,
        SERVICE_MODE_DETERMINISTIC,
        CitationItem,
        EvidenceBundle,
        evaluate_abstention_gate,
    )

    from ..coverage import assess_core_coverage, assess_flex_predictor_coverage

    pred_result = run_flex_prediction(bundle, flex_condition)
    abstention = evaluate_abstention_gate(request.query, investigation_id="PSI-69")
    if abstention.abstained:
        return EvidenceBundle(
            request=request,
            mode=SERVICE_MODE_DETERMINISTIC,
            abstention=abstention,
            resolved_investigation_id="PSI-69",
            table_result=None,
            field_summary=None,
            comparison_result=None,
            document_result=None,
            citations=(),
            warnings=(),
            disclaimers=(SERVICE_BOUNDARY_DISCLAIMER, bundle["disclaimer"]),
            coverage=assess_core_coverage(
                request=request,
                abstention=abstention,
                table_result=None,
                field_summary=None,
                comparison_result=None,
                document_result=None,
            ),
        )

    nearest = pred_result.get("support", {}).get("nearest_experiments", [])
    matched_records = tuple(
        records_by_pk[item["record_pk"]]
        for item in nearest
        if item.get("record_pk") in records_by_pk
    )
    table_result = QueryResult(
        records=matched_records,
        total_runs=len(matched_records),
        unique_sample_count=None,
        unique_flex_identifier_count=len({r.test_id for r in matched_records}),
        counts_by_investigation={"PSI-69": len(matched_records)} if matched_records else {},
        warnings=(),
        applied_filters={"investigation_id": "PSI-69", "nearest_experiments_for_condition": True},
    )

    warnings: list[str] = []
    document_result = None
    doc_query = (request.query or "").strip() or (
        f"FLEX droplet extinction burning rate {pred_result['normalized_input']['fuel']} needle disruption"
    )
    if bm25_index is not None:
        document_result = bm25_index.search(
            doc_query,
            investigation_id="PSI-69",
            top_k=min(max(request.top_k, 1), 3),
            use_bilingual_aliases=request.use_bilingual_aliases,
        )
    else:
        warnings.append("corpus_unavailable: primary NASA PDF report index not loaded; report passages omitted.")

    citations: list[CitationItem] = []
    seen_cits: set[str] = set()
    artifact_sha = str(bundle.get("training_data_sha256", ""))
    model_cits = (
        ("MODEL:ridge_phys8", "ridge_phys8 burning-rate model estimate (NOT a NASA measurement)"),
        ("MODEL:logit_phys10", "logit_phys10 extinction score estimate (NOT a calibrated safety probability)"),
    )
    for cid, label in model_cits:
        seen_cits.add(cid)
        citations.append(
            CitationItem(
                citation_id=cid,
                source_type="model_prediction",
                investigation_id="PSI-69",
                locator_label=label,
                source_relpath=DEFAULT_MODEL_ARTIFACT_REL_PATH.as_posix(),
                source_sha256=artifact_sha,
                record_pk=cid,
            )
        )

    for rec in matched_records:
        cid = f"TBL:{rec.record_pk}"
        if cid in seen_cits:
            continue
        seen_cits.add(cid)
        citations.append(
            CitationItem(
                citation_id=cid,
                source_type="table_row",
                investigation_id=rec.investigation_id,
                locator_label=f"PSI-69 FLEX-{rec.test_id} CSV row (measured reference)",
                source_relpath=rec.source.source_relpath,
                source_sha256=rec.source.source_sha256,
                record_pk=rec.record_pk,
                csv_record_index=rec.source.csv_record_index,
                physical_line_start=rec.source.physical_line_start,
                physical_line_end=rec.source.physical_line_end,
            )
        )

    if document_result is not None:
        for hit in document_result.hits:
            cid = f"DOC:{hit.chunk_id}"
            if cid in seen_cits:
                continue
            seen_cits.add(cid)
            citations.append(
                CitationItem(
                    citation_id=cid,
                    source_type="document_chunk",
                    investigation_id=hit.investigation_id,
                    locator_label=f"{hit.document_id} § {hit.section_title} (p. {hit.printed_page_start or '?'})",
                    source_relpath=hit.source_relpath,
                    source_sha256=hit.source_sha256,
                    chunk_id=hit.chunk_id,
                    document_id=hit.document_id,
                    section_title=hit.section_title,
                    printed_page_start=hit.printed_page_start,
                    printed_page_end=hit.printed_page_end,
                    pdf_page_start=hit.pdf_page_start,
                    pdf_page_end=hit.pdf_page_end,
                    source_url=hit.source_url,
                )
            )

    compact_model_payload = {
        "model_version": pred_result["model_version"],
        "status": pred_result["status"],
        "normalized_input": pred_result["normalized_input"],
        "support_gate": {
            "supported": pred_result["support"]["supported"],
            "status": pred_result["support"]["status"],
            "reasons": pred_result["support"]["reasons"],
            "nearest_distance_std": pred_result["support"]["nearest_distance_std"],
            "distance_threshold_std": pred_result["support"]["distance_threshold_std"],
        },
        "model_estimates_only": pred_result["predictions"],
        "shapley_audit_note": (
            pred_result["local_explanations"]["note"]
            if isinstance(pred_result.get("local_explanations"), dict)
            else "No model estimates produced because condition is outside joint experimental support."
        ),
        "explanation_contract": (
            "CRITICAL: MODEL:* citations refer exclusively to ridge_phys8/logit_phys10 statistical estimates. "
            "TBL:* and DOC:* citations refer to NASA PSI-69 experimental rows and NASA/TP-2015-216046 passages. "
            "Never conflate model estimates with NASA measurements, never compute new numbers, and never issue fire-safety ratings."
        ),
    }

    return EvidenceBundle(
        request=request,
        mode=SERVICE_MODE_DETERMINISTIC,
        abstention=abstention,
        resolved_investigation_id="PSI-69",
        table_result=table_result,
        field_summary=None,
        comparison_result=None,
        document_result=document_result,
        citations=tuple(citations),
        warnings=tuple(warnings),
        disclaimers=(SERVICE_BOUNDARY_DISCLAIMER, BM25_SCORE_DISCLAIMER, bundle["disclaimer"]),
        flex_model_payload=compact_model_payload,
        coverage=assess_flex_predictor_coverage(pred_result),
    )
