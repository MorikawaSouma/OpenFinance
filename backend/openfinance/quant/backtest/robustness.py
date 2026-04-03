from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from openfinance.quant.backtest.report import BacktestRequest
from openfinance.quant.backtest.strategy_runtime_action_regime import StrategyRuntimeActionRegimeDetails
from openfinance.quant.backtest.strategy_runtime_attribution_execution import (
    StrategyRuntimeAttributionExecutionDetails,
)
from openfinance.quant.backtest.strategy_runtime_control_action_deep import (
    StrategyRuntimeControlActionDeepDetails,
)
from openfinance.quant.backtest.strategy_runtime_control_optimizer import (
    StrategyRuntimeControlOptimizerDetails,
)
from openfinance.quant.backtest.strategy_runtime_diagnostics import StrategyRobustnessResultDetails
from openfinance.quant.backtest.strategy_runtime_summary import StrategyRobustnessOutcomeSummary
from openfinance.research.strategy_compilation import StrategyCompilationPlan
from openfinance.research.strategy_spec import StrategySpec
from openfinance.research.strategy_validation import StrategyValidationResult


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
    action_regime_details: StrategyRuntimeActionRegimeDetails | None = None
    attribution_execution_details: StrategyRuntimeAttributionExecutionDetails | None = None
    control_optimizer_details: StrategyRuntimeControlOptimizerDetails | None = None
    control_action_deep_details: StrategyRuntimeControlActionDeepDetails | None = None


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


class RobustnessAnalysisConfig(BaseModel):
    cost_multipliers: list[float] = Field(default_factory=list)
    lookback_values: list[int] | None = None
    threshold_values: list[float] | None = None
    rebalance_values: list[str] | None = None
    min_variants: int = 6
    max_variants: int = 12
    regime_vol_window: int = 20
    stress_shock_return: float = -0.12
    stress_vol_multiplier: float = 2.0
    base_constraints: dict[str, Any] = Field(default_factory=dict)
    base_cost_model: dict[str, float] = Field(default_factory=dict)


class RobustnessReport(BaseModel):
    robustness_id: str
    dataset_version: str
    strategy_id: str
    strategy_version: str
    market: str
    parent_task_id: str | None = None
    child_task_ids: list[str] = Field(default_factory=list)
    summary_report_ref: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    variants: list[RobustnessVariant] = Field(default_factory=list)
    summary: RobustnessSummary
    table: list[dict[str, float | int | str]] = Field(default_factory=list)
    regime_metrics: list[RegimeMetric] = Field(default_factory=list)
    stress_metrics: list[StressMetric] = Field(default_factory=list)
    worst_case_summary: WorstCaseSummary = Field(default_factory=WorstCaseSummary)
    outcome_summary: StrategyRobustnessOutcomeSummary | None = None
    result_details: StrategyRobustnessResultDetails | None = None
    base_strategy_spec: StrategySpec
    base_strategy_validation: StrategyValidationResult
    base_strategy_compilation: StrategyCompilationPlan
    base_backtest_request: BacktestRequest
    analysis_config: RobustnessAnalysisConfig
