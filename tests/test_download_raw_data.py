"""Offline unit tests for scripts/download_raw_data.py."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import download_raw_data  # noqa: E402


class DownloadRawDataTests(unittest.TestCase):
    def test_validate_file_magic_accepts_expected_formats_and_rejects_html(self) -> None:
        self.assertEqual(download_raw_data.validate_file_magic("sample.pdf", b"%PDF-1.7\n"), "pdf")
        self.assertEqual(download_raw_data.validate_file_magic("readme.docx", b"PK\x03\x04doc"), "docx")
        self.assertEqual(download_raw_data.validate_file_magic("summary.xlsx", b"PK\x03\x04xls"), "xlsx")
        self.assertEqual(download_raw_data.validate_file_magic("table.csv", b"a,b,c\n1,2,3\n"), "csv")

        with self.assertRaises(ValueError):
            download_raw_data.validate_file_magic("bad.pdf", b"<!DOCTYPE html><html>error</html>")
        with self.assertRaises(ValueError):
            download_raw_data.validate_file_magic("bad.csv", b"no commas at all")

    def test_download_all_raw_data_core_only_full_and_skip_existing(self) -> None:
        calls: list[str] = []

        def fake_transport(url: str, post_json: dict | None, timeout_s: float) -> bytes:
            calls.append(url)
            if "/repo/investigations/" in url:
                return json.dumps({"version": 1}).encode("utf-8")
            if url.endswith("/files/v2"):
                pid = str((post_json or {}).get("studyId", ""))
                if pid == "PSI-25":
                    items = [
                        {
                            "directory": True,
                            "key": "Experimental table/",
                            "files": [
                                {"key": "PSI-25/Experimental table/PSI-25_Experimental table_BASS-II.csv", "id": 11, "version": 1},
                            ],
                        },
                        {
                            "directory": True,
                            "key": "Science Documents/",
                            "files": [
                                {"key": "PSI-25/Science Documents/PSI-25_Science Documents_BASS-II_ReadMe.docx", "id": 12, "version": 1},
                            ],
                        },
                    ]
                elif pid == "PSI-69":
                    items = [
                        {"key": "PSI-69/Experimental table/PSI-69_Experimental table_FLEX.csv", "id": 21, "version": 1},
                    ]
                elif pid == "PSI-39":
                    items = [
                        {"key": "PSI-39/Science Documents/PSI-39_Science Documents_CFI_DataSummary_Spreadsheet_Jan2021.xlsx", "id": 31, "version": 1},
                        {"key": "PSI-39/Experimental table/PSI-39_Experimental table_CFI.csv", "id": 32, "version": 1},
                    ]
                else:
                    items = [
                        {"key": "PSI-99/Experimental table/PSI-99_Experimental table_SAFFIRE-2.csv", "id": 41, "version": 1},
                        {"key": "PSI-99/Science Documents/PSI-99_Science Documents_SAFFIRE-II Readme.docx", "id": 42, "version": 1},
                    ]
                return json.dumps({"files": items}).encode("utf-8")
            if "/download?" in url:
                return json.dumps(f"https://signed.example/{url.split('file=')[1].split('&')[0]}").encode("utf-8")
            if url.startswith("https://signed.example/"):
                fid = url.rsplit("/", 1)[-1]
                if fid in {"12", "31", "42"}:
                    return b"PK\x03\x04mockoffice"
                return b"col1,col2\nval1,val2\n"
            if url.endswith(".pdf"):
                return b"%PDF-1.4\nmockpdf"
            raise AssertionError(f"Unexpected URL: {url}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            core = download_raw_data.download_all_raw_data(
                root,
                include_optional=False,
                transport=fake_transport,
            )
            self.assertEqual(len(core), 5)
            self.assertTrue(all(item["status"] == "downloaded" for item in core))
            for item in core:
                self.assertTrue((root / item["path"]).exists())

            calls_before_reskip = len(calls)
            reskip = download_raw_data.download_all_raw_data(
                root,
                include_optional=False,
                transport=fake_transport,
            )
            self.assertEqual(len(reskip), 5)
            self.assertTrue(all(item["status"] == "skipped_existing" for item in reskip))
            self.assertEqual(len(calls), calls_before_reskip)

            full = download_raw_data.download_all_raw_data(
                root,
                include_optional=True,
                transport=fake_transport,
            )
            self.assertEqual(len(full), 9)
            statuses = {item["status"] for item in full}
            self.assertEqual(statuses, {"skipped_existing", "downloaded"})
            self.assertEqual(sum(1 for item in full if item["status"] == "downloaded"), 4)


if __name__ == "__main__":
    unittest.main()
