import json
import logging
import statistics
import time
from datetime import date
from functools import lru_cache
from pathlib import Path
from threading import Thread
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from openfinance.core.audit import AuditLogEntry, FileAuditStore
from openfinance.core.config import settings
from openfinance.core.events import event_bus
from openfinance.core.tasks import TaskRecord, get_task_manager
from openfinance.data.mock_factory import MockDataFactory, MockDatasetConfig
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.backtest.migration import MigrationChecker, MigrationWarning
from openfinance.quant.backtest.meta_runner import MetaBacktestConfig, MetaBacktestRunner
from openfinance.quant.backtest.report import BacktestRequest, BacktestReport
from openfinance.quant.backtest.robustness import RobustnessReport
from openfinance.quant.backtest.run_registry import RunRegistry, RunRegistryEntry
from openfinance.quant.backtest.runner import BacktestRunner
from openfinance.quant.backtest.strategy_runtime_action_regime import (
    StrategyRuntimeActionRegimeDetails,
    resolve_strategy_runtime_action_regime_details,
)
from openfinance.quant.backtest.strategy_runtime_attribution_execution import (
    StrategyRuntimeAttributionExecutionDetails,
    resolve_strategy_runtime_attribution_execution_details,
)
from openfinance.quant.backtest.strategy_runtime_control_action_deep import (
    StrategyRuntimeControlActionDeepDetails,
    resolve_strategy_runtime_control_action_deep_details,
)
from openfinance.quant.backtest.strategy_runtime_control_optimizer import (
    StrategyRuntimeControlOptimizerDetails,
    resolve_strategy_runtime_control_optimizer_details,
)
from openfinance.quant.backtest.strategy_runtime_diagnostics import (
    StrategyCompareResultDetails,
    build_strategy_compare_result_details,
    build_strategy_runtime_diagnostics_result,
)
from openfinance.quant.backtest.strategy_runtime_summary import (
    StrategyCompareOutcomeSummary,
    build_strategy_compare_outcome_summary,
    build_strategy_runtime_outcome_summary,
)
from openfinance.quant.factors.engine import FactorEngine
from openfinance.quant.factors.factor_spec import (
    CostSensitivity,
    CostSensitivityLevel,
    ExpectedHorizon,
    FactorInput,
    FactorSpec,
    ValidationPlan,
)
from openfinance.quant.checks.failure_conditions import normalize_failure_conditions
from openfinance.quant.factors.registry import FactorRegistry
from openfinance.research.strategy_registry import StrategyRegistry
from openfinance.research.strategy_compilation import (
    StrategyCompilationPlan,
    build_strategy_compile_runtime_context,
    build_strategy_compilation_plan,
)
from openfinance.research.strategy_request_builder import build_strategy_backtest_request
from openfinance.research.strategy_spec import StrategySpec, build_strategy_spec_from_constraints
from openfinance.research.strategy_validation import StrategyValidationResult, StrategyValidator

router = APIRouter(prefix="/workbench", tags=["workbench"])
logger = logging.getLogger(__name__)


class GenerateDatasetRequest(BaseModel):
    dataset_id: str = "mock_us_equity"
    market: str = "US"
    symbol: str = "AAPL"
    start: date
    end: date
    seed: int = 42
    base_price: float = Field(default=100.0, gt=0)
    inject_high_vol_segment: bool = False
    high_vol_start_day: int = 20
    high_vol_end_day: int = 40
    high_vol_scale: float = Field(default=3.0, ge=1.0, le=20.0)


class RunBacktestTaskRequest(BaseModel):
    dataset_version: str | None = None
    strategy_id: str = "demo_strategy"
    strategy_version: str = "0.1.0"
    market: str = "US"
    start: str = "2024-01-01"
    end: str = "2024-12-31"


class ReportSummary(BaseModel):
    run_id: str
    dataset_version: str
    strategy_version: str
    audit_trace_id: str
    metrics: dict[str, Any]


class AuditSummary(BaseModel):
    trace_id: str
    run_id: str | None
    event_type: str
    payload: dict[str, Any]
    created_at: str


class StrategySummary(BaseModel):
    strategy_id: str
    strategy_version: str
    status: str
    notes: str


class StrategyDetailResponse(BaseModel):
    source: Literal["strategy_registry", "run_registry_fallback", "placeholder"]
    created_at: str | None = None
    notes: str = ""
    spec: StrategySpec


class RunSummary(BaseModel):
    run_id: str
    audit_trace_id: str | None = None
    dataset_version: str
    strategy_id: str
    strategy_version: str
    market: str
    start: str
    end: str
    sharpe: float | None = None
    max_drawdown: float | None = None


class MultiMarketCompareRequest(BaseModel):
    markets: list[str] = Field(default_factory=lambda: ["US", "JP"])
    strategy_id: str = "multi_market_strategy"
    strategy_version: str = "multi-market-v1"
    strategy_family: str = "trend"
    rebalance: str = "weekly"
    lookback_days: int = Field(default=20, ge=2, le=252)
    signal_threshold: float = 0.0
    position_sizing: str = "risk_budget"
    risk_budget: str = "vol_target_10pct"
    max_position: float = Field(default=0.12, gt=0.0, lt=1.0)
    leverage_limit: float = Field(default=1.0, gt=0.0, le=2.0)
    auto_round_lot: bool = True
    start: str = "2024-01-01"
    end: str = "2024-03-31"
    seed: int = 42
    commission_bps: float = Field(default=5.0, ge=0.0, le=200.0)
    slippage_bps: float = Field(default=8.0, ge=0.0, le=200.0)
    symbol_map: dict[str, str] = Field(default_factory=dict)
    session_id: str | None = None
    request_token: str | None = None


class MarketCompareRow(BaseModel):
    market: str
    run_id: str
    dataset_version: str
    strategy_version: str
    metrics: dict[str, Any]
    action_regime_details: StrategyRuntimeActionRegimeDetails | None = None
    attribution_execution_details: StrategyRuntimeAttributionExecutionDetails | None = None
    control_optimizer_details: StrategyRuntimeControlOptimizerDetails | None = None
    control_action_deep_details: StrategyRuntimeControlActionDeepDetails | None = None


class MultiMarketCompareResponse(BaseModel):
    compare_id: str
    baseline_market: str
    strategy_spec: StrategySpec
    strategy_validation: StrategyValidationResult
    strategy_compilation: StrategyCompilationPlan
    outcome_summary: StrategyCompareOutcomeSummary | None = None
    result_details: StrategyCompareResultDetails | None = None
    rows: list[MarketCompareRow]
    diff_table: list[dict[str, Any]]
    parent_task_id: str | None = None
    child_task_ids: list[str] = Field(default_factory=list)
    migration_warnings: list[MigrationWarning] = Field(default_factory=list)
    market_warnings: dict[str, list[MigrationWarning]] = Field(default_factory=dict)


class RobustnessRunRequest(BaseModel):
    dataset_version: str | None = None
    strategy_id: str = "robustness_strategy"
    strategy_version: str = "robustness-v1"
    market: str = "US"
    start: str = "2024-01-01"
    end: str = "2024-03-31"
    strategy_family: str = "trend"
    rebalance: str = "weekly"
    lookback_days: int = Field(default=20, ge=2, le=252)
    signal_threshold: float = 0.0
    position_sizing: str = "risk_budget"
    risk_budget: str = "vol_target_10pct"
    max_position: float = Field(default=0.12, gt=0.0, lt=1.0)
    leverage_limit: float = Field(default=1.0, gt=0.0, le=2.0)
    auto_round_lot: bool = True
    commission_bps: float = Field(default=5.0, ge=0.0, le=200.0)
    slippage_bps: float = Field(default=8.0, ge=0.0, le=200.0)
    cost_multipliers: list[float] = Field(default_factory=lambda: [0.5, 1.0, 2.0])
    lookback_grid: list[int] = Field(default_factory=list)
    threshold_grid: list[float] = Field(default_factory=list)
    rebalance_grid: list[str] = Field(default_factory=list)
    max_variants: int = Field(default=12, ge=6, le=24)
    session_id: str | None = None
    request_token: str | None = None


class FactorSummary(BaseModel):
    factor_id: str
    version: str
    dataset_schema_version: str
    inputs_signature: str
    availability_lag: str
    created_at: str
    has_report: bool = False


class FactorRunRequest(BaseModel):
    dataset_version: str | None = None
    factor_id: str = "formula_factor"
    factor_version: str | None = None
    description: str = "user-defined formula factor"
    formula: str = "Rank(Ts_Mean(close, 20))"
    availability_lag: str = "0s"
    inputs: list[str] = Field(default_factory=lambda: ["close", "open"])
    failure_conditions: list[str | dict[str, Any]] = Field(default_factory=list)
    cost_sensitivity_level: CostSensitivityLevel | None = None
    cost_sensitivity_rationale: str | None = None
    expected_horizon: ExpectedHorizon | None = None
    lookback_days: int = Field(default=20, ge=1, le=252)
    decay_lags: int = Field(default=5, ge=1, le=20)
    universe: list[str] = Field(default_factory=list)
    seed: int = 42
    session_id: str | None = None
    request_token: str | None = None


class FactorRunResponse(BaseModel):
    factor_id: str
    factor_version: str
    dataset_version: str
    artifact_path: str
    cached: bool
    report: dict[str, Any]


class FactorMultiMarketCompareRequest(BaseModel):
    factor_id: str | None = None
    factor_versions: list[str] = Field(default_factory=list)
    factor_spec: FactorSpec | None = None
    markets: list[str] = Field(default_factory=lambda: ["US", "JP"])
    universe: list[str] = Field(default_factory=list)
    symbol_map: dict[str, str] = Field(default_factory=dict)
    start: str = "2024-01-01"
    end: str = "2024-06-30"
    seed: int = 42
    eval_metrics: list[str] = Field(default_factory=lambda: ["IC", "RankIC", "decay", "coverage"])
    session_id: str | None = None
    request_token: str | None = None


class FactorMarketMetricRow(BaseModel):
    market: str
    factor_id: str
    factor_version: str
    dataset_version: str
    ic_mean: float
    rank_ic_mean: float
    coverage: float
    turnover_proxy: float
    in_sample_ic_mean: float
    out_sample_ic_mean: float
    oos_gap: float
    avg_spread_bps: float
    decay_ratio: float
    decay_half_life_lag: int
    estimated_cost_pressure: float
    cost_sensitivity_level: str


