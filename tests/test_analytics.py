"""Tests for descriptive analytics, source-linked plot points, and CSV/JSON export.

Synthetic fixtures are clearly marked `[SYNTHETIC]` in `SyntheticAnalyticsTests`.
Real-dataset tests verify consistency against `filter_records` and `summarize_field`;
test results are software verification checks, not scientific findings or model scores.
"""

from __future__ import annotations

import csv
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from genaius.analytics import (
    _escape_csv_cell,
    build_descriptive_analytics,
    build_export_payload,
)
from genaius.data.contracts import (
    ExperimentRecord,
    MeasurementStatus,
    SourceLocation,
    TypedMeasurement,
)
from genaius.data.loader import load_core_datasets
from genaius.data.query import NumericRangeFilter, QueryValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]


class RealAnalyticsTests(unittest.TestCase):
    """Verify real PSI-25 / PSI-69 descriptive analytics, denominators, and export boundaries."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.records, _ = load_core_datasets(REPO_ROOT)

    def test_same_subset_and_consistent_status_denominators_on_high_pressure_flex(self) -> None:
        nf = (NumericRangeFilter(field_name="ambient_pressure_kpa", unit="mmHg", min_value=2200),)
        analytics = build_descriptive_analytics(
            self.records,
            investigation_id="PSI-69",
            field_name="burning_rate_mm2_s",
            unit="mm²/s",
            numeric_filters=nf,
        ).to_dict()

        self.assertEqual(analytics["total_runs"], 3)
        self.assertEqual(analytics["unique_flex_identifier_count"], 3)
        self.assertEqual(analytics["summary"]["candidate_run_count"], 3)
        self.assertEqual(analytics["summary"]["used_measured_count"], 2)
        self.assertEqual(analytics["summary"]["excluded_by_status"]["missing"], 1)
        self.assertEqual(analytics["summary"]["mean_value"], 0.385)
        self.assertEqual(analytics["summary"]["median_value"], 0.385)

        # Denominator consistency across summary, raw_points, and status_distribution
        total_from_status = sum(item["count"] for item in analytics["status_distribution"])
        self.assertEqual(total_from_status, analytics["total_runs"])
        self.assertEqual(len(analytics["raw_points"]), analytics["total_runs"])
        used_pts = [pt for pt in analytics["raw_points"] if pt["used_in_summary"]]
        self.assertEqual(len(used_pts), analytics["summary"]["used_total_count"])

        # Missing test 12 must NOT become zero
        missing_pt = [pt for pt in analytics["raw_points"] if pt["record_pk"] == "PSI-69:12"][0]
        self.assertEqual(missing_pt["measurement_status"], "missing")
        self.assertFalse(missing_pt["used_in_summary"])
        self.assertIsNone(missing_pt["value"])
        self.assertEqual(len(missing_pt["source_locator"]["source_sha256"]), 64)

        # PSI-69 preserves exact Test end source labels and chart boundary notes
        self.assertEqual(
            analytics["test_end_distribution"],
            [{"label": "Extinction", "count": 2}, {"label": "Disruption", "count": 1}],
        )
        self.assertIn("Descriptive Record View", analytics["charts"]["raw_record_points"]["title"])

        # CSV & JSON exports share the exact same 3-record subset
        csv_exp = build_export_payload(
            self.records,
            investigation_id="PSI-69",
            field_name="burning_rate_mm2_s",
            unit="mm²/s",
            export_format="csv",
            numeric_filters=nf,
        )
        json_exp = build_export_payload(
            self.records,
            investigation_id="PSI-69",
            field_name="burning_rate_mm2_s",
            unit="mm²/s",
            export_format="json",
            numeric_filters=nf,
        )
        self.assertEqual(csv_exp["total_runs"], 3)
        self.assertEqual(csv_exp["used_in_summary_count"], 2)
        self.assertEqual(csv_exp["excluded_count"], 1)

        csv_rows = list(csv.DictReader(io.StringIO(csv_exp["content"])))
        self.assertEqual([r["record_pk"] for r in csv_rows], ["PSI-69:10", "PSI-69:11", "PSI-69:12"])
        self.assertEqual(csv_rows[2]["measurement_status"], "missing")
        self.assertEqual(csv_rows[2]["used_in_summary"], "false")
        self.assertEqual(csv_rows[2]["value_in_requested_unit"], "")

        def _reject_nonfinite(tok: str) -> None:
            raise ValueError(f"Forbidden non-finite JSON token: {tok}")

        parsed_json = json.loads(json_exp["content"], parse_constant=_reject_nonfinite)
        self.assertEqual([r["record_pk"] for r in parsed_json["records"]], ["PSI-69:10", "PSI-69:11", "PSI-69:12"])
        self.assertIsNone(parsed_json["records"][2]["value_in_requested_unit"])

    def test_approximate_opt_in_and_psi25_boundaries(self) -> None:
        no_approx = build_descriptive_analytics(
            self.records,
            investigation_id="PSI-69",
            field_name="burn_time_s",
            unit="s",
            include_approximate=False,
        ).to_dict()
        with_approx = build_descriptive_analytics(
            self.records,
            investigation_id="PSI-69",
            field_name="burn_time_s",
            unit="s",
            include_approximate=True,
        ).to_dict()
        self.assertEqual(no_approx["total_runs"], 274)
        self.assertEqual(no_approx["summary"]["used_total_count"], 266)
        self.assertEqual(no_approx["summary"]["excluded_by_status"]["approximate"], 2)
        self.assertEqual(with_approx["summary"]["used_total_count"], 268)
        self.assertEqual(with_approx["summary"]["used_approximate_count"], 2)
        self.assertEqual(with_approx["summary"]["median_value"], 9.6)

        # PSI-25 initial_co_ppm preserves missing/above_limit/invalid without turning them into 0,
        # keeps test_end_distribution=None, and keeps real '-1' negative strings uncorrupted in CSV.
        psi25_co = build_descriptive_analytics(
            self.records,
            investigation_id="PSI-25",
            field_name="initial_co_ppm",
            unit="ppm",
        ).to_dict()
        self.assertEqual(psi25_co["total_runs"], 129)
        self.assertEqual(psi25_co["summary"]["used_total_count"], 113)
        self.assertEqual(psi25_co["summary"]["excluded_by_status"]["invalid"], 13)
        self.assertEqual(psi25_co["summary"]["excluded_by_status"]["above_limit"], 1)
        self.assertEqual(psi25_co["summary"]["excluded_by_status"]["missing"], 2)
        self.assertIsNone(psi25_co["test_end_distribution"])
        self.assertIsNone(psi25_co["charts"]["test_end_distribution"])

        exp_psi25 = build_export_payload(
            self.records,
            investigation_id="PSI-25",
            field_name="initial_co_ppm",
            unit="ppm",
            export_format="csv",
        )
        rows = list(csv.DictReader(io.StringIO(exp_psi25["content"])))
        neg_row = [r for r in rows if r["record_pk"] == "PSI-25:B4"][0]
        self.assertEqual(neg_row["raw_value"], "-1")
        self.assertEqual(neg_row["measurement_status"], "invalid")
        self.assertEqual(neg_row["value_in_requested_unit"], "")

    def test_validation_rejects_cross_study_mixing_bad_units_and_uncalibrated_fields(self) -> None:
        # Cross-study field mismatch
        with self.assertRaises(QueryValidationError):
            build_descriptive_analytics(
                self.records,
                investigation_id="PSI-25",
                field_name="burning_rate_mm2_s",
                unit="mm²/s",
            )
        # Wrong unit
        with self.assertRaises(QueryValidationError):
            build_descriptive_analytics(
                self.records,
                investigation_id="PSI-69",
                field_name="ambient_pressure_kpa",
                unit="banana",
            )
        # Uncalibrated PSI-25 fan/radiometer settings cannot be statistically summarized
        for uncal in ("fan_display", "air_display", "radiometer_gain"):
            with self.assertRaises(QueryValidationError):
                build_descriptive_analytics(
                    self.records,
                    investigation_id="PSI-25",
                    field_name=uncal,
                    unit="uncalibrated",
                )
        # Unsupported study
        with self.assertRaises(QueryValidationError):
            build_descriptive_analytics(
                self.records,
                investigation_id="PSI-39",
                field_name="burning_rate_mm2_s",
                unit="mm²/s",
            )


class SyntheticAnalyticsTests(unittest.TestCase):
    """[SYNTHETIC] Tests verifying exact median, empty filters, and CSV injection/negative escaping."""

    @staticmethod
    def _synthetic_record(
        idx: int,
        *,
        raw_val: str,
        val: float | None,
        status: MeasurementStatus,
        fuel: str = "Methanol",
        test_end: str = "Extinction",
    ) -> ExperimentRecord:
        pk = f"PSI-69:SYN-{idx}"
        return ExperimentRecord(
            record_pk=pk,
            investigation_id="PSI-69",
            test_id=f"SYN-{idx}",
            sample_id=None,
            flex_identifier=f"F{idx}",
            source=SourceLocation(
                source_relpath="synthetic/flex.csv",
                source_sha256="0" * 64,
                encoding="utf-8",
                csv_record_index=idx,
                physical_line_start=idx + 1,
                physical_line_end=idx + 1,
            ),
            raw_fields={"FLEX Test #": f"SYN-{idx}", "Burning rate; mm": raw_val},
            normalized_fields={"fuel_raw": fuel, "fuel_norm": fuel, "test_end": test_end},
            measurements={
                "burning_rate_mm2_s": TypedMeasurement(
                    field_name="burning_rate_mm2_s",
                    raw_header="Burning rate; mm",
                    raw_value=raw_val,
                    parsed_value=val,
                    source_unit="mm (CSV başlık hatası; rapor: mm2/s)",
                    normalized_value=val,
                    normalized_unit="mm²/s",
                    status=status,
                )
            },
        )

    def test_synthetic_median_distinguished_from_mean_and_empty_subset(self) -> None:
        # [SYNTHETIC] Asymmetric values [1.0, 2.0, 4.0, 10.0] -> mean=4.25, median=3.0; missing/censored excluded
        syn_records = [
            self._synthetic_record(1, raw_val="1.0", val=1.0, status=MeasurementStatus.MEASURED),
            self._synthetic_record(2, raw_val="2.0", val=2.0, status=MeasurementStatus.MEASURED),
            self._synthetic_record(3, raw_val="4.0", val=4.0, status=MeasurementStatus.MEASURED),
            self._synthetic_record(4, raw_val="10.0", val=10.0, status=MeasurementStatus.MEASURED),
            self._synthetic_record(5, raw_val="", val=None, status=MeasurementStatus.MISSING),
            self._synthetic_record(6, raw_val=">20", val=None, status=MeasurementStatus.ABOVE_LIMIT),
            self._synthetic_record(7, raw_val="~99", val=99.0, status=MeasurementStatus.APPROXIMATE),
        ]
        res = build_descriptive_analytics(
            syn_records,
            investigation_id="PSI-69",
            field_name="burning_rate_mm2_s",
            unit="mm²/s",
            include_approximate=False,
        ).to_dict()
        self.assertEqual(res["total_runs"], 7)
        self.assertEqual(res["summary"]["used_total_count"], 4)
        self.assertAlmostEqual(res["summary"]["mean_value"], 4.25)
        self.assertAlmostEqual(res["summary"]["median_value"], 3.0)
        self.assertEqual(res["summary"]["min_value"], 1.0)
        self.assertEqual(res["summary"]["max_value"], 10.0)

        # Empty filter result returns None stats (never 0) and 0-row export
        empty = build_descriptive_analytics(
            syn_records,
            investigation_id="PSI-69",
            field_name="burning_rate_mm2_s",
            unit="mm²/s",
            fuel="NoSuchFuel",
        ).to_dict()
        self.assertEqual(empty["total_runs"], 0)
        self.assertIsNone(empty["summary"]["mean_value"])
        self.assertIsNone(empty["summary"]["median_value"])
        self.assertEqual(empty["raw_points"], [])

    def test_synthetic_csv_formula_escaping_preserves_turkish_chars_and_negative_numbers(self) -> None:
        # [SYNTHETIC] Verify CSV formula cell neutralization + preservation of real negatives & UTF-8
        self.assertEqual(_escape_csv_cell("=CMD()"), "'=CMD()")
        self.assertEqual(_escape_csv_cell("+1+1"), "'+1+1")
        self.assertEqual(_escape_csv_cell("@SUM(A1:A2)"), "'@SUM(A1:A2)")
        self.assertEqual(_escape_csv_cell("\t=1+1"), "'\t=1+1")
        self.assertEqual(_escape_csv_cell(" =1+1"), "' =1+1")
        self.assertEqual(_escape_csv_cell("-CMD()"), "'-CMD()")
        self.assertEqual(_escape_csv_cell("-1+1"), "'-1+1")
        # Real finite negative numbers and Turkish characters must NOT be corrupted
        self.assertEqual(_escape_csv_cell(-12.5), "-12.5")
        self.assertEqual(_escape_csv_cell("-1"), "-1")
        self.assertEqual(_escape_csv_cell("-0.0045"), "-0.0045")
        self.assertEqual(_escape_csv_cell("Türkçe ölçüm ğüşiöç mm²/s"), "Türkçe ölçüm ğüşiöç mm²/s")

        tr_formula_rec = self._synthetic_record(
            1,
            raw_val="=HYPERLINK(\"http://evil\")",
            val=None,
            status=MeasurementStatus.INVALID,
            fuel="Türkçe yakıt öşğü",
        )
        exp = build_export_payload(
            [tr_formula_rec],
            investigation_id="PSI-69",
            field_name="burning_rate_mm2_s",
            unit="mm²/s",
            export_format="csv",
        )
        rows = list(csv.DictReader(io.StringIO(exp["content"])))
        self.assertEqual(rows[0]["raw_value"], "'=HYPERLINK(\"http://evil\")")
        self.assertEqual(rows[0]["fuel_norm"], "Türkçe yakıt öşğü")
        self.assertEqual(rows[0]["requested_unit"], "mm²/s")

    def test_flex_and_material_lab_real_aggregations_and_exclusions(self) -> None:
        from genaius.analytics import build_flex_analytics, build_material_lab_analytics
        from genaius.data.loader import load_core_datasets

        records, _ = load_core_datasets(Path(__file__).resolve().parents[1])

        flex_all = build_flex_analytics(records)
        self.assertEqual(flex_all["total_runs"], 274)
        self.assertEqual(flex_all["d_ext_diagnostics"]["raw_zero_count"], 8)
        self.assertEqual(flex_all["d_ext_diagnostics"]["positive_used_count"], 189)
        self.assertAlmostEqual(flex_all["d_ext_diagnostics"]["positive_median_mm"], 1.78, places=4)

        flex_high_p = build_flex_analytics(records, p_min_atm=2200.0 / 760.0)
        self.assertEqual(flex_high_p["total_runs"], 3)
        br = flex_high_p["field_summaries"]["burning_rate_mm2_s"]
        self.assertEqual(br["used_measured_count"], 2)
        self.assertEqual(br["excluded_by_status"]["missing"], 1)
        self.assertAlmostEqual(br["mean_value"], 0.385, places=6)

        mat_per_run = build_material_lab_analytics(records, target_o2_pct=21.0, window_pct=3.0)
        self.assertEqual(mat_per_run["total_runs"], 129)
        self.assertEqual(mat_per_run["unique_sample_count"], 107)
        self.assertEqual(mat_per_run["used_count"], 106)
        self.assertEqual(mat_per_run["excluded_count"], 23)
        self.assertEqual(mat_per_run["excluded_by_reason"]["paired_excluded_above_limit"], 4)
        self.assertEqual(mat_per_run["excluded_by_reason"]["paired_excluded_invalid"], 13)
        self.assertEqual(mat_per_run["excluded_by_reason"]["paired_excluded_missing"], 6)
        self.assertEqual(mat_per_run["available_filters"]["materials"], ["Nomex", "PMMA", "SIBAL fabric", "Wax candle"])
        self.assertFalse(mat_per_run["beyond_tested_range"])

        mat_dedupe = build_material_lab_analytics(records, target_o2_pct=34.0, dedupe_samples=True)
        self.assertEqual(mat_dedupe["total_runs"], 129)
        self.assertEqual(mat_dedupe["unique_sample_count"], 107)
        self.assertEqual(len(mat_dedupe["runs"]), 107)
        self.assertEqual(mat_dedupe["used_count"], 94)
        self.assertEqual(mat_dedupe["excluded_count"], 13)
        self.assertTrue(mat_dedupe["beyond_tested_range"])
        self.assertAlmostEqual(mat_dedupe["max_tested_o2_pct"], 22.2, places=3)


if __name__ == "__main__":
    unittest.main()
