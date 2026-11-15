"""Paket D: Service combining typed table evidence and BM25 document passages.

This module wraps the deterministic table query layer (`genaius.data.query`) and
section-level BM25 retrieval (`genaius.retrieval.bm25`) into a single traceable
`EvidenceBundle`:
- Numeric calculations come strictly from the typed table layer.
- BM25 lexical scores and table values are never turned into a fire-risk score.
- Out-of-scope studies, extinction-diameter (`d_ext`) cool-flame classification
  (`V10`), and CO-based crew toxicity scoring (`V11`) are deterministically
  rejected by `evaluate_abstention_gate` without speculative answers.
- Fully functional offline without an LLM/API key (`mode="deterministic_fallback"`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .claim_boundary import SOURCE_SCOPE_NOTE, asks_crew_harm, asks_gravity_transfer, asks_safety_judgment
from .data.contracts import DATASET_SPECS, ExperimentRecord
from .data.loader import load_core_datasets
from .data.query import (
    COMPARISON_BOUNDARY_NOTE,
    ComparisonResult,
    FieldSummary,
    NumericRangeFilter,
    QueryResult,
    QueryValidationError,
    _serialize_measurement,
    _serialize_record_summary,
    compare_records,
    filter_records,
    get_allowed_fields,
    summarize_field,
)
from .retrieval.bm25 import (
    BILINGUAL_SCOPE_NOTE,
    BM25_SCORE_DISCLAIMER,
    BM25Index,
    RetrievalHit,
    RetrievalValidationError,
    SearchResult,
    build_bm25_index,
)
from .retrieval.documents import DocumentChunk, RetrievalDocumentError, load_retrieval_corpus

VALID_INVESTIGATION_IDS: frozenset[str] = frozenset(DATASET_SPECS.keys())

SERVICE_MODE_DETERMINISTIC = "deterministic_fallback"

SERVICE_BOUNDARY_DISCLAIMER = (
    "This bundle combines only verified PSI-25 (BASS-II) and PSI-69 (FLEX) table "
    "records with primary NASA report passages; it does not produce a fire-risk score, "
    "safety ranking, or partial-gravity (Moon/Mars) extrapolation."
)

_FIELDS_BY_INVESTIGATION: dict[str, frozenset[str]] = {
    inv_id: frozenset(get_allowed_fields(inv_id)) for inv_id in VALID_INVESTIGATION_IDS
}

_TR_FOLD_TABLE = str.maketrans(
    {
        "ç": "c",
        "Ç": "c",
        "ğ": "g",
        "Ğ": "g",
        "ı": "i",
        "I": "i",
        "İ": "i",
        "ö": "o",
        "Ö": "o",
        "ş": "s",
        "Ş": "s",
        "ü": "u",
        "Ü": "u",
        "₂": "2",
        "²": "2",
    }
)

# V12 out-of-scope studies/acronyms (v1 contract covers only PSI-25 and PSI-69)
_OUT_OF_SCOPE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("SAFFIRE (PSI-98/99/100)", re.compile(r"\bsaffire(?:[-\s]*(?:i{1,3}|iv|v|vi|[1-6]))?\b")),
    ("SAME / SAME-R (PSI-101/102)", re.compile(r"\bsame(?:[-\s]*(?:r|2))?\b")),
    ("BASS-1 (PSI-26)", re.compile(r"\bbass[-\s]*1\b")),
    ("ACME (PSI-10/20/21/22/23/159)", re.compile(r"\bacme\b")),
    ("SPICE (PSI-60/107)", re.compile(r"\bspice\b")),
    ("CFI / FLEX-2 / SoFIE / F-REX", re.compile(r"\b(?:cfi|sofie|flex[-\s]*2j?|f[-\s]*rex|feps)\b")),
    (
        "SLICE / DAFT",
        re.compile(r"\b(?:slice|daft)\s+(?:experiment\w*|stud(?:y|ies)|tests?|data|droplet\w*|flame\w*|investigation\w*|deney\w*|verisi)\b"),
    ),
    ("Out-of-scope PSI study", re.compile(r"\bpsi[-\s]*(?!(?:25|69)\b)\d+\b")),
)
_OUT_OF_SCOPE_EXACT_CASE_RE = re.compile(r"\b(?:SLICE|DAFT)\b")
_OUT_OF_SCOPE_PSI_PK_PREFIX_RE = re.compile(r"^PSI-\d+$")
_PSI_STUDY_ID_RE = re.compile(r"^PSI-[1-9]\d*$")

# V10: Inferring/classifying cool flames from extinction diameter (d_ext) or automated labeling
_COOL_FLAME_RE = re.compile(r"\b(?:cool\s+flames?|soguk\s+alev\w*)\b")
_EXTINCTION_DIAMETER_RE = re.compile(
    r"\b(?:d_ext|extinction\s+diameter|visible\s+flame\s+extinction|sonme\s+capi\w*)\b"
    r"|(?:<\s*\d+(?:[.,]\d+)?\s*mm)"
)
_COOL_FLAME_DIRECT_CLASSIFY_RE = re.compile(
    r"\b(?:classify|label|tag|infer|predict|sinifla\w*|etiket\w*|tahmin\w*)\b"
    r".{0,48}\b(?:cool\s+flames?|soguk\s+alev\w*)\b"
    r"|\b(?:cool\s+flames?|soguk\s+alev\w*)\b.{0,32}\b(?:classification|classifier|siniflandir\w*|etiketle\w*|tahmin\w*|sayilir\w*)\b"
)

# V11: Deriving crew toxicity / poisoning / health-risk scores from CO readings
_CO_TOKEN_RE = re.compile(r"\b(?:co|karbonmonoksit|carbon\s+monoxide|ppm|csa[-\s]*cp)\b")
_TOXICITY_RE = re.compile(
    r"\b(?:toksik\w*|toksisite\w*|zehirlen\w*|zehirli\w*|toxicity|toxic\w*"
    r"|crew\s+(?:toxicity|health|hazard)|health\s+risk\w*|hazard\s+score\w*"
    r"|saglik\s+risk\w*|maruziyet\s+skor\w*)\b"
)

# Unsupported fire-risk scores, safety rankings, or partial-gravity extrapolations
_RISK_SCORE_RE = re.compile(
    r"\b(?:yangin\s+risk\s+(?:skoru|puani)|guvenlik\s+(?:skoru|puani|siralamasi)"
    r"|fire\s+(?:risk|hazard)\s+score|flammability\s+score|safety\s+(?:score|ranking|rating)"
    r"|safest\s+(?:material|fuel|cabin\w*)|predict\s+(?:fire\s+|cabin\s+)?safety)\b"
)



class EvidenceServiceError(ValueError):
    """Raised on invalid evidence request arguments or corrupt/missing local sources."""


def _validate_investigation_id_format(investigation_id: str | None) -> None:
    """Validate optional investigation_id against canonical PSI-<positive_integer> syntax."""
    if investigation_id is None:
        return
    if not isinstance(investigation_id, str) or not _PSI_STUDY_ID_RE.match(investigation_id):
        raise EvidenceServiceError(
            f"Invalid investigation_id: {investigation_id!r}. "
            "Expected canonical 'PSI-<positive_integer>' format "
            f"(supported v1 values: {sorted(VALID_INVESTIGATION_IDS)})."
        )


def _fold_text(text: str) -> str:
    """Fold Turkish characters and subscript/superscript digits into ASCII lowercase."""
    return " ".join(text.translate(_TR_FOLD_TABLE).lower().split())


@dataclass(frozen=True)
class AbstentionDecision:
    """Deterministic safety-gate decision for out-of-scope or unsupported queries."""

    abstained: bool
    reason_code: str | None = None
    explanation: str | None = None
    triggered_rule: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "abstained": self.abstained,
            "reason_code": self.reason_code,
            "explanation": self.explanation,
            "triggered_rule": self.triggered_rule,
        }


@dataclass(frozen=True)
class CitationItem:
    """Deduplicated, traceable provenance entry for a table row or document chunk."""

    citation_id: str
    source_type: str  # "table_row" | "document_chunk"
    investigation_id: str
    locator_label: str
    source_relpath: str
    source_sha256: str
    record_pk: str | None = None
    chunk_id: str | None = None
    document_id: str | None = None
    section_title: str | None = None
    printed_page_start: str | None = None
    printed_page_end: str | None = None
    pdf_page_start: int | None = None
    pdf_page_end: int | None = None
    csv_record_index: int | None = None
    physical_line_start: int | None = None
    physical_line_end: int | None = None
    source_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {
            "citation_id": self.citation_id,
            "source_type": self.source_type,
            "investigation_id": self.investigation_id,
            "locator_label": self.locator_label,
            "source_relpath": self.source_relpath,
            "source_sha256": self.source_sha256,
            "record_pk": self.record_pk,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "section_title": self.section_title,
            "printed_page_start": self.printed_page_start,
            "printed_page_end": self.printed_page_end,
            "pdf_page_start": self.pdf_page_start,
            "pdf_page_end": self.pdf_page_end,
            "csv_record_index": self.csv_record_index,
            "physical_line_start": self.physical_line_start,
            "physical_line_end": self.physical_line_end,
        }
        if self.source_url is not None:
            out["source_url"] = self.source_url
        return out


@dataclass(frozen=True)
class EvidenceRequest:
    """Unified request executing typed table operations and BM25 passage retrieval."""

    query: str | None = None
    investigation_id: str | None = None
    fuel: str | None = None
    test_end: str | None = None
    numeric_filters: tuple[NumericRangeFilter, ...] = ()
    include_approximate: bool = False
    summarize_field_name: str | None = None
    summarize_unit: str | None = None
    compare_record_pks: tuple[str, ...] = ()
    compare_field_names: tuple[str, ...] | None = None
    top_k: int = 5
    use_bilingual_aliases: bool = False
    run_table_query: bool = True
    max_table_citations: int = 25
    scope: str = "core"

    def to_dict(self) -> dict[str, Any]:
        out = {
            "query": self.query,
            "investigation_id": self.investigation_id,
            "fuel": self.fuel,
            "test_end": self.test_end,
            "numeric_filters": [
                {
                    "field_name": f.field_name,
                    "unit": f.unit,
                    "min_value": f.min_value,
                    "max_value": f.max_value,
                    "min_inclusive": f.min_inclusive,
                    "max_inclusive": f.max_inclusive,
                }
                for f in self.numeric_filters
            ],
            "include_approximate": self.include_approximate,
            "summarize_field_name": self.summarize_field_name,
            "summarize_unit": self.summarize_unit,
            "compare_record_pks": list(self.compare_record_pks),
            "compare_field_names": list(self.compare_field_names) if self.compare_field_names is not None else None,
            "top_k": self.top_k,
            "use_bilingual_aliases": self.use_bilingual_aliases,
            "run_table_query": self.run_table_query,
            "max_table_citations": self.max_table_citations,
        }
        if self.scope != "core":
            out["scope"] = self.scope
        return out


@dataclass(frozen=True)
class EvidenceBundle:
    """Combined table, summary, comparison, BM25 document hits, and citations bundle."""

    request: EvidenceRequest
    mode: str
    abstention: AbstentionDecision
    resolved_investigation_id: str | None
    table_result: QueryResult | None
    field_summary: FieldSummary | None
    comparison_result: ComparisonResult | None
    document_result: SearchResult | None
    citations: tuple[CitationItem, ...]
    warnings: tuple[str, ...]
    disclaimers: tuple[str, ...]
    case_payload: dict[str, Any] | None = None
    flex_model_payload: dict[str, Any] | None = None
    coverage: Any = None

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-safe dictionary without NaN values."""
        cov_dict = self.coverage.to_dict() if hasattr(self.coverage, "to_dict") else (dict(self.coverage) if isinstance(self.coverage, dict) else None)
        return {
            "mode": self.mode,
            "resolved_investigation_id": self.resolved_investigation_id,
            "abstention": self.abstention.to_dict(),
            "request": self.request.to_dict(),
            "table_result": self.table_result.to_dict() if self.table_result is not None else None,
            "field_summary": self.field_summary.to_dict() if self.field_summary is not None else None,
            "comparison_result": self.comparison_result.to_dict() if self.comparison_result is not None else None,
            "document_result": self.document_result.to_dict() if self.document_result is not None else None,
            "citations": [c.to_dict() for c in self.citations],
            "warnings": list(self.warnings),
            "disclaimers": list(self.disclaimers),
            **({"case_payload": dict(self.case_payload)} if self.case_payload is not None else {}),
            **({"flex_model_payload": dict(self.flex_model_payload)} if self.flex_model_payload is not None else {}),
            **({"coverage": cov_dict} if cov_dict is not None else {}),
        }

    def to_llm_payload(self) -> dict[str, Any]:
        """Return a compact, grounded payload for downstream explanation (no invented numbers)."""
        table_summary_payload: dict[str, Any] | None = None
        if self.table_result is not None:
            limited = self.table_result.records[: self.request.max_table_citations]
            table_summary_payload = {
                "total_runs": self.table_result.total_runs,
                "unique_sample_count": self.table_result.unique_sample_count,
                "unique_flex_identifier_count": self.table_result.unique_flex_identifier_count,
                "counts_by_investigation": dict(self.table_result.counts_by_investigation),
                "matched_record_pks": [r.record_pk for r in limited],
                "matched_rows": [
                    {
                        **_serialize_record_summary(r),
                        "measurements": {
                            fname: _serialize_measurement(m) for fname, m in r.measurements.items()
                        },
                    }
                    for r in limited
                ],
            }
        return {
            "mode": self.mode,
            "abstained": self.abstention.abstained,
            "abstention": self.abstention.to_dict(),
            "resolved_investigation_id": self.resolved_investigation_id,
            "query": self.request.query,
            "table_summary": table_summary_payload,
            "field_summary": self.field_summary.to_dict() if self.field_summary is not None else None,
            "comparison": self.comparison_result.to_dict() if self.comparison_result is not None else None,
            "document_passages": [
                {
                    "chunk_id": hit.chunk_id,
                    "document_id": hit.document_id,
                    "investigation_id": hit.investigation_id,
                    "section_title": hit.section_title,
                    "printed_page_start": hit.printed_page_start,
                    "pdf_page_start": hit.pdf_page_start,
                    "source_text": hit.source_text,
                }
                for hit in (self.document_result.hits if self.document_result is not None else ())
            ],
            "citations": [c.to_dict() for c in self.citations],
            "warnings": list(self.warnings),
            "disclaimers": list(self.disclaimers),
            **({"case_payload": dict(self.case_payload)} if self.case_payload is not None else {}),
            **({"flex_model_payload": dict(self.flex_model_payload)} if self.flex_model_payload is not None else {}),
        }