class FactorMarketDecayCurve(BaseModel):
    market: str
    factor_id: str
    factor_version: str
    points: list[dict[str, float | int]]


class FactorMultiMarketCompareResponse(BaseModel):
    compare_id: str
    requested_metrics: list[str]
    per_market_metrics: list[FactorMarketMetricRow]
    per_market_decay_curves: list[FactorMarketDecayCurve]
    summary_insights: list[str]
    parent_task_id: str | None = None
    child_task_ids: list[str] = Field(default_factory=list)


@lru_cache(maxsize=1)
def _task_manager():
    return get_task_manager()


@lru_cache(maxsize=1)
def _audit_store() -> FileAuditStore:
    return FileAuditStore(settings.audit_log_file)


@lru_cache(maxsize=1)
def _dataset_registry() -> DatasetRegistry:
    return DatasetRegistry(
        registry_file=settings.dataset_registry_file,
        data_root=settings.data_root,
    )


@lru_cache(maxsize=1)
def _run_registry() -> RunRegistry:
    return RunRegistry(settings.run_registry_file)


@lru_cache(maxsize=1)
def _factor_registry() -> FactorRegistry:
    return FactorRegistry(settings.factor_registry_db_file)


@lru_cache(maxsize=1)
def _strategy_registry() -> StrategyRegistry:
    return StrategyRegistry(settings.strategy_registry_db_file)


@lru_cache(maxsize=1)
def _factor_engine() -> FactorEngine:
    return FactorEngine(
        dataset_registry=_dataset_registry(),
        factor_registry=_factor_registry(),
        artifact_root=settings.factor_artifact_root,
    )


def _write_audit(event_type: str, trace_id: UUID, payload: dict[str, Any], run_id: UUID | None = None) -> None:
    _audit_store().append(
        AuditLogEntry(
            trace_id=trace_id,
            run_id=run_id,
            event_type=event_type,
            payload=payload,
        )
    )


def _emit_event(event_type: str, trace_id: UUID, payload: dict[str, Any], session_id: str = "workbench") -> None:
    event_bus.publish(
        event_type=event_type,
        payload=payload,
        trace_id=str(trace_id),
        session_id=session_id,
    )


def _task_payload(task: TaskRecord, **extra: Any) -> dict[str, Any]:
    payload = {
        "task_id": str(task.task_id),
        "parent_task_id": str(task.parent_task_id) if task.parent_task_id else None,
        "type": task.task_type,
        "status": task.status,
        "progress": task.progress,
        "message": task.message,
        "result_ref": task.result_ref,
        "error": task.error,
        "task": task.model_dump(mode="json"),
    }
    payload.update(extra)
    return payload


def _emit_task_state(event_type: str, trace_id: UUID, task: TaskRecord, **extra: Any) -> None:
    payload = _task_payload(task, **extra)
    session_id = str(
        extra.get("session_id")
        or (task.meta or {}).get("session_id")
        or payload.get("session_id")
        or "workbench"
    ).strip() or "workbench"
    payload["session_id"] = session_id
    _write_audit(event_type, trace_id, payload)
    _emit_event(event_type, trace_id, payload, session_id=session_id)

def _strategy_spec_from_run_entry(entry: RunRegistryEntry) -> StrategySpec:
    req = entry.request
    constraints = req.get("constraints", {})
    if not isinstance(constraints, dict):
        constraints = {}
    evidence_refs_raw = req.get("evidence_refs")
    return build_strategy_spec_from_constraints(
        strategy_id=str(entry.strategy_id),
        strategy_version=str(entry.strategy_version),
        plan_id=str(constraints.get("plan_id") or "").strip() or None,
        experiment_id=str(constraints.get("experiment_id") or "").strip() or None,
        market=str(entry.market or req.get("market", "US")),
        constraints=constraints,
        rationale=str(constraints.get("rationale", "Derived from run registry")).strip() or "Derived from run registry",
        evidence_refs=[
            str(ref).strip()
            for ref in evidence_refs_raw
            if str(ref).strip()
        ]
        if isinstance(evidence_refs_raw, list)
        else [],
    )


def _run_dataset_job(task_id: UUID, trace_id: UUID, req: GenerateDatasetRequest) -> None:
    tm = _task_manager()
    try:
        task = tm.update(task_id, status="running", progress=10, message="preparing config")
        _emit_task_state("task.progress", trace_id, task)
        time.sleep(0.2)

        config = MockDatasetConfig(
            dataset_id=req.dataset_id,
            market=req.market,
            symbol=req.symbol,
            start_date=req.start,
            end_date=req.end,
            seed=req.seed,
            base_price=req.base_price,
            inject_high_vol_segment=req.inject_high_vol_segment,
            high_vol_start_day=req.high_vol_start_day,
            high_vol_end_day=req.high_vol_end_day,
            high_vol_scale=req.high_vol_scale,
        )
        task = tm.update(task_id, progress=55, message="generating dataset")
        _emit_task_state("task.progress", trace_id, task)
        dataset = MockDataFactory().generate(config)
        entry = _dataset_registry().register(dataset)

        result = {
            "dataset_id": entry.dataset_id,
            "dataset_version": entry.dataset_version,
            "artifact_path": entry.artifact_path,
        }
        task = tm.update(task_id, status="done", progress=100, message="dataset ready", result=result)
        _emit_task_state("task.done", trace_id, task)
    except Exception as ex:
        task = tm.update(task_id, status="error", progress=100, message="dataset failed", error=str(ex))
        _emit_task_state("task.error", trace_id, task)


def _run_backtest_job(task_id: UUID, trace_id: UUID, req: RunBacktestTaskRequest) -> None:
    tm = _task_manager()
    try:
        task = tm.update(task_id, status="running", progress=15, message="loading dataset")
        _emit_task_state("task.progress", trace_id, task)
        time.sleep(0.2)

        dataset_version = req.dataset_version
        if not dataset_version:
            entries = _dataset_registry().list_entries()
            if not entries:
                raise ValueError("no dataset available; generate one first")
            dataset_version = entries[-1].dataset_version

        runner = BacktestRunner(
            dataset_registry=_dataset_registry(),
            run_registry=_run_registry(),
            audit_store=_audit_store(),
            report_root=settings.data_root,
        )
        task = tm.update(task_id, progress=65, message="running backtest")
        _emit_task_state("task.progress", trace_id, task)
        report = runner.run(
            BacktestRequest(
                dataset_version=dataset_version,
                strategy_id=req.strategy_id,
                strategy_version=req.strategy_version,
                market=req.market,
                start=req.start,
                end=req.end,
            )
        )

        result = {
            "run_id": str(report.run_id),
            "dataset_version": report.dataset_version,
            "strategy_version": report.strategy_version,
            "audit_trace_id": str(report.audit_trace_id),
            "report_ready": True,
        }
        task = tm.update(
            task_id,
            status="done",
            progress=100,
            message="backtest complete",
            result=result,
            result_ref={"run_id": str(report.run_id), "report_id": str(report.run_id)},
        )
        _write_audit("report.ready", trace_id, _task_payload(task, result=result), report.run_id)
        _emit_event("report.ready", trace_id, _task_payload(task, result=result))
        _emit_task_state("task.done", trace_id, task)
    except Exception as ex:
        task = tm.update(task_id, status="error", progress=100, message="backtest failed", error=str(ex))
        _emit_task_state("task.error", trace_id, task)


def _resolve_dataset_version(dataset_version: str | None) -> str:
    if dataset_version:
        return dataset_version
    rows = _dataset_registry().list_entries()
    if not rows:
        raise HTTPException(status_code=400, detail="no dataset available; generate one first")
    return rows[-1].dataset_version


def _factor_artifact_report(version: str) -> dict[str, Any] | None:
    root = Path(settings.factor_artifact_root)
    if not root.exists():
        return None
    for path in sorted(root.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if str(payload.get("factor_version")) != version:
            continue
        report = payload.get("report")
        if isinstance(report, dict):
            return report
        continue
    return None


def _default_symbol_for_market(market: str) -> str:
    key = market.upper()
    mapping = {
        "US": "AAPL",
        "CN": "600519.SS",
        "JP": "7203.T",
        "CRYPTO": "BTCUSDT",
    }
    return mapping.get(key, "AAPL")


def _normalize_markets(markets: list[str]) -> list[str]:
    ordered: list[str] = []
    for item in markets:
        key = str(item).strip().upper()
        if not key:
            continue
        if key not in {"US", "CN", "JP", "CRYPTO"}:
            continue
        if key not in ordered:
            ordered.append(key)
    return ordered


def _metric_number(metrics: dict[str, Any], key: str) -> float:
    value = metrics.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _normalize_eval_metrics(metrics: list[str]) -> list[str]:
    allowed = {"ic", "rankic", "decay", "coverage"}
    normalized: list[str] = []
    for item in metrics:
        key = str(item).strip().lower()
        if not key or key not in allowed:
            continue
        if key not in normalized:
            normalized.append(key)
    return normalized or ["ic", "rankic", "decay", "coverage"]


def _resolve_factor_specs_for_compare(request: FactorMultiMarketCompareRequest) -> list[FactorSpec]:
    registry = _factor_registry()
    if request.factor_spec is not None:
        return [request.factor_spec]

    if request.factor_versions:
        specs: list[FactorSpec] = []
        for version in request.factor_versions:
            entry = registry.get_by_version(version)
            if entry is None:
                raise HTTPException(status_code=404, detail=f"factor version not found: {version}")
            if request.factor_id and entry.factor_id != request.factor_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"factor version mismatch for factor_id={request.factor_id}: {version}",
                )
            specs.append(FactorSpec.model_validate(entry.spec))
        return specs

    if request.factor_id:
        for entry in registry.list_entries(limit=500):
            if entry.factor_id == request.factor_id:
                return [FactorSpec.model_validate(entry.spec)]
        raise HTTPException(status_code=404, detail=f"factor not found: {request.factor_id}")

    raise HTTPException(status_code=400, detail="provide factor_spec or factor_id/factor_versions")


def _with_universe_override(spec: FactorSpec, universe: list[str]) -> FactorSpec:
    cleaned = [str(item).strip() for item in universe if str(item).strip()]
    if not cleaned:
        return spec
    params = dict(spec.params)
    params["universe"] = list(dict.fromkeys(cleaned))
    return spec.model_copy(update={"params": params})


