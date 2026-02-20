from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class RobustnessVariant(BaseModel):
    variant_id: str
    group: str
    scenario: str
    run_id: str
    strategy_version: str
    commission_bps: float
    slippage_bps: float
    constraints: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, float | int | str] = Field(default_factory=dict)


class RobustnessSummary(BaseModel):
    variant_count: int
    sharpe_mean: float
    sharpe_std: float
    mdd_worst_case: float
    total_return_worst_case: float
    stability_score: float
    best_variant_id: str
    worst_variant_id: str
    cost_double_impact: dict[str, float | str] = Field(default_factory=dict)


class RegimeMetric(BaseModel):
    regime_id: str
    label: str
    start: str
    end: str
    bar_count: int
    run_id: str
    strategy_version: str
    dataset_version: str
    metrics: dict[str, float | int | str] = Field(default_factory=dict)


class StressMetric(BaseModel):
    stress_id: str
    scenario: str
    run_id: str
    strategy_version: str
    dataset_version: str
    params: dict[str, float | int | str] = Field(default_factory=dict)
    metrics: dict[str, float | int | str] = Field(default_factory=dict)


class WorstCaseSummary(BaseModel):
    source_type: str = ""
    scenario_id: str = ""
    run_id: str = ""
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    total_return: float = 0.0
    explanation: str = ""


class RobustnessReport(BaseModel):
    robustness_id: str
    dataset_version: str
    strategy_id: str
    strategy_version: str
    market: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    variants: list[RobustnessVariant] = Field(default_factory=list)
    summary: RobustnessSummary
    table: list[dict[str, float | int | str]] = Field(default_factory=list)
    regime_metrics: list[RegimeMetric] = Field(default_factory=list)
    stress_metrics: list[StressMetric] = Field(default_factory=list)
    worst_case_summary: WorstCaseSummary = Field(default_factory=WorstCaseSummary)
    base_spec: dict[str, Any] = Field(default_factory=dict)
