"""Reproducible eligibility, quality, coverage, and descriptive audit for NASA PSI-39 (CFI).

Reads the raw PSI-39 Excel workbook and experimental CSV read-only, joins all
visible sheets strictly by normalized text `Flex Number` (preserving `"1274A"`),
verifies field missingness, zero vs missing vs literal `'NaN'` separation,
precise comment-flag provenance, condition coverage for candidate questions,
quality-sensitivity descriptive statistics, and ML feasibility counts.

Writes strictly valid JSON (no NaN/Infinity tokens) to:
    data/processed/cfi_eligibility_audit.json
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import openpyxl

REPO_ROOT = Path(__file__).resolve().parents[2]
XLSX_PATH = (
    REPO_ROOT
    / "data"
    / "raw"
    / "psi"
    / "matrices_and_readmes"
    / "PSI-39"
    / "PSI-39_Science Documents_CFI_DataSummary_Spreadsheet_Jan2021.xlsx"
)
CSV_PATH = (
    REPO_ROOT
    / "data"
    / "raw"
    / "psi"
    / "experimental_tables"
    / "PSI-39"
    / "PSI-39_Experimental table_CFI.csv"
)
OUT_JSON = REPO_ROOT / "data" / "processed" / "cfi_eligibility_audit.json"

SHEETS_EXPECTED = ("Master Sheet", "DATA", "Camera Settings", "Igniter", "Comments")
NON_IGNITED_YES_IDS = frozenset({"1212", "1235"})


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _norm_key(raw: Any) -> str:
    return str(raw).strip()


def _norm_fuel(raw: Any) -> str:
    s = str(raw or "").strip()
    if s == "C12H26":
        return "C12H26"
    if "[.75]/[.25]" in s:
        return "75/25 C12H26/iso-dodecane"
    if "[.60]/[.40]" in s:
        return "60/40 C12H26/iso-dodecane"
    return s


def _load_sheet_by_key(ws: Any) -> tuple[list[str], list[str], dict[str, dict[str, Any]]]:
    rows = list(ws.iter_rows(values_only=True))
    raw_headers = [str(c) if c is not None else "" for c in rows[0]]
    clean_headers = [h.strip() for h in raw_headers]
    ordered_keys: list[str] = []
    by_key: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []

    for excel_row, values in enumerate(rows[1:], start=2):
        if all(v is None or (isinstance(v, str) and not v.strip()) for v in values):
            continue
        row_map = dict(zip(clean_headers, values))
        raw_key = row_map.get("Flex Number")
        key = _norm_key(raw_key)
        if key in by_key:
            duplicates.append(key)
        ordered_keys.append(key)
        by_key[key] = {
            "_excel_row": excel_row,
            "_raw_flex_number": raw_key,
            "_raw_flex_type": type(raw_key).__name__,
            **row_map,
        }

    if duplicates:
        raise ValueError(f"Duplicate Flex Number keys in {ws.title}: {duplicates}")
    return raw_headers, ordered_keys, by_key


def _classify_numeric_cell(val: Any) -> tuple[str, float | None]:
    if val is None:
        return "empty", None
    if isinstance(val, bool):
        return "other_bool", None
    if isinstance(val, (int, float)):
        fval = float(val)
        if not math.isfinite(fval):
            return "nonfinite_float", None
        if fval > 0.0:
            return "positive", fval
        if fval == 0.0:
            return "zero", 0.0
        return "negative", fval
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return "empty", None
        if s.lower() == "nan":
            return "literal_nan", None
        return "other_str", None
    return f"other_{type(val).__name__}", None


def _summarize_column(records: list[dict[str, Any]], col: str) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    finite_vals: list[float] = []
    nonfinite_keys: list[dict[str, Any]] = []
    for rec in records:
        kind, num = _classify_numeric_cell(rec.get(col))
        counts[kind] += 1
        if num is not None:
            finite_vals.append(num)
        elif kind != "empty":
            nonfinite_keys.append(
                {
                    "flex_number": rec["flex_number"],
                    "excel_row": rec["data_row"],
                    "raw_value": rec.get(col),
                    "kind": kind,
                }
            )
    return {
        "total_records": len(records),
        "positive": counts.get("positive", 0),
        "zero": counts.get("zero", 0),
        "negative": counts.get("negative", 0),
        "empty": counts.get("empty", 0),
        "literal_nan": counts.get("literal_nan", 0),
        "finite_total": len(finite_vals),
        "non_numeric_total": len(records) - len(finite_vals),
        "min": round(min(finite_vals), 6) if finite_vals else None,
        "max": round(max(finite_vals), 6) if finite_vals else None,
        "special_non_numeric": nonfinite_keys,
    }


def _excerpt(text: str, pattern: re.Pattern[str]) -> str:
    m = pattern.search(text)
    if not m:
        return text[:140]
    start = max(0, m.start() - 35)
    end = min(len(text), m.end() + 85)
    snippet = " ".join(text[start:end].split())
    return ("..." if start > 0 else "") + snippet + ("..." if end < len(text) else "")


# Precise phrase matchers verified against verbatim CFI Comments (avoids negated matches)
_FLAG_RULES: dict[str, dict[str, Any]] = {
    "reused_droplet": {
        "description": "Residual droplet from previous test was actively ignited, combined, or re-used.",
        "impacts_measurement": True,
        "include": re.compile(
            r"(?:using|use|ignited|attempting to re-?ignit\w*|try to burn)\s+(?:a\s+)?residual\s+drop\w*"
            r"|residual\s+drop\w*\s+(?:still\s+on\s+fiber|from\s+last\s+test)",
            re.I,
        ),
        "exclude": re.compile(r"got\s+rid\s+of\s+it|new\s+spot\s+on\s+fiber", re.I),
    },
    "attempted_reused_then_fresh": {
        "description": "Re-use was attempted initially, then droplet was vaporized/lost and replaced.",
        "impacts_measurement": False,
        "include": re.compile(r"re-?use\s+droplet\s+from\s+last\s+test", re.I),
        "exclude": None,
    },
    "ipsu_or_radiometer_failure": {
        "description": "IPSU intensified camera failed continuous mode or radiometer detection failed.",
        "impacts_measurement": True,
        "include": re.compile(
            r"ipsug?\s+did\s+not\s+switch|no\s+ipsu-?g\s+data|radiometer\s+dection\s+did\s+not\s+work|ipsu-?3\s+still\s+not\s+working",
            re.I,
        ),
        "exclude": None,
    },
    "fov_exit_confirmed": {
        "description": "Comment states the droplet left or likely left the HiBMS/camera FOV before completion.",
        "impacts_measurement": True,
        "include": re.compile(
            r"(?:left|drifted?\s+out\s+of|moves?\s+outside|moved\s+out\s+of|out\s+of)\s+(?:the\s+)?(?:hibms\s+|color\s+camera\s+)?fov"
            r"|likely\s+(?:drifted\s+out|leaves\s+hibms\s+fov)",
            re.I,
        ),
        "exclude": None,
    },
    "igniter_contact": {
        "description": "Comment reports droplet physically hitting or contacting an igniter.",
        "impacts_measurement": True,
        "include": re.compile(
            r"(?:droplet\s+(?:hits?|drifted[^.]{0,30}hit)|(?:hit|hits)\s+(?:the\s+)?(?:lower\s+|upper\s+|bottom\s+)?igniter|in\s+contact\s+w/\s*igniter)",
            re.I,
        ),
        "exclude": re.compile(r"protect\s+igniter", re.I),
    },
    "fiber_glow_or_slip": {
        "description": "Noticeable fiber glow or physical slackening/sliding of droplet on support fiber.",
        "impacts_measurement": True,
        "include": re.compile(
            r"(?:glow\s+(?:of|on)\s+(?:the\s+)?(?:carbide\s+)?fiber|fiber\s+glow|fiber\s+appears\s+to\s+slacken|droplet\s+slides\s+along\s+the\s+fiber)",
            re.I,
        ),
        "exclude": None,
    },
    "obscuration_note": {
        "description": "Dense vapor cloud, large soot agglomerate, or frozen downlink noted as impairing visibility.",
        "impacts_measurement": True,
        "include": re.compile(
            r"hard\s+to\s+see|large\s+soot\s+agglomerate|vapor\s+cloud\s+of\s+soot|unknown\s+cool\s+flame\s+burn|downlink[^.]{0,20}frozen",
            re.I,
        ),
        "exclude": None,
    },
}


def _extract_comment_flags(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_flag: dict[str, list[dict[str, Any]]] = {k: [] for k in _FLAG_RULES}
    flags_by_key: dict[str, list[str]] = defaultdict(list)

    for rec in records:
        txt = rec["comment"]
        for fname, rule in _FLAG_RULES.items():
            inc = rule["include"]
            exc = rule["exclude"]
            if inc.search(txt) and (exc is None or not exc.search(txt)):
                by_flag[fname].append(
                    {
                        "flex_number": rec["flex_number"],
                        "excel_row": rec["comment_row"],
                        "fiber": rec["fiber"],
                        "pressure_atm": rec["pressure_atm"],
                        "fuel": rec["fuel"],
                        "excerpt": _excerpt(txt, inc),
                    }
                )
                flags_by_key[rec["flex_number"]].append(fname)

    impacting_flags = {k for k, v in _FLAG_RULES.items() if v["impacts_measurement"]}
    impacted_keys = sorted(
        k for k, flist in flags_by_key.items() if any(f in impacting_flags for f in flist)
    )
    return {
        "rule_descriptions": {k: v["description"] for k, v in _FLAG_RULES.items()},
        "counts": {k: len(v) for k, v in by_flag.items()},
        "records_by_flag": by_flag,
        "flags_by_record": {k: flags_by_key[k] for k in sorted(flags_by_key)},
        "measurement_impacted_record_count": len(impacted_keys),
        "measurement_impacted_record_ids": impacted_keys,
    }


def _describe_subset(
    recs: list[dict[str, Any]],
    *,
    flags_by_record: dict[str, list[str]],
) -> dict[str, Any]:
    kcool_vals: list[float] = []
    kcool_raw: list[dict[str, Any]] = []
    dc_pos_vals: list[float] = []
    dc_pos_raw: list[dict[str, Any]] = []
    dc_zero = 0
    dc_empty = 0
    dc_nan = 0
    d0_vals: list[float] = []
    extrap_counts: Counter[str] = Counter()
    reig_pos = 0
    reused_count = 0

    for rec in recs:
        k = rec["flex_number"]
        rflags = flags_by_record.get(k, [])
        if "reused_droplet" in rflags:
            reused_count += 1
        ext_val = rec["extrap_cf"]
        extrap_counts[str(ext_val) if ext_val is not None else "empty"] += 1

        if isinstance(rec["reignitions"], (int, float)) and rec["reignitions"] > 0:
            reig_pos += 1
        d0_kind, d0_num = _classify_numeric_cell(rec["d0_mm"])
        if d0_num is not None:
            d0_vals.append(d0_num)

        kc_kind, kc_num = _classify_numeric_cell(rec["kcool"])
        if kc_num is not None:
            kcool_vals.append(kc_num)
            kcool_raw.append(
                {
                    "flex_number": k,
                    "excel_row": rec["data_row"],
                    "value": round(kc_num, 6),
                    "extrap_cf": ext_val,
                    "flags": rflags,
                }
            )

        dc_kind, dc_num = _classify_numeric_cell(rec["dext_cool_mm"])
        if dc_kind == "positive" and dc_num is not None:
            dc_pos_vals.append(dc_num)
            dc_pos_raw.append(
                {
                    "flex_number": k,
                    "excel_row": rec["data_row"],
                    "value": round(dc_num, 6),
                    "extrap_cf": ext_val,
                    "flags": rflags,
                }
            )
        elif dc_kind == "zero":
            dc_zero += 1
        elif dc_kind == "literal_nan":
            dc_nan += 1
        else:
            dc_empty += 1

    return {
        "n_candidates": len(recs),
        "record_ids": [r["flex_number"] for r in recs],
        "d0_range_mm": [round(min(d0_vals), 4), round(max(d0_vals), 4)] if d0_vals else None,
        "extrap_cf_raw_counts": dict(sorted(extrap_counts.items())),
        "reignitions_positive_count": reig_pos,
        "reused_droplet_count": reused_count,
        "kcool": {
            "n_finite": len(kcool_vals),
            "n_missing": len(recs) - len(kcool_vals),
            "median": round(statistics.median(kcool_vals), 4) if kcool_vals else None,
            "min": round(min(kcool_vals), 4) if kcool_vals else None,
            "max": round(max(kcool_vals), 4) if kcool_vals else None,
            "raw_records": kcool_raw,
        },
        "dext_cool_mm": {
            "n_positive": len(dc_pos_vals),
            "n_raw_zero_unresolved": dc_zero,
            "n_empty": dc_empty,
            "n_literal_nan": dc_nan,
            "positive_median": round(statistics.median(dc_pos_vals), 4) if dc_pos_vals else None,
            "positive_min": round(min(dc_pos_vals), 4) if dc_pos_vals else None,
            "positive_max": round(max(dc_pos_vals), 4) if dc_pos_vals else None,
            "positive_raw_records": dc_pos_raw,
        },
    }


def _build_sensitivity_scenarios(
    recs: list[dict[str, Any]],
    *,
    flags_by_record: dict[str, list[str]],
    impacted_set: set[str],
) -> dict[str, Any]:
    no_reused = [r for r in recs if "reused_droplet" not in flags_by_record.get(r["flex_number"], [])]
    no_impacted = [r for r in recs if r["flex_number"] not in impacted_set]
    no_extrap_cf1 = [r for r in recs if r["extrap_cf"] != 1]
    return {
        "all_candidates": _describe_subset(recs, flags_by_record=flags_by_record),
        "excluding_reused_droplet": _describe_subset(no_reused, flags_by_record=flags_by_record),
        "excluding_documented_measurement_issues": _describe_subset(
            no_impacted, flags_by_record=flags_by_record
        ),
        "sensitivity_excluding_extrap_cf_1": _describe_subset(
            no_extrap_cf1, flags_by_record=flags_by_record
        ),
    }


def run_audit() -> dict[str, Any]:
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    sheet_data: dict[str, tuple[list[str], list[str], dict[str, dict[str, Any]]]] = {}
    for name in SHEETS_EXPECTED:
        sheet_data[name] = _load_sheet_by_key(wb[name])

    master_raw_hdrs, master_keys, master_map = sheet_data["Master Sheet"]
    data_raw_hdrs, data_keys, data_map = sheet_data["DATA"]
    cam_hdrs, cam_keys, cam_map = sheet_data["Camera Settings"]
    ign_hdrs, ign_keys, ign_map = sheet_data["Igniter"]
    cmt_raw_hdrs, cmt_keys, cmt_map = sheet_data["Comments"]

    key_set = set(master_keys)
    sym_diffs = {
        name: sorted(key_set ^ set(sheet_data[name][2].keys()))
        for name in SHEETS_EXPECTED
    }
    order_matches = {
        name: (sheet_data[name][1] == master_keys) for name in SHEETS_EXPECTED
    }

    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as fh:
        csv_rows = list(csv.DictReader(fh))
    csv_keys = {str(r["Flex Number"]).strip() for r in csv_rows}

    records: list[dict[str, Any]] = []
    for k in master_keys:
        m = master_map[k]
        d = data_map[k]
        c = cmt_map[k]
        o2 = float(m["Oxygen"]) if m.get("Oxygen") is not None else None
        n2 = float(m["Nitrogen"]) if m.get("Nitrogen") is not None else None
        he = float(m["Helium"]) if m.get("Helium") is not None else None
        records.append(
            {
                "flex_number": k,
                "raw_flex_number": m["_raw_flex_number"],
                "raw_flex_type": m["_raw_flex_type"],
                "master_row": m["_excel_row"],
                "data_row": d["_excel_row"],
                "comment_row": c["_excel_row"],
                "test_date": str(m.get("Test Date") or ""),
                "cir": str(m.get("CIR") or "").strip(),
                "fuel_raw": m.get("Fuel"),
                "fuel": _norm_fuel(m.get("Fuel")),
                "pressure_master": m.get("Pressure"),
                "pressure_atm": float(d["Pressure (atm)"]) if d.get("Pressure (atm)") is not None else None,
                "o2": o2,
                "n2": n2,
                "he": he,
                "gas_sum": round(o2 + n2 + he, 6) if None not in (o2, n2, he) else None,
                "fiber": str(m.get("Fiber")).strip() if m.get("Fiber") is not None else None,
                "completed_analysis": str(d.get("Completed Analysis?") or "").strip(),
                "d0_mm": d.get("D0 ( mm )"),
                "dext_hot_mm": d.get("Dext, hot ( mm )"),
                "khot": d.get("khot ( mm^2/s )"),
                "hf_burn_time": d.get("HF Burn Time"),
                "peak_hf_rad": d.get("Peak HF Rad"),
                "peak_water_vapor_rad": d.get("Peak Water Vapor Rad"),
                "rad_ratio": d.get("Rad Ratio"),
                "reignitions": d.get("Reignitions"),
                "kcool": d.get("kcool ( mm^2/s )"),
                "dext_cool_mm": d.get("Dext,cool ( mm )"),
                "extrap_cf": d.get("Extrap CF?"),
                "comment": str(c.get("Comments") or ""),
            }
        )

    yes_records = [r for r in records if r["completed_analysis"] == "Yes"]
    no_records = [r for r in records if r["completed_analysis"] != "Yes"]
    candidate_records = [r for r in yes_records if r["flex_number"] not in NON_IGNITED_YES_IDS]
    excluded_non_ignited = [r for r in yes_records if r["flex_number"] in NON_IGNITED_YES_IDS]

    # Rename DATA fields cleanly for audit reporting
    data_col_map = {
        "d0_mm": "D0 ( mm )",
        "dext_hot_mm": "Dext, hot ( mm )",
        "khot": " khot ( mm^2/s )",
        "hf_burn_time": "HF Burn Time",
        "peak_hf_rad": "Peak HF Rad",
        "peak_water_vapor_rad": "Peak Water Vapor Rad",
        "rad_ratio": "Rad Ratio",
        "reignitions": "Reignitions",
        "kcool": "kcool ( mm^2/s )",
        "dext_cool_mm": "Dext,cool ( mm )",
        "extrap_cf": "Extrap CF?",
    }
    stats_146 = {label: _summarize_column(yes_records, attr) for attr, label in data_col_map.items()}
    stats_144 = {label: _summarize_column(candidate_records, attr) for attr, label in data_col_map.items()}

    # Dynamically verify manager checklist without hardcoding expected numbers into counts
    dc_146 = stats_146["Dext,cool ( mm )"]
    dc_144 = stats_144["Dext,cool ( mm )"]
    kc_146 = stats_146["kcool ( mm^2/s )"]
    kc_144 = stats_144["kcool ( mm^2/s )"]
    manager_checks = {
        "total_227": {"actual": len(records), "reference": 227, "matches": len(records) == 227},
        "completed_yes_146": {"actual": len(yes_records), "reference": 146, "matches": len(yes_records) == 146},
        "candidate_pool_144": {
            "actual": len(candidate_records),
            "reference": 144,
            "matches": len(candidate_records) == 144,
        },
        "dext_cool_146_breakdown": {
            "actual": {
                "positive": dc_146["positive"],
                "zero": dc_146["zero"],
                "empty": dc_146["empty"],
                "literal_nan": dc_146["literal_nan"],
                "sum": dc_146["positive"] + dc_146["zero"] + dc_146["empty"] + dc_146["literal_nan"],
            },
            "reference": {"positive": 69, "zero": 48, "empty": 27, "literal_nan": 2, "sum": 146},
            "matches": (
                dc_146["positive"] == 69
                and dc_146["zero"] == 48
                and dc_146["empty"] == 27
                and dc_146["literal_nan"] == 2
            ),
        },
        "dext_cool_144_breakdown": {
            "actual": {
                "positive": dc_144["positive"],
                "zero": dc_144["zero"],
                "empty": dc_144["empty"],
                "literal_nan": dc_144["literal_nan"],
                "sum": dc_144["positive"] + dc_144["zero"] + dc_144["empty"] + dc_144["literal_nan"],
            },
            "reference": {"positive": 69, "zero": 48, "empty": 25, "literal_nan": 2, "sum": 144},
            "matches": (
                dc_144["positive"] == 69
                and dc_144["zero"] == 48
                and dc_144["empty"] == 25
                and dc_144["literal_nan"] == 2
            ),
        },
        "kcool_missing_146_and_144": {
            "actual_146_missing": kc_146["non_numeric_total"],
            "actual_144_missing": kc_144["non_numeric_total"],
            "reference_146": 22,
            "reference_144": 20,
            "matches": kc_146["non_numeric_total"] == 22 and kc_144["non_numeric_total"] == 20,
        },
    }

    # Additional data-quality checks across 144 candidates
    dext_hot_gt_d0 = [
        {
            "flex_number": r["flex_number"],
            "excel_row": r["data_row"],
            "d0_mm": r["d0_mm"],
            "dext_hot_mm": r["dext_hot_mm"],
        }
        for r in candidate_records
        if isinstance(r["d0_mm"], (int, float))
        and isinstance(r["dext_hot_mm"], (int, float))
        and r["dext_hot_mm"] > r["d0_mm"]
    ]
    gas_sum_anomalies = [
        {
            "flex_number": r["flex_number"],
            "excel_row": r["master_row"],
            "o2": r["o2"],
            "n2": r["n2"],
            "he": r["he"],
            "gas_sum": r["gas_sum"],
            "completed_analysis": r["completed_analysis"],
        }
        for r in records
        if r["gas_sum"] is not None and abs(r["gas_sum"] - 1.0) > 1e-6
    ]
    zero_dext_cool_recs = [
        r for r in candidate_records if _classify_numeric_cell(r["dext_cool_mm"])[0] == "zero"
    ]
    extrap_1_recs = [r for r in candidate_records if r["extrap_cf"] == 1]

    comment_audit = _extract_comment_flags(candidate_records)
    flags_by_record = comment_audit["flags_by_record"]
    impacted_set = set(comment_audit["measurement_impacted_record_ids"])

    # Section C: Exact condition coverage
    air_groups: dict[tuple[float, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in candidate_records:
        if r["o2"] == 0.21 and r["n2"] == 0.79 and r["he"] == 0.0:
            air_groups[(float(r["pressure_atm"]), r["fuel"], str(r["fiber"]))].append(r)

    air_cells = []
    for p, fuel, fiber in sorted(air_groups):
        cell_recs = air_groups[(p, fuel, fiber)]
        desc = _describe_subset(cell_recs, flags_by_record=flags_by_record)
        sens = _build_sensitivity_scenarios(
            cell_recs, flags_by_record=flags_by_record, impacted_set=impacted_set
        )
        air_cells.append(
            {
                "pressure_atm": p,
                "fuel": fuel,
                "fiber": fiber,
                "o2": 0.21,
                "n2": 0.79,
                "he": 0.0,
                **desc,
                "sensitivity": sens,
            }
        )

    c12_groups: dict[tuple[float, float, float, float, str], list[dict[str, Any]]] = defaultdict(list)
    for r in candidate_records:
        if r["fuel"] == "C12H26":
            c12_groups[
                (float(r["pressure_atm"]), float(r["o2"]), float(r["n2"]), float(r["he"]), str(r["fiber"]))
            ].append(r)

    c12_cells = []
    for p, o2, n2, he, fiber in sorted(c12_groups):
        cell_recs = c12_groups[(p, o2, n2, he, fiber)]
        desc = _describe_subset(cell_recs, flags_by_record=flags_by_record)
        sens = _build_sensitivity_scenarios(
            cell_recs, flags_by_record=flags_by_record, impacted_set=impacted_set
        )
        notes = []
        if abs((o2 + n2 + he) - 1.0) > 1e-6:
            notes.append(f"gas_sum={round(o2 + n2 + he, 4)} (N2=0.76 unresolved)")
        if o2 != 0.21:
            notes.append(f"non_air_o2={o2}")
        c12_cells.append(
            {
                "pressure_atm": p,
                "o2": o2,
                "n2": n2,
                "he": he,
                "fiber": fiber,
                "comparability_notes": notes,
                **desc,
                "sensitivity": sens,
            }
        )

    # Section D: Focused descriptive comparison (Air P in {0.5, 0.75, 1.0, 1.25} atm, stratified by P x Fiber)
    q1_air_1atm_by_fiber = {
        fiber: {
            fuel: _build_sensitivity_scenarios(
                air_groups.get((1.0, fuel, fiber), []),
                flags_by_record=flags_by_record,
                impacted_set=impacted_set,
            )
            for fuel in ("C12H26", "75/25 C12H26/iso-dodecane", "60/40 C12H26/iso-dodecane")
        }
        for fiber in ("Yes", "No")
    }
    q2_he_1atm_fib_yes = {
        f"He={int(round(he * 100))}%": _build_sensitivity_scenarios(
            c12_groups.get((1.0, 0.21, n2, he, "Yes"), []),
            flags_by_record=flags_by_record,
            impacted_set=impacted_set,
        )
        for n2, he in ((0.79, 0.0), (0.50, 0.29), (0.20, 0.59))
    }

    # Section E: ML feasibility inventory
    cond_groups_all = Counter(
        (r["fuel"], r["pressure_atm"], r["o2"], r["n2"], r["he"], r["fiber"]) for r in candidate_records
    )
    cond_groups_kcool = Counter(
        (r["fuel"], r["pressure_atm"], r["o2"], r["n2"], r["he"], r["fiber"])
        for r in candidate_records
        if _classify_numeric_cell(r["kcool"])[1] is not None
    )
    cond_groups_dc_pos = Counter(
        (r["fuel"], r["pressure_atm"], r["o2"], r["n2"], r["he"], r["fiber"])
        for r in candidate_records
        if _classify_numeric_cell(r["dext_cool_mm"])[0] == "positive"
    )

    reused_ids = sorted(r["flex_number"] for r in comment_audit["records_by_flag"]["reused_droplet"])

    audit = {
        "schema_version": "036.1",
        "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": {
            "workbook": {
                "relpath": _rel(XLSX_PATH),
                "sha256": _sha256_file(XLSX_PATH),
                "sheets": {
                    name: {
                        "row_count": len(sheet_data[name][1]),
                        "raw_headers_with_ws_issues": [h for h in sheet_data[name][0] if h != h.strip()],
                    }
                    for name in SHEETS_EXPECTED
                },
            },
            "portal_csv": {
                "relpath": _rel(CSV_PATH),
                "sha256": _sha256_file(CSV_PATH),
                "row_count": len(csv_rows),
                "missing_from_csv_count": len(key_set - csv_keys),
            },
        },
        "key_alignment": {
            "join_key": "Flex Number (normalized str.strip())",
            "total_unique_keys": len(master_keys),
            "symmetric_diffs_vs_master": sym_diffs,
            "sheet_order_identical_to_master": order_matches,
            "special_key_1274A": {
                "normalized_key": "1274A",
                "raw_master_value": repr(master_map["1274A"]["_raw_flex_number"]),
                "raw_master_type": master_map["1274A"]["_raw_flex_type"],
                "master_excel_row": master_map["1274A"]["_excel_row"],
                "data_excel_row": data_map["1274A"]["_excel_row"],
                "comment_excel_row": cmt_map["1274A"]["_excel_row"],
            },
        },
        "pool_counts": {
            "total_records": len(records),
            "completed_analysis_yes": len(yes_records),
            "completed_analysis_no": len(no_records),
            "farnesane_in_yes": sum(1 for r in yes_records if r["fuel"] == "Farnesane"),
            "farnesane_in_no": sum(1 for r in no_records if r["fuel"] == "Farnesane"),
            "excluded_non_ignited_from_yes": [
                {
                    "flex_number": r["flex_number"],
                    "data_excel_row": r["data_row"],
                    "comment_excel_row": r["comment_row"],
                    "d0_mm": r["d0_mm"],
                    "khot": r["khot"],
                    "comment": r["comment"],
                }
                for r in excluded_non_ignited
            ],
            "candidate_analysis_pool_count": len(candidate_records),
            "candidate_fuels": dict(sorted(Counter(r["fuel"] for r in candidate_records).items())),
            "candidate_fibers": dict(sorted(Counter(str(r["fiber"]) for r in candidate_records).items())),
        },
        "field_stats_yes_146": stats_146,
        "field_stats_candidates_144": stats_144,
        "manager_check_comparison": manager_checks,
        "anomalies": {
            "dext_hot_gt_d0": {"count": len(dext_hot_gt_d0), "records": dext_hot_gt_d0},
            "gas_sum_not_1": {"count": len(gas_sum_anomalies), "records": gas_sum_anomalies},
            "flex_1213_record": {
                "flex_number": "1213",
                "excel_row": master_map["1213"]["_excel_row"],
                "workbook_o2": master_map["1213"]["Oxygen"],
                "workbook_n2": master_map["1213"]["Nitrogen"],
                "note": "Workbook/CSV record O2=0.17, N2=0.83 vs FLEX-1213_Summary.pdf YO2=0.210, YN2=0.790 (left unresolved).",
            },
            "dext_cool_zero_unresolved": {
                "count": len(zero_dext_cool_recs),
                "status": "raw_zero / interpretation_unresolved",
                "by_fuel": dict(sorted(Counter(r["fuel"] for r in zero_dext_cool_recs).items())),
                "by_pressure_atm": dict(
                    sorted((str(k), v) for k, v in Counter(r["pressure_atm"] for r in zero_dext_cool_recs).items())
                ),
                "extrap_cf_1_count": sum(1 for r in zero_dext_cool_recs if r["extrap_cf"] == 1),
                "reignitions_positive_count": sum(
                    1 for r in zero_dext_cool_recs if isinstance(r["reignitions"], (int, float)) and r["reignitions"] > 0
                ),
                "kcool_finite_count": sum(
                    1 for r in zero_dext_cool_recs if _classify_numeric_cell(r["kcool"])[1] is not None
                ),
            },
            "extrap_cf_1_candidates": {
                "count": len(extrap_1_recs),
                "status": "meaning_unverified",
                "kcool_finite_count": sum(
                    1 for r in extrap_1_recs if _classify_numeric_cell(r["kcool"])[1] is not None
                ),
                "dext_cool_positive_count": sum(
                    1 for r in extrap_1_recs if _classify_numeric_cell(r["dext_cool_mm"])[0] == "positive"
                ),
                "dext_cool_zero_count": sum(
                    1 for r in extrap_1_recs if _classify_numeric_cell(r["dext_cool_mm"])[0] == "zero"
                ),
            },
        },
        "comment_flags": comment_audit,
        "condition_coverage": {
            "q1_air_pressure_fuel_fiber": air_cells,
            "q2_pure_c12h26_pressure_gas_fiber": c12_cells,
        },
        "descriptive_focus_tables": {
            "q1_air_1atm_by_fiber": q1_air_1atm_by_fiber,
            "q2_pure_c12h26_1atm_he_fiber_yes": q2_he_1atm_fib_yes,
        },
        "model_feasibility_metrics": {
            "candidate_pool_n": len(candidate_records),
            "target_usable_counts": {
                "khot": stats_144[" khot ( mm^2/s )"]["finite_total"],
                "dext_hot_mm": stats_144["Dext, hot ( mm )"]["finite_total"],
                "kcool": stats_144["kcool ( mm^2/s )"]["finite_total"],
                "dext_cool_positive_only": stats_144["Dext,cool ( mm )"]["positive"],
                "dext_cool_zero_unresolved": stats_144["Dext,cool ( mm )"]["zero"],
                "dext_cool_missing_plus_nan": stats_144["Dext,cool ( mm )"]["non_numeric_total"],
                "reignitions_integer": stats_144["Reignitions"]["finite_total"],
            },
            "unique_condition_groups_144": len(cond_groups_all),
            "condition_groups_size_ge_2_in_144": sum(1 for v in cond_groups_all.values() if v >= 2),
            "unique_condition_groups_kcool": len(cond_groups_kcool),
            "condition_groups_size_ge_2_kcool": sum(1 for v in cond_groups_kcool.values() if v >= 2),
            "unique_condition_groups_dext_cool_pos": len(cond_groups_dc_pos),
            "condition_groups_size_ge_2_dext_cool_pos": sum(1 for v in cond_groups_dc_pos.values() if v >= 2),
            "reused_droplet_dependency_count": len(reused_ids),
            "reused_droplet_record_ids": reused_ids,
            "post_test_leakage_columns": [
                "HF Burn Time",
                "Peak HF Rad",
                "Peak Water Vapor Rad",
                "Rad Ratio",
                "Reignitions",
                "Extrap CF?",
                "2.5mm time",
                "Actual D",
                "2.5mm rad",
                "2.5mm narrow",
                "CF Rad Ratio",
                "2.5mm CF",
                "khot -> kcool / Dext,cool cross-target leakage",
            ],
        },
    }
    return audit


def main() -> None:
    audit = run_audit()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUT_JSON} ({OUT_JSON.stat().st_size} bytes)")
    for name, check in audit["manager_check_comparison"].items():
        print(f"  {name}: matches={check['matches']}")


if __name__ == "__main__":
    main()
