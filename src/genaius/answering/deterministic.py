"""Deterministic, evidence-only answer composition (no LLM) and shared source/coverage views."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from ..retrieval.bm25 import RetrievalHit
from ..schemas.llm_output import RECOMMENDED_FINDINGS_COUNT
from ..service import EvidenceBundle
from .models import AnswerFinding, GroundedAnswer, SourceReference


def _bundle_status(bundle: EvidenceBundle) -> str:
    if bundle.abstention.abstained:
        return "NO_EVIDENCE" if bundle.abstention.reason_code == "NO_MATCHING_EVIDENCE" else "ABSTAINED"
    return "OK"


def _build_sources(bundle: EvidenceBundle) -> tuple[SourceReference, ...]:
    hit_urls: dict[str, str] = {}
    if bundle.document_result is not None:
        for hit in bundle.document_result.hits:
            hit_urls[hit.chunk_id] = hit.source_url

    sources: list[SourceReference] = []
    for cit in bundle.citations:
        sources.append(
            SourceReference(
                citation_id=cit.citation_id,
                source_type=cit.source_type,
                investigation_id=cit.investigation_id,
                locator_label=cit.locator_label,
                source_relpath=cit.source_relpath,
                source_sha256=cit.source_sha256,
                record_pk=cit.record_pk,
                csv_record_index=cit.csv_record_index,
                physical_line_start=cit.physical_line_start,
                physical_line_end=cit.physical_line_end,
                chunk_id=cit.chunk_id,
                document_id=cit.document_id,
                section_title=cit.section_title,
                printed_page_start=cit.printed_page_start,
                printed_page_end=cit.printed_page_end,
                pdf_page_start=cit.pdf_page_start,
                pdf_page_end=cit.pdf_page_end,
                source_url=hit_urls.get(cit.chunk_id) if cit.chunk_id is not None else getattr(cit, "source_url", None),
            )
        )
    return tuple(sources)


def _evidence_overview(bundle: EvidenceBundle) -> dict[str, Any]:
    table_cits = [c for c in bundle.citations if c.source_type == "table_row"]
    return {
        "table_total_runs": bundle.table_result.total_runs if bundle.table_result is not None else 0,
        "table_shown_runs": len(table_cits) if bundle.table_result is not None else 0,
        "has_field_summary": bundle.field_summary is not None,
        "has_comparison": bundle.comparison_result is not None,
        "document_hits_returned": (
            bundle.document_result.total_hits_returned if bundle.document_result is not None else 0
        ),
    }


def _short_excerpt(text: str, *, limit: int = 240) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


def _hit_page_label(hit: RetrievalHit) -> str:
    parts: list[str] = []
    if hit.printed_page_start is not None:
        if hit.printed_page_end and hit.printed_page_end != hit.printed_page_start:
            parts.append(f"printed p. {hit.printed_page_start}-{hit.printed_page_end}")
        else:
            parts.append(f"printed p. {hit.printed_page_start}")
    if hit.pdf_page_start is not None:
        if hit.pdf_page_end and hit.pdf_page_end != hit.pdf_page_start:
            parts.append(f"PDF p. {hit.pdf_page_start}-{hit.pdf_page_end}")
        else:
            parts.append(f"PDF p. {hit.pdf_page_start}")
    return ", ".join(parts) if parts else "page recorded in metadata"


def _format_table_finding(bundle: EvidenceBundle, available_cits: set[str]) -> AnswerFinding | None:
    table = bundle.table_result
    if table is None:
        return None
    counts = ", ".join(f"{inv}: {cnt}" for inv, cnt in sorted(table.counts_by_investigation.items())) or "none"
    id_bits: list[str] = []
    if table.unique_sample_count is not None:
        id_bits.append(f"{table.unique_sample_count} unique Sample IDs")
    if table.unique_flex_identifier_count is not None:
        id_bits.append(f"{table.unique_flex_identifier_count} unique FLEX identifiers")
    id_note = f" ({'; '.join(id_bits)})" if id_bits else ""

    record_cits = [
        f"TBL:{r.record_pk}" for r in table.records if f"TBL:{r.record_pk}" in available_cits
    ]
    cited_count = len(record_cits)
    if cited_count < table.total_runs:
        subset_note = f"citing a truncated subset of {cited_count} of {table.total_runs} total matching records"
    else:
        subset_note = f"citing all {cited_count} of {table.total_runs} matching records"

    text = f"Matched {table.total_runs} verified table runs [{counts}]{id_note}; {subset_note}."
    return AnswerFinding(text=text, citation_ids=tuple(record_cits))


def _format_summary_finding(bundle: EvidenceBundle, available_cits: set[str]) -> AnswerFinding | None:
    summary = bundle.field_summary
    if summary is None:
        return None

    non_zero_excl = {k: v for k, v in summary.excluded_by_status.items() if v > 0}
    excl_note = (
        ", ".join(f"{k}={v}" for k, v in sorted(non_zero_excl.items())) if non_zero_excl else "none"
    )
    if summary.used_total_count > 0:
        stats = (
            f"mean={summary.mean_value:g}, min={summary.min_value:g}, max={summary.max_value:g} "
            f"{summary.unit}"
        )
    else:
        stats = "no finite measured observations available for mean/min/max"

    cited = tuple(
        f"TBL:{pk}" for pk in summary.used_record_pks if f"TBL:{pk}" in available_cits
    )
    prov = f" Source definition: {summary.provenance}" if summary.provenance else ""
    text = (
        f"Field summary for {summary.investigation_id} `{summary.field_name}` ({summary.unit}): "
        f"{summary.used_measured_count} measured and {summary.used_approximate_count} approximate runs "
        f"used out of {summary.candidate_run_count} candidate runs ({stats}); excluded: {excl_note}.{prov}"
    )
    return AnswerFinding(text=text, citation_ids=cited)


def _format_comparison_finding(bundle: EvidenceBundle, available_cits: set[str]) -> AnswerFinding | None:
    comp = bundle.comparison_result
    if comp is None:
        return None
    cited = tuple(
        f"TBL:{pk}" for pk in comp.requested_record_pks if f"TBL:{pk}" in available_cits
    )
    pks = ", ".join(comp.requested_record_pks)
    fields = ", ".join(comp.field_names[:8]) + ("..." if len(comp.field_names) > 8 else "")
    text = (
        f"Side-by-side comparison of {len(comp.rows)} requested runs ({pks}) across fields "
        f"[{fields}] preserves per-study native measurements without safety ranking."
    )
    return AnswerFinding(text=text, citation_ids=cited)


def _format_case_findings(bundle: EvidenceBundle, available_cits: set[str]) -> list[AnswerFinding]:
    cp = bundle.case_payload
    if not isinstance(cp, Mapping):
        return []
    findings: list[AnswerFinding] = []
    recs = [r for r in cp.get("records", ()) if isinstance(r, Mapping)]
    if len(recs) == 1:
        r = recs[0]
        tid = str(r.get("test_id", ""))
        cid = f"CASE-TBL:{tid}"
        rec_cits = (cid,) if cid in available_cits else ()
        flow_steps = [str(s) for s in r.get("flow_steps", ()) if str(s).strip()]
        init_flow = r.get("initial_air_flow_cm_s")
        flow_dir = r.get("flow_direction")
        flow_txt = (
            f"initial flow {init_flow} cm/s ({flow_dir}; protocol: {'; '.join(flow_steps)})"
            if flow_steps
            else f"initial flow {init_flow} cm/s ({flow_dir})"
        )
        cond_txt = (
            f"Saffire {tid} ({r.get('flight')}, {r.get('material')}) conditions: "
            f"ambient pressure {r.get('ambient_pressure_kpa')} kPa, {r.get('oxygen_mol_percent')}% O2 "
            f"(derived pO2 = {r.get('derived_po2_kpa')} kPa), free volume {r.get('free_volume_m3')} m^3, "
            f"{flow_txt}."
        )
        findings.append(AnswerFinding(text=cond_txt, citation_ids=rec_cits))
        if r.get("gas_calorimetry_reported"):
            burn_s = r.get("burn_duration_s")
            burn_txt = f" burn_duration={burn_s} s," if burn_s is not None else ""
            hrr_w = r.get("o2_peak_heat_release_w")
            hrr_kj = r.get("o2_total_heat_release_kj")
            cal_txt = (
                f" O2-calorimetry peak HRR={hrr_w} W / total={hrr_kj} kJ."
                if (hrr_w is not None and hrr_kj is not None)
                else ""
            )
            gas_txt = (
                f"Saffire {tid} measured post-fire changes:{burn_txt} "
                f"ΔCO2={r.get('co2_increase_ppm')} ppm ({r.get('co2_partial_pressure_increase_mmhg')} mmHg), "
                f"ΔCO={r.get('co_increase_ppm')} ppm.{cal_txt}"
            )
        else:
            gas_txt = (
                f"Saffire {tid} gas/calorimetry fields were not reported in the retrieved tables "
                "(strictly null; never coerced to 0)."
            )
        findings.append(AnswerFinding(text=gas_txt, citation_ids=rec_cits))
    elif recs:
        reported_parts: list[str] = []
        missing_ids: list[str] = []
        rec_cits: list[str] = []
        for r in recs:
            tid = str(r.get("test_id", ""))
            cid = f"CASE-TBL:{tid}"
            if cid in available_cits:
                rec_cits.append(cid)
            if r.get("gas_calorimetry_reported"):
                co2_mmhg = r.get("co2_partial_pressure_increase_mmhg")
                co_ppm = r.get("co_increase_ppm")
                po2 = r.get("derived_po2_kpa")
                reported_parts.append(
                    f"{tid} ({r.get('material')}: pO2_derived={po2} kPa, "
                    f"ΔCO2={r.get('co2_increase_ppm')} ppm/{co2_mmhg} mmHg, ΔCO={co_ppm} ppm)"
                )
            else:
                missing_ids.append(tid)
        bits: list[str] = []
        if reported_parts:
            bits.append("; ".join(reported_parts))
        if missing_ids:
            bits.append(
                f"unreported gas/calorimetry fields (strict null) for {', '.join(missing_ids)}"
            )
        findings.append(
            AnswerFinding(
                text=f"SAFFIRE IV–VI verified records ({len(recs)} matched): " + " | ".join(bits) + ".",
                citation_ids=tuple(rec_cits),
            )
        )

    for det in cp.get("detection_evidence", ()):
        if not isinstance(det, Mapping):
            continue
        eid = str(det.get("evidence_id", ""))
        cid = f"CASE-DET:{eid}"
        cits = (cid,) if cid in available_cits else ()
        derived_note = ""
        dm = det.get("derived_metrics")
        if isinstance(dm, Mapping) and isinstance(dm.get("elapsed_ignition_to_threshold_s"), Mapping):
            dval = dm["elapsed_ignition_to_threshold_s"].get("value")
            if dval is not None:
                derived_note = (
                    f" Derived elapsed time (ignition->threshold) = {dval:g} s "
                    "(981 s - 637 s; derived from authors' selected 1 mg/m^3 threshold)."
                )
        findings.append(
            AnswerFinding(
                text=f"{det.get('title')}: {det.get('summary')}{derived_note}",
                citation_ids=cits,
            )
        )
    return findings


# Case answers lead with the finding that matches the question's topic, so the reader sees the answer
# before the provenance note. Plain keyword routing; no finding text is rewritten.
_CASE_TOPIC_RULES: tuple[tuple[re.Pattern[str], re.Pattern[str]], ...] = (
    (re.compile(r"\b(smoke|detect\w*|alarm|threshold|when|how long|981|344)\b", re.I), re.compile(r"981|threshold", re.I)),
    (re.compile(r"\b(particle\w*|aerosol\w*|pm1|same|fortenberry|size)\b", re.I), re.compile(r"particle|aerosol|PM1", re.I)),
    (re.compile(r"\b(co2?|carbon|gas\w*|emission\w*|limit\w*|smac)\b", re.I), re.compile(r"ΔCO|gas/calorimetry|ΔCO2", re.I)),
    (re.compile(r"\b(pressure|oxygen|o2|condition\w*|flow|volume)\b", re.I), re.compile(r"conditions:", re.I)),
)


def _lead_case_finding(query: str | None, case_findings: list[AnswerFinding]) -> list[AnswerFinding]:
    if not query or len(case_findings) < 2:
        return case_findings
    for q_re, f_re in _CASE_TOPIC_RULES:
        if q_re.search(query):
            for idx, f in enumerate(case_findings):
                if f_re.search(f.text):
                    return [f] + case_findings[:idx] + case_findings[idx + 1:]
            break
    return case_findings


def _lead_sentence(text: str, limit: int = 260) -> str:
    """First sentence of a finding, cut on a '; ' boundary when it runs long; the full text stays in findings."""
    head = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
    if len(head) <= limit:
        return head
    cut = head.rfind("; ", 0, limit)
    return (head[:cut] if cut > 0 else head[:limit].rstrip()) + " …"


def _format_flex_model_findings(bundle: EvidenceBundle, available_cits: set[str]) -> list[AnswerFinding]:
    mp = bundle.flex_model_payload
    if not isinstance(mp, Mapping):
        return []
    findings: list[AnswerFinding] = []
    ni = mp.get("normalized_input", {})
    sup = mp.get("support_gate", {})
    preds = mp.get("model_estimates_only")
    reg_cits = ("MODEL:ridge_phys8",) if "MODEL:ridge_phys8" in available_cits else ()
    clf_cits = ("MODEL:logit_phys10",) if "MODEL:logit_phys10" in available_cits else ()
    if mp.get("status") == "NOT_SUPPORTED" or not isinstance(preds, Mapping):
        reasons = "; ".join(sup.get("reasons", ())) or "outside joint PSI-69 experimental support"
        both_cits = tuple(c for c in ("MODEL:ridge_phys8", "MODEL:logit_phys10") if c in available_cits)
        findings.append(
            AnswerFinding(
                text=(
                    f"Model estimates withheld (NOT_SUPPORTED) for {ni.get('fuel')} at O2={ni.get('o2_mol_frac')}, "
                    f"CO2={ni.get('co2_mol_frac')}, He={ni.get('he_mol_frac')}, P={ni.get('pressure_mmhg')} mmHg, "
                    f"d0={ni.get('droplet_initial_diameter_mm')} mm: {reasons}."
                ),
                citation_ids=both_cits,
            )
        )
        return findings

    br = preds.get("burning_rate_mm2_s", {})
    if isinstance(br, Mapping):
        findings.append(
            AnswerFinding(
                text=(
                    f"Model estimate ONLY (ridge_phys8 L2 linear regression, NOT NASA measurement): predicted burning-rate "
                    f"constant K = {br.get('value')} mm^2/s (grouped-CV atm+P MAE={br.get('group_cv_mae')}, "
                    f"RMSE={br.get('group_cv_rmse')}, R^2={br.get('group_cv_r2')})."
                ),
                citation_ids=reg_cits,
            )
        )
    ex = preds.get("extinction_likelihood", {})
    if isinstance(ex, Mapping):
        findings.append(
            AnswerFinding(
                text=(
                    f"Model estimate ONLY (logit_phys10 empirical score, NOT calibrated fire-safety probability): "
                    f"score = {ex.get('score')} -> {ex.get('predicted_label')} (threshold {ex.get('decision_threshold')}; "
                    f"grouped-CV ROC-AUC={ex.get('group_cv_roc_auc')}, Brier={ex.get('group_cv_brier')}; "
                    f"{ex.get('calibration_warning')})."
                ),
                citation_ids=clf_cits,
            )
        )
    audit_note = mp.get("shapley_audit_note")
    if isinstance(audit_note, str) and audit_note:
        both_cits = tuple(c for c in ("MODEL:ridge_phys8", "MODEL:logit_phys10") if c in available_cits)
        findings.append(AnswerFinding(text=f"Explanation audit boundary: {audit_note}", citation_ids=both_cits))
    return findings


def _format_document_findings(bundle: EvidenceBundle, available_cits: set[str]) -> list[AnswerFinding]:
    doc = bundle.document_result
    if doc is None or not doc.hits:
        return []
    findings: list[AnswerFinding] = []
    for hit in doc.hits:
        cid = f"DOC:{hit.chunk_id}"
        cits = (cid,) if cid in available_cits else ()
        excerpt = _short_excerpt(hit.source_text)
        pages = _hit_page_label(hit)
        text = (
            f'Related source passage (BM25 lexical rank #{hit.rank}, {hit.document_id} § '
            f'{hit.section_title}, {pages}): "{excerpt}"'
        )
        findings.append(AnswerFinding(text=text, citation_ids=cits))
    return findings


def _serialize_bundle_coverage(bundle: EvidenceBundle) -> dict[str, Any] | None:
    cov = getattr(bundle, "coverage", None)
    if cov is None:
        return None
    if hasattr(cov, "to_dict"):
        return cov.to_dict()
    if isinstance(cov, Mapping):
        return dict(cov)
    return None


def _build_deterministic_core(
    bundle: EvidenceBundle,
    *,
    extra_limitations: Sequence[str] = (),
    extra_warnings: Sequence[str] = (),
    answer_mode: str = "deterministic",
    failure_reason: str = "NONE",
    numerical_audit_override: dict[str, Any] | None = None,
    validation_diagnostics: Mapping[str, Any] | None = None,
) -> GroundedAnswer:
    from ..numerical_audit import NumericalAuditReport, extract_bundle_facts

    status = _bundle_status(bundle)
    sources = _build_sources(bundle)
    available_cits = {c.citation_id for c in bundle.citations}
    all_cits = tuple(c.citation_id for c in bundle.citations)
    overview = _evidence_overview(bundle)
    cov_dict = _serialize_bundle_coverage(bundle)
    if numerical_audit_override is not None:
        audit_dict = numerical_audit_override
    else:
        bundle_facts, _ = extract_bundle_facts(bundle)
        audit_dict = NumericalAuditReport(
            status="not_applicable_deterministic",
            audited_fields=(),
            checked_facts_count=len(bundle_facts),
            matched_fact_ids=(),
            issues=(),
            disclaimer="Deterministic template mode: all values come directly from verified Python calculations and citations without LLM prose.",
        ).to_dict()

    limitations: list[str] = list(extra_limitations)
    warnings: list[str] = list(bundle.warnings)
    for w in extra_warnings:
        if w and w not in warnings:
            warnings.append(w)

    def _add_limit(msg: str) -> None:
        if msg and msg not in limitations:
            limitations.append(msg)

    if bundle.abstention.abstained:
        reason = bundle.abstention.reason_code or "ABSTAINED"
        explanation = bundle.abstention.explanation or "Request outside verified evidence contract."
        if status == "NO_EVIDENCE":
            summary = f"No matching verified evidence found in the active indexed scope ({reason})."
            boundary_note = (
                "No records matched the active filters or indexed excerpts; broaden filters or switch scope instead of extrapolating."
            )
        else:
            summary = f"Request withheld by scope or safety guardrail ({reason})."
            if reason == "V12_OUT_OF_SCOPE_STUDY":
                boundary_note = (
                    "Core Q&A stays restricted to PSI-25 (BASS-II) and PSI-69 (FLEX). "
                    "Switch to SAFFIRE IV–VI Case Study for cabin-air Q&A or Data Explorer (#s-saffire) for PSI-99 cards."
                )
            else:
                boundary_note = (
                    "This guardrail stopped before any LLM call; no external claims or extrapolations were generated."
                )
        _add_limit(boundary_note)
        if any(w.startswith("corpus_unavailable:") for w in bundle.warnings):
            _add_limit("Primary report corpus was unavailable; missing document text was not filled from prior knowledge.")
        return GroundedAnswer(
            status=status,
            answer_mode=answer_mode,
            llm_used=False,
            resolved_investigation_id=bundle.resolved_investigation_id,
            summary=summary,
            findings=(),
            limitations=tuple(limitations),
            warnings=tuple(warnings),
            disclaimers=bundle.disclaimers,
            sources=sources,
            citation_ids=all_cits,
            abstention=bundle.abstention.to_dict(),
            evidence_overview=overview,
            coverage=cov_dict,
            numerical_audit=audit_dict,
            failure_reason=failure_reason,
        )

    findings: list[AnswerFinding] = []
    for builder in (_format_table_finding, _format_summary_finding, _format_comparison_finding):
        item = builder(bundle, available_cits)
        if item is not None:
            findings.append(item)
    case_findings = _lead_case_finding(
        getattr(bundle.request, "query", None), _format_case_findings(bundle, available_cits)
    )
    findings.extend(case_findings)
    findings.extend(_format_flex_model_findings(bundle, available_cits))
    doc_findings = _format_document_findings(bundle, available_cits)
    if case_findings:
        remaining_slots = max(0, RECOMMENDED_FINDINGS_COUNT - len(findings))
        findings.extend(doc_findings[:remaining_slots])
    else:
        findings.extend(doc_findings)

    summary_parts: list[str] = []
    if isinstance(bundle.case_payload, Mapping):
        crecs = bundle.case_payload.get("records", ())
        summary_parts.append(f"evaluated {len(crecs)} SAFFIRE IV–VI case records with deterministic Python derivations")
    if isinstance(bundle.flex_model_payload, Mapping):
        summary_parts.append(
            f"paired pre-test FLEX model verdict ({bundle.flex_model_payload.get('status')}) with nearest PSI-69 reference runs"
        )
    if bundle.table_result is not None:
        shown = overview["table_shown_runs"]
        total = bundle.table_result.total_runs
        if shown < total:
            summary_parts.append(f"matched {total} verified table runs (showing {shown} cited rows)")
        else:
            summary_parts.append(f"matched {total} verified table runs")
    if bundle.field_summary is not None:
        fs = bundle.field_summary
        if fs.used_total_count > 0:
            summary_parts.append(
                f"summarized {fs.field_name} (mean {fs.mean_value:g} {fs.unit} across {fs.used_total_count} runs)"
            )
        else:
            summary_parts.append(f"found 0 usable values for {fs.field_name}")
    if bundle.comparison_result is not None:
        summary_parts.append(f"compared {len(bundle.comparison_result.rows)} runs")
    if bundle.document_result is not None and bundle.document_result.total_hits_returned > 0:
        summary_parts.append(
            f"retrieved {bundle.document_result.total_hits_returned} related NASA report passages (BM25 excerpts only)"
        )

    scope_label = bundle.resolved_investigation_id or "PSI-25 / PSI-69"
    joined_parts = "; ".join(summary_parts) if summary_parts else "verified evidence retrieved"
    if answer_mode == "deterministic_fallback":
        summary = f"Deterministic fallback {scope_label} summary (no LLM synthesis used): {joined_parts}."
    else:
        summary = f"Deterministic {scope_label} evidence summary (offline, no LLM): {joined_parts}."
    if case_findings:
        # Answer first, provenance second: the case reader sees the finding before the pipeline note.
        summary = f"{_lead_sentence(case_findings[0].text)} ({summary[0].lower()}{summary[1:]})"

    if bundle.table_result is not None and overview["table_shown_runs"] < bundle.table_result.total_runs:
        _add_limit(
            f"Table citations include only the first {overview['table_shown_runs']} of "
            f"{bundle.table_result.total_runs} matching runs (controlled by max_table_citations)."
        )
    if bundle.document_result is not None and bundle.document_result.total_hits_returned > 0:
        _add_limit(
            "Report passages are BM25 lexical matches presented as excerpts rather than verified scientific answers; inspect cited PDF/printed pages."
        )
    if isinstance(bundle.case_payload, Mapping):
        related_cards = bundle.case_payload.get("related_research")
        if isinstance(related_cards, Sequence) and not isinstance(related_cards, (str, bytes)) and related_cards:
            _add_limit(
                "Background SAME/IV–V aerosol studies are held separately under Related research; ask about smoke particles or SAME to inspect them directly."
            )
    if any(w.startswith("corpus_unavailable:") for w in bundle.warnings):
        _add_limit(
            "Primary report index was unavailable; document passages were omitted and gaps were not filled from model memory."
        )
    if bundle.comparison_result is not None:
        _add_limit(bundle.comparison_result.boundary_note)
    if not available_cits and findings:
        _add_limit("No row-level or chunk-level citation_ids were emitted for this summary-only bundle.")
    if answer_mode == "deterministic":
        _add_limit("Generated deterministically from verified NASA records and indexed passages without an external LLM.")

    return GroundedAnswer(
        status=status,
        answer_mode=answer_mode,
        llm_used=False,
        resolved_investigation_id=bundle.resolved_investigation_id,
        summary=summary,
        findings=tuple(findings),
        limitations=tuple(limitations),
        warnings=tuple(warnings),
        disclaimers=bundle.disclaimers,
        sources=sources,
        citation_ids=all_cits,
        abstention=bundle.abstention.to_dict(),
        evidence_overview=overview,
        coverage=cov_dict,
        numerical_audit=audit_dict,
        failure_reason=failure_reason,
        validation_diagnostics=(
            dict(validation_diagnostics) if isinstance(validation_diagnostics, Mapping) else None
        ),
    )
