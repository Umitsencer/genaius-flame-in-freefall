"""Strict request schemas for deterministic scenario evidence endpoints."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from .requests import Number, StrictModel, Text


Language = Literal["en", "tr"]


class ScenarioCheckRequest(StrictModel):
    fuel: Text(80, min_length=1)
    o2_percent: Annotated[Number, Field(ge=0.0, le=100.0)]
    pressure_atm: Annotated[Number, Field(gt=0.0, le=5.0)] | None = None
    gravity_g: Annotated[Number, Field(ge=0.0, le=2.0)] | None = None
    purpose: Text(200) | None = None
    lang: Language = "en"

    @field_validator("fuel")
    @classmethod
    def _non_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be empty or whitespace")
        return value

    @field_validator("purpose")
    @classmethod
    def _optional_purpose(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class ScenarioGridRequest(StrictModel):
    fuel: Text(80, min_length=1)
    gravity_g: Annotated[Number, Field(ge=0.0, le=2.0)] | None = None
    lang: Language = "en"

    @field_validator("fuel")
    @classmethod
    def _fuel_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty or whitespace")
        return value


class ScenarioReportRequest(StrictModel):
    habitat: Literal["moon", "mars", "iss"] = "moon"
    fuels: Annotated[list[Text(80, min_length=1)], Field(min_length=1, max_length=8)] | None = None
    lang: Language = "en"