def _decay_profile(decay_curve: list[Any]) -> tuple[float, int, float, float]:
    if not decay_curve:
        return 0.0, 0, 0.0, 0.0
    points: list[tuple[int, float]] = []
    for row in decay_curve:
        if isinstance(row, dict):
            lag = row.get("lag")
            ic = row.get("ic")
        else:
            lag = getattr(row, "lag", None)
            ic = getattr(row, "ic", None)
        if not isinstance(lag, int):
            continue
        if not isinstance(ic, (int, float)):
            continue
        points.append((lag, float(ic)))
    if not points:
        return 0.0, 0, 0.0, 0.0

    points = sorted(points, key=lambda item: item[0])
    lag1_ic = points[0][1]
    last_ic = points[-1][1]
    base = max(abs(lag1_ic), 0.02)
    ratio = abs(last_ic) / base
    half_life_threshold = 0.5 * abs(lag1_ic)
    half_life = points[-1][0]
    for lag, ic in points:
        if abs(ic) <= half_life_threshold:
            half_life = lag
            break
    return ratio, half_life, lag1_ic, last_ic


def _market_avg_spread_bps(dataset: Any) -> float:
    spreads = [float(getattr(bar, "spread_bps", 0.0)) for bar in getattr(dataset, "market", [])]
    if not spreads:
        return 0.0
    return round(statistics.fmean(spreads), 6)


def _cost_sensitivity_multiplier(level: str) -> float:
    key = level.strip().lower()
    mapping = {"low": 0.7, "medium": 1.0, "high": 1.4}
    return mapping.get(key, 1.0)


def _build_factor_compare_insights(rows: list[FactorMarketMetricRow]) -> list[str]:
    if not rows:
        return ["No market rows were produced."]
    stable = max(rows, key=lambda row: row.decay_ratio)
    fast_decay = min(rows, key=lambda row: row.decay_ratio)
    weak_coverage = min(rows, key=lambda row: row.coverage)
    high_cost = max(rows, key=lambda row: row.estimated_cost_pressure)
    insights = [
        (
            f"{stable.market} has the most stable IC decay "
            f"(ratio={stable.decay_ratio:.3f}, lag1={stable.ic_mean:.4f})."
        ),
        (
            f"{fast_decay.market} decays fastest (ratio={fast_decay.decay_ratio:.3f}, "
            f"half_life_lag={fast_decay.decay_half_life_lag})."
        ),
        (
            f"{weak_coverage.market} has the weakest coverage ({weak_coverage.coverage:.3f}); "
            "review universe breadth or data quality."
        ),
        (
            f"Cost pressure is highest in {high_cost.market} "
            f"(score={high_cost.estimated_cost_pressure:.4f}, spread={high_cost.avg_spread_bps:.2f}bps)."
        ),
    ]
    us_row = next((row for row in rows if row.market == "US"), None)
    jp_row = next((row for row in rows if row.market == "JP"), None)
    if us_row is not None and jp_row is not None:
        if us_row.decay_ratio >= jp_row.decay_ratio:
            insights.append(
                "Mock regime signal: US IC is more stable while JP decay is faster under stronger mean reversion."
            )
        else:
            insights.append(
                "Mock regime signal: JP IC is currently more stable than US for this factor configuration."
            )
    return insights


@router.get("/datasets")
def list_datasets() -> list[dict[str, Any]]:
    return [entry.model_dump(mode="json") for entry in _dataset_registry().list_entries()]


@router.get("/datasets/{dataset_version}")
def get_dataset(dataset_version: str) -> dict[str, Any]:
    entry = _dataset_registry().get_entry(dataset_version)
    if entry is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    return entry.model_dump(mode="json")


@router.post("/datasets/generate", response_model=TaskRecord)
def create_dataset_task(request: GenerateDatasetRequest) -> TaskRecord:
    task = _task_manager().create(task_type="dataset.generate", message="queued")
    trace_id = uuid4()
    _emit_task_state("task.created", trace_id, task)
    Thread(target=_run_dataset_job, args=(task.task_id, trace_id, request), daemon=True).start()
    return task


@router.post("/backtests/run", response_model=TaskRecord)
def create_backtest_task(request: RunBacktestTaskRequest) -> TaskRecord:
    task = _task_manager().create(task_type="backtest.run", message="queued")
    trace_id = uuid4()
    _emit_task_state("task.created", trace_id, task)
    Thread(target=_run_backtest_job, args=(task.task_id, trace_id, request), daemon=True).start()
    return task


@router.get("/tasks", response_model=list[TaskRecord])
def list_tasks(session_id: str | None = Query(default=None)) -> list[TaskRecord]:
    rows = _task_manager().list_tasks()
    target_session = str(session_id or "").strip()
    if not target_session:
        return rows

    by_id = {row.task_id: row for row in rows}
    selected: set[UUID] = set()
    queue: list[UUID] = []

    for row in rows:
        row_session = str((row.meta or {}).get("session_id") or "").strip()
        if row_session == target_session:
            selected.add(row.task_id)
            queue.append(row.task_id)

    if not selected:
        return []

    while queue:
        current = queue.pop()
        current_row = by_id.get(current)
        if current_row is None:
            continue
        parent_id = current_row.parent_task_id
        if parent_id and parent_id not in selected:
            selected.add(parent_id)
            queue.append(parent_id)
        for candidate in rows:
            if candidate.parent_task_id == current and candidate.task_id not in selected:
                selected.add(candidate.task_id)
                queue.append(candidate.task_id)

    filtered = [row for row in rows if row.task_id in selected]
    return sorted(filtered, key=lambda x: x.created_at, reverse=True)


@router.get("/tasks/{task_id}", response_model=TaskRecord)
def get_task(task_id: UUID) -> TaskRecord:
    task = _task_manager().get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.get("/reports", response_model=list[ReportSummary])
def list_reports() -> list[ReportSummary]:
    reports: list[ReportSummary] = []
    for entry in _run_registry().list_entries():
        report_path = Path(entry.report_path)
        if not report_path.exists():
            continue
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        reports.append(
            ReportSummary(
                run_id=str(payload["run_id"]),
                dataset_version=payload["dataset_version"],
                strategy_version=payload["strategy_version"],
                audit_trace_id=str(payload["audit_trace_id"]),
                metrics=payload.get("metrics", {}),
            )
        )
    return reports


@router.get("/reports/{run_id}", response_model=BacktestReport)
def get_report(run_id: str) -> BacktestReport:
    for entry in _run_registry().list_entries():
        if str(entry.run_id) != run_id:
            continue
        report_path = Path(entry.report_path)
        if not report_path.exists():
            break
        report = BacktestReport.model_validate_json(report_path.read_text(encoding="utf-8"))
        return report.model_copy(
            update={
                "attribution_execution_details": resolve_strategy_runtime_attribution_execution_details(
                    detail_object="BacktestReport",
                    details=report.attribution_execution_details,
                    cost_breakdown=report.cost_breakdown,
                    attribution=report.attribution,
                    diagnostics=report.diagnostics,
                    orders=report.orders,
                    trades=report.trades,
                    metrics=report.metrics,
                ),
                "control_action_deep_details": resolve_strategy_runtime_control_action_deep_details(
                    detail_object="BacktestReport",
                    details=report.control_action_deep_details,
                    diagnostics=report.diagnostics,
                )
            }
        )
    raise HTTPException(status_code=404, detail="report not found")


