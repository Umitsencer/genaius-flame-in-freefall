"""Answer data types, the provider-agnostic adapter protocol and validation errors."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

OUT_DIAG_INVALID_JSON = "INVALID_JSON"
OUT_DIAG_WRONG_TYPE = "WRONG_TYPE"
OUT_DIAG_UNEXPECTED_KEY = "UNEXPECTED_KEY"
OUT_DIAG_MISSING_FIELD = "MISSING_REQUIRED_FIELD"
OUT_DIAG_LIMIT_EXCEEDED = "CHAR_OR_COUNT_LIMIT"
OUT_DIAG_EMPTY_CITATIONS = "EMPTY_CITATIONS"
OUT_DIAG_DISALLOWED_CITATION = "DISALLOWED_CITATION"


@dataclass(frozen=True)
class AdapterPromptInput:
    """Strictly bounded data payload passed to a provider-agnostic LLM adapter."""

    user_query: str
    evidence_payload: dict[str, Any]
    allowed_citation_ids: tuple[str, ...]
    system_rules: tuple[str, ...]
    truncated: bool
    truncation_notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_query": self.user_query,
            "evidence_payload": self.evidence_payload,
            "allowed_citation_ids": list(self.allowed_citation_ids),
            "system_rules": list(self.system_rules),
            "truncated": self.truncated,
            "truncation_notes": list(self.truncation_notes),
        }


class GroundedLLMAdapter(Protocol):
    """Provider-agnostic interface for grounded explanation adapters."""

    def generate(self, adapter_input: AdapterPromptInput) -> str | Mapping[str, Any]:
        """Return JSON text or a mapping matching `{summary, findings, limitations}`."""


@dataclass(frozen=True)
class AnswerFinding:
    """Single answer claim or excerpt paired with exact bundle citation IDs."""

    text: str
    citation_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "citation_ids": list(self.citation_ids),
        }


@dataclass(frozen=True)
class SourceReference:
    """Verifiable source record with full CSV/PDF locators and NTRS URL when present."""

    citation_id: str
    source_type: str
    investigation_id: str
    locator_label: str
    source_relpath: str
    source_sha256: str
    record_pk: str | None = None
    csv_record_index: int | None = None
    physical_line_start: int | None = None
    physical_line_end: int | None = None
    chunk_id: str | None = None
    document_id: str | None = None
    section_title: str | None = None
    printed_page_start: str | None = None
    printed_page_end: str | None = None
    pdf_page_start: int | None = None
    pdf_page_end: int | None = None
    source_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "source_type": self.source_type,
            "investigation_id": self.investigation_id,
            "locator_label": self.locator_label,
            "source_relpath": self.source_relpath,
            "source_sha256": self.source_sha256,
            "record_pk": self.record_pk,
            "csv_record_index": self.csv_record_index,
            "physical_line_start": self.physical_line_start,
            "physical_line_end": self.physical_line_end,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "section_title": self.section_title,
            "printed_page_start": self.printed_page_start,
            "printed_page_end": self.printed_page_end,
            "pdf_page_start": self.pdf_page_start,
            "pdf_page_end": self.pdf_page_end,
            "source_url": self.source_url,
        }


@dataclass(frozen=True)
class GroundedAnswer:
    """Structured evidence-backed response envelope payload."""

    status: str
    answer_mode: str
    llm_used: bool
    resolved_investigation_id: str | None
    summary: str
    findings: tuple[AnswerFinding, ...]
    limitations: tuple[str, ...]
    warnings: tuple[str, ...]
    disclaimers: tuple[str, ...]
    sources: tuple[SourceReference, ...]
    citation_ids: tuple[str, ...]
    abstention: dict[str, Any]
    evidence_overview: dict[str, Any]
    coverage: dict[str, Any] | None = None
    numerical_audit: dict[str, Any] | None = None
    failure_reason: str = "NONE"
    validation_diagnostics: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "answer_mode": self.answer_mode,
            "llm_used": self.llm_used,
            "resolved_investigation_id": self.resolved_investigation_id,
            "summary": self.summary,
            "findings": [item.to_dict() for item in self.findings],
            "limitations": list(self.limitations),
            "warnings": list(self.warnings),
            "disclaimers": list(self.disclaimers),
            "sources": [src.to_dict() for src in self.sources],
            "citation_ids": list(self.citation_ids),
            "abstention": dict(self.abstention),
            "evidence_overview": dict(self.evidence_overview),
            "coverage": dict(self.coverage) if isinstance(self.coverage, Mapping) else None,
            "numerical_audit": dict(self.numerical_audit) if isinstance(self.numerical_audit, Mapping) else None,
            "failure_reason": self.failure_reason,
            "validation_diagnostics": (
                dict(self.validation_diagnostics)
                if isinstance(self.validation_diagnostics, Mapping)
                else None
            ),
        }


class AdapterOutputValidationError(ValueError):
    """Raised when an LLM adapter output violates schema, bounds, or citation rules."""

    def __init__(
        self,
        message: str,
        *,
        diagnosis_code: str = OUT_DIAG_INVALID_JSON,
        field_path: str = "$",
        expected: str = "",
        observed: str = "",
    ) -> None:
        self.diagnosis_code = str(diagnosis_code)
        self.field_path = str(field_path)
        self.expected = str(expected)
        self.observed = str(observed)
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """Return structured, secret-free diagnostic details without raw prompts."""
        return {
            "category": "OUTPUT_VALIDATION_FAILED",
            "diagnosis_code": self.diagnosis_code,
            "field_path": self.field_path,
            "expected": self.expected,
            "observed": self.observed,
            "message": str(self),
        }


class AdapterInputBudgetError(ValueError):
    """Raised when the bounded evidence payload cannot fit within `max_payload_chars`."""