def evaluate_abstention_gate(
    query: str | None,
    *,
    investigation_id: str | None = None,
    compare_record_pks: Sequence[str] = (),
) -> AbstentionDecision:
    """Enforce deterministic V10, V11, V12, and boundary abstention rules."""
    _validate_investigation_id_format(investigation_id)
    if investigation_id is not None and investigation_id not in VALID_INVESTIGATION_IDS:
        return AbstentionDecision(
            abstained=True,
            reason_code="V12_OUT_OF_SCOPE_STUDY",
            explanation=(
                f"Requested investigation ({investigation_id!r}) matches canonical PSI-<positive_integer> "
                "syntax but is outside the v1 data contract (syntax check does not verify catalog existence). "
                "Only verified PSI-25 (BASS-II) and PSI-69 (FLEX) records are supported."
            ),
            triggered_rule="V12",
        )

    for pk in compare_record_pks:
        if isinstance(pk, str) and ":" in pk:
            prefix = pk.split(":", 1)[0].strip().upper()
            if _OUT_OF_SCOPE_PSI_PK_PREFIX_RE.match(prefix) and prefix not in VALID_INVESTIGATION_IDS:
                return AbstentionDecision(
                    abstained=True,
                    reason_code="V12_OUT_OF_SCOPE_STUDY",
                    explanation=(
                        f"Requested record key ({pk!r}) belongs to an out-of-scope study ({prefix}). "
                        "Only verified PSI-25 (BASS-II) and PSI-69 (FLEX) records are supported."
                    ),
                    triggered_rule="V12",
                )

    if not query or not query.strip():
        return AbstentionDecision(abstained=False)

    folded = _fold_text(query)

    # 1. V12: Out-of-scope PSI studies and NASA programs
    for label, pattern in _OUT_OF_SCOPE_PATTERNS:
        if pattern.search(folded):
            return AbstentionDecision(
                abstained=True,
                reason_code="V12_OUT_OF_SCOPE_STUDY",
                explanation=(
                    f"Out-of-scope investigation/program referenced ({label}). "
                    "The v1 data contract (VERI_SOZLESMESI.md §1) covers only PSI-25 (BASS-II) "
                    "and PSI-69 (FLEX)."
                ),
                triggered_rule="V12",
            )
    if _OUT_OF_SCOPE_EXACT_CASE_RE.search(query):
        return AbstentionDecision(
            abstained=True,
            reason_code="V12_OUT_OF_SCOPE_STUDY",
            explanation=(
                "Out-of-scope investigation/program referenced (SLICE / DAFT). "
                "The v1 data contract (VERI_SOZLESMESI.md §1) covers only PSI-25 (BASS-II) "
                "and PSI-69 (FLEX)."
            ),
            triggered_rule="V12",
        )

    # 2. V10: Inferring/classifying cool flames from extinction diameter (d_ext) or automated labeling
    if _COOL_FLAME_RE.search(folded) and (
        _EXTINCTION_DIAMETER_RE.search(folded) or _COOL_FLAME_DIRECT_CLASSIFY_RE.search(folded)
    ):
        return AbstentionDecision(
            abstained=True,
            reason_code="V10_COOL_FLAME_INFERENCE",
            explanation=(
                "Per NASA/TP-2015-216046 Appendix A.1 (printed p. 19 / PDF p. 25) and PSI-69 CSV data, "
                "visible flame extinction diameter (d_ext) alone is not sufficient evidence of a cool flame "
                "(also populated for Completion/Disruption and hot radiative extinction). Automated cool-flame "
                "classification is withheld."
            ),
            triggered_rule="V10",
        )

    # 3. V11: Deriving crew toxicity or health-risk scores from CO readings
    if _CO_TOKEN_RE.search(folded) and _TOXICITY_RE.search(folded):
        return AbstentionDecision(
            abstained=True,
            reason_code="V11_CO_TOXICITY_SCORE",
            explanation=(
                "Per BASS-II_ReadMe.docx and NASA/TM-20210011385, single-test CSA-CP CO (ppm) end readings "
                "cannot be converted into crew toxicity or exposure risk scores without MSG compartment volume, "
                "scrubbing/ventilation rate, and exposure duration."
            ),
            triggered_rule="V11",
        )

    # 4. Unsupported composite fire-risk scores or Moon/Mars/partial-gravity transfer (claim_boundary)
    if _RISK_SCORE_RE.search(folded) or asks_gravity_transfer(folded):
        return AbstentionDecision(
            abstained=True,
            reason_code="UNSUPPORTED_RISK_OR_GRAVITY_EXTRAPOLATION",
            explanation=(
                "Experiments across distinct physical regimes (solid surface vs droplet combustion) cannot be "
                "collapsed into a unified fire-risk score, and ISS microgravity measurements cannot be "
                "extrapolated to Lunar (1/6g) or Martian (3/8g) gravity without physical validation. "
                + SOURCE_SCOPE_NOTE
            ),
            triggered_rule="CONTRACT_BOUNDARY",
        )

    # 5. Safety verdicts / rule compliance / harm to people are not measured quantities (claim_boundary)
    if asks_safety_judgment(folded) or asks_crew_harm(folded):
        return AbstentionDecision(
            abstained=True,
            reason_code="UNSUPPORTED_SAFETY_JUDGMENT",
            explanation=(
                "The indexed NASA tables and reports record measured combustion results; they do not rate, rank or "
                "certify safety, compare spacecraft safety rules, or establish harm to a crew. " + SOURCE_SCOPE_NOTE
            ),
            triggered_rule="CONTRACT_BOUNDARY",
        )

    return AbstentionDecision(abstained=False)


