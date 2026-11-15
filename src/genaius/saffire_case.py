"""Standalone verified reference module for the SAFFIRE IV–VI cabin-air case study.

Keeps SAFFIRE IV–VI ("What did the fire do to the air?") and related SAME /
Fortenberry smoke-detection evidence strictly separate from:
- core PSI-25 (BASS-II) and PSI-69 (FLEX) 403 tables,
- PSI-99 (SAFFIRE-II 9 physical sample cards),
- PSI-39 (CFI) and FLEX droplet predictor modules.

All derived quantities (`pO2_kPa`, `344 s = 981 s - 637 s` elapsed threshold delta,
and threshold comparisons) are computed deterministically in Python and explicitly
labeled `derived`, while missing/unreported cells (such as V-3 / V-4 gas and
calorimetry fields) remain strictly `None` and are never coerced to zero.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .retrieval.bm25 import BM25Index, SearchResult, build_bm25_index
from .retrieval.documents import DocumentChunk
from .service import (
    BM25_SCORE_DISCLAIMER,
    COMPARISON_BOUNDARY_NOTE,
    AbstentionDecision,
    CitationItem,
    EvidenceBundle,
    EvidenceRequest,
    _fold_text,
)
from .claim_boundary import SOURCE_SCOPE_NOTE, asks_crew_harm, asks_gravity_transfer, asks_safety_judgment

SAFFIRE_CASE_RELPATH = "data/processed/saffire_case_reference.json"
SAFFIRE_CASE_ID = "SAFFIRE-CASE"
SAFFIRE_CASE_MODE = "saffire_case_reference"

VALID_CASE_FLIGHTS: tuple[str, ...] = ("Saffire IV", "Saffire V", "Saffire VI")
VALID_FUEL_GROUPS: tuple[str, ...] = ("thin_textile", "thick_pmma")
VALID_TEST_IDS: tuple[str, ...] = ("IV-1", "V-2", "V-3", "V-4", "VI-2", "VI-3", "VI-4")

CASE_BOUNDARY_DISCLAIMER = (
    "SAFFIRE IV–VI case study evidence is strictly separated from core 403 PSI-25/PSI-69 "
    "runs and PSI-99 SAFFIRE-II cards; published Cygnus delta readings do not establish "
    "human crew exposure safety, habitability certification, or partial-gravity predictions."
)

# Abstention patterns specifically for case-study human safety / certification / partial-g queries.
# Descriptive comparisons to published NASA-STD-3001 / JSC 20584 thresholds remain allowed.
_CASE_CREW_SAFETY_CERT_RE = re.compile(
    r"\b(?:"
    r"is\s+(?:this|it|saffire|the\s+(?:fire|cabin|air|atmosphere)|vi[-\s]*\d)\s+safe\b"
    r"|safe\s+for\s+(?:crew|humans?|astronauts?|breathing|habitation)"
    r"|certif(?:y|ication)\b"
    r"|(?:crew|human)\s+(?:survival|toxicity\s+score|health\s+risk\s+score|safe\s+exposure)"
    r"|safe(?:st|ty\s+rank(?:ing)?|ty\s+score)\s+(?:material|fuel|ranking)"
    r"|habitability\s+(?:clearance|compliance|approved)"
    r"|without\s+scrubb(?:ing|er)\s+(?:would\s+crew|can\s+crew|is\s+it\s+safe)"
    r")\b",
    re.IGNORECASE,
)
_CASE_CROSS_POOL_RE = re.compile(
    r"\b(?:pool(?:ed)?\s+with\s+(?:psi[-\s]*(?:25|69)|flex|bass)|merge\s+into\s+403)\b",
    re.IGNORECASE,
)

_TEST_ID_RE = re.compile(r"\b(IV-1|V-2|V-3|V-4|VI-2|VI-3|VI-4)\b", re.IGNORECASE)


class SaffireCaseError(RuntimeError):
    """Base error for standalone SAFFIRE IV–VI case study operations."""


class SaffireCaseLoadError(SaffireCaseError):
    """Raised when `data/processed/saffire_case_reference.json` is missing or invalid."""


class SaffireCaseValidationError(SaffireCaseError, ValueError):
    """Raised on invalid SAFFIRE IV–VI case API parameters."""


@dataclass(frozen=True)
class SaffireCaseDataset:
    """Immutable loaded bundle for SAFFIRE IV–VI conditions, timeline, detection evidence, and BM25."""

    raw: dict[str, Any]
    source_relpath: str
    source_sha256: str
    chunks: tuple[DocumentChunk, ...]
    bm25_index: BM25Index
    sources_by_id: dict[str, dict[str, Any]]
    records_by_id: dict[str, dict[str, Any]]
    detection_by_id: dict[str, dict[str, Any]]


def compute_po2_kpa(ambient_pressure_kpa: float | None, oxygen_mol_percent: float | None) -> float | None:
    """Deterministically compute derived oxygen partial pressure in kPa (`P * XO2 / 100`)."""
    if ambient_pressure_kpa is None or oxygen_mol_percent is None:
        return None
    return round(float(ambient_pressure_kpa) * float(oxygen_mol_percent) / 100.0, 2)


def compute_vi3_threshold_delta_s(ignition_time_s: float | None, threshold_time_s: float | None) -> float | None:
    """Deterministically compute derived elapsed seconds from ignition timestamp to threshold crossing."""
    if ignition_time_s is None or threshold_time_s is None:
        return None
    return round(float(threshold_time_s) - float(ignition_time_s), 2)


def _enrich_record_with_derived(raw_rec: Mapping[str, Any], thresholds: Mapping[str, Any]) -> dict[str, Any]:
    """Attach explicitly labeled derived values and NASA limit comparisons without mutating raw fields."""
    rec = dict(raw_rec)
    po2 = compute_po2_kpa(rec.get("ambient_pressure_kpa"), rec.get("oxygen_mol_percent"))

    co_ppm = rec.get("co_increase_ppm")
    co2_mmhg = rec.get("co2_partial_pressure_increase_mmhg")
    co_24h = float(thresholds["co_smac_24h_ppm"]["value"])
    co_1h = float(thresholds["co_smac_1h_ppm"]["value"])
    co2_1h = float(thresholds["co2_partial_pressure_1h_mmhg"]["value"])

    rec["derived"] = {
        "po2_kpa": {
            "value": po2,
            "unit": "kPa",
            "status": "derived" if po2 is not None else "unavailable",
            "formula": "ambient_pressure_kpa * oxygen_mol_percent / 100",
        },
        "threshold_comparisons": {
            "status": "derived_comparison_against_reported_limits" if rec.get("gas_calorimetry_reported") else "not_applicable_unreported_gas",
            "co_exceeds_24h_smac_100ppm": (co_ppm > co_24h) if co_ppm is not None else None,
            "co_exceeds_1h_smac_425ppm": (co_ppm > co_1h) if co_ppm is not None else None,
            "co2_exceeds_1h_limit_3mmhg": (co2_mmhg > co2_1h) if co2_mmhg is not None else None,
            "scope_caveat": "Comparison applies reported unmanned FFD Δgas increases against crew limit magnitudes; not a crew exposure ruling.",
        },
    }
    return rec


def load_saffire_case_dataset(repo_root: str | Path = ".") -> SaffireCaseDataset:
    """Load and validate the verified SAFFIRE IV–VI case reference JSON and build its BM25 index."""
    root = Path(repo_root)
    json_path = root / SAFFIRE_CASE_RELPATH
    if not json_path.is_file():
        raise SaffireCaseLoadError(f"Verified SAFFIRE case JSON not found: {json_path}")

    raw_bytes = json_path.read_bytes()
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SaffireCaseLoadError(f"Failed to parse {json_path}: {exc}") from exc

    if not isinstance(raw, dict) or not raw.get("condition_records") or not raw.get("passages"):
        raise SaffireCaseLoadError(f"Malformed structure in {json_path}")

    sources_by_id = {str(s["source_id"]): dict(s) for s in raw.get("verified_sources", ()) if isinstance(s, Mapping)}
    thresholds = raw.get("regulatory_reference_thresholds", {})

    records_by_id: dict[str, dict[str, Any]] = {}
    for item in raw.get("condition_records", ()):
        enriched = _enrich_record_with_derived(item, thresholds)
        records_by_id[str(enriched["test_id"])] = enriched

    if set(records_by_id.keys()) != set(VALID_TEST_IDS):
        raise SaffireCaseLoadError(
            f"Expected exact condition_records {sorted(VALID_TEST_IDS)}, found {sorted(records_by_id.keys())}"
        )

    detection_by_id: dict[str, dict[str, Any]] = {}
    for det in raw.get("detection_evidence", ()):
        d_copy = dict(det)
        if d_copy.get("evidence_id") == "DET-A":
            rm = d_copy.get("reported_metrics", {})
            delta_s = compute_vi3_threshold_delta_s(rm.get("ignition_time_s"), rm.get("alarm_threshold_time_s"))
            d_copy["derived_metrics"] = {
                "elapsed_ignition_to_threshold_s": {
                    "value": delta_s,
                    "unit": "s",
                    "status": "derived",
                    "formula": "alarm_threshold_time_s (981 s) - ignition_time_s (637 s)",
                }
            }
        detection_by_id[str(d_copy["evidence_id"])] = d_copy

    chunks: list[DocumentChunk] = []
    for ordinal, p in enumerate(raw.get("passages", ())):
        rel = str(p.get("source_relpath") or SAFFIRE_CASE_RELPATH)
        p_path = root / rel
        doc_sha = hashlib.sha256(p_path.read_bytes()).hexdigest() if p_path.is_file() else sha256
        chunks.append(
            DocumentChunk(
                chunk_id=str(p["chunk_id"]),
                chunk_ordinal=ordinal,
                document_id=str(p["document_id"]),
                investigation_id=SAFFIRE_CASE_ID,
                section_number=str(p.get("section_number") or ""),
                section_title=str(p["section_title"]),
                section_path=(str(p["section_title"]),),
                source_text=str(p["source_text"]),
                pdf_page_start=int(p["pdf_page_start"]) if p.get("pdf_page_start") is not None else None,
                pdf_page_end=int(p["pdf_page_end"]) if p.get("pdf_page_end") is not None else None,
                printed_page_start=str(p.get("printed_page_start")) if p.get("printed_page_start") is not None else None,
                printed_page_end=str(p.get("printed_page_end")) if p.get("printed_page_end") is not None else None,
                printed_pages=(str(p.get("printed_page_start")),) if p.get("printed_page_start") is not None else (),
                paragraph_index_start=None,
                paragraph_index_end=None,
                source_url=str(p["source_url"]),
                source_relpath=rel,
                source_sha256=doc_sha,
                extraction_warnings=(),
            )
        )

    bm25_index = build_bm25_index(chunks)
    return SaffireCaseDataset(
        raw=raw,
        source_relpath=SAFFIRE_CASE_RELPATH,
        source_sha256=sha256,
        chunks=tuple(chunks),
        bm25_index=bm25_index,
        sources_by_id=sources_by_id,
        records_by_id=records_by_id,
        detection_by_id=detection_by_id,
    )


def validate_case_filters(
    *,
    test_id: Any = None,
    flight: Any = None,
    fuel_group: Any = None,
) -> tuple[str | None, str | None, str | None]:
    """Validate optional SAFFIRE case filter fields strictly."""
    def _clean(val: Any, name: str) -> str | None:
        if val is None:
            return None
        if not isinstance(val, str):
            raise SaffireCaseValidationError(f"{name} must be null or a string.")
        s = val.strip()
        return s or None

    tid = _clean(test_id, "test_id")
    if tid is not None:
        norm_tid = tid.upper()
        if norm_tid not in VALID_TEST_IDS:
            raise SaffireCaseValidationError(f"Unknown test_id {tid!r}. Allowed: {VALID_TEST_IDS}")
        tid = norm_tid

    fl = _clean(flight, "flight")
    if fl is not None:
        matched = next((f for f in VALID_CASE_FLIGHTS if f.lower() == fl.lower()), None)
        if matched is None:
            raise SaffireCaseValidationError(f"Unknown flight {fl!r}. Allowed: {VALID_CASE_FLIGHTS}")
        fl = matched

    fg = _clean(fuel_group, "fuel_group")
    if fg is not None:
        norm_fg = fg.lower()
        if norm_fg not in VALID_FUEL_GROUPS:
            raise SaffireCaseValidationError(f"Unknown fuel_group {fg!r}. Allowed: {VALID_FUEL_GROUPS}")
        fg = norm_fg

    return tid, fl, fg


def _compute_case_summary(records: Sequence[Mapping[str, Any]], dataset: SaffireCaseDataset) -> dict[str, Any]:
    """Build deterministic aggregate metrics without coercing null V-3/V-4 rows to zero."""
    thin = [r for r in records if r.get("fuel_group") == "thin_textile" and r.get("gas_calorimetry_reported")]
    thick = [r for r in records if r.get("fuel_group") == "thick_pmma" and r.get("gas_calorimetry_reported")]
    unreported = [r["test_id"] for r in records if not r.get("gas_calorimetry_reported")]

    def _range(vals: list[float]) -> dict[str, Any]:
        if not vals:
            return {"count": 0, "min": None, "max": None}
        return {"count": len(vals), "min": min(vals), "max": max(vals)}

    tl_raw = dict(dataset.raw.get("vi3_timeline", {}))
    tl_raw["derived_elapsed_ignition_to_threshold_s"] = compute_vi3_threshold_delta_s(
        tl_raw.get("ignition_time_s"), tl_raw.get("alarm_threshold_time_s")
    )
    tl_raw["derived_formula"] = "981 s (1 mg/m3 threshold) - 637 s (ignition) = 344 s"

    return {
        "total_condition_records": len(records),
        "reported_gas_calorimetry_count": sum(1 for r in records if r.get("gas_calorimetry_reported")),
        "unreported_gas_calorimetry_test_ids": unreported,
        "thin_vs_thick_gas_summary": {
            "status": "derived_group_range",
            "thin_textile_co2_ppm": _range([float(r["co2_increase_ppm"]) for r in thin if r.get("co2_increase_ppm") is not None]),
            "thin_textile_co_ppm": _range([float(r["co_increase_ppm"]) for r in thin if r.get("co_increase_ppm") is not None]),
            "thick_pmma_reported_co2_ppm": _range([float(r["co2_increase_ppm"]) for r in thick if r.get("co2_increase_ppm") is not None]),
            "thick_pmma_reported_co_ppm": _range([float(r["co_increase_ppm"]) for r in thick if r.get("co_increase_ppm") is not None]),
        },
        "vi3_timeline": tl_raw,
    }


def build_saffire_case_schema(dataset: SaffireCaseDataset) -> dict[str, Any]:
    """Return case schema, metadata, provenance, boundaries, and available filters."""
    return {
        "case_id": dataset.raw.get("case_id"),
        "title": dataset.raw.get("title"),
        "subtitle": dataset.raw.get("subtitle"),
        "audit_date": dataset.raw.get("audit_date"),
        "source_relpath": dataset.source_relpath,
        "source_sha256": dataset.source_sha256,
        "available_test_ids": list(VALID_TEST_IDS),
        "available_flights": list(VALID_CASE_FLIGHTS),
        "available_fuel_groups": list(VALID_FUEL_GROUPS),
        "boundary_statements": list(dataset.raw.get("boundary_statements", ())),
        "what_this_does_not_establish": list(dataset.raw.get("what_this_does_not_establish", ())),
        "regulatory_reference_thresholds": dict(dataset.raw.get("regulatory_reference_thresholds", {})),
        "verified_sources": list(dataset.raw.get("verified_sources", ())),
        "unresolved_items": list(dataset.raw.get("unresolved_items", ())),
    }


def run_saffire_case_reference(
    dataset: SaffireCaseDataset,
    *,
    test_id: str | None = None,
    flight: str | None = None,
    fuel_group: str | None = None,
) -> dict[str, Any]:
    """Return filtered SAFFIRE IV–VI case records, VI-3 timeline, detection evidence, and boundaries."""
    tid, fl, fg = validate_case_filters(test_id=test_id, flight=flight, fuel_group=fuel_group)
    selected: list[dict[str, Any]] = []
    for key in VALID_TEST_IDS:
        rec = dataset.records_by_id[key]
        if tid is not None and rec["test_id"] != tid:
            continue
        if fl is not None and rec["flight"] != fl:
            continue
        if fg is not None and rec["fuel_group"] != fg:
            continue
        selected.append(rec)

    summary = _compute_case_summary(selected or [dataset.records_by_id[k] for k in VALID_TEST_IDS], dataset)
    from .coverage import assess_saffire_case_coverage

    result = {
        "status": "OK" if selected else "NO_EVIDENCE",
        "case_id": dataset.raw.get("case_id"),
        "title": dataset.raw.get("title"),
        "filters": {"test_id": tid, "flight": fl, "fuel_group": fg},
        "total_matching_records": len(selected),
        "records": selected,
        "summary": summary,
        "regulatory_reference_thresholds": dict(dataset.raw.get("regulatory_reference_thresholds", {})),
        "detection_evidence": [dataset.detection_by_id[k] for k in ("DET-A", "DET-B", "DET-C") if k in dataset.detection_by_id],
        "unresolved_items": list(dataset.raw.get("unresolved_items", ())),
        "boundary_statements": list(dataset.raw.get("boundary_statements", ())),
        "what_this_does_not_establish": list(dataset.raw.get("what_this_does_not_establish", ())),
        "verified_sources": list(dataset.raw.get("verified_sources", ())),
        "source_relpath": dataset.source_relpath,
        "source_sha256": dataset.source_sha256,
    }
    result["coverage"] = assess_saffire_case_coverage(result).to_dict()
    return result


def export_saffire_case(
    dataset: SaffireCaseDataset,
    *,
    fmt: str = "json",
    test_id: str | None = None,
    flight: str | None = None,
    fuel_group: str | None = None,
) -> dict[str, Any]:
    """Export filtered SAFFIRE IV–VI case data with provenance, derived tags, null preservation, and limits."""
    norm_fmt = str(fmt or "json").strip().lower()
    if norm_fmt not in {"json", "csv"}:
        raise SaffireCaseValidationError("Export format must be 'json' or 'csv'.")

    payload = run_saffire_case_reference(dataset, test_id=test_id, flight=flight, fuel_group=fuel_group)
    if norm_fmt == "json":
        content = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)
        return {
            "status": "OK",
            "format": "json",
            "filename": "genaius_saffire_case_reference.json",
            "record_count": payload["total_matching_records"],
            "content": content,
        }

    buf = io.StringIO()
    for stmt in payload["boundary_statements"]:
        buf.write(f"# BOUNDARY: {stmt}\n")
    buf.write(f"# SOURCE_SHA256: {dataset.source_sha256} ({dataset.source_relpath})\n")

    columns = [
        "test_id",
        "flight",
        "flight_date",
        "material",
        "fuel_group",
        "flow_direction",
        "initial_air_flow_cm_s",
        "ambient_pressure_kpa",
        "oxygen_mol_percent",
        "derived_po2_kpa",
        "free_volume_m3",
        "gas_calorimetry_reported",
        "burn_duration_s",
        "o2_peak_heat_release_w",
        "o2_total_heat_release_kj",
        "fuel_avg_heat_release_w",
        "fuel_total_heat_release_kj",
        "max_temp_sfu_outlet_c",
        "max_temp_ffd_c",
        "co2_increase_ppm",
        "co2_partial_pressure_increase_mmhg",
        "co_increase_ppm",
        "source_locators",
    ]
    writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for r in payload["records"]:
        row_out = {
            "test_id": r["test_id"],
            "flight": r["flight"],
            "flight_date": r["flight_date"],
            "material": r["material"],
            "fuel_group": r["fuel_group"],
            "flow_direction": r["flow_direction"],
            "initial_air_flow_cm_s": r["initial_air_flow_cm_s"],
            "ambient_pressure_kpa": r["ambient_pressure_kpa"],
            "oxygen_mol_percent": r["oxygen_mol_percent"],
            "derived_po2_kpa": r["derived"]["po2_kpa"]["value"],
            "free_volume_m3": r["free_volume_m3"],
            "gas_calorimetry_reported": r["gas_calorimetry_reported"],
            "burn_duration_s": "" if r["burn_duration_s"] is None else r["burn_duration_s"],
            "o2_peak_heat_release_w": "" if r["o2_peak_heat_release_w"] is None else r["o2_peak_heat_release_w"],
            "o2_total_heat_release_kj": "" if r["o2_total_heat_release_kj"] is None else r["o2_total_heat_release_kj"],
            "fuel_avg_heat_release_w": "" if r["fuel_avg_heat_release_w"] is None else r["fuel_avg_heat_release_w"],
            "fuel_total_heat_release_kj": "" if r["fuel_total_heat_release_kj"] is None else r["fuel_total_heat_release_kj"],
            "max_temp_sfu_outlet_c": "" if r["max_temp_sfu_outlet_c"] is None else r["max_temp_sfu_outlet_c"],
            "max_temp_ffd_c": "" if r["max_temp_ffd_c"] is None else r["max_temp_ffd_c"],
            "co2_increase_ppm": "" if r["co2_increase_ppm"] is None else r["co2_increase_ppm"],
            "co2_partial_pressure_increase_mmhg": (
                "" if r["co2_partial_pressure_increase_mmhg"] is None else r["co2_partial_pressure_increase_mmhg"]
            ),
            "co_increase_ppm": "" if r["co_increase_ppm"] is None else r["co_increase_ppm"],
            "source_locators": "; ".join(r.get("source_locators", ())),
        }
        writer.writerow(row_out)

    return {
        "status": "OK",
        "format": "csv",
        "filename": "genaius_saffire_case_reference.csv",
        "record_count": payload["total_matching_records"],
        "content": buf.getvalue(),
    }


def evaluate_case_abstention_gate(query: str | None) -> AbstentionDecision:
    """Enforce human crew-safety, certification, and partial-g boundaries on case-study queries."""
    if not query or not query.strip():
        return AbstentionDecision(abstained=False)

    folded = _fold_text(query)
    if _CASE_CREW_SAFETY_CERT_RE.search(query) or asks_safety_judgment(folded) or asks_crew_harm(folded):
        return AbstentionDecision(
            abstained=True,
            reason_code="CASE_HUMAN_SAFETY_OR_CERTIFICATION_BOUNDARY",
            explanation=(
                "The SAFFIRE IV–VI case study reports measured delta gas and heat-release values in an unmanned "
                "Cygnus spacecraft and compares them to published NASA-STD-3001 / JSC 20584 benchmark thresholds. "
                "It cannot certify human crew survival, safe breathing durations, or material safety rankings; "
                "no crew was aboard these tests. " + SOURCE_SCOPE_NOTE
            ),
            triggered_rule="CASE_SAFETY_BOUNDARY",
        )
    if asks_gravity_transfer(folded):
        return AbstentionDecision(
            abstained=True,
            reason_code="CASE_PARTIAL_GRAVITY_BOUNDARY",
            explanation=(
                "Per NTRS 20240002981 (p.6) and Fortenberry NTRS 20220009167 (slides 15–17), further work is "
                "required before extending microgravity Saffire/SAME results to Lunar (1/6g) or Martian (3/8g) habitats."
            ),
            triggered_rule="CASE_GRAVITY_BOUNDARY",
        )
    if _CASE_CROSS_POOL_RE.search(query):
        return AbstentionDecision(
            abstained=True,
            reason_code="CASE_ISOLATION_BOUNDARY",
            explanation=(
                "SAFFIRE IV–VI case data cannot be pooled into the 403 core PSI-25/PSI-69 dataset or PSI-99 SAFFIRE-II cards."
            ),
            triggered_rule="CASE_ISOLATION_BOUNDARY",
        )
    return AbstentionDecision(abstained=False)


_VI3_SIGNAL_TOKENS = ("vi-3", "344", "981", "637")
_RELATED_DETECTION_TOKENS = (
    "same",
    "fortenberry",
    "pm1",
    "aerosol",
    "particle",
    "clog",
    "ioniz",
    "photoelectric",
    "teflon",
    "kapton",
    "all detector",
    "equally",
    "equal",
)
_GENERAL_DETECTION_TOKENS = (
    "detect",
    "alarm",
    "smoke",
    "1 mg",
    "threshold",
    "timeline",
    "latency",
    "happened",
    "what did",
    "elapsed",
    *_VI3_SIGNAL_TOKENS,
    *_RELATED_DETECTION_TOKENS,
)


def _select_case_context_items(
    dataset: SaffireCaseDataset,
    query: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], set[str], bool]:
    """Select relevant condition rows, primary detection cards, and separated related research."""
    q_low = query.lower()
    explicit_ids = {m.group(1).upper() for m in _TEST_ID_RE.finditer(query)}
    if not explicit_ids and any(tok in q_low for tok in ("344", "981", "637")):
        explicit_ids = {"VI-3"}

    selected_records: list[dict[str, Any]] = []
    for tid in VALID_TEST_IDS:
        if explicit_ids and tid not in explicit_ids:
            continue
        selected_records.append(dataset.records_by_id[tid])

    if not explicit_ids and len(selected_records) > 7:
        selected_records = selected_records[:7]

    wants_related_det = any(tok in q_low for tok in _RELATED_DETECTION_TOKENS)
    wants_detection = any(tok in q_low for tok in _GENERAL_DETECTION_TOKENS)
    gas_only_vi3 = (
        explicit_ids == {"VI-3"}
        and any(tok in q_low for tok in ("gas", "co2", "co ", "oxygen", "smac", "calorimet", "heat"))
        and not any(tok in q_low for tok in ("344", "981", "637", "alarm", "smoke", "detect", "threshold", "timeline", "happened"))
    )

    selected_det: list[dict[str, Any]] = []
    related_research: list[dict[str, Any]] = []

    if explicit_ids and not wants_related_det:
        if "VI-3" in explicit_ids and not gas_only_vi3 and "DET-A" in dataset.detection_by_id:
            selected_det.append(dataset.detection_by_id["DET-A"])
        elif "VI-3" in explicit_ids and gas_only_vi3 and "DET-A" in dataset.detection_by_id:
            related_research.append(dataset.detection_by_id["DET-A"])
        for k in ("DET-B", "DET-C"):
            if k in dataset.detection_by_id:
                related_research.append(dataset.detection_by_id[k])
    elif wants_related_det:
        for k in ("DET-A", "DET-B", "DET-C"):
            if k in dataset.detection_by_id:
                selected_det.append(dataset.detection_by_id[k])
    elif wants_detection:
        if "DET-A" in dataset.detection_by_id:
            selected_det.append(dataset.detection_by_id["DET-A"])
        for k in ("DET-B", "DET-C"):
            if k in dataset.detection_by_id:
                related_research.append(dataset.detection_by_id[k])

    return selected_records, selected_det, related_research, explicit_ids, wants_related_det


def _primary_url_for_locators(dataset: SaffireCaseDataset, locators: Sequence[str]) -> str:
    text = " ".join(locators)
    if "NIST" in text:
        return dataset.sources_by_id.get("NIST-1335761", {}).get("url", "https://www.nist.gov/node/1335761")
    if "20220009167" in text:
        return "https://ntrs.nasa.gov/citations/20220009167"
    if "20240007488" in text and "20240002981" not in text:
        return "https://ntrs.nasa.gov/citations/20240007488"
    if "20210011521" in text and "20240002981" not in text:
        return "https://ntrs.nasa.gov/citations/20210011521"
    return "https://ntrs.nasa.gov/citations/20240002981"


def build_saffire_case_evidence_bundle(
    request: EvidenceRequest,
    *,
    dataset: SaffireCaseDataset,
) -> EvidenceBundle:
    """Execute case-scoped BM25 passage retrieval + Python-computed SAFFIRE IV–VI evidence bundle."""
    query_text = (request.query or "").strip()
    gate = evaluate_case_abstention_gate(query_text)
    if gate.abstained:
        from .coverage import assess_saffire_case_coverage

        return EvidenceBundle(
            request=request,
            mode=SAFFIRE_CASE_MODE,
            abstention=gate,
            resolved_investigation_id=SAFFIRE_CASE_ID,
            table_result=None,
            field_summary=None,
            comparison_result=None,
            document_result=None,
            citations=(),
            warnings=(gate.explanation,) if gate.explanation else (),
            disclaimers=(CASE_BOUNDARY_DISCLAIMER, COMPARISON_BOUNDARY_NOTE, BM25_SCORE_DISCLAIMER),
            case_payload=None,
            coverage=assess_saffire_case_coverage(
                {"records": [], "summary": {"total_condition_records": 7}},
                requested_query=query_text,
                abstention=gate,
            ),
        )

    effective_query = query_text or "Saffire VI-3 cabin gas detection timeline"
    records, det_cards, related_det_cards, explicit_ids, wants_related_det = _select_case_context_items(
        dataset, effective_query
    )
    req_top_k = min(max(request.top_k, 1), len(dataset.chunks))
    if explicit_ids and not wants_related_det:
        raw_doc = dataset.bm25_index.search(
            effective_query,
            top_k=len(dataset.chunks),
            investigation_id=None,
            use_bilingual_aliases=False,
        )
        q_low = effective_query.lower()
        wants_calorimetry = any(tok in q_low for tok in ("calorimet", "dual", "heat release", "hrr"))
        excluded_chunks: set[str] = {
            "SC-NIST-1335761-SAME",
            "SC-NTRS20220009167-FORTENBERRY",
            "SC-SAME2-20130000422",
        }
        if not explicit_ids & {"V-3", "V-4"}:
            excluded_chunks.add("SC-NTRS20210011521-V3-V4")
        if "VI-2" not in explicit_ids and not wants_calorimetry:
            excluded_chunks.add("SC-NTRS20240002981-P4-CAL")

        kept_hits = [h for h in raw_doc.hits if h.chunk_id not in excluded_chunks]

        def _hit_priority(hit: Any) -> tuple[int, float]:
            cid_low = str(getattr(hit, "chunk_id", "")).lower()
            title_low = str(getattr(hit, "section_title", "")).lower()
            direct_hit = any(tid.lower() in cid_low or tid.lower() in title_low for tid in explicit_ids)
            return (0 if direct_hit else 1, -float(getattr(hit, "score", 0.0)))

        kept_hits.sort(key=_hit_priority)
        kept_hits = kept_hits[:req_top_k]
        doc_result = SearchResult(
            query=raw_doc.query,
            investigation_id=raw_doc.investigation_id,
            top_k=req_top_k,
            total_hits_returned=len(kept_hits),
            hits=tuple(kept_hits),
            query_tokens=raw_doc.query_tokens,
            applied_query_expansions=raw_doc.applied_query_expansions,
            bilingual_scope_note=raw_doc.bilingual_scope_note,
            bm25_params=raw_doc.bm25_params,
        )
    else:
        doc_result = dataset.bm25_index.search(
            effective_query,
            top_k=req_top_k,
            investigation_id=None,
            use_bilingual_aliases=False,
        )
        # Fallback passage selection if a natural-language question only matched non-stemmed terms.
        if doc_result.total_hits_returned == 0:
            doc_result = dataset.bm25_index.search(
                "Saffire CO CO2 PMMA SIBAL detection",
                top_k=min(max(request.top_k, 3), len(dataset.chunks)),
                investigation_id=None,
                use_bilingual_aliases=False,
            )

    summary = _compute_case_summary(records, dataset)

    citations: list[CitationItem] = []
    seen_cits: set[str] = set()

    for rec in records:
        cid = f"CASE-TBL:{rec['test_id']}"
        if cid not in seen_cits:
            seen_cits.add(cid)
            loc = f"Saffire {rec['test_id']} ({rec['material']}) — {', '.join(rec.get('source_locators', ()))}"
            citations.append(
                CitationItem(
                    citation_id=cid,
                    source_type="case_record",
                    investigation_id=SAFFIRE_CASE_ID,
                    locator_label=loc,
                    source_relpath=dataset.source_relpath,
                    source_sha256=dataset.source_sha256,
                    record_pk=str(rec["test_id"]),
                    source_url=_primary_url_for_locators(dataset, rec.get("source_locators", ())),
                )
            )

    for det in det_cards:
        cid = f"CASE-DET:{det['evidence_id']}"
        if cid not in seen_cits:
            seen_cits.add(cid)
            loc = f"{det['evidence_id']}: {det['title']} ({'; '.join(det.get('locators', ()))})"
            citations.append(
                CitationItem(
                    citation_id=cid,
                    source_type="case_detection",
                    investigation_id=SAFFIRE_CASE_ID,
                    locator_label=loc,
                    source_relpath=dataset.source_relpath,
                    source_sha256=dataset.source_sha256,
                    record_pk=str(det["evidence_id"]),
                    source_url=_primary_url_for_locators(dataset, det.get("locators", ())),
                )
            )

    for hit in doc_result.hits:
        cid = f"DOC:{hit.chunk_id}"
        if cid not in seen_cits:
            seen_cits.add(cid)
            citations.append(
                CitationItem(
                    citation_id=cid,
                    source_type="document_chunk",
                    investigation_id=SAFFIRE_CASE_ID,
                    locator_label=f"{hit.document_id} § {hit.section_title} ({hit.printed_page_start or hit.pdf_page_start})",
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

    compact_records: list[dict[str, Any]] = []
    for rec in records:
        row_c: dict[str, Any] = {
            "test_id": rec["test_id"],
            "flight": rec["flight"],
            "material": rec["material"],
            "fuel_group": rec["fuel_group"],
            "flow_direction": rec["flow_direction"],
            "initial_air_flow_cm_s": rec["initial_air_flow_cm_s"],
            "ambient_pressure_kpa": rec["ambient_pressure_kpa"],
            "oxygen_mol_percent": rec["oxygen_mol_percent"],
            "derived_po2_kpa": rec["derived"]["po2_kpa"]["value"],
            "free_volume_m3": rec["free_volume_m3"],
            "gas_calorimetry_reported": rec["gas_calorimetry_reported"],
            "co2_increase_ppm": rec["co2_increase_ppm"],
            "co2_partial_pressure_increase_mmhg": rec["co2_partial_pressure_increase_mmhg"],
            "co_increase_ppm": rec["co_increase_ppm"],
        }
        for opt_k in (
            "burn_duration_s",
            "o2_peak_heat_release_w",
            "o2_total_heat_release_kj",
            "fuel_avg_heat_release_w",
            "fuel_total_heat_release_kj",
            "max_temp_sfu_outlet_c",
            "max_temp_ffd_c",
        ):
            if rec.get(opt_k) is not None:
                row_c[opt_k] = rec[opt_k]
        row_c["flow_steps"] = [
            f"{step.get('time_label', '')}: {step.get('flow_speed_cm_s')} cm/s"
            for step in rec.get("flow_protocol", ())
        ]
        if rec.get("gas_calorimetry_reported"):
            tc = rec["derived"]["threshold_comparisons"]
            row_c["limits_check"] = {
                "co_gt_24h_100ppm": tc["co_exceeds_24h_smac_100ppm"],
                "co_gt_1h_425ppm": tc["co_exceeds_1h_smac_425ppm"],
                "co2_gt_1h_3mmhg": tc["co2_exceeds_1h_limit_3mmhg"],
            }
        cal_note = rec.get("structured_notes", {}).get("calorimetry_method_note")
        if cal_note:
            row_c["calorimetry_note"] = cal_note
        compact_records.append(row_c)

    compact_detection = [
        {
            "evidence_id": d["evidence_id"],
            "title": d["title"],
            "summary": d["summary"],
            "limitations": d.get("limitations"),
            "derived_metrics": d.get("derived_metrics"),
            "locators": d.get("locators", ()),
        }
        for d in det_cards
    ]
    compact_related = [
        {
            "evidence_id": d["evidence_id"],
            "title": d["title"],
            "summary": d["summary"],
            "locators": d.get("locators", ()),
        }
        for d in related_det_cards
    ]
    tl_full = summary.get("vi3_timeline", {})
    vi3_timeline_compact = {
        "ignition_time_s": tl_full.get("ignition_time_s"),
        "alarm_threshold_mg_m3": tl_full.get("alarm_threshold_mg_m3"),
        "alarm_threshold_time_s": tl_full.get("alarm_threshold_time_s"),
        "derived_elapsed_ignition_to_threshold_s": tl_full.get("derived_elapsed_ignition_to_threshold_s"),
        "flow_reduced_time_s": tl_full.get("flow_reduced_time_s"),
        "flow_reduced_from_cm_s": tl_full.get("flow_reduced_from_cm_s"),
        "flow_reduced_to_cm_s": tl_full.get("flow_reduced_to_cm_s"),
        "flow_terminated_time_s": tl_full.get("flow_terminated_time_s"),
        "reported_burn_duration_s": tl_full.get("reported_burn_duration_s"),
    }
    if explicit_ids == {"VI-3"} and not wants_related_det:
        compact_summary = {
            "total_condition_records": summary["total_condition_records"],
            "vi3_timeline": vi3_timeline_compact,
        }
    else:
        compact_summary = {
            "total_condition_records": summary["total_condition_records"],
            "reported_gas_calorimetry_count": summary["reported_gas_calorimetry_count"],
            "unreported_gas_calorimetry_test_ids": summary["unreported_gas_calorimetry_test_ids"],
            "thin_vs_thick_gas_summary": summary["thin_vs_thick_gas_summary"],
            "vi3_timeline": vi3_timeline_compact,
        }
    compact_unresolved = [
        f"{u['id']}: {u['detail']}" for u in dataset.raw.get("unresolved_items", ())
    ]

    case_payload = {
        "case_id": dataset.raw.get("case_id"),
        "title": dataset.raw.get("title"),
        "records": compact_records,
        "summary": compact_summary,
        "detection_evidence": compact_detection,
        "related_research": compact_related,
        "regulatory_reference_thresholds": dict(dataset.raw.get("regulatory_reference_thresholds", {})),
        "unresolved_items": compact_unresolved,
        "what_this_does_not_establish": list(dataset.raw.get("what_this_does_not_establish", ())),
    }

    from .coverage import assess_saffire_case_coverage

    return EvidenceBundle(
        request=request,
        mode=SAFFIRE_CASE_MODE,
        abstention=AbstentionDecision(abstained=False),
        resolved_investigation_id=SAFFIRE_CASE_ID,
        table_result=None,
        field_summary=None,
        comparison_result=None,
        document_result=doc_result,
        citations=tuple(citations),
        warnings=(),
        disclaimers=(CASE_BOUNDARY_DISCLAIMER, COMPARISON_BOUNDARY_NOTE, BM25_SCORE_DISCLAIMER),
        case_payload=case_payload,
        coverage=assess_saffire_case_coverage(case_payload, requested_query=query_text),
    )


__all__ = [
    "CASE_BOUNDARY_DISCLAIMER",
    "SAFFIRE_CASE_ID",
    "SAFFIRE_CASE_MODE",
    "SAFFIRE_CASE_RELPATH",
    "SaffireCaseDataset",
    "SaffireCaseError",
    "SaffireCaseLoadError",
    "SaffireCaseValidationError",
    "VALID_CASE_FLIGHTS",
    "VALID_FUEL_GROUPS",
    "VALID_TEST_IDS",
    "build_saffire_case_evidence_bundle",
    "build_saffire_case_schema",
    "compute_po2_kpa",
    "compute_vi3_threshold_delta_s",
    "evaluate_case_abstention_gate",
    "export_saffire_case",
    "load_saffire_case_dataset",
    "run_saffire_case_reference",
    "validate_case_filters",
]
