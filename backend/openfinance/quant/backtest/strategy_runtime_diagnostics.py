from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return None


def _count_rows_by_key(rows: Any, *, key: str) -> tuple[int, dict[str, int]]:
    if not isinstance(rows, list):
        return 0, {}
    counts: dict[str, int] = {}
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        total += 1
        name = str(row.get(key) or "unknown").strip() or "unknown"
        counts[name] = counts.get(name, 0) + 1
    return total, counts


class StrategyRuntimeCostModelSummary(BaseModel):
    commission_bps: float | None = None
    slippage_bps: float | None = None


class StrategyRuntimeMarketRulesSummary(BaseModel):
    market: str = ""
    t_plus_one: bool | None = None
    lot_size: float | None = None
    supports_fractional_qty: bool | None = None
    min_notional: float | None = None
    is_24x7: bool | None = None


class StrategyRuntimeRiskManagementSummary(BaseModel):
    regime_vol_window: int | None = None
    regime_vol_threshold: float | None = None
    regime_exposure_scale_high_vol: float | None = None
    regime_pause_new_positions: bool | None = None
    drawdown_limit: float | None = None
    stop_trading_triggered: bool | None = None
    failure_condition_block_triggered: bool | None = None
    circuit_breaker_enabled: bool | None = None
    circuit_breaker_trigger_count: int = 0


class StrategyRuntimePortfolioOptimizationSummary(BaseModel):
    optimizer: str | None = None
    optimizer_universe_size: int = 0
    covariance_window: int | None = None
    max_position_weight: float | None = None
    max_gross_leverage: float | None = None
    max_sector_exposure: float | None = None
    sector_neutral: bool | None = None


class StrategyRuntimeBudgetDeviationSummary(BaseModel):
    mean_l1: float | None = None
    max_l1: float | None = None
    observations: int = 0


class StrategyRuntimeActionCounts(BaseModel):
    risk_action_count: int = 0
    risk_actions_by_type: dict[str, int] = Field(default_factory=dict)
    constraint_action_count: int = 0
    constraint_actions_by_type: dict[str, int] = Field(default_factory=dict)
    optimizer_diagnostic_count: int = 0
    rejected_order_count: int = 0
    failure_event_count: int = 0
    regime_period_count: int = 0


class StrategyRuntimeDiagnosticsResult(BaseModel):
    schema_version: str = "strategy_runtime_diagnostics.v1"
    diagnostics_object: Literal["BacktestReport", "RestoreReportHeader"] = "BacktestReport"
    execution_model: str = ""
    cost_model: StrategyRuntimeCostModelSummary = Field(default_factory=StrategyRuntimeCostModelSummary)
    market_rules: StrategyRuntimeMarketRulesSummary = Field(default_factory=StrategyRuntimeMarketRulesSummary)
    risk_management: StrategyRuntimeRiskManagementSummary = Field(default_factory=StrategyRuntimeRiskManagementSummary)
    portfolio_optimization: StrategyRuntimePortfolioOptimizationSummary = Field(default_factory=StrategyRuntimePortfolioOptimizationSummary)
    budget_deviation: StrategyRuntimeBudgetDeviationSummary = Field(default_factory=StrategyRuntimeBudgetDeviationSummary)
    action_counts: StrategyRuntimeActionCounts = Field(default_factory=StrategyRuntimeActionCounts)
    notes: str | None = None
    summary: str = ""


class StrategyCompareDiffRow(BaseModel):
    market: str
    run_id: str
    dataset_version: str
    sharpe: float | None = None
    max_drawdown: float | None = None
    turnover: float | None = None
    reject_count: int | None = None
    cost_drag: float | None = None
    sharpe_diff_vs_baseline: float | None = None
    max_drawdown_diff_vs_baseline: float | None = None
    turnover_diff_vs_baseline: float | None = None
    warning_count: int = 0
    highest_warning_severity: str | None = None


class StrategyCompareWarningSummary(BaseModel):
    market: str
    warning_count: int = 0
    highest_warning_severity: str | None = None
    warning_codes: list[str] = Field(default_factory=list)


