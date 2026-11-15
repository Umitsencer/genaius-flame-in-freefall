"""Tests for the separate PSI-39 (CFI) read-only descriptive research module.

Real-workbook checks validate independent raw-cell reading against `openpyxl`,
pool denominators, zero/empty/literal-NaN separation, gas anomaly exclusions,
sensitivity scenario consistency, and strict JSON output.
Synthetic boundary tests are explicitly marked `[SYNTHETIC]` in
`SyntheticCfiBoundaryAndDegradationTests`.
"""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import unittest
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from genaius.app_service import AppService
from genaius.cfi import (
    WORKBOOK_RELPATH,
    CfiLoadError,
    CfiValidationError,
    build_cfi_schema,
    load_cfi_dataset,
    run_cfi_analysis,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class RealCfiDatasetTests(unittest.TestCase):
    """Real PSI-39 CFI workbook verification against independent raw Excel reads."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = load_cfi_dataset(REPO_ROOT)

    def test_key_alignment_1274A_and_pool_denominators(self) -> None:
        counts = self.dataset.pool_counts
        self.assertEqual(counts["total_records"], 227)
        self.assertEqual(counts["completed_analysis_yes"], 146)
        self.assertEqual(counts["completed_analysis_no"], 81)
        self.assertEqual(counts["excluded_non_ignited_ids"], ["1212", "1235"])
        self.assertEqual(counts["candidate_pool_count"], 144)
        self.assertEqual(counts["farnesane_in_yes"], 0)
        self.assertEqual(counts["farnesane_in_no"], 44)
        self.assertEqual(counts["kcool_missing_in_yes_146"], 22)
        self.assertEqual(counts["kcool_missing_in_candidates_144"], 20)

        self.assertEqual(
            counts["dext_cool_yes_146_breakdown"],
            {"positive": 69, "raw_zero": 48, "empty": 27, "literal_nan": 2},
        )
        self.assertEqual(
            counts["dext_cool_candidates_144_breakdown"],
            {"positive": 69, "raw_zero": 48, "empty": 25, "literal_nan": 2},
        )

        # Preserve stripped alphanumeric ID '1274A' and hash-checked audit match
        by_key = {r.flex_number: r for r in self.dataset.records}
        self.assertIn("1274A", by_key)
        self.assertEqual(by_key["1274A"].sheet_rows["Master Sheet"], 71)
        self.assertEqual(by_key["1274A"].sheet_rows["DATA"], 71)
        self.assertEqual(self.dataset.audit_comparison["status"], "verified_matching")
        self.assertTrue(self.dataset.audit_comparison["matches_computed"])

        # Literal NaN strings (1331, 1338) stay distinct from empty and zero
        self.assertEqual(by_key["1331"].dext_cool_mm.kind, "literal_nan")
        self.assertEqual(by_key["1338"].dext_cool_mm.kind, "literal_nan")
        self.assertIsNone(by_key["1331"].dext_cool_mm.value)

    def test_gas_anomalies_and_pressure_fiber_stratification(self) -> None:
        # 1219, 1221, 1222 have O2=0.21, N2=0.76, He=0 (sum=0.97); 1213 has source conflict
        all_air_ids: set[str] = set()
        for p in (0.5, 0.75, 1.0, 1.25):
            for fib in ("Yes", "No"):
                res = run_cfi_analysis(self.dataset, pressure_atm=p, fiber=fib)
                for grp in res["fuel_groups"]:
                    all_air_ids.update(grp["record_ids"])

        for excluded_anomaly in ("1213", "1219", "1220", "1221", "1222", "1212", "1235"):
            self.assertNotIn(excluded_anomaly, all_air_ids)

        # Fiber=Yes and Fiber=No are strictly disjoint cohorts at 1.0 atm
        yes_1atm = run_cfi_analysis(self.dataset, pressure_atm=1.0, fiber="Yes")
        no_1atm = run_cfi_analysis(self.dataset, pressure_atm=1.0, fiber="No")
        yes_ids = {rid for g in yes_1atm["fuel_groups"] for rid in g["record_ids"]}
        no_ids = {rid for g in no_1atm["fuel_groups"] for rid in g["record_ids"]}
        self.assertEqual(len(yes_ids & no_ids), 0)
        self.assertEqual(yes_ids, {"1207", "1208", "1209", "1210", "1211", "1218", "1248", "1249", "1253",
                                     "1295", "1296", "1300", "1301"})
        self.assertEqual(no_ids, {"1206", "1247", "1250", "1251", "1252", "1297", "1298", "1299", "1302"})

        # Unsupported pressures / Fiber=all / Farnesane are rejected loudly
        for bad_kwargs in (
            {"pressure_atm": 3.0, "fiber": "Yes"},
            {"pressure_atm": 1.0, "fiber": "all"},
            {"pressure_atm": 1.0, "fiber": "Yes", "fuel": "Farnesane"},
            {"pressure_atm": 1.0, "fiber": "Yes", "sensitivity_mode": "unknown"},
        ):
            with self.assertRaises(CfiValidationError):
                run_cfi_analysis(self.dataset, **bad_kwargs)

    def test_1atm_kcool_and_dext_cool_verified_independently_from_raw_workbook(self) -> None:
        # Read raw Excel directly to verify numbers without copying application output
        wb = openpyxl.load_workbook(REPO_ROOT / WORKBOOK_RELPATH, data_only=True, read_only=True)
        try:
            def _sheet(name: str) -> dict[str, dict[str, object]]:
                rows = list(wb[name].iter_rows(values_only=True))
                hdr = [str(c).strip() if c is not None else "" for c in rows[0]]
                return {
                    str(dict(zip(hdr, r))["Flex Number"]).strip(): dict(zip(hdr, r))
                    for r in rows[1:]
                    if any(v is not None for v in r)
                }

            m = _sheet("Master Sheet")
            d = _sheet("DATA")
        finally:
            wb.close()

        expected_kcool: dict[str, list[float]] = {}
        expected_dext_pos: dict[str, list[float]] = {}
        expected_dext_zero: dict[str, int] = {}
        for k, mr in m.items():
            dr = d[k]
            if (
                str(dr.get("Completed Analysis?")).strip() == "Yes"
                and k not in {"1212", "1235"}
                and float(dr["Pressure (atm)"]) == 1.0
                and float(mr["Oxygen"]) == 0.21
                and float(mr["Nitrogen"]) == 0.79
                and float(mr["Helium"]) == 0.0
                and str(mr.get("Fiber")).strip() == "Yes"
            ):
                fuel_raw = str(mr["Fuel"]).strip()
                fuel_norm = (
                    "75/25 C12H26/iso-dodecane" if "[.75]/[.25]" in fuel_raw
                    else "60/40 C12H26/iso-dodecane" if "[.60]/[.40]" in fuel_raw
                    else fuel_raw
                )
                expected_kcool.setdefault(fuel_norm, []).append(float(dr["kcool ( mm^2/s )"]))
                dc = dr["Dext,cool ( mm )"]
                expected_dext_pos.setdefault(fuel_norm, [])
                expected_dext_zero.setdefault(fuel_norm, 0)
                if isinstance(dc, (int, float)):
                    if float(dc) > 0:
                        expected_dext_pos[fuel_norm].append(float(dc))
                    elif float(dc) == 0:
                        expected_dext_zero[fuel_norm] += 1

        res = run_cfi_analysis(self.dataset, pressure_atm=1.0, fiber="Yes")
        by_fuel = {g["fuel"]: g for g in res["fuel_groups"]}
        for fuel_name, kvals in expected_kcool.items():
            grp = by_fuel[fuel_name]
            self.assertEqual(grp["kcool"]["n_finite"], len(kvals))
            self.assertAlmostEqual(grp["kcool"]["median"], statistics.median(kvals), places=6)
            self.assertAlmostEqual(grp["kcool"]["min"], min(kvals), places=6)
            self.assertAlmostEqual(grp["kcool"]["max"], max(kvals), places=6)
            self.assertEqual(grp["dext_cool_mm"]["n_positive"], len(expected_dext_pos[fuel_name]))
            self.assertEqual(grp["dext_cool_mm"]["n_raw_zero_unresolved"], expected_dext_zero[fuel_name])
            self.assertEqual(
                grp["dext_cool_mm"]["positive_median"],
                round(statistics.median(expected_dext_pos[fuel_name]), 6),
            )

        # Strict finite JSON check (allow_nan=False)
        schema_doc = build_cfi_schema(self.dataset)
        json.dumps(schema_doc, allow_nan=False)
        json.dumps(res, allow_nan=False)
        self.assertFalse(schema_doc["scope"]["cfi_report_indexed_in_rag"])

    def test_sensitivity_scenarios_and_no_evidence_denominator_consistency(self) -> None:
        # 1.0 atm C12H26 Fiber=Yes: 9 all -> 7 exclude_extrap_cf_1 -> 6 conservative_comment_flags
        all_c = run_cfi_analysis(self.dataset, pressure_atm=1.0, fiber="Yes", fuel="C12H26", sensitivity_mode="all_candidates")
        no_ext = run_cfi_analysis(self.dataset, pressure_atm=1.0, fiber="Yes", fuel="C12H26", sensitivity_mode="exclude_extrap_cf_1")
        cons = run_cfi_analysis(
            self.dataset, pressure_atm=1.0, fiber="Yes", fuel="C12H26", sensitivity_mode="conservative_comment_flags"
        )
        self.assertEqual(all_c["fuel_groups"][0]["n_candidates"], 9)
        self.assertEqual(no_ext["fuel_groups"][0]["n_candidates"], 7)
        self.assertEqual(no_ext["fuel_groups"][0]["kcool"]["n_finite"], 7)
        self.assertEqual(cons["fuel_groups"][0]["n_candidates"], 6)
        self.assertIn("konservatif duyarlılık senaryosu", cons["fuel_groups"][0]["sensitivity_label"])
        for dropped in ("1208", "1209", "1210"):
            self.assertNotIn(dropped, cons["fuel_groups"][0]["record_ids"])

        # 0.50 atm Fiber=Yes C12H26: 1237 and 1238 are both reused_droplet -> empty under exclude_reused_droplet
        half_all = run_cfi_analysis(self.dataset, pressure_atm=0.5, fiber="Yes", fuel="C12H26")
        half_no_reuse = run_cfi_analysis(
            self.dataset, pressure_atm=0.5, fiber="Yes", fuel="C12H26", sensitivity_mode="exclude_reused_droplet"
        )
        self.assertEqual(half_all["total_candidates_in_cell"], 2)
        self.assertEqual(half_no_reuse["total_candidates_in_cell"], 2)
        self.assertEqual(half_no_reuse["total_returned_records"], 0)
        self.assertEqual(half_no_reuse["status"], "NO_EVIDENCE")

        # Real empty cell: 0.50 atm, Fiber=No, 75/25 C12H26/iso-dodecane has 0 candidates
        empty_cell = run_cfi_analysis(self.dataset, pressure_atm=0.5, fiber="No", fuel="75/25 C12H26/iso-dodecane")
        self.assertEqual(empty_cell["status"], "NO_EVIDENCE")
        self.assertEqual(empty_cell["fuel_groups"], [])


class SyntheticCfiBoundaryAndDegradationTests(unittest.TestCase):
    """[SYNTHETIC] Tests for malformed key joins, stale JSON hash guards, and core isolation."""

    @staticmethod
    def _write_synthetic_workbook(
        path: Path,
        *,
        duplicate_in_data: bool = False,
        drop_in_comments: bool = False,
        shuffle_data_order: bool = False,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        wb = openpyxl.Workbook()
        ws_m = wb.active
        ws_m.title = "Master Sheet"
        ws_m.append(["Flex Number", "Test Date", "CIR ", "Pressure", "Oxygen", "Nitrogen", "Helium", "Fiber", "Fuel "])
        ws_m.append([1274, "2020-01-01", "c1", "1 atm", 0.21, 0.79, 0.0, "Yes", "C12H26"])
        ws_m.append(["1274A ", "2020-01-02", "c2", "1 atm", 0.21, 0.79, 0.0, "Yes", "C12H26"])

        ws_d = wb.create_sheet("DATA")
        ws_d.append(["Flex Number", "Pressure (atm)", "Completed Analysis?", "D0 ( mm )", "Dext, hot ( mm )",
                     " khot ( mm^2/s )", "kcool ( mm^2/s )", "Dext,cool ( mm )", "Extrap CF?", "Reignitions"])
        row_a = [" 1274A ", 1.0, "Yes", 4.1, 3.2, 0.6, 0.41, 0.0, 0, 0]
        row_b = ["1274" if duplicate_in_data else 1274, 1.0, "Yes", 4.0, 3.0, 0.5, 0.39, "NaN", 0, 0]
        if shuffle_data_order:
            ws_d.append(row_a)
            ws_d.append(["1274" if duplicate_in_data else 1274, 1.0, "Yes", 4.0, 3.0, 0.5, 0.39, 0.5, 0, 0] if not duplicate_in_data else ["1274", 1.0, "Yes", 4.0, 3.0, 0.5, 0.39, 0.5, 0, 0])
        else:
            ws_d.append(row_b)
            ws_d.append(["1274" if duplicate_in_data else "1274A", 1.0, "Yes", 4.1, 3.2, 0.6, 0.41, 0.0, 0, 0])

        if duplicate_in_data:
            ws_d.append(["1274", 1.0, "Yes", 4.0, 3.0, 0.5, 0.39, 0.5, 0, 0])

        ws_cam = wb.create_sheet("Camera Settings")
        ws_cam.append(["Flex Number"])
        ws_cam.append([1274])
        ws_cam.append(["1274A"])

        ws_ign = wb.create_sheet("Igniter")
        ws_ign.append(["Flex Number"])
        ws_ign.append([1274])
        ws_ign.append(["1274A"])

        ws_cmt = wb.create_sheet("Comments")
        ws_cmt.append(["Flex Number", "Comments "])
        ws_cmt.append([1274, "clean run"])
        if not drop_in_comments:
            ws_cmt.append(["1274A", "noticeable glow of fiber"])

        wb.save(path)
        wb.close()

    def test_synthetic_key_order_independence_stale_hash_and_duplicate_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wb_path = root / WORKBOOK_RELPATH
            audit_path = root / "data" / "processed" / "cfi_eligibility_audit.json"
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit_path.write_text(json.dumps({"sources": {"workbook": {"sha256": "deadbeef"}}}), encoding="utf-8")

            # [SYNTHETIC] Out-of-order DATA rows still align by stripped key and reject stale JSON hash
            self._write_synthetic_workbook(wb_path, shuffle_data_order=True)
            ds = load_cfi_dataset(root)
            self.assertEqual([r.flex_number for r in ds.records], ["1274", "1274A"])
            self.assertEqual(ds.records[1].sheet_rows["DATA"], 2)  # out-of-order DATA row tracked accurately
            self.assertIn("fiber_glow_or_slip", ds.records[1].comment_flags)
            self.assertEqual(ds.audit_comparison["status"], "stale_hash_mismatch")

            # [SYNTHETIC] Duplicate key fails loudly
            self._write_synthetic_workbook(wb_path, duplicate_in_data=True)
            with self.assertRaises(CfiLoadError):
                load_cfi_dataset(root)

            # [SYNTHETIC] Cross-sheet missing key fails loudly
            self._write_synthetic_workbook(wb_path, drop_in_comments=True)
            with self.assertRaises(CfiLoadError):
                load_cfi_dataset(root)

    def test_synthetic_missing_cfi_does_not_break_core_and_evidence_gate_preserved(self) -> None:
        def _broken_cfi(_root: Path):
            raise CfiLoadError("C:/hidden/local/path/missing_openpyxl")

        service = AppService(REPO_ROOT, cfi_loader=_broken_cfi)
        self.assertEqual(service.cfi_status, "unavailable")

        schema_res = service.cfi_schema()
        analysis_res = service.cfi_analysis({"pressure_atm": 1.0, "fiber": "Yes"})
        self.assertEqual(schema_res["status"], "CFI_UNAVAILABLE")
        self.assertEqual(analysis_res["status"], "CFI_UNAVAILABLE")
        self.assertNotIn("C:/hidden", schema_res["message"])
        self.assertNotIn("missing_openpyxl", analysis_res["message"])

        # Core 403 runs + 503 passages + V12 evidence gate remain fully intact
        self.assertEqual(service.search({"investigation_id": "PSI-25"})["data"]["total_runs"], 129)
        self.assertEqual(service.search({"investigation_id": "PSI-69"})["data"]["total_runs"], 274)
        self.assertEqual(service.schema()["data"]["chunk_count"], 503)
        ev_cfi = service.evidence({"query": "Cool flames", "investigation_id": "PSI-39"})
        self.assertEqual(ev_cfi["status"], "ABSTAINED")
        self.assertEqual(ev_cfi["data"]["abstention"]["reason_code"], "V12_OUT_OF_SCOPE_STUDY")


if __name__ == "__main__":
    unittest.main()
