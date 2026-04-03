from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_serializer

from openfinance.quant.backtest.evaluation_plan import (
    BacktestEvaluationPlan,
    FactorVersionRef,
    backtest_evaluation_plan_payload,
)
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
from openfinance.quant.backtest.strategy_runtime_diagnostics import StrategyRuntimeDiagnosticsResult
from openfinance.quant.backtest.strategy_trace import StrategyTraceArtifact
from openfinance.quant.backtest.strategy_runtime_summary import StrategyRuntimeOutcomeSummary
from openfinance.research.strategy_compilation import StrategyCompilationPlan
from openfinance.research.strategy_decision import StrategyDecision
from openfinance.research.strategy_validation import StrategyValidationResult


class CostModel(BaseModel):
    commission_bps: float = 0.0
    slippage_bps: float = 0.0


class BacktestRequest(BaseModel):
    dataset_version: str
    strategy_id: str
    strategy_version: str
    market: str
    start: str
    end: str
    execution_model: str = "next_open"
    cost_model: CostModel = Field(default_factory=CostModel)
    factor_versions: list[FactorVersionRef] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    evaluation_plan: BacktestEvaluationPlan | dict[str, Any] = Field(default_factory=BacktestEvaluationPlan)

    @field_serializer("evaluation_plan")
    def _serialize_evaluation_plan(
        self,
        value: BacktestEvaluationPlan | dict[str, Any],
    ) -> dict[str, Any]:
        return backtest_evaluation_plan_payload(value)


class BacktestOrder(BaseModel):
    order_id: UUID = Field(default_factory=uuid4)
    time: datetime
    instrument: str
    side: str
    qty: float
    order_type: str = "market"
    limit_price: float | None = None
    status: str = "submitted"
    reason_code: str = ""
    reason_msg: str = ""
    user_friendly_msg: str = ""
    reason: str = ""


class BacktestTrade(BaseModel):
    trade_id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    time: datetime
    instrument: str
    side: str
    price: float
    qty: float
    commission: float
    slippage: float


class PositionSnapshot(BaseModel):
    time: datetime
    instrument: str
    qty: float
    avg_price: float
    market_price: float
    market_value: float
    cash: float
    equity: float
    unrealized_pnl: float


class BacktestReport(BaseModel):
    run_id: UUID = Field(default_factory=uuid4)
    dataset_version: str
    market: str = "US"
    strategy_version: str
    strategy_decision: StrategyDecision | None = None
    strategy_validation: StrategyValidationResult | None = None
    strategy_compilation: StrategyCompilationPlan | None = None
    strategy_trace: StrategyTraceArtifact | None = None
    runtime_summary: StrategyRuntimeOutcomeSummary | None = None
    runtime_diagnostics: StrategyRuntimeDiagnosticsResult | None = None
    action_regime_details: StrategyRuntimeActionRegimeDetails | None = None
    attribution_execution_details: StrategyRuntimeAttributionExecutionDetails | None = None
    control_optimizer_details: StrategyRuntimeControlOptimizerDetails | None = None
    control_action_deep_details: StrategyRuntimeControlActionDeepDetails | None = None
    factor_versions: list[FactorVersionRef] = Field(default_factory=list)
    factor_versions_reason: str | None = None
    audit_trace_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metrics: dict[str, float | int | str] = Field(default_factory=dict)
    charts: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    equity_curve: list[dict[str, float | int | str]] = Field(default_factory=list)
    orders: list[BacktestOrder] = Field(default_factory=list)
    trades: list[BacktestTrade] = Field(default_factory=list)
    positions: list[PositionSnapshot] = Field(default_factory=list)
    positions_ts: list[PositionSnapshot] = Field(default_factory=list)
    cost_breakdown: dict[str, float] = Field(default_factory=dict)
    attribution: dict[str, dict[str, float]] = Field(default_factory=dict)