class StrategyCompareResultDetails(BaseModel):
    schema_version: str = "strategy_compare_result_details.v1"
    result_object: Literal["MultiMarketCompareResponse"] = "MultiMarketCompareResponse"
    compare_id: str
    baseline_market: str
    diff_rows: list[StrategyCompareDiffRow] = Field(default_factory=list)
    warning_summaries: list[StrategyCompareWarningSummary] = Field(default_factory=list)
    summary: str = ""


class StrategyRobustnessVariantResultRow(BaseModel):
    variant_id: str
    group: str
    scenario: str
    run_id: str
    commission_bps: float | None = None
    slippage_bps: float | None = None
    sharpe: float | None = None
    max_drawdown: float | None = None
    total_return: float | None = None
    cost_drag: float | None = None
    turnover: float | None = None


class StrategyRobustnessResultDetails(BaseModel):
    schema_version: str = "strategy_robustness_result_details.v1"
    result_object: Literal["RobustnessReport"] = "RobustnessReport"
    robustness_id: str
    variant_rows: list[StrategyRobustnessVariantResultRow] = Field(default_factory=list)
    regime_metric_count: int = 0
    stress_metric_count: int = 0
    best_variant_id: str | None = None
    worst_variant_id: str | None = None
    summary: str = ""


def parse_strategy_runtime_diagnostics_result(
    raw: StrategyRuntimeDiagnosticsResult | dict[str, Any] | None,
) -> StrategyRuntimeDiagnosticsResult | None:
    if raw is None:
        return None
    if isinstance(raw, StrategyRuntimeDiagnosticsResult):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return StrategyRuntimeDiagnosticsResult.model_validate(raw)
    except ValidationError:
        return None


def parse_strategy_compare_result_details(
    raw: StrategyCompareResultDetails | dict[str, Any] | None,
) -> StrategyCompareResultDetails | None:
    if raw is None:
        return None
    if isinstance(raw, StrategyCompareResultDetails):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return StrategyCompareResultDetails.model_validate(raw)
    except ValidationError:
        return None


def parse_strategy_robustness_result_details(
    raw: StrategyRobustnessResultDetails | dict[str, Any] | None,
) -> StrategyRobustnessResultDetails | None:
    if raw is None:
        return None
    if isinstance(raw, StrategyRobustnessResultDetails):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return StrategyRobustnessResultDetails.model_validate(raw)
    except ValidationError:
        return None


