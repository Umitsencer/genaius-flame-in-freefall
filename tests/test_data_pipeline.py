"""Paket A veri yükleyici, sözleşme ve kalite raporu testleri.

Gerçek ham veri kontrolleri ile sentetik parsing/hata testleri ayrı sınıflarda tutulur.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from genaius.data import (  # noqa: E402
    DATASET_SPECS,
    EncodingValidationError,
    FieldContract,
    MeasurementStatus,
    SchemaMismatchError,
    build_quality_and_manifest,
    generate_core_artifacts,
    load_core_datasets,
    load_investigation_records,
)
from genaius.data.contracts import DatasetSpec  # noqa: E402
from genaius.data.loader import parse_measurement_value  # noqa: E402


class RealCoreDataTests(unittest.TestCase):
    """Gerçek PSI-25 ve PSI-69 ham CSV dosyaları üzerindeki doğrulamalar."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.records, cls.metas = load_core_datasets(REPO_ROOT)
        cls.by_pk = {r.record_pk: r for r in cls.records}
        cls.manifest, cls.quality = build_quality_and_manifest(REPO_ROOT)

    def test_expected_run_and_identity_counts(self) -> None:
        psi25 = [r for r in self.records if r.investigation_id == "PSI-25"]
        psi69 = [r for r in self.records if r.investigation_id == "PSI-69"]
        self.assertEqual(len(psi25), 129)
        self.assertEqual(len({r.sample_id for r in psi25}), 107)
        self.assertEqual(len(psi69), 274)
        self.assertEqual(len(self.records), 403)

    def test_composite_key_uniqueness_and_repeat_preservation(self) -> None:
        self.assertEqual(len(self.by_pk), 403)
        # Tekrarlanan Sample # (örn. 220m: 3 koşu) silinmeden korunmalı
        s220 = [r for r in self.records if r.investigation_id == "PSI-25" and r.sample_id == "220m"]
        self.assertEqual(len(s220), 3)
        self.assertTrue(all(r.normalized_fields["is_repeat_sample"] for r in s220))
        # Yinelenen FLEX Identifier 193F001 ayrışmalı
        f193 = [r for r in self.records if r.investigation_id == "PSI-69" and r.flex_identifier == "193F001"]
        self.assertEqual([r.test_id for r in f193], ["70", "73"])

    def test_real_special_tokens_status_and_bounds(self) -> None:
        # >500 (M5), OR (O4), over (O13b), empty Final CO (B2), none Final CO (T28a), negative Initial CO (B4, O5a, O20)
        m5 = self.by_pk["PSI-25:M5"].measurements["final_co_ppm"]
        self.assertEqual(m5.status, MeasurementStatus.ABOVE_LIMIT)
        self.assertEqual(m5.source_lower_bound, 500.0)
        self.assertEqual(m5.normalized_lower_bound, 500.0)
        self.assertFalse(m5.lower_bound_inclusive)
        self.assertIsNone(m5.parsed_value)

        o4 = self.by_pk["PSI-25:O4"].measurements["final_co_ppm"]
        self.assertEqual(o4.status, MeasurementStatus.ABOVE_LIMIT)
        self.assertEqual(o4.source_lower_bound, 1000.0)
        self.assertEqual(o4.normalized_lower_bound, 1000.0)
        self.assertFalse(o4.lower_bound_inclusive)
        self.assertIsNone(o4.parsed_value)

        o13b = self.by_pk["PSI-25:O13b"].measurements["final_co_ppm"]
        self.assertEqual(o13b.status, MeasurementStatus.ABOVE_LIMIT)
        self.assertIsNone(o13b.source_lower_bound)
        self.assertIsNone(o13b.normalized_lower_bound)
        self.assertIsNone(o13b.parsed_value)

        b2_fco = self.by_pk["PSI-25:B2"].measurements["final_co_ppm"]
        self.assertEqual(b2_fco.status, MeasurementStatus.MISSING)
        self.assertIsNone(b2_fco.parsed_value)

        t28a_fco = self.by_pk["PSI-25:T28a"].measurements["final_co_ppm"]
        self.assertEqual(t28a_fco.status, MeasurementStatus.MISSING)
        self.assertIsNone(t28a_fco.parsed_value)

        b4_ico = self.by_pk["PSI-25:B4"].measurements["initial_co_ppm"]
        self.assertEqual(b4_ico.status, MeasurementStatus.INVALID)
        self.assertEqual(b4_ico.raw_value, "-1")
        self.assertIsNone(b4_ico.parsed_value)
        self.assertIn("negative_reading", b4_ico.quality_flags)
        self.assertIn("nedeni doğrulanmadı", b4_ico.quality_flags)

        # PSI-69 dash missing (Test # 7 -> d_ext) and approximate burn time (~6, Test # 223)
        t7_dext = self.by_pk["PSI-69:7"].measurements["visible_flame_extinction_diameter_mm"]
        self.assertEqual(t7_dext.status, MeasurementStatus.MISSING)
        self.assertIsNone(t7_dext.parsed_value)

        t223_bt = self.by_pk["PSI-69:223"].measurements["burn_time_s"]
        self.assertEqual(t223_bt.status, MeasurementStatus.APPROXIMATE)
        self.assertEqual(t223_bt.parsed_value, 6.0)
        self.assertEqual(t223_bt.raw_value, "~6")

    def test_initial_final_and_o2_unit_separation(self) -> None:
        b2 = self.by_pk["PSI-25:B2"]
        self.assertEqual(b2.measurements["initial_o2_vol_pct"].parsed_value, 22.2)
        self.assertEqual(b2.measurements["final_o2_vol_pct"].parsed_value, 1.6)
        self.assertIn("outlier_B2_low_final_o2", b2.quality_flags)
        self.assertEqual(b2.measurements["initial_o2_vol_pct"].normalized_unit, "% vol")

        t10 = self.by_pk["PSI-69:10"]
        self.assertEqual(t10.measurements["initial_o2_flex_mol_pct"].source_unit, "mole fraction")
        self.assertEqual(t10.measurements["initial_o2_flex_mol_pct"].normalized_unit, "% mol")
        self.assertEqual(t10.measurements["initial_co2_flex_mol_pct"].normalized_value, 70.0)
        self.assertIn("TP-2015-216046", t10.measurements["initial_co2_flex_mol_pct"].provenance or "")

    def test_flex_test_12_missing_burning_rate_not_zero(self) -> None:
        t12 = self.by_pk["PSI-69:12"]
        k = t12.measurements["burning_rate_mm2_s"]
        self.assertEqual(k.status, MeasurementStatus.MISSING)
        self.assertEqual(k.raw_value, "")
        self.assertEqual(k.raw_header, "Burning rate; mm")
        self.assertIsNone(k.parsed_value)
        self.assertIsNone(k.normalized_value)

    def test_source_trace_back_and_manifest_truthfulness(self) -> None:
        t12 = self.by_pk["PSI-69:12"]
        self.assertEqual(t12.source.csv_record_index, 12)
        self.assertEqual(t12.source.physical_line_start, 13)
        self.assertEqual(t12.source.source_sha256, self.metas["PSI-69"]["sha256"])

        for src in self.manifest["sources"]:
            self.assertIsNone(src["download_date"])
            self.assertEqual(len(src["sha256"]), 64)

        self.assertEqual(self.quality["investigations"]["PSI-25"]["expected_vs_computed"]["run_count"]["computed"], 129)
        self.assertEqual(self.quality["investigations"]["PSI-25"]["expected_vs_computed"]["unique_sample_count"]["computed"], 107)
        self.assertEqual(self.quality["investigations"]["PSI-69"]["expected_vs_computed"]["run_count"]["computed"], 274)
        self.assertEqual(self.quality["investigations"]["PSI-25"]["unrecognized_tokens"], [])
        self.assertEqual(self.quality["investigations"]["PSI-69"]["unrecognized_tokens"], [])
        self.assertEqual(
            self.quality["investigations"]["PSI-25"]["record_quality_flag_counts"]["outlier_B2_low_final_o2"],
            1,
        )
        self.assertEqual(
            self.quality["investigations"]["PSI-25"]["measurement_quality_flag_counts"]["negative_reading"],
            13,
        )
        self.assertEqual(
            self.quality["investigations"]["PSI-69"]["record_quality_flag_counts"][
                "d_ext_present_with_non_extinction_end"
            ],
            38,
        )


