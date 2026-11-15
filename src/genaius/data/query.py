"""Framework-bağımsız, deterministik ve sözleşme uyumlu deney sorgulama ve karşılaştırma katmanı."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .contracts import DATASET_SPECS, ExperimentRecord, FieldContract, MeasurementStatus, TypedMeasurement
from .loader import normalize_fuel_label


class QueryValidationError(ValueError):
    """Geçersiz alan adı, uyumsuz çalışma/birim, geçersiz aralık veya eksik kayıt hatası."""


_CONTRACTS_BY_INVESTIGATION: dict[str, dict[str, FieldContract]] = {
    inv_id: {fc.field_name: fc for fc in spec.field_contracts}
    for inv_id, spec in DATASET_SPECS.items()
}

_ALL_FIELD_CONTRACTS: dict[str, tuple[str, FieldContract]] = {
    fc.field_name: (inv_id, fc)
    for inv_id, spec in DATASET_SPECS.items()
    for fc in spec.field_contracts
}

_EXCLUDED_STATUS_KEYS: tuple[MeasurementStatus, ...] = tuple(
    status for status in MeasurementStatus if status != MeasurementStatus.MEASURED
)

COMPARISON_BOUNDARY_NOTE = (
    "Koşul ve ölçüm karşılaştırmasıdır; çalışmalar arası güvenlik sıralaması, "
    "risk skoru veya nedensellik iddiası üretmez."
)


@dataclass(frozen=True)
class NumericRangeFilter:
    """Açık alan adı, açık birim ve kapsayıcılık sınırlarıyla sayısal aralık filtresi."""

    field_name: str
    unit: str
    min_value: float | None = None
    max_value: float | None = None
    min_inclusive: bool = True
    max_inclusive: bool = True


@dataclass(frozen=True)
class QueryResult:
    """Deterministik filtreleme sonucu; tekrarları korur ve tam kanıt izini taşır."""

    records: tuple[ExperimentRecord, ...]
    total_runs: int
    unique_sample_count: int | None
    unique_flex_identifier_count: int | None
    counts_by_investigation: dict[str, int]
    warnings: tuple[str, ...]
    applied_filters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """JSON uyumlu deterministik sözlük gösterimi üretir."""
        return {
            "total_runs": self.total_runs,
            "unique_sample_count": self.unique_sample_count,
            "unique_flex_identifier_count": self.unique_flex_identifier_count,
            "counts_by_investigation": dict(self.counts_by_investigation),
            "warnings": list(self.warnings),
            "applied_filters": dict(self.applied_filters),
            "records": [_serialize_record_summary(rec) for rec in self.records],
        }


@dataclass(frozen=True)
class FieldSummary:
    """Tek çalışma içi sayısal alan özeti; boş veya dışlanmış kümede ortalamayı 0 yapmaz."""

    investigation_id: str
    field_name: str
    unit: str
    candidate_run_count: int
    unique_sample_count: int | None
    unique_flex_identifier_count: int | None
    used_measured_count: int
    used_approximate_count: int
    used_total_count: int
    excluded_by_status: dict[str, int]
    mean_value: float | None
    min_value: float | None
    max_value: float | None
    warnings: tuple[str, ...]
    used_record_pks: tuple[str, ...]
    provenance: str | None

    def to_dict(self) -> dict[str, Any]:
        """JSON uyumlu deterministik özet sözlüğü üretir."""
        return {
            "investigation_id": self.investigation_id,
            "field_name": self.field_name,
            "unit": self.unit,
            "candidate_run_count": self.candidate_run_count,
            "unique_sample_count": self.unique_sample_count,
            "unique_flex_identifier_count": self.unique_flex_identifier_count,
            "used_measured_count": self.used_measured_count,
            "used_approximate_count": self.used_approximate_count,
            "used_total_count": self.used_total_count,
            "excluded_by_status": dict(self.excluded_by_status),
            "mean_value": self.mean_value,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "warnings": list(self.warnings),
            "used_record_pks": list(self.used_record_pks),
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class ComparisonResult:
    """Seçili record_pk kayıtları için kaynak izli yan yana karşılaştırma çıktısı."""

    requested_record_pks: tuple[str, ...]
    field_names: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]
    boundary_note: str = COMPARISON_BOUNDARY_NOTE

    def to_dict(self) -> dict[str, Any]:
        """JSON uyumlu deterministik karşılaştırma sözlüğü üretir."""
        return {
            "requested_record_pks": list(self.requested_record_pks),
            "field_names": list(self.field_names),
            "warnings": list(self.warnings),
            "boundary_note": self.boundary_note,
            "rows": [dict(row) for row in self.rows],
        }


def get_allowed_fields(investigation_id: str | None = None) -> tuple[str, ...]:
    """İzinli ölçüm alanlarını deterministik sırayla döndürür."""
    if investigation_id is not None:
        _validate_investigation_id(investigation_id)
        return tuple(_CONTRACTS_BY_INVESTIGATION[investigation_id].keys())
    return tuple(_ALL_FIELD_CONTRACTS.keys())


def get_allowed_units(field_name: str, investigation_id: str | None = None) -> tuple[str, ...]:
    """Bir ölçüm alanı için izin verilen açık birim listesini döndürür."""
    _, contract = _resolve_contract(field_name, investigation_id)
    units: list[str] = []
    for candidate in (contract.normalized_unit, contract.source_unit, contract.extra_unit):
        if candidate is not None and candidate not in units:
            units.append(candidate)
    return tuple(units)


def _validate_investigation_id(investigation_id: str) -> None:
    if not isinstance(investigation_id, str) or investigation_id not in DATASET_SPECS:
        valid = ", ".join(sorted(DATASET_SPECS))
        raise QueryValidationError(
            f"Bilinmeyen veya geçersiz investigation_id: {investigation_id!r}. İzin verilenler: {valid}."
        )


def _resolve_contract(
    field_name: str,
    investigation_id: str | None = None,
) -> tuple[str, FieldContract]:
    if not isinstance(field_name, str) or field_name not in _ALL_FIELD_CONTRACTS:
        allowed = ", ".join(_ALL_FIELD_CONTRACTS)
        raise QueryValidationError(
            f"İzin listesinde olmayan ölçüm alanı: {field_name!r}. İzin verilen alanlar: {allowed}."
        )
    owner_inv_id, contract = _ALL_FIELD_CONTRACTS[field_name]
    if investigation_id is not None:
        _validate_investigation_id(investigation_id)
        if owner_inv_id != investigation_id:
            raise QueryValidationError(
                f"{field_name!r} alanı {owner_inv_id} çalışmasına aittir; {investigation_id} ile kullanılamaz."
            )
    return owner_inv_id, contract


def _validate_numeric_bound(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QueryValidationError(f"{label} geçerli sonlu bir sayı olmalıdır; alınan: {value!r}.")
    num = float(value)
    if not math.isfinite(num):
        raise QueryValidationError(f"{label} sonlu olmalıdır (NaN/Inf kabul edilmez); alınan: {value!r}.")
    return num


def _validate_unit_for_numeric_query(
    contract: FieldContract,
    unit: str,
) -> None:
    if contract.uncalibrated:
        raise QueryValidationError(
            f"{contract.field_name!r} kalibresiz ayar alanıdır; sayısal filtre veya istatistik özetinde kullanılamaz."
        )
    if not isinstance(unit, str) or not unit:
        raise QueryValidationError(f"{contract.field_name!r} için açık bir birim (unit) verilmelidir.")
    allowed_units = get_allowed_units(contract.field_name)
    if unit not in allowed_units:
        raise QueryValidationError(
            f"{contract.field_name!r} alanı için geçersiz birim {unit!r}. İzin verilen birimler: {allowed_units}."
        )


def _validate_range_filter(
    rng: NumericRangeFilter,
    investigation_id: str | None,
) -> tuple[str, FieldContract]:
    if not isinstance(rng, NumericRangeFilter):
        raise QueryValidationError(f"NumericRangeFilter bekleniyordu; alınan: {type(rng).__name__}.")
    owner_inv_id, contract = _resolve_contract(rng.field_name, investigation_id)
    _validate_unit_for_numeric_query(contract, rng.unit)
    if rng.min_value is None and rng.max_value is None:
        raise QueryValidationError(
            f"{rng.field_name!r} filtresinde min_value veya max_value alanlarından en az biri verilmelidir."
        )
    min_val = _validate_numeric_bound(rng.min_value, "min_value") if rng.min_value is not None else None
    max_val = _validate_numeric_bound(rng.max_value, "max_value") if rng.max_value is not None else None
    if min_val is not None and max_val is not None:
        if min_val > max_val:
            raise QueryValidationError(
                f"{rng.field_name!r} filtresinde min_value ({min_val}) max_value ({max_val}) değerinden büyük olamaz."
            )
        if min_val == max_val and not (rng.min_inclusive and rng.max_inclusive):
            raise QueryValidationError(
                f"{rng.field_name!r} filtresinde min_value == max_value iken her iki sınır kapsayıcı olmalıdır."
            )
    return owner_inv_id, contract


def _extract_value_in_unit(
    measurement: TypedMeasurement,
    contract: FieldContract,
    unit: str,
) -> float | None:
    if unit == contract.normalized_unit:
        return measurement.normalized_value
    if unit == contract.source_unit:
        return measurement.parsed_value
    if contract.extra_unit is not None and unit == contract.extra_unit:
        conv = measurement.extra_conversions.get(contract.extra_unit)
        if conv is not None:
            raw = conv.get("value")
            return float(raw) if raw is not None else None
    return None


def _sort_records(records: Sequence[ExperimentRecord]) -> tuple[ExperimentRecord, ...]:
    return tuple(
        sorted(
            records,
            key=lambda r: (r.investigation_id, r.source.csv_record_index, r.record_pk),
        )
    )


def _matches_numeric_filter(
    record: ExperimentRecord,
    rng: NumericRangeFilter,
    contract: FieldContract,
    include_approximate: bool,
) -> bool:
    measurement = record.measurements.get(rng.field_name)
    if measurement is None:
        return False
    allowed_statuses = (
        (MeasurementStatus.MEASURED, MeasurementStatus.APPROXIMATE)
        if include_approximate
        else (MeasurementStatus.MEASURED,)
    )
    if measurement.status not in allowed_statuses:
        return False
    val = _extract_value_in_unit(measurement, contract, rng.unit)
    if val is None or not math.isfinite(val):
        return False
    if rng.min_value is not None:
        if rng.min_inclusive:
            if not (val >= rng.min_value):
                return False
        elif not (val > rng.min_value):
            return False
    if rng.max_value is not None:
        if rng.max_inclusive:
            if not (val <= rng.max_value):
                return False
        elif not (val < rng.max_value):
            return False
    return True


def _normalize_text_token(value: str, param_name: str) -> str:
    if not isinstance(value, str):
        raise QueryValidationError(f"{param_name} metin olmalıdır; alınan: {type(value).__name__}.")
    norm = normalize_fuel_label(value)
    if not norm:
        raise QueryValidationError(f"{param_name} boş metin olamaz; filtre uygulanmayacaksa None verin.")
    return norm


def _serialize_measurement(m: TypedMeasurement) -> dict[str, Any]:
    return {
        "field_name": m.field_name,
        "raw_header": m.raw_header,
        "raw_value": m.raw_value,
        "parsed_value": m.parsed_value,
        "source_unit": m.source_unit,
        "normalized_value": m.normalized_value,
        "normalized_unit": m.normalized_unit,
        "status": m.status.value,
        "source_lower_bound": m.source_lower_bound,
        "source_upper_bound": m.source_upper_bound,
        "normalized_lower_bound": m.normalized_lower_bound,
        "normalized_upper_bound": m.normalized_upper_bound,
        "lower_bound_inclusive": m.lower_bound_inclusive,
        "upper_bound_inclusive": m.upper_bound_inclusive,
        "quality_flags": list(m.quality_flags),
        "provenance": m.provenance,
        "error_reason": m.error_reason,
        "extra_conversions": dict(m.extra_conversions),
    }


def _serialize_source(rec: ExperimentRecord) -> dict[str, Any]:
    return {
        "source_relpath": rec.source.source_relpath,
        "source_sha256": rec.source.source_sha256,
        "encoding": rec.source.encoding,
        "csv_record_index": rec.source.csv_record_index,
        "physical_line_start": rec.source.physical_line_start,
        "physical_line_end": rec.source.physical_line_end,
        "position_definition": rec.source.position_definition,
    }


def _serialize_record_summary(rec: ExperimentRecord) -> dict[str, Any]:
    return {
        "record_pk": rec.record_pk,
        "investigation_id": rec.investigation_id,
        "test_id": rec.test_id,
        "sample_id": rec.sample_id,
        "flex_identifier": rec.flex_identifier,
        "fuel_raw": rec.normalized_fields.get("fuel_raw"),
        "fuel_norm": rec.normalized_fields.get("fuel_norm"),
        "test_date": rec.normalized_fields.get("test_date"),
        "test_gmt": rec.normalized_fields.get("test_gmt"),
        "test_end": rec.normalized_fields.get("test_end"),
        "is_repeat_sample": rec.normalized_fields.get("is_repeat_sample"),
        "sample_run_count": rec.normalized_fields.get("sample_run_count"),
        "is_repeat_flex_identifier": rec.normalized_fields.get("is_repeat_flex_identifier"),
        "flex_identifier_count": rec.normalized_fields.get("flex_identifier_count"),
        "quality_flags": list(rec.quality_flags),
        "source": _serialize_source(rec),
    }


def filter_records(
    records: Sequence[ExperimentRecord],
    *,
    investigation_id: str | None = None,
    fuel: str | None = None,
    test_end: str | None = None,
    numeric_filters: Sequence[NumericRangeFilter] = (),
    include_approximate: bool = False,
) -> QueryResult:
    """Çalışma kimliği, tam yakıt adı, FLEX Test end ve sayısal aralıklarla deterministik filtreleme yapar."""
    if investigation_id is not None:
        _validate_investigation_id(investigation_id)

    norm_fuel_cf = _normalize_text_token(fuel, "fuel").casefold() if fuel is not None else None
    norm_test_end_cf = _normalize_text_token(test_end, "test_end").casefold() if test_end is not None else None

    if norm_test_end_cf is not None and investigation_id == "PSI-25":
        raise QueryValidationError("test_end alanı yalnızca PSI-69 (FLEX) içinde bulunur; PSI-25 ile kullanılamaz.")

    validated_filters: list[tuple[NumericRangeFilter, FieldContract]] = []
    filter_owners: set[str] = set()
    if norm_test_end_cf is not None:
        filter_owners.add("PSI-69")
    for rng in numeric_filters:
        owner_inv_id, contract = _validate_range_filter(rng, investigation_id)
        filter_owners.add(owner_inv_id)
        validated_filters.append((rng, contract))

    if len(filter_owners) > 1:
        raise QueryValidationError(
            "Tek sorguda farklı çalışmaların sayısal filtreleri birleştirilemez: "
            "Tek sorguda farklı çalışmaların filtreleri birleştirilemez (örn. PSI-69 test_end ile PSI-25 sayısal alanları): "
            + ", ".join(sorted(filter_owners))
        )

    matched: list[ExperimentRecord] = []
    used_approximate_match = False
    for rec in _sort_records(records):
        if investigation_id is not None and rec.investigation_id != investigation_id:
            continue
        if norm_fuel_cf is not None:
            rec_fuel = rec.normalized_fields.get("fuel_norm", "")
            if str(rec_fuel).casefold() != norm_fuel_cf:
                continue
        if norm_test_end_cf is not None:
            rec_test_end = rec.normalized_fields.get("test_end")
            if rec_test_end is None or normalize_fuel_label(str(rec_test_end)).casefold() != norm_test_end_cf:
                continue
        if any(not _matches_numeric_filter(rec, rng, contract, include_approximate) for rng, contract in validated_filters):
            continue
        if include_approximate and validated_filters:
            for rng, _ in validated_filters:
                m = rec.measurements.get(rng.field_name)
                if m is not None and m.status == MeasurementStatus.APPROXIMATE:
                    used_approximate_match = True
        matched.append(rec)

    matched_tuple = tuple(matched)
    inv_counts = dict(sorted(Counter(r.investigation_id for r in matched_tuple).items()))

    psi25_samples = {
        r.sample_id
        for r in matched_tuple
        if r.investigation_id == "PSI-25" and r.sample_id is not None
    }
    has_psi25 = investigation_id == "PSI-25" or any(r.investigation_id == "PSI-25" for r in matched_tuple)
    unique_sample_count = len(psi25_samples) if has_psi25 else None

    psi69_flex = {
        r.flex_identifier
        for r in matched_tuple
        if r.investigation_id == "PSI-69" and r.flex_identifier is not None
    }
    has_psi69 = investigation_id == "PSI-69" or any(r.investigation_id == "PSI-69" for r in matched_tuple)
    unique_flex_count = len(psi69_flex) if has_psi69 else None

    warnings: list[str] = []
    if include_approximate:
        detail = (
            "Eşleşen kayıtlarda yaklaşık (~) değerler kullanıldı."
            if used_approximate_match
            else "Yaklaşık (~) değerler açık opt-in ile sorguya dahil edilebilir durumda."
        )
        warnings.append(f"approximate_included: {detail}")

    return QueryResult(
        records=matched_tuple,
        total_runs=len(matched_tuple),
        unique_sample_count=unique_sample_count,
        unique_flex_identifier_count=unique_flex_count,
        counts_by_investigation=inv_counts,
        warnings=tuple(warnings),
        applied_filters={
            "investigation_id": investigation_id,
            "fuel": fuel,
            "test_end": test_end,
            "include_approximate": include_approximate,
            "numeric_filters": [
                {
                    "field_name": rng.field_name,
                    "unit": rng.unit,
                    "min_value": rng.min_value,
                    "max_value": rng.max_value,
                    "min_inclusive": rng.min_inclusive,
                    "max_inclusive": rng.max_inclusive,
                }
                for rng, _ in validated_filters
            ],
        },
    )


def summarize_field(
    records: Sequence[ExperimentRecord],
    *,
    investigation_id: str,
    field_name: str,
    unit: str,
    include_approximate: bool = False,
) -> FieldSummary:
    """Tek çalışma içinde deterministik sayısal özet üretir; dışlanan durum sayılarını ayrı raporlar."""
    _validate_investigation_id(investigation_id)
    _, contract = _resolve_contract(field_name, investigation_id)
    _validate_unit_for_numeric_query(contract, unit)

    candidates = _sort_records([r for r in records if r.investigation_id == investigation_id])
    excluded_counts: Counter[str] = Counter()
    used_values: list[float] = []
    used_record_pks: list[str] = []
    used_measured_count = 0
    used_approximate_count = 0

    for rec in candidates:
        measurement = rec.measurements.get(field_name)
        if measurement is None:
            excluded_counts[MeasurementStatus.MISSING.value] += 1
            continue
        if measurement.status == MeasurementStatus.MEASURED:
            val = _extract_value_in_unit(measurement, contract, unit)
            if val is not None and math.isfinite(val):
                used_values.append(val)
                used_record_pks.append(rec.record_pk)
                used_measured_count += 1
            else:
                excluded_counts[MeasurementStatus.INVALID.value] += 1
        elif measurement.status == MeasurementStatus.APPROXIMATE:
            if include_approximate:
                val = _extract_value_in_unit(measurement, contract, unit)
                if val is not None and math.isfinite(val):
                    used_values.append(val)
                    used_record_pks.append(rec.record_pk)
                    used_approximate_count += 1
                else:
                    excluded_counts[MeasurementStatus.INVALID.value] += 1
            else:
                excluded_counts[MeasurementStatus.APPROXIMATE.value] += 1
        else:
            excluded_counts[measurement.status.value] += 1

    ordered_excluded = {status.value: excluded_counts.get(status.value, 0) for status in _EXCLUDED_STATUS_KEYS}

    used_total = len(used_values)
    if used_total == 0:
        mean_val: float | None = None
        min_val: float | None = None
        max_val: float | None = None
    else:
        mean_val = math.fsum(used_values) / used_total
        if not math.isfinite(mean_val):
            raise QueryValidationError(f"{field_name!r} için ortalama hesabı sonlu değil (taşma).")
        min_val = min(used_values)
        max_val = max(used_values)

    warnings: list[str] = []
    if include_approximate:
        warnings.append(
            f"approximate_included: Yaklaşık (~) değerler açık opt-in ile özete dahil edildi (adet={used_approximate_count})."
        )
    censored_total = ordered_excluded["above_limit"] + ordered_excluded["below_limit"]
    if censored_total > 0:
        warnings.append(
            f"censored_excluded: {censored_total} adet sınır-aşımlı (< / > / OR) ölçüm ortalama/min/max hesabının dışında bırakıldı."
        )

    unique_sample_count = (
        len({r.sample_id for r in candidates if r.sample_id is not None})
        if investigation_id == "PSI-25"
        else None
    )
    unique_flex_count = (
        len({r.flex_identifier for r in candidates if r.flex_identifier is not None})
        if investigation_id == "PSI-69"
        else None
    )

    return FieldSummary(
        investigation_id=investigation_id,
        field_name=field_name,
        unit=unit,
        candidate_run_count=len(candidates),
        unique_sample_count=unique_sample_count,
        unique_flex_identifier_count=unique_flex_count,
        used_measured_count=used_measured_count,
        used_approximate_count=used_approximate_count,
        used_total_count=used_total,
        excluded_by_status=ordered_excluded,
        mean_value=mean_val,
        min_value=min_val,
        max_value=max_val,
        warnings=tuple(warnings),
        used_record_pks=tuple(used_record_pks),
        provenance=contract.provenance,
    )


def compare_records(
    records: Sequence[ExperimentRecord],
    *,
    record_pks: Sequence[str],
    field_names: Sequence[str],
) -> ComparisonResult:
    """Seçili record_pk kayıtlarını tam kaynak izi ve birimleriyle yan yana karşılaştırır."""
    if not record_pks:
        raise QueryValidationError("compare_records için en az bir record_pk verilmelidir.")
    if not field_names:
        raise QueryValidationError("compare_records için en az bir ölçüm alanı (field_names) verilmelidir.")

    seen_pks: set[str] = set()
    ordered_unique_pks: list[str] = []
    for pk in record_pks:
        if not isinstance(pk, str) or not pk.strip():
            raise QueryValidationError(f"Geçersiz record_pk değeri: {pk!r}.")
        if pk not in seen_pks:
            seen_pks.add(pk)
            ordered_unique_pks.append(pk)

    validated_fields: list[str] = []
    seen_fields: set[str] = set()
    for fname in field_names:
        _resolve_contract(fname)
        if fname not in seen_fields:
            seen_fields.add(fname)
            validated_fields.append(fname)

    by_pk = {rec.record_pk: rec for rec in records}
    missing_pks = [pk for pk in ordered_unique_pks if pk not in by_pk]
    if missing_pks:
        raise QueryValidationError(f"Karşılaştırma için istenen record_pk bulunamadı: {missing_pks}.")

    selected_records = _sort_records([by_pk[pk] for pk in ordered_unique_pks])
    investigations_present = sorted({rec.investigation_id for rec in selected_records})

    rows: list[dict[str, Any]] = []
    for rec in selected_records:
        measurements_payload: dict[str, Any] = {}
        for fname in validated_fields:
            m = rec.measurements.get(fname)
            if m is None:
                owner_inv_id, contract = _resolve_contract(fname)
                measurements_payload[fname] = {
                    "field_name": fname,
                    "status": "not_applicable",
                    "raw_header": contract.raw_header,
                    "raw_value": None,
                    "parsed_value": None,
                    "source_unit": contract.source_unit,
                    "normalized_value": None,
                    "normalized_unit": contract.normalized_unit,
                    "note": f"Bu alan {owner_inv_id} çalışmasına aittir; {rec.investigation_id} kaydında yoktur.",
                }
            else:
                measurements_payload[fname] = _serialize_measurement(m)

        row = _serialize_record_summary(rec)
        row["measurements"] = measurements_payload
        rows.append(row)

    warnings: list[str] = []
    if len(investigations_present) > 1:
        warnings.append(
            "cross_study_units_preserved: Farklı çalışmalardan kayıtlar yan yana gösteriliyor "
            "(örn. PSI-25 % vol ile PSI-69 % mol birleştirilmez)."
        )

    return ComparisonResult(
        requested_record_pks=tuple(ordered_unique_pks),
        field_names=tuple(validated_fields),
        rows=tuple(rows),
        warnings=tuple(warnings),
    )