def _infer_investigation_from_query_text(query: str | None) -> str | None:
    """Return a single core investigation ID if the query text unambiguously names one."""
    if not query or not query.strip():
        return None
    folded = _fold_text(query)
    mentions_psi25 = bool(re.search(r"\b(?:psi[-\s]*25|bass[-\s]*ii|bass\s*2)\b", folded))
    mentions_psi69 = bool(re.search(r"\b(?:psi[-\s]*69|flex)\b", folded))
    if mentions_psi25 and not mentions_psi69:
        return "PSI-25"
    if mentions_psi69 and not mentions_psi25:
        return "PSI-69"
    return None


def _resolve_filter_investigation(request: EvidenceRequest) -> str | None:
    """Resolve explicit filter/summary target study without blocking cross-study compare_record_pks."""
    owners: set[str] = set()

    if request.investigation_id is not None:
        if request.investigation_id not in VALID_INVESTIGATION_IDS:
            raise EvidenceServiceError(
                f"Invalid investigation_id: {request.investigation_id!r}. "
                f"Allowed values: {sorted(VALID_INVESTIGATION_IDS)}"
            )
        owners.add(request.investigation_id)

    if request.test_end is not None:
        owners.add("PSI-69")

    for rng in request.numeric_filters:
        matched_invs = [
            inv_id for inv_id, fields in _FIELDS_BY_INVESTIGATION.items() if rng.field_name in fields
        ]
        if not matched_invs:
            raise EvidenceServiceError(f"Unknown numeric filter field: {rng.field_name!r}")
        if len(matched_invs) == 1:
            owners.add(matched_invs[0])

    if request.summarize_field_name is not None:
        matched_invs = [
            inv_id
            for inv_id, fields in _FIELDS_BY_INVESTIGATION.items()
            if request.summarize_field_name in fields
        ]
        if not matched_invs:
            raise EvidenceServiceError(f"Unknown summary field: {request.summarize_field_name!r}")
        if len(matched_invs) == 1:
            owners.add(matched_invs[0])

    if len(owners) > 1:
        raise EvidenceServiceError(
            "Cannot combine investigation-specific filters across PSI-25 and PSI-69 in one query: "
            + ", ".join(sorted(owners))
        )

    return next(iter(owners)) if owners else None


