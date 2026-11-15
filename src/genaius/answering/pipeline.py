"""Grounded answer orchestration: bounded LLM call, validation, numerical audit, safe fallback."""

from __future__ import annotations

from typing import Any

from ..numerical_audit import (
    FAILURE_INPUT_BUDGET,
    FAILURE_LLM_QUOTA,
    FAILURE_LLM_UNAVAILABLE,
    FAILURE_NONE,
    FAILURE_NUMERICAL_VALIDATION,
    FAILURE_OUTPUT_VALIDATION,
    NumericalAuditError,
    NumericalAuditReport,
    audit_grounded_answer_numbers,
    extract_bundle_facts,
)
from ..service import EvidenceBundle
from .adapter_input import (
    DEFAULT_MAX_ADAPTER_PASSAGE_CHARS,
    DEFAULT_MAX_ADAPTER_PASSAGES,
    DEFAULT_MAX_ADAPTER_PAYLOAD_CHARS,
    DEFAULT_MAX_ADAPTER_TABLE_ROWS,
    build_bounded_adapter_input,
)
from .deterministic import (
    _build_deterministic_core,
    _build_sources,
    _bundle_status,
    _evidence_overview,
    _serialize_bundle_coverage,
)
from .models import AdapterInputBudgetError, AdapterOutputValidationError, GroundedAnswer, GroundedLLMAdapter
from .validation import validate_llm_adapter_output


