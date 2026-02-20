import json
import statistics
import time
from datetime import date
from functools import lru_cache
from pathlib import Path
from threading import Thread
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from openfinance.core.audit import AuditLogEntry, FileAuditStore
from openfinance.core.config import settings
from openfinance.core.events import event_bus
from openfinance.core.tasks import TaskManager, TaskRecord
from openfinance.data.mock_factory import MockDataFactory, MockDatasetConfig
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.backtest.migration import MigrationChecker, MigrationWarning
from openfinance.quant.backtest.meta_runner import MetaBacktestConfig, MetaBacktestRunner
from openfinance.quant.backtest.report import BacktestRequest, BacktestReport, CostModel
from openfinance.quant.backtest.robustness import RobustnessReport
from openfinance.quant.backtest.run_registry import RunRegistry
from openfinance.quant.backtest.runner import BacktestRunner
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

router = APIRouter(prefix="/workbench", tags=["workbench"])


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


class MarketCompareRow(BaseModel):
    market: str
    run_id: str
    dataset_version: str
    strategy_version: str
    metrics: dict[str, Any]


class MultiMarketCompareResponse(BaseModel):
    compare_id: str
    baseline_market: str
    strategy_spec: dict[str, Any]
    rows: list[MarketCompareRow]
    diff_table: list[dict[str, Any]]
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


@lru_cache(maxsize=1)
def _task_manager() -> TaskManager:
    return TaskManager()


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


def _run_dataset_job(task_id: UUID, trace_id: UUID, req: GenerateDatasetRequest) -> None:
    tm = _task_manager()
    try:
        tm.update(task_id, status="running", progress=10, message="preparing config")
        _write_audit("task.progress", trace_id, {"task_id": str(task_id), "progress": 10})
        _emit_event("task.progress", trace_id, {"task_id": str(task_id), "progress": 10})
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
        tm.update(task_id, progress=55, message="generating dataset")
        _write_audit("task.progress", trace_id, {"task_id": str(task_id), "progress": 55})
        _emit_event("task.progress", trace_id, {"task_id": str(task_id), "progress": 55})
        dataset = MockDataFactory().generate(config)
        entry = _dataset_registry().register(dataset)

        result = {
            "dataset_id": entry.dataset_id,
            "dataset_version": entry.dataset_version,
            "artifact_path": entry.artifact_path,
        }
        tm.update(task_id, status="done", progress=100, message="dataset ready", result=result)
        _write_audit("task.done", trace_id, {"task_id": str(task_id), "result": result})
        _emit_event("task.done", trace_id, {"task_id": str(task_id), "result": result})
    except Exception as ex:
        tm.update(task_id, status="failed", progress=100, message="dataset failed", error=str(ex))
        _write_audit("task.done", trace_id, {"task_id": str(task_id), "error": str(ex)})
        _emit_event("task.done", trace_id, {"task_id": str(task_id), "error": str(ex)})


def _run_backtest_job(task_id: UUID, trace_id: UUID, req: RunBacktestTaskRequest) -> None:
    tm = _task_manager()
    try:
        tm.update(task_id, status="running", progress=15, message="loading dataset")
        _write_audit("task.progress", trace_id, {"task_id": str(task_id), "progress": 15})
        _emit_event("task.progress", trace_id, {"task_id": str(task_id), "progress": 15})
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
        tm.update(task_id, progress=65, message="running backtest")
        _write_audit("task.progress", trace_id, {"task_id": str(task_id), "progress": 65})
        _emit_event("task.progress", trace_id, {"task_id": str(task_id), "progress": 65})
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
        tm.update(task_id, status="done", progress=100, message="backtest complete", result=result)
        _write_audit("report.ready", trace_id, {"task_id": str(task_id), "result": result}, report.run_id)
        _write_audit("task.done", trace_id, {"task_id": str(task_id), "result": result}, report.run_id)
        _emit_event("report.ready", trace_id, {"task_id": str(task_id), "result": result})
        _emit_event("task.done", trace_id, {"task_id": str(task_id), "result": result})
    except Exception as ex:
        tm.update(task_id, status="failed", progress=100, message="backtest failed", error=str(ex))
        _write_audit("task.done", trace_id, {"task_id": str(task_id), "error": str(ex)})
        _emit_event("task.done", trace_id, {"task_id": str(task_id), "error": str(ex)})


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
    task = _task_manager().create(task_type="dataset.generate", message="task created")
    trace_id = uuid4()
    _write_audit("task.created", trace_id, {"task_id": str(task.task_id), "type": task.task_type})
    _emit_event("task.created", trace_id, {"task_id": str(task.task_id), "type": task.task_type})
    Thread(target=_run_dataset_job, args=(task.task_id, trace_id, request), daemon=True).start()
    return task


