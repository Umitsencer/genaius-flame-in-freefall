"""Pydantic request models for every POST endpoint (single source for shape, type and bounds).

Strict mode everywhere: no str→int / int→bool coercion, unknown keys rejected, non-finite
numbers rejected. These models check *shape*; scientific/domain rules (study allowlists,
unit contracts, gas-fraction sums, SAFFIRE identifiers, citation allowlists, …) stay in the
domain modules that own them. Passing validation never means a value is scientifically valid.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator

T = TypeVar("T", bound=BaseModel)


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False, frozen=True)


def Text(max_length: int, *, min_length: int = 0) -> Any:  # noqa: N802 - type factory
    return Annotated[str, StringConstraints(min_length=min_length, max_length=max_length)]


# int stays int and float stays float (JSON output echoes what the client sent); bool is rejected.
Number = int | float
UnitFraction = Annotated[float, Field(ge=0.0, le=1.0)]
PositiveFloat = Annotated[float, Field(gt=0.0)]
DropletDiameterMm = Annotated[float, Field(gt=0.0, le=50.0)]


def _reject_blank(value: str | None) -> str | None:
    if value is not None and not value.strip():
        raise ValueError("must not be empty or whitespace")
    return value


# --------------------------------------------------------------------------- errors
_ERROR_CODES = {
    "missing": "MISSING_FIELD",
    "extra_forbidden": "UNEXPECTED_FIELD",
    "finite_number": "NON_FINITE_NUMBER",
    "literal_error": "NOT_ALLOWED_VALUE",
}


def _code_for(err_type: str) -> str:
    if err_type in _ERROR_CODES:
        return _ERROR_CODES[err_type]
    if err_type.endswith("_type") or err_type == "model_attributes_type":
        return "WRONG_TYPE"
    if err_type.startswith(("too_", "string_too", "greater", "less")):
        return "OUT_OF_RANGE"
    return "INVALID_VALUE"


class RequestValidationError(ValueError):
    """Structured, input-free request validation failure (HTTP layer maps it to 400)."""

    def __init__(self, errors: list[dict[str, str]]):
        self.errors = errors
        first = errors[0] if errors else {"code": "INVALID_VALUE", "field": "$"}
        super().__init__(f"{first['code']} at {first['field']}")


def structured_errors(exc: ValidationError) -> list[dict[str, str]]:
    """Error code + JSON path only; Pydantic's `input` echo is deliberately dropped."""
    out = []
    for err in exc.errors(include_input=False, include_url=False):
        path = "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in err["loc"])
        out.append({"code": _code_for(err["type"]), "field": path})
    return out


def parse_request(model: type[T], payload: Any, *, error_cls: type[ValueError] | None = None) -> T:
    """Validate `payload` against `model`; raise a ValueError subclass with structured codes."""
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        errors = structured_errors(exc)
        if error_cls is None:
            raise RequestValidationError(errors) from None
        domain_exc = error_cls(f"{errors[0]['code']} at {errors[0]['field']}")
        domain_exc.errors = errors  # type: ignore[attr-defined]
        raise domain_exc from None


# --------------------------------------------------------------------------- shared parts
class NumericFilterIn(StrictModel):
    field_name: str
    unit: str
    min_value: Number | None = None
    max_value: Number | None = None


NumericFilters = Annotated[list[NumericFilterIn], Field(max_length=10)]


# --------------------------------------------------------------------------- core tables
class SearchRequest(StrictModel):
    investigation_id: str | None = None
    fuel: str | None = None
    numeric_filters: NumericFilters = []
    limit: Annotated[int, Field(ge=1, le=100)] = 25
    offset: Annotated[int, Field(ge=0)] = 0


class DetailRequest(StrictModel):
    record_pk: str


class CompareRequest(StrictModel):
    record_pks: Annotated[list[str], Field(min_length=2, max_length=4)]


class DocumentsRequest(StrictModel):
    query: Text(2000, min_length=1)
    investigation_id: str | None = None
    top_k: Annotated[int, Field(ge=1, le=10)] = 5

    _non_blank = field_validator("query")(_reject_blank)


Scope = Literal["auto", "core", "saffire_case", "flex_prediction"]


