"""Tests for NASA PSI Combustion Science catalog loading and deterministic search.

Note: Tests validate deterministic catalog joins, support-tier boundaries against
`DATASET_SPECS`, error handling on corrupt/inconsistent metadata, and lexical field
matching provenance. Synthetic fixtures are explicitly isolated in `SyntheticCatalogTests`.
These tests do NOT evaluate scientific ranking validity or fire-safety risk.
"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from genaius.catalog import (
    DEFAULT_CFI_FEASIBILITY_RELPATH,
    DEFAULT_COMPARISON_CSV_RELPATH,
    DEFAULT_MANIFEST_RELPATH,
    RANKING_ALGORITHM,
    CatalogLoadError,
    CatalogValidationError,
    load_research_catalog,
    search_catalog,
)
from genaius.data.contracts import DATASET_SPECS
from genaius.retrieval.bm25 import tokenize_text

REPO_ROOT = Path(__file__).resolve().parents[1]


class RealCatalogTests(unittest.TestCase):
    """Verify the real 24 NASA PSI Combustion Science catalog and boundaries."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_research_catalog(REPO_ROOT)

    def test_24_unique_ids_and_clean_provenance_join(self) -> None:
        self.assertEqual(len(self.catalog.entries), 24)
        ids = [entry.psi_id for entry in self.catalog.entries]
        self.assertEqual(len(set(ids)), 24)
        self.assertEqual(self.catalog.manifest_generated_utc, "2026-11-14T10:01:33+00:00")
        self.assertIn(DEFAULT_MANIFEST_RELPATH, self.catalog.source_hashes)
        self.assertIn(DEFAULT_COMPARISON_CSV_RELPATH, self.catalog.source_hashes)
        self.assertIn(DEFAULT_CFI_FEASIBILITY_RELPATH, self.catalog.source_hashes)

        # Missing optional portal metadata stays None (never fabricated)
        psi60 = self.catalog.get("PSI-60")
        self.assertIsNotNone(psi60)
        assert psi60 is not None
        self.assertIsNone(psi60.acronym)
        self.assertIsNone(psi60.flight_program)

        psi10 = self.catalog.get("PSI-10")
        self.assertIsNotNone(psi10)
        assert psi10 is not None
        self.assertIsNone(psi10.license)

        # Source provenance & portal fields are preserved
        psi69 = self.catalog.get("PSI-69")
        self.assertIsNotNone(psi69)
        assert psi69 is not None
        self.assertEqual(psi69.doi, "10.60555/mbq8-0451")
        self.assertEqual(psi69.catalog_url, "https://psi.nasa.gov/physci/repo/investigations/PSI-69")
        self.assertEqual(psi69.version, 5)
        self.assertEqual(psi69.provenance.manifest_record_key, "studies[psi_id=PSI-69]")
        self.assertEqual(psi69.provenance.comparison_csv_key, "PSI-ID=PSI-69")
        self.assertEqual(len(psi69.provenance.manifest_sha256), 64)
        self.assertEqual(len(psi69.provenance.comparison_csv_sha256), 64)

        # Documented Cygnus vs ISS metadata discrepancy on SAFFIRE-I / III
        psi98 = self.catalog.get("PSI-98")
        psi100 = self.catalog.get("PSI-100")
        assert psi98 is not None and psi100 is not None
        self.assertTrue(any("Cygnus" in item for item in psi98.source_discrepancies))
        self.assertTrue(any("Cygnus" in item for item in psi100.source_discrepancies))

    def test_core_support_matches_dataset_specs_and_excludes_cfi_and_samer(self) -> None:
        expected_core = set(DATASET_SPECS.keys())
        actual_core = {e.psi_id for e in self.catalog.entries if e.support.queryable_in_core}
        self.assertEqual(actual_core, expected_core)
        self.assertEqual(set(self.catalog.core_investigation_ids), expected_core)

        # All 24 entries are catalogued and reviewed; only DATASET_SPECS are queryable_in_core
        for entry in self.catalog.entries:
            self.assertTrue(entry.support.catalogued)
            self.assertTrue(entry.support.reviewed)
            self.assertEqual(entry.support.queryable_in_core, entry.psi_id in expected_core)

        # PSI-39 (CFI): strict wording and zero copied stale completed-Farnesane claims
        psi39 = self.catalog.get("PSI-39")
        assert psi39 is not None
        self.assertFalse(psi39.support.queryable_in_core)
        self.assertEqual(psi39.support.support_tier, "reviewed / descriptive extension proposed")
        self.assertEqual(psi39.evaluation_scope_status, "reviewed / descriptive extension proposed")
        self.assertNotIn("146 tamamlanm", psi39.evaluation_summary.lower())
        self.assertNotIn("1. öncelikli mvp", psi39.evaluation_summary.lower())
        self.assertTrue(any("PSI_24_KARSILASTIRMA.csv" in d for d in psi39.source_discrepancies))
        self.assertEqual(psi39.provenance.extra_review_relpath, DEFAULT_CFI_FEASIBILITY_RELPATH)

        # PSI-101 (SAME-R): strictly outside core
        psi101 = self.catalog.get("PSI-101")
        assert psi101 is not None
        self.assertFalse(psi101.support.queryable_in_core)
        self.assertEqual(psi101.support.support_tier, "reviewed")

    def test_exact_psi_id_and_acronym_matches(self) -> None:
        id_res = search_catalog(self.catalog, "PSI-69")
        self.assertEqual(id_res.status, "OK")
        self.assertEqual(id_res.ranking_algorithm, RANKING_ALGORITHM)
        self.assertEqual(id_res.total_matches, 1)
        self.assertEqual(id_res.hits[0].entry.psi_id, "PSI-69")
        self.assertIn("psi_id", id_res.hits[0].matched_fields)
        self.assertIn("psi-69", id_res.hits[0].matched_terms)

        flex_res = search_catalog(self.catalog, "FLEX")
        self.assertEqual(flex_res.status, "OK")
        self.assertGreaterEqual(flex_res.total_matches, 2)
        self.assertEqual(flex_res.hits[0].entry.psi_id, "PSI-69")
        self.assertEqual(flex_res.hits[0].matched_fields, ("acronym",))
        self.assertEqual(flex_res.hits[0].matched_terms, ("flex",))
        self.assertEqual(flex_res.hits[1].entry.psi_id, "PSI-68")
        self.assertGreater(flex_res.hits[0].score, flex_res.hits[1].score)

        cfi_res = search_catalog(self.catalog, "CFI")
        self.assertEqual(cfi_res.status, "OK")
        self.assertEqual(cfi_res.hits[0].entry.psi_id, "PSI-39")
        self.assertFalse(cfi_res.hits[0].entry.support.queryable_in_core)
        self.assertEqual(cfi_res.hits[0].entry.support.support_tier, "reviewed / descriptive extension proposed")

    def test_filters_and_match_explanation_alignment_and_stable_ties(self) -> None:
        ground_res = search_catalog(self.catalog, None, project_type="Ground Investigation")
        self.assertEqual(ground_res.status, "OK")
        self.assertEqual(
            [h.entry.psi_id for h in ground_res.hits],
            ["PSI-60", "PSI-62", "PSI-115", "PSI-117", "PSI-142"],
        )

        droplet_ground = search_catalog(
            self.catalog, "droplet", project_type="Ground Investigation", sub_research_area="Droplet"
        )
        self.assertEqual(droplet_ground.status, "OK")
        self.assertEqual([h.entry.psi_id for h in droplet_ground.hits], ["PSI-117"])

        core_only = search_catalog(self.catalog, None, queryable_in_core=True)
        self.assertEqual({h.entry.psi_id for h in core_only.hits}, set(DATASET_SPECS.keys()))

        # Deterministic tie-breaking on SAFFIRE studies & cool flame query
        saffire_res = search_catalog(self.catalog, "SAFFIRE")
        self.assertEqual(
            [h.entry.psi_id for h in saffire_res.hits],
            ["PSI-98", "PSI-99", "PSI-100"],
        )

        cf_res_1 = search_catalog(self.catalog, "cool flame", top_k=5)
        cf_res_2 = search_catalog(self.catalog, "cool flame", top_k=5)
        self.assertEqual([h.entry.psi_id for h in cf_res_1.hits], [h.entry.psi_id for h in cf_res_2.hits])
        self.assertEqual(cf_res_1.hits[0].entry.psi_id, "PSI-117")
        self.assertEqual(cf_res_1.hits[1].entry.psi_id, "PSI-142")

        # Every matched_field / matched_term is genuinely present in that entry's catalog fields
        for hit in cf_res_1.hits:
            self.assertTrue(hit.matched_fields)
            self.assertTrue(hit.matched_terms)
            self.assertIn("not a scientific importance or safety rating", hit.ranking_reason)
            for fname, fterms in hit.field_matches.items():
                raw_field = getattr(hit.entry, fname) or ""
                field_tokens = set(tokenize_text(raw_field))
                for term in fterms:
                    self.assertIn(term, field_tokens)

    def test_nonsense_query_returns_no_match_and_invalid_inputs_raise(self) -> None:
        empty_match = search_catalog(self.catalog, "quantum warp propulsion")
        self.assertEqual(empty_match.status, "NO_MATCH")
        self.assertEqual(empty_match.total_matches, 0)
        self.assertEqual(empty_match.hits, ())

        # Stale completed-Farnesane text is never searchable as a measured PSI-39 fuel
        farnesane_res = search_catalog(self.catalog, "farnesane")
        self.assertEqual(farnesane_res.status, "NO_MATCH")

        with self.assertRaises(CatalogValidationError):
            search_catalog(self.catalog, "   ")
        with self.assertRaises(CatalogValidationError):
            search_catalog(self.catalog, "FLEX", top_k=0)
        with self.assertRaises(CatalogValidationError):
            search_catalog(self.catalog, "FLEX", queryable_in_core="yes")  # type: ignore[arg-type]


