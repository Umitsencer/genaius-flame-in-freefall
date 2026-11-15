"""Separate read-only descriptive research module for NASA PSI-39 (Cool Flames Investigation — CFI).

This module intentionally stays separate from core `ExperimentRecord` / `DATASET_SPECS`
(`PSI-25` and `PSI-69`) and from prediction/safety-scoring pipelines. It joins the five
visible sheets of `PSI-39_Science Documents_CFI_DataSummary_Spreadsheet_Jan2021.xlsx`
strictly by stripped string `Flex Number` (preserving `'1274A'`), verifies key alignment
without trusting row order, validates optional pre-computed audit metadata only when the
workbook SHA-256 matches, and computes stratified descriptive statistics over the
full-air low/moderate-pressure cohort (`0.5 / 0.75 / 1.0 / 1.25 atm`).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WORKBOOK_RELPATH = (
    "data/raw/psi/matrices_and_readmes/PSI-39/"
    "PSI-39_Science Documents_CFI_DataSummary_Spreadsheet_Jan2021.xlsx"
)
PORTAL_CSV_RELPATH = "data/raw/psi/experimental_tables/PSI-39/PSI-39_Experimental table_CFI.csv"
AUDIT_JSON_RELPATH = "data/processed/cfi_eligibility_audit.json"
REPORT_RELPATH = "data/raw/psi/reports/PSI-39/PSI-39_Reports_CFI Science Final Report.pdf"
CFI_DOI = "10.60555/m6pj-a914"

EXPECTED_SHEETS = ("Master Sheet", "DATA", "Camera Settings", "Igniter", "Comments")
NON_IGNITED_YES_IDS = frozenset({"1212", "1235"})
SUPPORTED_PRESSURES_ATM = (0.5, 0.75, 1.0, 1.25)
SUPPORTED_FIBER_VALUES = ("Yes", "No")
FUEL_ORDER = (
    "C12H26",
    "75/25 C12H26/iso-dodecane",
    "60/40 C12H26/iso-dodecane",
)
SENSITIVITY_MODES = (
    "all_candidates",
    "exclude_reused_droplet",
    "exclude_extrap_cf_1",
    "conservative_comment_flags",
)
FULL_AIR_O2 = 0.21
FULL_AIR_N2 = 0.79
FULL_AIR_HE = 0.0
GAS_TOL = 1e-6

CFI_BOUNDARY_STATEMENTS: tuple[str, ...] = (
    "In-sample descriptive comparison only; no inferential significance test, regression model, "
    "causal attribution, fire-safety ranking, or extrapolation to Lunar/Mars/spacecraft atmospheres.",
    "Cell sizes are small and unbalanced (n often 1-3 outside 1.0 atm C12H26), with varying initial "
    "droplet diameters (D0) and residual-droplet dependence (reused_droplet) across sequential runs.",
    "Observations replicate existing CFI report/literature phenomena (cool flames, iso-dodecane NTC attenuation, "
    "fiber conduction); no claim of novel scientific discovery or literature priority is made.",
    "Dext,cool == 0 is preserved strictly as 'raw_zero / interpretation_unresolved' (never averaged into positive "
    "Dext,cool or equated with missing/NaN); Extrap CF? stays 'meaning_unverified' (Extrap CF?=0 is NOT claimed "
    "to be a verified direct unextrapolated measurement).",
    "Non-ignited dummy/vaporization rows (1212, 1235) are excluded from the 144 candidate pool; Farnesane (44 rows, "
    "all Completed Analysis?=No), gas-sum 0.97 anomalies (1219-1222), and FLEX-1213 source discrepancy (0.17 vs 0.21 O2) "
    "are preserved transparently without silent normalization or cross-study pooling with PSI-25/PSI-69.",
    "Conservative comment-flag exclusion relies on regex matches against raw operator Comments; matches do not "
    "independently verify physical corruption of every target nor guarantee that unflagged runs are artifact-free.",
)

CFI_SOURCE_REFERENCES: tuple[dict[str, Any], ...] = (
    {
        "source_id": "CFI_FINAL_REPORT_2020",
        "title": "Cool Flame Investigation (CFI) Science Final Report",
        "authors": "Vedha Nayagam and Daniel L. Dietrich",
        "date": "2020-07-23",
        "relpath": REPORT_RELPATH,
        "indexed_in_rag": False,
        "note": "Primary PDF is NOT yet indexed in the 503-chunk BM25 corpus; /api/evidence still blocks PSI-39.",
        "page_citations": [
            "PDF p. 1 (Title / Authors / Date 7-23-2020)",
            "PDF p. 5-6 (Printed pp. 4-5, Sec. 3a & 4a-4b: NTC kinetics, microgravity rationale, FLEX hardware reference)",
            "PDF p. 9 (Printed p. 8, Sec. 5.3 Fig. 4: Dext,cool vs ambient pressure for free-floated vs fiber-supported n-dodecane)",
            "PDF p. 10 (Printed p. 9, Sec. 5.4 Fig. 5: Effect of helium dilution on cool flame extinction and sooting behavior)",
        ],
    },
    {
        "source_id": "FLEX_TP_2015",
        "title": "Detailed Results From the Flame Extinguishment Experiment (FLEX) March 2009 to December 2011",
        "report_number": "NASA/TP-2015-216046",
        "official_citation_url": "https://ntrs.nasa.gov/citations/20150023456",
        "relpath": "data/raw/nasa_docs/20150023456_flex.pdf",
        "indexed_in_rag": True,
        "note": "Shared CIR/MDCA hardware and data-reduction procedure reference; droplet HiBMS uncertainty +/-50 um (Sec. 3.1.2, printed p. 8 / PDF p. 14) is separate from flame uncertainties (LLUV +/-200 um, color +/-250 um) and is not blindly generalized across all CFI soot/fiber regimes.",
        "page_citations": [
            "Sec. 3.1.2 (Printed p. 8 / PDF p. 14)",
            "Appendix A.1 (Printed p. 19 / PDF p. 25)",
        ],
    },
    {
        "source_id": "PSI_39_CATALOG",
        "title": "Cool Flames Investigation (NASA PSI-39 Dataset)",
        "doi": CFI_DOI,
        "relpath": WORKBOOK_RELPATH,
        "indexed_in_rag": False,
        "note": "Primary numeric source is the 5-sheet workbook (227 rows); PSI-39_Experimental table_CFI.csv holds only 87 metadata rows and no outcomes.",
        "page_citations": [
            "Sheets: Master Sheet, DATA, Camera Settings, Igniter, Comments (join key: strip(Flex Number), preserving '1274A')",
        ],
    },
)

# Context-aware comment regex matchers synced with the audited CFI Comments review
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


class CfiError(Exception):
    """Base error for optional CFI research module."""


class CfiLoadError(CfiError):
    """Raised when openpyxl or the primary CFI workbook is missing, corrupted, or misaligned."""


class CfiValidationError(CfiError, ValueError):
    """Raised when CFI API request parameters violate documented boundaries."""


@dataclass(frozen=True)
class CfiNumericCell:
    """Typed representation of one Excel numeric cell without conflating zero and missing."""

    raw_value: Any
    kind: str  # 'positive' | 'raw_zero' | 'negative' | 'empty' | 'literal_nan' | 'nonfinite_float' | 'other'
    value: float | None

    def to_raw_json(self) -> Any:
        if isinstance(self.raw_value, float) and not math.isfinite(self.raw_value):
            return str(self.raw_value)
        return self.raw_value


@dataclass(frozen=True)
class CfiRecord:
    """Single joined row across the five CFI workbook sheets."""

    flex_number: str
    raw_flex_number: str
    raw_flex_type: str
    sheet_rows: dict[str, int]
    test_date: str
    cir: str
    pressure_master_raw: str
    pressure_atm: float
    o2: float
    n2: float
    he: float
    gas_sum: float
    gas_anomaly: str | None
    fiber: str | None
    fuel_raw: str
    fuel: str
    completed_analysis: str
    excluded_non_ignited: bool
    in_candidate_pool: bool
    d0_mm: CfiNumericCell
    dext_hot_mm: CfiNumericCell
    khot: CfiNumericCell
    kcool: CfiNumericCell
    dext_cool_mm: CfiNumericCell
    extrap_cf_raw: Any
    reignitions: int | None
    comment: str
    comment_flags: tuple[str, ...]
    comment_excerpts: dict[str, str]
    impacted_by_comment_flags: bool


@dataclass(frozen=True)
class CfiDataset:
    """Validated in-memory CFI workbook representation plus provenance and audit cross-check."""

    workbook_relpath: str
    workbook_sha256: str
    sheet_names: tuple[str, ...]
    records: tuple[CfiRecord, ...]
    pool_counts: dict[str, Any]
    audit_comparison: dict[str, Any]
    source_discrepancies: tuple[dict[str, Any], ...]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm_fuel(raw: Any) -> str:
    s = str(raw or "").strip()
    if s == "C12H26":
        return "C12H26"
    if "[.75]/[.25]" in s:
        return "75/25 C12H26/iso-dodecane"
    if "[.60]/[.40]" in s:
        return "60/40 C12H26/iso-dodecane"
    return s


def _classify_cell(val: Any) -> CfiNumericCell:
    if val is None:
        return CfiNumericCell(raw_value="", kind="empty", value=None)
    if isinstance(val, bool):
        return CfiNumericCell(raw_value=val, kind="other", value=None)
    if isinstance(val, (int, float)):
        fval = float(val)
        if not math.isfinite(fval):
            return CfiNumericCell(raw_value=str(val), kind="nonfinite_float", value=None)
        if fval > 0.0:
            return CfiNumericCell(raw_value=fval, kind="positive", value=fval)
        if fval == 0.0:
            return CfiNumericCell(raw_value=0.0, kind="raw_zero", value=0.0)
        return CfiNumericCell(raw_value=fval, kind="negative", value=fval)
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return CfiNumericCell(raw_value="", kind="empty", value=None)
        if s.lower() == "nan":
            return CfiNumericCell(raw_value=val, kind="literal_nan", value=None)
        return CfiNumericCell(raw_value=val, kind="other", value=None)
    return CfiNumericCell(raw_value=str(val), kind="other", value=None)


def _finite_float_or_raise(val: Any, *, field_name: str, key: str) -> float:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise CfiLoadError(f"Non-numeric '{field_name}' cell for Flex Number '{key}'.")
    fval = float(val)
    if not math.isfinite(fval):
        raise CfiLoadError(f"Non-finite '{field_name}' cell for Flex Number '{key}'.")
    return fval


def _parse_pressure_master(raw: Any, key: str) -> float:
    text = str(raw or "").lower().replace("atm", "").strip()
    try:
        val = float(text)
    except ValueError as exc:
        raise CfiLoadError(f"Unparseable Master Sheet Pressure '{raw}' for Flex Number '{key}'.") from exc
    if not math.isfinite(val):
        raise CfiLoadError(f"Non-finite Master Sheet Pressure for Flex Number '{key}'.")
    return val


def _extract_flags(comment: str) -> tuple[tuple[str, ...], dict[str, str], bool]:
    flags: list[str] = []
    excerpts: dict[str, str] = {}
    impacted = False
    for fname, rule in _FLAG_RULES.items():
        inc = rule["include"]
        exc = rule["exclude"]
        m = inc.search(comment)
        if m and (exc is None or not exc.search(comment)):
            flags.append(fname)
            start = max(0, m.start() - 35)
            end = min(len(comment), m.end() + 85)
            snippet = " ".join(comment[start:end].split())
            excerpts[fname] = ("..." if start > 0 else "") + snippet + ("..." if end < len(comment) else "")
            if rule["impacts_measurement"]:
                impacted = True
    return tuple(flags), excerpts, impacted


def _load_sheet_by_key(ws: Any, title: str) -> dict[str, dict[str, Any]]:
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise CfiLoadError(f"Sheet '{title}' is empty.")
    headers = [str(c).strip() if c is not None else "" for c in rows[0]]
    if "Flex Number" not in headers:
        raise CfiLoadError(f"Sheet '{title}' lacks required 'Flex Number' column.")

    by_key: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for excel_row, values in enumerate(rows[1:], start=2):
        if all(v is None or (isinstance(v, str) and not v.strip()) for v in values):
            continue
        row_map = dict(zip(headers, values))
        raw_key = row_map.get("Flex Number")
        if raw_key is None or isinstance(raw_key, bool) or not str(raw_key).strip():
            raise CfiLoadError(f"Blank or invalid Flex Number at sheet '{title}' row {excel_row}.")
        key = str(raw_key).strip()
        if key in by_key:
            duplicates.append(key)
        by_key[key] = {
            "_excel_row": excel_row,
            "_raw_flex_number": repr(raw_key) if isinstance(raw_key, str) else str(raw_key),
            "_raw_flex_type": type(raw_key).__name__,
            **row_map,
        }
    if duplicates:
        raise CfiLoadError(f"Duplicate Flex Number keys in sheet '{title}': {duplicates[:5]}")
    return by_key


def _compute_pool_counts(records: tuple[CfiRecord, ...]) -> dict[str, Any]:
    yes_recs = [r for r in records if r.completed_analysis == "Yes"]
    no_recs = [r for r in records if r.completed_analysis != "Yes"]
    cand_recs = [r for r in records if r.in_candidate_pool]

    def _dext_breakdown(subset: list[CfiRecord]) -> dict[str, int]:
        cnt = Counter(r.dext_cool_mm.kind for r in subset)
        return {
            "positive": cnt.get("positive", 0),
            "raw_zero": cnt.get("raw_zero", 0),
            "empty": cnt.get("empty", 0),
            "literal_nan": cnt.get("literal_nan", 0),
        }

    return {
        "total_records": len(records),
        "completed_analysis_yes": len(yes_recs),
        "completed_analysis_no": len(no_recs),
        "excluded_non_ignited_ids": sorted(r.flex_number for r in records if r.excluded_non_ignited),
        "candidate_pool_count": len(cand_recs),
        "farnesane_in_yes": sum(1 for r in yes_recs if r.fuel == "Farnesane"),
        "farnesane_in_no": sum(1 for r in no_recs if r.fuel == "Farnesane"),
        "kcool_missing_in_yes_146": sum(1 for r in yes_recs if r.kcool.value is None),
        "kcool_missing_in_candidates_144": sum(1 for r in cand_recs if r.kcool.value is None),
        "dext_cool_yes_146_breakdown": _dext_breakdown(yes_recs),
        "dext_cool_candidates_144_breakdown": _dext_breakdown(cand_recs),
        "reused_droplet_in_candidates": sum(1 for r in cand_recs if "reused_droplet" in r.comment_flags),
        "extrap_cf_1_in_candidates": sum(1 for r in cand_recs if r.extrap_cf_raw == 1),
    }


def _compare_with_audit_json(
    repo_root: Path,
    workbook_sha256: str,
    pool_counts: dict[str, Any],
) -> dict[str, Any]:
    audit_path = repo_root / AUDIT_JSON_RELPATH
    if not audit_path.is_file():
        return {"status": "missing", "audit_relpath": AUDIT_JSON_RELPATH, "matches_computed": None}
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit_wb_sha = audit.get("sources", {}).get("workbook", {}).get("sha256")
    except (OSError, json.JSONDecodeError, AttributeError):
        return {"status": "unreadable_or_invalid", "audit_relpath": AUDIT_JSON_RELPATH, "matches_computed": None}

    if audit_wb_sha != workbook_sha256:
        return {
            "status": "stale_hash_mismatch",
            "audit_relpath": AUDIT_JSON_RELPATH,
            "audit_workbook_sha256": audit_wb_sha,
            "live_workbook_sha256": workbook_sha256,
            "matches_computed": False,
        }

    ap = audit.get("pool_counts", {})
    dc_144 = audit.get("field_stats_candidates_144", {}).get("Dext,cool ( mm )", {})
    kc_144 = audit.get("field_stats_candidates_144", {}).get("kcool ( mm^2/s )", {})
    checks = {
        "total_records": ap.get("total_records") == pool_counts["total_records"],
        "completed_analysis_yes": ap.get("completed_analysis_yes") == pool_counts["completed_analysis_yes"],
        "candidate_pool_count": ap.get("candidate_analysis_pool_count") == pool_counts["candidate_pool_count"],
        "farnesane_in_no": ap.get("farnesane_in_no") == pool_counts["farnesane_in_no"],
        "dext_cool_144_positive": dc_144.get("positive") == pool_counts["dext_cool_candidates_144_breakdown"]["positive"],
        "dext_cool_144_zero": dc_144.get("zero") == pool_counts["dext_cool_candidates_144_breakdown"]["raw_zero"],
        "dext_cool_144_empty": dc_144.get("empty") == pool_counts["dext_cool_candidates_144_breakdown"]["empty"],
        "dext_cool_144_literal_nan": (
            dc_144.get("literal_nan") == pool_counts["dext_cool_candidates_144_breakdown"]["literal_nan"]
        ),
        "kcool_144_missing": kc_144.get("non_numeric_total") == pool_counts["kcool_missing_in_candidates_144"],
    }
    all_ok = all(checks.values())
    return {
        "status": "verified_matching" if all_ok else "count_mismatch",
        "audit_relpath": AUDIT_JSON_RELPATH,
        "audit_workbook_sha256": audit_wb_sha,
        "matches_computed": all_ok,
        "check_details": checks,
    }


def load_cfi_dataset(repo_root: str | Path) -> CfiDataset:
    """Load and join the 5 visible sheets of the PSI-39 CFI Excel workbook read-only."""
    try:
        import openpyxl  # type: ignore[import-untyped]
    except ImportError as exc:
        raise CfiLoadError("openpyxl is required to load the PSI-39 CFI workbook.") from exc

    root = Path(repo_root).resolve()
    wb_path = root / WORKBOOK_RELPATH
    if not wb_path.is_file():
        raise CfiLoadError("PSI-39 CFI workbook is missing.")

    wb_sha256 = _sha256_file(wb_path)
    wb = None
    try:
        wb = openpyxl.load_workbook(wb_path, data_only=True, read_only=True)
        for name in EXPECTED_SHEETS:
            if name not in wb.sheetnames:
                raise CfiLoadError(f"Expected sheet '{name}' not found in CFI workbook.")
        sheet_maps = {name: _load_sheet_by_key(wb[name], name) for name in EXPECTED_SHEETS}
    except CfiLoadError:
        raise
    except Exception as exc:
        raise CfiLoadError("Failed to read PSI-39 CFI workbook.") from exc
    finally:
        if wb is not None:
            wb.close()

    master_map = sheet_maps["Master Sheet"]
    base_keys = set(master_map.keys())
    for name in EXPECTED_SHEETS[1:]:
        diff = base_keys ^ set(sheet_maps[name].keys())
        if diff:
            raise CfiLoadError(
                f"Flex Number key mismatch between Master Sheet and '{name}': {sorted(diff)[:5]}"
            )

    records: list[CfiRecord] = []
    for key, m in master_map.items():
        d = sheet_maps["DATA"][key]
        cam = sheet_maps["Camera Settings"][key]
        ign = sheet_maps["Igniter"][key]
        cmt = sheet_maps["Comments"][key]

        p_data = _finite_float_or_raise(d.get("Pressure (atm)"), field_name="Pressure (atm)", key=key)
        p_master = _parse_pressure_master(m.get("Pressure"), key=key)
        if abs(p_data - p_master) > 1e-6:
            raise CfiLoadError(
                f"Pressure mismatch for Flex Number '{key}': Master={p_master} atm vs DATA={p_data} atm."
            )

        o2 = _finite_float_or_raise(m.get("Oxygen"), field_name="Oxygen", key=key)
        n2 = _finite_float_or_raise(m.get("Nitrogen"), field_name="Nitrogen", key=key)
        he = _finite_float_or_raise(m.get("Helium"), field_name="Helium", key=key)
        gas_sum = round(o2 + n2 + he, 6)

        gas_anomaly: str | None = None
        if abs(gas_sum - 1.0) > GAS_TOL:
            gas_anomaly = "gas_sum_not_one"
        elif key == "1213":
            gas_anomaly = "source_discrepancy_flex_1213"

        completed = str(d.get("Completed Analysis?") or "").strip()
        excluded_non_ignited = completed == "Yes" and key in NON_IGNITED_YES_IDS
        in_candidate_pool = completed == "Yes" and not excluded_non_ignited

        fiber_raw = m.get("Fiber")
        fiber = str(fiber_raw).strip() if fiber_raw is not None and str(fiber_raw).strip() else None
        comment = str(cmt.get("Comments") or "")
        flags, excerpts, impacted = _extract_flags(comment)

        reig_raw = d.get("Reignitions")
        reignitions: int | None = None
        if isinstance(reig_raw, (int, float)) and not isinstance(reig_raw, bool) and math.isfinite(float(reig_raw)):
            reignitions = int(reig_raw)

        records.append(
            CfiRecord(
                flex_number=key,
                raw_flex_number=m["_raw_flex_number"],
                raw_flex_type=m["_raw_flex_type"],
                sheet_rows={
                    "Master Sheet": int(m["_excel_row"]),
                    "DATA": int(d["_excel_row"]),
                    "Camera Settings": int(cam["_excel_row"]),
                    "Igniter": int(ign["_excel_row"]),
                    "Comments": int(cmt["_excel_row"]),
                },
                test_date=str(m.get("Test Date") or ""),
                cir=str(m.get("CIR") or "").strip(),
                pressure_master_raw=str(m.get("Pressure") or ""),
                pressure_atm=p_data,
                o2=o2,
                n2=n2,
                he=he,
                gas_sum=gas_sum,
                gas_anomaly=gas_anomaly,
                fiber=fiber,
                fuel_raw=str(m.get("Fuel") or "").strip(),
                fuel=_norm_fuel(m.get("Fuel")),
                completed_analysis=completed,
                excluded_non_ignited=excluded_non_ignited,
                in_candidate_pool=in_candidate_pool,
                d0_mm=_classify_cell(d.get("D0 ( mm )")),
                dext_hot_mm=_classify_cell(d.get("Dext, hot ( mm )")),
                khot=_classify_cell(d.get("khot ( mm^2/s )")),
                kcool=_classify_cell(d.get("kcool ( mm^2/s )")),
                dext_cool_mm=_classify_cell(d.get("Dext,cool ( mm )")),
                extrap_cf_raw=d.get("Extrap CF?"),
                reignitions=reignitions,
                comment=comment,
                comment_flags=flags,
                comment_excerpts=excerpts,
                impacted_by_comment_flags=impacted,
            )
        )

    rec_tuple = tuple(records)
    pool_counts = _compute_pool_counts(rec_tuple)
    audit_comparison = _compare_with_audit_json(root, wb_sha256, pool_counts)

    discrepancies = (
        {
            "id": "FLEX_1213_O2_SOURCE_CONFLICT",
            "flex_number": "1213",
            "detail": (
                "Workbook Master Sheet and portal CSV record O2=0.17, N2=0.83, whereas archived "
                "FLEX-1213_Summary.pdf reports YO2=0.210, YN2=0.790. Retained without silent override; "
                "never placed into the full-air (0.21/0.79/0) cohort."
            ),
        },
        {
            "id": "GAS_SUM_0_97_ROWS",
            "flex_numbers": ["1219", "1220", "1221", "1222"],
            "detail": (
                "Master Sheet records O2=0.21, N2=0.76, He=0.0 (gas_sum=0.97). Never normalized to 1.00 "
                "and excluded from the full-air (0.21/0.79/0) cell."
            ),
        },
        {
            "id": "PORTAL_CSV_SUBSET_ONLY",
            "relpath": PORTAL_CSV_RELPATH,
            "detail": (
                "PSI portal CSV contains only 87 metadata rows without burning-rate or extinction measurements "
                "or Farnesane runs; excluded as a primary outcome source."
            ),
        },
        {
            "id": "FARNESANE_UNANALYZED_IN_WORKBOOK",
            "count": pool_counts["farnesane_in_no"],
            "detail": (
                "All 44 Farnesane records (FLEX 1388-1431) carry Completed Analysis?=No in the workbook and are "
                "excluded from the analyzed candidate pool (even though individual archived Summary PDFs exist in PSI)."
            ),
        },
    )

    return CfiDataset(
        workbook_relpath=WORKBOOK_RELPATH,
        workbook_sha256=wb_sha256,
        sheet_names=EXPECTED_SHEETS,
        records=rec_tuple,
        pool_counts=pool_counts,
        audit_comparison=audit_comparison,
        source_discrepancies=discrepancies,
    )


def _is_full_air_candidate(rec: CfiRecord) -> bool:
    return (
        rec.in_candidate_pool
        and rec.gas_anomaly is None
        and abs(rec.o2 - FULL_AIR_O2) <= GAS_TOL
        and abs(rec.n2 - FULL_AIR_N2) <= GAS_TOL
        and abs(rec.he - FULL_AIR_HE) <= GAS_TOL
    )


def build_cfi_schema(dataset: CfiDataset) -> dict[str, Any]:
    """Return descriptive schema, verified pool counts, filters, and boundaries for PSI-39 CFI."""
    air_in_scope = [
        r for r in dataset.records
        if _is_full_air_candidate(r)
        and any(abs(r.pressure_atm - p) <= 1e-6 for p in SUPPORTED_PRESSURES_ATM)
    ]
    present_pressures = sorted({round(r.pressure_atm, 4) for r in air_in_scope})
    present_fibers = sorted({r.fiber for r in air_in_scope if r.fiber in SUPPORTED_FIBER_VALUES}, reverse=True)
    present_fuels = [f for f in FUEL_ORDER if any(r.fuel == f for r in air_in_scope)]

    return {
        "investigation_id": "PSI-39",
        "acronym": "CFI",
        "title": "Cool Flames Investigation",
        "doi": CFI_DOI,
        "scope": {
            "separate_from_core_experiment_record": True,
            "queryable_in_core_analytics": False,
            "model_decision": "ERTELE",
            "cfi_report_indexed_in_rag": False,
            "description": (
                "Separate descriptive research endpoint for PSI-39 CFI; pools only stratified full-air "
                "(O2=0.21, N2=0.79, He=0) moderate pressures (0.5-1.25 atm) by single pressure and Fiber."
            ),
        },
        "workbook_provenance": {
            "relpath": dataset.workbook_relpath,
            "sha256": dataset.workbook_sha256,
            "sheets_joined": list(dataset.sheet_names),
            "join_key": "Flex Number (str.strip(); preserves '1274A')",
            "audit_json_comparison": dataset.audit_comparison,
        },
        "pool_summary": {
            **dataset.pool_counts,
            "candidate_pool_caveat": (
                "144 rows represent the pre-screened ignited 'candidate analysis pool' "
                "(227 total -> 146 Completed Analysis?=Yes -> minus non-ignited 1212 and 1235), "
                "NOT '144 clean/valid experiments'."
            ),
        },
        "fields": [
            {"name": "d0_mm", "source_column": "D0 ( mm )", "unit": "mm", "role": "measured_initial_diameter"},
            {"name": "dext_hot_mm", "source_column": "Dext, hot ( mm )", "unit": "mm", "role": "measured_hot_extinction_droplet_diameter"},
            {"name": "khot", "source_column": "khot ( mm^2/s )", "unit": "mm²/s", "role": "fitted_hot_flame_burning_rate"},
            {"name": "kcool", "source_column": "kcool ( mm^2/s )", "unit": "mm²/s", "role": "fitted_cool_flame_burning_rate"},
            {
                "name": "dext_cool_mm",
                "source_column": "Dext,cool ( mm )",
                "unit": "mm",
                "role": "cool_flame_extinction_diameter_with_raw_zero_unresolved",
            },
            {
                "name": "extrap_cf",
                "source_column": "Extrap CF?",
                "unit": "raw_binary_0_1",
                "role": "meaning_unverified",
            },
            {"name": "pressure_atm", "source_column": "Pressure (atm)", "unit": "atm", "role": "ambient_pressure"},
            {"name": "fiber", "source_column": "Fiber", "unit": "categorical (Yes|No)", "role": "support_strata_required"},
            {"name": "fuel", "source_column": "Fuel", "unit": "categorical", "role": "fuel_group"},
        ],
        "filters": {
            "atmosphere": {"o2": FULL_AIR_O2, "n2": FULL_AIR_N2, "he": FULL_AIR_HE, "label": "Full Air Only"},
            "supported_pressures_atm": present_pressures,
            "required_fiber_values": present_fibers,
            "candidate_fuels_in_scope": present_fuels,
            "excluded_from_analyzed_pool": ["Farnesane (44 Completed Analysis?=No rows)", "1212", "1235"],
            "sensitivity_modes": [
                {
                    "id": "all_candidates",
                    "label": "All candidate records in stratified cell (default)",
                },
                {
                    "id": "exclude_reused_droplet",
                    "label": "Exclude active reused_droplet comment flags",
                },
                {
                    "id": "exclude_extrap_cf_1",
                    "label": "Sensitivity excluding Extrap CF?=1 (Extrap CF?=0 remains meaning_unverified)",
                },
                {
                    "id": "conservative_comment_flags",
                    "label": "Konservatif duyarlılık senaryosu (exclude all impacting Comment regex flags)",
                    "caveat": (
                        "Regex matches against raw Comments do not prove every flag corrupts every target "
                        "nor prove unflagged rows are artifact-free."
                    ),
                },
            ],
            "default_analysis_example": {
                "pressure_atm": 1.0,
                "fiber": "Yes",
                "fuel": None,
                "sensitivity_mode": "all_candidates",
            },
        },
        "source_discrepancies": list(dataset.source_discrepancies),
        "limitations": list(CFI_BOUNDARY_STATEMENTS),
        "source_references": [dict(ref) for ref in CFI_SOURCE_REFERENCES],
    }


def _apply_sensitivity_filter(recs: list[CfiRecord], mode: str) -> list[CfiRecord]:
    if mode == "all_candidates":
        return recs
    if mode == "exclude_reused_droplet":
        return [r for r in recs if "reused_droplet" not in r.comment_flags]
    if mode == "exclude_extrap_cf_1":
        return [r for r in recs if r.extrap_cf_raw != 1]
    if mode == "conservative_comment_flags":
        return [r for r in recs if not r.impacted_by_comment_flags]
    raise CfiValidationError(f"Unsupported sensitivity_mode: {mode!r}")


def _describe_fuel_group(
    fuel: str,
    base_recs: list[CfiRecord],
    filtered_recs: list[CfiRecord],
    *,
    sensitivity_mode: str,
    workbook_relpath: str,
    workbook_sha256: str,
) -> dict[str, Any]:
    d0_vals = [r.d0_mm.value for r in filtered_recs if r.d0_mm.value is not None and r.d0_mm.value > 0]
    kcool_pts: list[dict[str, Any]] = []
    kcool_vals: list[float] = []
    kcool_missing = 0

    dc_pos_pts: list[dict[str, Any]] = []
    dc_pos_vals: list[float] = []
    dc_zero_ids: list[str] = []
    dc_empty_ids: list[str] = []
    dc_nan_ids: list[str] = []

    extrap_counts: Counter[str] = Counter()
    flag_counts: Counter[str] = Counter()
    dext_hot_gt_d0_ids: list[str] = []
    record_locations: list[dict[str, Any]] = []

    for r in filtered_recs:
        ext_key = str(r.extrap_cf_raw) if r.extrap_cf_raw is not None else "empty"
        extrap_counts[ext_key] += 1
        for fl in r.comment_flags:
            flag_counts[fl] += 1
        if r.dext_hot_mm.value is not None and r.d0_mm.value is not None and r.dext_hot_mm.value > r.d0_mm.value:
            dext_hot_gt_d0_ids.append(r.flex_number)

        record_locations.append(
            {
                "flex_number": r.flex_number,
                "raw_flex_number": r.raw_flex_number,
                "master_row": r.sheet_rows["Master Sheet"],
                "data_row": r.sheet_rows["DATA"],
                "comments_row": r.sheet_rows["Comments"],
                "workbook_relpath": workbook_relpath,
                "workbook_sha256": workbook_sha256,
            }
        )

        if r.kcool.value is not None:
            kcool_vals.append(r.kcool.value)
            kcool_pts.append(
                {
                    "flex_number": r.flex_number,
                    "data_excel_row": r.sheet_rows["DATA"],
                    "comments_excel_row": r.sheet_rows["Comments"],
                    "raw_value": r.kcool.to_raw_json(),
                    "value": round(r.kcool.value, 6),
                    "extrap_cf": r.extrap_cf_raw,
                    "flags": list(r.comment_flags),
                }
            )
        else:
            kcool_missing += 1

        if r.dext_cool_mm.kind == "positive" and r.dext_cool_mm.value is not None:
            dc_pos_vals.append(r.dext_cool_mm.value)
            dc_pos_pts.append(
                {
                    "flex_number": r.flex_number,
                    "data_excel_row": r.sheet_rows["DATA"],
                    "comments_excel_row": r.sheet_rows["Comments"],
                    "raw_value": r.dext_cool_mm.to_raw_json(),
                    "value": round(r.dext_cool_mm.value, 6),
                    "extrap_cf": r.extrap_cf_raw,
                    "flags": list(r.comment_flags),
                }
            )
        elif r.dext_cool_mm.kind == "raw_zero":
            dc_zero_ids.append(r.flex_number)
        elif r.dext_cool_mm.kind == "literal_nan":
            dc_nan_ids.append(r.flex_number)
        else:
            dc_empty_ids.append(r.flex_number)

    sens_label = (
        "konservatif duyarlılık senaryosu (regex comment flags excluded)"
        if sensitivity_mode == "conservative_comment_flags"
        else sensitivity_mode
    )

    return {
        "fuel": fuel,
        "sensitivity_mode": sensitivity_mode,
        "sensitivity_label": sens_label,
        "n_candidates_before_sensitivity": len(base_recs),
        "n_candidates": len(filtered_recs),
        "record_ids": [r.flex_number for r in filtered_recs],
        "d0_range_mm": (
            {"min": round(min(d0_vals), 6), "max": round(max(d0_vals), 6)} if d0_vals else None
        ),
        "kcool": {
            "unit": "mm²/s",
            "n_finite": len(kcool_vals),
            "n_missing": kcool_missing,
            "median": round(statistics.median(kcool_vals), 6) if kcool_vals else None,
            "min": round(min(kcool_vals), 6) if kcool_vals else None,
            "max": round(max(kcool_vals), 6) if kcool_vals else None,
            "raw_points": kcool_pts,
        },
        "dext_cool_mm": {
            "unit": "mm",
            "n_positive": len(dc_pos_vals),
            "n_raw_zero_unresolved": len(dc_zero_ids),
            "n_empty": len(dc_empty_ids),
            "n_literal_nan": len(dc_nan_ids),
            "raw_zero_record_ids": dc_zero_ids,
            "empty_record_ids": dc_empty_ids,
            "literal_nan_record_ids": dc_nan_ids,
            "positive_median": round(statistics.median(dc_pos_vals), 6) if dc_pos_vals else None,
            "positive_min": round(min(dc_pos_vals), 6) if dc_pos_vals else None,
            "positive_max": round(max(dc_pos_vals), 6) if dc_pos_vals else None,
            "positive_points": dc_pos_pts,
            "interpretation_note": (
                "Dext,cool == 0 is retained strictly as raw_zero / interpretation_unresolved; "
                "never merged into missing, literal NaN, or positive Dext,cool statistics."
            ),
        },
        "extrap_cf": {
            "meaning_status": "meaning_unverified",
            "raw_distribution": dict(sorted(extrap_counts.items())),
            "note": (
                "Extrap CF?=0 is NOT presented as a verified direct unextrapolated measurement; "
                "primary reports do not define the exact Extrap CF? column rule."
            ),
        },
        "quality_flags": {
            "flag_counts": {fname: flag_counts.get(fname, 0) for fname in _FLAG_RULES},
            "flags_by_record": {
                r.flex_number: list(r.comment_flags) for r in filtered_recs if r.comment_flags
            },
            "comment_excerpts": {
                r.flex_number: dict(r.comment_excerpts) for r in filtered_recs if r.comment_excerpts
            },
            "dext_hot_gt_d0_record_ids": dext_hot_gt_d0_ids,
            "regex_scope_note": (
                "Comment flags come from regex matching against raw Comments text, not independent video verification."
            ),
        },
        "source_locations": record_locations,
    }


def run_cfi_analysis(
    dataset: CfiDataset,
    *,
    pressure_atm: float = 1.0,
    fiber: str = "Yes",
    fuel: str | None = None,
    sensitivity_mode: str = "all_candidates",
) -> dict[str, Any]:
    """Compute stratified descriptive CFI output within full-air low/moderate pressures."""
    if isinstance(pressure_atm, bool) or not isinstance(pressure_atm, (int, float)):
        raise CfiValidationError("pressure_atm must be one of 0.5, 0.75, 1.0, or 1.25.")
    p_val = float(pressure_atm)
    if not math.isfinite(p_val) or not any(abs(p_val - p) <= 1e-6 for p in SUPPORTED_PRESSURES_ATM):
        raise CfiValidationError(
            "pressure_atm must be one of 0.5, 0.75, 1.0, or 1.25 atm (different pressures are never pooled)."
        )

    if not isinstance(fiber, str) or fiber not in SUPPORTED_FIBER_VALUES:
        raise CfiValidationError("fiber is required and must be strictly 'Yes' or 'No'.")

    if fuel is not None:
        if not isinstance(fuel, str) or fuel not in FUEL_ORDER:
            raise CfiValidationError(
                "fuel must be null or one of: 'C12H26', '75/25 C12H26/iso-dodecane', '60/40 C12H26/iso-dodecane' "
                "(Farnesane has 0 Completed Analysis?=Yes records and is excluded)."
            )
        target_fuels = (fuel,)
    else:
        target_fuels = FUEL_ORDER

    if not isinstance(sensitivity_mode, str) or sensitivity_mode not in SENSITIVITY_MODES:
        raise CfiValidationError(
            "sensitivity_mode must be one of: all_candidates, exclude_reused_droplet, "
            "exclude_extrap_cf_1, conservative_comment_flags."
        )

    cell_records = [
        r for r in dataset.records
        if _is_full_air_candidate(r)
        and abs(r.pressure_atm - p_val) <= 1e-6
        and r.fiber == fiber
    ]

    groups: list[dict[str, Any]] = []
    total_before = 0
    total_after = 0
    for fname in target_fuels:
        base_recs = [r for r in cell_records if r.fuel == fname]
        filtered_recs = _apply_sensitivity_filter(base_recs, sensitivity_mode)
        total_before += len(base_recs)
        total_after += len(filtered_recs)
        if filtered_recs or fuel is not None:
            groups.append(
                _describe_fuel_group(
                    fname,
                    base_recs,
                    filtered_recs,
                    sensitivity_mode=sensitivity_mode,
                    workbook_relpath=dataset.workbook_relpath,
                    workbook_sha256=dataset.workbook_sha256,
                )
            )

    if total_after == 0:
        groups = []

    status = "OK" if total_after > 0 else "NO_EVIDENCE"
    return {
        "investigation_id": "PSI-39",
        "acronym": "CFI",
        "status": status,
        "applied_filters": {
            "atmosphere": {"o2": FULL_AIR_O2, "n2": FULL_AIR_N2, "he": FULL_AIR_HE},
            "pressure_atm": p_val,
            "fiber": fiber,
            "fuel": fuel,
            "sensitivity_mode": sensitivity_mode,
        },
        "total_candidates_in_cell": total_before,
        "total_returned_records": total_after,
        "fuel_groups": groups,
        "pool_summary": dict(dataset.pool_counts),
        "workbook_provenance": {
            "relpath": dataset.workbook_relpath,
            "sha256": dataset.workbook_sha256,
            "audit_json_comparison": dataset.audit_comparison,
        },
        "source_discrepancies": list(dataset.source_discrepancies),
        "limitations": list(CFI_BOUNDARY_STATEMENTS),
        "source_references": [dict(ref) for ref in CFI_SOURCE_REFERENCES],
    }
