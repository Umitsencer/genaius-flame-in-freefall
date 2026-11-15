"""Read-only technical feasibility probe for NASA PSI-101 (SAME-R).

Inspects the verified PSI-101 Experimental Table together with lean downloaded
HKPData telemetry runs (`SAME Test # 89` and `91`) and writes structured
provenance, channel statistics, anomalies, and row-level CSV traceability to
`data/processed/same_r_feasibility.json`.

Raw telemetry Voltages are preserved strictly in their source units; no
uncalibrated smoke-density conversion or fire-detection threshold is invented.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXP_CSV = ROOT / "data" / "raw" / "psi" / "experimental_tables" / "PSI-101" / "PSI-101_Experimental table_SAME-R.csv"
META_101 = ROOT / "data" / "raw" / "psi" / "metadata" / "PSI-101.json"
META_102 = ROOT / "data" / "raw" / "psi" / "metadata" / "PSI-102.json"
PROBE_DIR = ROOT / "data" / "raw" / "psi" / "same_r_probe"
PROBE_DOWNLOADS = PROBE_DIR / "probe_downloads.json"
OUT_JSON = ROOT / "data" / "processed" / "same_r_feasibility.json"

SENTINEL_FLOATS = frozenset({-10.0, -400.0, -500.0, -999.0})

TRACKED_CHANNELS: tuple[tuple[str, str], ...] = (
    ("GasPlumeTemperature(DegC)", "DegC"),
    ("SampleResistance(Ohms)", "Ohms"),
    ("ISSDetectorObscurationMeasurement(Volts)", "Volts"),
    ("ISSDetectorScatterMeasurement(Volts)", "Volts"),
    ("STSDetectorMeasurement(Volts)", "Volts"),
    ("IonDetectorAMeasurement(Volts)", "Volts"),
    ("IonDetectorBMeasurement(Volts)", "Volts"),
    ("PTrakMeasurement(PtPerCC)", "PtPerCC"),
    ("DustTrakAMeasurement(MgPerM3)", "MgPerM3"),
    ("DustTrakBMeasurement(MgPerM3)", "MgPerM3"),
    ("DustTrakAAnalogMeasurement(Volts)", "Volts"),
    ("DustTrakBAnalogMeasurement(Volts)", "Volts"),
)

PROBE_TARGETS: tuple[tuple[str, str], ...] = (
    ("89", "PSI-101_Raw Data_HKPData_gmt242_6_run89.csv"),
    ("91", "PSI-101_Raw Data_HKPData_gmt250_1.csv"),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_optional_float(raw: str) -> float | None:
    txt = raw.strip()
    if not txt:
        return None
    try:
        val = float(txt)
    except ValueError:
        return None
    if val != val:  # NaN guard
        return None
    return val


def _audit_experimental_table(path: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    rows_by_test: dict[str, list[dict[str, Any]]] = {}
    materials: dict[str, int] = {}
    test_id_counts: dict[str, int] = {}
    aged_rows = 0
    missing_counts: dict[str, int] = {}
    na_net_aging = 0

    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        for col in fieldnames:
            missing_counts[col] = 0
        total_rows = 0
        for rec_idx, row in enumerate(reader, start=1):
            total_rows += 1
            csv_line = rec_idx + 1  # line 1 is CSV header
            mat = (row.get("Sample Type") or "").strip()
            materials[mat] = materials.get(mat, 0) + 1
            tid = (row.get("SAME Test #") or "").strip()
            test_id_counts[tid] = test_id_counts.get(tid, 0) + 1
            if tid.endswith("a"):
                aged_rows += 1
            for col in fieldnames:
                if not (row.get(col) or "").strip():
                    missing_counts[col] += 1
            if (row.get("Net aging time (sec)") or "").strip().lower() == "n/a":
                na_net_aging += 1
            entry = {
                "record_index": rec_idx,
                "physical_csv_line": csv_line,
                **{k: (v or "").strip() for k, v in row.items()},
            }
            rows_by_test.setdefault(tid, []).append(entry)

    duplicates = {k: rows_by_test[k] for k, c in test_id_counts.items() if c > 1}
    summary = {
        "file": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "columns": fieldnames,
        "data_row_count": total_rows,
        "unique_test_ids": len(test_id_counts),
        "aged_suffix_rows": aged_rows,
        "primary_or_non_a_rows": total_rows - aged_rows,
        "materials": materials,
        "empty_cell_counts": {k: v for k, v in missing_counts.items() if v > 0},
        "net_aging_na_count": na_net_aging,
        "duplicate_test_ids": {
            tid: [
                {
                    "physical_csv_line": r["physical_csv_line"],
                    "sample_type": r["Sample Type"],
                    "description": r["Description"],
                    "date": r["Date"],
                    "rt_r0": r["Rt/R0"],
                }
                for r in recs
            ]
            for tid, recs in duplicates.items()
        },
        "rt_r0_definition": (
            "Electrical resistance ratio setpoint Rt/R0 of the pyrolysis heater wire "
            "(Operations Manual Sec. 5.2, p.11; Final Report p.2, p.27) -- NOT a direct smoke metric."
        ),
    }
    return summary, rows_by_test


def _analyze_hkp_run(
    target_test_id: str,
    hkp_path: Path,
    exp_matches: list[dict[str, Any]],
    download_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    with hkp_path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        headers = list(reader.fieldnames or [])
        all_rows = list(reader)

    total_rows = len(all_rows)
    times = [int(r["Time"]) for r in all_rows]
    step_deltas: dict[int, int] = {}
    step_anomaly_samples: list[dict[str, Any]] = []
    for idx in range(1, total_rows):
        delta = times[idx] - times[idx - 1]
        step_deltas[delta] = step_deltas.get(delta, 0) + 1
        if delta != 1 and len(step_anomaly_samples) < 12:
            step_anomaly_samples.append({
                "physical_csv_line": idx + 2,
                "time_string": all_rows[idx]["TimeString"],
                "prev_unix": times[idx - 1],
                "curr_unix": times[idx],
                "delta_s": delta,
            })

    phase_segments: list[dict[str, Any]] = []
    cur_state: tuple[str, str, str] | None = None
    seg_start_idx = 0
    for idx, r in enumerate(all_rows):
        st = (r["RunMode"].strip(), r["TestNumber"].strip(), r["TestRunning"].strip())
        if st != cur_state:
            if cur_state is not None:
                phase_segments[-1]["end_record_index"] = idx
                phase_segments[-1]["end_csv_line"] = idx + 1
                phase_segments[-1]["end_time_string"] = all_rows[idx - 1]["TimeString"]
                phase_segments[-1]["end_elapsed_s"] = all_rows[idx - 1]["ElapsedTestTime(Secs)"]
                phase_segments[-1]["row_count"] = idx - seg_start_idx
            cur_state = st
            seg_start_idx = idx
            phase_segments.append({
                "run_mode": st[0],
                "test_number": st[1],
                "test_running": st[2],
                "start_record_index": idx + 1,
                "start_csv_line": idx + 2,
                "start_time_string": r["TimeString"],
                "start_elapsed_s": r["ElapsedTestTime(Secs)"],
            })
    if phase_segments:
        phase_segments[-1]["end_record_index"] = total_rows
        phase_segments[-1]["end_csv_line"] = total_rows + 1
        phase_segments[-1]["end_time_string"] = all_rows[-1]["TimeString"]
        phase_segments[-1]["end_elapsed_s"] = all_rows[-1]["ElapsedTestTime(Secs)"]
        phase_segments[-1]["row_count"] = total_rows - seg_start_idx

    active_indices = [
        idx
        for idx, r in enumerate(all_rows)
        if r["TestNumber"].strip() == target_test_id and r["TestRunning"].strip() == "1"
    ]
    heating_indices = [
        idx
        for idx in active_indices
        if r_val(all_rows[idx], "HeatingInProgress") == "1"
    ]
    post_test_ind_lines = [
        idx + 2
        for idx, r in enumerate(all_rows)
        if (r.get("GasPlumeTemperature(DegC)") or "").strip() == "-1.#IND"
    ]
    ptrak_missing_lines = [
        {"physical_csv_line": idx + 2, "elapsed_s": all_rows[idx]["ElapsedTestTime(Secs)"]}
        for idx in active_indices
        if (all_rows[idx].get("PTrakMeasurement(PtPerCC)") or "").strip() == "-999"
    ]
    sts_alarm_lines = [
        idx + 2
        for idx in active_indices
        if r_val(all_rows[idx], "STSDetectorAlarm") == "1"
    ]

    channels_out: list[dict[str, Any]] = []
    for col, unit in TRACKED_CHANNELS:
        if col not in headers:
            continue
        active_valid: list[tuple[float, int, str]] = []
        active_sentinels: dict[str, int] = {}
        full_file_sentinels: dict[str, int] = {}
        for idx, r in enumerate(all_rows):
            raw = (r.get(col) or "").strip()
            val = _parse_optional_float(raw)
            is_active = r["TestNumber"].strip() == target_test_id and r["TestRunning"].strip() == "1"
            if val is None or val in SENTINEL_FLOATS:
                key = raw if raw else "<empty>"
                full_file_sentinels[key] = full_file_sentinels.get(key, 0) + 1
                if is_active:
                    active_sentinels[key] = active_sentinels.get(key, 0) + 1
                continue
            if is_active:
                active_valid.append((val, idx + 2, r["ElapsedTestTime(Secs)"].strip()))

        if active_valid:
            min_pt = min(active_valid, key=lambda x: x[0])
            max_pt = max(active_valid, key=lambda x: x[0])
            start_pt = active_valid[0]
            end_pt = active_valid[-1]
        else:
            min_pt = max_pt = start_pt = end_pt = None

        channels_out.append({
            "column": col,
            "source_unit": unit,
            "active_valid_count": len(active_valid),
            "active_sentinels": active_sentinels,
            "full_file_sentinels": full_file_sentinels,
            "active_start": _pt_dict(start_pt) if start_pt else None,
            "active_min": _pt_dict(min_pt) if min_pt else None,
            "active_max": _pt_dict(max_pt) if max_pt else None,
            "active_end": _pt_dict(end_pt) if end_pt else None,
        })

    # Build traceable sample rows at key milestones
    milestone_indices: list[tuple[str, int]] = []
    if active_indices:
        milestone_indices.append(("active_start", active_indices[0]))
    if heating_indices:
        milestone_indices.append(("heating_start", heating_indices[0]))
        milestone_indices.append(("heating_end", heating_indices[-1]))
    # Peak STS or DustTrakB row if present
    for label, col in (
        ("peak_sts_detector", "STSDetectorMeasurement(Volts)"),
        ("peak_dusttrak_b", "DustTrakBMeasurement(MgPerM3)"),
    ):
        pts = [
            (idx, _parse_optional_float(all_rows[idx].get(col, "")))
            for idx in active_indices
        ]
        pts_ok = [(idx, v) for idx, v in pts if v is not None and v not in SENTINEL_FLOATS]
        if pts_ok:
            peak_idx, _ = max(pts_ok, key=lambda x: x[1])
            milestone_indices.append((label, peak_idx))
    if active_indices:
        milestone_indices.append(("active_end", active_indices[-1]))

    trace_samples = []
    for role, idx in milestone_indices:
        row = all_rows[idx]
        trace_samples.append({
            "milestone": role,
            "record_index": idx + 1,
            "physical_csv_line": idx + 2,
            "time_string": row["TimeString"],
            "unix_time": int(row["Time"]),
            "run_mode": row["RunMode"],
            "test_number": row["TestNumber"],
            "elapsed_test_time_s": row["ElapsedTestTime(Secs)"],
            "heating_in_progress": row["HeatingInProgress"],
            "gas_plume_temp_c": row["GasPlumeTemperature(DegC)"],
            "sts_detector_v": row["STSDetectorMeasurement(Volts)"],
            "iss_obscuration_v": row["ISSDetectorObscurationMeasurement(Volts)"],
            "iss_scatter_v": row["ISSDetectorScatterMeasurement(Volts)"],
            "ion_detector_b_v": row["IonDetectorBMeasurement(Volts)"],
            "ptrak_pt_per_cc": row["PTrakMeasurement(PtPerCC)"],
            "dusttrak_b_mg_per_m3": row["DustTrakBMeasurement(MgPerM3)"],
        })

    return {
        "test_number": target_test_id,
        "experimental_table_matches": exp_matches,
        "hkp_file": {
            "filename": hkp_path.name,
            "path": hkp_path.relative_to(ROOT).as_posix(),
            "bytes": hkp_path.stat().st_size,
            "sha256": _sha256(hkp_path),
            "source_api_endpoint": (download_meta or {}).get("api_endpoint"),
            "file_id": (download_meta or {}).get("file_id"),
            "study_version": (download_meta or {}).get("study_version"),
            "column_count": len(headers),
            "data_row_count": total_rows,
            "physical_line_count": total_rows + 1,
        },
        "time_summary": {
            "first_time_string": all_rows[0]["TimeString"],
            "last_time_string": all_rows[-1]["TimeString"],
            "unix_start": times[0],
            "unix_end": times[-1],
            "wall_span_s": times[-1] - times[0],
            "step_delta_histogram_s": {str(k): v for k, v in sorted(step_deltas.items())},
            "non_1s_step_anomalies_sample": step_anomaly_samples,
        },
        "phases": phase_segments,
        "heating_window": {
            "row_count": len(heating_indices),
            "start_csv_line": heating_indices[0] + 2 if heating_indices else None,
            "end_csv_line": heating_indices[-1] + 2 if heating_indices else None,
            "start_elapsed_s": all_rows[heating_indices[0]]["ElapsedTestTime(Secs)"] if heating_indices else None,
            "end_elapsed_s": all_rows[heating_indices[-1]]["ElapsedTestTime(Secs)"] if heating_indices else None,
        },
        "data_quality": {
            "active_running_rows": len(active_indices),
            "post_test_ind_temp_rows": len(post_test_ind_lines),
            "post_test_ind_line_range": (
                [post_test_ind_lines[0], post_test_ind_lines[-1]] if post_test_ind_lines else None
            ),
            "ptrak_minus999_count": len(ptrak_missing_lines),
            "ptrak_minus999_locations": ptrak_missing_lines,
            "sts_alarm_active_lines": sts_alarm_lines,
        },
        "channels": channels_out,
        "row_traceability_samples": trace_samples,
    }


def r_val(row: dict[str, str], col: str) -> str:
    return (row.get(col) or "").strip()


def _pt_dict(pt: tuple[float, int, str]) -> dict[str, Any]:
    return {"value": pt[0], "physical_csv_line": pt[1], "elapsed_s": pt[2]}


def main() -> None:
    meta_101 = json.loads(META_101.read_text(encoding="utf-8"))
    meta_102 = json.loads(META_102.read_text(encoding="utf-8"))
    downloads_list = json.loads(PROBE_DOWNLOADS.read_text(encoding="utf-8")) if PROBE_DOWNLOADS.exists() else []
    downloads_by_name = {d["filename"]: d for d in downloads_list}

    exp_summary, rows_by_test = _audit_experimental_table(EXP_CSV)

    telemetry_probes = []
    for tid, fname in PROBE_TARGETS:
        hkp_path = PROBE_DIR / fname
        if not hkp_path.exists():
            raise FileNotFoundError(f"Missing probe telemetry file: {hkp_path}")
        telemetry_probes.append(
            _analyze_hkp_run(
                target_test_id=tid,
                hkp_path=hkp_path,
                exp_matches=rows_by_test.get(tid, []),
                download_meta=downloads_by_name.get(fname),
            )
        )

    report = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "probe_scope": "Read-only technical feasibility probe for PSI-101 (SAME-R); kept strictly separate from PSI-102 (SAME) and BASS-II/FLEX core.",
        "investigation": {
            "psi_id": "PSI-101",
            "acronym": meta_101.get("investigationAcronym"),
            "title": meta_101.get("title"),
            "version": meta_101.get("version"),
            "doi": meta_101.get("doi"),
            "license_identifier": meta_101.get("licenseIdentifier"),
            "flight_program": meta_101.get("flightProgram"),
            "strict_separation_check": {
                "psi_102_acronym": meta_102.get("investigationAcronym"),
                "psi_102_title": meta_102.get("title"),
                "psi_102_version": meta_102.get("version"),
                "note": "PSI-101 (SAME-R, 2010, 5 materials incl. Pyrell + MPASS) and PSI-102 (SAME, 2007, 8 CSV summary rows incl. DBP) are distinct PSI studies.",
            },
        },
        "probe_downloads": downloads_list,
        "experimental_table_audit": exp_summary,
        "telemetry_probes": telemetry_probes,
        "limits_and_recommendation": {
            "observed_limits": [
                "No ambient O2 or chamber pressure variables in PSI-101 Experimental Table; only Inlet velocity (cm/s) and heater wire setpoint ratio Rt/R0.",
                "Rt/R0 measures resistive heater wire ratio, not smoke optical properties, and shows scatter due to air-exposed wire lead length (Final Report p.2, p.27) and heater offset issues (Ops Manual p.19).",
                "Experimental Table duplicates SAME Test # 57 across Lampwick (CSV line 57) and Teflon (CSV line 75) even though Final Report Appendix A p.32 assigns 57 to 10L Lampwick.",
                "HKPData files contain non-test rows, post-test Windows -1.#IND temperature NaNs, -10/-400/-500 sentinels, P-Trak -999 dropouts, IonDetectorA inactive (~0 V baseline when swapped for MPASS), and non-1s timestamp steps.",
                "Raw detector channels are in Volts without in-file smoke-density calibration constants; Final Report p.24 documents ionization detector calibration-range exceedances.",
            ],
            "recommendation": "limited_single_test_signal_display_optional",
            "recommendation_rationale": (
                "Do not add PSI-101 to the PSI-25/PSI-69 comparison core or infer flame-detection thresholds/severity. "
                "Either keep PSI-101 as a source/reference card or expose an isolated single-run telemetry viewer (e.g. Run 89) strictly in source Volts/PtPerCC/MgPerM3 with explicit caveats."
            ),
        },
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_JSON.relative_to(ROOT).as_posix()} ({OUT_JSON.stat().st_size} bytes)")
    for tp in telemetry_probes:
        hkp = tp["hkp_file"]
        qual = tp["data_quality"]
        print(
            f"  Test #{tp['test_number']} ({hkp['filename']}): "
            f"active_rows={qual['active_running_rows']}, "
            f"post_test_ind={qual['post_test_ind_temp_rows']}, "
            f"ptrak_-999={qual['ptrak_minus999_count']}, "
            f"heat={tp['heating_window']['start_elapsed_s']}..{tp['heating_window']['end_elapsed_s']}s"
        )


if __name__ == "__main__":
    main()