def build_strategy_runtime_diagnostics_result(
    *,
    diagnostics_object: Literal["BacktestReport", "RestoreReportHeader"],
    diagnostics: dict[str, Any] | None,
) -> StrategyRuntimeDiagnosticsResult:
    payload = diagnostics if isinstance(diagnostics, dict) else {}
    cost_model = payload.get("cost_model") if isinstance(payload.get("cost_model"), dict) else {}
    market_rules = payload.get("market_rules") if isinstance(payload.get("market_rules"), dict) else {}
    risk_management = payload.get("risk_management") if isinstance(payload.get("risk_management"), dict) else {}
    portfolio_optimization = (
        payload.get("portfolio_optimization") if isinstance(payload.get("portfolio_optimization"), dict) else {}
    )
    budget_deviation = payload.get("budget_deviation") if isinstance(payload.get("budget_deviation"), dict) else {}
    failure_condition_checks = (
        payload.get("failure_condition_checks") if isinstance(payload.get("failure_condition_checks"), dict) else {}
    )
    circuit_breaker = (
        risk_management.get("circuit_breaker") if isinstance(risk_management.get("circuit_breaker"), dict) else {}
    )
    risk_action_count, risk_actions_by_type = _count_rows_by_key(payload.get("risk_actions"), key="action")
    constraint_action_count, constraint_actions_by_type = _count_rows_by_key(
        payload.get("constraint_actions"),
        key="action",
    )
    optimizer_diagnostic_count = len(payload.get("optimizer_diagnostics")) if isinstance(payload.get("optimizer_diagnostics"), list) else 0
    rejected_order_count = len(payload.get("rejected_orders")) if isinstance(payload.get("rejected_orders"), list) else 0
    regime_period_count = len(payload.get("regime_periods")) if isinstance(payload.get("regime_periods"), list) else 0
    failure_event_count = len(failure_condition_checks.get("events")) if isinstance(failure_condition_checks.get("events"), list) else 0

    result = StrategyRuntimeDiagnosticsResult(
        diagnostics_object=diagnostics_object,
        execution_model=str(payload.get("execution_model") or ""),
        cost_model=StrategyRuntimeCostModelSummary(
            commission_bps=_to_float(cost_model.get("commission_bps")),
            slippage_bps=_to_float(cost_model.get("base_slippage_bps", cost_model.get("slippage_bps"))),
        ),
        market_rules=StrategyRuntimeMarketRulesSummary(
            market=str(market_rules.get("market") or ""),
            t_plus_one=_to_bool(market_rules.get("t_plus_one")),
            lot_size=_to_float(market_rules.get("lot_size")),
            supports_fractional_qty=_to_bool(market_rules.get("supports_fractional_qty")),
            min_notional=_to_float(market_rules.get("min_notional")),
            is_24x7=_to_bool(market_rules.get("is_24x7")),
        ),
        risk_management=StrategyRuntimeRiskManagementSummary(
            regime_vol_window=_to_int(risk_management.get("regime_vol_window")),
            regime_vol_threshold=_to_float(risk_management.get("regime_vol_threshold")),
            regime_exposure_scale_high_vol=_to_float(risk_management.get("regime_exposure_scale_high_vol")),
            regime_pause_new_positions=_to_bool(risk_management.get("regime_pause_new_positions")),
            drawdown_limit=_to_float(risk_management.get("drawdown_limit")),
            stop_trading_triggered=_to_bool(risk_management.get("stop_trading_triggered")),
            failure_condition_block_triggered=_to_bool(risk_management.get("failure_condition_block_triggered")),
            circuit_breaker_enabled=_to_bool(circuit_breaker.get("enabled")),
            circuit_breaker_trigger_count=_to_int(circuit_breaker.get("trigger_count")) or 0,
        ),
        portfolio_optimization=StrategyRuntimePortfolioOptimizationSummary(
            optimizer=str(portfolio_optimization.get("optimizer") or "") or None,
            optimizer_universe_size=len(portfolio_optimization.get("optimizer_universe")) if isinstance(portfolio_optimization.get("optimizer_universe"), list) else 0,
            covariance_window=_to_int(portfolio_optimization.get("covariance_window")),
            max_position_weight=_to_float(portfolio_optimization.get("max_position_weight")),
            max_gross_leverage=_to_float(portfolio_optimization.get("max_gross_leverage")),
            max_sector_exposure=_to_float(portfolio_optimization.get("max_sector_exposure")),
            sector_neutral=_to_bool(portfolio_optimization.get("sector_neutral")),
        ),
        budget_deviation=StrategyRuntimeBudgetDeviationSummary(
            mean_l1=_to_float(budget_deviation.get("mean_l1")),
            max_l1=_to_float(budget_deviation.get("max_l1")),
            observations=_to_int(budget_deviation.get("observations")) or 0,
        ),
        action_counts=StrategyRuntimeActionCounts(
            risk_action_count=risk_action_count,
            risk_actions_by_type=risk_actions_by_type,
            constraint_action_count=constraint_action_count,
            constraint_actions_by_type=constraint_actions_by_type,
            optimizer_diagnostic_count=optimizer_diagnostic_count,
            rejected_order_count=rejected_order_count,
            failure_event_count=failure_event_count,
            regime_period_count=regime_period_count,
        ),
        notes=str(payload.get("notes") or "").strip() or None,
    )

    summary_parts: list[str] = []
    if result.execution_model:
        summary_parts.append(f"execution_model={result.execution_model}")
    if result.portfolio_optimization.optimizer:
        summary_parts.append(f"optimizer={result.portfolio_optimization.optimizer}")
    if result.action_counts.risk_action_count:
        summary_parts.append(f"risk_actions={result.action_counts.risk_action_count}")
    if result.action_counts.constraint_action_count:
        summary_parts.append(f"constraints={result.action_counts.constraint_action_count}")
    if result.action_counts.rejected_order_count:
        summary_parts.append(f"rejected_orders={result.action_counts.rejected_order_count}")
    if result.risk_management.stop_trading_triggered:
        summary_parts.append("stop_trading=true")
    if result.risk_management.failure_condition_block_triggered:
        summary_parts.append("failure_block=true")
    if result.risk_management.circuit_breaker_trigger_count:
        summary_parts.append(f"circuit_breaker_triggers={result.risk_management.circuit_breaker_trigger_count}")
    if result.notes:
        summary_parts.append(result.notes)
    result.summary = "; ".join(summary_parts)
    return result