@router.post("/reports/multi-market/compare", response_model=MultiMarketCompareResponse)
def compare_multi_market(request: MultiMarketCompareRequest) -> MultiMarketCompareResponse:
    markets = _normalize_markets(request.markets)
    if len(markets) < 2:
        raise HTTPException(status_code=400, detail="at least two valid markets are required")

    compare_id = f"mmc_{uuid4().hex[:12]}"
    trace_id = uuid4()
    session_id = str(request.session_id or "").strip()
    request_token = str(request.request_token or "").strip()
    tm = _task_manager()
    migration_checker = MigrationChecker()
    runner = BacktestRunner(
        dataset_registry=_dataset_registry(),
        run_registry=_run_registry(),
        audit_store=_audit_store(),
        report_root=settings.data_root,
    )
    strategy_validator = StrategyValidator()
    strategy_spec = build_strategy_spec_from_constraints(
        strategy_id=request.strategy_id,
        strategy_version=request.strategy_version,
        market=markets[0],
        constraints={
            "strategy_family": request.strategy_family,
            "rebalance": request.rebalance,
            "lookback_days": request.lookback_days,
            "signal_threshold": request.signal_threshold,
            "position_sizing": request.position_sizing,
            "risk_budget": request.risk_budget,
            "max_position": request.max_position,
            "leverage_limit": request.leverage_limit,
            "auto_round_lot": request.auto_round_lot,
            "commission_bps": request.commission_bps,
            "slippage_bps": request.slippage_bps,
            "start": request.start,
            "end": request.end,
        },
        rationale="Multi-market comparison base strategy semantics derived from request.",
    )
    strategy_validation = strategy_validator.validate_spec(strategy_spec)
    runtime_context = build_strategy_compile_runtime_context(
        dataset_version="multi_market.compare",
        start=request.start,
        end=request.end,
        execution_model="next_open",
        run_time_utc="16:00",
        commission_bps=request.commission_bps,
        slippage_bps=request.slippage_bps,
        auto_round_lot=request.auto_round_lot,
        provenance_mode="user_requested",
    )
    strategy_compilation = build_strategy_compilation_plan(
        strategy_spec,
        strategy_validation,
        runtime_context=runtime_context,
    )
    strategy_spec_payload = strategy_spec.model_dump(mode="json")
    parent_task = tm.create(
        task_type="multi_market.compare",
        message="queued",
        status="queued",
        meta={
            "compare_id": compare_id,
            "markets": markets,
            "strategy_id": request.strategy_id,
            "strategy_version": request.strategy_version,
            "session_id": session_id,
            "request_token": request_token,
        },
    )
    logger.info("multi_market.compare parent_task created: %s", parent_task.task_id)
    _emit_task_state("task.created", trace_id, parent_task, role="parent", compare_id=compare_id)
    child_by_market: dict[str, UUID] = {}
    child_task_ids: list[str] = []
    for market in markets:
        child = tm.create(
            task_type="multi_market.market_run",
            message=f"queued: {market}",
            parent_task_id=parent_task.task_id,
            status="queued",
            meta={
                "market": market,
                "compare_id": compare_id,
                "session_id": session_id,
                "request_token": request_token,
            },
        )
        child_by_market[market] = child.task_id
        child_task_ids.append(str(child.task_id))
        _emit_task_state(
            "task.created",
            trace_id,
            child,
            role="child",
            parent_task_id=str(parent_task.task_id),
            market=market,
            compare_id=compare_id,
        )
    try:
        start_date = date.fromisoformat(request.start)
        end_date = date.fromisoformat(request.end)
    except ValueError as ex:
        error_message = "start/end must be YYYY-MM-DD"
        parent_error = tm.update(
            parent_task.task_id,
            status="error",
            progress=100,
            message=error_message,
            error=error_message,
        )
        _emit_task_state("task.error", trace_id, parent_error, role="parent", compare_id=compare_id)
        for market, child_id in child_by_market.items():
            child_canceled = tm.update(
                child_id,
                status="canceled",
                progress=100,
                message=f"canceled: {market}",
                error=error_message,
            )
            _emit_task_state(
                "task.error",
                trace_id,
                child_canceled,
                role="child",
                parent_task_id=str(parent_task.task_id),
                market=market,
                compare_id=compare_id,
            )
        raise HTTPException(status_code=400, detail="start/end must be YYYY-MM-DD") from ex
    if start_date >= end_date:
        error_message = "start must be earlier than end"
        parent_error = tm.update(
            parent_task.task_id,
            status="error",
            progress=100,
            message=error_message,
            error=error_message,
        )
        _emit_task_state("task.error", trace_id, parent_error, role="parent", compare_id=compare_id)
        for market, child_id in child_by_market.items():
            child_canceled = tm.update(
                child_id,
                status="canceled",
                progress=100,
                message=f"canceled: {market}",
                error=error_message,
            )
            _emit_task_state(
                "task.error",
                trace_id,
                child_canceled,
                role="child",
                parent_task_id=str(parent_task.task_id),
                market=market,
                compare_id=compare_id,
            )
        raise HTTPException(status_code=400, detail="start must be earlier than end")

    parent_running = tm.update(
        parent_task.task_id,
        status="running",
        progress=5,
        message=f"queued {len(markets)} market runs",
    )
    _emit_task_state("task.progress", trace_id, parent_running, role="parent", compare_id=compare_id)
    rows: list[MarketCompareRow] = []
    market_warnings: dict[str, list[MigrationWarning]] = {}
    flat_warnings: list[MigrationWarning] = []
    done_markets = 0
    try:
        if settings.task_force_error:
            raise RuntimeError("forced task failure via OPENFINANCE_TASK_FORCE_ERROR=true")
        for idx, market in enumerate(markets):
            child_id = child_by_market.get(market)
            if child_id is not None:
                child_running = tm.update(child_id, status="running", progress=12, message=f"running: {market}")
                _emit_task_state(
                    "task.progress",
                    trace_id,
                    child_running,
                    role="child",
                    parent_task_id=str(parent_task.task_id),
                    market=market,
                    compare_id=compare_id,
                )

            symbol = request.symbol_map.get(market) or _default_symbol_for_market(market)
            rules = runner.market_rules.get(market)
            dataset = MockDataFactory().generate(
                MockDatasetConfig(
                    dataset_id=f"{compare_id}_{market.lower()}",
                    market=market,
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    seed=request.seed + idx,
                )
            )
            dataset_entry = _dataset_registry().register(dataset)
            market_strategy_spec = strategy_spec.model_copy(update={"market": market}, deep=True)
            market_strategy_validation = strategy_validator.validate_spec(market_strategy_spec)
            market_runtime_context = build_strategy_compile_runtime_context(
                dataset_version=dataset_entry.dataset_version,
                start=request.start,
                end=request.end,
                execution_model="next_open",
                run_time_utc="16:00",
                commission_bps=request.commission_bps,
                slippage_bps=request.slippage_bps,
                auto_round_lot=request.auto_round_lot,
                provenance_mode="user_requested",
            )
            market_strategy_compilation = build_strategy_compilation_plan(
                market_strategy_spec,
                market_strategy_validation,
                runtime_context=market_runtime_context,
            )
            backtest_request = build_strategy_backtest_request(
                strategy_id=request.strategy_id,
                strategy_version=request.strategy_version,
                market=market,
                runtime_context=market_runtime_context,
                constraints={
                    "strategy_family": request.strategy_family,
                    "rebalance": request.rebalance,
                    "lookback_days": request.lookback_days,
                    "signal_threshold": request.signal_threshold,
                    "position_sizing": request.position_sizing,
                    "risk_budget": request.risk_budget,
                    "max_position": request.max_position,
                    "leverage_limit": request.leverage_limit,
                    "auto_round_lot": request.auto_round_lot,
                },
                strategy_validation=market_strategy_validation,
                strategy_compilation=market_strategy_compilation,
            )
            current_warnings = migration_checker.check(strategy_spec, market, rules)
            market_warnings[market] = current_warnings
            flat_warnings.extend(current_warnings)
            report = runner.run(backtest_request)
            action_regime_details = resolve_strategy_runtime_action_regime_details(
                detail_object="MarketCompareRow",
                details=report.action_regime_details,
                diagnostics=report.diagnostics,
            )
            attribution_execution_details = resolve_strategy_runtime_attribution_execution_details(
                detail_object="MarketCompareRow",
                details=report.attribution_execution_details,
                cost_breakdown=report.cost_breakdown,
                attribution=report.attribution,
                diagnostics=report.diagnostics,
                orders=report.orders,
                trades=report.trades,
                metrics=report.metrics,
            )
            control_optimizer_details = resolve_strategy_runtime_control_optimizer_details(
                detail_object="MarketCompareRow",
                details=report.control_optimizer_details,
                diagnostics=report.diagnostics,
            )
            control_action_deep_details = resolve_strategy_runtime_control_action_deep_details(
                detail_object="MarketCompareRow",
                details=report.control_action_deep_details,
                diagnostics=report.diagnostics,
            )
            row = MarketCompareRow(
                market=market,
                run_id=str(report.run_id),
                dataset_version=report.dataset_version,
                strategy_version=report.strategy_version,
                metrics=report.metrics,
                action_regime_details=action_regime_details,
                attribution_execution_details=attribution_execution_details,
                control_optimizer_details=control_optimizer_details,
                control_action_deep_details=control_action_deep_details,
            )
            rows.append(row)
            done_markets += 1
            if child_id is not None:
                child_runtime_summary = report.runtime_summary or build_strategy_runtime_outcome_summary(
                    summary_object="MarketCompareRow",
                    run_id=str(report.run_id),
                    dataset_version=report.dataset_version,
                    market=row.market,
                    strategy_version=report.strategy_version,
                    metrics=report.metrics,
                    strategy_trace=report.strategy_trace,
                    warning_count=len(market_warnings.get(row.market, [])),
                    highest_warning_severity=migration_checker.highest_severity(market_warnings.get(row.market, [])),
                )
                child_runtime_diagnostics = report.runtime_diagnostics or build_strategy_runtime_diagnostics_result(
                    diagnostics_object="BacktestReport",
                    diagnostics=report.diagnostics,
                )
                child_done = tm.update(
                    child_id,
                    status="done",
                    progress=100,
                    message=f"done: {market}",
                    result={
                        "metrics": dict(report.metrics),
                        "runtime_summary": child_runtime_summary.model_dump(mode="json"),
                        "runtime_diagnostics": child_runtime_diagnostics.model_dump(mode="json"),
                        "action_regime_details": action_regime_details.model_dump(mode="json"),
                        "attribution_execution_details": attribution_execution_details.model_dump(mode="json"),
                        "control_optimizer_details": control_optimizer_details.model_dump(mode="json"),
                        "control_action_deep_details": control_action_deep_details.model_dump(mode="json"),
                    },
                    result_ref={
                        "run_id": str(report.run_id),
                        "report_id": str(report.run_id),
                        "open_path": f"/reports/{report.run_id}",
                    },
                )
                _emit_task_state(
                    "task.done",
                    trace_id,
                    child_done,
                    role="child",
                    parent_task_id=str(parent_task.task_id),
                    market=market,
                    compare_id=compare_id,
                )
            parent_progress = min(90, 8 + int((done_markets / max(1, len(markets))) * 80))
            parent_running = tm.update(
                parent_task.task_id,
                status="running",
                progress=parent_progress,
                message=f"{done_markets}/{len(markets)} market runs completed",
            )
            _emit_task_state(
                "task.progress",
                trace_id,
                parent_running,
                role="parent",
                compare_id=compare_id,
                parent_task_id=str(parent_task.task_id),
            )
    except Exception as ex:
        logger.exception("multi_market.compare failed: parent_task_id=%s", parent_task.task_id)
        parent_error = tm.update(
            parent_task.task_id,
            status="error",
            progress=100,
            message="multi-market compare failed",
            error=str(ex),
        )
        _emit_task_state("task.error", trace_id, parent_error, role="parent", compare_id=compare_id)
        for market, child_id in child_by_market.items():
            child = tm.get(child_id)
            if child is None or child.status == "done":
                continue
            child_error = tm.update(
                child_id,
                status="error",
                progress=100,
                message=f"canceled due to parent failure: {market}",
                error=str(ex),
            )
            _emit_task_state(
                "task.error",
                trace_id,
                child_error,
                role="child",
                parent_task_id=str(parent_task.task_id),
                market=market,
                compare_id=compare_id,
            )
        raise

    baseline = rows[0]
    baseline_metrics = baseline.metrics
    diff_table: list[dict[str, Any]] = []
    for row in rows:
        metrics = row.metrics
        diff_table.append(
            {
                "market": row.market,
                "run_id": row.run_id,
                "dataset_version": row.dataset_version,
                "sharpe": _metric_number(metrics, "sharpe"),
                "max_drawdown": _metric_number(metrics, "max_drawdown"),
                "turnover": _metric_number(metrics, "turnover"),
                "reject_count": _metric_number(metrics, "reject_count"),
                "cost_drag": _metric_number(metrics, "cost_drag"),
                "sharpe_diff_vs_baseline": round(
                    _metric_number(metrics, "sharpe") - _metric_number(baseline_metrics, "sharpe"), 6
                ),
                "max_drawdown_diff_vs_baseline": round(
                    _metric_number(metrics, "max_drawdown")
                    - _metric_number(baseline_metrics, "max_drawdown"),
                    6,
                ),
                "turnover_diff_vs_baseline": round(
                    _metric_number(metrics, "turnover") - _metric_number(baseline_metrics, "turnover"), 6
                ),
                "warning_count": len(market_warnings.get(row.market, [])),
                "highest_warning_severity": migration_checker.highest_severity(market_warnings.get(row.market, [])),
            }
        )

    outcome_summary_rows = [
        build_strategy_runtime_outcome_summary(
            summary_object="MarketCompareRow",
            run_id=row.run_id,
            dataset_version=row.dataset_version,
            market=row.market,
            strategy_version=row.strategy_version,
            metrics=row.metrics,
            warning_count=len(market_warnings.get(row.market, [])),
            highest_warning_severity=migration_checker.highest_severity(market_warnings.get(row.market, [])),
        )
        for row in rows
    ]
    outcome_summary = build_strategy_compare_outcome_summary(
        compare_id=compare_id,
        baseline_market=baseline.market,
        rows=outcome_summary_rows,
    )
    result_details = build_strategy_compare_result_details(
        compare_id=compare_id,
        baseline_market=baseline.market,
        diff_rows=diff_table,
        market_warnings={
            key: [item.model_dump(mode="json") for item in values] for key, values in market_warnings.items()
        },
    )

    _write_audit(
        "workbench.multi_market.compare",
        trace_id,
        {
            "compare_id": compare_id,
            "baseline_market": baseline.market,
            "strategy_spec": strategy_spec_payload,
            "strategy_validation": strategy_validation.model_dump(mode="json"),
            "strategy_compilation": strategy_compilation.model_dump(mode="json"),
            "outcome_summary": outcome_summary.model_dump(mode="json"),
            "result_details": result_details.model_dump(mode="json"),
            "rows": [row.model_dump(mode="json") for row in rows],
            "diff_table": diff_table,
            "market_warnings": {
                key: [item.model_dump(mode="json") for item in values] for key, values in market_warnings.items()
            },
        },
    )
    _emit_event(
        "report.multi_market.ready",
        trace_id,
        {
            "compare_id": compare_id,
            "baseline_market": baseline.market,
            "row_count": len(rows),
            "parent_task_id": str(parent_task.task_id),
        },
    )
    parent_done = tm.update(
        parent_task.task_id,
        status="done",
        progress=100,
        message=f"{done_markets}/{len(markets)} market runs completed",
        result={
            "compare_id": compare_id,
            "baseline_market": baseline.market,
            "row_count": len(rows),
            "strategy_spec": strategy_spec_payload,
            "strategy_validation": strategy_validation.model_dump(mode="json"),
            "strategy_compilation": strategy_compilation.model_dump(mode="json"),
            "outcome_summary": outcome_summary.model_dump(mode="json"),
            "result_details": result_details.model_dump(mode="json"),
            "rows": [row.model_dump(mode="json") for row in rows],
            "diff_table": diff_table,
            "migration_warnings": [item.model_dump(mode="json") for item in flat_warnings],
            "market_warnings": {
                key: [item.model_dump(mode="json") for item in values] for key, values in market_warnings.items()
            },
        },
        result_ref={
            "report_id": compare_id,
            "open_path": f"/reports?compare_id={compare_id}",
            "compare_path": "/reports",
        },
        meta={
            **(tm.get(parent_task.task_id).meta if tm.get(parent_task.task_id) else {}),
            "child_task_ids": child_task_ids,
        },
    )
    _emit_task_state(
        "task.done",
        trace_id,
        parent_done,
        role="parent",
        compare_id=compare_id,
        parent_task_id=str(parent_task.task_id),
    )
    logger.info("multi_market.compare done: parent_task_id=%s compare_id=%s", parent_task.task_id, compare_id)
    return MultiMarketCompareResponse(
        compare_id=compare_id,
        baseline_market=baseline.market,
        strategy_spec=strategy_spec,
        strategy_validation=strategy_validation,
        strategy_compilation=strategy_compilation,
        outcome_summary=outcome_summary,
        result_details=result_details,
        rows=rows,
        diff_table=diff_table,
        parent_task_id=str(parent_task.task_id),
        child_task_ids=child_task_ids,
        migration_warnings=flat_warnings,
        market_warnings=market_warnings,
    )


