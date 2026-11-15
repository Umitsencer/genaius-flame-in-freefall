"""Real and [SYNTHETIC] boundary tests for the standalone PSI-99 SAFFIRE-II module."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from genaius.app_service import AppService
from genaius.saffire import (
    SAFFIRE_CSV_RELPATH,
    SAFFIRE_README_RELPATH,
    SaffireLoadError,
    SaffireValidationError,
    build_saffire_schema,
    load_saffire_dataset,
    run_saffire_reference,
)

ROOT = Path(__file__).resolve().parents[1]


class RealSaffireDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_saffire_dataset(ROOT)
        cls.schema = build_saffire_schema(cls.dataset)
        cls.all_ref = run_saffire_reference(cls.dataset)

    def test_nine_samples_separated_from_six_auxiliary_rows_and_provenance(self):
        self.assertEqual(self.dataset.total_data_rows, 15)
        self.assertEqual(len(self.dataset.cards), 9)
        self.assertEqual(len(self.dataset.auxiliary_rows), 6)

        ids = [c.sample_id for c in self.dataset.cards]
        self.assertEqual(ids, [f"2-{i}" for i in range(1, 10)])
        self.assertEqual(len(set(ids)), 9)

        expected_csv_sha = hashlib.sha256((ROOT / SAFFIRE_CSV_RELPATH).read_bytes()).hexdigest()
        expected_doc_sha = hashlib.sha256((ROOT / SAFFIRE_README_RELPATH).read_bytes()).hexdigest()
        self.assertEqual(self.dataset.csv_sha256, expected_csv_sha)
        self.assertEqual(self.dataset.readme.sha256, expected_doc_sha)

        self.assertEqual(
            [c.physical_csv_line for c in self.dataset.cards],
            list(range(2, 11)),
        )
        self.assertEqual(
            [a.physical_csv_line for a in self.dataset.auxiliary_rows],
            list(range(11, 17)),
        )
        self.assertEqual(
            [a.row_key for a in self.dataset.auxiliary_rows],
            ["F1C1/F1C2", "F2C1/F2C2", "Note 1", "Note 2", "Note 3", "Note 4"],
        )
        self.assertEqual(self.schema["provenance"]["readme_docx"]["paragraph_count"], 27)
        self.assertIn("4", self.schema["provenance"]["readme_docx"]["embedded_image_paragraphs"])
        self.assertIn("7", self.schema["provenance"]["readme_docx"]["embedded_image_paragraphs"])

    def test_ambiguous_037mm_empty_material_see_fig5_and_qualitative_values_unimputed(self):
        by_id = {c["sample_id"]: c for c in self.all_ref["cards"]}

        # 037 mm on 2-4, 2-5, 2-6 preserved literally and never coerced to 37 or silently 0.37
        for sid in ("2-4", "2-5", "2-6"):
            thick = by_id[sid]["test_conditions"]["thickness"]
            self.assertEqual(thick["raw_value"], "037 mm")
            self.assertIsNone(thick["verified_numeric"])
            self.assertEqual(thick["verification_status"], "unresolved_malformed_thickness_and_readme_conflict")

        # Empty Material on 2-6 and 2-9 never forward-filled from 2-5 or 2-8
        for sid in ("2-6", "2-9"):
            mat = by_id[sid]["material"]
            self.assertEqual(mat["raw_value"], "")
            self.assertIsNone(mat["display_value"])
            self.assertFalse(mat["auto_filled_from_previous_row"])
        self.assertEqual(by_id["2-6"]["material"]["readme_table1_material"], "SIBAL fabric")
        self.assertEqual(by_id["2-9"]["material"]["readme_table1_material"], "Flat PMMA")

        # See Fig. 5 on 2-8 unresolved with explicit external source need
        thick_2_8 = by_id["2-8"]["test_conditions"]["thickness"]
        self.assertEqual(thick_2_8["raw_value"], "See Fig. 5")
        self.assertIsNone(thick_2_8["verified_numeric"])
        self.assertEqual(thick_2_8["verification_status"], "unresolved_external_figure_reference")
        self.assertIn("Fig. 5", by_id["2-8"]["external_source_needed"])

        # Complete, ~ 0, Insignificant never turned into exact numbers
        self.assertEqual(by_id["2-1"]["test_conditions"]["burn_time"]["raw_value"], "Insignificant")
        self.assertIsNone(by_id["2-1"]["test_conditions"]["burn_time"]["verified_numeric"])
        self.assertEqual(by_id["2-1"]["results"]["microgravity"]["burn_length"]["raw_value"], "~ 0")
        self.assertIsNone(by_id["2-1"]["results"]["microgravity"]["burn_length"]["verified_numeric"])
        self.assertEqual(by_id["2-1"]["results"]["normal_gravity_reference"]["burn_length"]["raw_value"], "Complete")
        self.assertIsNone(by_id["2-1"]["results"]["normal_gravity_reference"]["burn_length"]["verified_numeric"])

        # Verified scalars kept separately alongside raw values (e.g., 2-2)
        self.assertEqual(by_id["2-2"]["test_conditions"]["thickness"]["verified_numeric"], {"value": 0.61, "unit": "mm"})
        self.assertEqual(by_id["2-2"]["results"]["normal_gravity_reference"]["burn_length"]["verified_numeric"], {"value": 7.6, "unit": "cm"})
        self.assertEqual(by_id["2-2"]["results"]["normal_gravity_reference"]["spread_rate"]["verified_numeric"], {"value": 1.2, "unit": "mm/s"})

    def test_unit_mismatch_derived_o2_and_footnote_links_preserved(self):
        by_id = {c["sample_id"]: c for c in self.all_ref["cards"]}

        # ?-g Spread Length holds mm/s on 2-5 and 2-6 -> never emitted as numeric length chart field
        for sid, raw_val in (("2-5", "2.1 mm/s"), ("2-6", "2.6 mm/s")):
            spread = by_id[sid]["results"]["microgravity"]["spread_length_or_rate"]
            self.assertEqual(spread["raw_header"], "?-g Spread Length")
            self.assertEqual(spread["raw_value"], raw_val)
            self.assertIsNone(spread["verified_numeric"])
            self.assertEqual(spread["verification_status"], "unresolved_header_unit_mismatch")

        # Note 1 derived O2 attached to all 9 cards
        for sid in [f"2-{i}" for i in range(1, 10)]:
            o2 = by_id[sid]["test_conditions"]["percent_o2"]
            self.assertTrue(o2["is_derived"])
            self.assertIsNone(o2["verified_numeric"])
            self.assertIn("Note 1", [n["row_key"] for n in by_id[sid]["footnotes"]])

        # Specific footnote attachments & auxiliary flow-vis conflict on F2
        self.assertIn("Note 2", [n["row_key"] for n in by_id["2-7"]["footnotes"]])
        self.assertIn("Note 3", [n["row_key"] for n in by_id["2-8"]["footnotes"]])
        self.assertIn("Note 4", [n["row_key"] for n in by_id["2-8"]["footnotes"]])
        self.assertIn("Note 4", [n["row_key"] for n in by_id["2-9"]["footnotes"]])
        self.assertEqual([a["row_key"] for a in by_id["2-1"]["auxiliary_flow_records"]], ["F1C1/F1C2"])
        self.assertEqual([a["row_key"] for a in by_id["2-2"]["auxiliary_flow_records"]], ["F2C1/F2C2"])
        self.assertIn("post-flow", by_id["2-2"]["auxiliary_flow_records"][0]["readme_crosscheck"])

    def test_scope_boundaries_strict_json_and_lookup_validation(self):
        self.assertFalse(self.schema["scope"]["queryable_in_core"])
        self.assertFalse(self.schema["scope"]["indexed_in_rag"])
        self.assertFalse(self.schema["scope"]["ceteris_paribus_1g_vs_0g"])
        self.assertFalse(self.schema["scope"]["safety_ranking_enabled"])

        serialized = json.dumps(self.all_ref, allow_nan=False, ensure_ascii=False)
        self.assertNotIn("NaN", serialized)

        single = run_saffire_reference(self.dataset, sample_id="2-8")
        self.assertEqual(single["status"], "OK")
        self.assertEqual(single["total_returned_cards"], 1)
        self.assertEqual(single["cards"][0]["sample_id"], "2-8")

        missing = run_saffire_reference(self.dataset, sample_id="2-10")
        self.assertEqual(missing["status"], "NO_EVIDENCE")
        self.assertEqual(missing["total_returned_cards"], 0)
        self.assertEqual(missing["cards"], [])

        for bad in (123, "", "   ", "../etc/passwd", "1" * 40 + "-1"):
            with self.assertRaises(SaffireValidationError):
                run_saffire_reference(self.dataset, sample_id=bad)  # type: ignore[arg-type]


class SyntheticSaffireBoundaryAndDegradationTests(unittest.TestCase):
    def test_synthetic_corrupt_sources_raise_load_error_and_keep_core_plus_cfi_alive(self):
        # [SYNTHETIC] Verify corrupt CSV/DOCX detection and graceful AppService isolation
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            shutil.copytree(ROOT / "data" / "processed", tmp_root / "data" / "processed")
            shutil.copytree(ROOT / "data" / "raw" / "nasa_docs", tmp_root / "data" / "raw" / "nasa_docs")
            shutil.copytree(ROOT / "data" / "raw" / "psi" / "experimental_tables" / "PSI-25", tmp_root / "data" / "raw" / "psi" / "experimental_tables" / "PSI-25")
            shutil.copytree(ROOT / "data" / "raw" / "psi" / "experimental_tables" / "PSI-69", tmp_root / "data" / "raw" / "psi" / "experimental_tables" / "PSI-69")
            shutil.copytree(ROOT / "data" / "raw" / "psi" / "matrices_and_readmes" / "PSI-25", tmp_root / "data" / "raw" / "psi" / "matrices_and_readmes" / "PSI-25")
            shutil.copytree(ROOT / "data" / "raw" / "psi" / "matrices_and_readmes" / "PSI-39", tmp_root / "data" / "raw" / "psi" / "matrices_and_readmes" / "PSI-39")

            # 1) Missing PSI-99 fails Saffire loader while keeping core (403 runs + 503 chunks) + CFI (144) alive
            with self.assertRaises(SaffireLoadError):
                load_saffire_dataset(tmp_root)

            svc = AppService(tmp_root)
            self.assertEqual(svc.saffire_status, "unavailable")
            self.assertEqual(svc.saffire_schema()["status"], "SAFFIRE_UNAVAILABLE")
            self.assertEqual(svc.saffire_reference({})["status"], "SAFFIRE_UNAVAILABLE")
            self.assertEqual(svc.search({"investigation_id": "PSI-25"})["data"]["total_runs"], 129)
            self.assertEqual(svc.search({"investigation_id": "PSI-69"})["data"]["total_runs"], 274)
            self.assertEqual(svc.schema()["data"]["chunk_count"], 503)
            self.assertEqual(svc.cfi_status, "ready")
            self.assertEqual(svc.cfi_schema()["data"]["pool_summary"]["candidate_pool_count"], 144)
            self.assertEqual(
                svc.evidence({"query": "flammability", "investigation_id": "PSI-99"})["data"]["abstention"]["reason_code"],
                "V12_OUT_OF_SCOPE_STUDY",
            )

            # 2) Corrupt CSV header or corrupt DOCX archive explicitly raises SaffireLoadError
            csv_target = tmp_root / SAFFIRE_CSV_RELPATH
            doc_target = tmp_root / SAFFIRE_README_RELPATH
            csv_target.parent.mkdir(parents=True, exist_ok=True)
            doc_target.parent.mkdir(parents=True, exist_ok=True)
            csv_target.write_text("Wrong,Headers\n2-1,Silicone\n", encoding="utf-8")
            shutil.copy2(ROOT / SAFFIRE_README_RELPATH, doc_target)
            with self.assertRaises(SaffireLoadError):
                load_saffire_dataset(tmp_root)

            shutil.copy2(ROOT / SAFFIRE_CSV_RELPATH, csv_target)
            doc_target.write_bytes(b"not a valid docx zip archive")
            with self.assertRaises(SaffireLoadError):
                load_saffire_dataset(tmp_root)


if __name__ == "__main__":
    unittest.main()