class SyntheticCatalogTests(unittest.TestCase):
    """[SYNTHETIC] Tests validating explicit load failures on corrupt or mismatched fixtures."""

    def _write_synthetic_pair(
        self,
        tmp: Path,
        *,
        studies: list[dict[str, object]],
        csv_rows: list[dict[str, str]],
        study_count: int | None = None,
    ) -> tuple[str, str]:
        manifest_rel = "manifest_synthetic.json"
        csv_rel = "comparison_synthetic.csv"
        manifest_payload = {
            "generated_utc": "2026-01-01T00:00:00+00:00",
            "scope": "SYNTHETIC TEST CATALOG",
            "source_search_url": "https://example.invalid/synthetic",
            "study_count": len(studies) if study_count is None else study_count,
            "studies": studies,
        }
        (tmp / manifest_rel).write_text(json.dumps(manifest_payload), encoding="utf-8")

        fieldnames = ["PSI-ID", "başlık", "tür", "kalite sınırı", "kullanım önerisi", "karar", "gerekçe"]
        with (tmp / csv_rel).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_rows)
        return manifest_rel, csv_rel

    @staticmethod
    def _sample_study(psi_id: str, title: str = "Synthetic Study") -> dict[str, object]:
        return {
            "psi_id": psi_id,
            "title": title,
            "acronym": "SYN",
            "version": 1,
            "research_area": "Combustion Science",
            "sub_research_area": "Synthetic",
            "project_type": "Microgravity Investigation",
            "flight_program": "Synthetic ISS",
            "license": "CC0-1.0",
            "doi": "10.0000/synthetic",
            "catalog_url": f"https://example.invalid/{psi_id}",
            "metadata_api_url": f"https://example.invalid/api/{psi_id}",
            "publication_count": 0,
            "publications": [],
            "local_files": [],
            "remote_summary": {"total_files": 0},
        }

    @staticmethod
    def _sample_csv_row(psi_id: str, karar: str = "C. Synthetic reference only") -> dict[str, str]:
        return {
            "PSI-ID": psi_id,
            "başlık": f"Synthetic {psi_id}",
            "tür": "Microgravity Investigation",
            "kalite sınırı": "Synthetic fixture boundary",
            "kullanım önerisi": "Synthetic fixture note",
            "karar": karar,
            "gerekçe": "Synthetic rationale",
        }

    def test_synthetic_missing_and_duplicate_and_mismatched_ids_raise_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)

            # 1. [SYNTHETIC] ID present in manifest but missing from CSV
            m_rel, c_rel = self._write_synthetic_pair(
                tmp,
                studies=[self._sample_study("PSI-25"), self._sample_study("PSI-69")],
                csv_rows=[self._sample_csv_row("PSI-25")],
            )
            with self.assertRaises(CatalogLoadError):
                load_research_catalog(
                    tmp,
                    manifest_relpath=m_rel,
                    comparison_csv_relpath=c_rel,
                    cfi_feasibility_relpath=None,
                    expected_count=None,
                )

            # 2. [SYNTHETIC] Duplicate psi_id in manifest
            m_rel, c_rel = self._write_synthetic_pair(
                tmp,
                studies=[self._sample_study("PSI-25"), self._sample_study("PSI-25")],
                csv_rows=[self._sample_csv_row("PSI-25"), self._sample_csv_row("PSI-69")],
            )
            with self.assertRaises(CatalogLoadError):
                load_research_catalog(
                    tmp,
                    manifest_relpath=m_rel,
                    comparison_csv_relpath=c_rel,
                    cfi_feasibility_relpath=None,
                    expected_count=None,
                )

            # 3. [SYNTHETIC] Duplicate PSI-ID in CSV
            m_rel, c_rel = self._write_synthetic_pair(
                tmp,
                studies=[self._sample_study("PSI-25"), self._sample_study("PSI-69")],
                csv_rows=[self._sample_csv_row("PSI-25"), self._sample_csv_row("PSI-25")],
            )
            with self.assertRaises(CatalogLoadError):
                load_research_catalog(
                    tmp,
                    manifest_relpath=m_rel,
                    comparison_csv_relpath=c_rel,
                    cfi_feasibility_relpath=None,
                    expected_count=None,
                )

            # 4. [SYNTHETIC] Missing active DATASET_SPECS study fails loud
            m_rel, c_rel = self._write_synthetic_pair(
                tmp,
                studies=[self._sample_study("PSI-25")],
                csv_rows=[self._sample_csv_row("PSI-25")],
            )
            with self.assertRaises(CatalogLoadError):
                load_research_catalog(
                    tmp,
                    manifest_relpath=m_rel,
                    comparison_csv_relpath=c_rel,
                    cfi_feasibility_relpath=None,
                    expected_count=1,
                )

            # 5. [SYNTHETIC] Expected count enforcement fails when count != expected_count
            m_rel, c_rel = self._write_synthetic_pair(
                tmp,
                studies=[self._sample_study("PSI-25"), self._sample_study("PSI-69")],
                csv_rows=[self._sample_csv_row("PSI-25"), self._sample_csv_row("PSI-69")],
            )
            with self.assertRaises(CatalogLoadError):
                load_research_catalog(
                    tmp,
                    manifest_relpath=m_rel,
                    comparison_csv_relpath=c_rel,
                    cfi_feasibility_relpath=None,
                    expected_count=24,
                )


if __name__ == "__main__":
    unittest.main()
