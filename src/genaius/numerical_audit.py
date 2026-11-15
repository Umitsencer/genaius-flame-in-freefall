"""Deterministic numerical & unit provenance audit for LLM-generated answers.

Extracts structured ``EvidenceFact`` entries from an ``EvidenceBundle`` and
audits every number in LLM ``summary`` and ``findings`` before output release.

Rules:
- Zero arbitrary global percentage tolerances: matching uses source/display
  precision (``0.5 * 10^(-d)`` for ``d >= 1`` decimals, exact integer equality
  when ``d == 0`` unless an explicit rounding relation applies to a value >= 10).
- Explicit unit verification (never allows ``760 atm`` or ``1 mmHg`` swaps).
- Test / record attribution verification (single-test claims must match that test).
- Context guards: ``initial`` vs ``final`` diameter swap, wrong fraction
  denominators, coercion of unreported runs (e.g. SAFFIRE ``V-3``/``V-4``) to
  ``0``, conflating post-fire ``Delta CO2`` with crew exposure dose, or
  presenting ``MODEL:*`` estimates as NASA experimental measurements.
- On failure, never silently edits LLM prose; raises ``NumericalAuditError`` so
  the caller falls back cleanly to the deterministic template with
  ``failure_reason = "NUMERICAL_VALIDATION_FAILED"``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

FAILURE_NONE = "NONE"
FAILURE_NUMERICAL_VALIDATION = "NUMERICAL_VALIDATION_FAILED"
FAILURE_LLM_QUOTA = "LLM_QUOTA_EXCEEDED"
FAILURE_OUTPUT_VALIDATION = "OUTPUT_VALIDATION_FAILED"
FAILURE_LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
FAILURE_INPUT_BUDGET = "INPUT_BUDGET_EXCEEDED"

NUMERICAL_AUDIT_DISCLAIMER = (
    "Numerical consistency was deterministically checked against structured bundle facts and cited passages; "
    "this verifies cited numbers, units, and documented guardrails, not full semantic truth of prose."
)


class NumericalAuditError(ValueError):
    """Raised when LLM summary or findings fail deterministic numerical verification."""

    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(self.issues[:5]))


@dataclass(frozen=True)
class EvidenceFact:
    """Single atomic numerical fact extracted deterministically from an EvidenceBundle."""

    fact_id: str
    value: float
    unit: str
    field_name: str
    physical_meaning: str
    origin_type: str  # "reported" | "derived" | "model_prediction"
    time_context: str
    citation_ids: tuple[str, ...]
    test_id: str | None = None
    record_pk: str | None = None
    formula_and_inputs: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "value": self.value,
            "unit": self.unit,
            "field_name": self.field_name,
            "physical_meaning": self.physical_meaning,
            "origin_type": self.origin_type,
            "time_context": self.time_context,
            "citation_ids": list(self.citation_ids),
            "test_id": self.test_id,
            "record_pk": self.record_pk,
            "formula_and_inputs": self.formula_and_inputs,
        }


@dataclass(frozen=True)
class NumericalAuditReport:
    """Typed audit metadata attached to GroundedAnswer and /api/answer responses."""

    status: str  # "passed" | "failed_fallback" | "not_applicable_deterministic"
    audited_fields: tuple[str, ...]
    checked_facts_count: int
    matched_fact_ids: tuple[str, ...]
    issues: tuple[str, ...]
    disclaimer: str = NUMERICAL_AUDIT_DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "audited_fields": list(self.audited_fields),
            "checked_facts_count": self.checked_facts_count,
            "matched_fact_ids": list(self.matched_fact_ids),
            "issues": list(self.issues),
            "disclaimer": self.disclaimer,
        }


_CANONICAL_UNIT_ALIASES: dict[str, str] = {
    "mmhg": "mmHg",
    "torr": "mmHg",
    "atm": "atm",
    "kpa": "kPa",
    "pa": "Pa",
    "psi": "psi",
    "ppm": "ppm",
    "mm2/s": "mm^2/s",
    "mm^2/s": "mm^2/s",
    "mm²/s": "mm^2/s",
    "mm/s2": "mm^2/s",
    "mm": "mm",
    "cm/s": "cm/s",
    "m/s": "m/s",
    "m3": "m^3",
    "m^3": "m^3",
    "m³": "m^3",
    "mg/m3": "mg/m^3",
    "mg/m^3": "mg/m^3",
    "mg/m³": "mg/m^3",
    "s": "s",
    "sec": "s",
    "secs": "s",
    "seconds": "s",
    "second": "s",
    "min": "min",
    "mins": "min",
    "w": "W",
    "kw": "kW",
    "kj": "kJ",
    "c": "C",
    "°c": "C",
    "degc": "C",
    "%": "%",
    "pct": "%",
    "percent": "%",
    "% mol": "% mol",
    "%mol": "% mol",
    "mol%": "% mol",
    "mol %": "% mol",
    "% vol": "% vol",
    "%vol": "% vol",
    "vol%": "% vol",
    "vol %": "% vol",
    "mol_frac": "mol_frac",
    "vol_frac": "vol_frac",
    "std": "std",
    "mmsqsec": "mm^2/s",
    "unitmassconc": "mg/m^3",
    "unitvol": "m^3",
}


def _canonical_unit(unit: str | None) -> str:
    if not unit:
        return ""
    u = unit.strip()
    low = u.lower().replace("²", "^2").replace("³", "^3")
    return _CANONICAL_UNIT_ALIASES.get(low, u)


def _infer_field_time_context(field_name: str) -> str:
    f = field_name.lower()
    if "initial" in f or f in {"d0_mm", "droplet_initial_diameter_mm"}:
        return "initial"
    if "extinction" in f or "final" in f or f in {"visible_flame_extinction_diameter_mm"}:
        return "final"
    if "burning_rate" in f:
        return "burning_rate"
    if "burn_time" in f or "burn_duration" in f:
        return "duration"
    if "ignition_time" in f:
        return "ignition"
    if "alarm_threshold_time" in f:
        return "threshold"
    if "elapsed" in f:
        return "elapsed_delta"
    if "increase" in f or "delta" in f:
        return "delta_post_fire"
    return "ambient_or_measured"


def _add_fact(
    facts: list[EvidenceFact],
    seen: set[tuple[str, float, str, str | None]],
    *,
    fact_id: str,
    value: Any,
    unit: str,
    field_name: str,
    physical_meaning: str,
    origin_type: str,
    time_context: str,
    citation_ids: Sequence[str],
    test_id: str | None = None,
    record_pk: str | None = None,
    formula_and_inputs: str | None = None,
) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return
    num = float(value)
    if not math.isfinite(num):
        return
    c_unit = _canonical_unit(unit)
    dedupe_key = (field_name, round(num, 8), c_unit, record_pk or test_id)
    if dedupe_key in seen:
        return
    seen.add(dedupe_key)
    facts.append(
        EvidenceFact(
            fact_id=fact_id,
            value=num,
            unit=c_unit,
            field_name=field_name,
            physical_meaning=physical_meaning,
            origin_type=origin_type,
            time_context=time_context,
            citation_ids=tuple(citation_ids),
            test_id=test_id,
            record_pk=record_pk,
            formula_and_inputs=formula_and_inputs,
        )
    )


def _extract_measurement_facts(
    facts: list[EvidenceFact],
    seen: set[tuple[str, float, str, str | None]],
    *,
    test_id: str | None,
    record_pk: str,
    field_name: str,
    m_obj: Any,
    cit_id: str,
) -> None:
    if isinstance(m_obj, Mapping):
        status = str(m_obj.get("status") or "")
        parsed = m_obj.get("parsed_value")
        s_unit = str(m_obj.get("source_unit") or "")
        norm = m_obj.get("normalized_value")
        n_unit = str(m_obj.get("normalized_unit") or "")
        extras = m_obj.get("extra_conversions") or {}
    else:
        status_enum = getattr(m_obj, "status", None)
        status = getattr(status_enum, "value", str(status_enum or ""))
        parsed = getattr(m_obj, "parsed_value", None)
        s_unit = str(getattr(m_obj, "source_unit", "") or "")
        norm = getattr(m_obj, "normalized_value", None)
        n_unit = str(getattr(m_obj, "normalized_unit", "") or "")
        extras = getattr(m_obj, "extra_conversions", None) or {}

    if status not in {"measured", "approximate"}:
        return

    t_ctx = _infer_field_time_context(field_name)
    origin = "reported"
    if parsed is not None:
        _add_fact(
            facts,
            seen,
            fact_id=f"{record_pk}:{field_name}:{_canonical_unit(s_unit)}",
            value=parsed,
            unit=s_unit,
            field_name=field_name,
            physical_meaning=f"{field_name} ({status})",
            origin_type=origin,
            time_context=t_ctx,
            citation_ids=(cit_id,),
            test_id=test_id,
            record_pk=record_pk,
        )
    if norm is not None:
        _add_fact(
            facts,
            seen,
            fact_id=f"{record_pk}:{field_name}:{_canonical_unit(n_unit)}",
            value=norm,
            unit=n_unit,
            field_name=field_name,
            physical_meaning=f"{field_name} normalized ({status})",
            origin_type=origin,
            time_context=t_ctx,
            citation_ids=(cit_id,),
            test_id=test_id,
            record_pk=record_pk,
        )
        if n_unit in {"mol_frac", "vol_frac"} and isinstance(norm, (int, float)):
            pct_unit = "% mol" if n_unit == "mol_frac" else "% vol"
            _add_fact(
                facts,
                seen,
                fact_id=f"{record_pk}:{field_name}:pct",
                value=float(norm) * 100.0,
                unit=pct_unit,
                field_name=field_name,
                physical_meaning=f"{field_name} percent ({pct_unit})",
                origin_type="derived",
                time_context=t_ctx,
                citation_ids=(cit_id,),
                test_id=test_id,
                record_pk=record_pk,
                formula_and_inputs=f"{field_name} * 100",
            )
    if isinstance(extras, Mapping):
        for ex_unit, payload in extras.items():
            if isinstance(payload, Mapping) and payload.get("value") is not None:
                _add_fact(
                    facts,
                    seen,
                    fact_id=f"{record_pk}:{field_name}:{_canonical_unit(str(ex_unit))}",
                    value=payload["value"],
                    unit=str(ex_unit),
                    field_name=field_name,
                    physical_meaning=f"{field_name} converted to {ex_unit}",
                    origin_type="derived",
                    time_context=t_ctx,
                    citation_ids=(cit_id,),
                    test_id=test_id,
                    record_pk=record_pk,
                    formula_and_inputs=f"unit conversion from {s_unit}",
                )


def extract_bundle_facts(bundle: Any) -> tuple[tuple[EvidenceFact, ...], dict[str, Any]]:
    """Deterministically extract all verifiable facts + metadata sets from an EvidenceBundle."""
    facts: list[EvidenceFact] = []
    seen: set[tuple[str, float, str, str | None]] = set()
    unreported_gas_tests: set[str] = set()
    all_test_ids: set[str] = set()
    doc_numbers: set[float] = set()

    req = getattr(bundle, "request", None)
    for idx, nf in enumerate(getattr(req, "numeric_filters", ()) or ()):
        f_name = str(getattr(nf, "field_name", "") or "filter")
        f_unit = str(getattr(nf, "unit", "") or "")
        for bound_key in ("min_value", "max_value"):
            b_val = getattr(nf, bound_key, None)
            if b_val is not None:
                _add_fact(
                    facts,
                    seen,
                    fact_id=f"filter:{idx}:{f_name}:{bound_key}",
                    value=b_val,
                    unit=f_unit,
                    field_name=f_name,
                    physical_meaning=f"Applied query filter {f_name} {bound_key}",
                    origin_type="reported",
                    time_context="ambient_or_measured",
                    citation_ids=(),
                )

    table_res = getattr(bundle, "table_result", None)
    if table_res is not None:
        total_runs = getattr(table_res, "total_runs", None)
        _add_fact(
            facts,
            seen,
            fact_id="table:total_runs",
            value=total_runs,
            unit="count",
            field_name="total_runs",
            physical_meaning="Filtered table record count",
            origin_type="derived",
            time_context="count",
            citation_ids=(),
        )
        for key in ("unique_sample_count", "unique_flex_identifier_count"):
            _add_fact(
                facts,
                seen,
                fact_id=f"table:{key}",
                value=getattr(table_res, key, None),
                unit="count",
                field_name=key,
                physical_meaning=key,
                origin_type="derived",
                time_context="count",
                citation_ids=(),
            )
        for inv_k, inv_v in (getattr(table_res, "counts_by_investigation", None) or {}).items():
            _add_fact(
                facts,
                seen,
                fact_id=f"table:count:{inv_k}",
                value=inv_v,
                unit="count",
                field_name=f"count_{inv_k}",
                physical_meaning=f"Run count for {inv_k}",
                origin_type="derived",
                time_context="count",
                citation_ids=(),
            )
        for rec in getattr(table_res, "records", ()) or ():
            pk = str(getattr(rec, "record_pk", ""))
            tid = str(getattr(rec, "test_id", "") or pk)
            if tid:
                all_test_ids.add(tid)
            if pk:
                all_test_ids.add(pk)
            cit = f"TBL:{pk}"
            for fname, m_obj in (getattr(rec, "measurements", None) or {}).items():
                _extract_measurement_facts(
                    facts,
                    seen,
                    test_id=tid,
                    record_pk=pk,
                    field_name=str(fname),
                    m_obj=m_obj,
                    cit_id=cit,
                )

    comp_res = getattr(bundle, "comparison_result", None)
    if comp_res is not None:
        for row in getattr(comp_res, "rows", ()) or ():
            if not isinstance(row, Mapping):
                continue
            pk = str(row.get("record_pk") or "")
            tid = str(row.get("test_id") or pk)
            if tid:
                all_test_ids.add(tid)
            if pk:
                all_test_ids.add(pk)
            cit = f"TBL:{pk}"
            for fname, m_obj in (row.get("measurements") or {}).items():
                _extract_measurement_facts(
                    facts,
                    seen,
                    test_id=tid,
                    record_pk=pk,
                    field_name=str(fname),
                    m_obj=m_obj,
                    cit_id=cit,
                )

    f_sum = getattr(bundle, "field_summary", None)
    if f_sum is not None:
        sum_pks = tuple(getattr(f_sum, "used_record_pks", ()) or ())
        sum_cits = tuple(f"TBL:{pk}" for pk in sum_pks[:10])
        sum_unit = str(getattr(f_sum, "unit", "") or "")
        sum_field = str(getattr(f_sum, "field_name", "") or "summary")
        for attr, mean_str, unit_ov in (
            ("candidate_run_count", "Candidate run count", "count"),
            ("used_measured_count", "Measured values included in summary", "count"),
            ("used_approximate_count", "Approximate values included in summary", "count"),
            ("used_total_count", "Total values used in summary", "count"),
            ("mean_value", f"Mean of {sum_field}", sum_unit),
            ("min_value", f"Minimum of {sum_field}", sum_unit),
            ("max_value", f"Maximum of {sum_field}", sum_unit),
        ):
            _add_fact(
                facts,
                seen,
                fact_id=f"summary:{sum_field}:{attr}",
                value=getattr(f_sum, attr, None),
                unit=unit_ov,
                field_name=f"{sum_field}_{attr}",
                physical_meaning=mean_str,
                origin_type="derived",
                time_context="summary_stat" if unit_ov != "count" else "count",
                citation_ids=sum_cits,
            )
        for ex_k, ex_v in (getattr(f_sum, "excluded_by_status", None) or {}).items():
            _add_fact(
                facts,
                seen,
                fact_id=f"summary:excluded:{ex_k}",
                value=ex_v,
                unit="count",
                field_name=f"excluded_{ex_k}",
                physical_meaning=f"Excluded {ex_k} count",
                origin_type="derived",
                time_context="count",
                citation_ids=(),
            )

    # SAFFIRE IV-VI case payload
    case_payload = getattr(bundle, "case_payload", None)
    if isinstance(case_payload, Mapping):
        for rec in case_payload.get("records") or ():
            if not isinstance(rec, Mapping):
                continue
            tid = str(rec.get("test_id") or "")
            if tid:
                all_test_ids.add(tid)
            cit = f"CASE-TBL:{tid}"
            if rec.get("gas_calorimetry_reported") is False:
                unreported_gas_tests.add(tid)

            field_unit_specs = (
                ("initial_air_flow_cm_s", "cm/s", "reported", "ambient_or_measured"),
                ("ambient_pressure_kpa", "kPa", "reported", "ambient_or_measured"),
                ("oxygen_mol_percent", "% mol", "reported", "ambient_or_measured"),
                ("derived_po2_kpa", "kPa", "derived", "derived_po2"),
                ("free_volume_m3", "m^3", "reported", "ambient_or_measured"),
                ("co2_increase_ppm", "ppm", "reported", "delta_post_fire"),
                ("co2_partial_pressure_increase_mmhg", "mmHg", "reported", "delta_post_fire"),
                ("co_increase_ppm", "ppm", "reported", "delta_post_fire"),
                ("burn_duration_s", "s", "reported", "duration"),
                ("o2_peak_heat_release_w", "W", "reported", "heat_release"),
                ("o2_total_heat_release_kj", "kJ", "reported", "heat_release"),
                ("fuel_avg_heat_release_w", "W", "reported", "heat_release"),
                ("fuel_total_heat_release_kj", "kJ", "reported", "heat_release"),
                ("max_temp_sfu_outlet_c", "C", "reported", "temperature"),
                ("max_temp_ffd_c", "C", "reported", "temperature"),
            )
            for fname, u_str, orig, t_ctx in field_unit_specs:
                _add_fact(
                    facts,
                    seen,
                    fact_id=f"case:{tid}:{fname}",
                    value=rec.get(fname),
                    unit=u_str,
                    field_name=fname,
                    physical_meaning=f"SAFFIRE {tid} {fname}",
                    origin_type=orig,
                    time_context=t_ctx,
                    citation_ids=(cit,),
                    test_id=tid,
                    record_pk=tid,
                    formula_and_inputs=(
                        "ambient_pressure_kpa * oxygen_mol_percent / 100"
                        if fname == "derived_po2_kpa"
                        else None
                    ),
                )
            for step_str in rec.get("flow_steps") or ():
                if isinstance(step_str, str):
                    for m_num in re.finditer(r"(\d+(?:\.\d+)?)\s*cm/s", step_str):
                        _add_fact(
                            facts,
                            seen,
                            fact_id=f"case:{tid}:flow_step:{m_num.group(1)}",
                            value=float(m_num.group(1)),
                            unit="cm/s",
                            field_name="flow_step_cm_s",
                            physical_meaning=f"SAFFIRE {tid} flow step",
                            origin_type="reported",
                            time_context="ambient_or_measured",
                            citation_ids=(cit,),
                            test_id=tid,
                            record_pk=tid,
                        )

        c_sum = case_payload.get("summary") or {}
        if isinstance(c_sum, Mapping):
            for uid in c_sum.get("unreported_gas_calorimetry_test_ids") or ():
                if uid:
                    unreported_gas_tests.add(str(uid))
                    all_test_ids.add(str(uid))
            for cnt_k in ("total_condition_records", "reported_gas_calorimetry_count"):
                _add_fact(
                    facts,
                    seen,
                    fact_id=f"case:summary:{cnt_k}",
                    value=c_sum.get(cnt_k),
                    unit="count",
                    field_name=cnt_k,
                    physical_meaning=cnt_k,
                    origin_type="derived",
                    time_context="count",
                    citation_ids=(),
                )
            tl = c_sum.get("vi3_timeline") or {}
            if isinstance(tl, Mapping):
                all_test_ids.add("VI-3")
                tl_specs = (
                    ("ignition_time_s", "s", "reported", "ignition", None),
                    ("alarm_threshold_mg_m3", "mg/m^3", "reported", "threshold", None),
                    ("alarm_threshold_time_s", "s", "reported", "threshold", None),
                    (
                        "derived_elapsed_ignition_to_threshold_s",
                        "s",
                        "derived",
                        "elapsed_delta",
                        "alarm_threshold_time_s (981 s) - ignition_time_s (637 s)",
                    ),
                    ("flow_reduced_time_s", "s", "reported", "flow_event", None),
                    ("flow_reduced_from_cm_s", "cm/s", "reported", "flow_event", None),
                    ("flow_reduced_to_cm_s", "cm/s", "reported", "flow_event", None),
                    ("flow_terminated_time_s", "s", "reported", "flow_event", None),
                    ("reported_burn_duration_s", "s", "reported", "duration", None),
                )
                for fname, u_str, orig, t_ctx, form in tl_specs:
                    _add_fact(
                        facts,
                        seen,
                        fact_id=f"case:VI-3:{fname}",
                        value=tl.get(fname),
                        unit=u_str,
                        field_name=fname,
                        physical_meaning=f"SAFFIRE VI-3 {fname}",
                        origin_type=orig,
                        time_context=t_ctx,
                        citation_ids=("CASE-DET:DET-A", "CASE-TBL:VI-3"),
                        test_id="VI-3",
                        record_pk="VI-3",
                        formula_and_inputs=form,
                    )
        for th_k, th_obj in (case_payload.get("regulatory_reference_thresholds") or {}).items():
            if isinstance(th_obj, Mapping) and th_obj.get("value") is not None:
                _add_fact(
                    facts,
                    seen,
                    fact_id=f"case:threshold:{th_k}",
                    value=th_obj.get("value"),
                    unit=str(th_obj.get("unit") or ""),
                    field_name=f"threshold_{th_k}",
                    physical_meaning=f"NASA reference threshold {th_k}",
                    origin_type="reported",
                    time_context="reference_limit",
                    citation_ids=("CASE-DET:DET-A",),
                )
                period_txt = f"{th_obj.get('exposure_period') or ''} {th_obj.get('source') or ''}"
                for m_p in re.finditer(r"(?<![A-Za-z0-9_.\-])\d+(?:,\d{3})*(?:\.\d+)?(?![A-Za-z0-9_.])", period_txt):
                    doc_numbers.add(float(m_p.group(0).replace(",", "")))
        for det in case_payload.get("detection_evidence") or ():
            if isinstance(det, Mapping):
                det_text = f"{det.get('summary') or ''} {det.get('limitations') or ''}"
                for m_d in re.finditer(r"(?<![A-Za-z0-9_.\-])\d+(?:,\d{3})*(?:\.\d+)?(?![A-Za-z0-9_.])", det_text):
                    val_d = float(m_d.group(0).replace(",", ""))
                    doc_numbers.add(val_d)
                    _add_fact(
                        facts,
                        seen,
                        fact_id=f"case:det:{det.get('evidence_id') or 'card'}:{m_d.group(0).replace(',', '')}",
                        value=val_d,
                        unit="",
                        field_name="detection_evidence_number",
                        physical_meaning="Published SAFFIRE detection evidence figure",
                        origin_type="reported",
                        time_context="document_passage",
                        citation_ids=(f"CASE-DET:{det.get('evidence_id') or 'DET-A'}",),
                    )

    # FLEX prediction payload
    flex_payload = getattr(bundle, "flex_model_payload", None)
    if isinstance(flex_payload, Mapping):
        norm_in = flex_payload.get("normalized_input") or {}
        if isinstance(norm_in, Mapping):
            for k, u_str, scale_pct in (
                ("o2_mol_frac", "mol_frac", "% mol"),
                ("co2_mol_frac", "mol_frac", "% mol"),
                ("he_mol_frac", "mol_frac", "% mol"),
                ("n2_mol_frac", "mol_frac", "% mol"),
                ("pressure_mmhg", "mmHg", None),
                ("droplet_initial_diameter_mm", "mm", None),
            ):
                val = norm_in.get(k)
                _add_fact(
                    facts,
                    seen,
                    fact_id=f"flex_in:{k}",
                    value=val,
                    unit=u_str,
                    field_name=k,
                    physical_meaning=f"Requested FLEX input {k}",
                    origin_type="reported",
                    time_context="initial" if "initial" in k else "ambient_or_measured",
                    citation_ids=(),
                )
                if scale_pct and isinstance(val, (int, float)):
                    _add_fact(
                        facts,
                        seen,
                        fact_id=f"flex_in:{k}:pct",
                        value=float(val) * 100.0,
                        unit=scale_pct,
                        field_name=f"{k}_pct",
                        physical_meaning=f"Requested FLEX input {k} (%)",
                        origin_type="derived",
                        time_context="ambient_or_measured",
                        citation_ids=(),
                    )
            if isinstance(norm_in.get("pressure_mmhg"), (int, float)):
                p_mmhg = float(norm_in["pressure_mmhg"])
                _add_fact(
                    facts,
                    seen,
                    fact_id="flex_in:pressure_atm",
                    value=round(p_mmhg / 760.0, 4),
                    unit="atm",
                    field_name="pressure_atm",
                    physical_meaning="Requested pressure in atm",
                    origin_type="derived",
                    time_context="ambient_or_measured",
                    citation_ids=(),
                    formula_and_inputs=f"{p_mmhg} / 760",
                )
                _add_fact(
                    facts,
                    seen,
                    fact_id="flex_in:pressure_kpa",
                    value=round(p_mmhg * 101.325 / 760.0, 3),
                    unit="kPa",
                    field_name="pressure_kpa",
                    physical_meaning="Requested pressure in kPa",
                    origin_type="derived",
                    time_context="ambient_or_measured",
                    citation_ids=(),
                )

        gate = flex_payload.get("support_gate") or {}
        if isinstance(gate, Mapping):
            for gk in ("nearest_distance_std", "distance_threshold_std"):
                _add_fact(
                    facts,
                    seen,
                    fact_id=f"flex_gate:{gk}",
                    value=gate.get(gk),
                    unit="std",
                    field_name=gk,
                    physical_meaning=f"Support gate {gk}",
                    origin_type="derived",
                    time_context="support_gate",
                    citation_ids=(),
                )

        est = flex_payload.get("model_estimates_only") or {}
        if isinstance(est, Mapping):
            br = est.get("burning_rate_mm2_s") or {}
            if isinstance(br, Mapping):
                for bk, b_unit in (
                    ("value", "mm^2/s"),
                    ("raw_model_output", "mm^2/s"),
                    ("group_cv_mae", "mm^2/s"),
                    ("group_cv_rmse", "mm^2/s"),
                    ("group_cv_r2", ""),
                    ("group_fuel_cv_r2", ""),
                ):
                    _add_fact(
                        facts,
                        seen,
                        fact_id=f"flex_model:ridge:{bk}",
                        value=br.get(bk),
                        unit=b_unit,
                        field_name=f"burning_rate_{bk}",
                        physical_meaning=f"ridge_phys8 {bk} (model estimate)",
                        origin_type="model_prediction",
                        time_context="model_output",
                        citation_ids=("MODEL:ridge_phys8",),
                    )
            ext = est.get("extinction_likelihood") or {}
            if isinstance(ext, Mapping):
                for ek, e_unit in (
                    ("score", ""),
                    ("decision_threshold", ""),
                    ("group_cv_roc_auc", ""),
                    ("group_fuel_cv_roc_auc", ""),
                    ("group_cv_brier", ""),
                    ("false_positive_rate_on_non_extinction", ""),
                ):
                    val = ext.get(ek)
                    _add_fact(
                        facts,
                        seen,
                        fact_id=f"flex_model:logit:{ek}",
                        value=val,
                        unit=e_unit,
                        field_name=f"extinction_{ek}",
                        physical_meaning=f"logit_phys10 {ek} (model estimate)",
                        origin_type="model_prediction",
                        time_context="model_output",
                        citation_ids=("MODEL:logit_phys10",),
                    )
                    if ek in {"score", "false_positive_rate_on_non_extinction"} and isinstance(val, (int, float)):
                        pct_fid = "score_pct" if ek == "score" else "fp_rate_pct"
                        _add_fact(
                            facts,
                            seen,
                            fact_id=f"flex_model:logit:{pct_fid}",
                            value=float(val) * 100.0,
                            unit="%",
                            field_name=f"extinction_{pct_fid}",
                            physical_meaning=f"logit_phys10 {ek} (%) (model estimate)",
                            origin_type="derived" if ek != "score" else "model_prediction",
                            time_context="model_output",
                            citation_ids=("MODEL:logit_phys10",),
                        )
                # Parse calibration counts from calibration_warning / false_positives_by_true_end if present
                for fp_v in (ext.get("false_positives_by_true_end") or {}).values():
                    _add_fact(
                        facts,
                        seen,
                        fact_id=f"flex_model:logit:fp:{fp_v}",
                        value=fp_v,
                        unit="count",
                        field_name="fp_count",
                        physical_meaning="False positive breakdown count",
                        origin_type="derived",
                        time_context="count",
                        citation_ids=("MODEL:logit_phys10",),
                    )
                cw = str(ext.get("calibration_warning") or "")
                for m_cal in re.finditer(r"\b(\d+(?:\.\d+)?)\b", cw):
                    cal_v = float(m_cal.group(1))
                    doc_numbers.add(cal_v)
                    _add_fact(
                        facts,
                        seen,
                        fact_id=f"flex_model:logit:cal:{m_cal.group(1)}",
                        value=cal_v,
                        unit="count",
                        field_name="calibration_metric",
                        physical_meaning="Documented calibration/threshold metric from logit_phys10 warning",
                        origin_type="derived",
                        time_context="count",
                        citation_ids=("MODEL:logit_phys10",),
                    )

    # Retrieved document passages: record numerical values appearing verbatim in retrieved text
    doc_res = getattr(bundle, "document_result", None)
    if doc_res is not None:
        for hit in getattr(doc_res, "hits", ()) or ():
            src_txt = str(getattr(hit, "source_text", "") or "")
            cit = f"DOC:{getattr(hit, 'chunk_id', '')}"
            for m_num in re.finditer(r"(?<![A-Za-z0-9_.\-])\d+(?:,\d{3})*(?:\.\d+)?(?![A-Za-z0-9_.])", src_txt):
                raw_num = m_num.group(0).replace(",", "")
                try:
                    num = float(raw_num)
                except ValueError:
                    continue
                doc_numbers.add(num)
                _add_fact(
                    facts,
                    seen,
                    fact_id=f"doc:{getattr(hit, 'chunk_id', '')}:{raw_num}",
                    value=num,
                    unit="",
                    field_name="document_passage_number",
                    physical_meaning="Verbatim number from retrieved primary passage",
                    origin_type="reported",
                    time_context="document_passage",
                    citation_ids=(cit,),
                )
            for pg_attr in ("pdf_page_start", "pdf_page_end"):
                pg = getattr(hit, pg_attr, None)
                if pg is not None:
                    doc_numbers.add(float(pg))
            for pr_attr in ("printed_page_start", "printed_page_end"):
                pr = getattr(hit, pr_attr, None)
                if pr and str(pr).isdigit():
                    doc_numbers.add(float(str(pr)))

    metadata = {
        "unreported_gas_tests": unreported_gas_tests,
        "all_test_ids": all_test_ids,
        "doc_numbers": doc_numbers,
        "has_case": case_payload is not None,
        "has_flex_model": flex_payload is not None,
    }
    return tuple(facts), metadata


# Whitelisted safe context patterns that contain digits (IDs, citations, chemical formulas, years, standards)
_SAFE_SPAN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\[(?:TBL|DOC|CASE-TBL|CASE-DET|MODEL):[^\]]+\]"),
    re.compile(r"\b(?:TBL|DOC|CASE-TBL|CASE-DET|MODEL):[A-Za-z0-9_.:-]*[A-Za-z0-9]"),
    re.compile(r"\b(?:PSI|SAFFIRE|BASS|FLEX|SAME)[-\s]*(?:\d+(?::\d+)?|IV|VI|I{1,3}|V|R|2J)(?:-\d+)?\b", re.IGNORECASE),
    re.compile(r"\b(?:IV|V|VI)-\d+\b"),
    re.compile(r"\b(?:NASA-STD-\d+|JSC[-\s]*\d+|NTRS\s+\d+|NIST[-\s]*\d+)\b", re.IGNORECASE),
    re.compile(r"\bNASA/(?:TP|TM)[-\u2014\u2013]*\d+(?:-\d+)?\b", re.IGNORECASE),
    re.compile(r"\b(?:Table|Section|Fig\.?|Figure|Appendix|Page|p\.|pp\.)\s+[A-Z0-9.\-]+\b", re.IGNORECASE),
    re.compile(r"\b(?:O2|CO2|N2|H2O|H2|NO2|CH4|C7H16|CH3OH|pm2\.5|PM2\.5|PM10?|1/6g|3/8g|1g|0g)\b", re.IGNORECASE),
    re.compile(r"\b(?:ridge_phys8|logit_phys10|logreg_phys7)\b", re.IGNORECASE),
    re.compile(r"\b(?:19|20)\d{2}\b"),
    re.compile(r"#\d+\b"),
    re.compile(r"\b2\^6\b"),
)

_NUMBER_WITH_UNIT_RE = re.compile(
    r"(?<![A-Za-z0-9_.\-])"
    r"(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)"
    r"(?:\s*(?:(mol%|vol%|% mol|% vol|%)(?![A-Za-z0-9_])|(mmHg|torr|atm|kPa|Pa|psi|ppm|mmSqSec|mm\^2/s|mm2/s|mm²/s|mm|cm/s|m/s|unitVol|m\^3|m3|m³|unitMassConc|mg/m\^3|mg/m3|mg/m³|secs?|seconds?|s|hrs?|hours?|days?|min|kW|kJ|W|°C|C|std)\b))?"
    r"(?![A-Za-z0-9_])",
    re.IGNORECASE,
)

_FRACTION_RE = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")
_TEST_MENTION_RE = re.compile(
    r"(?:\[(?:TBL|CASE-TBL):([^\]]+)\]|(?:PSI-(?:25|69):(\d+))|\b(IV-1|V-2|V-3|V-4|VI-2|VI-3|VI-4)\b|\b(?:test|run|FLEX)[-\s]+(\d+)\b)",
    re.IGNORECASE,
)

_INITIAL_HINTS = ("initial diameter", "d0", "initial droplet", "initial size")
_FINAL_HINTS = ("extinction diameter", "d_ext", "final diameter", "visible flame extinction")
_ZERO_COERCE_RE = re.compile(
    r"\b(?:0(?:\.0+)?\s*(?:ppm|mmhg|mg/m|kpa)?|zero\s+(?:co2?|increase|ppm|mmhg)|no\s+(?:co2?|gas)\s+increase)\b",
    re.IGNORECASE,
)
_DELTA_CO2_EXPOSURE_BAD_RE = re.compile(
    r"(?:delta\s*co2|co2\s+increase|8539\s*ppm|1639\s*ppm|1\.28\s*mmhg).{0,60}\b(?:crew\s+(?:exposure|toxicity)\s+limit|crew\s+dose|safe\s+for\s+(?:crew|humans|astronauts)|lethal\s+dose)\b"
    r"|\b(?:crew\s+(?:exposure|toxicity)\s+limit|crew\s+dose|occupant\s+exposure)\b.{0,50}(?:exceeded|proven\s+safe)\s+by\s+(?:delta\s*co2|co2\s+increase)",
    re.IGNORECASE,
)
_MODEL_AS_NASA_MEAS_RE = re.compile(
    r"\b(?:model\s+(?:prediction|estimate|output)|ridge_phys8|logit_phys10)\b.{0,55}\b(?:was\s+measured\s+by\s+nasa|nasa\s+measured\s+test\s+value|experimental\s+measurement)\b"
    r"|\b(?:measured\s+by\s+nasa|experimental\s+nasa\s+value)\s+(?:from|of)\s+(?:ridge_phys8|logit_phys10|model)\b",
    re.IGNORECASE,
)


def _mask_safe_spans(text: str) -> str:
    chars = list(text)
    for pat in _SAFE_SPAN_PATTERNS:
        for m in pat.finditer(text):
            for idx in range(m.start(), m.end()):
                chars[idx] = " "
    # Also mask explicit chemical subscript / section numbers like "5.2" after §
    out = "".join(chars)
    out = re.sub(r"§\s*[A-Z0-9.\-]+", " ", out)
    # Split numeric ranges like "0.5-1.0" cleanly so "-1.0" isn't parsed negative
    out = re.sub(r"(?<=\d)\s*[-–—]\s*(?=\d)", " to ", out)
    # Mask exponent 2/3 inside unit tokens while preserving canonical unit checking
    out = re.sub(r"(?:mm\^2/s|mm2/s|mm²/s)", " mmSqSec ", out, flags=re.IGNORECASE)
    out = re.sub(r"mg/m(?:\^3|3|³)", " unitMassConc ", out, flags=re.IGNORECASE)
    out = re.sub(r"\bm(?:\^3|3|³)", " unitVol ", out, flags=re.IGNORECASE)
    return out


def _decimals_in_token(num_str: str) -> int:
    if "." not in num_str:
        return 0
    return len(num_str.split(".", 1)[1])


def _value_matches_fact(num: float, decimals: int, fact_val: float) -> bool:
    if decimals == 0:
        if abs(num - fact_val) <= 1e-5:
            return True
        # Allow rounded integer ONLY when fact magnitude is >= 10 and rounds directly to num
        if abs(num) >= 10 and abs(round(fact_val) - num) <= 1e-6:
            return True
        return False
    half_ulp = 0.5 * (10.0 ** (-decimals))
    return abs(num - fact_val) <= (half_ulp + 1e-5)


def _extract_unit_after_match(raw_text: str, end_pos: int, captured_unit_pct: str | None, captured_unit_word: str | None = None) -> str:
    if captured_unit_pct:
        return _canonical_unit(captured_unit_pct)
    if captured_unit_word:
        return _canonical_unit(captured_unit_word)
    tail = raw_text[end_pos:end_pos + 18]
    m_u = re.match(r"^\s*(?:(mol%|vol%|% mol|% vol|%)(?![A-Za-z0-9_])|(mmHg|torr|atm|kPa|Pa|psi|ppm|mmSqSec|mm\^2/s|mm2/s|mm|cm/s|m/s|unitVol|m3|m\^3|unitMassConc|mg/m3|mg/m\^3|secs?|seconds?|s|hrs?|hours?|days?|min|W|kW|kJ|°C|C|std)\b)", tail, re.IGNORECASE)
    if m_u:
        return _canonical_unit(m_u.group(1) or m_u.group(2))
    return ""


def _extract_test_mentions(text: str) -> set[str]:
    out: set[str] = set()
    for m in _TEST_MENTION_RE.finditer(text):
        for g in m.groups():
            if not g:
                continue
            token = g.strip()
            if ":" in token:
                out.add(token)
                out.add(token.split(":")[-1])
            else:
                out.add(token)
    return out


def _candidate_facts_for_text(
    facts: Sequence[EvidenceFact],
    *,
    num: float,
    decimals: int,
    unit: str,
    test_mentions: set[str],
    clause_lower: str,
) -> tuple[list[EvidenceFact], list[str]]:
    issues: list[str] = []
    # Check semantic context hints in local clause
    has_initial_hint = any(h in clause_lower for h in _INITIAL_HINTS) and not any(h in clause_lower for h in _FINAL_HINTS)
    has_final_hint = any(h in clause_lower for h in _FINAL_HINTS) and not any(h in clause_lower for h in _INITIAL_HINTS)

    val_matches = [f for f in facts if _value_matches_fact(num, decimals, f.value)]
    if not val_matches:
        return [], [f"Unverified number {num} (decimals={decimals}, unit={unit or 'none'}) does not match any bundle fact within source precision."]

    # Explicit unit compatibility check when caller text provides a unit
    if unit:
        unit_matches = [
            f for f in val_matches
            if (f.unit == unit)
            or (unit == "%" and f.unit in {"%", "% mol", "% vol"})
            or (f.unit == "" and f.time_context == "document_passage")
        ]
        #Wait: if value ONLY matches document_passage AND a table fact exists with the SAME value in a DIFFERENT incompatible physical unit (e.g. 760 mmHg written as 760 atm!), reject!
        non_doc_matches = [f for f in val_matches if f.time_context != "document_passage"]
        if non_doc_matches and not any(
            (f.unit == unit) or (unit == "%" and f.unit in {"%", "% mol", "% vol"}) or f.unit == ""
            for f in non_doc_matches
        ):
            found_units = sorted({f.unit for f in non_doc_matches if f.unit})
            return [], [f"Unit mismatch for value {num}: text states '{unit}', bundle facts have {found_units}."]
        if unit_matches:
            val_matches = unit_matches
        elif non_doc_matches:
            found_units = sorted({f.unit for f in non_doc_matches if f.unit})
            return [], [f"Unit mismatch for value {num}: text states '{unit}', bundle facts have {found_units}."]

    # Single-test attribution check
    if len(test_mentions) == 1:
        mentioned = next(iter(test_mentions))
        # Summary/count/reference-limit/document facts are exempt if no record fact on another test overrides
        record_specific = [f for f in val_matches if f.test_id or f.record_pk]
        other_tests_only = record_specific and not any(
            (f.test_id == mentioned or f.record_pk == mentioned)
            for f in record_specific
        )
        non_record_matches = [
            f for f in val_matches
            if not f.test_id and not f.record_pk and f.time_context in {"summary_stat", "count", "reference_limit", "document_passage"}
        ]
        if other_tests_only and not non_record_matches:
            actual_ids = sorted({f.record_pk or f.test_id or "" for f in record_specific})
            return [], [f"Test attribution mismatch for value {num}: text references '{mentioned}', but value belongs to {actual_ids}."]

    # Initial vs final diameter swap check
    if has_initial_hint:
        final_only = [f for f in val_matches if f.time_context == "final"]
        non_final = [f for f in val_matches if f.time_context != "final"]
        if final_only and not non_final:
            return [], [f"Initial/final diameter swap: text labels {num} as initial diameter, but bundle records it strictly as final/extinction diameter."]
    if has_final_hint:
        init_only = [f for f in val_matches if f.time_context == "initial"]
        non_init = [f for f in val_matches if f.time_context != "initial"]
        if init_only and not non_init:
            return [], [f"Initial/final diameter swap: text labels {num} as final/extinction diameter, but bundle records it strictly as initial diameter."]

    return val_matches, []


def _split_clauses(text: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<=[.;\n])\s+", text) if c.strip()]


def audit_grounded_answer_numbers(
    *,
    summary: str,
    findings: Sequence[Mapping[str, Any]],
    bundle: Any,
    facts: Sequence[EvidenceFact] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> NumericalAuditReport:
    """Deterministically verify all numerical claims in LLM ``summary`` and ``findings``.

    Raises ``NumericalAuditError`` on any inconsistency; never silently edits LLM prose.
    """
    if facts is None or metadata is None:
        facts, metadata = extract_bundle_facts(bundle)

    unreported_gas_tests: set[str] = set(metadata.get("unreported_gas_tests") or ())
    has_case = bool(metadata.get("has_case"))
    has_flex_model = bool(metadata.get("has_flex_model"))

    blocks: list[tuple[str, str, tuple[str, ...]]] = [("summary", summary or "", ())]
    for idx, f in enumerate(findings):
        f_txt = str(f.get("text") or "")
        f_cits = tuple(str(c) for c in (f.get("citation_ids") or ()) if c)
        blocks.append((f"finding[{idx}]", f_txt, f_cits))

    all_issues: list[str] = []
    matched_fact_ids: list[str] = []
    seen_matched: set[str] = set()

    for label, text, block_cits in blocks:
        if not text:
            continue

        # 1. Semantic/provenance guardrail checks across the block
        if has_case and _DELTA_CO2_EXPOSURE_BAD_RE.search(text):
            all_issues.append(
                f"{label}: Conflates post-fire compartment Delta CO2 with crew toxicity/exposure ruling."
            )
        if has_flex_model and _MODEL_AS_NASA_MEAS_RE.search(text):
            all_issues.append(
                f"{label}: Presents empirical model prediction (ridge_phys8/logit_phys10) as a NASA experimental measurement."
            )

        block_test_mentions = _extract_test_mentions(text)
        for c in block_cits:
            if c.startswith(("TBL:", "CASE-TBL:")):
                block_test_mentions.add(c.split(":", 1)[1])

        for clause in _split_clauses(text):
            clause_lower = clause.lower()
            clause_mentions = _extract_test_mentions(clause)
            effective_mentions = clause_mentions or block_test_mentions

            # 2. Missing / unreported SAFFIRE gas runs (V-3, V-4) must never be coerced to 0
            for unrep_id in unreported_gas_tests:
                if unrep_id in effective_mentions and _ZERO_COERCE_RE.search(clause):
                    all_issues.append(
                        f"{label}: Coerces unreported gas calorimetry test {unrep_id} to 0/zero instead of preserving missing status."
                    )

            # 3. Mask identifiers/dates/formulas/units before extracting numbers
            masked = _mask_safe_spans(clause)

            # 4. Explicit fraction check A/B (after safe masking so 1/6g is untouched)
            for m_frac in _FRACTION_RE.finditer(masked):
                a_val = float(m_frac.group(1))
                b_val = float(m_frac.group(2))
                a_matches = [f for f in facts if _value_matches_fact(a_val, 0, f.value)]
                b_matches = [f for f in facts if _value_matches_fact(b_val, 0, f.value)]
                if not (a_matches and b_matches) and b_val != 0:
                    # Also allow exact ratio match against a bundle count/ratio fact
                    ratio_pct = (a_val / b_val) * 100.0
                    if not any(_value_matches_fact(ratio_pct, 1, f.value) for f in facts):
                        all_issues.append(
                            f"{label}: Unverified fraction/denominator '{m_frac.group(1)}/{m_frac.group(2)}' not grounded in bundle counts."
                        )

            # Strip bare numerators/denominators already checked by fraction check OR validate them directly
            # Keep standard number extraction cleanly:
            for m_num in _NUMBER_WITH_UNIT_RE.finditer(masked):
                num_str = m_num.group(1).replace(",", "")
                try:
                    num = float(num_str)
                except ValueError:
                    continue
                decimals = _decimals_in_token(num_str)
                # Recover unit from original masked text slice if present
                unit = _extract_unit_after_match(masked, m_num.end(1), m_num.group(2), m_num.group(3))
                # Ignore list enumerator like "1. " at start of clause with no unit
                if m_num.start() <= 2 and decimals == 0 and masked[m_num.end(1):m_num.end(1) + 2] == ". ":
                    continue

                matched, num_issues = _candidate_facts_for_text(
                    facts,
                    num=num,
                    decimals=decimals,
                    unit=unit,
                    test_mentions=effective_mentions,
                    clause_lower=clause_lower,
                )
                if num_issues:
                    for iss in num_issues:
                        all_issues.append(f"{label}: {iss}")
                else:
                    for mf in matched[:3]:
                        if mf.fact_id not in seen_matched:
                            seen_matched.add(mf.fact_id)
                            matched_fact_ids.append(mf.fact_id)

    if all_issues:
        raise NumericalAuditError(all_issues)

    return NumericalAuditReport(
        status="passed",
        audited_fields=("summary", "findings"),
        checked_facts_count=len(facts),
        matched_fact_ids=tuple(matched_fact_ids),
        issues=(),
        disclaimer=NUMERICAL_AUDIT_DISCLAIMER,
    )