def build_strategy_compare_result_details(
    *,
    compare_id: str,
    baseline_market: str,
    diff_rows: list[dict[str, Any]],
    market_warnings: dict[str, list[Any]] | None = None,
) -> StrategyCompareResultDetails:
    warning_rows: list[StrategyCompareWarningSummary] = []
    for market, rows in (market_warnings or {}).items():
        entries = rows if isinstance(rows, list) else []
        codes = [
            str(item.get("code") or "").strip()
            for item in entries
            if isinstance(item, dict) and str(item.get("code") or "").strip()
        ]
        severities = [
            str(item.get("severity") or "").strip()
            for item in entries
            if isinstance(item, dict) and str(item.get("severity") or "").strip()
        ]
        highest = None
        for level in ("high", "medium", "low"):
            if level in severities:
                highest = level
                break
        warning_rows.append(
            StrategyCompareWarningSummary(
                market=str(market).upper(),
                warning_count=len(entries),
                highest_warning_severity=highest,
                warning_codes=sorted(set(codes)),
            )
        )

    typed_rows = [
        StrategyCompareDiffRow(
            market=str(row.get("market") or ""),
            run_id=str(row.get("run_id") or ""),
            dataset_version=str(row.get("dataset_version") or ""),
            sharpe=_to_float(row.get("sharpe")),
            max_drawdown=_to_float(row.get("max_drawdown")),
            turnover=_to_float(row.get("turnover")),
            reject_count=_to_int(row.get("reject_count")),
            cost_drag=_to_float(row.get("cost_drag")),
            sharpe_diff_vs_baseline=_to_float(row.get("sharpe_diff_vs_baseline")),
            max_drawdown_diff_vs_baseline=_to_float(row.get("max_drawdown_diff_vs_baseline")),
            turnover_diff_vs_baseline=_to_float(row.get("turnover_diff_vs_baseline")),
            warning_count=_to_int(row.get("warning_count")) or 0,
            highest_warning_severity=str(row.get("highest_warning_severity") or "").strip() or None,
        )
        for row in diff_rows
        if isinstance(row, dict)
    ]
    summary_parts = [f"markets={len(typed_rows)}", f"baseline={baseline_market}"]
    warning_total = sum(item.warning_count for item in warning_rows)
    if warning_total:
        summary_parts.append(f"warnings={warning_total}")
    return StrategyCompareResultDetails(
        compare_id=compare_id,
        baseline_market=baseline_market,
        diff_rows=typed_rows,
        warning_summaries=warning_rows,
        summary="; ".join(summary_parts),
    )


def build_strategy_robustness_result_details(
    *,
    robustness_id: str,
    variant_rows: list[dict[str, Any]],
    regime_metric_count: int,
    stress_metric_count: int,
    best_variant_id: str | None = None,
    worst_variant_id: str | None = None,
) -> StrategyRobustnessResultDetails:
    typed_rows = [
        StrategyRobustnessVariantResultRow(
            variant_id=str(row.get("variant_id") or ""),
            group=str(row.get("group") or ""),
            scenario=str(row.get("scenario") or ""),
            run_id=str(row.get("run_id") or ""),
            commission_bps=_to_float(row.get("commission_bps")),
            slippage_bps=_to_float(row.get("slippage_bps")),
            sharpe=_to_float(row.get("sharpe")),
            max_drawdown=_to_float(row.get("max_drawdown")),
            total_return=_to_float(row.get("total_return")),
            cost_drag=_to_float(row.get("cost_drag")),
            turnover=_to_float(row.get("turnover")),
        )
        for row in variant_rows
        if isinstance(row, dict)
    ]
    summary_parts = [f"variants={len(typed_rows)}"]
    if regime_metric_count:
        summary_parts.append(f"regimes={regime_metric_count}")
    if stress_metric_count:
        summary_parts.append(f"stress={stress_metric_count}")
    return StrategyRobustnessResultDetails(
        robustness_id=robustness_id,
        variant_rows=typed_rows,
        regime_metric_count=max(0, int(regime_metric_count)),
        stress_metric_count=max(0, int(stress_metric_count)),
        best_variant_id=best_variant_id,
        worst_variant_id=worst_variant_id,
        summary="; ".join(summary_parts),
    )