def generate_grounded_answer(
    bundle: EvidenceBundle,
    *,
    llm_adapter: GroundedLLMAdapter | None = None,
    max_table_rows: int = DEFAULT_MAX_ADAPTER_TABLE_ROWS,
    max_passages: int = DEFAULT_MAX_ADAPTER_PASSAGES,
    max_chars_per_passage: int = DEFAULT_MAX_ADAPTER_PASSAGE_CHARS,
    max_payload_chars: int = DEFAULT_MAX_ADAPTER_PAYLOAD_CHARS,
) -> GroundedAnswer:
    """Build a traceable grounded answer from `bundle`, falling back deterministically on failure."""

    if llm_adapter is None or bundle.abstention.abstained:
        return _build_deterministic_core(bundle, answer_mode="deterministic")

    bundle_facts, fact_meta = extract_bundle_facts(bundle)
    failure_reason = FAILURE_NONE
    audit_override: dict[str, Any] | None = None
    fallback_note = ""

    try:
        adapter_input = build_bounded_adapter_input(
            bundle,
            max_table_rows=max_table_rows,
            max_passages=max_passages,
            max_chars_per_passage=max_chars_per_passage,
            max_payload_chars=max_payload_chars,
        )
        raw_output = llm_adapter.generate(adapter_input)
        summary, findings, llm_limitations = validate_llm_adapter_output(
            raw_output,
            allowed_citation_ids=adapter_input.allowed_citation_ids,
        )
        audit_report = audit_grounded_answer_numbers(
            summary=summary,
            findings=[f.to_dict() for f in findings],
            bundle=bundle,
            facts=bundle_facts,
            metadata=fact_meta,
        )
    except NumericalAuditError as exc:
        failure_reason = FAILURE_NUMERICAL_VALIDATION
        diag = {
            "category": failure_reason,
            "diagnosis_code": "NUMERICAL_AUDIT_MISMATCH",
            "field_path": "$.summary|$.findings",
            "expected": "all cited numbers and units verified against bundle facts",
            "observed": f"{len(exc.issues)} issue(s)",
            "message": str(exc),
        }
        fallback_note = f"llm_fallback: numerical_audit_failed: {exc}"
        audit_override = NumericalAuditReport(
            status="failed_fallback",
            audited_fields=("summary", "findings"),
            checked_facts_count=len(bundle_facts),
            matched_fact_ids=(),
            issues=exc.issues,
        ).to_dict()
        return _build_deterministic_core(
            bundle,
            extra_limitations=(),
            extra_warnings=(fallback_note,),
            answer_mode="deterministic_fallback",
            failure_reason=failure_reason,
            numerical_audit_override=audit_override,
            validation_diagnostics=diag,
        )
    except AdapterOutputValidationError as exc:
        failure_reason = FAILURE_OUTPUT_VALIDATION
        diag = exc.to_dict()
        fallback_note = f"llm_fallback: {exc.diagnosis_code} at {exc.field_path}: {exc}"
        return _build_deterministic_core(
            bundle,
            extra_limitations=(),
            extra_warnings=(fallback_note,),
            answer_mode="deterministic_fallback",
            failure_reason=failure_reason,
            validation_diagnostics=diag,
        )
    except AdapterInputBudgetError as exc:
        failure_reason = FAILURE_INPUT_BUDGET
        diag = {
            "category": failure_reason,
            "diagnosis_code": "INPUT_BUDGET_EXCEEDED",
            "field_path": "$input",
            "expected": f"payload <= {max_payload_chars} chars with >= 1 citation",
            "observed": str(exc),
            "message": str(exc),
        }
        fallback_note = f"llm_fallback: input_budget_exceeded: {exc}"
        return _build_deterministic_core(
            bundle,
            extra_limitations=(),
            extra_warnings=(fallback_note,),
            answer_mode="deterministic_fallback",
            failure_reason=failure_reason,
            validation_diagnostics=diag,
        )
    except Exception as exc:
        if getattr(exc, "status_code", None) == 429:
            failure_reason = FAILURE_LLM_QUOTA
            diag = {
                "category": failure_reason,
                "diagnosis_code": "HTTP_429",
                "field_path": "$provider",
                "expected": "HTTP 200 completion",
                "observed": "HTTP 429 rate/quota limit",
                "message": "Upstream OpenRouter provider returned HTTP 429 (quota or rate limit exceeded).",
            }
            fallback_note = (
                "llm_fallback: llm_quota_exceeded: Upstream OpenRouter provider returned HTTP 429."
            )
        else:
            failure_reason = FAILURE_LLM_UNAVAILABLE
            err_kind = type(exc).__name__
            status_code = getattr(exc, "status_code", None)
            observed_label = (
                f"{err_kind} (HTTP {status_code})" if status_code is not None else err_kind
            )
            diag = {
                "category": failure_reason,
                "diagnosis_code": err_kind,
                "field_path": "$provider",
                "expected": "valid provider completion response",
                "observed": observed_label,
                "message": f"Configured LLM adapter failed ({err_kind}).",
            }
            fallback_note = f"llm_fallback: {err_kind}: Configured LLM adapter failed or was unreachable."
        return _build_deterministic_core(
            bundle,
            extra_limitations=(),
            extra_warnings=(fallback_note,),
            answer_mode="deterministic_fallback",
            failure_reason=failure_reason,
            validation_diagnostics=diag,
        )

    limitations = list(llm_limitations)
    for note in adapter_input.truncation_notes:
        if note not in limitations:
            limitations.append(note)
    if not adapter_input.allowed_citation_ids:
        note = "No row-level or chunk-level citation_ids were emitted for this summary-only bundle."
        if note not in limitations:
            limitations.append(note)

    return GroundedAnswer(
        status=_bundle_status(bundle),
        answer_mode="llm",
        llm_used=True,
        resolved_investigation_id=bundle.resolved_investigation_id,
        summary=summary,
        findings=findings,
        limitations=tuple(limitations),
        warnings=bundle.warnings,
        disclaimers=bundle.disclaimers,
        sources=_build_sources(bundle),
        citation_ids=tuple(c.citation_id for c in bundle.citations),
        abstention=bundle.abstention.to_dict(),
        evidence_overview=_evidence_overview(bundle),
        coverage=_serialize_bundle_coverage(bundle),
        numerical_audit=audit_report.to_dict(),
        failure_reason=FAILURE_NONE,
    )