def _wait_task_by_request_token(*, task_type: str, request_token: str, timeout_s: float = 2.5) -> TaskRecord:
    deadline = time.time() + max(0.2, timeout_s)
    while time.time() <= deadline:
        rows = _task_manager().list_tasks()
        for row in rows:
            if row.task_type != task_type:
                continue
            token = str((row.meta or {}).get("request_token") or "").strip()
            if token == request_token:
                return row
        time.sleep(0.02)
    raise HTTPException(status_code=500, detail=f"failed to register {task_type} task")


@router.post("/reports/multi-market/compare/submit", response_model=TaskRecord)
def submit_multi_market_compare_task(request: MultiMarketCompareRequest) -> TaskRecord:
    markets = _normalize_markets(request.markets)
    if len(markets) < 2:
        raise HTTPException(status_code=400, detail="at least two valid markets are required")
    request_token = uuid4().hex
    submit_request = request.model_copy(update={"request_token": request_token}, deep=True)

    def _worker() -> None:
        try:
            compare_multi_market(submit_request)
        except Exception:
            logger.exception("submit_multi_market_compare_task worker failed")

    Thread(target=_worker, daemon=True).start()
    return _wait_task_by_request_token(
        task_type="multi_market.compare",
        request_token=request_token,
        timeout_s=12.0,
    )