def _build_table_citation(rec: ExperimentRecord) -> CitationItem:
    """Create a verifiable CitationItem from an ExperimentRecord."""
    loc = (
        f"{rec.investigation_id} Test #{rec.test_id} "
        f"(csv_record_index={rec.source.csv_record_index}, "
        f"lines={rec.source.physical_line_start}-{rec.source.physical_line_end})"
    )
    return CitationItem(
        citation_id=f"TBL:{rec.record_pk}",
        source_type="table_row",
        investigation_id=rec.investigation_id,
        locator_label=loc,
        source_relpath=rec.source.source_relpath,
        source_sha256=rec.source.source_sha256,
        record_pk=rec.record_pk,
        csv_record_index=rec.source.csv_record_index,
        physical_line_start=rec.source.physical_line_start,
        physical_line_end=rec.source.physical_line_end,
    )


def _build_document_citation(hit: RetrievalHit) -> CitationItem:
    """Create a verifiable CitationItem from a BM25 RetrievalHit."""
    page_parts: list[str] = []
    if hit.printed_page_start is not None:
        if hit.printed_page_end and hit.printed_page_end != hit.printed_page_start:
            page_parts.append(f"printed p.{hit.printed_page_start}-{hit.printed_page_end}")
        else:
            page_parts.append(f"printed p.{hit.printed_page_start}")
    if hit.pdf_page_start is not None:
        if hit.pdf_page_end and hit.pdf_page_end != hit.pdf_page_start:
            page_parts.append(f"PDF p.{hit.pdf_page_start}-{hit.pdf_page_end}")
        else:
            page_parts.append(f"PDF p.{hit.pdf_page_start}")
    if hit.paragraph_index_start is not None:
        page_parts.append(f"P{hit.paragraph_index_start}-P{hit.paragraph_index_end}")

    page_str = ", ".join(page_parts) if page_parts else "location recorded"
    loc = f"{hit.document_id} § {hit.section_title} ({page_str})"

    return CitationItem(
        citation_id=f"DOC:{hit.chunk_id}",
        source_type="document_chunk",
        investigation_id=hit.investigation_id,
        locator_label=loc,
        source_relpath=hit.source_relpath,
        source_sha256=hit.source_sha256,
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        section_title=hit.section_title,
        printed_page_start=hit.printed_page_start,
        printed_page_end=hit.printed_page_end,
        pdf_page_start=hit.pdf_page_start,
        pdf_page_end=hit.pdf_page_end,
    )