@router.post("/backtests/run", response_model=TaskRecord)
def create_backtest_task(request: RunBacktestTaskRequest) -> TaskRecord:
    task = _task_manager().create(task_type="backtest.run", message="task created")
    trace_id = uuid4()
    _write_audit("task.created", trace_id, {"task_id": str(task.task_id), "type": task.task_type})
    _emit_event("task.created", trace_id, {"task_id": str(task.task_id), "type": task.task_type})
    Thread(target=_run_backtest_job, args=(task.task_id, trace_id, request), daemon=True).start()
    return task


@router.get("/tasks", response_model=list[TaskRecord])
def list_tasks() -> list[TaskRecord]:
    return _task_manager().list_tasks()


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
        return BacktestReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404, detail="report not found")


@router.post("/reports/multi-market/compare", response_model=MultiMarketCompareResponse)
def compare_multi_market(request: MultiMarketCompareRequest) -> MultiMarketCompareResponse:
    markets = _normalize_markets(request.markets)
    if len(markets) < 2:
        raise HTTPException(status_code=400, detail="at least two valid markets are required")

    compare_id = f"mmc_{uuid4().hex[:12]}"
    trace_id = uuid4()
    migration_checker = MigrationChecker()
    runner = BacktestRunner(
        dataset_registry=_dataset_registry(),
        run_registry=_run_registry(),
        audit_store=_audit_store(),
        report_root=settings.data_root,
    )
    strategy_spec = {
        "strategy_id": request.strategy_id,
        "strategy_version": request.strategy_version,
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
    }
    try:
        start_date = date.fromisoformat(request.start)
        end_date = date.fromisoformat(request.end)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail="start/end must be YYYY-MM-DD") from ex
    if start_date >= end_date:
        raise HTTPException(status_code=400, detail="start must be earlier than end")
    rows: list[MarketCompareRow] = []
    market_warnings: dict[str, list[MigrationWarning]] = {}
    flat_warnings: list[MigrationWarning] = []

    for idx, market in enumerate(markets):
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
        backtest_request = BacktestRequest(
            dataset_version=dataset_entry.dataset_version,
            strategy_id=request.strategy_id,
            strategy_version=request.strategy_version,
            market=market,
            start=request.start,
            end=request.end,
            cost_model=CostModel(
                commission_bps=request.commission_bps,
                slippage_bps=request.slippage_bps,
            ),
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
        )
        current_warnings = migration_checker.check(backtest_request.constraints, market, rules)
        market_warnings[market] = current_warnings
        flat_warnings.extend(current_warnings)
        report = runner.run(backtest_request)
        rows.append(
            MarketCompareRow(
                market=market,
                run_id=str(report.run_id),
                dataset_version=report.dataset_version,
                strategy_version=report.strategy_version,
                metrics=report.metrics,
            )
        )

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

    _write_audit(
        "workbench.multi_market.compare",
        trace_id,
        {
            "compare_id": compare_id,
            "baseline_market": baseline.market,
            "strategy_spec": strategy_spec,
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
        },
    )
    return MultiMarketCompareResponse(
        compare_id=compare_id,
        baseline_market=baseline.market,
        strategy_spec=strategy_spec,
        rows=rows,
        diff_table=diff_table,
        migration_warnings=flat_warnings,
        market_warnings=market_warnings,
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

    base_request = BacktestRequest(
        dataset_version=dataset_version,
        strategy_id=request.strategy_id,
        strategy_version=request.strategy_version,
        market=request.market.upper(),
        start=request.start,
        end=request.end,
        cost_model=CostModel(
            commission_bps=request.commission_bps,
            slippage_bps=request.slippage_bps,
        ),
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
    robustness = meta_runner.run(base_request, meta_config)
    trace_id = uuid4()
    _write_audit(
        "workbench.robustness.ready",
        trace_id,
        {
            "robustness_id": robustness.robustness_id,
            "dataset_version": robustness.dataset_version,
            "strategy_id": robustness.strategy_id,
            "strategy_version": robustness.strategy_version,
            "variant_count": robustness.summary.variant_count,
            "summary": robustness.summary.model_dump(mode="json"),
        },
    )
    _emit_event(
        "report.robustness.ready",
        trace_id,
        {
            "robustness_id": robustness.robustness_id,
            "variant_count": robustness.summary.variant_count,
            "sharpe_std": robustness.summary.sharpe_std,
            "mdd_worst_case": robustness.summary.mdd_worst_case,
        },
    )
    return robustness


@router.get("/strategies", response_model=list[StrategySummary])
def list_strategies() -> list[StrategySummary]:
    versions = sorted({entry.strategy_version for entry in _run_registry().list_entries()})
    rows = [
        StrategySummary(
            strategy_id="demo_strategy",
            strategy_version=version,
            status="registered",
            notes="Generated from run registry",
        )
        for version in versions
    ]
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


@router.get("/strategies/{strategy_version}")
def get_strategy(strategy_version: str) -> dict[str, Any]:
    def _default_circuit_breaker(threshold: float = 0.1) -> dict[str, Any]:
        return {
            "enabled": True,
            "rule": {
                "type": "drawdown",
                "threshold": float(max(0.0, threshold)),
                "cool_down_days": 5,
            },
        }

    def _normalize_circuit_breaker(raw: Any, *, drawdown_threshold: float) -> dict[str, Any]:
        allowed = {"consecutive_losses", "drawdown", "vol_spike"}
        fallback = _default_circuit_breaker(drawdown_threshold)
        if not isinstance(raw, dict):
            return fallback
        enabled = raw.get("enabled")
        if not isinstance(enabled, bool):
            enabled = fallback["enabled"]
        rule = raw.get("rule")
        if not isinstance(rule, dict):
            return {**fallback, "enabled": enabled}
        rule_type = str(rule.get("type", "drawdown")).strip().lower()
        if rule_type not in allowed:
            rule_type = "drawdown"
        threshold = rule.get("threshold")
        if not isinstance(threshold, (int, float)):
            threshold = fallback["rule"]["threshold"]
        cool_down = rule.get("cool_down_days")
        if not isinstance(cool_down, (int, float)):
            cool_down = fallback["rule"]["cool_down_days"]
        return {
            "enabled": enabled,
            "rule": {
                "type": rule_type,
                "threshold": float(max(0.0, float(threshold))),
                "cool_down_days": int(max(0, int(cool_down))),
            },
        }

    def _normalize_failure_regimes(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return ["range_bound_market", "high_correlation_breakdown", "frequent_gap_moves"]
        rows = [str(item).strip() for item in raw if str(item).strip()]
        if not rows:
            return ["range_bound_market", "high_correlation_breakdown", "frequent_gap_moves"]
        return list(dict.fromkeys(rows))[:8]

    entries = [e for e in _run_registry().list_entries() if e.strategy_version == strategy_version]
    if not entries:
        if strategy_version == "0.1.0":
            return {
                "strategy_id": "demo_strategy",
                "strategy_version": strategy_version,
                "market": "US",
                "rebalance": "weekly",
                "risk_constraints": {"max_drawdown_target": 0.1, "position_limit": 0.12},
                "circuit_breaker": _default_circuit_breaker(0.1),
                "failure_regimes": ["range_bound_market", "high_correlation_breakdown", "frequent_gap_moves"],
                "notes": "placeholder strategy",
            }
        raise HTTPException(status_code=404, detail="strategy not found")
    latest = entries[-1]
    req = latest.request
    constraints = req.get("constraints", {})
    drawdown_threshold = float(constraints.get("max_drawdown_target", 0.1) or 0.1)
    circuit_breaker = _normalize_circuit_breaker(
        constraints.get("circuit_breaker"),
        drawdown_threshold=drawdown_threshold,
    )
    failure_regimes = _normalize_failure_regimes(constraints.get("failure_regimes"))
    return {
        "strategy_id": latest.strategy_id,
        "strategy_version": latest.strategy_version,
        "market": req.get("market", "US"),
        "rebalance": constraints.get("rebalance", "weekly"),
        "strategy_family": constraints.get("strategy_family", latest.strategy_id),
        "lookback_days": constraints.get("lookback_days", 20),
        "risk_budget": constraints.get("risk_budget", "vol_target_10pct"),
        "risk_constraints": {
            "max_drawdown_target": constraints.get("max_drawdown_target", 0.1),
            "position_limit": constraints.get("max_position", 0.12),
            "turnover_target": constraints.get("turnover_target", 0.3),
            "leverage_limit": constraints.get("leverage_limit", 1.0),
        },
        "circuit_breaker": circuit_breaker,
        "failure_regimes": failure_regimes,
        "notes": "derived from run registry",
    }


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
    try:
        result = _factor_engine().run(
            factor_spec=spec,
            dataset_version=dataset_version,
            factor_version=request.factor_version,
            seed=request.seed,
        )
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    trace_id = uuid4()
    _write_audit(
        "factor.health_report.linked",
        trace_id,
        {
            "factor_id": result.factor_id,
            "factor_version": result.factor_version,
            "dataset_version": result.dataset_version,
            "factor_artifact_path": result.artifact_path,
            "health_report_artifact_path": result.report.health_report_artifact_path,
        },
    )
    return FactorRunResponse(
        factor_id=result.factor_id,
        factor_version=result.factor_version,
        dataset_version=result.dataset_version,
        artifact_path=result.artifact_path,
        cached=result.cached,
        report=result.report.model_dump(mode="json"),
    )


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

    per_market_metrics: list[FactorMarketMetricRow] = []
    per_market_decay_curves: list[FactorMarketDecayCurve] = []
    dataset_registry = _dataset_registry()
    factor_engine = _factor_engine()

    for spec_idx, raw_spec in enumerate(specs):
        spec = _with_universe_override(raw_spec, request.universe)
        cost_level = spec.cost_sensitivity.level.value if spec.cost_sensitivity else "medium"
        cost_multiplier = _cost_sensitivity_multiplier(cost_level)
        for market_idx, market in enumerate(markets):
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

            per_market_metrics.append(
                FactorMarketMetricRow(
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
            )
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

    summary_insights = _build_factor_compare_insights(per_market_metrics)
    _write_audit(
        "workbench.factor.multi_market.compare",
        trace_id,
        {
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
            "compare_id": compare_id,
            "row_count": len(per_market_metrics),
            "market_count": len(markets),
        },
    )
    return FactorMultiMarketCompareResponse(
        compare_id=compare_id,
        requested_metrics=requested_metrics,
        per_market_metrics=per_market_metrics,
        per_market_decay_curves=per_market_decay_curves,
        summary_insights=summary_insights,
    )


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
                market=str(req.get("market", "US")),
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