@router.post("/reports/robustness/run", response_model=RobustnessReport)
def run_robustness(request: RobustnessRunRequest) -> RobustnessReport:
    dataset_version = _resolve_dataset_version(request.dataset_version)
    try:
        start_date = date.fromisoformat(request.start)
        end_date = date.fromisoformat(request.end)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail="start/end must be YYYY-MM-DD") from ex
    if start_date >= end_date:
        raise HTTPException(status_code=400, detail="start must be earlier than end")

    strategy_validator = StrategyValidator()
    base_strategy_spec = build_strategy_spec_from_constraints(
        strategy_id=request.strategy_id,
        strategy_version=request.strategy_version,
        market=request.market.upper(),
        constraints={
            "strategy_family": request.strategy_family,
            "rebalance": request.rebalance,
            "lookback_days": request.lookback_days,
            "signal_threshold": request.signal_threshold,
            "position_sizing": request.position_sizing,
            "risk_budget": request.risk_budget,
            "max_position": request.max_position,
            "leverage_limit": request.leverage_limit,
            "auto_round_lot": request.auto_round_lot,
        },
        rationale="Robustness base strategy semantics derived from request.",
    )
    base_strategy_validation = strategy_validator.validate_spec(base_strategy_spec)
    base_runtime_context = build_strategy_compile_runtime_context(
        dataset_version=dataset_version,
        start=request.start,
        end=request.end,
        execution_model="next_open",
        run_time_utc="16:00",
        commission_bps=request.commission_bps,
        slippage_bps=request.slippage_bps,
        auto_round_lot=request.auto_round_lot,
        provenance_mode="user_requested",
    )
    base_strategy_compilation = build_strategy_compilation_plan(
        base_strategy_spec,
        base_strategy_validation,
        runtime_context=base_runtime_context,
    )
    base_request = build_strategy_backtest_request(
        strategy_id=request.strategy_id,
        strategy_version=request.strategy_version,
        market=request.market.upper(),
        runtime_context=base_runtime_context,
        constraints={
            "strategy_family": request.strategy_family,
            "rebalance": request.rebalance,
            "lookback_days": request.lookback_days,
            "signal_threshold": request.signal_threshold,
            "position_sizing": request.position_sizing,
            "risk_budget": request.risk_budget,
            "max_position": request.max_position,
            "leverage_limit": request.leverage_limit,
            "auto_round_lot": request.auto_round_lot,
        },
        strategy_validation=base_strategy_validation,
        strategy_compilation=base_strategy_compilation,
    )
    multipliers: list[float] = [max(0.0, float(value)) for value in request.cost_multipliers]
    if not any(abs(value - 1.0) <= 1e-9 for value in multipliers):
        multipliers.append(1.0)
    if not any(abs(value - 2.0) <= 1e-9 for value in multipliers):
        multipliers.append(2.0)
    normalized_multipliers = tuple(dict.fromkeys(sorted(multipliers)))
    meta_config = MetaBacktestConfig(
        cost_multipliers=normalized_multipliers,
        lookback_values=tuple(request.lookback_grid) if request.lookback_grid else None,
        threshold_values=tuple(request.threshold_grid) if request.threshold_grid else None,
        rebalance_values=tuple(request.rebalance_grid) if request.rebalance_grid else None,
        min_variants=6,
        max_variants=request.max_variants,
    )
    runner = BacktestRunner(
        dataset_registry=_dataset_registry(),
        run_registry=_run_registry(),
        audit_store=_audit_store(),
        report_root=settings.data_root,
    )
    meta_runner = MetaBacktestRunner(runner)
    trace_id = uuid4()
    session_id = str(request.session_id or "").strip()
    request_token = str(request.request_token or "").strip()
    tm = _task_manager()
    parent_task = tm.create(
        task_type="robustness.run",
        message="planning variants",
        status="queued",
        meta={
            "market": request.market.upper(),
            "strategy_id": request.strategy_id,
            "strategy_version": request.strategy_version,
            "variant_total": 0,
            "session_id": session_id,
            "request_token": request_token,
        },
    )
    logger.info("robustness.run parent_task created: %s", parent_task.task_id)
    _emit_task_state("task.created", trace_id, parent_task, role="parent")

    child_task_map: dict[str, UUID] = {}
    child_task_ids: list[str] = []
    completed_children = 0
    planned_variants: list[dict[str, Any]] = []

    def _update_parent_progress(*, progress: int, message: str, stage: str) -> None:
        parent = tm.update(
            parent_task.task_id,
            status="running" if progress < 100 else "done",
            progress=max(0, min(100, progress)),
            message=message,
        )
        _emit_task_state(
            "task.progress" if progress < 100 else "task.done",
            trace_id,
            parent,
            role="parent",
            stage=stage,
            parent_task_id=str(parent_task.task_id),
            variant_done=completed_children,
            variant_total=len(planned_variants),
        )

    def _on_meta_progress(event: dict[str, Any]) -> None:
        nonlocal completed_children
        phase = str(event.get("phase", "")).strip().lower()
        variant_id = str(event.get("variant_id", "")).strip()
        child_task_id = child_task_map.get(variant_id)
        if phase == "variant.start" and child_task_id is not None:
            child = tm.update(
                child_task_id,
                status="running",
                progress=12,
                message=f"running: {event.get('scenario', '')}",
            )
            _emit_task_state(
                "task.progress",
                trace_id,
                child,
                role="child",
                parent_task_id=str(parent_task.task_id),
                variant_id=variant_id,
            )
            return
        if phase == "variant.done" and child_task_id is not None:
            run_id = str(event.get("run_id", ""))
            metrics = event.get("metrics")
            action_regime_details = event.get("action_regime_details")
            attribution_execution_details = event.get("attribution_execution_details")
            control_optimizer_details = event.get("control_optimizer_details")
            control_action_deep_details = event.get("control_action_deep_details")
            child = tm.update(
                child_task_id,
                status="done",
                progress=100,
                message=f"done: {event.get('scenario', '')}",
                result={
                    "metrics": metrics if isinstance(metrics, dict) else {},
                    "action_regime_details": action_regime_details if isinstance(action_regime_details, dict) else None,
                    "attribution_execution_details": (
                        attribution_execution_details if isinstance(attribution_execution_details, dict) else None
                    ),
                    "control_optimizer_details": (
                        control_optimizer_details if isinstance(control_optimizer_details, dict) else None
                    ),
                    "control_action_deep_details": (
                        control_action_deep_details if isinstance(control_action_deep_details, dict) else None
                    ),
                },
                result_ref={
                    "run_id": run_id,
                    "report_id": run_id,
                    "open_path": f"/reports/{run_id}" if run_id else "",
                },
            )
            _emit_task_state(
                "task.done",
                trace_id,
                child,
                role="child",
                parent_task_id=str(parent_task.task_id),
                variant_id=variant_id,
            )
            completed_children += 1
            total = max(1, len(planned_variants))
            progress = min(90, 10 + int((completed_children / total) * 78))
            _update_parent_progress(
                progress=progress,
                message=f"{completed_children}/{len(planned_variants)} variants completed",
                stage="variants.running",
            )
            return
        if phase == "variants.summary":
            _update_parent_progress(
                progress=92,
                message=f"{completed_children}/{len(planned_variants)} variants completed; building summary",
                stage="variants.summary",
            )
            return
        if phase == "regime.start":
            _update_parent_progress(progress=94, message="running regime slices", stage="regime.start")
            return
        if phase == "regime.done":
            count = int(event.get("count", 0) or 0)
            _update_parent_progress(progress=96, message=f"regime slices done ({count})", stage="regime.done")
            return
        if phase == "stress.start":
            _update_parent_progress(progress=97, message="running stress scenarios", stage="stress.start")
            return
        if phase == "stress.done":
            count = int(event.get("count", 0) or 0)
            _update_parent_progress(progress=98, message=f"stress scenarios done ({count})", stage="stress.done")
            return
        if phase == "finalize":
            _update_parent_progress(progress=99, message="finalizing robustness report", stage="finalize")

    try:
        parent_task = tm.update(
            parent_task.task_id,
            status="running",
            progress=2,
            message="planning robustness variants",
        )
        _emit_task_state(
            "task.progress",
            trace_id,
            parent_task,
            role="parent",
            parent_task_id=str(parent_task.task_id),
            stage="variants.plan",
            variant_done=0,
            variant_total=0,
        )
        planned_variants = meta_runner.plan_variants(base_request, meta_config)
        parent_task = tm.update(
            parent_task.task_id,
            status="running",
            progress=5,
            message=f"queued {len(planned_variants)} variants",
            meta={
                **(tm.get(parent_task.task_id).meta if tm.get(parent_task.task_id) else {}),
                "variant_total": len(planned_variants),
            },
        )
        _emit_task_state(
            "task.progress",
            trace_id,
            parent_task,
            role="parent",
            parent_task_id=str(parent_task.task_id),
            variant_done=0,
            variant_total=len(planned_variants),
        )
        for idx, plan in enumerate(planned_variants):
            child = tm.create(
                task_type="robustness.variant",
                message=f"queued: {plan.get('scenario', '')}",
                parent_task_id=parent_task.task_id,
                status="queued",
                meta={
                    "variant_id": str(plan.get("variant_id", "")),
                    "group": str(plan.get("group", "")),
                    "scenario": str(plan.get("scenario", "")),
                    "variant_index": idx + 1,
                    "variant_total": len(planned_variants),
                    "session_id": session_id,
                    "request_token": request_token,
                },
            )
            variant_key = str(plan.get("variant_id", f"variant_{idx + 1}"))
            child_task_map[variant_key] = child.task_id
            child_task_ids.append(str(child.task_id))
            _emit_task_state(
                "task.created",
                trace_id,
                child,
                role="child",
                parent_task_id=str(parent_task.task_id),
                variant_id=variant_key,
            )
        if settings.task_force_error:
            raise RuntimeError("forced task failure via OPENFINANCE_TASK_FORCE_ERROR=true")
        robustness = meta_runner.run(base_request, meta_config, progress_callback=_on_meta_progress)
    except Exception as ex:
        logger.exception("robustness.run failed: parent_task_id=%s", parent_task.task_id)
        parent_error = tm.update(
            parent_task.task_id,
            status="error",
            progress=100,
            message="robustness failed",
            error=str(ex),
        )
        _emit_task_state(
            "task.error",
            trace_id,
            parent_error,
            role="parent",
            parent_task_id=str(parent_task.task_id),
        )
        for child_id in child_task_ids:
            child_uuid = UUID(child_id)
            row = tm.get(child_uuid)
            if row is None or row.status == "done":
                continue
            child_error = tm.update(
                child_uuid,
                status="error",
                progress=100,
                message="cancelled due to parent failure",
                error=str(ex),
            )
            _emit_task_state(
                "task.error",
                trace_id,
                child_error,
                role="child",
                parent_task_id=str(parent_task.task_id),
            )
        raise

    summary_ref = f"/reports?tab=robustness&robustness_id={robustness.robustness_id}"
    parent_done = tm.update(
        parent_task.task_id,
        status="done",
        progress=100,
        message=f"{completed_children}/{len(planned_variants)} variants completed",
        result={
            "robustness_id": robustness.robustness_id,
            "variant_count": robustness.summary.variant_count,
            "summary": robustness.summary.model_dump(mode="json"),
            "outcome_summary": robustness.outcome_summary.model_dump(mode="json") if robustness.outcome_summary else None,
            "result_details": robustness.result_details.model_dump(mode="json") if robustness.result_details else None,
            "report": robustness.model_dump(mode="json"),
        },
        result_ref={
            "report_id": robustness.robustness_id,
            "open_path": summary_ref,
            "compare_path": "/reports",
        },
        meta={
            **(tm.get(parent_task.task_id).meta if tm.get(parent_task.task_id) else {}),
            "child_task_ids": child_task_ids,
        },
    )
    _emit_task_state(
        "task.done",
        trace_id,
        parent_done,
        role="parent",
        parent_task_id=str(parent_task.task_id),
        variant_done=completed_children,
        variant_total=len(planned_variants),
    )
    logger.info("robustness.run done: parent_task_id=%s robustness_id=%s", parent_task.task_id, robustness.robustness_id)

    robustness = robustness.model_copy(
        update={
            "parent_task_id": str(parent_task.task_id),
            "child_task_ids": child_task_ids,
            "summary_report_ref": summary_ref,
        },
        deep=True,
    )
    _write_audit(
        "workbench.robustness.ready",
        trace_id,
        {
            "parent_task_id": str(parent_task.task_id),
            "child_task_ids": child_task_ids,
            "robustness_id": robustness.robustness_id,
            "dataset_version": robustness.dataset_version,
            "strategy_id": robustness.strategy_id,
            "strategy_version": robustness.strategy_version,
            "variant_count": robustness.summary.variant_count,
            "summary": robustness.summary.model_dump(mode="json"),
            "outcome_summary": robustness.outcome_summary.model_dump(mode="json") if robustness.outcome_summary else None,
            "result_details": robustness.result_details.model_dump(mode="json") if robustness.result_details else None,
        },
    )
    _emit_event(
        "report.robustness.ready",
        trace_id,
        {
            "parent_task_id": str(parent_task.task_id),
            "robustness_id": robustness.robustness_id,
            "variant_count": robustness.summary.variant_count,
            "sharpe_std": robustness.summary.sharpe_std,
            "mdd_worst_case": robustness.summary.mdd_worst_case,
            "summary_report_ref": summary_ref,
        },
    )
    return robustness


@router.post("/reports/robustness/run/submit", response_model=TaskRecord)
def submit_robustness_task(request: RobustnessRunRequest) -> TaskRecord:
    _resolve_dataset_version(request.dataset_version)
    try:
        start_date = date.fromisoformat(request.start)
        end_date = date.fromisoformat(request.end)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail="start/end must be YYYY-MM-DD") from ex
    if start_date >= end_date:
        raise HTTPException(status_code=400, detail="start must be earlier than end")

    request_token = uuid4().hex
    submit_request = request.model_copy(update={"request_token": request_token}, deep=True)

    def _worker() -> None:
        try:
            run_robustness(submit_request)
        except Exception:
            logger.exception("submit_robustness_task worker failed")

    Thread(target=_worker, daemon=True).start()
    return _wait_task_by_request_token(
        task_type="robustness.run",
        request_token=request_token,
        timeout_s=12.0,
    )


@router.get("/strategies", response_model=list[StrategySummary])
def list_strategies() -> list[StrategySummary]:
    rows: list[StrategySummary] = []
    seen_versions: set[str] = set()
    for entry in _strategy_registry().list_entries():
        if entry.version in seen_versions:
            continue
        seen_versions.add(entry.version)
        rows.append(
            StrategySummary(
                strategy_id=entry.strategy_id,
                strategy_version=entry.version,
                status="registered",
                notes=f"{entry.market} {entry.strategy_family} spec",
            )
        )
    for entry in reversed(_run_registry().list_entries()):
        version = str(entry.strategy_version)
        if version in seen_versions:
            continue
        seen_versions.add(version)
        rows.append(
            StrategySummary(
                strategy_id=str(entry.strategy_id),
                strategy_version=version,
                status="derived",
                notes="Derived from run registry",
            )
        )
    if not rows:
        rows.append(
            StrategySummary(
                strategy_id="demo_strategy",
                strategy_version="0.1.0",
                status="placeholder",
                notes="No runs yet",
            )
        )
    return rows


