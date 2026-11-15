"""Kanonik veri sözleşmesi sabitleri, alias haritaları ve tipli veri modelleri."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MeasurementStatus(str, Enum):
    """VERI_SOZLESMESI.md içinde tanımlanan yedi ölçüm durumu."""

    MEASURED = "measured"
    MISSING = "missing"
    BELOW_LIMIT = "below_limit"
    ABOVE_LIMIT = "above_limit"
    APPROXIMATE = "approximate"
    INVALID = "invalid"
    MEANING_UNVERIFIED = "meaning_unverified"


POSITION_DEFINITION = (
    "csv_record_index: başlık satırı hariç 1-tabanlı CSV mantıksal kayıt sırası; "
    "physical_line_start/physical_line_end: başlık satırı=1 dahil olmak üzere ham dosyadaki "
    "1-tabanlı fiziksel satır aralığı."
)

TP_BURNING_RATE_PROVENANCE = (
    "NASA/TP-2015-216046 Ek A.1 (basılı s.19, PDF s.25) ve Ek A.2 Tablo IX "
    "'Burning rate, mm2/s' (basılı s.20, PDF s.26)."
)

TP_CO2_PROVENANCE = (
    "NASA/TP-2015-216046 Ek A.1 (basılı s.19, PDF s.25), Ek A.2 Tablo IX CO2 sütunu "
    "(basılı s.20, PDF s.26) ve §4.1 Tablo II FLEX-010..018 (basılı s.10, PDF s.16)."
)

TP_EXTINCTION_DIAMETER_PROVENANCE = (
    "NASA/TP-2015-216046 Ek A.1 (basılı s.19, PDF s.25) ve Tablo IX (basılı s.20, PDF s.26): "
    "görünür alevin söndüğü andaki damlacık çapıdır; tek başına soğuk alev veya güvenlik "
    "sınıfı kanıtı değildir."
)

BASS_OR_PROVENANCE = (
    "PSI-25_Science Documents_BASS-II_ReadMe.docx §CO readings: OR = over range (> 1000 ppm)."
)

PRESSURE_CONVERSION_PROVENANCE = (
    "Standart fizik katsayıları: 1 atm = 760 mmHg = 101.325 kPa (kPa = mmHg * 101.325 / 760; "
    "atm = mmHg / 760)."
)


@dataclass(frozen=True)
class SourceLocation:
    """Her kaydın ham dosya ve satır düzeyinde geri izlenebilir konumu."""

    source_relpath: str
    source_sha256: str
    encoding: str
    csv_record_index: int
    physical_line_start: int
    physical_line_end: int
    position_definition: str = POSITION_DEFINITION


@dataclass(frozen=True)
class TypedMeasurement:
    """Ham değer, ayrıştırılmış sayı, kaynak/normalize sınırlar, birim, durum ve kalite izini taşır."""

    field_name: str
    raw_header: str
    raw_value: str
    parsed_value: float | None
    source_unit: str | None
    normalized_value: float | None
    normalized_unit: str | None
    status: MeasurementStatus
    source_lower_bound: float | None = None
    source_upper_bound: float | None = None
    normalized_lower_bound: float | None = None
    normalized_upper_bound: float | None = None
    lower_bound_inclusive: bool | None = None
    upper_bound_inclusive: bool | None = None
    quality_flags: tuple[str, ...] = ()
    provenance: str | None = None
    error_reason: str | None = None
    extra_conversions: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class ExperimentRecord:
    """Tek bir PSI test koşusu kaydı (1 satır = 1 test koşusu; tekrarlar korunur)."""

    record_pk: str
    investigation_id: str
    test_id: str
    sample_id: str | None
    flex_identifier: str | None
    source: SourceLocation
    raw_fields: dict[str, str]
    normalized_fields: dict[str, Any]
    measurements: dict[str, TypedMeasurement]
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class FieldContract:
    """Tek bir sayısal veya kalibrasyonsuz sütunun sözleşme kuralı."""

    raw_header: str
    field_name: str
    source_unit: str
    normalized_unit: str
    scale_factor: float | None = 1.0
    uncalibrated: bool = False
    or_lower_bound: float | None = None
    allow_negative: bool = False
    negative_reason_flag: str | None = None
    provenance: str | None = None
    extra_unit: str | None = None
    extra_scale_factor: float | None = None


@dataclass(frozen=True)
class DatasetSpec:
    """PSI-25 ve PSI-69 dosya yolu, kodlama, kimlik ve beklenen özet sayımları."""

    investigation_id: str
    experiment_name: str
    relative_path: str
    encoding: str
    doi: str
    catalog_license: str
    reports_license_note: str
    primary_test_header: str
    sample_header: str | None
    flex_identifier_header: str | None
    header_aliases: dict[str, str]
    field_contracts: tuple[FieldContract, ...]
    expected_run_count: int
    expected_unique_sample_count: int | None = None


PSI25_HEADER_ALIASES: dict[str, str] = {
    "PI": "pi",
    "Test #": "test_id",
    "Date": "test_date",
    "GMT": "test_gmt",
    "Sample #": "sample_id",
    "Fuel Sample Material": "fuel_raw",
    "Flow restrictor": "flow_restrictor",
    "Fan display": "fan_display",
    "Air display": "air_display",
    "Radiometer gain   (1000   250   50   10)": "radiometer_gain",
    "Total Frames Shot": "total_frames_shot",
    "Calibrated  initial O2 % by vol ": "initial_o2_vol_pct",
    "Calibrated final O2 % by vol": "final_o2_vol_pct",
    "Initial CO2 % by vol": "initial_co2_vol_pct",
    "Final CO2 % by vol": "final_co2_vol_pct",
    "Initial CO (ppm)": "initial_co_ppm",
    "Final CO (ppm)": "final_co_ppm",
}


PSI69_HEADER_ALIASES: dict[str, str] = {
    "FLEX Test #": "test_id",
    "FLEX Identifier": "flex_identifier",
    "Test Date": "test_date",
    "Test GMT": "test_gmt",
    "Fuel": "fuel_raw",
    "Ambient pressure; mmHg": "ambient_pressure_kpa",
    "O initial ambient composition; mole fraction": "initial_o2_flex_mol_pct",
    "N initial ambient composition; mole fraction": "initial_n2_flex_mol_pct",
    "CO initial ambient composition; mole fraction": "initial_co2_flex_mol_pct",
    "He initial ambient composition; mole fraction": "initial_he_flex_mol_pct",
    "Droplet initial diameter; mm": "droplet_initial_diameter_mm",
    "Visible flame extinction diameter; mm": "visible_flame_extinction_diameter_mm",
    "Burning rate; mm": "burning_rate_mm2_s",
    "Burn time; s": "burn_time_s",
    "Test end": "test_end",
}


PSI25_CONTRACTS: tuple[FieldContract, ...] = (
    FieldContract(
        raw_header="Flow restrictor",
        field_name="flow_restrictor",
        source_unit="code (0-2)",
        normalized_unit="code (0-2)",
        scale_factor=1.0,
        provenance="BASS-II_ReadMe.docx: 0=en düşük kısıtlama/en yüksek akış, 2=en yüksek kısıtlama.",
    ),
    FieldContract(
        raw_header="Fan display",
        field_name="fan_display",
        source_unit="uncalibrated setting / voltage x 10",
        normalized_unit="uncalibrated",
        scale_factor=None,
        uncalibrated=True,
        provenance="BASS-II_ReadMe.docx: ek kalibrasyon tablosu olmadan akış hızına çevrilmez.",
    ),
    FieldContract(
        raw_header="Air display",
        field_name="air_display",
        source_unit="uncalibrated video duct speed reading (cm/s, ~1 min lag)",
        normalized_unit="uncalibrated",
        scale_factor=None,
        uncalibrated=True,
        provenance="BASS-II_ReadMe.docx: ~1 dk tepki gecikmesi nedeniyle kalibreli anlık hız sayılmaz.",
    ),
    FieldContract(
        raw_header="Radiometer gain   (1000   250   50   10)",
        field_name="radiometer_gain",
        source_unit="uncalibrated gain setting",
        normalized_unit="uncalibrated",
        scale_factor=None,
        uncalibrated=True,
        provenance="BASS-II_ReadMe.docx: kalibrasyon eğrisi olmadan ışınım akısı birimine çevrilmez.",
    ),
    FieldContract(
        raw_header="Calibrated  initial O2 % by vol ",
        field_name="initial_o2_vol_pct",
        source_unit="% vol",
        normalized_unit="% vol",
        scale_factor=1.0,
        provenance="BASS-II_ReadMe.docx & NASA/TM-20210011385: MCA kalibreli başlangıç O2.",
    ),
    FieldContract(
        raw_header="Calibrated final O2 % by vol",
        field_name="final_o2_vol_pct",
        source_unit="% vol",
        normalized_unit="% vol",
        scale_factor=1.0,
        provenance="BASS-II_ReadMe.docx & NASA/TM-20210011385: test sonu kabin O2; initial ile ayrı tutulur.",
    ),
    FieldContract(
        raw_header="Initial CO2 % by vol",
        field_name="initial_co2_vol_pct",
        source_unit="% vol",
        normalized_unit="% vol",
        scale_factor=1.0,
        provenance="BASS-II_ReadMe.docx: CDM başlangıç CO2.",
    ),
    FieldContract(
        raw_header="Final CO2 % by vol",
        field_name="final_co2_vol_pct",
        source_unit="% vol",
        normalized_unit="% vol",
        scale_factor=1.0,
        provenance="BASS-II_ReadMe.docx: CDM test sonu CO2.",
    ),
    FieldContract(
        raw_header="Initial CO (ppm)",
        field_name="initial_co_ppm",
        source_unit="ppm",
        normalized_unit="ppm",
        scale_factor=1.0,
        or_lower_bound=1000.0,
        allow_negative=False,
        negative_reason_flag="nedeni doğrulanmadı",
        provenance=f"{BASS_OR_PROVENANCE} Negatif okumaların fiziksel nedeni raporda doğrulanmadı.",
    ),
    FieldContract(
        raw_header="Final CO (ppm)",
        field_name="final_co_ppm",
        source_unit="ppm",
        normalized_unit="ppm",
        scale_factor=1.0,
        or_lower_bound=1000.0,
        allow_negative=False,
        negative_reason_flag="nedeni doğrulanmadı",
        provenance=BASS_OR_PROVENANCE,
    ),
)


PSI69_CONTRACTS: tuple[FieldContract, ...] = (
    FieldContract(
        raw_header="Ambient pressure; mmHg",
        field_name="ambient_pressure_kpa",
        source_unit="mmHg",
        normalized_unit="kPa",
        scale_factor=101.325 / 760.0,
        provenance=PRESSURE_CONVERSION_PROVENANCE,
        extra_unit="atm",
        extra_scale_factor=1.0 / 760.0,
    ),
    FieldContract(
        raw_header="O initial ambient composition; mole fraction",
        field_name="initial_o2_flex_mol_pct",
        source_unit="mole fraction",
        normalized_unit="% mol",
        scale_factor=100.0,
        provenance="NASA/TP-2015-216046 Ek A.1 (basılı s.19, PDF s.25): O2 mol kesri.",
    ),
    FieldContract(
        raw_header="N initial ambient composition; mole fraction",
        field_name="initial_n2_flex_mol_pct",
        source_unit="mole fraction",
        normalized_unit="% mol",
        scale_factor=100.0,
        provenance="NASA/TP-2015-216046 Ek A.1 (basılı s.19, PDF s.25): N2 mol kesri.",
    ),
    FieldContract(
        raw_header="CO initial ambient composition; mole fraction",
        field_name="initial_co2_flex_mol_pct",
        source_unit="mole fraction",
        normalized_unit="% mol",
        scale_factor=100.0,
        provenance=TP_CO2_PROVENANCE,
    ),
    FieldContract(
        raw_header="He initial ambient composition; mole fraction",
        field_name="initial_he_flex_mol_pct",
        source_unit="mole fraction",
        normalized_unit="% mol",
        scale_factor=100.0,
        provenance="NASA/TP-2015-216046 Ek A.2 Tablo IX (basılı s.20, PDF s.26): He mol kesri.",
    ),
    FieldContract(
        raw_header="Droplet initial diameter; mm",
        field_name="droplet_initial_diameter_mm",
        source_unit="mm",
        normalized_unit="mm",
        scale_factor=1.0,
        provenance="NASA/TP-2015-216046 Ek A.1 (basılı s.19, PDF s.25): Actual D0.",
    ),
    FieldContract(
        raw_header="Visible flame extinction diameter; mm",
        field_name="visible_flame_extinction_diameter_mm",
        source_unit="mm",
        normalized_unit="mm",
        scale_factor=1.0,
        provenance=TP_EXTINCTION_DIAMETER_PROVENANCE,
    ),
    FieldContract(
        raw_header="Burning rate; mm",
        field_name="burning_rate_mm2_s",
        source_unit="mm (CSV başlık hatası; rapor: mm2/s)",
        normalized_unit="mm²/s",
        scale_factor=1.0,
        provenance=TP_BURNING_RATE_PROVENANCE,
    ),
    FieldContract(
        raw_header="Burn time; s",
        field_name="burn_time_s",
        source_unit="s",
        normalized_unit="s",
        scale_factor=1.0,
        provenance="NASA/TP-2015-216046 Tablo IX (basılı s.20, PDF s.26): Burn time, s.",
    ),
)


DATASET_SPECS: dict[str, DatasetSpec] = {
    "PSI-25": DatasetSpec(
        investigation_id="PSI-25",
        experiment_name="Burning and Suppression of Solids - II (BASS-II)",
        relative_path="data/raw/psi/experimental_tables/PSI-25/PSI-25_Experimental table_BASS-II.csv",
        encoding="utf-8-sig",
        doi="10.60555/4qc4-de67",
        catalog_license="CC0-1.0 (PSI deney tablosu katalog kaydı)",
        reports_license_note="Ek NASA/dergi raporları kendi lisans/telif koşullarına tabidir.",
        primary_test_header="Test #",
        sample_header="Sample #",
        flex_identifier_header=None,
        header_aliases=PSI25_HEADER_ALIASES,
        field_contracts=PSI25_CONTRACTS,
        expected_run_count=129,
        expected_unique_sample_count=107,
    ),
    "PSI-69": DatasetSpec(
        investigation_id="PSI-69",
        experiment_name="Flame Extinguishment Experiment (FLEX)",
        relative_path="data/raw/psi/experimental_tables/PSI-69/PSI-69_Experimental table_FLEX.csv",
        encoding="windows-1252",
        doi="10.60555/mbq8-0451",
        catalog_license="CC0-1.0 (PSI deney tablosu katalog kaydı)",
        reports_license_note="Ek NASA/dergi raporları kendi lisans/telif koşullarına tabidir.",
        primary_test_header="FLEX Test #",
        sample_header=None,
        flex_identifier_header="FLEX Identifier",
        header_aliases=PSI69_HEADER_ALIASES,
        field_contracts=PSI69_CONTRACTS,
        expected_run_count=274,
        expected_unique_sample_count=None,
    ),
}
