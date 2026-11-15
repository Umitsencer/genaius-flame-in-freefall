"""Lean gap-filler downloader for NASA PSI's 24 Combustion Science studies.

Reads the live PSI investigation file tree per study, skips any file already
present with matching size/magic (without silently overwriting modified files),
verifies magic bytes (rejecting HTML error pages), avoids giant archives/videos,
and stores provenance using permanent API/DOI URLs (never signed S3 URLs).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RAW_PSI = ROOT / "data" / "raw" / "psi"
OUT_LOG = RAW_PSI / "psi_24_download_log.json"
BASE = "https://psi.nasa.gov/geode-py/ws"

# Target essential files (excluding giant archives, raw telemetry collections,
# videos, presentations, and duplicates of already-local BASS-II/FLEX/SAME-R PDFs).
TARGETS: dict[str, list[tuple[str, str]]] = {
    "PSI-10": [
        ("PSI-10_Reports_FinalRpt_ACMEFlameDesign.pdf", "reports/PSI-10"),
        ("PSI-10_Science Documents_SRD_ACMEFlameDesign.pdf", "matrices_and_readmes/PSI-10"),
    ],
    "PSI-20": [
        ("PSI-20_Reports_Final_20220201.pdf", "reports/PSI-20"),
        ("PSI-20_Science Documents_BRE_data_interpretation_20220804.pdf", "matrices_and_readmes/PSI-20"),
        ("PSI-20_Science Documents_ACME_non-imaging_data_file_description.pdf", "matrices_and_readmes/PSI-20"),
    ],
    "PSI-21": [
        ("CLD_Flame_final_report_20220330.pdf", "reports/PSI-21"),
    ],
    "PSI-22": [
        ("PSI-22_Reports_E-FIELD Flames Final Report.pdf", "reports/PSI-22"),
        ("PSI-22_Science Documents_E-FIELD Flames data interpretation document.pdf", "matrices_and_readmes/PSI-22"),
        ("PSI-22_Science Documents_ACME E-FIELD Flames DoD.pdf", "matrices_and_readmes/PSI-22"),
    ],
    "PSI-23": [
        ("PSI-23_Reports_s_Flame_final_report_20210729.pdf", "reports/PSI-23"),
        ("PSI-23_Science Documents_ACME s-Flame  DoD.pdf", "matrices_and_readmes/PSI-23"),
    ],
    "PSI-25": [
        ("PSI-25_Science Documents_BASS-II_Test.Matrices.xlsx", "matrices_and_readmes/PSI-25"),
    ],
    "PSI-26": [
        ("PSI-26_Science Documents_SRD_BASS.pdf", "matrices_and_readmes/PSI-26"),
        ("PSI-26_Science Documents_DLD_BASS.pdf", "matrices_and_readmes/PSI-26"),
    ],
    "PSI-39": [
        ("PSI-39_Reports_CFI Science Final Report.pdf", "reports/PSI-39"),
    ],
    "PSI-47": [
        ("PSI-47_Reports_DAFT_30Day.PostFlightReport.pdf", "reports/PSI-47"),
        ("PSI-47_Analyzed Data_DAFT Retrieved Data Summary.xls", "matrices_and_readmes/PSI-47"),
    ],
    "PSI-60": [
        ("PSI-60_metadata_NEWID-5_Computational and Ex.zip", "matrices_and_readmes/PSI-60"),
    ],
    "PSI-62": [
        ("PSI-62_metadata_NEWID-7_Concurrent Flame Spr.zip", "matrices_and_readmes/PSI-62"),
    ],
    "PSI-68": [
        ("PSI-68_Science Documents_FLEX-2 DoD.docx", "matrices_and_readmes/PSI-68"),
        ("PSI-68_Science Documents_FLEX-2 SRD Final.pdf", "matrices_and_readmes/PSI-68"),
    ],
    "PSI-69": [
        ("PSI-69_Science Documents_FLEX DoD.docx", "matrices_and_readmes/PSI-69"),
        ("PSI-69_Science Documents_FLEX_Test_Plan.pdf", "matrices_and_readmes/PSI-69"),
    ],
    "PSI-98": [
        ("PSI-98_Science Documents_SAFFIRE Objectives, Development and Status.pdf", "matrices_and_readmes/PSI-98"),
        ("PSI-98_Engineering Documents_SAFFIRE-I Operations.pdf", "matrices_and_readmes/PSI-98"),
    ],
    "PSI-100": [
        ("PSI-100_Engineering Documents_SAFFIRE-III Operations.pdf", "matrices_and_readmes/PSI-100"),
    ],
    "PSI-102": [
        ("PSI-102_Engineering Documents_SAME Verification Plan and Engineering Requirements Document (VPRED)_January 2007.pdf", "matrices_and_readmes/PSI-102"),
    ],
    "PSI-106": [
        ("SLICE final report 20171226.pdf", "reports/PSI-106"),
    ],
    "PSI-107": [
        ("PSI-107_Reports_SPICE_FinalReport.pdf", "reports/PSI-107"),
        ("PSI-107_Reports_SPICE_30-DayPostFlightReport.pdf", "reports/PSI-107"),
    ],
    "PSI-115": [
        ("PSI-115_Reports_NNX17AF08A_FinalReport.pdf", "reports/PSI-115"),
        ("PSI-115_Science Documents_DataOrganizationDocument.pdf", "matrices_and_readmes/PSI-115"),
        ("PSI-115_Analyzed Data_8cmNoGravityPSD.dat", "analyzed_data/PSI-115"),
        ("PSI-115_Analyzed Data_nodeDiameters.dat", "analyzed_data/PSI-115"),
    ],
    "PSI-117": [
        ("PSI-117_Reports_Dissertation_Combustion Behavior Of Sub-Millimeter Sized Oxygenated And N-Alka.pdf", "reports/PSI-117"),
        ("PSI-117_Analyzed Data_ReadMe_List_of_Data.xlsx", "analyzed_data/PSI-117"),
        ("PSI-117_Analyzed Data_PROCI_2023_Alkane_Extinction_Diameter_1atm.csv", "analyzed_data/PSI-117"),
        ("PSI-117_Analyzed Data_PROCI_2019_Oscillatory_Cool_Flame.csv", "analyzed_data/PSI-117"),
        ("PSI-117_Analyzed Data_PROCI_2023_C12_Extinction_Diameter_vs_pressure.csv", "analyzed_data/PSI-117"),
        ("PSI-117_Analyzed Data_PROCI_2019_Stable_Cool.csv", "analyzed_data/PSI-117"),
        ("PSI-117_Analyzed Data_PROCI_C12_2019_Three_Stage.csv", "analyzed_data/PSI-117"),
        ("PSI-117_Analyzed Data_MST_2024_Burning_history_Flame_diameter.csv", "analyzed_data/PSI-117"),
        ("PSI-117_Analyzed Data_MST_2024_Kavg.csv", "analyzed_data/PSI-117"),
        ("PSI-117_Analyzed Data_MST_2024_Dext.csv", "analyzed_data/PSI-117"),
        ("PSI-117_Analyzed Data_MST_2024_Radiance_Flame_Diameter.csv", "analyzed_data/PSI-117"),
    ],
    "PSI-142": [
        ("PSI-142_Analyzed Data_PSI data summary Princeton with links.xlsx", "analyzed_data/PSI-142"),
        ("PSI-142_metadata_PSI-164_Quantitative Studies.zip", "matrices_and_readmes/PSI-142"),
    ],
    "PSI-159": [
        ("PSI-159_Reports_FinalRpt_ACME.CFI-G.pdf", "reports/PSI-159"),
    ],
}


def _http_bytes(url: str, payload: dict[str, Any] | None = None) -> bytes:
    data = json.dumps(payload).encode() if payload else None
    headers = (
        {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
        if payload
        else {"User-Agent": "Mozilla/5.0"}
    )
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=35) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"RETRY {attempt + 1} for {url[:80]}: {exc}", flush=True)
            time.sleep(1.2 * (attempt + 1))
    assert last_err is not None
    raise last_err


def _walk_files(node: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    for entry in node.get("files", []):
        if entry.get("directory") or entry.get("files"):
            by_name.update(_walk_files(entry))
        else:
            name = entry.get("key", "").rsplit("/", 1)[-1]
            if name:
                by_name[name] = entry
    return by_name


def _validate_format(filename: str, raw: bytes) -> str:
    head = raw[:32].lstrip()
    low = filename.lower()
    if head.startswith((b"<!DOCTYPE", b"<html", b"<HTML")):
        raise ValueError(f"HTML error response received instead of {filename}")
    if low.endswith(".pdf"):
        if not raw.startswith(b"%PDF-"):
            raise ValueError(f"Missing %PDF header for {filename}")
        return "pdf"
    if low.endswith((".zip", ".xlsx", ".docx")):
        if not raw.startswith(b"PK"):
            raise ValueError(f"Missing PK/ZIP magic header for {filename}")
        return low.rsplit(".", 1)[-1]
    if low.endswith(".xls"):
        if not raw.startswith(b"\xd0\xcf\x11\xe0"):
            raise ValueError(f"Missing OLE2 magic header for {filename}")
        return "xls"
    return low.rsplit(".", 1)[-1] if "." in low else "binary"


def main() -> None:
    log_entries: list[dict[str, Any]] = []
    meta_dir = RAW_PSI / "metadata"
    for pid, specs in TARGETS.items():
        cached_meta = meta_dir / f"{pid}.json"
        cached_tree = meta_dir / f"{pid}_files.json"
        meta = (
            json.loads(cached_meta.read_text(encoding="utf-8"))
            if cached_meta.exists()
            else json.loads(_http_bytes(f"{BASE}/repo/investigations/{pid}"))
        )
        ver = meta.get("version", 1)
        tree = (
            json.loads(cached_tree.read_text(encoding="utf-8"))
            if cached_tree.exists()
            else json.loads(
                _http_bytes(
                    f"{BASE}/files/v2",
                    {
                        "folder": f"{pid}/",
                        "fileType": "study",
                        "studyId": pid,
                        "version": ver,
                        "obfuscationcode": "",
                    },
                )
            )
        )
        remote_map = _walk_files(tree)
        for fname, rel_subdir in specs:
            info = remote_map.get(fname)
            if not info:
                log_entries.append({
                    "psi_id": pid,
                    "filename": fname,
                    "status": "not_found_in_remote_tree",
                })
                print(f"MISSING {pid}: {fname}", flush=True)
                continue

            dest = RAW_PSI / rel_subdir / fname
            dest.parent.mkdir(parents=True, exist_ok=True)
            fid = info["id"]
            fver = info.get("version", 1)
            permanent_api_url = (
                f"{BASE}/studies/{pid}/download?file={fid}&version={fver}&studyVersion={ver}&redirect=false"
            )
            if dest.exists():
                raw = dest.read_bytes()
                fmt = _validate_format(fname, raw)
                sha = hashlib.sha256(raw).hexdigest()
                log_entries.append({
                    "psi_id": pid,
                    "filename": fname,
                    "relative_path": dest.relative_to(ROOT).as_posix(),
                    "format": fmt,
                    "study_version": ver,
                    "file_version": fver,
                    "file_id": fid,
                    "bytes": len(raw),
                    "sha256": sha,
                    "permanent_catalog_url": f"https://psi.nasa.gov/physci/repo/investigations/{pid}",
                    "permanent_api_download_endpoint": permanent_api_url,
                    "license": meta.get("licenseIdentifier") or "",
                    "doi": meta.get("doi") or "",
                    "accessed_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    "status": "already_present_verified",
                })
                print(f"SKIP_EXISTING {pid}/{fname}: {len(raw)} B", flush=True)
                continue

            signed_raw = _http_bytes(permanent_api_url).decode().strip().strip('"').encode().decode("unicode_escape")
            raw = _http_bytes(signed_raw)
            fmt = _validate_format(fname, raw)
            dest.write_bytes(raw)
            sha = hashlib.sha256(raw).hexdigest()
            log_entries.append({
                "psi_id": pid,
                "filename": fname,
                "relative_path": dest.relative_to(ROOT).as_posix(),
                "format": fmt,
                "study_version": ver,
                "file_version": fver,
                "file_id": fid,
                "bytes": len(raw),
                "sha256": sha,
                "permanent_catalog_url": f"https://psi.nasa.gov/physci/repo/investigations/{pid}",
                "permanent_api_download_endpoint": permanent_api_url,
                "license": meta.get("licenseIdentifier") or "",
                "doi": meta.get("doi") or "",
                "accessed_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "status": "downloaded_verified",
            })
            print(f"OK {pid}/{fname}: {len(raw)} B ({fmt}) sha256={sha[:12]}", flush=True)

    OUT_LOG.write_text(json.dumps(log_entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nCompleted {len(log_entries)} target entries -> {OUT_LOG.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
