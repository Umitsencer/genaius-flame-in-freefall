"""Typed deterministic evidence-coverage assessment across GeNAIus scopes.

Distinguishes four mutually exclusive coverage outcomes:
- ``matching``    -> ``MATCHING TESTS FOUND``
- ``related``     -> ``RELATED TESTS ONLY``
- ``no_match``    -> ``NO MATCH IN INDEXED SOURCES``
- ``unavailable`` -> ``SOURCE UNAVAILABLE / ERROR``

This module never computes risk/safety scores, never interpolates missing gaps,
and never blurs model support gates with exact measured test matches.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

COVERAGE_STATUS_LABELS: dict[str, str] = {
    "matching": "MATCHING TESTS FOUND",
    "related": "RELATED TESTS ONLY",
    "no_match": "NO MATCH IN INDEXED SOURCES",
    "unavailable": "SOURCE UNAVAILABLE / ERROR",
}

DEFAULT_LIMITATIONS: tuple[str, ...] = (
    "Categorical or lexical similarity does not imply physical, chemical, or material equivalence.",
    "Nearest neighbors in feature space, query condition matches, and model support gates are distinct concepts.",
    "BM25 document scores and catalog ranking weights are search signals, never fire-risk or safety scores.",
    "No Match in Indexed Sources means absent from the indexed local corpora/tables, never that NASA never tested a condition.",
)


@dataclass(frozen=True)
class EvidenceCoverageAssessment:
    """Structured coverage metadata explaining what real evidence backs a result."""

    status: str
    ui_label: str
    scope: str
    corpus_id: str
    corpus_version: str
    requested_conditions: dict[str, Any]
    applied_filters: dict[str, Any]
    matching_record_ids: tuple[str, ...]
    matching_count: int
    total_corpus_count: int
    differing_or_missing_conditions: tuple[str, ...]
    tolerance_policy: dict[str, Any]
    limitations: tuple[str, ...]
    error_detail: str | None = None

    def __post_init__(self) -> None:
        if self.status not in COVERAGE_STATUS_LABELS:
            raise ValueError(f"Unsupported coverage status: {self.status!r}")
        expected = COVERAGE_STATUS_LABELS[self.status]
        if self.ui_label != expected:
            object.__setattr__(self, "ui_label", expected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "ui_label": self.ui_label,
            "scope": self.scope,
            "corpus_id": self.corpus_id,
            "corpus_version": self.corpus_version,
            "requested_conditions": dict(self.requested_conditions),
            "applied_filters": dict(self.applied_filters),
            "matching_record_ids": list(self.matching_record_ids),
            "matching_count": self.matching_count,
            "total_corpus_count": self.total_corpus_count,
            "differing_or_missing_conditions": list(self.differing_or_missing_conditions),
            "tolerance_policy": dict(self.tolerance_policy),
            "limitations": list(self.limitations),
            "error_detail": self.error_detail,
        }


def assess_unavailable_coverage(
    *,
    scope: str,
    corpus_id: str,
    error_detail: str,
    corpus_version: str = "unknown",
    requested_conditions: Mapping[str, Any] | None = None,
) -> EvidenceCoverageAssessment:
    """Return an explicit ``unavailable`` coverage outcome when a source fails to load."""
    return EvidenceCoverageAssessment(
        status="unavailable",
        ui_label=COVERAGE_STATUS_LABELS["unavailable"],
        scope=scope,
        corpus_id=corpus_id,
        corpus_version=corpus_version,
        requested_conditions=dict(requested_conditions or {}),
        applied_filters={},
        matching_record_ids=(),
        matching_count=0,
        total_corpus_count=0,
        differing_or_missing_conditions=(
            "Target dataset or evidence artifact could not be loaded or validated.",
        ),
        tolerance_policy={
            "mode": "unavailable",
            "applied_tolerance": "N/A",
            "rationale": "Coverage cannot be evaluated while source data is unavailable.",
            "is_advisory_only": False,
        },
        limitations=DEFAULT_LIMITATIONS,
        error_detail=error_detail,
    )


def _extract_request_filters(request: Any) -> dict[str, Any]:
    raw_filters = getattr(request, "numeric_filters", ()) or ()
    return {
        "investigation_id": getattr(request, "investigation_id", None),
        "fuel": getattr(request, "fuel", None),
        "test_end": getattr(request, "test_end", None),
        "include_approximate": bool(getattr(request, "include_approximate", False)),
        "numeric_filters": [
            {
                "field_name": f.field_name,
                "unit": f.unit,
                "min_value": f.min_value,
                "max_value": f.max_value,
                "min_inclusive": f.min_inclusive,
                "max_inclusive": f.max_inclusive,
            }
            for f in raw_filters
        ],
        "compare_record_pks": list(getattr(request, "compare_record_pks", ()) or ()),
        "summarize_field_name": getattr(request, "summarize_field_name", None),
        "summarize_unit": getattr(request, "summarize_unit", None),
    }


def assess_core_coverage(
    *,
    request: Any,
    abstention: Any,
    table_result: Any,
    field_summary: Any,
    comparison_result: Any,
    document_result: Any,
    total_corpus_count: int = 381,
    corpus_version: str = "PSI-25_v1+PSI-69_v1",
) -> EvidenceCoverageAssessment:
    """Assess deterministic evidence coverage for a core PSI-25/PSI-69 EvidenceBundle."""
    applied_filters = _extract_request_filters(request)
    raw_query = str(getattr(request, "query", None) or "").strip()
    requested_conditions: dict[str, Any] = {
        **({"query_provided": True} if raw_query else {}),
        **{k: v for k, v in applied_filters.items() if v not in (None, [], False)},
    }

    matched_ids: list[str] = []
    seen_ids: set[str] = set()
    if table_result is not None:
        for rec in getattr(table_result, "records", ()) or ():
            pk = getattr(rec, "record_pk", None)
            if pk and pk not in seen_ids:
                seen_ids.add(pk)
                matched_ids.append(pk)
    if comparison_result is not None:
        for row in getattr(comparison_result, "rows", ()) or ():
            pk = row.get("record_pk") if isinstance(row, Mapping) else getattr(row, "record_pk", None)
            if pk and pk not in seen_ids:
                seen_ids.add(pk)
                matched_ids.append(pk)

    doc_hits = list(getattr(document_result, "hits", ()) or ()) if document_result is not None else []
    diff_notes: list[str] = []

    inv_id = getattr(request, "investigation_id", None)
    if inv_id == "PSI-25":
        diff_notes.append(
            "PSI-25 (BASS-II) records gas concentration in % vol (air + N2/O2); chamber pressure and gravity are not numeric columns."
        )
    elif inv_id == "PSI-69":
        diff_notes.append(
            "PSI-69 (FLEX) covers microgravity isolated spherical droplets (heptane/methanol/% mol diluent), not solid-sheet or forced-flow tests."
        )
    else:
        diff_notes.append(
            "Indexed table corpora cover PSI-25 (107 BASS-II runs, % vol) and PSI-69 (274 FLEX runs, % mol); units are never auto-merged."
        )

    if getattr(abstention, "abstained", False):
        reason = str(getattr(abstention, "reason_code", None) or getattr(abstention, "reason", "") or "")
        msg = str(getattr(abstention, "explanation", None) or getattr(abstention, "message", "") or "")
        diff_notes.append(f"Request boundary triggered ({reason}): {msg}")
        return EvidenceCoverageAssessment(
            status="no_match",
            ui_label=COVERAGE_STATUS_LABELS["no_match"],
            scope=getattr(request, "scope", "core") or "core",
            corpus_id="PSI-25 + PSI-69 Tabular + NASA/TP-2015-216046 / NASA/TM-20210011385",
            corpus_version=corpus_version,
            requested_conditions=requested_conditions,
            applied_filters=applied_filters,
            matching_record_ids=(),
            matching_count=0,
            total_corpus_count=total_corpus_count,
            differing_or_missing_conditions=tuple(diff_notes),
            tolerance_policy={
                "mode": "exact_contract",
                "applied_tolerance": "Explicit numeric_filters bounds only; out-of-scope studies abstained.",
                "rationale": "Deterministic contract boundaries reject speculative extrapolation.",
                "is_advisory_only": False,
            },
            limitations=DEFAULT_LIMITATIONS,
        )

    matched_count = len(matched_ids)
    has_structured_filters = bool(
        applied_filters["investigation_id"]
        or applied_filters["fuel"]
        or applied_filters["test_end"]
        or applied_filters["numeric_filters"]
        or applied_filters["compare_record_pks"]
        or applied_filters["summarize_field_name"]
    )
    has_summary_used = bool(
        field_summary is not None and getattr(field_summary, "used_total_count", 0) > 0
    )

    if matched_count > 0 or has_summary_used:
        status = "matching"
        rationale = "Filtered deterministic table query returned verified records satisfying the requested criteria."
        if matched_count == 0 and has_summary_used:
            # Summarize ran on verified rows
            matched_ids = list(getattr(field_summary, "used_record_pks", ()) or ())
            matched_count = len(matched_ids)
    elif doc_hits:
        status = "related"
        if has_structured_filters:
            diff_notes.append(
                "Active structured table filters matched 0 experiment rows; only BM25 report passages matched lexically."
            )
            rationale = "Exact structured filters returned 0 table runs; lexical passages provide contextual reference only."
        else:
            diff_notes.append(
                "No filtered table rows were selected; BM25 report passages matched lexically without structured condition filtering."
            )
            rationale = "Lexical BM25 passages found; add structured condition filters for exact run matching."
    else:
        status = "no_match"
        diff_notes.append("0 table runs and 0 BM25 document chunks matched the query filters.")
        rationale = "No matching records or report chunks in indexed PSI-25/PSI-69 sources."

    return EvidenceCoverageAssessment(
        status=status,
        ui_label=COVERAGE_STATUS_LABELS[status],
        scope=getattr(request, "scope", "core") or "core",
        corpus_id="PSI-25 + PSI-69 Tabular + NASA Reports",
        corpus_version=corpus_version,
        requested_conditions=requested_conditions,
        applied_filters=applied_filters,
        matching_record_ids=tuple(matched_ids[:50]),
        matching_count=matched_count,
        total_corpus_count=total_corpus_count,
        differing_or_missing_conditions=tuple(diff_notes),
        tolerance_policy={
            "mode": "exact_contract",
            "applied_tolerance": "Contract bounds + explicit unit normalization (exact inclusive/exclusive checks).",
            "rationale": rationale,
            "is_advisory_only": status != "matching",
        },
        limitations=DEFAULT_LIMITATIONS,
    )


def assess_flex_analytics_coverage(analytics_payload: Mapping[str, Any]) -> EvidenceCoverageAssessment:
    """Assess evidence coverage for FLEX condition analytics (strict vs broad window)."""
    match = analytics_payload.get("condition_match") or {}
    match_level = str(match.get("match_level") or "broad")
    total_runs = int(analytics_payload.get("corpus_total_runs") or analytics_payload.get("total_runs") or 274)
    matched_runs = int(analytics_payload.get("matched_runs") or 0)
    filters = analytics_payload.get("applied_filters") or {}
    runs = analytics_payload.get("runs") or []
    matched_ids = tuple(
        str(r.get("record_pk"))
        for r in runs[:50]
        if isinstance(r, Mapping) and r.get("record_pk")
    )

    o2_win = match.get("o2_window_pct")
    p_win = match.get("p_window_atm")
    diff_notes = [
        "PSI-69 FLEX represents microgravity spherical droplets (n-heptane / methanol) in O2/diluent mixtures.",
        "Empty cells in the O2 x Pressure coverage matrix indicate no tested PSI-69 runs at that combination (never interpolated).",
    ]

    if matched_runs > 0 and match_level == "matched":
        status = "matching"
        tol_mode = "exact_contract"
        advisory = False
        rationale = "Real PSI-69 droplet runs found inside the specified condition filter/window."
    elif matched_runs > 0:
        status = "related"
        tol_mode = "window_advisory"
        advisory = True
        diff_notes.append(
            f"Showing broader matching PSI-69 neighborhood ({matched_runs} of {total_runs} runs); verify exact O2/Pressure cell counts."
        )
        rationale = "Related PSI-69 runs returned under advisory condition window; not an exact single-point match."
    else:
        status = "no_match"
        tol_mode = "exact_contract"
        advisory = True
        diff_notes.append(
            "0 PSI-69 runs matched the active fuel/diluent/O2/Pressure filter combination."
        )
        rationale = "No tested PSI-69 run falls inside the active condition filters."

    return EvidenceCoverageAssessment(
        status=status,
        ui_label=COVERAGE_STATUS_LABELS[status],
        scope="analytics_flex",
        corpus_id="PSI-69 FLEX (Table IX verified)",
        corpus_version="PSI-69_v1_274_runs",
        requested_conditions=dict(filters),
        applied_filters=dict(filters),
        matching_record_ids=matched_ids,
        matching_count=matched_runs,
        total_corpus_count=total_runs,
        differing_or_missing_conditions=tuple(diff_notes),
        tolerance_policy={
            "mode": tol_mode,
            "applied_tolerance": f"O2 window: {o2_win} % mol; Pressure window: {p_win} atm",
            "rationale": rationale,
            "is_advisory_only": advisory,
        },
        limitations=DEFAULT_LIMITATIONS,
    )


def assess_material_lab_coverage(lab_payload: Mapping[str, Any]) -> EvidenceCoverageAssessment:
    """Assess evidence coverage for PSI-25 BASS-II solid-material screening."""
    total_runs = int(lab_payload.get("total_runs") or 0)
    matched_runs = int(lab_payload.get("matched_runs") or 0)
    filters = lab_payload.get("applied_filters") or {}
    runs = lab_payload.get("runs") or []
    matched_ids = tuple(
        str(r.get("record_pk"))
        for r in runs[:50]
        if isinstance(r, Mapping) and r.get("record_pk")
    )
    diff_notes = [
        "PSI-25 (BASS-II) tabulates O2 (% vol) and sample material/geometry only; chamber pressure and gravity are not recorded as calibrated columns.",
        "Exploratory habitat atmosphere presets (e.g. Moon 34% O2 / 8.2 psi) are hypothetical planning scenarios, not NASA Lunar 1/6g test evidence.",
    ]

    if matched_runs > 0:
        tight_count = int(lab_payload.get("tight_matched_runs") or 0)
        near_only = tight_count == 0
        status = "matching" if not near_only else "related"
        rationale = (
            "Matching PSI-25 BASS-II runs found for the active material and O2 filters."
            if status == "matching"
            else "Only advisory O2-window PSI-25 runs matched; pressure and partial gravity remain unverified."
        )
    else:
        status = "no_match"
        diff_notes.append("0 PSI-25 BASS-II runs matched the requested material/O2/outcome filters.")
        rationale = "No matching records in PSI-25 BASS-II under the active filters."

    return EvidenceCoverageAssessment(
        status=status,
        ui_label=COVERAGE_STATUS_LABELS[status],
        scope="analytics_materials",
        corpus_id="PSI-25 BASS-II (Table verified)",
        corpus_version="PSI-25_v1_107_runs",
        requested_conditions=dict(filters),
        applied_filters=dict(filters),
        matching_record_ids=matched_ids,
        matching_count=matched_runs,
        total_corpus_count=total_runs,
        differing_or_missing_conditions=tuple(diff_notes),
        tolerance_policy={
            "mode": "window_advisory" if status == "related" else "exact_contract",
            "applied_tolerance": f"O2 (% vol) window filter from PSI-25 target ({filters.get('target_o2')})",
            "rationale": rationale,
            "is_advisory_only": status != "matching",
        },
        limitations=DEFAULT_LIMITATIONS,
    )


def assess_flex_predictor_coverage(prediction_payload: Mapping[str, Any]) -> EvidenceCoverageAssessment:
    """Assess evidence coverage for a FLEX condition prediction while keeping gates distinct.

    Separates:
    1) exact/near query point match in PSI-69 measured runs,
    2) nearest-neighbor training distance (similarity reference only), and
    3) convex/Mahalanobis training support gate (model admissibility).
    """
    norm_in = dict(prediction_payload.get("normalized_input") or {})
    gate = dict(prediction_payload.get("support") or prediction_payload.get("support_gate") or {})
    neighbors = list(
        gate.get("nearest_experiments")
        or prediction_payload.get("nearest_neighbors")
        or []
    )
    neighbor_ids = tuple(
        str(n.get("record_pk"))
        for n in neighbors[:10]
        if isinstance(n, Mapping) and n.get("record_pk")
    )

    in_support = bool(gate.get("supported", gate.get("in_support", False)))
    nearest_dist = gate.get("nearest_distance_std")
    dist_thresh = gate.get("distance_threshold_std")
    fuel = str(norm_in.get("fuel") or "")
    diluent = str(norm_in.get("diluent_regime") or norm_in.get("diluent_family") or "")

    # Exact condition match only when fuel matches and standardized feature distance is <= 0.05
    exact_match_neighbors = [
        str(n.get("record_pk"))
        for n in neighbors
        if isinstance(n, Mapping)
        and isinstance(n.get("distance_std"), (int, float))
        and float(n["distance_std"]) <= 0.05
        and str(n.get("fuel") or "") == fuel
    ]

    o2_pct_display = (
        round(float(norm_in["o2_mol_frac"]) * 100.0, 2)
        if isinstance(norm_in.get("o2_mol_frac"), (int, float))
        else norm_in.get("o2_pct")
    )
    p_atm_display = (
        round(float(norm_in["pressure_mmhg"]) / 760.0, 3)
        if isinstance(norm_in.get("pressure_mmhg"), (int, float))
        else norm_in.get("pressure_atm")
    )
    d0_display = norm_in.get("droplet_initial_diameter_mm", norm_in.get("d0_mm"))

    diff_notes = [
        f"Requested condition ({fuel}, {diluent}, O2={o2_pct_display}%, P={p_atm_display} atm, d0={d0_display} mm).",
        "Nearest neighbors are geometric feature-space references only; they are NOT equivalent to the queried test condition.",
        "Model predictions (ridge_phys8 / logit_phys10) carry origin_type='model_prediction' and are distinct from NASA measured values.",
    ]

    if exact_match_neighbors:
        status = "matching"
        rationale = (
            f"PSI-69 includes near-identical measured run(s) within <=0.05 std distance ({', '.join(exact_match_neighbors)}); model estimate complements those runs."
        )
        matching_ids = tuple(exact_match_neighbors)
    elif in_support and neighbor_ids:
        status = "related"
        diff_notes.append(
            f"Inside training support gate (nearest_distance_std={nearest_dist} <= {dist_thresh}), but no exact single-point NASA duplicate exists at this input."
        )
        rationale = "Condition lies inside PSI-69 training support with nearby reference runs; prediction remains an empirical statistical estimate."
        matching_ids = neighbor_ids
    else:
        status = "no_match"
        reason_list = gate.get("reasons") or []
        reason = gate.get("reason") or ("; ".join(str(r) for r in reason_list) if reason_list else "Outside PSI-69 training domain")
        diff_notes.append(f"Support gate rejected condition: {reason}")
        rationale = "No PSI-69 training support at this condition; model estimates are withheld to prevent unvalidated extrapolation."
        matching_ids = ()

    return EvidenceCoverageAssessment(
        status=status,
        ui_label=COVERAGE_STATUS_LABELS[status],
        scope="flex_prediction",
        corpus_id="PSI-69 FLEX Empirical Predictor (Görev 049/050-B)",
        corpus_version="flex_condition_models_v1",
        requested_conditions=norm_in,
        applied_filters={
            "fuel": fuel,
            "diluent_regime": diluent,
            "in_support": in_support,
            "nearest_distance_std": nearest_dist,
            "distance_threshold_std": dist_thresh,
        },
        matching_record_ids=matching_ids,
        matching_count=len(matching_ids),
        total_corpus_count=274,
        differing_or_missing_conditions=tuple(diff_notes),
        tolerance_policy={
            "mode": "exact_contract" if status == "matching" else "nearest_neighbor_only",
            "applied_tolerance": f"exact <=0.05 std; support gate <= {dist_thresh} std (1D/feature domain checks)",
            "rationale": rationale,
            "is_advisory_only": status != "matching",
        },
        limitations=DEFAULT_LIMITATIONS,
    )


def assess_saffire_case_coverage(
    case_payload: Mapping[str, Any],
    *,
    requested_query: str | None = None,
    abstention: Any = None,
) -> EvidenceCoverageAssessment:
    """Assess evidence coverage for verified SAFFIRE IV–VI gas & detection case study."""
    tests = list(case_payload.get("records") or case_payload.get("tests") or [])
    matched_ids = tuple(
        str(t.get("test_id"))
        for t in tests
        if isinstance(t, Mapping) and t.get("test_id")
    )
    summary_block = case_payload.get("summary") or {}
    total_case_records = int(summary_block.get("total_condition_records") or len(matched_ids) or 7)
    diff_notes = [
        "Verified case metrics come exclusively from SAFFIRE IV, V, and VI published summary records (gas rises + alarm timing).",
        "Atmospheric volume changes (Delta CO2 / Delta CO) are post-fire compartment measurements, NOT direct crew toxicity/dose calculations.",
        "Unreported cells (e.g. SAFFIRE V-3, V-4) remain explicitly missing (null) and are never coerced to zero.",
    ]

    if abstention is not None and getattr(abstention, "abstained", False):
        reason = str(getattr(abstention, "reason_code", None) or getattr(abstention, "reason", "") or "")
        msg = str(getattr(abstention, "explanation", None) or getattr(abstention, "message", "") or "")
        diff_notes.append(f"Case guardrail triggered ({reason}): {msg}")
        return EvidenceCoverageAssessment(
            status="no_match",
            ui_label=COVERAGE_STATUS_LABELS["no_match"],
            scope="saffire_case",
            corpus_id="SAFFIRE IV–VI Case Study (Verified Published Sources)",
            corpus_version="saffire_case_v1",
            requested_conditions={"query_provided": True} if requested_query else {},
            applied_filters={"study": "SAFFIRE IV–VI"},
            matching_record_ids=(),
            matching_count=0,
            total_corpus_count=len(matched_ids),
            differing_or_missing_conditions=tuple(diff_notes),
            tolerance_policy={
                "mode": "exact_contract",
                "applied_tolerance": "Strict reported / derived SAFFIRE IV–VI fields only; crew toxicity/unreported runs abstained.",
                "rationale": msg,
                "is_advisory_only": True,
            },
            limitations=DEFAULT_LIMITATIONS,
        )

    return EvidenceCoverageAssessment(
        status="matching" if matched_ids else "no_match",
        ui_label=COVERAGE_STATUS_LABELS["matching" if matched_ids else "no_match"],
        scope="saffire_case",
        corpus_id="SAFFIRE IV–VI Case Study (Verified Published Sources)",
        corpus_version="saffire_case_v1",
        requested_conditions={"query_provided": True} if requested_query else {},
        applied_filters={"study": "SAFFIRE IV–VI"},
        matching_record_ids=matched_ids,
        matching_count=len(matched_ids),
        total_corpus_count=total_case_records,
        differing_or_missing_conditions=tuple(diff_notes),
        tolerance_policy={
            "mode": "exact_contract",
            "applied_tolerance": "Exact published figures + documented deterministic derivations (pO2 kPa, 981 - 637 = 344 s).",
            "rationale": "All displayed gas increments and detector timings map directly to cited SAFFIRE IV–VI case tables.",
            "is_advisory_only": False,
        },
        limitations=DEFAULT_LIMITATIONS,
    )