@router.get("/strategies/{strategy_version}", response_model=StrategyDetailResponse)
def get_strategy(strategy_version: str) -> StrategyDetailResponse:
    entry = _strategy_registry().get_by_version(strategy_version)
    if entry is not None:
        return StrategyDetailResponse(
            source="strategy_registry",
            created_at=entry.created_at.isoformat(),
            notes="Registry-backed strategy spec",
            spec=entry.spec,
        )

    entries = [e for e in _run_registry().list_entries() if e.strategy_version == strategy_version]
    if not entries:
        if strategy_version == "0.1.0":
            return StrategyDetailResponse(
                source="placeholder",
                notes="placeholder strategy",
                spec=StrategySpec(
                    strategy_id="demo_strategy",
                    strategy_version=strategy_version,
                    market="US",
                    strategy_family="demo_strategy",
                    rebalance="weekly",
                    lookback_days=20,
                    signal_threshold=0.0,
                    position_sizing="risk_budget",
                    risk_budget="vol_target_10pct",
                    max_position=0.12,
                    stop_loss=0.06,
                    leverage_limit=1.0,
                    factor_weights={},
                    constraints={"max_drawdown_target": 0.1, "position_limit": 0.12},
                    circuit_breaker=_default_strategy_circuit_breaker(0.1),
                    failure_regimes=["range_bound_market", "high_correlation_breakdown", "frequent_gap_moves"],
                    rationale="placeholder strategy",
                ),
            )
        raise HTTPException(status_code=404, detail="strategy not found")
    latest = entries[-1]
    return StrategyDetailResponse(
        source="run_registry_fallback",
        notes="Derived from run registry",
        spec=_strategy_spec_from_run_entry(latest),
    )


@router.get("/factors", response_model=list[FactorSummary])
def list_factors() -> list[FactorSummary]:
    rows = []
    for entry in _factor_registry().list_entries():
        rows.append(
            FactorSummary(
                factor_id=entry.factor_id,
                version=entry.version,
                dataset_schema_version=entry.dataset_schema_version,
                inputs_signature=entry.inputs_signature,
                availability_lag=entry.availability_lag,
                created_at=entry.created_at.isoformat(),
                has_report=_factor_artifact_report(entry.version) is not None,
            )
        )
    return rows


@router.get("/factors/{factor_version}")
def get_factor(factor_version: str) -> dict[str, Any]:
    entry = _factor_registry().get_by_version(factor_version)
    if entry is None:
        raise HTTPException(status_code=404, detail="factor not found")
    report = _factor_artifact_report(factor_version)
    return {
        "factor_id": entry.factor_id,
        "version": entry.version,
        "dataset_schema_version": entry.dataset_schema_version,
        "inputs_signature": entry.inputs_signature,
        "availability_lag": entry.availability_lag,
        "created_at": entry.created_at.isoformat(),
        "spec": entry.spec,
        "report": report,
    }


@router.post("/factors/run", response_model=FactorRunResponse)
def run_formula_factor(request: FactorRunRequest) -> FactorRunResponse:
    dataset_version = _resolve_dataset_version(request.dataset_version)
    failure_conditions = normalize_failure_conditions(
        request.failure_conditions,
        default_applies_to="factor",
    )
    if not failure_conditions:
        raise HTTPException(
            status_code=400,
            detail="failure_conditions is required and must contain at least one item",
        )
    rationale = (request.cost_sensitivity_rationale or "").strip()
    if request.cost_sensitivity_level is None or not rationale:
        raise HTTPException(
            status_code=400,
            detail="cost_sensitivity_level and cost_sensitivity_rationale are required",
        )
    factor_inputs = [
        FactorInput(name=name, source="market", availability_lag=request.availability_lag)
        for name in request.inputs
        if name
    ]
    if not factor_inputs:
        factor_inputs = [FactorInput(name="close", source="market", availability_lag=request.availability_lag)]
    spec = FactorSpec(
        factor_id=request.factor_id,
        factor_version=request.factor_version or "draft",
        description=request.description,
        inputs=factor_inputs,
        params={
            "formula": request.formula,
            "lookback_days": request.lookback_days,
            "decay_lags": request.decay_lags,
            "universe": request.universe,
        },
        failure_conditions=failure_conditions,
        cost_sensitivity=CostSensitivity(
            level=request.cost_sensitivity_level,
            rationale=rationale,
        ),
        expected_horizon=request.expected_horizon,
        validation_plan=ValidationPlan(
            in_sample_start="2023-01-01",
            in_sample_end="2023-12-31",
            out_sample_start="2024-01-01",
            out_sample_end="2024-12-31",
        ),
    )
    trace_id = uuid4()
    session_id = str(request.session_id or "").strip()
    request_token = str(request.request_token or "").strip()
    tm = _task_manager()
    parent_task = tm.create(
        task_type="factor.run",
        message="queued",
        status="queued",
        meta={
            "factor_id": request.factor_id,
            "factor_version": request.factor_version or spec.factor_version,
            "dataset_version": dataset_version,
            "session_id": session_id,
            "request_token": request_token,
        },
    )
    _emit_task_state("task.created", trace_id, parent_task, role="parent")
    try:
        parent_running = tm.update(
            parent_task.task_id,
            status="running",
            progress=40,
            message="running factor validation and compute",
        )
        _emit_task_state("task.progress", trace_id, parent_running, role="parent", stage="factor.run")
        result = _factor_engine().run(
            factor_spec=spec,
            dataset_version=dataset_version,
            factor_version=request.factor_version,
            seed=request.seed,
        )
    except ValueError as ex:
        parent_error = tm.update(
            parent_task.task_id,
            status="error",
            progress=100,
            message="factor run failed",
            error=str(ex),
        )
        _emit_task_state("task.error", trace_id, parent_error, role="parent")
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    except Exception as ex:
        logger.exception("factor.run failed: parent_task_id=%s", parent_task.task_id)
        parent_error = tm.update(
            parent_task.task_id,
            status="error",
            progress=100,
            message="factor run failed",
            error=str(ex),
        )
        _emit_task_state("task.error", trace_id, parent_error, role="parent")
        raise

    response = FactorRunResponse(
        factor_id=result.factor_id,
        factor_version=result.factor_version,
        dataset_version=result.dataset_version,
        artifact_path=result.artifact_path,
        cached=result.cached,
        report=result.report.model_dump(mode="json"),
    )
    parent_done = tm.update(
        parent_task.task_id,
        status="done",
        progress=100,
        message="factor ready",
        result=response.model_dump(mode="json"),
        result_ref={
            "factor_version": result.factor_version,
            "open_path": f"/factors?factor_version={result.factor_version}",
            "compare_path": "/factors",
        },
    )
    _emit_task_state("task.done", trace_id, parent_done, role="parent")
    _write_audit(
        "factor.health_report.linked",
        trace_id,
        {
            "parent_task_id": str(parent_task.task_id),
            "factor_id": result.factor_id,
            "factor_version": result.factor_version,
            "dataset_version": result.dataset_version,
            "factor_artifact_path": result.artifact_path,
            "health_report_artifact_path": result.report.health_report_artifact_path,
        },
    )
    return response


@router.post("/factors/run/submit", response_model=TaskRecord)
def submit_factor_run_task(request: FactorRunRequest) -> TaskRecord:
    _resolve_dataset_version(request.dataset_version)
    failure_conditions = normalize_failure_conditions(
        request.failure_conditions,
        default_applies_to="factor",
    )
    if not failure_conditions:
        raise HTTPException(
            status_code=400,
            detail="failure_conditions is required and must contain at least one item",
        )
    rationale = (request.cost_sensitivity_rationale or "").strip()
    if request.cost_sensitivity_level is None or not rationale:
        raise HTTPException(
            status_code=400,
            detail="cost_sensitivity_level and cost_sensitivity_rationale are required",
        )

    request_token = uuid4().hex
    submit_request = request.model_copy(update={"request_token": request_token}, deep=True)

    def _worker() -> None:
        try:
            run_formula_factor(submit_request)
        except Exception:
            logger.exception("submit_factor_run_task worker failed")

    Thread(target=_worker, daemon=True).start()
    return _wait_task_by_request_token(task_type="factor.run", request_token=request_token)


