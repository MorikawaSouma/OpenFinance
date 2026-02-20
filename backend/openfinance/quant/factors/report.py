from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class FactorSeriesPoint(BaseModel):
    instrument: str
    ts: datetime
    value: float


class DecayPoint(BaseModel):
    lag: int
    ic: float


class OOSDecayPoint(BaseModel):
    lag: int
    in_sample_ic: float
    out_sample_ic: float
    gap: float


class SensitivityPoint(BaseModel):
    variant_id: str
    params: dict[str, float | int | str] = Field(default_factory=dict)
    ic_mean: float
    rank_ic_mean: float
    ic_delta: float
    rank_ic_delta: float
    observation_count: int = 0


class FactorHealthReport(BaseModel):
    stability_score: float
    oos_gap: float
    in_sample_ic_mean: float
    out_sample_ic_mean: float
    in_sample_rank_ic_mean: float
    out_sample_rank_ic_mean: float
    in_sample_decay_curve: list[DecayPoint] = Field(default_factory=list)
    out_sample_decay_curve: list[DecayPoint] = Field(default_factory=list)
    oos_decay_gap_curve: list[OOSDecayPoint] = Field(default_factory=list)
    sensitivity: list[SensitivityPoint] = Field(default_factory=list)
    sensitivity_grid_size: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    notes: list[str] = Field(default_factory=list)


class FactorReport(BaseModel):
    factor_id: str
    factor_version: str
    dataset_version: str
    market: str
    observation_count: int
    ic_mean: float
    ic_std: float
    rank_ic_mean: float
    rank_ic_std: float
    t_stat: float
    coverage: float = 1.0
    missing_rate: float = 0.0
    turnover_proxy: float = 0.0
    oos_split_ratio: float = 0.7
    in_sample_observation_count: int = 0
    out_sample_observation_count: int = 0
    in_sample_ic_mean: float = 0.0
    out_sample_ic_mean: float = 0.0
    in_sample_rank_ic_mean: float = 0.0
    out_sample_rank_ic_mean: float = 0.0
    decay_curve: list[DecayPoint] = Field(default_factory=list)
    in_sample_decay_curve: list[DecayPoint] = Field(default_factory=list)
    out_sample_decay_curve: list[DecayPoint] = Field(default_factory=list)
    dsl_execution_plan: dict[str, Any] | None = None
    health_report: FactorHealthReport | None = None
    health_report_artifact_path: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    notes: list[str] = Field(default_factory=list)


class FactorEngineResult(BaseModel):
    factor_id: str
    factor_version: str
    dataset_version: str
    market: str
    artifact_path: str
    cached: bool = False
    factor_series: list[FactorSeriesPoint] = Field(default_factory=list)
    report: FactorReport