class SyntheticContractAndErrorTests(unittest.TestCase):
    """Sentetik parsing, dönüşüm, hata ve çok satırlı CSV konumu testleri (gerçek veri değildir)."""

    def test_synthetic_pressure_760_mmhg_conversion(self) -> None:
        contract = next(c for c in DATASET_SPECS["PSI-69"].field_contracts if c.field_name == "ambient_pressure_kpa")
        m = parse_measurement_value("760", contract)
        self.assertEqual(m.status, MeasurementStatus.MEASURED)
        self.assertEqual(m.normalized_value, 101.325)
        self.assertEqual(m.normalized_unit, "kPa")
        self.assertEqual(m.extra_conversions["atm"]["value"], 1.0)
        self.assertEqual(m.extra_conversions["atm"]["unit"], "atm")

    def test_synthetic_unrecognized_and_below_limit_tokens(self) -> None:
        fc = FieldContract(raw_header="CO (ppm)", field_name="co_ppm", source_unit="ppm", normalized_unit="ppm")
        m_lt = parse_measurement_value("<5", fc)
        self.assertEqual(m_lt.status, MeasurementStatus.BELOW_LIMIT)
        self.assertEqual(m_lt.source_upper_bound, 5.0)
        self.assertEqual(m_lt.normalized_upper_bound, 5.0)
        self.assertFalse(m_lt.upper_bound_inclusive)
        self.assertIsNone(m_lt.parsed_value)

        m_unk = parse_measurement_value("N/A?", fc)
        self.assertEqual(m_unk.status, MeasurementStatus.INVALID)
        self.assertIn("unrecognized_token", m_unk.quality_flags)
        self.assertEqual(m_unk.raw_value, "N/A?")
        self.assertIsNotNone(m_unk.error_reason)

    def test_synthetic_part_a_numeric_overflow_approx_neg_and_bound_units(self) -> None:
        p_contract = next(c for c in DATASET_SPECS["PSI-69"].field_contracts if c.field_name == "ambient_pressure_kpa")
        # 1. "1e999" -> INVALID (non_finite_or_overflow), ham metin korunur, inf uretilmez
        m_inf = parse_measurement_value("1e999", p_contract)
        self.assertEqual(m_inf.status, MeasurementStatus.INVALID)
        self.assertEqual(m_inf.raw_value, "1e999")
        self.assertIsNone(m_inf.parsed_value)
        self.assertIsNone(m_inf.normalized_value)
        self.assertIn("non_finite_or_overflow", m_inf.quality_flags)

        # Donusum tasmasi (ornegin 1e307 * 100 -> inf)
        o2_contract = next(c for c in DATASET_SPECS["PSI-69"].field_contracts if c.field_name == "initial_o2_flex_mol_pct")
        m_conv_inf = parse_measurement_value("1e307", o2_contract)
        self.assertEqual(m_conv_inf.status, MeasurementStatus.INVALID)
        self.assertIsNone(m_conv_inf.parsed_value)
        self.assertIsNone(m_conv_inf.normalized_value)
        self.assertIn("non_finite_or_overflow", m_conv_inf.quality_flags)

        # 2. "~-1" -> INVALID + negative_reading, approximate olmaz
        m_neg_approx = parse_measurement_value("~-1", p_contract)
        self.assertEqual(m_neg_approx.status, MeasurementStatus.INVALID)
        self.assertEqual(m_neg_approx.raw_value, "~-1")
        self.assertIsNone(m_neg_approx.parsed_value)
        self.assertIsNone(m_neg_approx.normalized_value)
        self.assertIn("negative_reading", m_neg_approx.quality_flags)

        # ">-5" ve "<1e999" da ortak dogrulamadan gecmeli
        m_neg_gt = parse_measurement_value(">-5", p_contract)
        self.assertEqual(m_neg_gt.status, MeasurementStatus.INVALID)
        self.assertIsNone(m_neg_gt.source_lower_bound)

        # 3. ">760" -> source_lower_bound=760 (mmHg), normalized_lower_bound=101.325 (kPa), dislayici >
        m_gt_p = parse_measurement_value(">760", p_contract)
        self.assertEqual(m_gt_p.status, MeasurementStatus.ABOVE_LIMIT)
        self.assertEqual(m_gt_p.source_unit, "mmHg")
        self.assertEqual(m_gt_p.normalized_unit, "kPa")
        self.assertEqual(m_gt_p.source_lower_bound, 760.0)
        self.assertEqual(m_gt_p.normalized_lower_bound, 101.325)
        self.assertFalse(m_gt_p.lower_bound_inclusive)
        self.assertEqual(m_gt_p.extra_conversions["atm"]["value"], 1.0)

    def test_synthetic_multiline_csv_record_vs_physical_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_file = root / "synthetic.csv"
            csv_file.write_text(
                'FLEX Test #,FLEX Identifier,Test Date,Test GMT,Fuel,Ambient pressure; mmHg,'
                'O initial ambient composition; mole fraction,N initial ambient composition; mole fraction,'
                'CO initial ambient composition; mole fraction,He initial ambient composition; mole fraction,'
                'Droplet initial diameter; mm,Visible flame extinction diameter; mm,Burning rate; mm,'
                'Burn time; s,Test end\n'
                '1,ID1,1/1/2026,00:00:00,"Methanol\nmulti-line",760,0.21,0.79,0,0,2.0,1.0,0.5,4.0,Extinction\n'
                '2,ID2,1/1/2026,00:01:00,Heptane,760,0.21,0.79,0,0,2.0,-,0.6,5.0,Completion\n',
                encoding="windows-1252",
            )
            base = DATASET_SPECS["PSI-69"]
            spec = DatasetSpec(
                investigation_id=base.investigation_id,
                experiment_name=base.experiment_name,
                relative_path="synthetic.csv",
                encoding="windows-1252",
                doi=base.doi,
                catalog_license=base.catalog_license,
                reports_license_note=base.reports_license_note,
                primary_test_header=base.primary_test_header,
                sample_header=base.sample_header,
                flex_identifier_header=base.flex_identifier_header,
                header_aliases=base.header_aliases,
                field_contracts=base.field_contracts,
                expected_run_count=2,
            )
            recs, _ = load_investigation_records("PSI-69", repo_root=root, spec_override=spec)
            self.assertEqual(recs[0].source.csv_record_index, 1)
            self.assertEqual((recs[0].source.physical_line_start, recs[0].source.physical_line_end), (2, 3))
            self.assertEqual(recs[1].source.csv_record_index, 2)
            self.assertEqual((recs[1].source.physical_line_start, recs[1].source.physical_line_end), (4, 4))

    def test_synthetic_missing_header_and_bad_encoding_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad_header = root / "bad_header.csv"
            bad_header.write_text("FLEX Test #,Fuel\n1,Methanol\n", encoding="windows-1252")
            base = DATASET_SPECS["PSI-69"]
            spec_hdr = DatasetSpec(
                investigation_id=base.investigation_id,
                experiment_name=base.experiment_name,
                relative_path="bad_header.csv",
                encoding="windows-1252",
                doi=base.doi,
                catalog_license=base.catalog_license,
                reports_license_note=base.reports_license_note,
                primary_test_header=base.primary_test_header,
                sample_header=base.sample_header,
                flex_identifier_header=base.flex_identifier_header,
                header_aliases=base.header_aliases,
                field_contracts=base.field_contracts,
                expected_run_count=1,
            )
            with self.assertRaises(SchemaMismatchError) as ctx:
                load_investigation_records("PSI-69", repo_root=root, spec_override=spec_hdr)
            self.assertIn("zorunlu başlıkları eksik", str(ctx.exception))

            bad_enc = root / "bad_enc.csv"
            bad_enc.write_bytes(b"PI,Test #\xff\n")
            base25 = DATASET_SPECS["PSI-25"]
            spec_enc = DatasetSpec(
                investigation_id=base25.investigation_id,
                experiment_name=base25.experiment_name,
                relative_path="bad_enc.csv",
                encoding="utf-8-sig",
                doi=base25.doi,
                catalog_license=base25.catalog_license,
                reports_license_note=base25.reports_license_note,
                primary_test_header=base25.primary_test_header,
                sample_header=base25.sample_header,
                flex_identifier_header=base25.flex_identifier_header,
                header_aliases=base25.header_aliases,
                field_contracts=base25.field_contracts,
                expected_run_count=1,
            )
            with self.assertRaises(EncodingValidationError) as ctx_enc:
                load_investigation_records("PSI-25", repo_root=root, spec_override=spec_enc)
            self.assertIn("utf-8-sig", str(ctx_enc.exception))

    def test_generate_artifacts_reproducible_in_temp_dir(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            m_path, q_path = generate_core_artifacts(REPO_ROOT, output_dir=tmp)
            self.assertTrue(m_path.exists())
            self.assertTrue(q_path.exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
