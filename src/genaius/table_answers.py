"""Deterministic table answers for Auto/Core questions (no LLM; computed from table records).

Recognises a small set of question shapes and answers them from the typed PSI-25 / PSI-69
records using the existing query/analytics functions:

* extreme      — highest/lowest value of one contract field (all tied records listed);
* material_gas — per-material gas summary (initial, final and paired Δ kept separate, every
                 measurement status counted, NULL never treated as zero);
* group_compare— one material/shape at two or more initial-O₂ levels (full record lists);
* count        — number of runs for a material or study.

Every eligible record is used: there is no top_k, paging or citation cap in the arithmetic.
Anything not recognised returns ``None`` and the normal evidence/LLM pipeline continues.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

from .analytics import _classify_psi25_material, _compute_psi25_metric, _descriptive_stats, _measured_in_unit
from .data.contracts import ExperimentRecord, MeasurementStatus
from .data.query import summarize_field
from .service import _build_table_citation, _fold_text

ANSWER_MODE = "table_computed"
BADGE = "Computed from table records"
_SCOPE_NOTE = (
    "Computed in Python from the verified PSI-25/PSI-69 CSV rows listed under sources; no language model was used. "
    "A cited row shows where a number comes from; it does not establish causation, safety or applicability "
    "beyond the tested ISS microgravity conditions."
)

# ---------------------------------------------------------------- vocabulary
_MATERIALS = {
    "nomex": "Nomex",
    "pmma": "PMMA",
    "acrylic": "PMMA",
    "sibal": "SIBAL fabric",
    "wax": "Wax candle",
    "candle": "Wax candle",
}
_SHAPES = ("film", "slab", "rod", "sphere", "fabric", "candle")
_SOLID_CUES = re.compile(r"\b(?:solid|solids|material|materials|bass|psi[-\s]*25|sample|samples|fabric|film|rod|slab)\b")
_DROPLET_CUES = re.compile(r"\b(?:droplet|droplets|flex|psi[-\s]*69|liquid|heptane|methanol)\b")
_MAX_RE = re.compile(r"\b(?:highest|maximum|max|largest|greatest|en\s+yuksek|en\s+buyuk)\b")
_MIN_RE = re.compile(r"\b(?:lowest|minimum|min|smallest|least|en\s+dusuk|en\s+kucuk)\b")
_COMPARE_RE = re.compile(r"\b(?:compare|comparison|versus|vs|karsilastir\w*)\b")
_COUNT_RE = re.compile(r"\bhow\s+many\b|\bkac\s+(?:test|kosu|deney)\w*\b|\bnumber\s+of\s+(?:tests|runs)\b")
_GAS_RE = {
    "co": re.compile(r"\b(?:co|carbon\s+monoxide|karbon\s*monoksit)\b"),
    "co2": re.compile(r"\b(?:co2|carbon\s+dioxide|karbondioksit)\b"),
    "o2": re.compile(r"\b(?:o2|oxygen|oksijen)\b"),
}
_PCT_RE = re.compile(r"(\d{1,2}(?:[.,]\d+)?)\s*%")

# (study, field, unit, label) for "highest/lowest" questions; the study is chosen by explicit cues.
_EXTREME_FIELDS = {
    ("o2", "PSI-25"): ("initial_o2_vol_pct", "% vol", "initial (calibrated) O₂"),
    ("o2", "PSI-69"): ("initial_o2_flex_mol_pct", "% mol", "initial ambient O₂"),
    ("co", "PSI-25"): ("final_co_ppm", "ppm", "final CO"),
    ("co2", "PSI-25"): ("final_co2_vol_pct", "% vol", "final CO₂"),
}


def _material_of(folded: str) -> str | None:
    for key, family in _MATERIALS.items():
        if re.search(rf"\b{key}\b", folded):
            return family
    return None


def _shape_of(folded: str) -> str | None:
    for shape in _SHAPES:
        if re.search(rf"\b{shape}s?\b", folded):
            return shape
    return None


def _gas_of(folded: str) -> str | None:
    # CO2 must win over CO when both tokens could match.
    for gas in ("co2", "co", "o2"):
        if _GAS_RE[gas].search(folded):
            return gas
    return None


def _psi25(records: Sequence[ExperimentRecord]) -> list[ExperimentRecord]:
    return [r for r in records if r.investigation_id == "PSI-25"]


def _num(rec: ExperimentRecord, field: str) -> tuple[float | None, str]:
    m = rec.measurements.get(field)
    if m is None:
        return None, MeasurementStatus.MISSING.value
    if m.status != MeasurementStatus.MEASURED or m.parsed_value is None:
        return None, m.status.value
    return float(m.parsed_value), m.status.value


def _fmt(value: float | None, unit: str = "") -> str:
    if value is None:
        return "NULL"
    txt = f"{value:g}"
    return f"{txt} {unit}".strip()


def _sources(records: Sequence[ExperimentRecord]) -> list[dict[str, Any]]:
    out = []
    for rec in records:
        cit = _build_table_citation(rec)
        out.append({
            "citation_id": cit.citation_id, "source_type": cit.source_type, "investigation_id": cit.investigation_id,
            "locator_label": cit.locator_label, "source_relpath": cit.source_relpath,
            "source_sha256": cit.source_sha256, "record_pk": cit.record_pk,
            "csv_record_index": cit.csv_record_index, "physical_line_start": cit.physical_line_start,
            "physical_line_end": cit.physical_line_end, "chunk_id": None, "document_id": None,
            "section_title": None, "printed_page_start": None, "printed_page_end": None,
            "pdf_page_start": None, "pdf_page_end": None, "source_url": None,
        })
    return out


def _cits(records: Sequence[ExperimentRecord]) -> list[str]:
    return [f"TBL:{r.record_pk}" for r in records]


def _answer(intent: str, summary: str, findings: list[dict[str, Any]], used: Sequence[ExperimentRecord],
            table: dict[str, Any], limitations: list[str], total_corpus: int) -> dict[str, Any]:
    ids = _cits(used)
    return {
        "status": "OK",
        "answer_mode": ANSWER_MODE,
        "answer_badge": BADGE,
        "llm_used": False,
        "llm_calls": 0,
        "table_intent": intent,
        "resolved_investigation_id": table.get("investigation_id"),
        "summary": summary,
        "findings": findings,
        "limitations": limitations + [_SCOPE_NOTE],
        "warnings": [],
        "disclaimers": [],
        "sources": _sources(used),
        "citation_ids": ids,
        "computed_table": table,
        "abstention": {"abstained": False, "reason_code": None, "explanation": None},
        "evidence_overview": {"table_total_runs": len(used), "table_shown_runs": len(used),
                              "document_hit_count": 0, "citation_count": len(ids)},
        "coverage": {
            "status": "matching", "ui_label": "COMPUTED FROM TABLE RECORDS", "scope": "core_table_answer",
            "corpus_id": f"{table.get('investigation_id') or 'PSI-25 + PSI-69'} Tabular",
            "corpus_version": "PSI-25_v1+PSI-69_v1", "requested_conditions": table.get("conditions", {}),
            "applied_filters": table.get("conditions", {}), "matching_record_ids": [r.record_pk for r in used],
            "matching_count": len(used), "total_corpus_count": total_corpus,
            "differing_or_missing_conditions": [],
            "tolerance_policy": {"mode": "exact_contract", "applied_tolerance": "Contract fields and units only.",
                                 "rationale": "All eligible records are evaluated; no top_k or citation cap.",
                                 "is_advisory_only": False},
            "limitations": [],
        },
        "numerical_audit": {"checked": False, "status": "not_applicable",
                            "reason": "Values are computed directly from table records; no generated text to audit.",
                            "violation_count": 0, "checked_claim_count": 0},
        "failure_reason": "NONE",
    }


# ---------------------------------------------------------------- intents
def _extreme(folded: str, records: Sequence[ExperimentRecord]) -> dict[str, Any] | None:
    want_max, want_min = bool(_MAX_RE.search(folded)), bool(_MIN_RE.search(folded))
    gas = _gas_of(folded)
    if want_max == want_min or gas is None:
        return None
    solid, droplet = bool(_SOLID_CUES.search(folded)), bool(_DROPLET_CUES.search(folded))
    if solid == droplet:  # ambiguous or both: never pool studies — let the normal pipeline clarify
        return None
    study = "PSI-25" if solid else "PSI-69"
    spec = _EXTREME_FIELDS.get((gas, study))
    if spec is None:
        return None
    field, unit, label = spec
    if "final" in folded and gas == "o2" and study == "PSI-25":
        field, label = "final_o2_vol_pct", "final (end-of-test) O₂"
    summ = summarize_field(records, investigation_id=study, field_name=field, unit=unit)
    target = summ.max_value if want_max else summ.min_value
    if target is None:
        return None
    used = set(summ.used_record_pks)
    pool = [r for r in records if r.record_pk in used]
    hits = [r for r in pool if (v := _measured_in_unit(r, field, unit)) is not None and abs(v - target) < 1e-9]
    word = "highest" if want_max else "lowest"
    study_name = "BASS-II (PSI-25, solid samples)" if study == "PSI-25" else "FLEX (PSI-69, droplets)"
    excluded = {k: v for k, v in summ.excluded_by_status.items() if v}
    rows = [{"test_id": r.test_id, "record_pk": r.record_pk, "material_as_recorded": r.normalized_fields.get("fuel_norm"),
             "value": _measured_in_unit(r, field, unit), "unit": unit} for r in hits]
    summary = (f"The {word} {label} recorded in {study_name} is {_fmt(target, unit)}, "
               f"reached in {len(hits)} of {summ.used_total_count} runs with a measured value.")
    findings = [{"text": "Runs at this value: " + ", ".join(f"{r.test_id} ({r.normalized_fields.get('fuel_norm')})" for r in hits),
                 "citation_ids": _cits(hits)}]
    if excluded:
        findings.append({"text": "Not included because the value is not a usable measurement: "
                         + ", ".join(f"{k}={v}" for k, v in sorted(excluded.items())), "citation_ids": []})
    lims = [f"This is the {label} field only; "
            + ("final (end-of-test) O₂ is a separate column and is not a tested condition."
               if field == "initial_o2_vol_pct" else "other columns are reported separately.")]
    table = {"investigation_id": study, "field": field, "unit": unit, "extreme": word, "value": target,
             "measured_runs": summ.used_total_count, "excluded_by_status": excluded, "rows": rows,
             "conditions": {"investigation_id": study, "field": field}}
    return _answer("extreme", summary, findings, hits, table, lims, len(records))


def _material_gas(folded: str, records: Sequence[ExperimentRecord]) -> dict[str, Any] | None:
    family, gas = _material_of(folded), _gas_of(folded)
    if family is None or gas is None or _COMPARE_RE.search(folded) or _PCT_RE.search(folded):
        return None
    init_f, final_f, unit = {
        "co": ("initial_co_ppm", "final_co_ppm", "ppm"),
        "co2": ("initial_co2_vol_pct", "final_co2_vol_pct", "% vol"),
        "o2": ("initial_o2_vol_pct", "final_o2_vol_pct", "% vol"),
    }[gas]
    metric = {"co": "delta_co_ppm", "co2": "delta_co2_vol_pct", "o2": "delta_o2_vol_pct"}[gas]
    runs = [r for r in _psi25(records) if _classify_psi25_material(r.normalized_fields["fuel_norm"])[0] == family]
    if not runs:
        return None
    rows, init_st, final_st, delta_st, deltas = [], Counter(), Counter(), Counter(), []
    for r in runs:
        iv, ist = _num(r, init_f)
        fv, fst = _num(r, final_f)
        dv, dst = _compute_psi25_metric(r, metric)
        init_st[ist] += 1
        final_st[fst] += 1
        delta_st["measured" if dv is not None else dst.replace("paired_excluded_", "")] += 1
        if dv is not None:
            deltas.append(dv)
        rows.append({"test_id": r.test_id, "record_pk": r.record_pk, "material_as_recorded": r.normalized_fields["fuel_norm"],
                     "initial_o2_vol_pct": _num(r, "initial_o2_vol_pct")[0], f"initial_{gas}": iv, f"initial_{gas}_status": ist,
                     f"final_{gas}": fv, f"final_{gas}_status": fst, f"delta_{gas}": dv, f"delta_{gas}_status": dst, "unit": unit})

    def counts(c: Counter) -> str:
        order = ("measured", "missing", "invalid", "above_limit", "below_limit", "approximate", "meaning_unverified")
        names = {"above_limit": "over-range", "below_limit": "under-range"}
        return ", ".join(f"{names.get(k, k)} {c.get(k, 0)}" for k in order if c.get(k, 0) or k in ("measured", "missing", "invalid", "above_limit"))

    gas_label = {"co": "CO", "co2": "CO₂", "o2": "O₂"}[gas]
    st = _descriptive_stats(deltas)
    summary = (f"{family}: {len(runs)} BASS-II runs. Final {gas_label} — {counts(final_st)}. "
               f"Paired Δ{gas_label} (final − initial, both measured) is available for {len(deltas)} run(s)"
               + (f", range {_fmt(st['min'], unit)} to {_fmt(st['max'], unit)}." if deltas else "."))
    per_run = "; ".join(
        f"{row['test_id']} (initial O₂ {_fmt(row['initial_o2_vol_pct'], '% vol')}): initial {_fmt(row[f'initial_{gas}'], unit)} ({row[f'initial_{gas}_status']}), "
        f"final {_fmt(row[f'final_{gas}'], unit)} ({row[f'final_{gas}_status']}), "
        f"Δ {_fmt(row[f'delta_{gas}'], unit)}" for row in rows)
    findings = [
        {"text": f"Per run: {per_run}.", "citation_ids": _cits(runs)},
        {"text": f"Initial {gas_label} statuses — {counts(init_st)}. Δ{gas_label} statuses — {counts(delta_st)}.",
         "citation_ids": _cits(runs)},
    ]
    lims = [
        f"Final {gas_label} ({unit}) is the end-of-test concentration in the test chamber, Δ{gas_label} is final minus "
        "initial, and neither is a produced gas mass: chamber volume and ventilation are not in this table, so mass is not computed.",
        "Runs differ in initial O₂ and flow settings; these values are not a material ranking or toxicity measure.",
    ]
    if gas == "co":
        lims.append("CO readings above the analyser range are flagged over-range and never replaced by a number.")
    table = {"investigation_id": "PSI-25", "material_family": family, "gas": gas, "unit": unit, "runs": len(runs),
             "initial_status_counts": dict(init_st), "final_status_counts": dict(final_st),
             "delta_status_counts": dict(delta_st), "delta_stats": st, "rows": rows,
             "conditions": {"investigation_id": "PSI-25", "material_family": family}}
    return _answer("material_gas", summary, findings, runs, table, lims, len(records))


def _group_compare(folded: str, records: Sequence[ExperimentRecord]) -> dict[str, Any] | None:
    family = _material_of(folded)
    levels = sorted({float(m.replace(",", ".")) for m in _PCT_RE.findall(folded)})
    if family is None or len(levels) < 2 or not (_COMPARE_RE.search(folded) or " and " in folded):
        return None
    if not _GAS_RE["o2"].search(folded) and "%" not in folded:
        return None
    shape = _shape_of(folded)
    pool = []
    for r in _psi25(records):
        fam, shp = _classify_psi25_material(r.normalized_fields["fuel_norm"])
        if fam == family and (shape is None or shp == shape):
            pool.append(r)
    groups, used = [], []
    for level in levels:
        members = [r for r in pool if (v := _num(r, "initial_o2_vol_pct")[0]) is not None and abs(v - level) < 0.05]
        used.extend(members)
        dco = [d for r in members if (d := _compute_psi25_metric(r, "delta_co_ppm")[0]) is not None]
        do2 = [d for r in members if (d := _compute_psi25_metric(r, "delta_o2_vol_pct")[0]) is not None]
        groups.append({
            "initial_o2_vol_pct": level,
            "runs": len(members),
            "records": [{"test_id": r.test_id, "record_pk": r.record_pk,
                         "material_as_recorded": r.normalized_fields["fuel_norm"],
                         "final_co_ppm": _num(r, "final_co_ppm")[0], "final_co_status": _num(r, "final_co_ppm")[1],
                         "delta_co_ppm": _compute_psi25_metric(r, "delta_co_ppm")[0]} for r in members],
            "delta_co_ppm": _descriptive_stats(dco), "delta_co_measured_runs": len(dco),
            "delta_o2_vol_pct": _descriptive_stats(do2), "delta_o2_measured_runs": len(do2),
        })
    if not used:
        return None
    label = f"{family} {shape}" if shape else family
    parts = []
    findings = []
    for g in groups:
        ids = ", ".join(f"{x['test_id']} ({x['material_as_recorded']})" for x in g["records"]) or "none"
        parts.append(f"{_fmt(g['initial_o2_vol_pct'], '%')} O₂: {g['runs']} run(s)")
        dc = g["delta_co_ppm"]
        findings.append({
            "text": (f"{_fmt(g['initial_o2_vol_pct'], '% vol')} initial O₂ — {g['runs']} run(s): {ids}. "
                     f"ΔCO measured in {g['delta_co_measured_runs']} of {g['runs']} run(s)"
                     + (f": median {_fmt(dc['median'], 'ppm')}, range {_fmt(dc['min'], 'ppm')}–{_fmt(dc['max'], 'ppm')}." if dc["count"] else ".")),
            "citation_ids": _cits([r for r in used if r.record_pk in {x['record_pk'] for x in g['records']}]),
        })
    summary = (f"{label} in BASS-II (PSI-25) at the requested initial O₂ levels — " + "; ".join(parts)
               + ". Every matching run is listed with its geometry as recorded; widths and thicknesses differ between runs.")
    lims = ["Grouping uses the calibrated initial O₂ column (±0.05 % vol); final O₂ is not used as a test condition.",
            "Runs within a group differ in film thickness/width and flow setting, so group differences are descriptive, "
            "not a controlled effect of O₂."]
    table = {"investigation_id": "PSI-25", "material_family": family, "shape": shape, "levels": levels,
             "groups": groups, "conditions": {"investigation_id": "PSI-25", "material_family": family,
                                              "shape": shape, "initial_o2_vol_pct": levels}}
    return _answer("group_compare", summary, findings, used, table, lims, len(records))


def _count(folded: str, records: Sequence[ExperimentRecord]) -> dict[str, Any] | None:
    if not _COUNT_RE.search(folded):
        return None
    family = _material_of(folded)
    if family is None:
        return None
    runs = [r for r in _psi25(records) if _classify_psi25_material(r.normalized_fields["fuel_norm"])[0] == family]
    shapes = Counter(_classify_psi25_material(r.normalized_fields["fuel_norm"])[1] for r in runs)
    summary = f"BASS-II (PSI-25) contains {len(runs)} {family} run(s)" + (
        " (" + ", ".join(f"{k} {v}" for k, v in sorted(shapes.items())) + ")." if runs else ".")
    findings = [{"text": "Runs: " + ", ".join(r.test_id for r in runs), "citation_ids": _cits(runs)}] if runs else []
    table = {"investigation_id": "PSI-25", "material_family": family, "runs": len(runs), "by_shape": dict(shapes),
             "conditions": {"investigation_id": "PSI-25", "material_family": family}}
    return _answer("count", summary, findings, runs, table, [], len(records)) if runs else None


_INTENTS = (_group_compare, _extreme, _material_gas, _count)


def try_table_answer(query: str | None, records: Sequence[ExperimentRecord]) -> dict[str, Any] | None:
    """Return a deterministic table answer dict, or ``None`` when the question is not a table question."""
    if not query or not query.strip():
        return None
    folded = _fold_text(query)
    for intent in _INTENTS:
        result = intent(folded, records)
        if result is not None:
            return result
    return None
