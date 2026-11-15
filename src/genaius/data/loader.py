"""Sözleşme uyumlu CSV yükleyici, token ayrıştırıcı ve birim dönüştürücü."""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .contracts import (
    DATASET_SPECS,
    DatasetSpec,
    ExperimentRecord,
    FieldContract,
    MeasurementStatus,
    SourceLocation,
    TypedMeasurement,
)

_MISSING_TOKENS = {"", "none", "-", "–", "—"}
_FLOAT_BODY = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_NUMBER_RE = re.compile(rf"^{_FLOAT_BODY}$")
_APPROX_RE = re.compile(rf"^~\s*({_FLOAT_BODY})$")
_GT_RE = re.compile(rf"^>\s*({_FLOAT_BODY})$")
_LT_RE = re.compile(rf"^<\s*({_FLOAT_BODY})$")


class DataContractError(ValueError):
    """Veri sözleşmesi doğrulama hatası taban sınıfı."""


class EncodingValidationError(DataContractError):
    """Kaynak dosya beklenen karakter kodlamasıyla çözülemediğinde fırlatılır."""


class SchemaMismatchError(DataContractError):
    """Zorunlu başlıklar eksik veya kimlik alanları geçersiz olduğunda fırlatılır."""


def compute_sha256(path: Path) -> str:
    """Dosyanın tam SHA-256 özetini küçük harfli hex olarak hesaplar."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def normalize_fuel_label(raw_fuel: str) -> str:
    """Yakıt metnini gereksiz iç boşlukları toparlayarak normalize eder; ham metni silmez."""
    return " ".join(raw_fuel.split())


def _invalid_non_finite(raw_value: str, contract: FieldContract) -> TypedMeasurement:
    return TypedMeasurement(
        field_name=contract.field_name,
        raw_header=contract.raw_header,
        raw_value=raw_value,
        parsed_value=None,
        source_unit=contract.source_unit,
        normalized_value=None,
        normalized_unit=contract.normalized_unit,
        status=MeasurementStatus.INVALID,
        quality_flags=("non_finite_or_overflow",),
        provenance=contract.provenance,
        error_reason=f"Sonlu olmayan sayı veya birim dönüşüm taşması: {raw_value!r}",
    )


def _invalid_negative(raw_value: str, contract: FieldContract) -> TypedMeasurement:
    flags = ["negative_reading"]
    if contract.negative_reason_flag:
        flags.append(contract.negative_reason_flag)
    return TypedMeasurement(
        field_name=contract.field_name,
        raw_header=contract.raw_header,
        raw_value=raw_value,
        parsed_value=None,
        source_unit=contract.source_unit,
        normalized_value=None,
        normalized_unit=contract.normalized_unit,
        status=MeasurementStatus.INVALID,
        quality_flags=tuple(flags),
        provenance=contract.provenance,
        error_reason="Negatif ölçüm; nedeni doğrulanmadı.",
    )


def _validate_and_convert_scalar(
    num_str: str,
    raw_value: str,
    contract: FieldContract,
) -> tuple[float, float | None, dict[str, dict[str, Any]]] | TypedMeasurement:
    """Normal, yaklaşık ve sınır tokenleri için ortak sonluluk, negatiflik ve dönüşüm kontrolü."""
    val = float(num_str)
    if not math.isfinite(val):
        return _invalid_non_finite(raw_value, contract)
    if val < 0 and not contract.allow_negative:
        return _invalid_negative(raw_value, contract)
    norm_val, extra = _convert_numeric(val, contract)
    if contract.scale_factor is not None and (norm_val is None or not math.isfinite(norm_val)):
        return _invalid_non_finite(raw_value, contract)
    for conv in extra.values():
        if not math.isfinite(conv["value"]):
            return _invalid_non_finite(raw_value, contract)
    return val, norm_val, extra


def parse_measurement_value(raw_value: str, contract: FieldContract) -> TypedMeasurement:
    """Ham hücre metnini sözleşmedeki yedi durumdan birine ve tipli yapıya dönüştürür."""
    text = raw_value.strip()
    lower = text.lower()

    if contract.uncalibrated:
        if lower in _MISSING_TOKENS:
            return TypedMeasurement(
                field_name=contract.field_name,
                raw_header=contract.raw_header,
                raw_value=raw_value,
                parsed_value=None,
                source_unit=contract.source_unit,
                normalized_value=None,
                normalized_unit=contract.normalized_unit,
                status=MeasurementStatus.MISSING,
                quality_flags=("uncalibrated_setting",),
                provenance=contract.provenance,
            )
        return TypedMeasurement(
            field_name=contract.field_name,
            raw_header=contract.raw_header,
            raw_value=raw_value,
            parsed_value=None,
            source_unit=contract.source_unit,
            normalized_value=None,
            normalized_unit=contract.normalized_unit,
            status=MeasurementStatus.MEANING_UNVERIFIED,
            quality_flags=("uncalibrated_no_physical_conversion",),
            provenance=contract.provenance,
        )

    if lower in _MISSING_TOKENS:
        return TypedMeasurement(
            field_name=contract.field_name,
            raw_header=contract.raw_header,
            raw_value=raw_value,
            parsed_value=None,
            source_unit=contract.source_unit,
            normalized_value=None,
            normalized_unit=contract.normalized_unit,
            status=MeasurementStatus.MISSING,
            provenance=contract.provenance,
        )

    if lower == "or":
        if contract.or_lower_bound is not None:
            norm_bound, extra = _convert_numeric(contract.or_lower_bound, contract)
            if contract.scale_factor is not None and norm_bound is None:
                return _invalid_non_finite(raw_value, contract)
            return TypedMeasurement(
                field_name=contract.field_name,
                raw_header=contract.raw_header,
                raw_value=raw_value,
                parsed_value=None,
                source_unit=contract.source_unit,
                normalized_value=None,
                normalized_unit=contract.normalized_unit,
                status=MeasurementStatus.ABOVE_LIMIT,
                source_lower_bound=contract.or_lower_bound,
                normalized_lower_bound=norm_bound,
                lower_bound_inclusive=False,
                quality_flags=("over_range_token",),
                provenance=contract.provenance,
                extra_conversions=extra,
            )
        return TypedMeasurement(
            field_name=contract.field_name,
            raw_header=contract.raw_header,
            raw_value=raw_value,
            parsed_value=None,
            source_unit=contract.source_unit,
            normalized_value=None,
            normalized_unit=contract.normalized_unit,
            status=MeasurementStatus.INVALID,
            quality_flags=("unrecognized_token",),
            provenance=contract.provenance,
            error_reason=f"OR tokeni {contract.field_name} alanı için sözleşmede tanımlı değil.",
        )

    if lower == "over":
        return TypedMeasurement(
            field_name=contract.field_name,
            raw_header=contract.raw_header,
            raw_value=raw_value,
            parsed_value=None,
            source_unit=contract.source_unit,
            normalized_value=None,
            normalized_unit=contract.normalized_unit,
            status=MeasurementStatus.ABOVE_LIMIT,
            source_lower_bound=None,
            normalized_lower_bound=None,
            lower_bound_inclusive=False,
            quality_flags=("above_limit_unknown_bound",),
            provenance=contract.provenance,
        )

    if m_gt := _GT_RE.match(text):
        res = _validate_and_convert_scalar(m_gt.group(1), raw_value, contract)
        if isinstance(res, TypedMeasurement):
            return res
        bound, norm_bound, extra = res
        return TypedMeasurement(
            field_name=contract.field_name,
            raw_header=contract.raw_header,
            raw_value=raw_value,
            parsed_value=None,
            source_unit=contract.source_unit,
            normalized_value=None,
            normalized_unit=contract.normalized_unit,
            status=MeasurementStatus.ABOVE_LIMIT,
            source_lower_bound=bound,
            normalized_lower_bound=norm_bound,
            lower_bound_inclusive=False,
            quality_flags=("censored_above_limit",),
            provenance=contract.provenance,
            extra_conversions=extra,
        )

    if m_lt := _LT_RE.match(text):
        res = _validate_and_convert_scalar(m_lt.group(1), raw_value, contract)
        if isinstance(res, TypedMeasurement):
            return res
        bound, norm_bound, extra = res
        return TypedMeasurement(
            field_name=contract.field_name,
            raw_header=contract.raw_header,
            raw_value=raw_value,
            parsed_value=None,
            source_unit=contract.source_unit,
            normalized_value=None,
            normalized_unit=contract.normalized_unit,
            status=MeasurementStatus.BELOW_LIMIT,
            source_upper_bound=bound,
            normalized_upper_bound=norm_bound,
            upper_bound_inclusive=False,
            quality_flags=("censored_below_limit",),
            provenance=contract.provenance,
            extra_conversions=extra,
        )

    if m_approx := _APPROX_RE.match(text):
        res = _validate_and_convert_scalar(m_approx.group(1), raw_value, contract)
        if isinstance(res, TypedMeasurement):
            return res
        val, norm_val, extra = res
        return TypedMeasurement(
            field_name=contract.field_name,
            raw_header=contract.raw_header,
            raw_value=raw_value,
            parsed_value=val,
            source_unit=contract.source_unit,
            normalized_value=norm_val,
            normalized_unit=contract.normalized_unit,
            status=MeasurementStatus.APPROXIMATE,
            quality_flags=("approximate_prefix",),
            provenance=contract.provenance,
            extra_conversions=extra,
        )

    if _NUMBER_RE.match(text):
        res = _validate_and_convert_scalar(text, raw_value, contract)
        if isinstance(res, TypedMeasurement):
            return res
        val, norm_val, extra = res
        return TypedMeasurement(
            field_name=contract.field_name,
            raw_header=contract.raw_header,
            raw_value=raw_value,
            parsed_value=val,
            source_unit=contract.source_unit,
            normalized_value=norm_val,
            normalized_unit=contract.normalized_unit,
            status=MeasurementStatus.MEASURED,
            provenance=contract.provenance,
            extra_conversions=extra,
        )

    return TypedMeasurement(
        field_name=contract.field_name,
        raw_header=contract.raw_header,
        raw_value=raw_value,
        parsed_value=None,
        source_unit=contract.source_unit,
        normalized_value=None,
        normalized_unit=contract.normalized_unit,
        status=MeasurementStatus.INVALID,
        quality_flags=("unrecognized_token",),
        provenance=contract.provenance,
        error_reason=f"Tanınmayan sayısal token: {raw_value!r}",
    )


def _convert_numeric(
    val: float, contract: FieldContract
) -> tuple[float | None, dict[str, dict[str, Any]]]:
    if contract.scale_factor is None:
        return None, {}
    scaled = val * contract.scale_factor
    if not math.isfinite(scaled):
        return None, {}
    norm_val = round(scaled, 10)
    extra: dict[str, dict[str, Any]] = {}
    if contract.extra_unit and contract.extra_scale_factor is not None:
        extra_scaled = val * contract.extra_scale_factor
        if not math.isfinite(extra_scaled):
            return None, {}
        extra[contract.extra_unit] = {
            "value": round(extra_scaled, 10),
            "unit": contract.extra_unit,
            "scale_factor": contract.extra_scale_factor,
        }
    return norm_val, extra


def _decode_strict(raw_bytes: bytes, encoding: str, path: Path) -> str:
    try:
        return raw_bytes.decode(encoding, errors="strict")
    except UnicodeDecodeError as exc:
        raise EncodingValidationError(
            f"{path} dosyası {encoding} kodlaması ile çözülemedi (bayt konumu {exc.start}..{exc.end}): {exc.reason}"
        ) from exc


def _validate_headers(header: list[str], spec: DatasetSpec, path: Path) -> list[str]:
    required = list(spec.header_aliases.keys())
    header_set = set(header)
    missing = [col for col in required if col not in header_set]
    if missing:
        raise SchemaMismatchError(
            f"{spec.investigation_id} ({path}) zorunlu başlıkları eksik: {missing}"
        )
    dupes = [col for col, cnt in Counter(header).items() if cnt > 1]
    if dupes:
        raise SchemaMismatchError(
            f"{spec.investigation_id} ({path}) yinelenen başlık içeriyor: {dupes}"
        )
    return [col for col in header if col not in spec.header_aliases]


def load_investigation_records(
    investigation_id: str,
    repo_root: str | Path = ".",
    spec_override: DatasetSpec | None = None,
) -> tuple[list[ExperimentRecord], dict[str, Any]]:
    """Tek bir PSI deney tablosunu sözleşmeye göre doğrular ve yükler."""
    spec = spec_override or DATASET_SPECS[investigation_id]
    root = Path(repo_root).resolve()
    csv_path = (root / spec.relative_path).resolve()
    if not csv_path.exists():
        raise FileNotFoundError(f"{spec.investigation_id} kaynak CSV bulunamadı: {csv_path}")

    raw_bytes = csv_path.read_bytes()
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    text = _decode_strict(raw_bytes, spec.encoding, csv_path)

    stream = io.StringIO(text, newline="")
    reader = csv.reader(stream)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise SchemaMismatchError(f"{spec.investigation_id} ({csv_path}) boş dosya.") from exc

    unexpected_headers = _validate_headers(header, spec, csv_path)
    contracts_by_raw = {c.raw_header: c for c in spec.field_contracts}

    records: list[ExperimentRecord] = []
    seen_pks: dict[str, int] = {}
    csv_record_index = 0

    while True:
        prev_phys_end = reader.line_num
        try:
            row = next(reader)
        except StopIteration:
            break
        phys_start = prev_phys_end + 1
        phys_end = reader.line_num
        csv_record_index += 1

        if len(row) != len(header):
            raise SchemaMismatchError(
                f"{spec.investigation_id} kayıt #{csv_record_index} (fiziksel satır {phys_start}..{phys_end}) "
                f"sütun sayısı uyuşmuyor: beklenen {len(header)}, okunan {len(row)}."
            )

        raw_fields = dict(zip(header, row))
        test_id = raw_fields[spec.primary_test_header].strip()
        if not test_id:
            raise SchemaMismatchError(
                f"{spec.investigation_id} kayıt #{csv_record_index} (satır {phys_start}) boş kimlik."
            )
        record_pk = f"{spec.investigation_id}:{test_id}"
        if record_pk in seen_pks:
            raise SchemaMismatchError(
                f"Yinelenen birleşik anahtar {record_pk!r} (kayıt #{seen_pks[record_pk]} ve #{csv_record_index})."
            )
        seen_pks[record_pk] = csv_record_index

        sample_id = (
            raw_fields[spec.sample_header].strip()
            if spec.sample_header is not None
            else None
        )
        flex_id = (
            raw_fields[spec.flex_identifier_header].strip()
            if spec.flex_identifier_header is not None
            else None
        )

        measurements: dict[str, TypedMeasurement] = {}
        record_flags: list[str] = []
        for raw_col, contract in contracts_by_raw.items():
            m = parse_measurement_value(raw_fields[raw_col], contract)
            if (
                contract.field_name == "final_o2_vol_pct"
                and test_id == "B2"
                and m.status == MeasurementStatus.MEASURED
                and m.parsed_value == 1.6
            ):
                m = TypedMeasurement(
                    field_name=m.field_name,
                    raw_header=m.raw_header,
                    raw_value=m.raw_value,
                    parsed_value=m.parsed_value,
                    source_unit=m.source_unit,
                    normalized_value=m.normalized_value,
                    normalized_unit=m.normalized_unit,
                    status=m.status,
                    quality_flags=m.quality_flags + ("outlier_B2_low_final_o2",),
                    provenance=m.provenance,
                )
                record_flags.append("outlier_B2_low_final_o2")
            if (
                contract.field_name == "visible_flame_extinction_diameter_mm"
                and m.status == MeasurementStatus.MEASURED
                and raw_fields.get("Test end", "").strip() in ("Completion", "Disruption")
            ):
                record_flags.append("d_ext_present_with_non_extinction_end")
            measurements[contract.field_name] = m

        fuel_raw = raw_fields.get("Fuel Sample Material") or raw_fields.get("Fuel") or ""
        normalized_fields: dict[str, Any] = {
            "investigation_id": spec.investigation_id,
            "test_id": test_id,
            "sample_id": sample_id,
            "flex_identifier": flex_id,
            "fuel_raw": fuel_raw,
            "fuel_norm": normalize_fuel_label(fuel_raw),
            "test_date": (raw_fields.get("Date") or raw_fields.get("Test Date") or "").strip(),
            "test_gmt": (raw_fields.get("GMT") or raw_fields.get("Test GMT") or "").strip(),
        }
        if "PI" in raw_fields:
            normalized_fields["pi"] = raw_fields["PI"].strip()
        if "Total Frames Shot" in raw_fields:
            normalized_fields["total_frames_shot_raw"] = raw_fields["Total Frames Shot"].strip()
        if "Test end" in raw_fields:
            normalized_fields["test_end"] = raw_fields["Test end"].strip()

        source_loc = SourceLocation(
            source_relpath=spec.relative_path,
            source_sha256=sha256,
            encoding=spec.encoding,
            csv_record_index=csv_record_index,
            physical_line_start=phys_start,
            physical_line_end=phys_end,
        )
        records.append(
            ExperimentRecord(
                record_pk=record_pk,
                investigation_id=spec.investigation_id,
                test_id=test_id,
                sample_id=sample_id,
                flex_identifier=flex_id,
                source=source_loc,
                raw_fields=raw_fields,
                normalized_fields=normalized_fields,
                measurements=measurements,
                quality_flags=tuple(sorted(set(record_flags))),
            )
        )

    # Tekrarlanan Sample # ve FLEX Identifier işaretlerini ekle (tekrarları silmeden)
    sample_counts = Counter(r.sample_id for r in records if r.sample_id is not None)
    flex_counts = Counter(r.flex_identifier for r in records if r.flex_identifier is not None)
    enriched: list[ExperimentRecord] = []
    for rec in records:
        norm = dict(rec.normalized_fields)
        if rec.sample_id is not None:
            cnt = sample_counts[rec.sample_id]
            norm["sample_run_count"] = cnt
            norm["is_repeat_sample"] = cnt > 1
        if rec.flex_identifier is not None:
            cnt = flex_counts[rec.flex_identifier]
            norm["flex_identifier_count"] = cnt
            norm["is_repeat_flex_identifier"] = cnt > 1
        enriched.append(
            ExperimentRecord(
                record_pk=rec.record_pk,
                investigation_id=rec.investigation_id,
                test_id=rec.test_id,
                sample_id=rec.sample_id,
                flex_identifier=rec.flex_identifier,
                source=rec.source,
                raw_fields=rec.raw_fields,
                normalized_fields=norm,
                measurements=rec.measurements,
                quality_flags=rec.quality_flags,
            )
        )

    meta = {
        "investigation_id": spec.investigation_id,
        "experiment_name": spec.experiment_name,
        "relative_path": spec.relative_path,
        "encoding": spec.encoding,
        "file_bytes": len(raw_bytes),
        "sha256": sha256,
        "doi": spec.doi,
        "catalog_license": spec.catalog_license,
        "reports_license_note": spec.reports_license_note,
        "raw_headers": header,
        "unexpected_headers": unexpected_headers,
        "physical_line_count": len(text.splitlines()),
        "computed_run_count": len(enriched),
        "expected_run_count": spec.expected_run_count,
    }
    return enriched, meta


def load_core_datasets(
    repo_root: str | Path = ".",
) -> tuple[list[ExperimentRecord], dict[str, dict[str, Any]]]:
    """PSI-25 ve PSI-69 çekirdek deneylerinin ikisini birlikte yükler."""
    all_records: list[ExperimentRecord] = []
    metas: dict[str, dict[str, Any]] = {}
    for inv_id in ("PSI-25", "PSI-69"):
        recs, meta = load_investigation_records(inv_id, repo_root=repo_root)
        all_records.extend(recs)
        metas[inv_id] = meta
    return all_records, metas
