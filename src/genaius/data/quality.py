"""PSI-25 ve PSI-69 için çalıştırılabilir manifest ve kalite raporu üretici."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .contracts import ExperimentRecord, MeasurementStatus, POSITION_DEFINITION
from .loader import load_core_datasets


def _summarize_investigation(records: list[ExperimentRecord], meta: dict[str, Any]) -> dict[str, Any]:
    status_by_field: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    unrecognized_tokens: list[dict[str, Any]] = []
    negative_readings: list[dict[str, Any]] = []
    record_flag_counts: Counter[str] = Counter()
    measurement_flag_counts: Counter[str] = Counter()

    for rec in records:
        for fl in rec.quality_flags:
            record_flag_counts[fl] += 1
        for fname, m in rec.measurements.items():
            status_by_field[fname][m.status.value] += 1
            for fl in m.quality_flags:
                measurement_flag_counts[fl] += 1
            if "unrecognized_token" in m.quality_flags:
                unrecognized_tokens.append(
                    {
                        "record_pk": rec.record_pk,
                        "field_name": fname,
                        "raw_value": m.raw_value,
                        "error_reason": m.error_reason,
                        "physical_line_start": rec.source.physical_line_start,
                    }
                )
            if "negative_reading" in m.quality_flags:
                negative_readings.append(
                    {
                        "record_pk": rec.record_pk,
                        "field_name": fname,
                        "raw_value": m.raw_value,
                        "status": m.status.value,
                        "quality_flags": list(m.quality_flags),
                        "physical_line_start": rec.source.physical_line_start,
                    }
                )

    ordered_statuses = [s.value for s in MeasurementStatus]
    field_distributions = {
        fname: {st: cnts.get(st, 0) for st in ordered_statuses if cnts.get(st, 0) > 0}
        for fname, cnts in status_by_field.items()
    }

    sample_groups: dict[str, list[str]] = defaultdict(list)
    flex_id_groups: dict[str, list[str]] = defaultdict(list)
    for rec in records:
        if rec.sample_id is not None:
            sample_groups[rec.sample_id].append(rec.test_id)
        if rec.flex_identifier is not None:
            flex_id_groups[rec.flex_identifier].append(rec.test_id)

    repeated_samples = {
        sid: tests for sid, tests in sorted(sample_groups.items()) if len(tests) > 1
    }
    repeated_flex_ids = {
        fid: tests for fid, tests in sorted(flex_id_groups.items()) if len(tests) > 1
    }

    unique_samples = len(sample_groups) if sample_groups else None
    unique_pks = len({r.record_pk for r in records})

    return {
        "investigation_id": meta["investigation_id"],
        "source_relpath": meta["relative_path"],
        "sha256": meta["sha256"],
        "encoding": meta["encoding"],
        "file_bytes": meta["file_bytes"],
        "expected_vs_computed": {
            "run_count": {
                "expected": meta["expected_run_count"],
                "computed": len(records),
                "matches": len(records) == meta["expected_run_count"],
            },
            "unique_sample_count": (
                {
                    "expected": 107,
                    "computed": unique_samples,
                    "matches": unique_samples == 107,
                }
                if meta["investigation_id"] == "PSI-25"
                else None
            ),
            "composite_key_uniqueness": {
                "total_records": len(records),
                "unique_record_pk": unique_pks,
                "is_unique": unique_pks == len(records),
            },
        },
        "unexpected_headers": meta["unexpected_headers"],
        "field_status_distributions": field_distributions,
        "unrecognized_tokens": unrecognized_tokens,
        "negative_readings": negative_readings,
        "repeated_sample_ids": {
            "repeated_sample_count": len(repeated_samples),
            "rows_in_repeated_samples": sum(len(v) for v in repeated_samples.values()),
            "samples": repeated_samples,
        }
        if sample_groups
        else None,
        "repeated_flex_identifiers": {
            "repeated_identifier_count": len(repeated_flex_ids),
            "identifiers": repeated_flex_ids,
        }
        if flex_id_groups
        else None,
        "record_quality_flag_counts": dict(sorted(record_flag_counts.items())),
        "measurement_quality_flag_counts": dict(sorted(measurement_flag_counts.items())),
    }


def _run_conversion_and_provenance_checks(
    records: list[ExperimentRecord],
) -> dict[str, Any]:
    by_inv: dict[str, list[ExperimentRecord]] = defaultdict(list)
    for r in records:
        by_inv[r.investigation_id].append(r)

    psi25 = by_inv["PSI-25"]
    psi69 = by_inv["PSI-69"]

    o2_vol_units = {
        r.measurements["initial_o2_vol_pct"].normalized_unit for r in psi25
    }
    o2_mol_units = {
        r.measurements["initial_o2_flex_mol_pct"].normalized_unit for r in psi69
    }

    pressure_sample = next(
        (
            {
                "record_pk": r.record_pk,
                "raw_mmhg": r.measurements["ambient_pressure_kpa"].raw_value,
                "kpa": r.measurements["ambient_pressure_kpa"].normalized_value,
                "atm": r.measurements["ambient_pressure_kpa"].extra_conversions["atm"]["value"],
            }
            for r in psi69
            if r.measurements["ambient_pressure_kpa"].status == MeasurementStatus.MEASURED
        ),
        None,
    )

    uncalibrated_converted = sum(
        1
        for r in psi25
        for fname in ("fan_display", "air_display", "radiometer_gain")
        if r.measurements[fname].normalized_value is not None
    )

    burning_rate_prov = sorted(
        {r.measurements["burning_rate_mm2_s"].provenance or "" for r in psi69}
    )
    co2_prov = sorted(
        {r.measurements["initial_co2_flex_mol_pct"].provenance or "" for r in psi69}
    )

    trace_ok = all(
        bool(r.source.source_sha256)
        and r.source.csv_record_index >= 1
        and r.source.physical_line_start >= 2
        and r.source.physical_line_end >= r.source.physical_line_start
        for r in records
    )

    return {
        "o2_unit_separation": {
            "psi25_normalized_units": sorted(u or "" for u in o2_vol_units),
            "psi69_normalized_units": sorted(u or "" for u in o2_mol_units),
            "kept_separate": o2_vol_units != o2_mol_units,
        },
        "pressure_conversion_sample": pressure_sample,
        "uncalibrated_fields_converted_to_physical": uncalibrated_converted,
        "flex_provenance": {
            "burning_rate": burning_rate_prov,
            "co2_initial": co2_prov,
        },
        "source_trace_all_valid": trace_ok,
    }


def build_quality_and_manifest(
    repo_root: str | Path = ".",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Manifest ve kalite raporu sözlüklerini canlı hesaplamayla üretir."""
    records, metas = load_core_datasets(repo_root=repo_root)

    manifest = {
        "contract_version": "0.1.0-paket-a",
        "contract_reference": "docs/hazirlik/VERI_SOZLESMESI.md",
        "position_definition": POSITION_DEFINITION,
        "sources": [
            {
                "investigation_id": meta["investigation_id"],
                "experiment_name": meta["experiment_name"],
                "relative_path": meta["relative_path"],
                "encoding": meta["encoding"],
                "file_bytes": meta["file_bytes"],
                "sha256": meta["sha256"],
                "doi": meta["doi"],
                "catalog_license": meta["catalog_license"],
                "reports_license_note": meta["reports_license_note"],
                "download_date": None,
                "download_date_note": "Yerel dosya metadata'sında doğrulanmış indirme tarihi bulunmadığından uydurulmadı.",
                "computed_run_count": meta["computed_run_count"],
                "physical_line_count": meta["physical_line_count"],
                "raw_headers": meta["raw_headers"],
            }
            for meta in (metas["PSI-25"], metas["PSI-69"])
        ],
    }

    by_inv: dict[str, list[ExperimentRecord]] = defaultdict(list)
    for rec in records:
        by_inv[rec.investigation_id].append(rec)

    all_pks = [r.record_pk for r in records]
    quality = {
        "contract_version": "0.1.0-paket-a",
        "overall": {
            "expected_total_runs": 129 + 274,
            "computed_total_runs": len(records),
            "unique_composite_keys": len(set(all_pks)),
            "composite_keys_all_unique": len(all_pks) == len(set(all_pks)),
            "schema_mismatch_count": sum(len(m["unexpected_headers"]) for m in metas.values()),
        },
        "investigations": {
            inv_id: _summarize_investigation(by_inv[inv_id], metas[inv_id])
            for inv_id in ("PSI-25", "PSI-69")
        },
        "conversion_and_trace_checks": _run_conversion_and_provenance_checks(records),
    }
    return manifest, quality


def generate_core_artifacts(
    repo_root: str | Path = ".",
    output_dir: str | Path = "data/processed",
) -> tuple[Path, Path]:
    """Manifest ve kalite raporunu hesaplayıp JSON dosyalarına yazar."""
    root = Path(repo_root).resolve()
    out = (root / output_dir).resolve() if not Path(output_dir).is_absolute() else Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    manifest, quality = build_quality_and_manifest(repo_root=root)
    manifest_path = out / "psi_core_manifest.json"
    quality_path = out / "psi_core_quality.json"

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    quality_path.write_text(
        json.dumps(quality, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return manifest_path, quality_path


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[0]) if argv else Path(".")
    manifest_path, quality_path = generate_core_artifacts(repo_root=root)
    print(f"Manifest yazıldı: {manifest_path}")
    print(f"Kalite raporu yazıldı: {quality_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
