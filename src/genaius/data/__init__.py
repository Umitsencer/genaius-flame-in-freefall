"""Sözleşme uyumlu veri yükleyici, tipli ölçüm modelleri ve kalite raporu modülleri."""

from .contracts import (
    DATASET_SPECS,
    PSI25_HEADER_ALIASES,
    PSI69_HEADER_ALIASES,
    DatasetSpec,
    ExperimentRecord,
    FieldContract,
    MeasurementStatus,
    SourceLocation,
    TypedMeasurement,
)
from .loader import (
    DataContractError,
    EncodingValidationError,
    SchemaMismatchError,
    load_core_datasets,
    load_investigation_records,
)


def __getattr__(name: str):
    if name in ("build_quality_and_manifest", "generate_core_artifacts"):
        from . import quality

        return getattr(quality, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "DATASET_SPECS",
    "DataContractError",
    "DatasetSpec",
    "EncodingValidationError",
    "ExperimentRecord",
    "FieldContract",
    "MeasurementStatus",
    "PSI25_HEADER_ALIASES",
    "PSI69_HEADER_ALIASES",
    "SchemaMismatchError",
    "SourceLocation",
    "TypedMeasurement",
    "build_quality_and_manifest",
    "generate_core_artifacts",
    "load_core_datasets",
    "load_investigation_records",
]
