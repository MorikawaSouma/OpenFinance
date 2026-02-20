from enum import Enum
from pydantic import BaseModel, Field, field_validator
from pydantic.functional_validators import BeforeValidator
from typing_extensions import Annotated

from openfinance.quant.checks.failure_conditions import (
    FailureConditionConfig,
    normalize_failure_conditions,
)


class FactorInput(BaseModel):
    name: str
    source: str
    as_of_field: str = "as_of"
    publish_time_field: str | None = "publish_time"
    availability_lag: str = Field(
        default="0s",
        description="Lag from publish_time to feature availability, e.g. 1d/6h/30m.",
    )


class FactorTransform(BaseModel):
    name: str
    params: dict[str, float | int | str | bool | list[str]] = Field(default_factory=dict)


class ValidationPlan(BaseModel):
    in_sample_start: str
    in_sample_end: str
    out_sample_start: str
    out_sample_end: str
    checks: list[str] = Field(default_factory=lambda: ["lookahead", "stability"])


class CostSensitivityLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class ExpectedHorizon(str, Enum):
    intraday = "intraday"
    swing = "swing"
    long_only = "long_only"


class CostSensitivity(BaseModel):
    level: CostSensitivityLevel = CostSensitivityLevel.medium
    rationale: str = "Default medium sensitivity for draft factor."

    @field_validator("rationale")
    @classmethod
    def _validate_rationale(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("cost_sensitivity.rationale must not be empty")
        return text


class FactorSpec(BaseModel):
    factor_id: str
    factor_version: str
    description: str
    inputs: list[FactorInput]
    params: dict[str, float | int | str | bool | list[str]] = Field(default_factory=dict)
    transforms: list[FactorTransform] = Field(default_factory=list)
    validation_plan: ValidationPlan
    failure_conditions: Annotated[
        list[FailureConditionConfig],
        BeforeValidator(lambda value: normalize_failure_conditions(value, default_applies_to="factor")),
    ] = Field(default_factory=list)
    cost_sensitivity: CostSensitivity = Field(default_factory=CostSensitivity)
    expected_horizon: ExpectedHorizon | None = None

    @field_validator("failure_conditions")
    @classmethod
    def _dedupe_failure_conditions(
        cls,
        value: list[FailureConditionConfig],
    ) -> list[FailureConditionConfig]:
        cleaned: list[FailureConditionConfig] = []
        seen: set[tuple[str, str]] = set()
        for item in value:
            if not isinstance(item, FailureConditionConfig):
                continue
            key = (item.code, item.applies_to)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(item)
        return cleaned
