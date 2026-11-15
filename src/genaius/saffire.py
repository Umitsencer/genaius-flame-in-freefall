"""Read-only, provenance-preserving reference loader and API builder for PSI-99 SAFFIRE-II.

Keeps SAFFIRE-II strictly separate from the PSI-25/PSI-69 core ExperimentRecord pool
and from PSI-39 CFI. Preserves raw cells, unresolved discrepancies, auxiliary flow-vis
and footnote rows, and ReadMe DOCX locations without computing safety rankings, pooled
means, percentage differences, or causal gravity claims.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SAFFIRE_CSV_RELPATH = (
    "data/raw/psi/experimental_tables/PSI-99/PSI-99_Experimental table_SAFFIRE-2.csv"
)
SAFFIRE_README_RELPATH = (
    "data/raw/psi/matrices_and_readmes/PSI-99/PSI-99_Science Documents_SAFFIRE-II Readme.docx"
)

EXPECTED_CSV_HEADERS: tuple[str, ...] = (
    "Sample Number",
    "Material",
    "Samle Thickness ",
    "Sample Length ",
    "Sample Width (cm)",
    "Air Flow (cm/s)",
    "Percent O2 (Note 1)",
    "Ignition Power (W)",
    "Ignition Time (s)",
    "Burn Time (s)",
    "Flow Direction",
    "?-g Burn Length",
    "?-g Spread Length",
    "1-g Burn Length",
    "1-g Spread Rate",
    "Camera 1",
    "Camera 2",
)

SAMPLE_ID_RE = re.compile(r"^[0-9]+-[0-9]+$")
NOTE_ID_RE = re.compile(r"^(Note\s+\d+)\b(.*)$", re.IGNORECASE)
FLOW_VIS_RE = re.compile(r"^F(\d+)C1/F\1C2$", re.IGNORECASE)
SCALAR_UNIT_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(mm/s|mm|cm/s|cm|W|s)$")

_DOCX_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

# Verified by direct inspection of embedded PNGs inside SAFFIRE-II Readme.docx
# (word/media/image1.png at P[4] for Table 1; word/media/image2.png at P[7] for Figure 1).
README_EMBEDDED_TABLE1: dict[str, dict[str, str]] = {
    "2-1": {
        "table1_id": "S1",
        "material": "Silicone",
        "thickness": "0.25 mm",
        "air_flow_cm_s": "20",
        "igniter_position": "Upstream",
        "figure1_material": "Silicone",
    },
    "2-2": {
        "table1_id": "S2",
        "material": "Silicone",
        "thickness": "0.61 mm",
        "air_flow_cm_s": "20",
        "igniter_position": "Upstream",
        "figure1_material": "Silicone",
    },
    "2-3": {
        "table1_id": "S3",
        "material": "Silicone",
        "thickness": "1.02 mm",
        "air_flow_cm_s": "20",
        "igniter_position": "Upstream",
        "figure1_material": "Silicone",
    },
    "2-4": {
        "table1_id": "S4",
        "material": "Silicone",
        "thickness": "0.36 mm",
        "air_flow_cm_s": "20",
        "igniter_position": "Downstream",
        "figure1_material": "Silicone opposed",
    },
    "2-5": {
        "table1_id": "S5",
        "material": "SIBAL fabric",
        "thickness": "0.33 mm",
        "air_flow_cm_s": "20",
        "igniter_position": "Upstream",
        "figure1_material": "SIBAL",
    },
    "2-6": {
        "table1_id": "S6",
        "material": "SIBAL fabric",
        "thickness": "0.33 mm",
        "air_flow_cm_s": "30",
        "igniter_position": "Upstream",
        "figure1_material": "SIBAL",
    },
    "2-7": {
        "table1_id": "S7",
        "material": "PMMA to Nomex",
        "thickness": "0.33 mm",
        "air_flow_cm_s": "20",
        "igniter_position": "Upstream",
        "figure1_material": "PMMA & Nomex",
    },
    "2-8": {
        "table1_id": "S8",
        "material": "Structured PMMA",
        "thickness": "10 mm (with tapered edge for ignition)",
        "air_flow_cm_s": "20",
        "igniter_position": "Upstream",
        "figure1_material": "PMMA",
    },
    "2-9": {
        "table1_id": "S9",
        "material": "Flat PMMA",
        "thickness": "10 mm (with tapered edge for ignition)",
        "air_flow_cm_s": "30",
        "igniter_position": "Upstream",
        "figure1_material": "PMMA",
    },
}

SAFFIRE_BOUNDARY_STATEMENTS: tuple[str, ...] = (
    "Reference cards present the 9 physical PSI-99 SAFFIRE-II sample records separated from 6 auxiliary/note rows; zero cross-study pooling with PSI-25, PSI-69, or PSI-39 is performed.",
    "Not a fire-safety ranking, material qualification pass/fail, causal gravity-effect proof, pooled average, or percentage-difference calculation.",
    "Microgravity Cygnus duct tests (forced air flow 20 or 30 cm/s, wire igniter 80 W / 97 W) and 1-g NASA-STD-6001 Test 1 upward screening references do NOT hold other boundary conditions equal.",
    "Distinct from SAFFIRE-VI cabin CO2 exposure hypotheses and from SAME-R (PSI-101) smoke-detector claims; emissions and detector failure rates are not analyzed here.",
    "PSI-99 sources are NOT indexed in the 503-chunk BM25/RAG corpus (indexed_in_rag=false); /api/evidence keeps PSI-99 gated under V12_OUT_OF_SCOPE_STUDY.",
    "Unresolved source cells ('037 mm', blank Material on 2-6 and 2-9, 'See Fig. 5' on 2-8, '?-g Spread Length' mm/s values, '~ 0', 'Complete', 'Insignificant', Note 1 derived O2, and CSV vs ReadMe Table 1 airflow/thickness/camera discrepancies) require primary report/publication verification and are never silently imputed.",
)


class SaffireError(RuntimeError):
    """Base error for the standalone PSI-99 SAFFIRE-II module."""


class SaffireLoadError(SaffireError):
    """Raised when SAFFIRE-II raw sources are missing or structurally invalid."""


class SaffireValidationError(SaffireError, ValueError):
    """Raised when a SAFFIRE-II API request has invalid keys, types, or format."""


@dataclass(frozen=True)
class ReadmeContext:
    """Parsed structural provenance extracted from SAFFIRE-II Readme.docx via stdlib XML."""

    relpath: str
    sha256: str
    paragraph_count: int
    paragraphs: dict[int, str]
    tables: dict[int, list[list[str]]]
    embedded_images_by_paragraph: dict[int, str]

    def summary_citations(self) -> list[dict[str, Any]]:
        """Return verified ReadMe XML/media locations used across cards."""
        items: list[dict[str, Any]] = []
        if 1 in self.paragraphs:
            items.append({
                "location": "P[1]",
                "kind": "paragraph",
                "detail": "Objectives, NASA-STD-6001 Test 1 normal-gravity screening comparison, 9 samples (5 cm x 29 cm).",
                "excerpt": self.paragraphs[1][:240],
            })
        if 3 in self.paragraphs or 4 in self.embedded_images_by_paragraph:
            items.append({
                "location": "P[3]-P[4] (Table 1 embedded PNG)",
                "kind": "embedded_image",
                "archive_member": self.embedded_images_by_paragraph.get(4, "word/media/image1.png"),
                "detail": "Table 1. Saffire-II Samples (S1..S9 materials, thicknesses, 20/30 cm/s airflow, upstream/downstream igniter).",
            })
        if 6 in self.paragraphs or 7 in self.embedded_images_by_paragraph:
            items.append({
                "location": "P[6]-P[7] (Figure 1 embedded PNG)",
                "kind": "embedded_image",
                "archive_member": self.embedded_images_by_paragraph.get(7, "word/media/image2.png"),
                "detail": "Figure 1. Sample Layout for Saffire-II (3x3 card showing Sample 4 Silicone opposed and airflow arrows).",
            })
        if 9 in self.paragraphs:
            items.append({
                "location": "P[9]",
                "kind": "paragraph",
                "detail": "Pre-flow (F1) and post-flow (F2) image-set definitions.",
                "excerpt": self.paragraphs[9],
            })
        if 10 in self.paragraphs or 1 in self.tables:
            items.append({
                "location": "P[10] & TBL[1] (Table 2)",
                "kind": "paragraph_and_table",
                "detail": f"Camera naming C1/C2 and {max(0, len(self.tables.get(1, [])) - 1)} PSI experiment data record rows (F1C1..S9C1).",
            })
        if 16 in self.paragraphs or 17 in self.embedded_images_by_paragraph:
            items.append({
                "location": "P[16]-P[17] (Table 3 embedded PNG)",
                "kind": "embedded_image",
                "archive_member": self.embedded_images_by_paragraph.get(17, "word/media/image3.png"),
                "detail": "Table 3. Saffire I, II and III Diagnostics (solid-state CO2 and O2 sensors in avionics bay / inlet).",
            })
        return items


@dataclass(frozen=True)
class SaffireAuxiliaryRow:
    """One non-sample row (pre/post flow-vis or Note 1-4) from the SAFFIRE-II CSV."""

    row_kind: str
    row_key: str
    physical_csv_line: int
    row_index: int
    raw_text: str
    raw_cells: tuple[str, ...]
    linked_sample_ids: tuple[str, ...]
    linked_columns: tuple[str, ...]
    readme_crosscheck: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_kind": self.row_kind,
            "row_key": self.row_key,
            "physical_csv_line": self.physical_csv_line,
            "row_index": self.row_index,
            "raw_text": self.raw_text,
            "linked_sample_ids": list(self.linked_sample_ids),
            "linked_columns": list(self.linked_columns),
            "readme_crosscheck": self.readme_crosscheck,
        }


@dataclass(frozen=True)
class SaffireSampleCard:
    """One of the 9 physical SAFFIRE-II sample cards (2-1 through 2-9)."""

    sample_id: str
    physical_csv_line: int
    row_index: int
    raw_row: dict[str, str]
    card_payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.card_payload


@dataclass(frozen=True)
class SaffireDataset:
    """In-memory, immutable SAFFIRE-II reference dataset."""

    csv_relpath: str
    csv_sha256: str
    headers: tuple[str, ...]
    total_data_rows: int
    cards: tuple[SaffireSampleCard, ...]
    cards_by_id: dict[str, SaffireSampleCard]
    auxiliary_rows: tuple[SaffireAuxiliaryRow, ...]
    readme: ReadmeContext
    source_discrepancies: tuple[dict[str, Any], ...]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_readme_docx(docx_path: Path, relpath: str) -> ReadmeContext:
    """Parse paragraphs, XML tables, and embedded-image positions via stdlib zipfile/ET."""
    if not docx_path.is_file():
        raise SaffireLoadError(f"Missing SAFFIRE-II ReadMe DOCX: {relpath}")
    raw_bytes = docx_path.read_bytes()
    sha256 = _sha256_bytes(raw_bytes)
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            names = set(zf.namelist())
            if "word/document.xml" not in names:
                raise SaffireLoadError("SAFFIRE-II ReadMe DOCX is missing word/document.xml.")
            rel_targets: dict[str, str] = {}
            if "word/_rels/document.xml.rels" in names:
                rels_root = ET.fromstring(zf.read("word/_rels/document.xml.rels"))
                for rel in rels_root:
                    rid = rel.attrib.get("Id")
                    target = rel.attrib.get("Target")
                    if rid and target:
                        rel_targets[rid] = f"word/{target.lstrip('/')}"
            doc_root = ET.fromstring(zf.read("word/document.xml"))
    except (zipfile.BadZipFile, ET.ParseError, OSError) as exc:
        raise SaffireLoadError(f"Unable to parse SAFFIRE-II ReadMe DOCX: {exc}") from exc

    body = doc_root.find("w:body", _DOCX_NS)
    if body is None:
        raise SaffireLoadError("SAFFIRE-II ReadMe DOCX has no document body.")

    paragraphs: dict[int, str] = {}
    tables: dict[int, list[list[str]]] = {}
    embedded_images: dict[int, str] = {}
    p_idx = 0
    t_idx = 0

    for child in body:
        local = child.tag.split("}")[-1]
        if local == "p":
            p_idx += 1
            text = "".join(node.text or "" for node in child.findall(".//w:t", _DOCX_NS)).strip()
            if text:
                paragraphs[p_idx] = text
            for blip in child.findall(".//a:blip", _DOCX_NS):
                rid = blip.attrib.get(f"{{{_DOCX_NS['r']}}}embed")
                if rid and rid in rel_targets:
                    embedded_images[p_idx] = rel_targets[rid]
        elif local == "tbl":
            t_idx += 1
            tbl_rows: list[list[str]] = []
            for tr in child.findall("./w:tr", _DOCX_NS):
                cells: list[str] = []
                for tc in tr.findall("./w:tc", _DOCX_NS):
                    cell_text = " | ".join(
                        "".join(t.text or "" for t in p.findall(".//w:t", _DOCX_NS)).strip()
                        for p in tc.findall("./w:p", _DOCX_NS)
                    ).strip()
                    cells.append(cell_text)
                tbl_rows.append(cells)
            tables[t_idx] = tbl_rows

    if not paragraphs and not tables:
        raise SaffireLoadError("SAFFIRE-II ReadMe DOCX contains no readable paragraphs or tables.")

    return ReadmeContext(
        relpath=relpath,
        sha256=sha256,
        paragraph_count=p_idx,
        paragraphs=paragraphs,
        tables=tables,
        embedded_images_by_paragraph=embedded_images,
    )


def _scalar_field(
    raw_header: str,
    raw_value: str,
    *,
    expected_unit: str | None = None,
    conflict_note: str | None = None,
) -> dict[str, Any]:
    """Classify a scalar/text CSV cell conservatively without guessing ambiguous values."""
    text = raw_value.strip()
    if not text:
        return {
            "raw_header": raw_header,
            "raw_value": raw_value,
            "verified_numeric": None,
            "verification_status": "empty_in_csv",
            "resolution_note": "Cell is blank in CSV.",
        }
    lowered = text.lower()
    if lowered.startswith("note "):
        return {
            "raw_header": raw_header,
            "raw_value": raw_value,
            "verified_numeric": None,
            "verification_status": "footnote_reference_only",
            "resolution_note": f"Cell references {text} instead of a direct scalar measurement.",
        }
    if lowered in {"n/a", "n/a (nomex)"}:
        return {
            "raw_header": raw_header,
            "raw_value": raw_value,
            "verified_numeric": None,
            "verification_status": "not_applicable",
            "resolution_note": "Reported as not applicable in CSV.",
        }
    if lowered in {"complete", "insignificant", "acceleratory"}:
        return {
            "raw_header": raw_header,
            "raw_value": raw_value,
            "verified_numeric": None,
            "verification_status": "qualitative_threshold",
            "resolution_note": (
                f"Qualitative value '{text}' preserved without equating 'Complete' to 29 cm "
                "or converting 'Insignificant'/'Acceleratory' into numbers."
            ),
        }
    if text.startswith("~") or "(note" in lowered or " to " in lowered:
        return {
            "raw_header": raw_header,
            "raw_value": raw_value,
            "verified_numeric": None,
            "verification_status": "approximate_or_range_unparsed",
            "resolution_note": (
                f"Approximate or ranged text '{text}' preserved literally; '~ 0' is never coerced to exact 0.0."
            ),
        }
    if " and " in lowered or " & " in lowered:
        return {
            "raw_header": raw_header,
            "raw_value": raw_value,
            "verified_numeric": None,
            "verification_status": "composite_sample_segments",
            "resolution_note": "Two-segment PMMA & Nomex sample values kept separate and unaveraged.",
        }

    match = SCALAR_UNIT_RE.match(text)
    if match:
        val = float(match.group(1))
        unit = match.group(2)
        if expected_unit and unit != expected_unit and not (expected_unit == "cm" and text == "1 cm"):
            return {
                "raw_header": raw_header,
                "raw_value": raw_value,
                "verified_numeric": None,
                "verification_status": "unresolved_header_unit_mismatch",
                "resolution_note": (
                    f"CSV column header '{raw_header}' implies unit '{expected_unit}', "
                    f"whereas cell value '{text}' uses '{unit}'; no numeric chart field is emitted."
                ),
            }
        if conflict_note:
            return {
                "raw_header": raw_header,
                "raw_value": raw_value,
                "verified_numeric": None,
                "csv_parsed_candidate": {"value": val, "unit": unit},
                "verification_status": "unresolved_source_discrepancy",
                "resolution_note": conflict_note,
            }
        return {
            "raw_header": raw_header,
            "raw_value": raw_value,
            "verified_numeric": {"value": val, "unit": unit},
            "verification_status": "verified_scalar",
            "resolution_note": f"Exact CSV scalar verified with unit '{unit}'.",
        }

    return {
        "raw_header": raw_header,
        "raw_value": raw_value,
        "verified_numeric": None,
        "verification_status": "unresolved_text_value",
        "resolution_note": f"Unparsed qualitative/reference cell '{text}' preserved verbatim.",
    }


def _build_thickness_field(raw_value: str, sample_id: str) -> dict[str, Any]:
    raw_header = "Samle Thickness "
    text = raw_value.strip()
    t1 = README_EMBEDDED_TABLE1.get(sample_id, {})
    t1_thick = t1.get("thickness")

    if text == "037 mm":
        return {
            "raw_header": raw_header,
            "raw_value": raw_value,
            "verified_numeric": None,
            "readme_table1_value": t1_thick,
            "verification_status": "unresolved_malformed_thickness_and_readme_conflict",
            "resolution_note": (
                f"CSV records malformed '037 mm' (missing decimal point; NOT 37 mm), while "
                f"ReadMe Table 1 ({t1.get('table1_id')}, P[4] image1.png) lists '{t1_thick}'. "
                "Preserved raw without guessing 0.37 vs Table 1 value."
            ),
        }
    if text == "See Fig. 5":
        return {
            "raw_header": raw_header,
            "raw_value": raw_value,
            "verified_numeric": None,
            "readme_table1_value": t1_thick,
            "verification_status": "unresolved_external_figure_reference",
            "resolution_note": (
                "CSV refers to 'See Fig. 5', which is absent from SAFFIRE-II Readme.docx "
                "(only Figure 1 exists locally). ReadMe Table 1 S8 states "
                f"'{t1_thick}'; an external primary report/publication is required to verify Fig. 5."
            ),
        }
    if text in {"0.27 mm", "1.03 mm"}:
        return _scalar_field(
            raw_header,
            raw_value,
            conflict_note=(
                f"CSV reports '{text}', whereas ReadMe Table 1 ({t1.get('table1_id')}, "
                f"P[4] image1.png) reports '{t1_thick}'. Both retained without overriding."
            ),
        )
    if text == "0.85 and 0.37 mm":
        field = _scalar_field(raw_header, raw_value)
        field["readme_table1_value"] = t1_thick
        field["resolution_note"] += f" Note ReadMe Table 1 S7 summarizes thickness as '{t1_thick}'."
        return field
    field = _scalar_field(raw_header, raw_value)
    if t1_thick:
        field["readme_table1_value"] = t1_thick
    return field


def _build_material_field(raw_value: str, sample_id: str) -> dict[str, Any]:
    t1 = README_EMBEDDED_TABLE1.get(sample_id, {})
    t1_mat = t1.get("material")
    fig1_mat = t1.get("figure1_material")
    if not raw_value.strip():
        return {
            "raw_header": "Material",
            "raw_value": raw_value,
            "display_value": None,
            "auto_filled_from_previous_row": False,
            "readme_table1_sample": t1.get("table1_id"),
            "readme_table1_material": t1_mat,
            "readme_figure1_material": fig1_mat,
            "verification_status": "unresolved_empty_in_csv_readme_candidate_with_conflict",
            "resolution_note": (
                "Material cell is empty in CSV and is NEVER carried down from the preceding row. "
                f"Embedded ReadMe Table 1 ({t1.get('table1_id')}, P[4] image1.png) identifies it as "
                f"'{t1_mat}' (Figure 1, P[7] image2.png: '{fig1_mat}'), but Table 1 conflicts with CSV "
                "on Air Flow (30 vs 20 cm/s) and S6 thickness (0.33 mm vs '037 mm')."
            ),
        }
    status = "verified_from_csv_and_readme"
    note = f"Matches ReadMe Table 1 ({t1.get('table1_id')}, P[4] image1.png: '{t1_mat}')."
    if sample_id == "2-8":
        note = (
            f"CSV states 'PMMA'; embedded ReadMe Table 1 (S8, P[4] image1.png) specifies "
            f"'{t1_mat}' with tapered edge for ignition."
        )
    return {
        "raw_header": "Material",
        "raw_value": raw_value,
        "display_value": raw_value,
        "auto_filled_from_previous_row": False,
        "readme_table1_sample": t1.get("table1_id"),
        "readme_table1_material": t1_mat,
        "readme_figure1_material": fig1_mat,
        "verification_status": status,
        "resolution_note": note,
    }


def _build_percent_o2_field(raw_value: str) -> dict[str, Any]:
    return {
        "raw_header": "Percent O2 (Note 1)",
        "raw_value": raw_value,
        "unit": "%",
        "is_derived": True,
        "verified_numeric": None,
        "verification_status": "derived_and_approximate_per_note1",
        "resolution_note": (
            "Note 1: derived from measured CO2 production and referenced to initial O2 "
            "concentration reported by ISS (not a direct local duct O2 sensor reading per sample). "
            "ReadMe Table 3 (P[17] image3.png) places solid-state CO2 and O2 sensors in/at the avionics bay."
        ),
    }


def _build_camera_info(raw_row: dict[str, str], sample_id: str, readme: ReadmeContext) -> dict[str, Any]:
    cam1 = raw_row["Camera 1"].strip()
    cam2 = raw_row["Camera 2"].strip()
    sample_num = sample_id.split("-")[1]
    expected_prefix = f"SAFFIRE-II S{sample_num}C"
    tbl1 = readme.tables.get(1, [])
    table2_entries = [
        {"record_name": r[0], "description": r[1]}
        for r in tbl1[1:]
        if len(r) >= 2 and r[0].startswith(expected_prefix)
    ]
    discrepancy: str | None = None
    if sample_id == "2-4" and cam2 == "S4C1":
        discrepancy = (
            "CSV Camera 2 is 'S4C1' (duplicate of Camera 1), whereas ReadMe TBL[1] (Table 2) "
            "lists 'SAFFIRE-II S4C1' and 'SAFFIRE-II S4C2'."
        )
    elif sample_id == "2-6" and cam2 == "S56C2":
        discrepancy = (
            "CSV Camera 2 has typo 'S56C2', whereas ReadMe TBL[1] (Table 2) lists 'SAFFIRE-II S6C2'."
        )
    elif sample_id == "2-3" and not cam1:
        discrepancy = (
            "CSV Camera 1 is blank for 2-3; ReadMe TBL[1] (Table 2) lists only 'SAFFIRE-II S3C2' for Sample 3."
        )
    return {
        "camera_1_raw": raw_row["Camera 1"],
        "camera_2_raw": raw_row["Camera 2"],
        "readme_table2_records": table2_entries,
        "discrepancy_note": discrepancy,
    }


def _parse_auxiliary_row(row_index: int, row: list[str]) -> SaffireAuxiliaryRow:
    physical_line = row_index + 1
    first = row[0].strip()
    second = row[1].strip() if len(row) > 1 else ""

    flow_match = FLOW_VIS_RE.match(first)
    if flow_match:
        flow_num = flow_match.group(1)
        target_sample = f"2-{flow_num}" if flow_num in {"1", "2"} else "2-1"
        if flow_num == "1":
            crosscheck = "Matches ReadMe P[9] and TBL[1] (F1 = pre-flow; CSV has spelling 'visulation')."
        elif flow_num == "2":
            crosscheck = (
                "CONFLICT: CSV text repeats 'Pre-test flow visulation data for sample 2-2', "
                "whereas ReadMe P[9] and TBL[1] (Table 2) define F2 as post-flow ('SAFFIRE-II F2C1/F2C2: Post-flow')."
            )
        else:
            crosscheck = "Matched to ReadMe P[9] / TBL[1]."
        return SaffireAuxiliaryRow(
            row_kind="flow_visualization",
            row_key=first,
            physical_csv_line=physical_line,
            row_index=row_index,
            raw_text=second,
            raw_cells=tuple(row),
            linked_sample_ids=(target_sample,),
            linked_columns=("Sample Number", "Material"),
            readme_crosscheck=crosscheck,
        )

    note_match = NOTE_ID_RE.match(first)
    if note_match:
        label = " ".join(note_match.group(1).split()).title()
        note_body = note_match.group(2).strip()
        links_by_note: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
            "Note 1": (tuple(f"2-{i}" for i in range(1, 10)), ("Percent O2 (Note 1)",)),
            "Note 2": (("2-7",), ("?-g Burn Length",)),
            "Note 3": (("2-8",), ("?-g Burn Length",)),
            "Note 4": (("2-8", "2-9"), ("?-g Burn Length", "?-g Spread Length")),
        }
        linked_samples, linked_cols = links_by_note.get(label, ((), ()))
        return SaffireAuxiliaryRow(
            row_kind="footnote",
            row_key=label,
            physical_csv_line=physical_line,
            row_index=row_index,
            raw_text=first,
            raw_cells=tuple(row),
            linked_sample_ids=linked_samples,
            linked_columns=linked_cols,
            readme_crosscheck=None if note_body else None,
        )

    raise SaffireLoadError(
        f"Unrecognized non-sample CSV row at physical line {physical_line}: {first!r}"
    )


def _build_card(
    row_index: int,
    raw_row: dict[str, str],
    notes_by_sample: dict[str, list[SaffireAuxiliaryRow]],
    aux_by_sample: dict[str, list[SaffireAuxiliaryRow]],
    csv_relpath: str,
    csv_sha256: str,
    readme: ReadmeContext,
) -> SaffireSampleCard:
    sample_id = raw_row["Sample Number"].strip()
    physical_line = row_index + 1
    t1 = README_EMBEDDED_TABLE1.get(sample_id, {})

    material = _build_material_field(raw_row["Material"], sample_id)
    thickness = _build_thickness_field(raw_row["Samle Thickness "], sample_id)
    length = _scalar_field("Sample Length ", raw_row["Sample Length "], expected_unit="cm")
    width = _scalar_field("Sample Width (cm)", raw_row["Sample Width (cm)"], expected_unit="cm")

    t1_flow = t1.get("air_flow_cm_s")
    air_flow_conflict = None
    if t1_flow and f"{t1_flow} cm/s" != raw_row["Air Flow (cm/s)"].strip():
        air_flow_conflict = (
            f"CSV states '{raw_row['Air Flow (cm/s)'].strip()}', whereas embedded ReadMe Table 1 "
            f"({t1.get('table1_id')}, P[4] image1.png) lists '{t1_flow} cm/s'."
        )
    air_flow = _scalar_field(
        "Air Flow (cm/s)",
        raw_row["Air Flow (cm/s)"],
        expected_unit="cm/s",
        conflict_note=air_flow_conflict,
    )
    if t1_flow:
        air_flow["readme_table1_value"] = f"{t1_flow} cm/s"

    percent_o2 = _build_percent_o2_field(raw_row["Percent O2 (Note 1)"])
    ignition_power = _scalar_field("Ignition Power (W)", raw_row["Ignition Power (W)"], expected_unit="W")
    ignition_time = _scalar_field("Ignition Time (s)", raw_row["Ignition Time (s)"], expected_unit="s")
    burn_time = _scalar_field("Burn Time (s)", raw_row["Burn Time (s)"], expected_unit="s")

    microg_burn = _scalar_field("?-g Burn Length", raw_row["?-g Burn Length"], expected_unit="cm")
    microg_burn["header_meaning_note"] = (
        "'?-g' is CSV ASCII replacement for 'µ-g' (low/microgravity Cygnus duct test)."
    )
    microg_spread = _scalar_field("?-g Spread Length", raw_row["?-g Spread Length"], expected_unit="cm")
    if microg_spread["verification_status"] == "footnote_reference_only":
        microg_spread["resolution_note"] = (
            "References Note 4 (regression rate 0.01 to 0.04 mm/s), whereas header says "
            "'?-g Spread Length'. No numeric chart value is generated."
        )

    normalg_burn = _scalar_field("1-g Burn Length", raw_row["1-g Burn Length"], expected_unit="cm")
    normalg_rate = _scalar_field("1-g Spread Rate", raw_row["1-g Spread Rate"], expected_unit="mm/s")
    cameras = _build_camera_info(raw_row, sample_id, readme)

    attached_notes = [n.to_dict() for n in notes_by_sample.get(sample_id, [])]
    attached_aux = [a.to_dict() for a in aux_by_sample.get(sample_id, [])]

    unresolved_items: list[dict[str, Any]] = []
    field_map = {
        "material": material,
        "thickness": thickness,
        "length": length,
        "width": width,
        "air_flow": air_flow,
        "percent_o2": percent_o2,
        "burn_time": burn_time,
        "?-g Burn Length": microg_burn,
        "?-g Spread Length": microg_spread,
        "1-g Burn Length": normalg_burn,
        "1-g Spread Rate": normalg_rate,
    }
    for fname, fobj in field_map.items():
        if fobj.get("verified_numeric") is None and fobj["verification_status"] not in {
            "verified_from_csv_and_readme",
            "not_applicable",
        }:
            unresolved_items.append({
                "field": fname,
                "raw_value": fobj["raw_value"],
                "status": fobj["verification_status"],
                "detail": fobj["resolution_note"],
            })
    if cameras["discrepancy_note"]:
        unresolved_items.append({
            "field": "cameras",
            "raw_value": f"{cameras['camera_1_raw']} / {cameras['camera_2_raw']}",
            "status": "camera_label_discrepancy",
            "detail": cameras["discrepancy_note"],
        })

    card_readme_citations = [
        {"location": "P[1]", "reason": "NASA-STD-6001 Test 1 1-g comparison & 5 cm x 29 cm geometry"},
        {
            "location": f"P[3]-P[4] (Table 1 {t1.get('table1_id', sample_id)} in image1.png)",
            "reason": "Sample material, thickness, airflow, and upstream/downstream igniter position",
        },
        {"location": "P[6]-P[7] (Figure 1 in image2.png)", "reason": "Sample layout position on 3x3 card"},
    ]
    if attached_aux:
        card_readme_citations.append({
            "location": "P[9] & TBL[1] (Table 2)",
            "reason": "Pre-flow (F1) / post-flow (F2) vs CSV label comparison and camera sets",
        })

    payload = {
        "sample_id": sample_id,
        "material": material,
        "test_conditions": {
            "thickness": thickness,
            "length": length,
            "width": width,
            "air_flow": air_flow,
            "percent_o2": percent_o2,
            "ignition_power": ignition_power,
            "ignition_time": ignition_time,
            "burn_time": burn_time,
            "flow_direction": {
                "raw_header": "Flow Direction",
                "raw_value": raw_row["Flow Direction"],
                "readme_table1_igniter_position": t1.get("igniter_position"),
            },
        },
        "results": {
            "microgravity": {
                "header_meaning_note": "CSV headers use '?-g' where 'µ-g' (microgravity Cygnus flight) was intended.",
                "burn_length": microg_burn,
                "spread_length_or_rate": microg_spread,
            },
            "normal_gravity_reference": {
                "screening_standard": "NASA-STD-6001 Test 1 (ReadMe P[1])",
                "conditions_equal_to_flight": False,
                "environment_caveat": (
                    "Normal-gravity screening uses upward quiescent buoyancy conditions; airflow, "
                    "igniter power (80/97 W), and chamber dilution are not matched in CSV."
                ),
                "burn_length": normalg_burn,
                "spread_rate": normalg_rate,
            },
        },
        "cameras": cameras,
        "footnotes": attached_notes,
        "auxiliary_flow_records": attached_aux,
        "unresolved_items": unresolved_items,
        "external_source_needed": (
            "Primary SAFFIRE-II final report/journal publications required to verify 'See Fig. 5' (2-8) "
            if sample_id == "2-8"
            else "Raw Excel sensor files and primary SAFFIRE-II publications are needed for quantitative time-series."
        ),
        "source_provenance": {
            "csv_relpath": csv_relpath,
            "csv_sha256": csv_sha256,
            "physical_csv_line": physical_line,
            "csv_data_row_index": row_index,
            "raw_row": dict(raw_row),
            "readme_relpath": readme.relpath,
            "readme_sha256": readme.sha256,
            "readme_citations": card_readme_citations,
        },
    }
    return SaffireSampleCard(
        sample_id=sample_id,
        physical_csv_line=physical_line,
        row_index=row_index,
        raw_row=dict(raw_row),
        card_payload=payload,
    )


def _build_source_discrepancies() -> tuple[dict[str, Any], ...]:
    return (
        {
            "id": "MALFORMED_037_MM_AND_TABLE1_CONFLICT",
            "sample_ids": ["2-4", "2-5", "2-6"],
            "detail": (
                "CSV records '037 mm' (missing decimal point); ReadMe Table 1 (image1.png) records "
                "0.36 mm (S4) and 0.33 mm (S5, S6). Preserved raw without auto-fixing."
            ),
        },
        {
            "id": "THICKNESS_AND_FLOW_DISCREPANCIES_CSV_VS_TABLE1",
            "sample_ids": ["2-1", "2-3", "2-6", "2-9"],
            "detail": (
                "CSV vs ReadMe Table 1 differ on thickness (2-1: 0.27 vs 0.25 mm; 2-3: 1.03 vs 1.02 mm; "
                "2-7: 0.85 & 0.37 vs 0.33 mm) and Air Flow (2-6 & 2-9: 20 cm/s in CSV vs 30 cm/s in Table 1)."
            ),
        },
        {
            "id": "EMPTY_MATERIAL_CELLS",
            "sample_ids": ["2-6", "2-9"],
            "detail": (
                "CSV leaves Material blank on 2-6 and 2-9. Never auto-filled from previous row; "
                "ReadMe Table 1 (S6='SIBAL fabric', S8='Structured PMMA', S9='Flat PMMA') shows 2-8 and 2-9 differ."
            ),
        },
        {
            "id": "EXTERNAL_FIG_5_UNRESOLVED",
            "sample_ids": ["2-8"],
            "detail": (
                "CSV thickness says 'See Fig. 5', which does not exist in SAFFIRE-II Readme.docx "
                "(only Figure 1 is present); an external primary publication/report is required."
            ),
        },
        {
            "id": "MICROGRAVITY_HEADER_AND_SPREAD_UNIT_MISMATCH",
            "sample_ids": ["2-1", "2-2", "2-3", "2-4", "2-5", "2-6", "2-7", "2-8", "2-9"],
            "detail": (
                "Headers use '?-g' for microgravity; column '?-g Spread Length' contains '2.1 mm/s', "
                "'2.6 mm/s', and 'Note 4' (0.01 to 0.04 mm/s regression rate) — rate units under a length header."
            ),
        },
        {
            "id": "NOTE1_DERIVED_O2_AND_NONQUANTITATIVE_CELLS",
            "sample_ids": ["2-1", "2-2", "2-3", "2-4", "2-5", "2-6", "2-7", "2-8", "2-9"],
            "detail": (
                "Percent O2 (Note 1) is derived from CO2 and initial ISS O2; '~ 0' is never coerced to 0, "
                "'Complete' is never coerced to 29 cm, and 'Insignificant'/'Acceleratory' remain qualitative."
            ),
        },
        {
            "id": "F2_PRE_VS_POST_FLOW_AND_CAMERA_LABELS",
            "sample_ids": ["2-2", "2-4", "2-6"],
            "detail": (
                "CSV F2C1/F2C2 reads 'Pre-test flow visulation' whereas ReadMe P[9] and Table 2 define F2 as post-flow; "
                "CSV Camera 2 shows 'S4C1' (2-4) and 'S56C2' (2-6) vs Table 2 'S4C2' and 'S6C2'."
            ),
        },
    )


def load_saffire_dataset(repo_root: str | Path) -> SaffireDataset:
    """Load and validate PSI-99 SAFFIRE-II CSV and ReadMe DOCX strictly in read-only mode."""
    root = Path(repo_root).resolve()
    csv_path = root / SAFFIRE_CSV_RELPATH
    if not csv_path.is_file():
        raise SaffireLoadError(f"Missing SAFFIRE-II experimental table CSV: {SAFFIRE_CSV_RELPATH}")

    csv_bytes = csv_path.read_bytes()
    csv_sha256 = _sha256_bytes(csv_bytes)
    try:
        csv_text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SaffireLoadError(f"Invalid encoding in SAFFIRE-II CSV: {exc}") from exc

    rows = list(csv.reader(csv_text.splitlines()))
    if len(rows) < 2:
        raise SaffireLoadError("SAFFIRE-II CSV must include header and data rows.")
    header = tuple(rows[0])
    if header != EXPECTED_CSV_HEADERS:
        raise SaffireLoadError("SAFFIRE-II CSV header does not match expected schema.")

    readme = _parse_readme_docx(root / SAFFIRE_README_RELPATH, SAFFIRE_README_RELPATH)

    sample_rows: list[tuple[int, dict[str, str]]] = []
    seen_sample_ids: set[str] = set()
    auxiliary_rows: list[SaffireAuxiliaryRow] = []

    for idx, row in enumerate(rows[1:], start=1):
        if len(row) != len(header):
            raise SaffireLoadError(
                f"SAFFIRE-II CSV row width mismatch at physical line {idx + 1}: "
                f"expected {len(header)}, got {len(row)}."
            )
        sample_cell = row[0].strip()
        if SAMPLE_ID_RE.match(sample_cell):
            if sample_cell in seen_sample_ids:
                raise SaffireLoadError(f"Duplicate Sample Number '{sample_cell}' in SAFFIRE-II CSV.")
            seen_sample_ids.add(sample_cell)
            sample_rows.append((idx, dict(zip(header, row))))
        else:
            auxiliary_rows.append(_parse_auxiliary_row(idx, row))

    if not sample_rows:
        raise SaffireLoadError("SAFFIRE-II CSV contains zero sample records.")

    notes_by_sample: dict[str, list[SaffireAuxiliaryRow]] = {}
    aux_by_sample: dict[str, list[SaffireAuxiliaryRow]] = {}
    for aux in auxiliary_rows:
        target_map = notes_by_sample if aux.row_kind == "footnote" else aux_by_sample
        for sid in aux.linked_sample_ids:
            target_map.setdefault(sid, []).append(aux)

    cards = tuple(
        _build_card(
            idx,
            row_dict,
            notes_by_sample,
            aux_by_sample,
            SAFFIRE_CSV_RELPATH,
            csv_sha256,
            readme,
        )
        for idx, row_dict in sample_rows
    )
    cards_by_id = {c.sample_id: c for c in cards}

    return SaffireDataset(
        csv_relpath=SAFFIRE_CSV_RELPATH,
        csv_sha256=csv_sha256,
        headers=header,
        total_data_rows=len(rows) - 1,
        cards=cards,
        cards_by_id=cards_by_id,
        auxiliary_rows=tuple(auxiliary_rows),
        readme=readme,
        source_discrepancies=_build_source_discrepancies(),
    )


def build_saffire_schema(dataset: SaffireDataset) -> dict[str, Any]:
    """Build the GET /api/saffire/schema payload describing scope, counts, and caveats."""
    flow_vis_count = sum(1 for a in dataset.auxiliary_rows if a.row_kind == "flow_visualization")
    footnote_count = sum(1 for a in dataset.auxiliary_rows if a.row_kind == "footnote")
    return {
        "investigation_id": "PSI-99",
        "acronym": "SAFFIRE-II",
        "title": "Spacecraft Fire Experiment-II",
        "doi": "10.60555/2chp-m469",
        "license": "CC0-1.0",
        "scope": {
            "separate_from_core_experiment_record": True,
            "queryable_in_core": False,
            "separate_from_cfi": True,
            "indexed_in_rag": False,
            "cross_environment_pooling_allowed": False,
            "safety_ranking_enabled": False,
            "ceteris_paribus_1g_vs_0g": False,
            "description": (
                "Separate condition-preserving reference card view for PSI-99 SAFFIRE-II "
                "(9 physical sample records separated from 6 auxiliary/note rows). Not integrated "
                "into BM25/RAG or the PSI-25/PSI-69 ExperimentRecord core."
            ),
        },
        "row_separation": {
            "total_csv_data_rows": dataset.total_data_rows,
            "physical_sample_count": len(dataset.cards),
            "auxiliary_and_note_row_count": len(dataset.auxiliary_rows),
            "flow_visualization_rows": flow_vis_count,
            "footnote_rows": footnote_count,
            "sample_ids": [c.sample_id for c in dataset.cards],
        },
        "filters": {
            "sample_id": {
                "optional": True,
                "format_regex": "^[0-9]+-[0-9]+$",
                "available_values": [c.sample_id for c in dataset.cards],
                "default_behavior": "When omitted or null, returns all 9 reference cards.",
            }
        },
        "provenance": {
            "csv": {
                "relpath": dataset.csv_relpath,
                "sha256": dataset.csv_sha256,
                "raw_headers": list(dataset.headers),
            },
            "readme_docx": {
                "relpath": dataset.readme.relpath,
                "sha256": dataset.readme.sha256,
                "paragraph_count": dataset.readme.paragraph_count,
                "xml_table_count": len(dataset.readme.tables),
                "embedded_image_paragraphs": {
                    str(k): v for k, v in sorted(dataset.readme.embedded_images_by_paragraph.items())
                },
                "key_locations": dataset.readme.summary_citations(),
            },
        },
        "auxiliary_rows": [a.to_dict() for a in dataset.auxiliary_rows],
        "source_discrepancies": list(dataset.source_discrepancies),
        "limitations": list(SAFFIRE_BOUNDARY_STATEMENTS),
    }


def validate_sample_id(sample_id: Any) -> str | None:
    """Validate optional sample_id input; invalid type/syntax raises SaffireValidationError."""
    if sample_id is None:
        return None
    if not isinstance(sample_id, str):
        raise SaffireValidationError("sample_id must be a string or null.")
    cleaned = sample_id.strip()
    if not cleaned or len(cleaned) > 32 or not SAMPLE_ID_RE.match(cleaned):
        raise SaffireValidationError(
            "sample_id must match the SAFFIRE-II sample format '<digit>-<digit>' (e.g., '2-1')."
        )
    return cleaned


def run_saffire_reference(
    dataset: SaffireDataset,
    *,
    sample_id: str | None = None,
) -> dict[str, Any]:
    """Return provenance-rich reference card(s) without cross-sample aggregation."""
    clean_id = validate_sample_id(sample_id)
    if clean_id is None:
        selected = list(dataset.cards)
    else:
        card = dataset.cards_by_id.get(clean_id)
        selected = [card] if card is not None else []

    status = "OK" if selected else "NO_EVIDENCE"
    return {
        "investigation_id": "PSI-99",
        "acronym": "SAFFIRE-II",
        "status": status,
        "requested_sample_id": clean_id,
        "total_sample_records": len(dataset.cards),
        "auxiliary_and_note_rows_excluded_from_sample_count": len(dataset.auxiliary_rows),
        "total_returned_cards": len(selected),
        "cards": [c.to_dict() for c in selected],
        "auxiliary_rows": (
            [a.to_dict() for a in dataset.auxiliary_rows]
            if clean_id is None
            else [
                a.to_dict()
                for a in dataset.auxiliary_rows
                if clean_id in a.linked_sample_ids
            ]
        ),
        "source_discrepancies": list(dataset.source_discrepancies),
        "limitations": list(SAFFIRE_BOUNDARY_STATEMENTS),
        "provenance": {
            "csv_relpath": dataset.csv_relpath,
            "csv_sha256": dataset.csv_sha256,
            "readme_relpath": dataset.readme.relpath,
            "readme_sha256": dataset.readme.sha256,
            "readme_locations": dataset.readme.summary_citations(),
        },
    }