class EvidenceRequestIn(StrictModel):
    """Shared payload of /api/evidence and /api/answer (scope routing happens afterwards)."""

    query: Text(2000) | None = None
    investigation_id: Text(64) | None = None
    fuel: Text(128) | None = None
    test_end: Text(64) | None = None
    numeric_filters: NumericFilters = []
    include_approximate: bool = False
    summarize_field_name: Text(128) | None = None
    summarize_unit: Text(32) | None = None
    compare_record_pks: Annotated[list[str], Field(max_length=10)] = []
    compare_field_names: list[str] | None = None
    top_k: Annotated[int, Field(ge=1, le=10)] = 5
    max_table_citations: Annotated[int, Field(ge=0, le=50)] = 25
    run_table_query: bool = True
    use_bilingual_aliases: bool = False
    scope: Scope | None = None
    flex_condition: dict[str, Any] | None = None


# Fields that belong to the Core (PSI-25/PSI-69) table query and are cleared when a request is
# routed to the separate SAFFIRE IV–VI case corpus (never pooled).
CORE_ONLY_FIELDS: tuple[str, ...] = (
    "investigation_id", "fuel", "test_end", "numeric_filters", "summarize_field_name",
    "summarize_unit", "compare_record_pks", "compare_field_names", "flex_condition",
)


class CatalogSearchRequest(StrictModel):
    query: Text(500) | None = None
    project_type: Text(128) | None = None
    sub_research_area: Text(128) | None = None
    queryable_in_core: bool | None = None
    top_k: Annotated[int, Field(ge=1, le=50)] | None = None

    _non_blank = field_validator("query", "project_type", "sub_research_area")(_reject_blank)


# --------------------------------------------------------------------------- analytics
class AnalyticsRequest(StrictModel):
    investigation_id: Text(64, min_length=1)
    field_name: Text(128, min_length=1)
    unit: Text(64, min_length=1)
    fuel: Text(128) | None = None
    test_end: Text(64) | None = None
    numeric_filters: NumericFilters = []
    include_approximate: bool = False


class ExportRequest(AnalyticsRequest):
    format: Literal["csv", "json"]


class FlexAnalyticsRequest(StrictModel):
    fuel: Text(64) | None = None
    diluent: Text(32) | None = None
    o2_min_pct: Number | None = None
    o2_max_pct: Number | None = None
    p_min_atm: Number | None = None
    p_max_atm: Number | None = None
    target_o2_pct: Number | None = None
    target_p_atm: Number | None = None


class MaterialLabRequest(StrictModel):
    target_o2_pct: Number = 21.0
    window_pct: Number = 3.0
    metric: Text(64) | None = None
    group_by: Text(64) | None = None
    flow_restrictor: Annotated[int, Field(ge=0, le=2)] | None = None  # strict int: bool rejected
    pi: Text(64) | None = None
    materials: Annotated[list[str], Field(max_length=20)] | None = None
    dedupe_samples: bool = False


class CfiAnalysisRequest(StrictModel):
    pressure_atm: Number = 1.0
    fiber: Literal["Yes", "No"] = "Yes"
    fuel: Text(128) | None = None
    sensitivity_mode: Text(64, min_length=1) = "all_candidates"

    _non_blank = field_validator("fuel")(_reject_blank)


# --------------------------------------------------------------------------- SAFFIRE
class SaffireReferenceRequest(StrictModel):
    sample_id: str | None = None


class SaffireCaseRequest(StrictModel):
    test_id: str | None = None
    flight: str | None = None
    fuel_group: str | None = None


class SaffireCaseExportRequest(SaffireCaseRequest):
    format: str = "json"


# --------------------------------------------------------------------------- FLEX predictor
class _PressureFields(StrictModel):
    pressure_mmhg: PositiveFloat | None = None
    pressure_atm: PositiveFloat | None = None
    pressure_kpa: PositiveFloat | None = None


class FlexConditionIn(_PressureFields):
    """Pre-test FLEX inputs only; post-test variables (t_b, d_ext, K, test_end) are unknown keys."""

    fuel: Text(64, min_length=1)
    o2_mol_frac: UnitFraction
    co2_mol_frac: UnitFraction
    he_mol_frac: UnitFraction
    n2_mol_frac: UnitFraction | None = None
    droplet_initial_diameter_mm: DropletDiameterMm
    domain_context: Text(200) | None = None

    _non_blank = field_validator("fuel")(_reject_blank)


class FlexExportRequest(FlexConditionIn):
    format: str = "md"


class FlexConditionMapIn(_PressureFields):
    fuel: Text(64, min_length=1)
    diluent_regime: Literal["Air", "CO2", "He"] = "Air"
    droplet_initial_diameter_mm: DropletDiameterMm
    o2_steps: Annotated[int, Field(ge=5, le=17)] = 15
    y_steps: Annotated[int, Field(ge=5, le=13)] = 11

    _non_blank = field_validator("fuel")(_reject_blank)
