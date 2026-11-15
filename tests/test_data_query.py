"""Paket B sorgulama, filtreleme, özetleme ve karşılaştırma katmanı testleri."""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from genaius.data.contracts import (
    DATASET_SPECS,
    ExperimentRecord,
    MeasurementStatus,
    POSITION_DEFINITION,
    SourceLocation,
    TypedMeasurement,
)
from genaius.data.loader import load_core_datasets, parse_measurement_value
from genaius.data.query import (
    COMPARISON_BOUNDARY_NOTE,
    NumericRangeFilter,
    QueryValidationError,
    compare_records,
    filter_records,
    get_allowed_fields,
    get_allowed_units,
    summarize_field,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_synthetic_record(
    *,
    investigation_id: str,
    test_id: str,
    csv_index: int,
    fuel_raw: str,
    raw_values: dict[str, str],
    sample_id: str | None = None,
    flex_identifier: str | None = None,
    test_end: str | None = None,
) -> ExperimentRecord:
    spec = DATASET_SPECS[investigation_id]
    contracts = {fc.field_name: fc for fc in spec.field_contracts}
    measurements: dict[str, TypedMeasurement] = {}
    for fname, contract in contracts.items():
        cell = raw_values.get(fname, "")
        measurements[fname] = parse_measurement_value(cell, contract)
    norm_fields: dict[str, object] = {
        "fuel_raw": fuel_raw,
        "fuel_norm": " ".join(fuel_raw.split()),
    }
    if test_end is not None:
        norm_fields["test_end"] = test_end.strip()
    return ExperimentRecord(
        record_pk=f"{investigation_id}:{test_id}",
        investigation_id=investigation_id,
        test_id=test_id,
        sample_id=sample_id,
        flex_identifier=flex_identifier,
        source=SourceLocation(
            source_relpath=f"synthetic/{investigation_id}.csv",
            source_sha256="0" * 64,
            encoding=spec.encoding,
            csv_record_index=csv_index,
            physical_line_start=csv_index + 1,
            physical_line_end=csv_index + 1,
            position_definition=POSITION_DEFINITION,
        ),
        raw_fields={},
        normalized_fields=norm_fields,
        measurements=measurements,
        quality_flags=(),
    )


class RealCoreQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records, cls.metas = load_core_datasets(REPO_ROOT)

    def test_psi69_pressure_2200_mmhg_and_kpa_equivalence(self) -> None:
        res_mmhg = filter_records(
            self.records,
            investigation_id="PSI-69",
            numeric_filters=(
                NumericRangeFilter(
                    field_name="ambient_pressure_kpa",
                    unit="mmHg",
                    min_value=2200.0,
                    min_inclusive=True,
                ),
            ),
        )
        res_kpa = filter_records(
            self.records,
            investigation_id="PSI-69",
            numeric_filters=(
                NumericRangeFilter(
                    field_name="ambient_pressure_kpa",
                    unit="kPa",
                    min_value=2200.0 * 101.325 / 760.0,
                    min_inclusive=True,
                ),
            ),
        )

        self.assertEqual([r.record_pk for r in res_mmhg.records], ["PSI-69:10", "PSI-69:11", "PSI-69:12"])
        self.assertEqual([r.test_id for r in res_mmhg.records], ["10", "11", "12"])
        self.assertEqual([r.record_pk for r in res_kpa.records], [r.record_pk for r in res_mmhg.records])
        self.assertEqual(res_mmhg.total_runs, 3)

    def test_psi69_heptane_positive_co2_in_both_units(self) -> None:
        expected_pks = sorted(
            (
                r.record_pk
                for r in self.records
                if r.investigation_id == "PSI-69"
                and str(r.normalized_fields["fuel_norm"]).casefold() == "heptane"
                and r.measurements["initial_co2_flex_mol_pct"].status == MeasurementStatus.MEASURED
                and (r.measurements["initial_co2_flex_mol_pct"].parsed_value or 0.0) > 0.0
            ),
        )
        self.assertEqual(len(expected_pks), 48)

        res_frac = filter_records(
            self.records,
            investigation_id="PSI-69",
            fuel="Heptane",
            numeric_filters=(
                NumericRangeFilter(
                    field_name="initial_co2_flex_mol_pct",
                    unit="mole fraction",
                    min_value=0.0,
                    min_inclusive=False,
                ),
            ),
        )
        res_pct = filter_records(
            self.records,
            investigation_id="PSI-69",
            fuel="  heptane ",
            numeric_filters=(
                NumericRangeFilter(
                    field_name="initial_co2_flex_mol_pct",
                    unit="% mol",
                    min_value=0.0,
                    min_inclusive=False,
                ),
            ),
        )
        self.assertEqual(res_frac.total_runs, 48)
        self.assertEqual(sorted(r.record_pk for r in res_frac.records), expected_pks)
        self.assertEqual([r.record_pk for r in res_frac.records], [r.record_pk for r in res_pct.records])

    def test_psi25_nomex_exact_label_match_vs_no_default_substring(self) -> None:
        nomex_labels = sorted(
            {
                str(r.normalized_fields["fuel_norm"])
                for r in self.records
                if r.investigation_id == "PSI-25"
                and "nomex" in str(r.normalized_fields["fuel_norm"]).casefold()
            }
        )
        self.assertEqual(nomex_labels, ["Nomex natural (nomex III)"])

        exact_res = filter_records(
            self.records,
            investigation_id="PSI-25",
            fuel="Nomex natural (nomex III)",
        )
        normalized_case_res = filter_records(
            self.records,
            investigation_id="PSI-25",
            fuel="  nomex   natural (NOMEX iii) ",
        )
        substring_res = filter_records(
            self.records,
            investigation_id="PSI-25",
            fuel="Nomex",
        )

        self.assertEqual([r.test_id for r in exact_res.records], ["F1", "F2", "F3"])
        self.assertEqual([r.record_pk for r in normalized_case_res.records], ["PSI-25:F1", "PSI-25:F2", "PSI-25:F3"])
        self.assertEqual(substring_res.total_runs, 0)

    def test_psi25_preserves_repeat_runs_vs_unique_samples(self) -> None:
        res = filter_records(self.records, investigation_id="PSI-25")
        self.assertEqual(res.total_runs, 129)
        self.assertEqual(res.unique_sample_count, 107)

    def test_psi69_burning_rate_summary_excludes_missing(self) -> None:
        measured_vals = [
            r.measurements["burning_rate_mm2_s"].normalized_value
            for r in self.records
            if r.investigation_id == "PSI-69"
            and r.measurements["burning_rate_mm2_s"].status == MeasurementStatus.MEASURED
            and r.measurements["burning_rate_mm2_s"].normalized_value is not None
        ]
        summary = summarize_field(
            self.records,
            investigation_id="PSI-69",
            field_name="burning_rate_mm2_s",
            unit="mm²/s",
        )
        self.assertEqual(summary.candidate_run_count, 274)
        self.assertEqual(summary.used_measured_count, 258)
        self.assertEqual(summary.used_approximate_count, 0)
        self.assertEqual(summary.used_total_count, 258)
        self.assertEqual(summary.excluded_by_status["missing"], 16)
        self.assertAlmostEqual(summary.mean_value, math.fsum(measured_vals) / len(measured_vals), places=12)
        self.assertAlmostEqual(summary.min_value, min(measured_vals), places=12)
        self.assertAlmostEqual(summary.max_value, max(measured_vals), places=12)

    def test_psi69_test_12_missing_burning_rate_not_zero(self) -> None:
        test_12 = [r for r in self.records if r.record_pk == "PSI-69:12"]
        self.assertEqual(len(test_12), 1)

        summary = summarize_field(
            test_12,
            investigation_id="PSI-69",
            field_name="burning_rate_mm2_s",
            unit="mm²/s",
        )
        self.assertEqual(summary.candidate_run_count, 1)
        self.assertEqual(summary.used_measured_count, 0)
        self.assertEqual(summary.used_total_count, 0)
        self.assertEqual(summary.excluded_by_status["missing"], 1)
        self.assertIsNone(summary.mean_value)
        self.assertIsNone(summary.min_value)
        self.assertIsNone(summary.max_value)

        zero_match = filter_records(
            test_12,
            investigation_id="PSI-69",
            numeric_filters=(
                NumericRangeFilter("burning_rate_mm2_s", "mm²/s", min_value=0.0, max_value=0.0),
            ),
        )
        self.assertEqual(zero_match.total_runs, 0)

    def test_psi25_b2_initial_vs_final_o2_separate(self) -> None:
        comp = compare_records(
            self.records,
            record_pks=("PSI-25:B2",),
            field_names=("initial_o2_vol_pct", "final_o2_vol_pct"),
        )
        row = comp.rows[0]
        self.assertEqual(row["record_pk"], "PSI-25:B2")
        self.assertAlmostEqual(row["measurements"]["initial_o2_vol_pct"]["normalized_value"], 22.2, places=6)
        self.assertAlmostEqual(row["measurements"]["final_o2_vol_pct"]["normalized_value"], 1.6, places=6)
        self.assertEqual(row["measurements"]["initial_o2_vol_pct"]["normalized_unit"], "% vol")
        self.assertEqual(row["measurements"]["final_o2_vol_pct"]["normalized_unit"], "% vol")

    def test_psi69_tests_10_to_12_side_by_side_comparison_and_provenance(self) -> None:
        comp = compare_records(
            self.records,
            record_pks=("PSI-69:12", "PSI-69:10", "PSI-69:11"),
            field_names=(
                "ambient_pressure_kpa",
                "droplet_initial_diameter_mm",
                "burning_rate_mm2_s",
                "burn_time_s",
            ),
        )
        self.assertEqual(comp.boundary_note, COMPARISON_BOUNDARY_NOTE)
        self.assertEqual([r["record_pk"] for r in comp.rows], ["PSI-69:10", "PSI-69:11", "PSI-69:12"])

        source_by_pk = {r.record_pk: r for r in self.records}
        by_pk = {r["record_pk"]: r for r in comp.rows}
        for pk in ("PSI-69:10", "PSI-69:11", "PSI-69:12"):
            row = by_pk[pk]
            src_rec = source_by_pk[pk]
            self.assertEqual(row["fuel_norm"], src_rec.normalized_fields["fuel_norm"])
            self.assertEqual(row["test_end"], src_rec.normalized_fields["test_end"])
            self.assertEqual(row["measurements"]["droplet_initial_diameter_mm"]["status"], "measured")
            self.assertEqual(
                row["measurements"]["droplet_initial_diameter_mm"]["normalized_value"],
                src_rec.measurements["droplet_initial_diameter_mm"].normalized_value,
            )
            self.assertTrue(row["test_end"])
            self.assertTrue(row["source"]["source_sha256"])
            self.assertEqual(
                row["source"]["source_relpath"],
                "data/raw/psi/experimental_tables/PSI-69/PSI-69_Experimental table_FLEX.csv",
            )
            self.assertGreater(row["source"]["csv_record_index"], 0)
            self.assertGreaterEqual(row["source"]["physical_line_end"], row["source"]["physical_line_start"])

        self.assertEqual(by_pk["PSI-69:10"]["measurements"]["burning_rate_mm2_s"]["status"], "measured")
        self.assertEqual(by_pk["PSI-69:11"]["measurements"]["burning_rate_mm2_s"]["status"], "measured")
        self.assertEqual(by_pk["PSI-69:12"]["measurements"]["burning_rate_mm2_s"]["status"], "missing")
        self.assertIsNone(by_pk["PSI-69:12"]["measurements"]["burning_rate_mm2_s"]["normalized_value"])

        # JSON serileştirme NaN/Inf olmadan çalışmalı
        encoded = json.dumps(comp.to_dict(), ensure_ascii=False, allow_nan=False)
        self.assertIn("PSI-69:12", encoded)


class SyntheticQueryContractTests(unittest.TestCase):
    def test_empty_results_and_none_summary(self) -> None:
        empty_filter = filter_records((), investigation_id="PSI-25", fuel="PMMA")
        self.assertEqual(empty_filter.total_runs, 0)
        self.assertEqual(empty_filter.unique_sample_count, 0)
        self.assertEqual(empty_filter.records, ())

        empty_summary = summarize_field(
            (),
            investigation_id="PSI-69",
            field_name="burning_rate_mm2_s",
            unit="mm²/s",
        )
        self.assertEqual(empty_summary.candidate_run_count, 0)
        self.assertEqual(empty_summary.used_total_count, 0)
        self.assertIsNone(empty_summary.mean_value)
        self.assertIsNone(empty_summary.min_value)
        self.assertIsNone(empty_summary.max_value)

    def test_validation_errors_on_bad_fields_units_bounds_and_missing_pks(self) -> None:
        rec25 = _make_synthetic_record(
            investigation_id="PSI-25",
            test_id="S1",
            csv_index=1,
            fuel_raw="PMMA",
            sample_id="S-1",
            raw_values={"initial_o2_vol_pct": "21.0"},
        )
        rec69 = _make_synthetic_record(
            investigation_id="PSI-69",
            test_id="1",
            csv_index=1,
            fuel_raw="Heptane",
            raw_values={"ambient_pressure_kpa": "760"},
        )

        # Bilinmeyen alan
        with self.assertRaises(QueryValidationError):
            filter_records(
                [rec69],
                numeric_filters=(NumericRangeFilter("nonexistent_field", "kPa", min_value=1.0),),
            )

        # Yanlış birim: PSI-69 alanında % vol kabul edilmemeli
        with self.assertRaises(QueryValidationError):
            summarize_field(
                [rec69],
                investigation_id="PSI-69",
                field_name="initial_o2_flex_mol_pct",
                unit="% vol",
            )

        # Yanlış çalışma + alan eşleşmesi
        with self.assertRaises(QueryValidationError):
            summarize_field(
                [rec25],
                investigation_id="PSI-25",
                field_name="burning_rate_mm2_s",
                unit="mm²/s",
            )

        # CSV başlık hatasındaki tek başına "mm" birimi burning rate için reddedilmeli
        with self.assertRaises(QueryValidationError):
            summarize_field(
                [rec69],
                investigation_id="PSI-69",
                field_name="burning_rate_mm2_s",
                unit="mm",
            )

        # PSI-25 ile test_end reddedilmeli
        with self.assertRaises(QueryValidationError):
            filter_records([rec25], investigation_id="PSI-25", test_end="Extinction")

        # Kalibresiz alan sayısal özet ve filtrede reddedilmeli
        with self.assertRaises(QueryValidationError):
            summarize_field(
                [rec25],
                investigation_id="PSI-25",
                field_name="fan_display",
                unit="uncalibrated",
            )

        # NaN / Inf / min > max / boş filtre aralığı reddedilmeli
        with self.assertRaises(QueryValidationError):
            filter_records(
                [rec69],
                numeric_filters=(NumericRangeFilter("ambient_pressure_kpa", "kPa", min_value=float("nan")),),
            )
        with self.assertRaises(QueryValidationError):
            filter_records(
                [rec69],
                numeric_filters=(NumericRangeFilter("ambient_pressure_kpa", "kPa", min_value=200.0, max_value=100.0),),
            )
        with self.assertRaises(QueryValidationError):
            filter_records(
                [rec69],
                numeric_filters=(NumericRangeFilter("ambient_pressure_kpa", "kPa"),),
            )

        # Tek sorguda farklı çalışma filtreleri reddedilmeli
        with self.assertRaises(QueryValidationError):
            filter_records(
                [rec25, rec69],
                numeric_filters=(
                    NumericRangeFilter("initial_o2_vol_pct", "% vol", min_value=20.0),
                    NumericRangeFilter("ambient_pressure_kpa", "kPa", min_value=50.0),
                ),
            )

        # investigation_id verilmeden test_end (PSI-69) + PSI-25 sayısal filtresi reddedilmeli
        with self.assertRaises(QueryValidationError):
            filter_records(
                [rec25, rec69],
                test_end="Extinction",
                numeric_filters=(NumericRangeFilter("initial_o2_vol_pct", "% vol", min_value=20.0),),
            )

        # Açık investigation_id ile de test_end + PSI-25 sayısal filtresi reddedilmeli
        with self.assertRaises(QueryValidationError):
            filter_records(
                [rec25, rec69],
                investigation_id="PSI-69",
                test_end="Extinction",
                numeric_filters=(NumericRangeFilter("initial_o2_vol_pct", "% vol", min_value=20.0),),
            )
        with self.assertRaises(QueryValidationError):
            filter_records(
                [rec25, rec69],
                investigation_id="PSI-25",
                test_end="Extinction",
                numeric_filters=(NumericRangeFilter("initial_o2_vol_pct", "% vol", min_value=20.0),),
            )

        # Eksik record_pk açık hata vermeli
        with self.assertRaises(QueryValidationError):
            compare_records(
                [rec25],
                record_pks=("PSI-25:S1", "PSI-69:999"),
                field_names=("initial_o2_vol_pct",),
            )

    def test_boundary_equality_inclusive_vs_exclusive(self) -> None:
        r_eq = _make_synthetic_record(
            investigation_id="PSI-69",
            test_id="1",
            csv_index=1,
            fuel_raw="Heptane",
            raw_values={"ambient_pressure_kpa": "760"},
        )
        inc = filter_records(
            [r_eq],
            investigation_id="PSI-69",
            numeric_filters=(NumericRangeFilter("ambient_pressure_kpa", "kPa", min_value=101.325, min_inclusive=True),),
        )
        exc = filter_records(
            [r_eq],
            investigation_id="PSI-69",
            numeric_filters=(NumericRangeFilter("ambient_pressure_kpa", "kPa", min_value=101.325, min_inclusive=False),),
        )
        upper_inc = filter_records(
            [r_eq],
            investigation_id="PSI-69",
            numeric_filters=(NumericRangeFilter("ambient_pressure_kpa", "mmHg", max_value=760.0, max_inclusive=True),),
        )
        upper_exc = filter_records(
            [r_eq],
            investigation_id="PSI-69",
            numeric_filters=(NumericRangeFilter("ambient_pressure_kpa", "mmHg", max_value=760.0, max_inclusive=False),),
        )
        self.assertEqual(inc.total_runs, 1)
        self.assertEqual(exc.total_runs, 0)
        self.assertEqual(upper_inc.total_runs, 1)
        self.assertEqual(upper_exc.total_runs, 0)

    def test_approximate_opt_in_and_non_measured_exclusions(self) -> None:
        r_meas = _make_synthetic_record(
            investigation_id="PSI-25",
            test_id="1",
            csv_index=1,
            fuel_raw="PMMA",
            sample_id="A",
            raw_values={"initial_co_ppm": "100"},
        )
        r_approx = _make_synthetic_record(
            investigation_id="PSI-25",
            test_id="2",
            csv_index=2,
            fuel_raw="PMMA",
            sample_id="B",
            raw_values={"initial_co_ppm": "~200"},
        )
        r_above = _make_synthetic_record(
            investigation_id="PSI-25",
            test_id="3",
            csv_index=3,
            fuel_raw="PMMA",
            sample_id="C",
            raw_values={"initial_co_ppm": "OR"},
        )
        r_below = _make_synthetic_record(
            investigation_id="PSI-25",
            test_id="4",
            csv_index=4,
            fuel_raw="PMMA",
            sample_id="D",
            raw_values={"initial_co_ppm": "<5"},
        )
        r_neg = _make_synthetic_record(
            investigation_id="PSI-25",
            test_id="5",
            csv_index=5,
            fuel_raw="PMMA",
            sample_id="E",
            raw_values={"initial_co_ppm": "-3"},
        )
        r_miss = _make_synthetic_record(
            investigation_id="PSI-25",
            test_id="6",
            csv_index=6,
            fuel_raw="PMMA",
            sample_id="F",
            raw_values={"initial_co_ppm": ""},
        )
        dataset = [r_meas, r_approx, r_above, r_below, r_neg, r_miss]

        default_filter = filter_records(
            dataset,
            investigation_id="PSI-25",
            numeric_filters=(NumericRangeFilter("initial_co_ppm", "ppm", min_value=0.0),),
        )
        optin_filter = filter_records(
            dataset,
            investigation_id="PSI-25",
            numeric_filters=(NumericRangeFilter("initial_co_ppm", "ppm", min_value=0.0),),
            include_approximate=True,
        )
        self.assertEqual([r.record_pk for r in default_filter.records], ["PSI-25:1"])
        self.assertEqual(default_filter.warnings, ())
        self.assertEqual([r.record_pk for r in optin_filter.records], ["PSI-25:1", "PSI-25:2"])
        self.assertTrue(any("approximate_included" in w for w in optin_filter.warnings))

        default_sum = summarize_field(
            dataset,
            investigation_id="PSI-25",
            field_name="initial_co_ppm",
            unit="ppm",
        )
        self.assertEqual(default_sum.candidate_run_count, 6)
        self.assertEqual(default_sum.used_measured_count, 1)
        self.assertEqual(default_sum.used_approximate_count, 0)
        self.assertEqual(default_sum.excluded_by_status["approximate"], 1)
        self.assertEqual(default_sum.excluded_by_status["above_limit"], 1)
        self.assertEqual(default_sum.excluded_by_status["below_limit"], 1)
        self.assertEqual(default_sum.excluded_by_status["invalid"], 1)
        self.assertEqual(default_sum.excluded_by_status["missing"], 1)
        self.assertAlmostEqual(default_sum.mean_value, 100.0, places=6)

        optin_sum = summarize_field(
            dataset,
            investigation_id="PSI-25",
            field_name="initial_co_ppm",
            unit="ppm",
            include_approximate=True,
        )
        self.assertEqual(optin_sum.used_measured_count, 1)
        self.assertEqual(optin_sum.used_approximate_count, 1)
        self.assertEqual(optin_sum.used_total_count, 2)
        self.assertAlmostEqual(optin_sum.mean_value, 150.0, places=6)
        self.assertTrue(any("approximate_included" in w for w in optin_sum.warnings))

    def test_cross_study_comparison_never_merges_units_and_exposes_allowlist(self) -> None:
        r25 = _make_synthetic_record(
            investigation_id="PSI-25",
            test_id="B2",
            csv_index=1,
            fuel_raw="PMMA",
            sample_id="S-1",
            raw_values={"initial_o2_vol_pct": "22.2"},
        )
        r69 = _make_synthetic_record(
            investigation_id="PSI-69",
            test_id="10",
            csv_index=1,
            fuel_raw="Heptane",
            raw_values={"initial_o2_flex_mol_pct": "0.21"},
            test_end="Flame extinction",
        )
        comp = compare_records(
            [r25, r69],
            record_pks=("PSI-25:B2", "PSI-69:10"),
            field_names=("initial_o2_vol_pct", "initial_o2_flex_mol_pct"),
        )
        self.assertTrue(any("cross_study_units_preserved" in w for w in comp.warnings))
        by_pk = {r["record_pk"]: r for r in comp.rows}
        self.assertEqual(by_pk["PSI-25:B2"]["measurements"]["initial_o2_vol_pct"]["normalized_unit"], "% vol")
        self.assertEqual(by_pk["PSI-25:B2"]["measurements"]["initial_o2_flex_mol_pct"]["status"], "not_applicable")
        self.assertEqual(by_pk["PSI-69:10"]["measurements"]["initial_o2_flex_mol_pct"]["normalized_unit"], "% mol")
        self.assertEqual(by_pk["PSI-69:10"]["measurements"]["initial_o2_vol_pct"]["status"], "not_applicable")

        self.assertIn("ambient_pressure_kpa", get_allowed_fields("PSI-69"))
        self.assertNotIn("ambient_pressure_kpa", get_allowed_fields("PSI-25"))
        self.assertEqual(get_allowed_units("ambient_pressure_kpa"), ("kPa", "mmHg", "atm"))
        self.assertEqual(json.loads(json.dumps(comp.to_dict(), allow_nan=False))["rows"][0]["record_pk"], "PSI-25:B2")


if __name__ == "__main__":
    unittest.main()
