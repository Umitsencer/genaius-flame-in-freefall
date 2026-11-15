"""Framework bağımsız, gerçek veri ve belge çekirdeğini birleştiren prototip servisi."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .analytics import (
    build_descriptive_analytics,
    build_export_payload,
    build_flex_analytics,
    build_material_lab_analytics,
)
from .answering import GroundedLLMAdapter, generate_grounded_answer
from .catalog import (
    CatalogError,
    ResearchCatalog,
    load_research_catalog,
    search_catalog,
)
from .cfi import (
    CfiDataset,
    CfiError,
    build_cfi_schema,
    load_cfi_dataset,
    run_cfi_analysis,
)
from .saffire import (
    SaffireDataset,
    SaffireError,
    build_saffire_schema,
    load_saffire_dataset,
    run_saffire_reference,
    validate_sample_id,
)
from .saffire_case import (
    SAFFIRE_CASE_MODE,
    SaffireCaseDataset,
    SaffireCaseError,
    SaffireCaseValidationError,
    build_saffire_case_evidence_bundle,
    build_saffire_case_schema,
    export_saffire_case,
    load_saffire_case_dataset,
    run_saffire_case_reference,
    validate_case_filters,
)
from .flex_predictor import (
    FlexPredictionValidationError,
    FlexPredictorError,
    build_flex_prediction_evidence_bundle,
    build_flex_prediction_schema,
    build_flex_research_summary_export,
    load_flex_predictor_bundle,
    run_flex_condition_map,
    run_flex_prediction,
    validate_prediction_payload,
)
from .flex_reconciliation import (
    FlexReconciliationError,
    load_flex_reconciliation,
)
from .data.contracts import DATASET_SPECS
from .data.loader import load_core_datasets
from .data.query import (NumericRangeFilter, filter_records,
                         compare_records, get_allowed_units, _serialize_measurement)
from .retrieval.bm25 import build_bm25_index
from .retrieval.documents import load_retrieval_corpus
from .coverage import assess_unavailable_coverage
from .scope_router import resolve_scope
from .scenario_check import (ScenarioChecker, answer_payload as scenario_answer_payload, coverage_grid,
                             parse_question as parse_scenario_question, parse_report_question,
                             report_answer_payload)
from .schemas.requests import (
    AnalyticsRequest,
    CatalogSearchRequest,
    CfiAnalysisRequest,
    CompareRequest,
    DetailRequest,
    DocumentsRequest,
    EvidenceRequestIn,
    ExportRequest,
    FlexAnalyticsRequest,
    FlexExportRequest,
    MaterialLabRequest,
    NumericFilterIn,
    SaffireCaseExportRequest,
    SaffireCaseRequest,
    SaffireReferenceRequest,
    SearchRequest,
    parse_request,
)
from .schemas.scenario import ScenarioCheckRequest, ScenarioGridRequest, ScenarioReportRequest
from .service import EvidenceBundle, EvidenceRequest, build_evidence_bundle, evaluate_abstention_gate
from .prevention import build_prevention_summary, is_prevention_question, prevention_answer
from .service import _fold_text
from .table_answers import ANSWER_MODE as TABLE_ANSWER_MODE, try_table_answer

VERSION = "0.1"
BOUNDARY = "Condition comparison only; not a safety ranking or causal conclusion."


def envelope(
    data: Any,
    status: str = "OK",
    message: str = "",
    *,
    mode: str = "evidence_search_only",
    llm_enabled: bool = False,
    coverage: dict[str, Any] | None = None,
) -> dict:
    out = {"schema_version": VERSION, "status": status, "message": message,
           "mode": mode, "llm_enabled": llm_enabled, "data": data}
    if coverage is not None:
        out["coverage"] = coverage
    return out


# (scope, corpus_id, error_detail, status, mode) of optional modules that may be unavailable.
_SAFFIRE_CASE_GAP = ("saffire_case", "SAFFIRE IV-VI Case Study",
                     "Optional SAFFIRE IV-VI case study module is unavailable.", "SAFFIRE_CASE_UNAVAILABLE",
                     SAFFIRE_CASE_MODE)
_FLEX_GAP = ("flex_prediction", "FLEX Condition Predictor",
             "Optional FLEX condition prediction artifact is unavailable.", "FLEX_PREDICTOR_UNAVAILABLE",
             "flex_condition_prediction_only")
_CATALOG_GAP = ("catalog", "PSI Combustion 24-Study Catalog", "Catalog index is temporarily unavailable.",
                "CATALOG_UNAVAILABLE", "catalog_lookup_only")


def _unavailable(gap: tuple[str, str, str, str, str], message: str, *,
                 data_extra: dict[str, Any] | None = None) -> dict:
    """Controlled degraded-module envelope with an explicit coverage gap (never silent fallback)."""
    scope, corpus_id, detail, status, mode = gap
    cov = assess_unavailable_coverage(scope=scope, corpus_id=corpus_id, error_detail=detail).to_dict()
    data = None if data_extra is None else {"coverage": cov, **data_extra}
    return envelope(data, status, message, mode=mode, llm_enabled=False, coverage=cov)


def _to_range_filters(filters: list[NumericFilterIn]) -> tuple[NumericRangeFilter, ...]:
    return tuple(NumericRangeFilter(f.field_name, f.unit, f.min_value, f.max_value) for f in filters)


class AppService:
    """Bir kez yüklenir; sorgular kaynakları değiştirmez ve dış ağa çıkmaz."""

    def __init__(
        self,
        repo_root: str | Path,
        *,
        answer_adapter: GroundedLLMAdapter | None = None,
        catalog_loader: Callable[[Path], ResearchCatalog] | None = None,
        cfi_loader: Callable[[Path], CfiDataset] | None = None,
        saffire_loader: Callable[[Path], SaffireDataset] | None = None,
        saffire_case_loader: Callable[[Path], SaffireCaseDataset] | None = None,
        flex_predictor_loader: Callable[[Path], dict[str, Any]] | None = None,
        flex_reconciliation_loader: Callable[[Path], dict[str, Any]] | None = None,
    ):
        self.root = Path(repo_root).resolve()
        self.answer_adapter = answer_adapter
        self.records, self.metadata = load_core_datasets(self.root)
        self.by_pk = {r.record_pk: r for r in self.records}
        self.index = None
        self.corpus_status = "unavailable"
        # Eksik belge veri tablolarını devre dışı bırakmaz; kısmi corpus açıkça bildirilir.
        chunks, manifest = load_retrieval_corpus(self.root, strict=False)
        if chunks:
            self.index = build_bm25_index(chunks)
            self.corpus_status = ("ready" if all(m.access_status == "verified_readable"
                                               for m in manifest) else "partial")

        self.catalog: ResearchCatalog | None = None
        self.catalog_status = "unavailable"
        loader = catalog_loader or load_research_catalog
        try:
            self.catalog = loader(self.root)
            self.catalog_status = "ready"
        except (CatalogError, OSError, ValueError):
            # Katalog eksik/bozuksa tablo, belge ve cevap servisleri çalışmaya devam eder.
            self.catalog = None
            self.catalog_status = "unavailable"

        self.cfi: CfiDataset | None = None
        self.cfi_status = "unavailable"
        resolved_cfi_loader = cfi_loader or load_cfi_dataset
        try:
            self.cfi = resolved_cfi_loader(self.root)
            self.cfi_status = "ready"
        except (CfiError, OSError, ValueError):
            # Opsiyonel CFI verisi/openpyxl yoksa mevcut PSI-25/PSI-69 çekirdeği çalışmaya devam eder.
            self.cfi = None
            self.cfi_status = "unavailable"

        self.saffire: SaffireDataset | None = None
        self.saffire_status = "unavailable"
        resolved_saffire_loader = saffire_loader or load_saffire_dataset
        try:
            self.saffire = resolved_saffire_loader(self.root)
            self.saffire_status = "ready"
        except (SaffireError, OSError, ValueError):
            # SAFFIRE-II kaynakları eksik/bozuksa çekirdek ve CFI servisleri etkilenmez.
            self.saffire = None
            self.saffire_status = "unavailable"

        self.flex_predictor: dict[str, Any] | None = None
        self.flex_predictor_status = "unavailable"
        resolved_predictor_loader = flex_predictor_loader or load_flex_predictor_bundle
        try:
            self.flex_predictor = resolved_predictor_loader(self.root)
            self.flex_predictor_status = "ready"
        except (FlexPredictorError, OSError, ValueError):
            self.flex_predictor = None
            self.flex_predictor_status = "unavailable"

        self.flex_reconciliation_data: dict[str, Any] | None = None
        self.flex_reconciliation_status = "unavailable"
        resolved_recon_loader = flex_reconciliation_loader or load_flex_reconciliation
        try:
            self.flex_reconciliation_data = resolved_recon_loader(self.root)
            self.flex_reconciliation_status = "ready"
        except (FlexReconciliationError, OSError, ValueError):
            self.flex_reconciliation_data = None
            self.flex_reconciliation_status = "unavailable"

        self.saffire_case: SaffireCaseDataset | None = None
        self.saffire_case_status = "unavailable"
        resolved_case_loader = saffire_case_loader or load_saffire_case_dataset
        try:
            self.saffire_case = resolved_case_loader(self.root)
            self.saffire_case_status = "ready"
        except (SaffireCaseError, OSError, ValueError):
            self.saffire_case = None
            self.saffire_case_status = "unavailable"

        self.scenario_checker = ScenarioChecker(self.records)

    def scenario_check(self, payload: dict) -> dict:
        """Scenario Evidence Check: TESTED / PARTIAL / GAP for one planned condition (deterministic, no LLM)."""
        req = parse_request(ScenarioCheckRequest, payload)
        data = self.scenario_checker.check(
            req.fuel.strip(),
            None if req.o2_percent is None else float(req.o2_percent),
            None if req.pressure_atm is None else float(req.pressure_atm),
            None if req.gravity_g is None else float(req.gravity_g),
            (req.purpose or "").strip(),
            lang=req.lang,
        )
        return envelope(data, "OK", mode="scenario_evidence_check", llm_enabled=False)

    def scenario_grid(self, payload: dict) -> dict:
        """Coverage map: TESTED / PARTIAL / GAP for every oxygen x pressure cell at one gravity."""
        req = parse_request(ScenarioGridRequest, payload)
        return envelope(
            coverage_grid(
                self.scenario_checker,
                req.fuel.strip(),
                None if req.gravity_g is None else float(req.gravity_g),
                lang=req.lang,
            ),
            "OK",
            mode="scenario_coverage_map",
            llm_enabled=False,
        )

    def scenario_report(self, payload: dict) -> dict:
        """Habitat report: several materials checked under one habitat condition, summarised in one table."""
        req = parse_request(ScenarioReportRequest, payload)
        return envelope(self.scenario_checker.habitat_report(req.habitat, req.fuels, lang=req.lang), "OK",
                        mode="scenario_habitat_report", llm_enabled=False)

    def schema(self) -> dict:
        datasets = []
        for inv, spec in DATASET_SPECS.items():
            records = [r for r in self.records if r.investigation_id == inv]
            datasets.append({"id": inv, "name": spec.experiment_name,
                "run_count": len(records), "doi": spec.doi,
                "sha256": self.metadata[inv]["sha256"],
                "fuels": sorted({r.normalized_fields["fuel_norm"] for r in records}),
                "fields": [{"name": f.field_name, "label": f.field_name.replace("_", " "),
                            "units": list(get_allowed_units(f.field_name, inv)),
                            "meaning_unverified": f.uncalibrated}
                           for f in spec.field_contracts if not f.uncalibrated]})
        llm_model = (
            getattr(getattr(self.answer_adapter, "config", None), "model", None)
            if self.answer_adapter is not None
            else None
        )
        return envelope({"datasets": datasets, "corpus_status": self.corpus_status,
                         "chunk_count": len(self.index.chunks) if self.index else 0,
                         "llm_model": llm_model,
                         "boundary": BOUNDARY},
                        llm_enabled=self.answer_adapter is not None)

    def search(self, payload: dict) -> dict:
        req = parse_request(SearchRequest, payload)
        limit, offset = req.limit, req.offset
        result = filter_records(self.records, investigation_id=req.investigation_id,
                                fuel=req.fuel, numeric_filters=_to_range_filters(req.numeric_filters))
        data = result.to_dict()
        data["records"] = data["records"][offset:offset + limit]
        data.update(limit=limit, offset=offset, returned_count=len(data["records"]))
        inv_filter = req.investigation_id
        data["coverage"] = {
            "status": "matching" if result.total_runs > 0 else "no_match",
            "ui_label": "MATCHING TESTS FOUND" if result.total_runs > 0 else "NO MATCH IN INDEXED SOURCES",
            "scope": "core_search",
            "corpus_id": f"{inv_filter or 'PSI-25 + PSI-69'} Tabular",
            "corpus_version": "PSI-25_v1+PSI-69_v1",
            "requested_conditions": {
                "investigation_id": inv_filter,
                "fuel": req.fuel,
                "numeric_filters": [f.model_dump(exclude_unset=True) for f in req.numeric_filters],
            },
            "applied_filters": data["applied_filters"],
            "matching_record_ids": [r.record_pk for r in result.records[:50]],
            "matching_count": result.total_runs,
            "total_corpus_count": len(self.records),
            "differing_or_missing_conditions": [
                "Search filters operate strictly over PSI-25 (107 BASS-II runs, % vol) and PSI-69 (274 FLEX runs, % mol)."
            ],
            "tolerance_policy": {
                "mode": "exact_contract",
                "applied_tolerance": "Contract bounds + explicit unit normalization.",
                "rationale": "Verified table rows matching exact active filters.",
                "is_advisory_only": result.total_runs == 0,
            },
            "limitations": [
                "Categorical similarity does not imply material equivalence.",
                "No match means absent from PSI-25/PSI-69 tables, never that NASA never tested a condition.",
            ],
        }
        return envelope(data, "OK" if result.total_runs else "NO_EVIDENCE")

    def detail(self, payload: dict) -> dict:
        pk = parse_request(DetailRequest, payload).record_pk
        if pk not in self.by_pk:
            raise ValueError("Unknown record_pk.")
        rec = self.by_pk[pk]
        return envelope({"record_pk": pk, "investigation_id": rec.investigation_id,
            "test_id": rec.test_id, "fuel": rec.normalized_fields["fuel_raw"],
            "source": asdict(rec.source), "raw_fields": rec.raw_fields,
            "measurements": {k: _serialize_measurement(v) for k, v in rec.measurements.items()},
            "quality_flags": list(rec.quality_flags), "boundary": BOUNDARY})

    def compare(self, payload: dict) -> dict:
        pks = list(parse_request(CompareRequest, payload).record_pks)
        if any(pk not in self.by_pk for pk in pks) or len(set(pks)) != len(pks):
            raise ValueError("Select 2–4 distinct, existing record_pks.")
        # Yeniden hesaplama yok: mevcut karşılaştırma sözleşmesi korunur.
        fields = sorted({k for pk in pks for k in self.by_pk[pk].measurements})
        result = compare_records(self.records, record_pks=pks, field_names=fields).to_dict()
        result["boundary_note"] = BOUNDARY
        result["details"] = [self.detail({"record_pk": pk})["data"] for pk in pks]
        return envelope(result)

    def documents(self, payload: dict) -> dict:
        req = parse_request(DocumentsRequest, payload)
        query, top_k, inv = req.query, req.top_k, req.investigation_id
        if inv is not None and inv not in DATASET_SPECS:
            raise ValueError("investigation_id must be a core study (PSI-25 or PSI-69).")
        if self.index is None:
            cov = assess_unavailable_coverage(
                scope="documents",
                corpus_id="NASA Primary Report BM25 Index",
                error_detail="Documents index is unavailable in this environment.",
                requested_conditions={"query_provided": bool(query.strip()), **({"investigation_id": inv} if inv else {})},
            ).to_dict()
            return envelope(None, "CORPUS_UNAVAILABLE", "Documents are unavailable; table search remains available.", coverage=cov)
        result = self.index.search(query, investigation_id=inv, top_k=top_k,
                                   use_bilingual_aliases=False).to_dict()
        result["corpus_status"] = self.corpus_status
        result["boundary"] = "Lexical relevance is not scientific verification or a fire-safety score."
        hits = result.get("hits") or []
        result["coverage"] = {
            "status": "related" if hits else "no_match",
            "ui_label": "RELATED TESTS ONLY" if hits else "NO MATCH IN INDEXED SOURCES",
            "scope": "documents",
            "corpus_id": "NASA/TP-2015-216046 + NASA/TM-20210011385 + BASS-II ReadMe",
            "corpus_version": "corpus_v1",
            "requested_conditions": {"query_provided": bool(query.strip()), **({"investigation_id": inv} if inv else {})},
            "applied_filters": {"investigation_id": inv, "top_k": top_k},
            "matching_record_ids": [h.get("chunk_id") for h in hits if h.get("chunk_id")],
            "matching_count": len(hits),
            "total_corpus_count": len(self.index.chunks),
            "differing_or_missing_conditions": [
                "BM25 matches report text lexically; it does not verify exact numeric table conditions."
            ],
            "tolerance_policy": {
                "mode": "window_advisory",
                "applied_tolerance": "BM25 lexical token match",
                "rationale": "Retrieved primary passages for inspection; lexical relevance is not verification.",
                "is_advisory_only": True,
            },
            "limitations": [
                "BM25 score is a lexical search weight, never a safety or validity score."
            ],
        }
        return envelope(result, "OK" if result["hits"] else "NO_EVIDENCE")

    def _build_evidence_bundle(self, req: EvidenceRequestIn | dict) -> tuple[EvidenceBundle, str, str]:
        """Construct an EvidenceBundle from a scope-resolved request (raw dicts are validated first)."""
        if not isinstance(req, EvidenceRequestIn):
            req = parse_request(EvidenceRequestIn, req)
        scope = req.scope or "core"
        if scope == "auto":
            raise ValueError("scope must be resolved before building evidence.")
        evidence_req = EvidenceRequest(
            query=req.query,
            investigation_id=req.investigation_id,
            fuel=req.fuel,
            test_end=req.test_end,
            numeric_filters=_to_range_filters(req.numeric_filters),
            include_approximate=req.include_approximate,
            summarize_field_name=req.summarize_field_name,
            summarize_unit=req.summarize_unit,
            compare_record_pks=tuple(req.compare_record_pks),
            compare_field_names=tuple(req.compare_field_names) if req.compare_field_names is not None else None,
            top_k=req.top_k,
            use_bilingual_aliases=req.use_bilingual_aliases,
            run_table_query=req.run_table_query,
            max_table_citations=req.max_table_citations,
            scope=scope,
        )
        if scope == "saffire_case":
            if self.saffire_case is None:
                raise ValueError("SAFFIRE IV–VI case study module is unavailable.")
            bundle = build_saffire_case_evidence_bundle(evidence_req, dataset=self.saffire_case)
        elif scope == "flex_prediction":
            if self.flex_predictor is None:
                raise ValueError("FLEX condition prediction module is unavailable.")
            flex_cond = req.flex_condition
            if flex_cond is None:
                raise FlexPredictionValidationError("flex_condition must be a JSON object when scope='flex_prediction'.")
            bundle = build_flex_prediction_evidence_bundle(
                evidence_req,
                bundle=self.flex_predictor,
                flex_condition=flex_cond,
                records_by_pk=self.by_pk,
                bm25_index=self.index,
            )
        else:
            bundle = build_evidence_bundle(evidence_req, records=self.records, bm25_index=self.index)
        if bundle.abstention.abstained:
            status = "NO_EVIDENCE" if bundle.abstention.reason_code == "NO_MATCHING_EVIDENCE" else "ABSTAINED"
            msg = bundle.abstention.explanation or ""
        else:
            status, msg = "OK", ""
        return bundle, status, msg

    def _build_scope_early_envelope(
        self,
        *,
        early_info: dict[str, Any],
        routing: dict[str, Any],
        for_answer: bool,
    ) -> dict[str, Any]:
        """Return a deterministic non-LLM scope clarification or pooling boundary response."""
        outside_domain = early_info["reason_code"] == "OUT_OF_DOMAIN_QUERY"
        cov = {
            "status": "no_match" if outside_domain else "related",
            "ui_label": early_info["ui_label"],
            "scope": routing["requested_scope"],
            "corpus_id": "GeNAIus Scope Router (Unpooled Corpora)",
            "corpus_version": "scope_router_v1",
            "requested_conditions": {"query": early_info["query"], "requested_scope": routing["requested_scope"]},
            "applied_filters": {"resolved_scope": routing["resolved_scope"]},
            "matching_record_ids": [],
            "matching_count": 0,
            "total_corpus_count": 0 if outside_domain else len(self.records),
            "differing_or_missing_conditions": [early_info["explanation"]],
            "tolerance_policy": {
                "mode": "exact_contract",
                "applied_tolerance": "Strict NASA corpus separation",
                "rationale": early_info["limitation"],
                "is_advisory_only": False,
            },
            "limitations": [early_info["limitation"]],
        }
        abstention = {
            "abstained": True,
            "reason_code": early_info["reason_code"],
            "explanation": early_info["explanation"],
        }
        if not for_answer:
            return envelope(
                {
                    "mode": "scope_guardrail",
                    "abstention": abstention,
                    "coverage": cov,
                    "citations": [],
                    "scope_routing": routing,
                    "corpus_status": self.corpus_status,
                },
                "ABSTAINED",
                early_info["explanation"],
                mode="deterministic",
                llm_enabled=False,
                coverage=cov,
            )
        return envelope(
            {
                "status": "ABSTAINED",
                "answer_mode": "deterministic",
                "llm_used": False,
                "resolved_investigation_id": None,
                "summary": early_info["summary"],
                "findings": [],
                "limitations": [early_info["limitation"]],
                "warnings": [],
                "disclaimers": [BOUNDARY],
                "sources": [],
                "citation_ids": [],
                "abstention": abstention,
                "evidence_overview": {
                    "query": early_info["query"],
                    "table_total_runs": 0,
                    "table_shown_runs": 0,
                    "document_hit_count": 0,
                    "citation_count": 0,
                },
                "coverage": cov,
                "numerical_audit": {
                    "checked": True,
                    "status": "skipped",
                    "reason": "Stopped by deterministic scope router before LLM invocation.",
                    "violation_count": 0,
                    "checked_claim_count": 0,
                },
                "failure_reason": "NONE",
                "scope_routing": routing,
                "corpus_status": self.corpus_status,
            },
            "ABSTAINED",
            early_info["explanation"],
            mode="deterministic",
            llm_enabled=False,
            coverage=cov,
        )

    def evidence(self, payload: dict) -> dict:
        """Combine typed table results, field summaries, comparisons, and BM25 passages."""
        effective_req, routing, early_info = resolve_scope(parse_request(EvidenceRequestIn, payload))
        if early_info is not None:
            return self._build_scope_early_envelope(early_info=early_info, routing=routing, for_answer=False)
        scope = routing["resolved_scope"]
        if scope == "saffire_case" and self.saffire_case is None:
            return _unavailable(_SAFFIRE_CASE_GAP, "Optional SAFFIRE IV–VI case study module is unavailable.", data_extra={"scope_routing": routing})
        if scope == "flex_prediction" and self.flex_predictor is None:
            return _unavailable(_FLEX_GAP, "Optional FLEX condition prediction artifact is unavailable.", data_extra={"scope_routing": routing})
        bundle, status, msg = self._build_evidence_bundle(effective_req)
        data = bundle.to_dict()
        data["corpus_status"] = self.corpus_status
        data["scope_routing"] = routing
        return envelope(data, status, msg)

    def _prevention_payload(self) -> dict[str, Any]:
        return build_prevention_summary(self.records, case_raw=self.saffire_case.raw if self.saffire_case else None)

    def prevention_summary(self) -> dict:
        """Shared prevention evidence summary (Data page section and chatbot use the same payload)."""
        return envelope(self._prevention_payload(), "OK", mode="prevention_evidence_summary", llm_enabled=False)

    def _table_answer(self, req: EvidenceRequestIn) -> dict[str, Any] | None:
        """Deterministic table answer for plain Core questions; runs before (and instead of) any LLM call.

        Structured requests (filters, comparisons, summaries) keep the evidence pipeline; the same
        abstention gate as the evidence path applies first, and an explicit study selection is honoured.
        """
        if req.numeric_filters or req.compare_record_pks or req.summarize_field_name or req.fuel or req.test_end:
            return None
        if evaluate_abstention_gate(req.query, investigation_id=req.investigation_id).abstained:
            return None
        table = try_table_answer(req.query, self.records)
        if table is None:
            return None
        if req.investigation_id is not None and table.get("resolved_investigation_id") != req.investigation_id:
            return None
        return table

    def answer(self, payload: dict) -> dict:
        """Produce a traceable evidence-backed answer in deterministic or bounded-LLM mode."""
        effective_req, routing, early_info = resolve_scope(parse_request(EvidenceRequestIn, payload))
        if early_info is not None:
            return self._build_scope_early_envelope(early_info=early_info, routing=routing, for_answer=True)
        scope = routing["resolved_scope"]
        if scope == "saffire_case" and self.saffire_case is None:
            return _unavailable(_SAFFIRE_CASE_GAP, "Optional SAFFIRE IV–VI case study module is unavailable.", data_extra={"failure_reason": "SOURCE_UNAVAILABLE", "scope_routing": routing})
        if scope == "flex_prediction" and self.flex_predictor is None:
            return _unavailable(_FLEX_GAP, "Optional FLEX condition prediction artifact is unavailable.", data_extra={"failure_reason": "SOURCE_UNAVAILABLE", "scope_routing": routing})
        scenario = parse_scenario_question(effective_req.query or "") if scope == "core" else None
        report = parse_report_question(effective_req.query or "") if scope == "core" and scenario is None else None
        if scenario is not None or report is not None:
            data = (scenario_answer_payload(self.scenario_checker.check(**scenario)) if scenario is not None
                    else report_answer_payload(self.scenario_checker.habitat_report(**report)))
            data["corpus_status"] = self.corpus_status
            data["scope_routing"] = routing
            return envelope(data, "OK", "", mode="scenario_check", llm_enabled=False)
        if scope == "core" and is_prevention_question(_fold_text(effective_req.query or "")) and not \
                evaluate_abstention_gate(effective_req.query).abstained:
            data = prevention_answer(self._prevention_payload())
            data["corpus_status"] = self.corpus_status
            data["scope_routing"] = routing
            return envelope(data, "OK", "", mode="prevention_summary", llm_enabled=False)
        if scope == "core":
            table = self._table_answer(effective_req)
            if table is not None:
                table["corpus_status"] = self.corpus_status
                table["scope_routing"] = routing
                return envelope(table, "OK", "", mode=TABLE_ANSWER_MODE, llm_enabled=False)
        bundle, _, msg = self._build_evidence_bundle(effective_req)
        result = generate_grounded_answer(bundle, llm_adapter=self.answer_adapter)
        data = result.to_dict()
        data["corpus_status"] = self.corpus_status
        data["scope_routing"] = routing
        return envelope(
            data,
            result.status,
            msg,
            mode=result.answer_mode,
            llm_enabled=result.llm_used,
        )

    def catalog_filters(self) -> dict:
        """Return available filter values and core-support boundaries from the 24-study catalog."""
        if self.catalog is None:
            return _unavailable(_CATALOG_GAP, "Catalog index is temporarily unavailable; core experiment and document endpoints remain available.")
        filters = self.catalog.available_filters()
        data = {
            "total_studies": len(self.catalog.entries),
            "catalog_status": self.catalog_status,
            "catalog_generated_utc": self.catalog.manifest_generated_utc,
            "core_investigation_ids": list(self.catalog.core_investigation_ids),
            **filters,
        }
        return envelope(data, "OK", mode="catalog_lookup_only", llm_enabled=False)

    def catalog_search(self, payload: dict) -> dict:
        """Search or filter the 24-study NASA PSI Combustion catalog via catalog.py."""
        req = parse_request(CatalogSearchRequest, payload)
        query, project_type, sub_research_area = req.query, req.project_type, req.sub_research_area
        queryable_in_core, top_k = req.queryable_in_core, req.top_k

        if self.catalog is None:
            return _unavailable(_CATALOG_GAP, "Catalog index is temporarily unavailable; core experiment and document endpoints remain available.")

        data = search_catalog(
            self.catalog,
            query=query,
            project_type=project_type,
            sub_research_area=sub_research_area,
            queryable_in_core=queryable_in_core,
            top_k=top_k,
        ).to_dict()
        data["catalog_status"] = self.catalog_status
        return envelope(data, status=data["status"], mode="catalog_lookup_only", llm_enabled=False)

    @staticmethod
    def _analytics_args(req: AnalyticsRequest) -> dict[str, Any]:
        args: dict[str, Any] = {
            "investigation_id": req.investigation_id,
            "field_name": req.field_name,
            "unit": req.unit,
            "fuel": req.fuel,
            "test_end": req.test_end,
            "numeric_filters": _to_range_filters(req.numeric_filters),
            "include_approximate": req.include_approximate,
        }
        if isinstance(req, ExportRequest):
            args["export_format"] = req.format
        return args

    def analytics(self, payload: dict) -> dict:
        """Compute single-study descriptive summary, raw chart points, and status distributions."""
        args = self._analytics_args(parse_request(AnalyticsRequest, payload))
        data = build_descriptive_analytics(self.records, **args).to_dict()
        return envelope(
            data,
            "OK" if data["total_runs"] > 0 else "NO_EVIDENCE",
            mode="descriptive_analytics_only",
            llm_enabled=False,
        )

    def export(self, payload: dict) -> dict:
        """Export descriptive subset with provenance and formula-safe CSV or strict JSON."""
        args = self._analytics_args(parse_request(ExportRequest, payload))
        data = build_export_payload(self.records, **args)
        return envelope(
            data,
            "OK" if data["total_runs"] > 0 else "NO_EVIDENCE",
            mode="descriptive_analytics_only",
            llm_enabled=False,
        )

    def analytics_flex(self, payload: dict) -> dict:
        """Return PSI-69 FLEX filtered descriptive summary, oxygen/diluent slices, and points."""
        req = parse_request(FlexAnalyticsRequest, payload)
        fuel, diluent = req.fuel, req.diluent
        float_args: dict[str, float | None] = {
            key: (float(val) if (val := getattr(req, key)) is not None else None)
            for key in ("o2_min_pct", "o2_max_pct", "p_min_atm", "p_max_atm", "target_o2_pct", "target_p_atm")
        }
        data = build_flex_analytics(
            self.records,
            fuel=fuel,
            diluent=diluent,
            **float_args,
        )
        return envelope(
            data,
            "OK" if data["total_runs"] > 0 else "NO_EVIDENCE",
            mode="descriptive_analytics_only",
            llm_enabled=False,
        )

    def analytics_materials(self, payload: dict) -> dict:
        """Return strictly verified PSI-25 (BASS-II) Material Lab descriptive analytics."""
        req = parse_request(MaterialLabRequest, payload)
        target_o2, window_pct = req.target_o2_pct, req.window_pct
        metric = req.metric or "delta_co_ppm"
        group_by = req.group_by or "material_family"
        pi, fr, raw_mats, dedupe = req.pi, req.flow_restrictor, req.materials, req.dedupe_samples
        data = build_material_lab_analytics(
            self.records,
            target_o2_pct=float(target_o2),
            window_pct=float(window_pct),
            metric=metric,
            group_by=group_by,
            flow_restrictor=fr,
            pi=pi,
            materials=tuple(raw_mats) if raw_mats is not None else None,
            dedupe_samples=dedupe,
        )
        return envelope(
            data,
            "OK" if data["total_runs"] > 0 else "NO_EVIDENCE",
            mode="descriptive_analytics_only",
            llm_enabled=False,
        )

    def cfi_schema(self) -> dict:
        """Return separate PSI-39 CFI descriptive schema, pool counts, filters, and boundaries."""
        if self.cfi is None:
            return envelope(
                None,
                "CFI_UNAVAILABLE",
                "Optional PSI-39 CFI module is unavailable; core PSI-25/PSI-69 endpoints remain available.",
                mode="cfi_descriptive_only",
                llm_enabled=False,
            )
        data = build_cfi_schema(self.cfi)
        data["cfi_status"] = self.cfi_status
        return envelope(data, "OK", mode="cfi_descriptive_only", llm_enabled=False)

    def cfi_analysis(self, payload: dict) -> dict:
        """Compute separate stratified descriptive CFI metrics without cross-study pooling."""
        req = parse_request(CfiAnalysisRequest, payload)
        pressure_atm, fiber, fuel, sensitivity_mode = req.pressure_atm, req.fiber, req.fuel, req.sensitivity_mode

        if self.cfi is None:
            # Reuse domain check without full dataset so bad values (e.g. pressure=3.0) still 400 cleanly.
            from .cfi import FUEL_ORDER, SENSITIVITY_MODES, SUPPORTED_PRESSURES_ATM
            if float(pressure_atm) not in SUPPORTED_PRESSURES_ATM or sensitivity_mode not in SENSITIVITY_MODES or (fuel is not None and fuel not in FUEL_ORDER):
                raise ValueError("Invalid CFI filter parameters.")
            return envelope(
                None,
                "CFI_UNAVAILABLE",
                "Optional PSI-39 CFI module is unavailable; core PSI-25/PSI-69 endpoints remain available.",
                mode="cfi_descriptive_only",
                llm_enabled=False,
            )

        data = run_cfi_analysis(
            self.cfi,
            pressure_atm=float(pressure_atm),
            fiber=fiber,
            fuel=fuel,
            sensitivity_mode=sensitivity_mode,
        )
        data["cfi_status"] = self.cfi_status
        return envelope(data, data["status"], mode="cfi_descriptive_only", llm_enabled=False)

    def saffire_schema(self) -> dict:
        """Return separate PSI-99 SAFFIRE-II reference schema, provenance, and limits."""
        if self.saffire is None:
            return envelope(
                None,
                "SAFFIRE_UNAVAILABLE",
                "Optional PSI-99 SAFFIRE-II module is unavailable; core PSI-25/PSI-69 and CFI endpoints remain available.",
                mode="saffire_reference_only",
                llm_enabled=False,
            )
        data = build_saffire_schema(self.saffire)
        data["saffire_status"] = self.saffire_status
        return envelope(data, "OK", mode="saffire_reference_only", llm_enabled=False)

    def saffire_reference(self, payload: dict) -> dict:
        """Return separate source-linked SAFFIRE-II sample reference cards (all 9 or 1 by sample_id)."""
        sample_id = validate_sample_id(parse_request(SaffireReferenceRequest, payload).sample_id)
        if self.saffire is None:
            return envelope(
                None,
                "SAFFIRE_UNAVAILABLE",
                "Optional PSI-99 SAFFIRE-II module is unavailable; core PSI-25/PSI-69 and CFI endpoints remain available.",
                mode="saffire_reference_only",
                llm_enabled=False,
            )
        data = run_saffire_reference(self.saffire, sample_id=sample_id)
        data["saffire_status"] = self.saffire_status
        return envelope(data, data["status"], mode="saffire_reference_only", llm_enabled=False)

    def saffire_case_schema(self) -> dict:
        """Return isolated SAFFIRE IV–VI cabin-air case schema, verified sources, and boundaries."""
        if self.saffire_case is None:
            return _unavailable(_SAFFIRE_CASE_GAP, "Optional SAFFIRE IV–VI case study module is unavailable; core and PSI-99 endpoints remain available.")
        data = build_saffire_case_schema(self.saffire_case)
        data["saffire_case_status"] = self.saffire_case_status
        return envelope(data, "OK", mode=SAFFIRE_CASE_MODE, llm_enabled=False)

    def saffire_case_reference(self, payload: dict) -> dict:
        """Return filtered SAFFIRE IV–VI case conditions, derived metrics, VI-3 timeline, and detection cards."""
        req = parse_request(SaffireCaseRequest, payload)
        tid, fl, fg = validate_case_filters(test_id=req.test_id, flight=req.flight, fuel_group=req.fuel_group)
        if self.saffire_case is None:
            return _unavailable(_SAFFIRE_CASE_GAP, "Optional SAFFIRE IV–VI case study module is unavailable; core and PSI-99 endpoints remain available.")
        data = run_saffire_case_reference(self.saffire_case, test_id=tid, flight=fl, fuel_group=fg)
        data["saffire_case_status"] = self.saffire_case_status
        return envelope(data, data["status"], mode=SAFFIRE_CASE_MODE, llm_enabled=False)

    def saffire_case_export(self, payload: dict) -> dict:
        """Export filtered SAFFIRE IV–VI case data (CSV or JSON) preserving null cells, derived tags, and limits."""
        req = parse_request(SaffireCaseExportRequest, payload, error_cls=SaffireCaseValidationError)
        fmt = req.format
        tid, fl, fg = validate_case_filters(test_id=req.test_id, flight=req.flight, fuel_group=req.fuel_group)
        if self.saffire_case is None:
            return _unavailable(_SAFFIRE_CASE_GAP, "Optional SAFFIRE IV–VI case study module is unavailable; core and PSI-99 endpoints remain available.")
        data = export_saffire_case(self.saffire_case, fmt=fmt, test_id=tid, flight=fl, fuel_group=fg)
        data["saffire_case_status"] = self.saffire_case_status
        return envelope(data, data["status"], mode=SAFFIRE_CASE_MODE, llm_enabled=False)

    def flex_prediction_schema(self) -> dict:
        """Return separate validated FLEX condition prediction schema, joint support gates, and CV metrics."""
        if self.flex_predictor is None:
            return _unavailable(_FLEX_GAP, "Optional FLEX condition prediction artifact is unavailable; core PSI-25/PSI-69 endpoints remain available.")
        data = build_flex_prediction_schema(self.flex_predictor)
        data["flex_predictor_status"] = self.flex_predictor_status
        return envelope(data, "OK", mode="flex_condition_prediction_only", llm_enabled=False)

    def flex_prediction(self, payload: dict) -> dict:
        """Validate pre-test FLEX condition inputs, apply joint-support gating, and return predictions."""
        validate_prediction_payload(payload)
        if self.flex_predictor is None:
            return _unavailable(_FLEX_GAP, "Optional FLEX condition prediction artifact is unavailable; core PSI-25/PSI-69 endpoints remain available.")
        data = run_flex_prediction(self.flex_predictor, payload)
        data["flex_predictor_status"] = self.flex_predictor_status
        return envelope(data, data["status"], mode="flex_condition_prediction_only", llm_enabled=False)

    def flex_prediction_map(self, payload: dict) -> dict:
        """Evaluate a bounded O2 vs diluent/pressure support grid (strict masking across unsupported gaps)."""
        if self.flex_predictor is None:
            return _unavailable(_FLEX_GAP, "Optional FLEX condition prediction artifact is unavailable; core PSI-25/PSI-69 endpoints remain available.")
        data = run_flex_condition_map(self.flex_predictor, payload)
        data["flex_predictor_status"] = self.flex_predictor_status
        return envelope(data, data["status"], mode="flex_condition_prediction_only", llm_enabled=False)

    def flex_prediction_export(self, payload: dict) -> dict:
        """Export a Condition Research Summary separating measured PSI-69, model estimates, and scope limits."""
        fmt = parse_request(FlexExportRequest, payload, error_cls=FlexPredictionValidationError).format
        cond_payload = {k: v for k, v in payload.items() if k != "format"}
        validate_prediction_payload(cond_payload)
        if self.flex_predictor is None:
            return _unavailable(_FLEX_GAP, "Optional FLEX condition prediction artifact is unavailable; core PSI-25/PSI-69 endpoints remain available.")
        data = build_flex_research_summary_export(self.flex_predictor, cond_payload, fmt=fmt)
        data["flex_predictor_status"] = self.flex_predictor_status
        return envelope(data, data["status"], mode="flex_condition_prediction_only", llm_enabled=False)

    def flex_reconciliation(self) -> dict:
        """Return provenance-linked reconciliation summary and entries between PSI-69 CSV and NASA TP Table IX."""
        if self.flex_reconciliation_data is None:
            return envelope(
                None,
                "FLEX_RECONCILIATION_UNAVAILABLE",
                "Optional FLEX Table IX reconciliation artifact is unavailable; core PSI-25/PSI-69 endpoints remain available.",
                mode="flex_reconciliation_only",
                llm_enabled=False,
            )
        data = dict(self.flex_reconciliation_data)
        data["flex_reconciliation_status"] = self.flex_reconciliation_status
        return envelope(data, "OK", mode="flex_reconciliation_only", llm_enabled=False)
