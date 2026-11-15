"""Descriptive analytics, source-linked plot points, and safe CSV/JSON export.

Reuses the existing typed dataset contracts and query functions (`filter_records`,
`summarize_field`, `get_allowed_units`) without altering public query contracts,
duplicating measurement eligibility rules, pooling PSI-25 and PSI-69 distributions,
converting missing/censored values to zero, or inventing fire-risk/safety scores.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .data.contracts import ExperimentRecord, FieldContract, MeasurementStatus
from .data.query import (
    FieldSummary,
    NumericRangeFilter,
    QueryResult,
    QueryValidationError,
    _extract_value_in_unit,
    _resolve_contract,
    _serialize_source,
    _validate_investigation_id,
    filter_records,
    summarize_field,
)

DESCRIPTIVE_ANALYTICS_BOUNDARY = (
    "Descriptive record summary over verified runs within a single investigation; "
    "no outlier deletion, imputation, confidence intervals, causal inference, or fire-safety ranking. "
    "Missing, below_limit, above_limit, invalid, and meaning_unverified values are never turned into 0."
)

EXPORT_SCOPE_BOUNDARY = (
    "Source-linked descriptive export preserving per-run measurements, status exclusions, "
    "and SHA-256 locators; exporting records does not imply new modeling or cross-study pooling."
)

_SAFE_NEGATIVE_NUMBER_RE = re.compile(r"^-\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")
_FORMULA_LEADING_CHARS = frozenset(("=", "+", "-", "@", "\t", "\r"))


def _escape_csv_cell(value: Any) -> str:
    """Serialize cell for RFC 4180 CSV while neutralizing spreadsheet formulas cleanly.

    Real finite negative numbers (`int`/`float` or plain `-12.5` numeric text) are
    preserved intact; dangerous formula-like strings (`=`, `+`, `@`, tab/CR, or `-expr`)
    are prefixed with a single quote `'`.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise QueryValidationError("Non-finite floating point value cannot be exported to CSV.")
        return repr(value) if not value.is_integer() else str(value)

    text = str(value)
    stripped = text.strip()
    if stripped and _SAFE_NEGATIVE_NUMBER_RE.fullmatch(stripped):
        return text

    lstrip_text = text.lstrip(" ")
    if text and (text[0] in _FORMULA_LEADING_CHARS or (lstrip_text and lstrip_text[0] in ("=", "+", "-", "@"))):
        return "'" + text
    return text


def _build_locator_label(rec: ExperimentRecord) -> str:
    return (
        f"{rec.investigation_id} Test #{rec.test_id} "
        f"(csv_record_index={rec.source.csv_record_index}, "
        f"lines={rec.source.physical_line_start}-{rec.source.physical_line_end})"
    )


def _compute_median_from_summary_pks(
    records_by_pk: dict[str, ExperimentRecord],
    summary: FieldSummary,
    contract: FieldContract,
) -> float | None:
    """Compute median using the exact record_pks accepted by `summarize_field`."""
    if summary.used_total_count == 0 or not summary.used_record_pks:
        return None
    values: list[float] = []
    for pk in summary.used_record_pks:
        rec = records_by_pk[pk]
        measurement = rec.measurements[summary.field_name]
        val = _extract_value_in_unit(measurement, contract, summary.unit)
        if val is None or not math.isfinite(val):
            raise QueryValidationError(
                f"Invariant error: summarize_field accepted {pk!r} without finite value in {summary.unit!r}."
            )
        values.append(float(val))
    median_val = float(statistics.median(values))
    if not math.isfinite(median_val):
        raise QueryValidationError(f"Median for {summary.field_name!r} is non-finite.")
    return median_val


@dataclass(frozen=True)
class DescriptiveAnalyticsResult:
    """Typed single-study descriptive summary + raw points + strictly scoped chart views."""

    investigation_id: str
    field_name: str
    unit: str
    include_approximate: bool
    query_result: QueryResult
    summary: FieldSummary
    median_value: float | None
    raw_points: tuple[dict[str, Any], ...]
    status_distribution: tuple[dict[str, Any], ...]
    test_end_distribution: tuple[dict[str, Any], ...] | None
    charts: dict[str, Any]
    boundary_note: str = DESCRIPTIVE_ANALYTICS_BOUNDARY

    def to_dict(self) -> dict[str, Any]:
        summary_dict = self.summary.to_dict()
        summary_dict["median_value"] = self.median_value
        return {
            "investigation_id": self.investigation_id,
            "field_name": self.field_name,
            "unit": self.unit,
            "include_approximate": self.include_approximate,
            "total_runs": self.query_result.total_runs,
            "unique_sample_count": self.query_result.unique_sample_count,
            "unique_flex_identifier_count": self.query_result.unique_flex_identifier_count,
            "applied_filters": dict(self.query_result.applied_filters),
            "warnings": list(dict.fromkeys([*self.query_result.warnings, *self.summary.warnings])),
            "summary": summary_dict,
            "raw_points": [dict(pt) for pt in self.raw_points],
            "status_distribution": [dict(row) for row in self.status_distribution],
            "test_end_distribution": (
                [dict(row) for row in self.test_end_distribution]
                if self.test_end_distribution is not None
                else None
            ),
            "charts": dict(self.charts),
            "boundary_note": self.boundary_note,
        }


