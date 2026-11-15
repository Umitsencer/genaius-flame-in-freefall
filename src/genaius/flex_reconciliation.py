"""Forensic reconciliation between PSI-69 FLEX CSV and NASA/TP-2015-216046 Table IX.

Keeps raw sources untouched and produces a standalone provenance-linked table
explaining exact count differences (274 vs 276 tests; 50 vs 51 helium runs),
missing Table IX sequence numbers, duplicate identifiers, and corrupted fields.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .data.contracts import MeasurementStatus
from .data.loader import load_investigation_records

RECONCILIATION_SCHEMA_VERSION = "1.0.0"
FLEX_PDF_REL_PATH = Path("data/raw/nasa_docs/20150023456_flex.pdf")
FLEX_CSV_REL_PATH = Path("data/raw/psi/experimental_tables/PSI-69/PSI-69_Experimental table_FLEX.csv")
DEFAULT_RECONCILIATION_REL_PATH = Path("data/processed/flex_reconciliation.json")

_TABLE_IX_PAGE_RANGE = range(25, 34)  # PDF pages 26-34 (0-indexed 25..33)
_TABLE_IX_ROW_RE = re.compile(
    r"^FLEX[–-](\d+)\s+"
    r"(\S+)\s+"
    r"(\d+/\d+/\d+)\s+"
    r"(\S+)\s+"
    r"(Methanol|Heptane)\s+"
    r"(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+"
    r"(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+"
    r"(Extinction|Disruption|Completion)\b"
)

_MEASUREMENT_PAIRS: tuple[tuple[str, str], ...] = (
    ("ambient_pressure_mmhg", "ambient_pressure_kpa"),
    ("initial_o2_mol_frac", "initial_o2_flex_mol_pct"),
    ("initial_n2_mol_frac", "initial_n2_flex_mol_pct"),
    ("initial_co2_mol_frac", "initial_co2_flex_mol_pct"),
    ("initial_he_mol_frac", "initial_he_flex_mol_pct"),
    ("droplet_initial_diameter_mm", "droplet_initial_diameter_mm"),
    ("visible_flame_extinction_diameter_mm", "visible_flame_extinction_diameter_mm"),
    ("burning_rate_mm2_s", "burning_rate_mm2_s"),
    ("burn_time_s", "burn_time_s"),
)


class FlexReconciliationError(RuntimeError):
    """Raised when FLEX Table IX / PSI-69 reconciliation or artifact checks fail."""


@dataclass(frozen=True)
class TableIXRow:
    """Single parsed row from NASA/TP-2015-216046 Table IX."""

    tp_number: int
    tp_test_label: str
    flex_identifier: str
    date_raw: str
    gmt_raw: str
    fuel: str
    pressure_raw: str
    o2_raw: str
    n2_raw: str
    co2_raw: str
    he_raw: str
    d0_raw: str
    d_ext_raw: str
    burning_rate_raw: str
    burn_time_raw: str
    test_end: str
    pdf_page_1based: int

    def raw_measurement_map(self) -> dict[str, str]:
        return {
            "ambient_pressure_mmhg": self.pressure_raw,
            "initial_o2_mol_frac": self.o2_raw,
            "initial_n2_mol_frac": self.n2_raw,
            "initial_co2_mol_frac": self.co2_raw,
            "initial_he_mol_frac": self.he_raw,
            "droplet_initial_diameter_mm": self.d0_raw,
            "visible_flame_extinction_diameter_mm": self.d_ext_raw,
            "burning_rate_mm2_s": self.burning_rate_raw,
            "burn_time_s": self.burn_time_raw,
        }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _parse_tp_number(raw: str) -> float | None:
    cleaned = raw.strip()
    if cleaned in {"–", "-", ""}:
        return None
    if cleaned.startswith("~"):
        cleaned = cleaned[1:].strip()
    return float(cleaned)


def parse_table_ix_rows(pdf_path: Path) -> list[TableIXRow]:
    """Parse all 276 Table IX rows from NASA/TP-2015-216046."""
    if not pdf_path.exists():
        raise FlexReconciliationError(f"Missing NASA/TP-2015-216046 PDF: {pdf_path}")
    reader = PdfReader(str(pdf_path))
    if len(reader.pages) < 34:
        raise FlexReconciliationError(f"Unexpected PDF page count ({len(reader.pages)}) in {pdf_path}")

    rows: list[TableIXRow] = []
    for page_idx in _TABLE_IX_PAGE_RANGE:
        text = reader.pages[page_idx].extract_text() or ""
        for line in text.splitlines():
            match = _TABLE_IX_ROW_RE.match(line.strip())
            if not match:
                continue
            groups = match.groups()
            tp_num = int(groups[0])
            rows.append(
                TableIXRow(
                    tp_number=tp_num,
                    tp_test_label=f"FLEX-{tp_num:03d}",
                    flex_identifier=groups[1],
                    date_raw=groups[2],
                    gmt_raw=groups[3],
                    fuel=groups[4],
                    pressure_raw=groups[5],
                    o2_raw=groups[6],
                    n2_raw=groups[7],
                    co2_raw=groups[8],
                    he_raw=groups[9],
                    d0_raw=groups[10],
                    d_ext_raw=groups[11],
                    burning_rate_raw=groups[12],
                    burn_time_raw=groups[13],
                    test_end=groups[14],
                    pdf_page_1based=page_idx + 1,
                )
            )
    if len(rows) != 276:
        raise FlexReconciliationError(f"Expected 276 Table IX rows in NASA TP PDF, parsed {len(rows)}.")
    return rows


def build_flex_reconciliation(repo_root: str | Path) -> dict[str, Any]:
    """Build full provenance-linked Table IX vs PSI-69 CSV reconciliation payload."""
    root = Path(repo_root).resolve()
    pdf_path = root / FLEX_PDF_REL_PATH
    csv_path = root / FLEX_CSV_REL_PATH
    if not csv_path.exists():
        raise FlexReconciliationError(f"Missing PSI-69 CSV: {csv_path}")

    table_ix_rows = parse_table_ix_rows(pdf_path)
    psi_records, psi_meta = load_investigation_records("PSI-69", root)
    if len(psi_records) != 274:
        raise FlexReconciliationError(f"Expected 274 PSI-69 records, loaded {len(psi_records)}.")

    tp_by_num = {row.tp_number: row for row in table_ix_rows}
    if len(tp_by_num) != 276:
        raise FlexReconciliationError("Duplicate FLEX-NNN numbers detected while parsing Table IX.")

    missing_seq = sorted(set(range(1, 281)) - set(tp_by_num))
    tp_only_rows = [row for row in table_ix_rows if row.tp_number in {216, 230}]
    shared_tp_rows = [row for row in table_ix_rows if row.tp_number not in {216, 230}]
    if len(shared_tp_rows) != len(psi_records):
        raise FlexReconciliationError("Shared Table IX rows do not match PSI-69 CSV row count.")

    aligned_rows: list[dict[str, Any]] = []
    shared_mismatches: list[dict[str, Any]] = []
    gas_sum_out_of_tolerance = 0

    for tp_row, rec in zip(shared_tp_rows, psi_records):
        anomalies: list[str] = []
        tp_raw_map = tp_row.raw_measurement_map()
        measurements_summary: dict[str, Any] = {}

        if tp_row.flex_identifier != rec.normalized_fields["flex_identifier"]:
            shared_mismatches.append({"csv_test_id": rec.test_id, "tp_test_label": tp_row.tp_test_label, "field": "flex_identifier"})
        if tp_row.fuel != rec.normalized_fields["fuel_norm"]:
            shared_mismatches.append({"csv_test_id": rec.test_id, "tp_test_label": tp_row.tp_test_label, "field": "fuel"})
        if tp_row.test_end != rec.normalized_fields["test_end"]:
            shared_mismatches.append({"csv_test_id": rec.test_id, "tp_test_label": tp_row.tp_test_label, "field": "test_end"})

        for out_key, csv_key in _MEASUREMENT_PAIRS:
            meas = rec.measurements[csv_key]
            tp_val = _parse_tp_number(tp_raw_map[out_key])
            csv_val = meas.parsed_value
            if (csv_val is None) != (tp_val is None) or (
                csv_val is not None and tp_val is not None and abs(csv_val - tp_val) > 1e-6
            ):
                shared_mismatches.append(
                    {
                        "csv_test_id": rec.test_id,
                        "tp_test_label": tp_row.tp_test_label,
                        "field": out_key,
                        "csv_value": csv_val,
                        "tp_value": tp_val,
                    }
                )
            measurements_summary[out_key] = csv_val

        p_val = measurements_summary["ambient_pressure_mmhg"]
        o2 = measurements_summary["initial_o2_mol_frac"] or 0.0
        n2 = measurements_summary["initial_n2_mol_frac"] or 0.0
        co2 = measurements_summary["initial_co2_mol_frac"] or 0.0
        he = measurements_summary["initial_he_mol_frac"] or 0.0
        gas_sum = round(o2 + n2 + co2 + he, 4)
        if not (0.98 <= gas_sum <= 1.01):
            gas_sum_out_of_tolerance += 1

        if rec.normalized_fields["flex_identifier"] == "193F001":
            anomalies.append("duplicate_flex_identifier_193F001_distinct_droplets")
        if p_val is not None and p_val <= 0:
            anomalies.append("corrupted_zero_pressure_in_table_ix_and_csv_vs_table_vi_0_70_atm")
        if rec.measurements["droplet_initial_diameter_mm"].status != MeasurementStatus.MEASURED:
            anomalies.append("missing_initial_diameter")
        if rec.measurements["burning_rate_mm2_s"].status != MeasurementStatus.MEASURED:
            anomalies.append("missing_burning_rate")
        if rec.measurements["burn_time_s"].status == MeasurementStatus.APPROXIMATE:
            anomalies.append("approximate_burn_time")
        if rec.test_id == "129":
            anomalies.append("extinction_diameter_slightly_exceeds_d0")

        aligned_rows.append(
            {
                "status": "MATCHED",
                "psi_test_id": rec.test_id,
                "record_pk": rec.record_pk,
                "csv_row": rec.source.physical_line_start,
                "tp_number": tp_row.tp_number,
                "tp_test_label": tp_row.tp_test_label,
                "tp_pdf_page": tp_row.pdf_page_1based,
                "id_offset": int(rec.test_id) - tp_row.tp_number,
                "flex_identifier": tp_row.flex_identifier,
                "fuel": tp_row.fuel,
                "date_csv": rec.normalized_fields["test_date"],
                "date_tp": tp_row.date_raw,
                "gmt": rec.normalized_fields["test_gmt"],
                "test_end": tp_row.test_end,
                "gas_sum_csv": gas_sum,
                "measurements": measurements_summary,
                "anomalies": anomalies,
            }
        )

    if shared_mismatches:
        raise FlexReconciliationError(
            f"Unexpected mismatches across aligned shared rows: {shared_mismatches[:5]}"
        )

    tp_only_entries = []
    for row in tp_only_rows:
        tp_raw_map = row.raw_measurement_map()
        parsed_map = {k: _parse_tp_number(v) for k, v in tp_raw_map.items()}
        notes = (
            "Reported in NASA/TP-2015-216046 Table IX only; omitted from PSI-69 CSV release. "
            "Figure 217 caption prints 0.15/0.84 O2/N2 while Table IX lists .15/.85."
            if row.tp_number == 216
            else "Reported in NASA/TP-2015-216046 Table IX only; omitted from PSI-69 CSV release. "
            "Contains 0.05 He, accounting directly for the 51 vs 50 helium-diluted test difference. "
            "Figure 230 caption contains typo 0.20/0375/0.05."
        )
        tp_only_entries.append(
            {
                "status": "TP_TABLE_IX_ONLY",
                "psi_test_id": None,
                "record_pk": None,
                "csv_row": None,
                "tp_number": row.tp_number,
                "tp_test_label": row.tp_test_label,
                "tp_pdf_page": row.pdf_page_1based,
                "flex_identifier": row.flex_identifier,
                "fuel": row.fuel,
                "date_tp": row.date_raw,
                "gmt": row.gmt_raw,
                "test_end": row.test_end,
                "measurements": parsed_map,
                "anomalies": ["omitted_from_psi69_csv_reason_unresolved"],
                "notes": notes,
            }
        )

    all_entries = sorted(aligned_rows + tp_only_entries, key=lambda item: item["tp_number"])

    psi_counts = _outcome_counts([row["test_end"] for row in aligned_rows])
    tp_counts = _outcome_counts([row.test_end for row in table_ix_rows])
    psi_he = sum(1 for row in aligned_rows if (row["measurements"]["initial_he_mol_frac"] or 0.0) > 0)
    tp_he = sum(1 for row in table_ix_rows if (_parse_tp_number(row.he_raw) or 0.0) > 0)

    return {
        "schema_version": RECONCILIATION_SCHEMA_VERSION,
        "sources": {
            "psi69_csv": {
                "path": FLEX_CSV_REL_PATH.as_posix(),
                "sha256": psi_meta["sha256"],
                "row_count": len(psi_records),
            },
            "nasa_tp_2015_216046_table_ix": {
                "path": FLEX_PDF_REL_PATH.as_posix(),
                "sha256": _sha256_file(pdf_path),
                "pdf_pages": "26-34",
                "row_count": len(table_ix_rows),
                "sequence_range": "FLEX-001..FLEX-280",
                "skipped_sequence_numbers": missing_seq,
            },
        },
        "reconciliation_summary": {
            "psi69_csv_rows": len(psi_records),
            "table_ix_rows": len(table_ix_rows),
            "matched_shared_rows": len(aligned_rows),
            "table_ix_only_rows": len(tp_only_entries),
            "table_ix_only_labels": [item["tp_test_label"] for item in tp_only_entries],
            "shared_row_value_mismatches": len(shared_mismatches),
            "psi69_helium_runs": psi_he,
            "table_ix_helium_runs": tp_he,
            "helium_difference_explained_by": "FLEX-230 (H01H103, 0.20 O2 / 0.75 N2 / 0.05 He, Disruption)",
            "psi69_outcomes": psi_counts,
            "table_ix_outcomes": tp_counts,
            "co2_he_overlap_count": sum(
                1
                for row in aligned_rows
                if (row["measurements"]["initial_co2_mol_frac"] or 0.0) > 0
                and (row["measurements"]["initial_he_mol_frac"] or 0.0) > 0
            ),
            "gas_sum_out_of_0_98_to_1_01_count": gas_sum_out_of_tolerance,
            "known_anomalies": {
                "missing_table_ix_sequence_numbers": missing_seq,
                "duplicate_flex_identifier": {
                    "flex_identifier": "193F001",
                    "psi_test_ids": ["70", "73"],
                    "tp_labels": ["FLEX-070", "FLEX-073"],
                    "note": "Same timestamp/atmosphere, distinct droplet diameters and burning rates.",
                },
                "corrupted_zero_pressure": {
                    "psi_test_id": "114",
                    "tp_label": "FLEX-114",
                    "flex_identifier": "C11M201",
                    "table_ix_and_csv_value": 0.0,
                    "table_vi_and_fig_118_value": "0.70 atm (~532 mmHg nominal)",
                    "note": "Raw Table IX and CSV record pressure=0; excluded from predictive modeling rather than silently imputed.",
                },
                "burning_rate_unit_note": (
                    "Both PSI-69 CSV (col label '[mm]') and NASA/TP-2015-216046 Appendix A.1 state burning rate K is "
                    "the linear d^2 vs t regression slope in mm^2/s."
                ),
            },
            "unresolved": [
                {
                    "item": "omission_of_flex_216_and_flex_230_from_psi69_csv",
                    "status": "unresolved",
                    "details": (
                        "Neither NASA/TP-2015-216046 nor PSI-69_Experimental table_FLEX.csv documents why FLEX-216 and FLEX-230 "
                        "were excluded when NASA compiled the 274-row PSI CSV release. Raw PSI-69 files are kept unmodified."
                    ),
                },
                {
                    "item": "skipped_table_ix_ids_156_205_213_228",
                    "status": "unresolved",
                    "details": (
                        "IDs FLEX-156, FLEX-205, FLEX-213, and FLEX-228 do not appear anywhere in NASA/TP-2015-216046."
                    ),
                },
            ],
        },
        "entries": all_entries,
    }


def _outcome_counts(ends: list[str]) -> dict[str, Any]:
    total = len(ends)
    counts = {
        cat: sum(1 for item in ends if item == cat)
        for cat in ("Extinction", "Disruption", "Completion")
    }
    return {
        **counts,
        "percentages": {cat: round(100.0 * count / total, 2) if total else 0.0 for cat, count in counts.items()},
    }


def save_flex_reconciliation(repo_root: str | Path, output_path: Path | None = None) -> tuple[dict[str, Any], Path]:
    """Generate and persist the standalone FLEX reconciliation JSON artifact."""
    root = Path(repo_root).resolve()
    payload = build_flex_reconciliation(root)
    target = output_path or (root / DEFAULT_RECONCILIATION_REL_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload, target


def load_flex_reconciliation(repo_root: str | Path) -> dict[str, Any]:
    """Load and verify the precomputed FLEX reconciliation JSON against live PSI-69 CSV SHA-256."""
    root = Path(repo_root).resolve()
    artifact_path = root / DEFAULT_RECONCILIATION_REL_PATH
    csv_path = root / FLEX_CSV_REL_PATH
    if not artifact_path.exists():
        raise FlexReconciliationError(f"Reconciliation artifact not found: {artifact_path}")
    if not csv_path.exists():
        raise FlexReconciliationError(f"Missing PSI-69 CSV: {csv_path}")
    data = json.loads(artifact_path.read_text(encoding="utf-8"))
    if data.get("schema_version") != RECONCILIATION_SCHEMA_VERSION:
        raise FlexReconciliationError("Unsupported FLEX reconciliation schema version.")
    expected_csv_sha = data.get("sources", {}).get("psi69_csv", {}).get("sha256")
    actual_csv_sha = _sha256_file(csv_path)
    if expected_csv_sha != actual_csv_sha:
        raise FlexReconciliationError("FLEX reconciliation CSV SHA-256 mismatch with workspace CSV.")
    return data