def _verify_chunks_against_manifest(
    chunks: Sequence[DocumentChunk],
    manifest_path: Path,
) -> None:
    """Verify chunk count and document SHA-256 hashes against psi_document_manifest.json."""
    try:
        manifest_raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceServiceError(f"Failed to read document manifest {manifest_path}: {exc}") from exc

    expected_total = manifest_raw.get("summary", {}).get("total_chunks")
    if isinstance(expected_total, int) and expected_total != len(chunks):
        raise EvidenceServiceError(
            f"Document chunk count mismatch: manifest={expected_total}, chunks={len(chunks)}"
        )

    expected_sha_by_doc = {
        str(doc["document_id"]): str(doc["sha256"])
        for doc in manifest_raw.get("documents", ())
        if isinstance(doc, dict) and doc.get("document_id") and doc.get("sha256")
    }
    for chunk in chunks:
        expected_sha = expected_sha_by_doc.get(chunk.document_id)
        if expected_sha is not None and chunk.source_sha256 != expected_sha:
            raise EvidenceServiceError(
                f"SHA-256 mismatch for chunk {chunk.chunk_id} ({chunk.document_id})."
            )


def load_processed_chunks(
    repo_root: str | Path = ".",
    *,
    verify_manifest: bool = True,
) -> tuple[DocumentChunk, ...]:
    """Load pre-extracted chunks from `data/processed/psi_document_chunks.json`.

    Verifies counts and source hashes against `psi_document_manifest.json` when
    `verify_manifest=True` and the manifest exists.
    """
    root = Path(repo_root)
    chunks_path = root / "data" / "processed" / "psi_document_chunks.json"
    if not chunks_path.is_file():
        raise EvidenceServiceError(f"Processed document chunks file not found: {chunks_path}")

    try:
        raw_data = json.loads(chunks_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceServiceError(f"Failed to parse {chunks_path}: {exc}") from exc

    raw_chunks = raw_data.get("chunks") if isinstance(raw_data, dict) else None
    if not isinstance(raw_chunks, list) or not raw_chunks:
        raise EvidenceServiceError(f"Invalid or empty psi_document_chunks.json content: {chunks_path}")

    try:
        chunks = tuple(
            DocumentChunk(
                chunk_id=str(item["chunk_id"]),
                chunk_ordinal=int(item["chunk_ordinal"]),
                document_id=str(item["document_id"]),
                investigation_id=str(item["investigation_id"]),
                section_number=item.get("section_number"),
                section_title=str(item["section_title"]),
                section_path=tuple(str(x) for x in item.get("section_path", ())),
                source_text=str(item["source_text"]),
                pdf_page_start=item.get("pdf_page_start"),
                pdf_page_end=item.get("pdf_page_end"),
                printed_page_start=item.get("printed_page_start"),
                printed_page_end=item.get("printed_page_end"),
                printed_pages=tuple(str(x) for x in item.get("printed_pages", ())),
                paragraph_index_start=item.get("paragraph_index_start"),
                paragraph_index_end=item.get("paragraph_index_end"),
                source_url=str(item["source_url"]),
                source_relpath=str(item["source_relpath"]),
                source_sha256=str(item["source_sha256"]),
                extraction_warnings=tuple(str(x) for x in item.get("extraction_warnings", ())),
            )
            for item in raw_chunks
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EvidenceServiceError(f"Malformed chunk record in {chunks_path}: {exc}") from exc

    manifest_path = root / "data" / "processed" / "psi_document_manifest.json"
    if verify_manifest and manifest_path.is_file():
        _verify_chunks_against_manifest(chunks, manifest_path)

    return chunks


def _validate_request(request: EvidenceRequest) -> None:
    if not isinstance(request, EvidenceRequest):
        raise EvidenceServiceError(f"request must be an EvidenceRequest; got {type(request).__name__}")
    if request.scope not in {"core", "saffire_case"}:
        raise EvidenceServiceError(f"Unsupported evidence scope: {request.scope!r}. Allowed: 'core', 'saffire_case'.")
    _validate_investigation_id_format(request.investigation_id)
    if isinstance(request.top_k, bool) or not isinstance(request.top_k, int) or not 1 <= request.top_k <= 100:
        raise EvidenceServiceError("top_k must be an integer between 1 and 100.")
    if (
        isinstance(request.max_table_citations, bool)
        or not isinstance(request.max_table_citations, int)
        or not 0 <= request.max_table_citations <= 100
    ):
        raise EvidenceServiceError("max_table_citations must be an integer between 0 and 100.")


def _infer_comparison_fields(
    record_pks: Sequence[str],
    resolved_inv_id: str | None,
) -> tuple[str, ...]:
    pk_invs = [
        pk.split(":", 1)[0].strip()
        for pk in record_pks
        if isinstance(pk, str) and ":" in pk and pk.split(":", 1)[0].strip() in VALID_INVESTIGATION_IDS
    ]
    target_invs = list(dict.fromkeys(pk_invs)) or (
        [resolved_inv_id] if resolved_inv_id is not None else sorted(VALID_INVESTIGATION_IDS)
    )
    inferred: list[str] = []
    for inv in target_invs:
        for fname in get_allowed_fields(inv):
            if fname not in inferred:
                inferred.append(fname)
    return tuple(inferred)


def _collect_citations(
    records: Sequence[ExperimentRecord],
    *,
    table_result: QueryResult | None,
    comparison_result: ComparisonResult | None,
    document_result: SearchResult | None,
    max_table_citations: int,
) -> tuple[CitationItem, ...]:
    citations: list[CitationItem] = []
    seen_ids: set[str] = set()

    def _add(cit: CitationItem) -> None:
        if cit.citation_id not in seen_ids:
            seen_ids.add(cit.citation_id)
            citations.append(cit)

    if comparison_result is not None:
        pk_map = {r.record_pk: r for r in records}
        for pk in comparison_result.requested_record_pks:
            rec = pk_map.get(pk)
            if rec is not None:
                _add(_build_table_citation(rec))

    if table_result is not None and max_table_citations > 0:
        for rec in table_result.records[:max_table_citations]:
            _add(_build_table_citation(rec))

    if document_result is not None:
        for hit in document_result.hits:
            _add(_build_document_citation(hit))

    return tuple(citations)


def _collect_warnings(
    *,
    table_result: QueryResult | None,
    field_summary: FieldSummary | None,
    comparison_result: ComparisonResult | None,
    document_result: SearchResult | None,
    corpus_unavailable: bool,
) -> tuple[str, ...]:
    warnings: list[str] = []

    def _push(msg: str) -> None:
        if msg not in warnings:
            warnings.append(msg)

    if corpus_unavailable:
        _push("corpus_unavailable: Document retrieval index is unavailable; table search remains active.")
    for src in (table_result, field_summary, comparison_result):
        if src is not None:
            for w in src.warnings:
                _push(w)
    if document_result is not None:
        for hit in document_result.hits:
            for w in hit.extraction_warnings:
                _push(f"{hit.chunk_id}: {w}")
    return tuple(warnings)


def build_evidence_bundle(
    request: EvidenceRequest,
    *,
    records: Sequence[ExperimentRecord],
    bm25_index: BM25Index | None,
) -> EvidenceBundle:
    """Execute table filtering, field summary, record comparison, and BM25 retrieval as one bundle."""
    _validate_request(request)

    gate_decision = evaluate_abstention_gate(
        request.query,
        investigation_id=request.investigation_id,
        compare_record_pks=request.compare_record_pks,
    )
    if gate_decision.abstained:
        from .coverage import assess_core_coverage

        cov = assess_core_coverage(
            request=request,
            abstention=gate_decision,
            table_result=None,
            field_summary=None,
            comparison_result=None,
            document_result=None,
            total_corpus_count=len(records),
        )
        return EvidenceBundle(
            request=request,
            mode=SERVICE_MODE_DETERMINISTIC,
            abstention=gate_decision,
            resolved_investigation_id=(
                request.investigation_id if request.investigation_id in VALID_INVESTIGATION_IDS else None
            ),
            table_result=None,
            field_summary=None,
            comparison_result=None,
            document_result=None,
            citations=(),
            warnings=(gate_decision.explanation,) if gate_decision.explanation else (),
            disclaimers=(SERVICE_BOUNDARY_DISCLAIMER, COMPARISON_BOUNDARY_NOTE, BM25_SCORE_DISCLAIMER),
            coverage=cov,
        )

    try:
        filter_inv_id = _resolve_filter_investigation(request)
    except (QueryValidationError, RetrievalValidationError) as exc:
        raise EvidenceServiceError(str(exc)) from exc

    query_inv_id = _infer_investigation_from_query_text(request.query)
    if filter_inv_id is not None and query_inv_id is not None and filter_inv_id != query_inv_id:
        # Respect explicit structured filters for table operations; avoid cross-contaminating doc scope.
        doc_scope_inv_id = filter_inv_id
    else:
        doc_scope_inv_id = filter_inv_id or query_inv_id

    has_table_value_filters = any(
        (
            request.fuel is not None,
            request.test_end is not None,
            bool(request.numeric_filters),
        )
    )
    has_query_text = bool(request.query and request.query.strip())
    should_run_table = request.run_table_query and (
        has_table_value_filters
        or (not has_query_text and not request.compare_record_pks and request.summarize_field_name is None)
    )

    table_result: QueryResult | None = None
    field_summary: FieldSummary | None = None
    comparison_result: ComparisonResult | None = None
    document_result: SearchResult | None = None
    resolved_inv_id = doc_scope_inv_id

    try:
        if should_run_table:
            table_result = filter_records(
                records,
                investigation_id=filter_inv_id,
                fuel=request.fuel,
                test_end=request.test_end,
                numeric_filters=request.numeric_filters,
                include_approximate=request.include_approximate,
            )
            if filter_inv_id is None and len(table_result.counts_by_investigation) == 1:
                resolved_inv_id = next(iter(table_result.counts_by_investigation.keys()))

        if request.summarize_field_name is not None:
            if not request.summarize_unit:
                raise EvidenceServiceError(
                    "summarize_unit must be explicitly specified when summarize_field_name is provided."
                )
            summary_inv_id = resolved_inv_id
            if summary_inv_id is None:
                raise EvidenceServiceError(
                    "summarize_field_name requires investigation_id or an investigation-specific field."
                )
            source_records = table_result.records if table_result is not None else records
            field_summary = summarize_field(
                source_records,
                investigation_id=summary_inv_id,
                field_name=request.summarize_field_name,
                unit=request.summarize_unit,
                include_approximate=request.include_approximate,
            )

        if request.compare_record_pks:
            comp_fields = request.compare_field_names or _infer_comparison_fields(
                request.compare_record_pks, resolved_inv_id
            )
            comparison_result = compare_records(
                records,
                record_pks=request.compare_record_pks,
                field_names=comp_fields,
            )

        if has_query_text and bm25_index is not None:
            document_result = bm25_index.search(
                request.query or "",
                top_k=request.top_k,
                investigation_id=resolved_inv_id,
                use_bilingual_aliases=request.use_bilingual_aliases,
            )
            if resolved_inv_id is None and document_result.hits:
                hit_invs = {h.investigation_id for h in document_result.hits}
                if len(hit_invs) == 1:
                    resolved_inv_id = next(iter(hit_invs))
    except (QueryValidationError, RetrievalValidationError) as exc:
        raise EvidenceServiceError(str(exc)) from exc

    corpus_unavailable = has_query_text and bm25_index is None
    citations = _collect_citations(
        records,
        table_result=table_result,
        comparison_result=comparison_result,
        document_result=document_result,
        max_table_citations=request.max_table_citations,
    )
    warnings = _collect_warnings(
        table_result=table_result,
        field_summary=field_summary,
        comparison_result=comparison_result,
        document_result=document_result,
        corpus_unavailable=corpus_unavailable,
    )

    has_table_matches = (
        (table_result is not None and table_result.total_runs > 0)
        or (field_summary is not None and field_summary.used_total_count > 0)
        or (comparison_result is not None and len(comparison_result.rows) > 0)
    )
    has_doc_matches = document_result is not None and document_result.total_hits_returned > 0

    if not has_table_matches and not has_doc_matches:
        final_abstention = AbstentionDecision(
            abstained=True,
            reason_code="NO_MATCHING_EVIDENCE",
            explanation=(
                "No supporting evidence was found in the verified PSI-25 / PSI-69 tables "
                "or primary NASA report passages for this request."
            ),
            triggered_rule="EMPTY_RESULT",
        )
    else:
        final_abstention = AbstentionDecision(abstained=False)

    disclaimers: list[str] = [SERVICE_BOUNDARY_DISCLAIMER, COMPARISON_BOUNDARY_NOTE, BM25_SCORE_DISCLAIMER]
    if document_result is not None and document_result.applied_query_expansions:
        disclaimers.append(BILINGUAL_SCOPE_NOTE)

    from .coverage import assess_core_coverage, assess_unavailable_coverage

    if corpus_unavailable and table_result is None and field_summary is None and comparison_result is None:
        cov = assess_unavailable_coverage(
            scope=request.scope,
            corpus_id="PSI-25 + PSI-69 BM25 Document Corpus",
            error_detail="Primary NASA document BM25 index is unavailable in this environment.",
            requested_conditions={
                **({"query_provided": True} if str(request.query or "").strip() else {}),
                **({"investigation_id": request.investigation_id} if request.investigation_id else {}),
            },
        )
    else:
        cov = assess_core_coverage(
            request=request,
            abstention=final_abstention,
            table_result=table_result,
            field_summary=field_summary,
            comparison_result=comparison_result,
            document_result=document_result,
            total_corpus_count=len(records),
        )

    return EvidenceBundle(
        request=request,
        mode=SERVICE_MODE_DETERMINISTIC,
        abstention=final_abstention,
        resolved_investigation_id=resolved_inv_id,
        table_result=table_result,
        field_summary=field_summary,
        comparison_result=comparison_result,
        document_result=document_result,
        citations=citations,
        warnings=warnings,
        disclaimers=tuple(disclaimers),
        coverage=cov,
    )


class EvidenceService:
    """High-level evidence bundling service backed by typed CSV records and BM25 index."""

    def __init__(
        self,
        *,
        records: Sequence[ExperimentRecord],
        bm25_index: BM25Index | None,
        dataset_metas: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._records: tuple[ExperimentRecord, ...] = tuple(records)
        self._bm25_index = bm25_index
        self._dataset_metas = dict(dataset_metas) if dataset_metas is not None else {}

    @classmethod
    def from_repo(
        cls,
        repo_root: str | Path = ".",
        *,
        prefer_processed_chunks: bool = True,
        strict_corpus: bool = True,
    ) -> EvidenceService:
        """Load core datasets and BM25 corpus from `repo_root`."""
        root = Path(repo_root)
        records, metas = load_core_datasets(root)
        chunks: Sequence[DocumentChunk] = ()
        if prefer_processed_chunks:
            try:
                chunks = load_processed_chunks(root)
            except EvidenceServiceError:
                try:
                    chunks, _ = load_retrieval_corpus(root, strict=strict_corpus)
                except RetrievalDocumentError as exc:
                    raise EvidenceServiceError(str(exc)) from exc
        else:
            try:
                chunks, _ = load_retrieval_corpus(root, strict=strict_corpus)
            except RetrievalDocumentError as exc:
                raise EvidenceServiceError(str(exc)) from exc
        index = build_bm25_index(chunks) if chunks else None
        return cls(records=records, bm25_index=index, dataset_metas=metas)

    @property
    def records(self) -> tuple[ExperimentRecord, ...]:
        return self._records

    @property
    def bm25_index(self) -> BM25Index | None:
        return self._bm25_index

    def query(self, request: EvidenceRequest) -> EvidenceBundle:
        """Build a grounded `EvidenceBundle` for `request`."""
        return build_evidence_bundle(
            request,
            records=self._records,
            bm25_index=self._bm25_index,
        )


__all__ = [
    "AbstentionDecision",
    "CitationItem",
    "EvidenceBundle",
    "EvidenceRequest",
    "EvidenceService",
    "EvidenceServiceError",
    "SERVICE_BOUNDARY_DISCLAIMER",
    "SERVICE_MODE_DETERMINISTIC",
    "VALID_INVESTIGATION_IDS",
    "build_evidence_bundle",
    "evaluate_abstention_gate",
    "load_processed_chunks",
]