def build_descriptive_analytics(
    records: Sequence[ExperimentRecord],
    *,
    investigation_id: str,
    field_name: str,
    unit: str,
    fuel: str | None = None,
    test_end: str | None = None,
    numeric_filters: Sequence[NumericRangeFilter] = (),
    include_approximate: bool = False,
) -> DescriptiveAnalyticsResult:
    """Build descriptive analytics, chart views, and per-run points from one filtered subset."""
    _validate_investigation_id(investigation_id)
    _, contract = _resolve_contract(field_name, investigation_id)

    filtered = filter_records(
        records,
        investigation_id=investigation_id,
        fuel=fuel,
        test_end=test_end,
        numeric_filters=numeric_filters,
        include_approximate=include_approximate,
    )

    summary = summarize_field(
        filtered.records,
        investigation_id=investigation_id,
        field_name=field_name,
        unit=unit,
        include_approximate=include_approximate,
    )

    records_by_pk = {rec.record_pk: rec for rec in filtered.records}
    median_value = _compute_median_from_summary_pks(records_by_pk, summary, contract)
    used_pk_set = set(summary.used_record_pks)

    raw_points: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    test_end_counts: Counter[str] = Counter()

    for rec in filtered.records:
        m = rec.measurements.get(field_name)
        status_str = m.status.value if m is not None else MeasurementStatus.MISSING.value
        status_counts[status_str] += 1

        if investigation_id == "PSI-69":
            raw_label = rec.normalized_fields.get("test_end")
            label = str(raw_label).strip() if raw_label is not None and str(raw_label).strip() else "Missing"
            test_end_counts[label] += 1

        used_in_summary = rec.record_pk in used_pk_set
        value_in_unit: float | None = None
        if used_in_summary and m is not None:
            value_in_unit = _extract_value_in_unit(m, contract, unit)

        raw_points.append(
            {
                "record_pk": rec.record_pk,
                "investigation_id": rec.investigation_id,
                "test_id": rec.test_id,
                "sample_id": rec.sample_id,
                "flex_identifier": rec.flex_identifier,
                "fuel_norm": rec.normalized_fields.get("fuel_norm"),
                "test_end": rec.normalized_fields.get("test_end"),
                "field_name": field_name,
                "value": value_in_unit,
                "unit": unit,
                "measurement_status": status_str,
                "is_approximate": (m.status == MeasurementStatus.APPROXIMATE) if m is not None else False,
                "used_in_summary": used_in_summary,
                "raw_value": m.raw_value if m is not None else "",
                "parsed_value": m.parsed_value if m is not None else None,
                "normalized_value": m.normalized_value if m is not None else None,
                "normalized_unit": m.normalized_unit if m is not None else contract.normalized_unit,
                "source_lower_bound": m.source_lower_bound if m is not None else None,
                "source_upper_bound": m.source_upper_bound if m is not None else None,
                "source_locator": {
                    **_serialize_source(rec),
                    "locator_label": _build_locator_label(rec),
                },
            }
        )

    ordered_statuses = [status.value for status in MeasurementStatus]
    status_distribution = tuple(
        {"status": st, "count": status_counts.get(st, 0)}
        for st in ordered_statuses
    )

    test_end_dist: tuple[dict[str, Any], ...] | None = None
    if investigation_id == "PSI-69":
        test_end_dist = tuple(
            {"label": label, "count": count}
            for label, count in sorted(test_end_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        )

    charts: dict[str, Any] = {
        "raw_record_points": {
            "title": f"Descriptive Record View: {field_name} ({unit}) Across Filtered {investigation_id} Runs",
            "chart_type": "scatter_by_record_order",
            "x_axis": "source.csv_record_index",
            "y_axis": f"{field_name} ({unit})",
            "descriptive_only_note": (
                "Descriptive record distribution only; unaligned across fuels/pressures "
                "and not a causal effect or safety comparison."
            ),
            "total_runs": filtered.total_runs,
            "included_count": summary.used_total_count,
            "excluded_count": filtered.total_runs - summary.used_total_count,
            "points_key": "raw_points",
        },
        "measurement_status_distribution": {
            "title": f"Descriptive Record View: Measurement Status Counts for {field_name} ({investigation_id})",
            "chart_type": "bar_status_counts",
            "descriptive_only_note": (
                "Counts of measured vs excluded/missing/censored statuses within the filtered records; "
                "excluded entries are not zero."
            ),
            "total_runs": filtered.total_runs,
            "counts": [dict(row) for row in status_distribution],
        },
        "test_end_distribution": (
            {
                "title": "Descriptive Record View: Source 'Test end' Labels (PSI-69 FLEX)",
                "chart_type": "bar_source_labels",
                "descriptive_only_note": (
                    "Exact source Test end labels from PSI-69 CSV without renaming into safe/unsafe classes."
                ),
                "total_runs": filtered.total_runs,
                "counts": [dict(row) for row in test_end_dist],
            }
            if test_end_dist is not None
            else None
        ),
    }

    return DescriptiveAnalyticsResult(
        investigation_id=investigation_id,
        field_name=field_name,
        unit=unit,
        include_approximate=include_approximate,
        query_result=filtered,
        summary=summary,
        median_value=median_value,
        raw_points=tuple(raw_points),
        status_distribution=status_distribution,
        test_end_distribution=test_end_dist,
        charts=charts,
    )


def _format_applied_scope(analytics: DescriptiveAnalyticsResult) -> str:
    flt = analytics.query_result.applied_filters
    parts = [
        f"investigation_id={analytics.investigation_id}",
        f"field_name={analytics.field_name}",
        f"unit={analytics.unit}",
        f"include_approximate={str(analytics.include_approximate).lower()}",
        f"total_runs={analytics.query_result.total_runs}",
        f"used_in_summary={analytics.summary.used_total_count}",
    ]
    if flt.get("fuel"):
        parts.append(f"fuel={flt['fuel']}")
    if flt.get("test_end"):
        parts.append(f"test_end={flt['test_end']}")
    if flt.get("numeric_filters"):
        parts.append(f"numeric_filters={json.dumps(flt['numeric_filters'], ensure_ascii=False)}")
    return "; ".join(parts)


def _safe_filename(investigation_id: str, field_name: str, ext: str) -> str:
    inv_slug = re.sub(r"[^a-z0-9_-]+", "-", investigation_id.lower()).strip("-")
    field_slug = re.sub(r"[^a-z0-9_]+", "_", field_name.lower()).strip("_")
    return f"genaius_{inv_slug}_{field_slug}.{ext}"


def build_export_payload(
    records: Sequence[ExperimentRecord],
    *,
    investigation_id: str,
    field_name: str,
    unit: str,
    export_format: str,
    fuel: str | None = None,
    test_end: str | None = None,
    numeric_filters: Sequence[NumericRangeFilter] = (),
    include_approximate: bool = False,
) -> dict[str, Any]:
    """Generate formula-safe CSV or strict JSON export from the exact analytics subset."""
    if not isinstance(export_format, str) or export_format not in ("csv", "json"):
        raise QueryValidationError(
            f"Unsupported export format: {export_format!r}. Expected 'csv' or 'json'."
        )

    analytics = build_descriptive_analytics(
        records,
        investigation_id=investigation_id,
        field_name=field_name,
        unit=unit,
        fuel=fuel,
        test_end=test_end,
        numeric_filters=numeric_filters,
        include_approximate=include_approximate,
    )

    analytics_dict = analytics.to_dict()
    applied_scope = _format_applied_scope(analytics)
    filename = _safe_filename(investigation_id, field_name, export_format)
    used_cnt = int(analytics_dict["summary"]["used_total_count"])
    total_cnt = int(analytics_dict["total_runs"])
    if total_cnt > 0 and used_cnt > 0:
        cov_status = "matching"
        cov_label = "MATCHING TESTS FOUND"
    elif total_cnt > 0:
        cov_status = "related"
        cov_label = "RELATED TESTS ONLY"
    else:
        cov_status = "no_match"
        cov_label = "NO MATCH IN INDEXED SOURCES"
    cov_tol = f"Exact contract filters + explicit unit ({analytics.unit}); include_approximate={analytics.include_approximate}"

    if export_format == "json":
        export_doc = {
            "export_format": "json",
            "descriptive_boundary": EXPORT_SCOPE_BOUNDARY,
            "evidence_coverage": {
                "status": cov_status,
                "ui_label": cov_label,
                "applied_scope": applied_scope,
                "applied_tolerance": cov_tol,
                "total_runs": total_cnt,
                "used_in_summary_count": used_cnt,
            },
            "provenance_origin_types": ["reported", "derived"],
            "investigation_id": analytics.investigation_id,
            "field_name": analytics.field_name,
            "unit": analytics.unit,
            "include_approximate": analytics.include_approximate,
            "applied_filters": analytics_dict["applied_filters"],
            "applied_scope": applied_scope,
            "total_runs": analytics_dict["total_runs"],
            "summary": analytics_dict["summary"],
            "records": [
                {
                    "record_pk": pt["record_pk"],
                    "test_id": pt["test_id"],
                    "sample_id": pt["sample_id"],
                    "flex_identifier": pt["flex_identifier"],
                    "fuel_norm": pt["fuel_norm"],
                    "test_end": pt["test_end"],
                    "field_name": pt["field_name"],
                    "requested_unit": pt["unit"],
                    "raw_value": pt["raw_value"],
                    "parsed_value": pt["parsed_value"],
                    "normalized_value": pt["normalized_value"],
                    "normalized_unit": pt["normalized_unit"],
                    "value_in_requested_unit": pt["value"],
                    "measurement_status": pt["measurement_status"],
                    "used_in_summary": pt["used_in_summary"],
                    "exclusion_reason": (None if pt["used_in_summary"] else pt["measurement_status"]),
                    "source_locator": pt["source_locator"],
                }
                for pt in analytics_dict["raw_points"]
            ],
        }
        content = json.dumps(export_doc, ensure_ascii=False, allow_nan=False, indent=2)
        media_type = "application/json; charset=utf-8"
    else:
        buf = io.StringIO()
        fieldnames = [
            "investigation_id",
            "record_pk",
            "test_id",
            "sample_id",
            "flex_identifier",
            "fuel_norm",
            "test_end",
            "field_name",
            "requested_unit",
            "raw_value",
            "parsed_value",
            "normalized_value",
            "normalized_unit",
            "value_in_requested_unit",
            "measurement_status",
            "used_in_summary",
            "exclusion_reason",
            "applied_scope",
            "coverage_status",
            "coverage_label",
            "applied_tolerance",
            "source_relpath",
            "source_sha256",
            "csv_record_index",
            "physical_line_start",
            "physical_line_end",
            "descriptive_boundary",
        ]
        writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for pt in analytics_dict["raw_points"]:
            src = pt["source_locator"]
            writer.writerow(
                {
                    "investigation_id": _escape_csv_cell(pt["investigation_id"]),
                    "record_pk": _escape_csv_cell(pt["record_pk"]),
                    "test_id": _escape_csv_cell(pt["test_id"]),
                    "sample_id": _escape_csv_cell(pt["sample_id"]),
                    "flex_identifier": _escape_csv_cell(pt["flex_identifier"]),
                    "fuel_norm": _escape_csv_cell(pt["fuel_norm"]),
                    "test_end": _escape_csv_cell(pt["test_end"]),
                    "field_name": _escape_csv_cell(pt["field_name"]),
                    "requested_unit": _escape_csv_cell(pt["unit"]),
                    "raw_value": _escape_csv_cell(pt["raw_value"]),
                    "parsed_value": _escape_csv_cell(pt["parsed_value"]),
                    "normalized_value": _escape_csv_cell(pt["normalized_value"]),
                    "normalized_unit": _escape_csv_cell(pt["normalized_unit"]),
                    "value_in_requested_unit": _escape_csv_cell(pt["value"]),
                    "measurement_status": _escape_csv_cell(pt["measurement_status"]),
                    "used_in_summary": _escape_csv_cell(pt["used_in_summary"]),
                    "exclusion_reason": _escape_csv_cell(
                        None if pt["used_in_summary"] else pt["measurement_status"]
                    ),
                    "applied_scope": _escape_csv_cell(applied_scope),
                    "coverage_status": _escape_csv_cell(cov_status),
                    "coverage_label": _escape_csv_cell(cov_label),
                    "applied_tolerance": _escape_csv_cell(cov_tol),
                    "source_relpath": _escape_csv_cell(src["source_relpath"]),
                    "source_sha256": _escape_csv_cell(src["source_sha256"]),
                    "csv_record_index": _escape_csv_cell(src["csv_record_index"]),
                    "physical_line_start": _escape_csv_cell(src["physical_line_start"]),
                    "physical_line_end": _escape_csv_cell(src["physical_line_end"]),
                    "descriptive_boundary": _escape_csv_cell(EXPORT_SCOPE_BOUNDARY),
                }
            )
        content = buf.getvalue()
        media_type = "text/csv; charset=utf-8"

    return {
        "filename": filename,
        "media_type": media_type,
        "format": export_format,
        "total_runs": analytics_dict["total_runs"],
        "used_in_summary_count": analytics_dict["summary"]["used_total_count"],
        "excluded_count": analytics_dict["total_runs"] - analytics_dict["summary"]["used_total_count"],
        "content": content,
        "boundary_note": EXPORT_SCOPE_BOUNDARY,
    }


def _quantile_linear(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = (len(sorted_vals) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    frac = pos - lo
    return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


def _descriptive_stats(values: list[float]) -> dict[str, Any]:
    clean = sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
    n = len(clean)
    if n == 0:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "q1": None,
            "q3": None,
            "min": None,
            "max": None,
        }
    return {
        "count": n,
        "mean": round(float(statistics.fmean(clean)), 6),
        "median": round(float(statistics.median(clean)), 6),
        "q1": round(_quantile_linear(clean, 0.25), 6),
        "q3": round(_quantile_linear(clean, 0.75), 6),
        "min": round(float(clean[0]), 6),
        "max": round(float(clean[-1]), 6),
    }


def _measured_in_unit(rec: ExperimentRecord, field_name: str, unit: str | None = None) -> float | None:
    m = rec.measurements.get(field_name)
    if m is None or m.status != MeasurementStatus.MEASURED:
        return None
    _, contract = _resolve_contract(field_name, rec.investigation_id)
    val = _extract_value_in_unit(m, contract, unit or contract.normalized_unit)
    return float(val) if val is not None and math.isfinite(val) else None


def _flex_diluent_label(co2_pct: float | None, he_pct: float | None) -> str:
    if co2_pct is not None and co2_pct > 0:
        return "CO2"
    if he_pct is not None and he_pct > 0:
        return "Helium"
    return "None"


def _flex_outcome_parts(recs: Sequence[ExperimentRecord]) -> list[dict[str, Any]]:
    n = len(recs)
    counts: Counter[str] = Counter()
    for rec in recs:
        raw_end = rec.normalized_fields.get("test_end")
        label = str(raw_end).strip() if raw_end is not None and str(raw_end).strip() else "Missing"
        counts[label] += 1
    order = {"Extinction": 0, "Disruption": 1, "Completion": 2, "Missing": 3}
    return [
        {
            "label": label,
            "count": count,
            "share": round(count / n, 6) if n else 0.0,
        }
        for label, count in sorted(counts.items(), key=lambda kv: (order.get(kv[0], 9), -kv[1], kv[0]))
    ]


def build_flex_o2_pressure_coverage(
    all_flex_records: Sequence[ExperimentRecord],
    filtered_records: Sequence[ExperimentRecord],
) -> dict[str, Any]:
    """Build discrete measured PSI-69 O2 (% mol) x Pressure (atm) coverage matrix without gap interpolation."""
    o2_bins = (
        ("<14% O2", None, 14.0, True, False),
        ("14-18% O2", 14.0, 18.0, True, False),
        ("18-22% O2", 18.0, 22.0, True, False),
        ("22-26% O2", 22.0, 26.0, True, False),
        ("26-31% O2", 26.0, 31.0, True, True),
        (">31% O2", 31.0, None, False, True),
    )
    p_bins = (
        ("<0.55 atm", None, 0.55, True, False),
        ("0.55-0.85 atm", 0.55, 0.85, True, False),
        ("0.85-1.25 atm", 0.85, 1.25, True, False),
        ("1.25-2.20 atm", 1.25, 2.20, True, False),
        (">=2.20 atm", 2.20, None, True, True),
    )

    def _in_bin(val: float, lo: float | None, hi: float | None, lo_incl: bool, hi_incl: bool) -> bool:
        if lo is not None:
            if val < lo or (not lo_incl and val <= lo):
                return False
        if hi is not None:
            if val > hi or (not hi_incl and val >= hi):
                return False
        return True

    filtered_pks = {r.record_pk for r in filtered_records}
    cells: list[dict[str, Any]] = []
    unmeasured_filtered = 0
    total_with_o2_p = 0
    filtered_with_o2_p = 0

    row_recs: list[tuple[ExperimentRecord, float | None, float | None]] = []
    for rec in all_flex_records:
        o2 = _measured_in_unit(rec, "initial_o2_flex_mol_pct", "% mol")
        p = _measured_in_unit(rec, "ambient_pressure_kpa", "atm")
        if o2 is not None and p is not None:
            total_with_o2_p += 1
            if rec.record_pk in filtered_pks:
                filtered_with_o2_p += 1
        elif rec.record_pk in filtered_pks:
            unmeasured_filtered += 1
        row_recs.append((rec, o2, p))

    for p_label, p_lo, p_hi, p_lo_i, p_hi_i in p_bins:
        for o2_label, o2_lo, o2_hi, o2_lo_i, o2_hi_i in o2_bins:
            all_hits = [
                rec
                for rec, o2, p in row_recs
                if o2 is not None
                and p is not None
                and _in_bin(o2, o2_lo, o2_hi, o2_lo_i, o2_hi_i)
                and _in_bin(p, p_lo, p_hi, p_lo_i, p_hi_i)
            ]
            filt_hits = [rec for rec in all_hits if rec.record_pk in filtered_pks]
            cells.append(
                {
                    "o2_bin": o2_label,
                    "p_bin": p_label,
                    "filtered_count": len(filt_hits),
                    "total_psi69_count": len(all_hits),
                    "has_measured_runs": len(all_hits) > 0,
                    "has_filtered_runs": len(filt_hits) > 0,
                    "sample_record_pks": [r.record_pk for r in filt_hits[:5]] if filt_hits else [r.record_pk for r in all_hits[:3]],
                }
            )

    return {
        "corpus_id": "PSI-69 FLEX",
        "o2_bins": [b[0] for b in o2_bins],
        "pressure_bins": [b[0] for b in p_bins],
        "filtered_with_o2_p_count": filtered_with_o2_p,
        "filtered_missing_o2_or_p_count": unmeasured_filtered,
        "total_psi69_with_o2_p_count": total_with_o2_p,
        "total_psi69_count": len(all_flex_records),
        "cells": cells,
        "interpolation_policy": "zero_interpolation_empty_cells_mean_no_measured_psi69_run",
        "cross_regime_separation": [
            {
                "dataset": "PSI-69 FLEX",
                "coverage": "Measured O2 (% mol) x Pressure (atm) in microgravity spherical droplets (Heptane / Methanol).",
                "gap_note": "No partial-gravity (Moon 1/6g / Mars 3/8g) or CO2+He co-dilution tests exist.",
            },
            {
                "dataset": "PSI-25 BASS-II",
                "coverage": "Solid samples in O2 (% vol) only; ambient pressure & gravity are NOT recorded as calibrated numeric columns.",
                "gap_note": "Never pool or project BASS-II solids onto FLEX droplet O2 x P cells.",
            },
            {
                "dataset": "SAFFIRE IV-VI",
                "coverage": "Flow-duct Cygnus spacecraft cabin ambient pressure (kPa) & % mol O2 with ΔCO2/ΔCO & alarm timing.",
                "gap_note": "Separate engineering case study; spacecraft duct geometry != FLEX droplets or BASS-II.",
            },
        ],
    }


def build_flex_analytics(
    records: Sequence[ExperimentRecord],
    *,
    fuel: str | None = None,
    diluent: str | None = None,
    o2_min_pct: float | None = None,
    o2_max_pct: float | None = None,
    p_min_atm: float | None = None,
    p_max_atm: float | None = None,
    target_o2_pct: float | None = None,
    target_p_atm: float | None = None,
) -> dict[str, Any]:
    """Build verified PSI-69 (FLEX) descriptive summary, bands, and per-run points."""
    if diluent is not None and diluent not in ("any", "None", "CO2", "Helium"):
        raise QueryValidationError(f"Unsupported FLEX diluent filter: {diluent!r}.")

    ranges: list[NumericRangeFilter] = []
    if o2_min_pct is not None or o2_max_pct is not None:
        ranges.append(
            NumericRangeFilter(
                field_name="initial_o2_flex_mol_pct",
                unit="% mol",
                min_value=o2_min_pct,
                max_value=o2_max_pct,
            )
        )
    if p_min_atm is not None or p_max_atm is not None:
        ranges.append(
            NumericRangeFilter(
                field_name="ambient_pressure_kpa",
                unit="atm",
                min_value=p_min_atm,
                max_value=p_max_atm,
            )
        )

    base = filter_records(
        records,
        investigation_id="PSI-69",
        fuel=fuel,
        numeric_filters=ranges,
    )

    filtered_recs: list[ExperimentRecord] = []
    for rec in base.records:
        co2_pct = _measured_in_unit(rec, "initial_co2_flex_mol_pct", "% mol")
        he_pct = _measured_in_unit(rec, "initial_he_flex_mol_pct", "% mol")
        dil = _flex_diluent_label(co2_pct, he_pct)
        if diluent and diluent != "any" and dil != diluent:
            continue
        filtered_recs.append(rec)

    field_summaries: dict[str, Any] = {}
    for fname, unit in (
        ("burning_rate_mm2_s", "mm²/s"),
        ("burn_time_s", "s"),
        ("droplet_initial_diameter_mm", "mm"),
        ("visible_flame_extinction_diameter_mm", "mm"),
        ("initial_o2_flex_mol_pct", "% mol"),
        ("ambient_pressure_kpa", "atm"),
    ):
        sm = summarize_field(filtered_recs, investigation_id="PSI-69", field_name=fname, unit=unit)
        _, contract = _resolve_contract(fname, "PSI-69")
        by_pk = {rec.record_pk: rec for rec in filtered_recs}
        med = _compute_median_from_summary_pks(by_pk, sm, contract)
        sm_dict = sm.to_dict()
        sm_dict["median_value"] = round(med, 6) if med is not None else None
        field_summaries[fname] = sm_dict

    d_ext_raw_zero_count = sum(
        1
        for rec in filtered_recs
        if (v := _measured_in_unit(rec, "visible_flame_extinction_diameter_mm", "mm")) is not None and v == 0.0
    )
    d_ext_positive_vals = [
        v
        for rec in filtered_recs
        if (v := _measured_in_unit(rec, "visible_flame_extinction_diameter_mm", "mm")) is not None and v > 0.0
    ]

    band_bounds = [(lo, lo + 4.0) for lo in range(12, 36, 4)]
    fuels_present = [fuel] if fuel else ["Methanol", "Heptane"]
    oxygen_bands: list[dict[str, Any]] = []
    for f_label in fuels_present:
        for lo, hi in band_bounds:
            grp = [
                rec
                for rec in filtered_recs
                if rec.normalized_fields.get("fuel_norm") == f_label
                and (o2 := _measured_in_unit(rec, "initial_o2_flex_mol_pct", "% mol")) is not None
                and lo <= o2
                and (o2 < hi or (hi == 36.0 and o2 <= 36.0))
            ]
            if not grp:
                continue
            burn_vals = [v for r in grp if (v := _measured_in_unit(r, "burn_time_s", "s")) is not None]
            ext_pos_vals = [
                v
                for r in grp
                if (v := _measured_in_unit(r, "visible_flame_extinction_diameter_mm", "mm")) is not None and v > 0.0
            ]
            oxygen_bands.append(
                {
                    "fuel": f_label,
                    "o2_min_pct": lo,
                    "o2_max_pct": hi,
                    "label": f"{f_label}, {int(lo)} to {int(hi)}%",
                    "count": len(grp),
                    "outcomes": _flex_outcome_parts(grp),
                    "median_burn_time_s": _descriptive_stats(burn_vals)["median"],
                    "median_d_ext_positive_mm": _descriptive_stats(ext_pos_vals)["median"],
                }
            )

    diluent_groups: list[dict[str, Any]] = []
    for f_label in fuels_present:
        for d_label in ("None", "CO2", "Helium"):
            grp = [
                rec
                for rec in filtered_recs
                if rec.normalized_fields.get("fuel_norm") == f_label
                and _flex_diluent_label(
                    _measured_in_unit(rec, "initial_co2_flex_mol_pct", "% mol"),
                    _measured_in_unit(rec, "initial_he_flex_mol_pct", "% mol"),
                )
                == d_label
            ]
            if not grp:
                continue
            diluent_groups.append(
                {
                    "fuel": f_label,
                    "diluent": d_label,
                    "label": f"{f_label}, {'no diluent' if d_label == 'None' else d_label + ' added'}",
                    "count": len(grp),
                    "outcomes": _flex_outcome_parts(grp),
                }
            )

    run_rows: list[dict[str, Any]] = []
    for rec in filtered_recs:
        co2_pct = _measured_in_unit(rec, "initial_co2_flex_mol_pct", "% mol")
        he_pct = _measured_in_unit(rec, "initial_he_flex_mol_pct", "% mol")
        o2_pct = _measured_in_unit(rec, "initial_o2_flex_mol_pct", "% mol")
        p_atm = _measured_in_unit(rec, "ambient_pressure_kpa", "atm")
        d0_mm = _measured_in_unit(rec, "droplet_initial_diameter_mm", "mm")
        d_ext_mm = _measured_in_unit(rec, "visible_flame_extinction_diameter_mm", "mm")
        k_val = _measured_in_unit(rec, "burning_rate_mm2_s", "mm²/s")
        t_burn = _measured_in_unit(rec, "burn_time_s", "s")
        run_rows.append(
            {
                "record_pk": rec.record_pk,
                "investigation_id": rec.investigation_id,
                "test_id": rec.test_id,
                "flex_identifier": rec.flex_identifier,
                "fuel": rec.normalized_fields.get("fuel_norm"),
                "test_end": rec.normalized_fields.get("test_end"),
                "diluent": _flex_diluent_label(co2_pct, he_pct),
                "o2_mol_pct": o2_pct,
                "co2_mol_pct": co2_pct,
                "he_mol_pct": he_pct,
                "p_atm": p_atm,
                "d0_mm": d0_mm,
                "d_ext_mm": d_ext_mm,
                "d_ext_is_raw_zero": (d_ext_mm == 0.0) if d_ext_mm is not None else False,
                "burning_rate_mm2_s": k_val,
                "burn_time_s": t_burn,
                "measurement_statuses": {k: m.status.value for k, m in rec.measurements.items()},
                "source_locator": {
                    **_serialize_source(rec),
                    "locator_label": _build_locator_label(rec),
                },
            }
        )

    condition_match: dict[str, Any] | None = None
    if target_o2_pct is not None and target_p_atm is not None:
        all_flex = [rec for rec in records if rec.investigation_id == "PSI-69" and (not fuel or rec.normalized_fields.get("fuel_norm") == fuel)]
        matched_recs: list[ExperimentRecord] = []
        used_o2_win: float | None = None
        used_p_win: float | None = None
        match_level = "fuel_wide"
        for widen in range(4):
            factor = float(2 ** widen)
            o2_w = 2.0 * factor
            p_w = 0.1 * factor
            cand = [
                rec
                for rec in all_flex
                if (o2 := _measured_in_unit(rec, "initial_o2_flex_mol_pct", "% mol")) is not None
                and abs(o2 - float(target_o2_pct)) <= o2_w
                and ((p := _measured_in_unit(rec, "ambient_pressure_kpa", "atm")) is None or abs(p - float(target_p_atm)) <= p_w)
            ]
            if len(cand) >= 5:
                matched_recs = cand
                used_o2_win = o2_w
                used_p_win = p_w
                match_level = "matched"
                break
        if match_level != "matched":
            matched_recs = all_flex
        o2_vals = [v for r in matched_recs if (v := _measured_in_unit(r, "initial_o2_flex_mol_pct", "% mol")) is not None]
        d0_vals = [v for r in matched_recs if (v := _measured_in_unit(r, "droplet_initial_diameter_mm", "mm")) is not None]
        d_ext_pos = [
            v
            for r in matched_recs
            if (v := _measured_in_unit(r, "visible_flame_extinction_diameter_mm", "mm")) is not None and v > 0.0
        ]
        k_vals = [v for r in matched_recs if (v := _measured_in_unit(r, "burning_rate_mm2_s", "mm²/s")) is not None]
        t_vals = [v for r in matched_recs if (v := _measured_in_unit(r, "burn_time_s", "s")) is not None]
        condition_match = {
            "fuel": fuel or "Both fuels",
            "target_o2_pct": float(target_o2_pct),
            "target_p_atm": float(target_p_atm),
            "match_level": match_level,
            "o2_window_pct": used_o2_win,
            "p_window_atm": used_p_win,
            "count": len(matched_recs),
            "o2_range_pct": [min(o2_vals), max(o2_vals)] if o2_vals else None,
            "outcomes": _flex_outcome_parts(matched_recs),
            "medians": {
                "d0_mm": _descriptive_stats(d0_vals)["median"],
                "d_ext_positive_mm": _descriptive_stats(d_ext_pos)["median"],
                "burning_rate_mm2_s": _descriptive_stats(k_vals)["median"],
                "burn_time_s": _descriptive_stats(t_vals)["median"],
            },
            "sample_record_pks": [r.record_pk for r in matched_recs[:8]],
            "note": (
                "Exact outcome counts and descriptive medians from microgravity FLEX CSV runs; "
                "no confidence intervals or non-microgravity gravity extrapolation are computed."
            ),
        }

    from .coverage import assess_flex_analytics_coverage

    all_psi69_records = [rec for rec in records if rec.investigation_id == "PSI-69"]
    o2_pressure_cov = build_flex_o2_pressure_coverage(all_psi69_records, filtered_recs)
    matched_count = (
        int(condition_match["count"])
        if condition_match is not None
        else len(filtered_recs)
    )
    out = {
        "investigation_id": "PSI-69",
        "experiment_name": "Flame Extinguishment Experiment (FLEX)",
        "total_runs": len(filtered_recs),
        "corpus_total_runs": len(all_psi69_records),
        "matched_runs": matched_count,
        "applied_filters": {
            "fuel": fuel,
            "diluent": diluent,
            "o2_min_pct": o2_min_pct,
            "o2_max_pct": o2_max_pct,
            "p_min_atm": p_min_atm,
            "p_max_atm": p_max_atm,
            "target_o2_pct": target_o2_pct,
            "target_p_atm": target_p_atm,
        },
        "outcomes": _flex_outcome_parts(filtered_recs),
        "field_summaries": field_summaries,
        "d_ext_diagnostics": {
            "raw_zero_count": d_ext_raw_zero_count,
            "positive_used_count": len(d_ext_positive_vals),
            "positive_median_mm": _descriptive_stats(d_ext_positive_vals)["median"],
            "note": (
                "Runs recording 0.0 mm for visible_flame_extinction_diameter_mm remain in raw_points "
                "and summarize_field; positive_median_mm excludes 0.0 mm entries transparently."
            ),
        },
        "oxygen_bands": oxygen_bands,
        "diluent_groups": diluent_groups,
        "runs": run_rows,
        "condition_match": condition_match,
        "o2_pressure_coverage": o2_pressure_cov,
        "boundary_note": (
            f"{DESCRIPTIVE_ANALYTICS_BOUNDARY} FLEX runs are microgravity droplet tests only; "
            "no Wilson/parametric confidence intervals or cause-and-effect claims are produced."
        ),
    }
    if condition_match is None and len(filtered_recs) > 0:
        out["condition_match"] = {
            "match_level": "matched",
            "o2_window_pct": f"[{o2_min_pct}, {o2_max_pct}]",
            "p_window_atm": f"[{p_min_atm}, {p_max_atm}]",
            "count": len(filtered_recs),
        }
    out["coverage"] = assess_flex_analytics_coverage(out).to_dict()
    return out


def _classify_psi25_material(fuel_norm: str) -> tuple[str, str]:
    low = fuel_norm.lower()
    if "pmma" in low or "rod" in low or "film" in low or "micron" in low or "slab" in low or "spherical" in low:
        family = "PMMA"
    elif "sibal" in low:
        family = "SIBAL fabric"
    elif "nomex" in low:
        family = "Nomex"
    elif "wax" in low or "candle" in low:
        family = "Wax candle"
    else:
        family = "Other"

    if "film" in low or "micron" in low:
        shape = "film"
    elif "slab" in low or "sided" in low:
        shape = "slab"
    elif "rod" in low:
        shape = "rod"
    elif "spherical" in low or "sphere" in low:
        shape = "sphere"
    elif "sibal" in low or "nomex" in low:
        shape = "fabric"
    elif "wax" in low or "candle" in low:
        shape = "candle"
    else:
        shape = "other"
    return family, shape


def _parse_flow_restrictor(rec: ExperimentRecord) -> int | None:
    raw = str(rec.raw_fields.get("Flow restrictor") or "").strip()
    if not raw:
        return None
    try:
        fval = float(raw)
    except ValueError:
        return None
    return int(fval) if fval.is_integer() else None


def _compute_psi25_metric(
    rec: ExperimentRecord,
    metric: str,
) -> tuple[float | None, str]:
    """Compute paired gas change strictly from MEASURED initial & final values, or single field."""
    pairs = {
        "delta_co_ppm": ("initial_co_ppm", "final_co_ppm", "ppm"),
        "delta_o2_vol_pct": ("initial_o2_vol_pct", "final_o2_vol_pct", "% vol"),
        "delta_co2_vol_pct": ("initial_co2_vol_pct", "final_co2_vol_pct", "% vol"),
    }
    if metric == "final_co_ppm":
        m = rec.measurements.get("final_co_ppm")
        if m is None:
            return None, "missing"
        if m.status != MeasurementStatus.MEASURED:
            return None, m.status.value
        val = _measured_in_unit(rec, "final_co_ppm", "ppm")
        return (round(val, 6), "measured") if val is not None else (None, "missing")

    if metric not in pairs:
        raise QueryValidationError(f"Unsupported Material Lab metric: {metric!r}.")

    init_f, final_f, unit = pairs[metric]
    mi = rec.measurements.get(init_f)
    mf = rec.measurements.get(final_f)
    if mi is None or mf is None:
        return None, "missing"
    # Preserve explicit censorship/invalidity precedence without ever imputing zero.
    for st in (
        MeasurementStatus.ABOVE_LIMIT,
        MeasurementStatus.BELOW_LIMIT,
        MeasurementStatus.INVALID,
        MeasurementStatus.MEANING_UNVERIFIED,
        MeasurementStatus.APPROXIMATE,
        MeasurementStatus.MISSING,
    ):
        if mi.status == st or mf.status == st:
            return None, f"paired_excluded_{st.value}"
    v_init = _measured_in_unit(rec, init_f, unit)
    v_final = _measured_in_unit(rec, final_f, unit)
    if v_init is None or v_final is None:
        return None, "missing"
    return round(v_final - v_init, 6), "measured"


def build_material_lab_analytics(
    records: Sequence[ExperimentRecord],
    *,
    target_o2_pct: float = 21.0,
    window_pct: float = 3.0,
    metric: str = "delta_co_ppm",
    group_by: str = "material_family",
    flow_restrictor: int | None = None,
    pi: str | None = None,
    materials: Sequence[str] | None = None,
    dedupe_samples: bool = False,
) -> dict[str, Any]:
    """Build strictly verified PSI-25 (BASS-II) gas analytics without cross-study pooling."""
    if not math.isfinite(target_o2_pct) or not 0.0 <= target_o2_pct <= 100.0:
        raise QueryValidationError("target_o2_pct must be between 0 and 100.")
    if not math.isfinite(window_pct) or not 0.1 <= window_pct <= 50.0:
        raise QueryValidationError("window_pct must be between 0.1 and 50.0.")
    if group_by not in ("material_family", "material_shape"):
        raise QueryValidationError(f"Unsupported group_by mode: {group_by!r}.")
    if metric not in ("delta_co_ppm", "delta_o2_vol_pct", "delta_co2_vol_pct", "final_co_ppm"):
        raise QueryValidationError(f"Unsupported metric: {metric!r}.")

    all_r25 = filter_records(records, investigation_id="PSI-25").records
    max_tested_o2 = max(
        (v for r in all_r25 if (v := _measured_in_unit(r, "initial_o2_vol_pct", "% vol")) is not None),
        default=None,
    )
    min_tested_o2 = min(
        (v for r in all_r25 if (v := _measured_in_unit(r, "initial_o2_vol_pct", "% vol")) is not None),
        default=None,
    )
    available_materials = sorted({_classify_psi25_material(r.normalized_fields["fuel_norm"])[0] for r in all_r25})
    available_pis = sorted({str(r.normalized_fields.get("pi") or "").strip() for r in all_r25 if r.normalized_fields.get("pi")})
    available_restrictors = sorted({fr for r in all_r25 if (fr := _parse_flow_restrictor(r)) is not None})

    mat_filter = set(materials) if materials is not None else None
    run_rows: list[dict[str, Any]] = []
    excluded_counts: Counter[str] = Counter()

    for rec in all_r25:
        family, shape = _classify_psi25_material(rec.normalized_fields["fuel_norm"])
        rec_pi = str(rec.normalized_fields.get("pi") or "").strip()
        restr = _parse_flow_restrictor(rec)
        if mat_filter is not None and family not in mat_filter:
            continue
        if flow_restrictor is not None and restr != flow_restrictor:
            continue
        if pi and rec_pi != pi:
            continue

        o2_pct = _measured_in_unit(rec, "initial_o2_vol_pct", "% vol")
        d_co, st_co = _compute_psi25_metric(rec, "delta_co_ppm")
        d_o2, st_o2 = _compute_psi25_metric(rec, "delta_o2_vol_pct")
        d_co2, st_co2 = _compute_psi25_metric(rec, "delta_co2_vol_pct")
        f_co, st_fco = _compute_psi25_metric(rec, "final_co_ppm")

        sel_val = {
            "delta_co_ppm": d_co,
            "delta_o2_vol_pct": d_o2,
            "delta_co2_vol_pct": d_co2,
            "final_co_ppm": f_co,
        }[metric]
        sel_status = {
            "delta_co_ppm": st_co,
            "delta_o2_vol_pct": st_o2,
            "delta_co2_vol_pct": st_co2,
            "final_co_ppm": st_fco,
        }[metric]
        if sel_val is None:
            excluded_counts[sel_status] += 1

        group_label = (f"PMMA {shape}" if group_by == "material_shape" and family == "PMMA" else family)
        run_rows.append(
            {
                "record_pk": rec.record_pk,
                "investigation_id": rec.investigation_id,
                "test_id": rec.test_id,
                "sample_id": rec.sample_id,
                "is_repeat_sample": bool(rec.normalized_fields.get("is_repeat_sample")),
                "sample_run_count": rec.normalized_fields.get("sample_run_count"),
                "material_family": family,
                "material_shape": shape,
                "group_label": group_label,
                "fuel_norm": rec.normalized_fields.get("fuel_norm"),
                "pi": rec_pi or None,
                "test_date": rec.normalized_fields.get("test_date"),
                "flow_restrictor": restr,
                "o2_pct": o2_pct,
                "delta_co_ppm": d_co,
                "delta_co_status": st_co,
                "delta_o2_vol_pct": d_o2,
                "delta_o2_status": st_o2,
                "delta_co2_vol_pct": d_co2,
                "delta_co2_status": st_co2,
                "final_co_ppm": f_co,
                "final_co_status": st_fco,
                "selected_value": sel_val,
                "selected_status": sel_status,
                "source_locator": {
                    **_serialize_source(rec),
                    "locator_label": _build_locator_label(rec),
                },
            }
        )

    # Optionally collapse repeated Sample # measurements to 1 median point per unique specimen.
    analysis_units = run_rows
    if dedupe_samples:
        by_sample: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in run_rows:
            skey = (row["group_label"], row["sample_id"] or row["record_pk"])
            by_sample.setdefault(skey, []).append(row)
        collapsed: list[dict[str, Any]] = []
        for (_, _sid), srows in by_sample.items():
            o2s = [r["o2_pct"] for r in srows if r["o2_pct"] is not None]
            vals = [r["selected_value"] for r in srows if r["selected_value"] is not None]
            rep = dict(srows[0])
            rep["aggregated_run_pks"] = [r["record_pk"] for r in srows]
            rep["aggregated_run_count"] = len(srows)
            rep["o2_pct"] = round(float(statistics.median(o2s)), 6) if o2s else None
            rep["selected_value"] = round(float(statistics.median(vals)), 6) if vals else None
            rep["selected_status"] = "sample_median" if vals else srows[0]["selected_status"]
            collapsed.append(rep)
        analysis_units = collapsed

    groups_map: dict[str, list[dict[str, Any]]] = {}
    for row in analysis_units:
        groups_map.setdefault(row["group_label"], []).append(row)

    group_summaries: list[dict[str, Any]] = []
    for g_label, g_rows in groups_map.items():
        all_o2 = [r["o2_pct"] for r in g_rows if r["o2_pct"] is not None]
        near_rows = [
            r
            for r in g_rows
            if r["o2_pct"] is not None and abs(r["o2_pct"] - target_o2_pct) <= window_pct
        ]
        near_vals = [r["selected_value"] for r in near_rows if r["selected_value"] is not None]
        all_vals = [r["selected_value"] for r in g_rows if r["selected_value"] is not None]
        nearest_dist = (
            min(abs(r["o2_pct"] - target_o2_pct) for r in g_rows if r["o2_pct"] is not None)
            if all_o2
            else None
        )
        tier = 2 if not near_rows else (0 if len(near_vals) >= 3 else 1)
        unique_samples_in_group = len({r["sample_id"] for r in g_rows if r["sample_id"]})
        group_summaries.append(
            {
                "label": g_label,
                "unit_count": len(g_rows),
                "run_count": sum(r.get("aggregated_run_count", 1) for r in g_rows),
                "unique_sample_count": unique_samples_in_group,
                "near_unit_count": len(near_rows),
                "near_used_count": len(near_vals),
                "near_excluded_count": len(near_rows) - len(near_vals),
                "near_stats": _descriptive_stats(near_vals),
                "all_used_count": len(all_vals),
                "all_excluded_count": len(g_rows) - len(all_vals),
                "all_stats": _descriptive_stats(all_vals),
                "o2_min_pct": round(min(all_o2), 3) if all_o2 else None,
                "o2_max_pct": round(max(all_o2), 3) if all_o2 else None,
                "nearest_distance_pct": round(nearest_dist, 3) if nearest_dist is not None else None,
                "tier": tier,
            }
        )

    group_summaries.sort(
        key=lambda g: (
            g["tier"],
            g["near_stats"]["median"] if g["tier"] == 0 and g["near_stats"]["median"] is not None else float("inf"),
            -g["near_unit_count"] if g["tier"] == 1 else (g["nearest_distance_pct"] if g["nearest_distance_pct"] is not None else float("inf")),
            g["label"],
        )
    )

    all_used_vals = [r["selected_value"] for r in analysis_units if r["selected_value"] is not None]
    beyond_tested = bool(max_tested_o2 is not None and target_o2_pct > max_tested_o2 + window_pct)
    unique_samples_total = len({r["sample_id"] for r in run_rows if r["sample_id"]})

    from .coverage import assess_material_lab_coverage

    near_matched_count = sum(
        1
        for r in analysis_units
        if r.get("o2_pct") is not None and abs(float(r["o2_pct"]) - float(target_o2_pct)) <= float(window_pct)
    )
    tight_matched_count = sum(
        1
        for r in analysis_units
        if r.get("o2_pct") is not None and abs(float(r["o2_pct"]) - float(target_o2_pct)) <= min(0.5, float(window_pct))
    )
    for r in analysis_units:
        if r.get("o2_pct") is not None and abs(float(r["o2_pct"]) - float(target_o2_pct)) <= min(0.5, float(window_pct)):
            r["match_kind"] = "exact_band"
        elif r.get("o2_pct") is not None and abs(float(r["o2_pct"]) - float(target_o2_pct)) <= float(window_pct):
            r["match_kind"] = "window"
        else:
            r["match_kind"] = "outside_window"

    out_lab = {
        "investigation_id": "PSI-25",
        "experiment_name": "Burning and Suppression of Solids - II (BASS-II)",
        "aggregation_mode": "unique_sample_median" if dedupe_samples else "per_run",
        "total_runs": len(run_rows),
        "matched_runs": near_matched_count,
        "tight_matched_runs": tight_matched_count,
        "applied_filters": {
            "target_o2": float(target_o2_pct),
            "window_pct": float(window_pct),
            "metric": metric,
            "group_by": group_by,
            "flow_restrictor": flow_restrictor,
            "pi": pi,
            "materials": sorted(mat_filter) if mat_filter is not None else None,
            "dedupe_samples": dedupe_samples,
        },
        "unique_sample_count": unique_samples_total,
        "has_repeated_samples": len(run_rows) > unique_samples_total,
        "used_count": len(all_used_vals),
        "excluded_count": len(analysis_units) - len(all_used_vals),
        "excluded_by_reason": dict(sorted(excluded_counts.items())),
        "metric": metric,
        "group_by": group_by,
        "target_o2_pct": float(target_o2_pct),
        "window_pct": float(window_pct),
        "max_tested_o2_pct": round(max_tested_o2, 3) if max_tested_o2 is not None else None,
        "min_tested_o2_pct": round(min_tested_o2, 3) if min_tested_o2 is not None else None,
        "beyond_tested_range": beyond_tested,
        "available_filters": {
            "materials": available_materials,
            "pis": available_pis,
            "flow_restrictors": available_restrictors,
        },
        "groups": group_summaries,
        "runs": analysis_units,
        "boundary_note": (
            f"{DESCRIPTIVE_ANALYTICS_BOUNDARY} Material Lab uses verified PSI-25 (BASS-II) records only "
            "(never pooled with PSI-26 or SAFFIRE). Repeated Sample # burns, negative CO readings flagged "
            "as invalid ('nedeni doğrulanmadı'), and over-range (>1000 ppm) readings are never hidden or coerced to zero. "
            "Condition comparison only; not a flammability or safety ranking."
        ),
    }
    out_lab["coverage"] = assess_material_lab_coverage(out_lab).to_dict()
    return out_lab
