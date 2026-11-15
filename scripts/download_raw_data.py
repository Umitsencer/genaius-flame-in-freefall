"""Idempotent downloader for official NASA PSI and NTRS raw files into data/raw/.

Downloads the 5 required core sources (PSI-25 CSV/DOCX, PSI-69 CSV, FLEX/BASS-II
NTRS PDFs) and optionally the 4 PSI-39 CFI / PSI-99 SAFFIRE-II files using official
NASA PSI API endpoints and NTRS download URLs from ``DOCUMENT_SPECS``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from genaius.retrieval.documents import DOCUMENT_SPECS  # noqa: E402

PSI_API_BASE = "https://psi.nasa.gov/geode-py/ws"

CORE_PSI_TARGETS: tuple[tuple[str, str, str], ...] = (
    ("PSI-25", "PSI-25_Experimental table_BASS-II.csv", "experimental_tables/PSI-25"),
    ("PSI-25", "PSI-25_Science Documents_BASS-II_ReadMe.docx", "matrices_and_readmes/PSI-25"),
    ("PSI-69", "PSI-69_Experimental table_FLEX.csv", "experimental_tables/PSI-69"),
)

OPTIONAL_PSI_TARGETS: tuple[tuple[str, str, str], ...] = (
    (
        "PSI-39",
        "PSI-39_Science Documents_CFI_DataSummary_Spreadsheet_Jan2021.xlsx",
        "matrices_and_readmes/PSI-39",
    ),
    ("PSI-39", "PSI-39_Experimental table_CFI.csv", "experimental_tables/PSI-39"),
    ("PSI-99", "PSI-99_Experimental table_SAFFIRE-2.csv", "experimental_tables/PSI-99"),
    ("PSI-99", "PSI-99_Science Documents_SAFFIRE-II Readme.docx", "matrices_and_readmes/PSI-99"),
)

TransportFn = Callable[[str, dict[str, Any] | None, float], bytes]


def _default_http_bytes(url: str, post_json: dict[str, Any] | None = None, timeout_s: float = 45.0) -> bytes:
    """Fetch raw bytes from an HTTPS NASA endpoint with brief retry on transient 5xx."""
    if not url.startswith("https://"):
        raise ValueError(f"Only HTTPS URLs are permitted: {url}")
    headers = {"User-Agent": "GeNAIus-SpaceApps-RawFetcher/1.0"}
    data = None
    if post_json is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(post_json).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers)
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return resp.read()
        except Exception as exc:
            last_err = exc
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"Download failed for {url}: {last_err}")


def _walk_psi_tree(node: Any) -> dict[str, dict[str, Any]]:
    """Flatten nested NASA PSI /files/v2 folder nodes into {filename: node_info}."""
    found: dict[str, dict[str, Any]] = {}
    if isinstance(node, list):
        for item in node:
            found.update(_walk_psi_tree(item))
    elif isinstance(node, dict):
        children = node.get("children") or node.get("files") or []
        is_dir = bool(node.get("directory")) or (isinstance(children, list) and bool(children))
        if not is_dir:
            key = str(node.get("key") or node.get("name") or "")
            fname = key.rsplit("/", 1)[-1]
            if fname:
                found[fname] = node
        if isinstance(children, list):
            for child in children:
                found.update(_walk_psi_tree(child))
    return found


def validate_file_magic(filename: str, raw: bytes) -> str:
    """Reject empty files or HTML error pages using magic bytes and extension checks."""
    if not raw:
        raise ValueError(f"Empty download payload for {filename}")
    low = filename.lower()
    if raw[:15].lstrip().lower().startswith((b"<!doctype", b"<html")):
        raise ValueError(f"Unexpected HTML page returned instead of raw file {filename}")
    if low.endswith(".pdf"):
        if not raw.startswith(b"%PDF"):
            raise ValueError(f"{filename} does not begin with %PDF magic bytes")
        return "pdf"
    if low.endswith((".docx", ".xlsx")):
        if not raw.startswith(b"PK"):
            raise ValueError(f"{filename} does not begin with ZIP/Office PK magic bytes")
        return low.rsplit(".", 1)[-1]
    if low.endswith(".csv"):
        head = raw[:4096].decode("utf-8", errors="replace")
        if "," not in head:
            raise ValueError(f"{filename} does not appear to contain comma-delimited CSV data")
        return "csv"
    return low.rsplit(".", 1)[-1] if "." in low else "binary"


def download_all_raw_data(
    dest_root: Path,
    *,
    include_optional: bool = True,
    force: bool = False,
    timeout_s: float = 45.0,
    transport: TransportFn = _default_http_bytes,
) -> list[dict[str, Any]]:
    """Fetch verified core (and optionally PSI-39/PSI-99) NASA raw files into ``dest_root``."""
    results: list[dict[str, Any]] = []
    targets = list(CORE_PSI_TARGETS) + (list(OPTIONAL_PSI_TARGETS) if include_optional else [])
    by_psi: dict[str, list[tuple[str, str]]] = {}
    for pid, fname, rel_sub in targets:
        by_psi.setdefault(pid, []).append((fname, rel_sub))

    raw_psi_root = dest_root / "data" / "raw" / "psi"
    for pid, specs in by_psi.items():
        pending = [
            (fname, rel_sub, raw_psi_root / rel_sub / fname)
            for fname, rel_sub in specs
        ]
        if not force and all(p.exists() for _, _, p in pending):
            for fname, _, dest in pending:
                raw = dest.read_bytes()
                fmt = validate_file_magic(fname, raw)
                results.append(
                    {
                        "source": pid,
                        "path": dest.relative_to(dest_root).as_posix(),
                        "format": fmt,
                        "bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "status": "skipped_existing",
                    }
                )
            continue

        meta = json.loads(transport(f"{PSI_API_BASE}/repo/investigations/{pid}", None, timeout_s))
        ver = meta.get("version", 1)
        tree = json.loads(
            transport(
                f"{PSI_API_BASE}/files/v2",
                {
                    "folder": f"{pid}/",
                    "fileType": "study",
                    "studyId": pid,
                    "version": ver,
                    "obfuscationcode": "",
                },
                timeout_s,
            )
        )
        remote_map = _walk_psi_tree(tree)
        for fname, _, dest in pending:
            if not force and dest.exists():
                raw = dest.read_bytes()
                fmt = validate_file_magic(fname, raw)
                results.append(
                    {
                        "source": pid,
                        "path": dest.relative_to(dest_root).as_posix(),
                        "format": fmt,
                        "bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "status": "skipped_existing",
                    }
                )
                continue
            info = remote_map.get(fname)
            if not info:
                raise FileNotFoundError(f"NASA PSI investigation {pid} file tree missing {fname}")
            fid = info["id"]
            fver = info.get("version", 1)
            dl_api = (
                f"{PSI_API_BASE}/studies/{pid}/download"
                f"?file={fid}&version={fver}&studyVersion={ver}&redirect=false"
            )
            signed_url = transport(dl_api, None, timeout_s).decode("utf-8").strip().strip('"').encode().decode("unicode_escape")
            raw = transport(signed_url, None, timeout_s)
            fmt = validate_file_magic(fname, raw)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
            results.append(
                {
                    "source": pid,
                    "path": dest.relative_to(dest_root).as_posix(),
                    "format": fmt,
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "status": "downloaded",
                }
            )

    for spec in DOCUMENT_SPECS:
        if not spec.official_download_url:
            continue
        dest = dest_root / spec.relative_path
        if not force and dest.exists():
            raw = dest.read_bytes()
            fmt = validate_file_magic(dest.name, raw)
            results.append(
                {
                    "source": spec.document_id,
                    "path": spec.relative_path,
                    "format": fmt,
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "status": "skipped_existing",
                }
            )
            continue
        raw = transport(spec.official_download_url, None, timeout_s)
        fmt = validate_file_magic(dest.name, raw)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        results.append(
            {
                "source": spec.document_id,
                "path": spec.relative_path,
                "format": fmt,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "status": "downloaded",
            }
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest-root", type=Path, default=REPO_ROOT, help="Repository root containing data/raw/")
    parser.add_argument("--core-only", action="store_true", help="Download only the 5 required PSI-25/PSI-69/NTRS core files")
    parser.add_argument("--force", action="store_true", help="Overwrite existing local files")
    parser.add_argument("--timeout", type=float, default=45.0, help="Per-request HTTPS timeout in seconds")
    args = parser.parse_args(argv)

    summary = download_all_raw_data(
        args.dest_root.resolve(),
        include_optional=not args.core_only,
        force=args.force,
        timeout_s=args.timeout,
    )
    print(json.dumps({"files": summary, "count": len(summary)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