@router.post("/factor/multi_market_compare", response_model=FactorMultiMarketCompareResponse)
def compare_factor_multi_market(request: FactorMultiMarketCompareRequest) -> FactorMultiMarketCompareResponse:
    markets = _normalize_markets(request.markets)
    if len(markets) < 2:
        raise HTTPException(status_code=400, detail="at least two valid markets are required")
    try:
        start_date = date.fromisoformat(request.start)
        end_date = date.fromisoformat(request.end)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail="start/end must be YYYY-MM-DD") from ex
    if start_date >= end_date:
        raise HTTPException(status_code=400, detail="start must be earlier than end")

    requested_metrics = _normalize_eval_metrics(request.eval_metrics)
    specs = _resolve_factor_specs_for_compare(request)
    compare_id = f"fmmc_{uuid4().hex[:12]}"
    trace_id = uuid4()
    session_id = str(request.session_id or "").strip()
    request_token = str(request.request_token or "").strip()
    tm = _task_manager()

    total_variants = max(1, len(specs) * len(markets))
    parent_task = tm.create(
        task_type="factor.multi_market_compare",
        message="queued",
        status="queued",
        meta={
            "compare_id": compare_id,
            "market_count": len(markets),
            "variant_total": total_variants,
            "session_id": session_id,
            "request_token": request_token,
        },
    )
    _emit_task_state("task.created", trace_id, parent_task, role="parent", compare_id=compare_id)
    parent_running = tm.update(
        parent_task.task_id,
        status="running",
        progress=5,
        message=f"queued {total_variants} variants",
    )
    _emit_task_state(
        "task.progress",
        trace_id,
        parent_running,
        role="parent",
        compare_id=compare_id,
        variant_done=0,
        variant_total=total_variants,
    )

    per_market_metrics: list[FactorMarketMetricRow] = []
    per_market_decay_curves: list[FactorMarketDecayCurve] = []
    child_task_map: dict[tuple[int, str], UUID] = {}
    child_task_ids: list[str] = []
    dataset_registry = _dataset_registry()
    factor_engine = _factor_engine()
    planned_specs: list[FactorSpec] = [_with_universe_override(raw_spec, request.universe) for raw_spec in specs]

    variant_index = 0
    for spec_idx, spec in enumerate(planned_specs):
        for market in markets:
            variant_index += 1
            child = tm.create(
                task_type="factor.multi_market_compare.variant",
                message=f"queued: {market} / {spec.factor_version}",
                parent_task_id=parent_task.task_id,
                status="queued",
                meta={
                    "variant_index": variant_index,
                    "variant_total": total_variants,
                    "market": market,
                    "factor_id": spec.factor_id,
                    "factor_version": spec.factor_version,
                    "compare_id": compare_id,
                    "session_id": session_id,
                    "request_token": request_token,
                },
            )
            child_task_map[(spec_idx, market)] = child.task_id
            child_task_ids.append(str(child.task_id))
            _emit_task_state(
                "task.created",
                trace_id,
                child,
                role="child",
                parent_task_id=str(parent_task.task_id),
                compare_id=compare_id,
            )

    completed_variants = 0
    try:
        for spec_idx, spec in enumerate(planned_specs):
            cost_level = spec.cost_sensitivity.level.value if spec.cost_sensitivity else "medium"
            cost_multiplier = _cost_sensitivity_multiplier(cost_level)
            for market_idx, market in enumerate(markets):
                child_task_id = child_task_map[(spec_idx, market)]
                child_running = tm.update(
                    child_task_id,
                    status="running",
                    progress=20,
                    message=f"preparing dataset: {market} / {spec.factor_version}",
                )
                _emit_task_state(
                    "task.progress",
                    trace_id,
                    child_running,
                    role="child",
                    parent_task_id=str(parent_task.task_id),
                    compare_id=compare_id,
                )

                symbol = request.symbol_map.get(market) or _default_symbol_for_market(market)
                dataset = MockDataFactory().generate(
                    MockDatasetConfig(
                        dataset_id=f"{compare_id}_{spec_idx}_{market.lower()}",
                        market=market,
                        symbol=symbol,
                        start_date=start_date,
                        end_date=end_date,
                        seed=request.seed + (spec_idx * 101) + market_idx,
                    )
                )
                dataset_entry = dataset_registry.register(dataset)
                child_running = tm.update(
                    child_task_id,
                    status="running",
                    progress=60,
                    message=f"running factor engine: {market} / {spec.factor_version}",
                )
                _emit_task_state(
                    "task.progress",
                    trace_id,
                    child_running,
                    role="child",
                    parent_task_id=str(parent_task.task_id),
                    compare_id=compare_id,
                )
                result = factor_engine.run(
                    factor_spec=spec,
                    dataset_version=dataset_entry.dataset_version,
                    factor_version=spec.factor_version,
                    seed=request.seed + (spec_idx * 31) + market_idx,
                )
                report = result.report
                decay_ratio, half_life_lag, _, _ = _decay_profile(report.decay_curve)
                avg_spread_bps = _market_avg_spread_bps(dataset)
                estimated_cost_pressure = round(
                    (avg_spread_bps / 10000.0) * max(0.0, float(report.turnover_proxy)) * cost_multiplier,
                    8,
                )
                oos_gap = round(float(report.in_sample_ic_mean) - float(report.out_sample_ic_mean), 6)

                metric_row = FactorMarketMetricRow(
                    market=market,
                    factor_id=result.factor_id,
                    factor_version=result.factor_version,
                    dataset_version=result.dataset_version,
                    ic_mean=round(float(report.ic_mean), 6),
                    rank_ic_mean=round(float(report.rank_ic_mean), 6),
                    coverage=round(float(report.coverage), 6),
                    turnover_proxy=round(float(report.turnover_proxy), 6),
                    in_sample_ic_mean=round(float(report.in_sample_ic_mean), 6),
                    out_sample_ic_mean=round(float(report.out_sample_ic_mean), 6),
                    oos_gap=oos_gap,
                    avg_spread_bps=avg_spread_bps,
                    decay_ratio=round(decay_ratio, 6),
                    decay_half_life_lag=int(half_life_lag),
                    estimated_cost_pressure=estimated_cost_pressure,
                    cost_sensitivity_level=cost_level,
                )
                per_market_metrics.append(metric_row)
                per_market_decay_curves.append(
                    FactorMarketDecayCurve(
                        market=market,
                        factor_id=result.factor_id,
                        factor_version=result.factor_version,
                        points=[
                            {"lag": int(point.lag), "ic": float(point.ic)}
                            for point in report.decay_curve
                        ],
                    )
                )
                child_done = tm.update(
                    child_task_id,
                    status="done",
                    progress=100,
                    message=f"done: {market} / {spec.factor_version}",
                    result=metric_row.model_dump(mode="json"),
                    result_ref={
                        "factor_version": result.factor_version,
                        "open_path": f"/factors?factor_version={result.factor_version}",
                    },
                )
                _emit_task_state(
                    "task.done",
                    trace_id,
                    child_done,
                    role="child",
                    parent_task_id=str(parent_task.task_id),
                    compare_id=compare_id,
                )
                completed_variants += 1
                parent_progress = min(95, 5 + int((completed_variants / total_variants) * 88))
                parent_running = tm.update(
                    parent_task.task_id,
                    status="running",
                    progress=parent_progress,
                    message=f"{completed_variants}/{total_variants} variants completed",
                )
                _emit_task_state(
                    "task.progress",
                    trace_id,
                    parent_running,
                    role="parent",
                    compare_id=compare_id,
                    variant_done=completed_variants,
                    variant_total=total_variants,
                )
    except Exception as ex:
        logger.exception("factor.multi_market_compare failed: parent_task_id=%s", parent_task.task_id)
        parent_error = tm.update(
            parent_task.task_id,
            status="error",
            progress=100,
            message="factor multi-market compare failed",
            error=str(ex),
        )
        _emit_task_state("task.error", trace_id, parent_error, role="parent", compare_id=compare_id)
        for child_id in child_task_ids:
            child_uuid = UUID(child_id)
            child = tm.get(child_uuid)
            if child is None or child.status == "done":
                continue
            child_error = tm.update(
                child_uuid,
                status="error",
                progress=100,
                message="cancelled due to parent failure",
                error=str(ex),
            )
            _emit_task_state(
                "task.error",
                trace_id,
                child_error,
                role="child",
                parent_task_id=str(parent_task.task_id),
                compare_id=compare_id,
            )
        if isinstance(ex, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=str(ex)) from ex

    summary_insights = _build_factor_compare_insights(per_market_metrics)
    _write_audit(
        "workbench.factor.multi_market.compare",
        trace_id,
        {
            "parent_task_id": str(parent_task.task_id),
            "compare_id": compare_id,
            "requested_metrics": requested_metrics,
            "row_count": len(per_market_metrics),
            "markets": markets,
            "factor_versions": [spec.factor_version for spec in specs],
            "summary_insights": summary_insights,
        },
    )
    _emit_event(
        "report.factor.multi_market.ready",
        trace_id,
        {
            "parent_task_id": str(parent_task.task_id),
            "compare_id": compare_id,
            "row_count": len(per_market_metrics),
            "market_count": len(markets),
        },
        session_id=session_id or "workbench",
    )

    response = FactorMultiMarketCompareResponse(
        compare_id=compare_id,
        requested_metrics=requested_metrics,
        per_market_metrics=per_market_metrics,
        per_market_decay_curves=per_market_decay_curves,
        summary_insights=summary_insights,
        parent_task_id=str(parent_task.task_id),
        child_task_ids=child_task_ids,
    )
    parent_done = tm.update(
        parent_task.task_id,
        status="done",
        progress=100,
        message=f"{completed_variants}/{total_variants} variants completed",
        result=response.model_dump(mode="json"),
        result_ref={
            "report_id": compare_id,
            "open_path": f"/factors?compare_id={compare_id}",
            "compare_path": "/factors",
        },
        meta={
            **(tm.get(parent_task.task_id).meta if tm.get(parent_task.task_id) else {}),
            "child_task_ids": child_task_ids,
        },
    )
    _emit_task_state(
        "task.done",
        trace_id,
        parent_done,
        role="parent",
        compare_id=compare_id,
        variant_done=completed_variants,
        variant_total=total_variants,
    )
    return response


@router.post("/factor/multi_market_compare/submit", response_model=TaskRecord)
def submit_factor_multi_market_compare_task(request: FactorMultiMarketCompareRequest) -> TaskRecord:
    markets = _normalize_markets(request.markets)
    if len(markets) < 2:
        raise HTTPException(status_code=400, detail="at least two valid markets are required")
    try:
        start_date = date.fromisoformat(request.start)
        end_date = date.fromisoformat(request.end)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail="start/end must be YYYY-MM-DD") from ex
    if start_date >= end_date:
        raise HTTPException(status_code=400, detail="start must be earlier than end")
    _resolve_factor_specs_for_compare(request)

    request_token = uuid4().hex
    submit_request = request.model_copy(update={"request_token": request_token}, deep=True)

    def _worker() -> None:
        try:
            compare_factor_multi_market(submit_request)
        except Exception:
            logger.exception("submit_factor_multi_market_compare_task worker failed")

    Thread(target=_worker, daemon=True).start()
    return _wait_task_by_request_token(task_type="factor.multi_market_compare", request_token=request_token)


@router.get("/runs", response_model=list[RunSummary])
def list_runs() -> list[RunSummary]:
    rows: list[RunSummary] = []
    for entry in _run_registry().list_entries():
        report_path = Path(entry.report_path)
        metrics = {}
        if report_path.exists():
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            metrics = payload.get("metrics", {})
        req = entry.request
        rows.append(
            RunSummary(
                run_id=str(entry.run_id),
                audit_trace_id=str(entry.audit_trace_id),
                dataset_version=entry.dataset_version,
                strategy_id=entry.strategy_id,
                strategy_version=entry.strategy_version,
                market=str(entry.market or req.get("market", "US")),
                start=str(req.get("start", "")),
                end=str(req.get("end", "")),
                sharpe=float(metrics.get("sharpe")) if metrics.get("sharpe") is not None else None,
                max_drawdown=float(metrics.get("max_drawdown")) if metrics.get("max_drawdown") is not None else None,
            )
        )
    return list(reversed(rows))


@router.get("/runs/{run_id}", response_model=BacktestReport)
def get_run(run_id: str) -> BacktestReport:
    return get_report(run_id)


@router.get("/run/{run_id}", response_model=BacktestReport)
def get_run_alias(run_id: str) -> BacktestReport:
    return get_report(run_id)


@router.get("/audit", response_model=list[AuditSummary])
def list_audit(trace_id: str | None = Query(default=None)) -> list[AuditSummary]:
    rows = _audit_store().list_all()
    if trace_id:
        rows = [row for row in rows if str(row.trace_id) == trace_id]
    return [
        AuditSummary(
            trace_id=str(row.trace_id),
            run_id=str(row.run_id) if row.run_id else None,
            event_type=row.event_type,
            payload=row.payload,
            created_at=row.created_at.isoformat(),
        )
        for row in rows[-500:]
    ]
