import hashlib
import json
import math
import statistics
from datetime import date
from pathlib import Path
from typing import Any

from openfinance.core.audit import AuditLogEntry, FileAuditStore
from openfinance.core.events import event_bus
from openfinance.data.contracts.dataset import GeneratedDataset, OHLCVBar
from openfinance.data.contracts.instruments import Instrument, TradingHours
from openfinance.data.registry import DatasetRegistry
from openfinance.markets.plugins import build_market_rules_provider
from openfinance.quant.backtest.report import (
    BacktestOrder,
    BacktestReport,
    BacktestRequest,
    BacktestTrade,
    FactorVersionRef,
    PositionSnapshot,
)
from openfinance.quant.checks import (
    FailureConditionCheckRegistry,
    normalize_failure_conditions,
)
from openfinance.quant.backtest.run_registry import RunRegistry, RunRegistryEntry
from openfinance.quant.portfolio import (
    ConstraintInput,
    ConstraintSolver,
    OptimizerInput,
    PortfolioOptimizer,
    RiskBudgetOptimizerV2,
    RiskParityOptimizer,
    ScoreBasedOptimizer,
)


class BacktestRunner:
    def __init__(
        self,
        dataset_registry: DatasetRegistry,
        run_registry: RunRegistry,
        audit_store: FileAuditStore,
        report_root: str,
    ) -> None:
        self.dataset_registry = dataset_registry
        self.run_registry = run_registry
        self.audit_store = audit_store
        self.report_root = Path(report_root)
        self.report_root.mkdir(parents=True, exist_ok=True)
        self.market_rules = build_market_rules_provider()
        self.constraint_solver = ConstraintSolver()
        self.portfolio_optimizers: dict[str, PortfolioOptimizer] = {
            "score_based": ScoreBasedOptimizer(),
            "risk_parity": RiskParityOptimizer(),
            "risk_budget_v2": RiskBudgetOptimizerV2(),
        }
        self.failure_check_registry = FailureConditionCheckRegistry.default_registry()

    def run(self, request: BacktestRequest) -> BacktestReport:
        dataset_entry = self.dataset_registry.get_entry(request.dataset_version)
        if dataset_entry is None:
            raise ValueError(f"dataset_version not found: {request.dataset_version}")

        dataset = GeneratedDataset.model_validate_json(
            Path(dataset_entry.artifact_path).read_text(encoding="utf-8")
        )
        report = self._build_report(request, dataset)

        report_path = self.report_root / f"{report.run_id}.json"
        report_path.write_text(
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.run_registry.append(
            RunRegistryEntry(
                run_id=report.run_id,
                dataset_version=request.dataset_version,
                strategy_id=request.strategy_id,
                strategy_version=request.strategy_version,
                audit_trace_id=report.audit_trace_id,
                request=request.model_dump(mode="json"),
                report_path=str(report_path),
            )
        )
        self.audit_store.append(
            AuditLogEntry(
                run_id=report.run_id,
                trace_id=report.audit_trace_id,
                event_type="backtest.run.completed",
                payload={
                    "dataset_version": request.dataset_version,
                    "strategy_id": request.strategy_id,
                    "strategy_version": request.strategy_version,
                    "report_path": str(report_path),
                },
            )
        )
        rejected_orders = [order for order in report.orders if order.status == "rejected"]
        for order in rejected_orders:
            self.audit_store.append(
                AuditLogEntry(
                    run_id=report.run_id,
                    trace_id=report.audit_trace_id,
                    event_type="backtest.order.rejected",
                    payload={
                        "order_id": str(order.order_id),
                        "time": order.time.isoformat(),
                        "instrument": order.instrument,
                        "side": order.side,
                        "qty": order.qty,
                        "reason": order.reason,
                        "reason_code": order.reason_code,
                        "reason_msg": order.reason_msg,
                        "user_friendly_msg": order.user_friendly_msg,
                    },
                )
            )
        risk_actions = report.diagnostics.get("risk_actions", [])
        if isinstance(risk_actions, list):
            for action in risk_actions:
                if not isinstance(action, dict):
                    continue
                self.audit_store.append(
                    AuditLogEntry(
                        run_id=report.run_id,
                        trace_id=report.audit_trace_id,
                        event_type="backtest.risk.action",
                        payload=action,
                    )
                )
        constraint_actions = report.diagnostics.get("constraint_actions", [])
        if isinstance(constraint_actions, list):
            for action in constraint_actions:
                if not isinstance(action, dict):
                    continue
                self.audit_store.append(
                    AuditLogEntry(
                        run_id=report.run_id,
                        trace_id=report.audit_trace_id,
                        event_type="backtest.constraint.action",
                        payload=action,
                    )
                )
        return report

    def _build_report(self, request: BacktestRequest, dataset: GeneratedDataset) -> BacktestReport:
        factor_versions, factor_versions_reason = self._resolve_factor_versions(request)
        strategy_decision_payload = self._resolve_strategy_decision(request)
        bars = sorted([bar for bar in dataset.market if not bar.is_missing], key=lambda row: row.ts)
        if len(bars) < 2:
            return BacktestReport(
                dataset_version=request.dataset_version,
                strategy_version=request.strategy_version,
                strategy_decision=strategy_decision_payload,
                factor_versions=factor_versions,
                factor_versions_reason=factor_versions_reason,
                metrics={
                    "total_return": 0.0,
                    "volatility": 0.0,
                    "sharpe": 0.0,
                    "max_drawdown": 0.0,
                    "trade_count": 0,
                    "turnover": 0.0,
                    "cost_drag": 0.0,
                },
                charts=["equity_curve", "drawdown_curve", "monthly_heatmap"],
                diagnostics={
                    "notes": "insufficient market bars",
                    "strategy_decision": strategy_decision_payload,
                    "factor_lineage": {
                        "factor_versions": [row.model_dump(mode="json") for row in factor_versions],
                        "reason": factor_versions_reason,
                    },
                },
            )

        market = str(dataset.generation_config.get("market", request.market or "US")).upper()
        symbol = str(dataset.generation_config.get("symbol", "DEMO"))
        sector = str(dataset.generation_config.get("sector") or self._default_sector(symbol))
        rules = self.market_rules.get(market)
        initial_cash = float(request.constraints.get("initial_cash", 1_000_000.0) or 1_000_000.0)
        lookback = int(request.constraints.get("lookback_days", 20) or 20)
        threshold = float(request.constraints.get("signal_threshold", 0.0) or 0.0)
        family = str(request.constraints.get("strategy_family", request.strategy_id)).lower()
        rebalance = str(request.constraints.get("rebalance", "weekly")).lower()
        position_sizing = str(request.constraints.get("position_sizing", "risk_budget")).lower()
        risk_budget = str(request.constraints.get("risk_budget", "vol_target_10pct")).lower()
        default_optimizer = "risk_budget_v2" if position_sizing in {"risk_budget", "vol_target"} else (
            "risk_parity" if family == "risk_parity" else "score_based"
        )
        optimizer_name = str(
            request.constraints.get("portfolio_optimizer", request.constraints.get("optimizer", default_optimizer))
        ).lower()
        optimizer = self.portfolio_optimizers.get(optimizer_name) or self.portfolio_optimizers["score_based"]
        optimizer_name = optimizer.name
        max_position = float(request.constraints.get("max_position", 0.12) or 0.12)
        leverage_limit = float(request.constraints.get("leverage_limit", 1.0) or 1.0)
        raw_max_position_weight = request.constraints.get("max_position_weight")
        max_position_weight = float(max(1.0, leverage_limit) if raw_max_position_weight is None else raw_max_position_weight)
        raw_max_gross_leverage = request.constraints.get("max_gross_leverage")
        max_gross_leverage = float(leverage_limit if raw_max_gross_leverage is None else raw_max_gross_leverage)
        sector_neutral = bool(request.constraints.get("sector_neutral", False))
        raw_max_sector_exposure = request.constraints.get("max_sector_exposure")
        max_sector_exposure = float(
            max(max_gross_leverage, 1e-6) if raw_max_sector_exposure is None else raw_max_sector_exposure
        )
        execution_model = str(
            request.constraints.get(
                "execution_model",
                request.constraints.get("execution_price", request.execution_model),
            )
        ).lower()
        if execution_model not in {"next_open", "next_close"}:
            execution_model = "next_open"

        lot_size = float(request.constraints.get("lot_size", rules.lot_size()) or rules.lot_size())
        auto_round_lot = bool(request.constraints.get("auto_round_lot", not rules.supports_fractional_qty()))
        commission_bps = float(getattr(request.cost_model, "commission_bps", 0.0) or 0.0)
        base_slippage_bps = float(getattr(request.cost_model, "slippage_bps", 0.0) or 0.0)
        rebalance_step = {"daily": 1, "weekly": 5, "biweekly": 10, "monthly": 21}.get(rebalance, 5)
        budget_scale = self._risk_budget_scale(risk_budget)
        exposure_scalar = max(0.25, min(1.5, (0.5 + max_position * 3.0) * leverage_limit))
        price_limit_pct = rules.price_limit_pct()
        regime_vol_window = int(request.constraints.get("regime_vol_window", 20) or 20)
        regime_vol_threshold = float(request.constraints.get("regime_vol_threshold", 0.03) or 0.03)
        regime_exposure_scale = float(
            request.constraints.get("regime_exposure_scale_high_vol", 0.5) or 0.5
        )
        regime_pause_new_positions = bool(request.constraints.get("regime_pause_new_positions", False))
        raw_dd = request.constraints.get("max_drawdown_target")
        drawdown_limit = max(0.0, float(raw_dd)) if raw_dd is not None else 0.2
        circuit_breaker = self._normalize_circuit_breaker(
            raw=request.constraints.get("circuit_breaker"),
            default_drawdown_limit=drawdown_limit,
        )
        if circuit_breaker["rule"]["type"] == "drawdown":
            drawdown_limit = float(circuit_breaker["rule"]["threshold"])
        optimizer_universe = self._optimizer_universe(symbol=symbol, constraints=request.constraints)
        optimizer_sectors = self._optimizer_sectors(
            symbol=symbol,
            fallback_sector=sector,
            universe=optimizer_universe,
            constraints=request.constraints,
        )
        risk_budget_vector = self._risk_budget_vector(
            universe=optimizer_universe,
            constraints=request.constraints,
            risk_budget_label=risk_budget,
        )
        covariance_window = int(request.constraints.get("cov_lookback_days", lookback) or lookback)
        high_vol_assets = self._string_list(request.constraints.get("high_vol_assets"))
        high_vol_shock_start = int(request.constraints.get("high_vol_shock_start", max(5, len(bars) // 2)) or max(5, len(bars) // 2))
        high_vol_shock_mult = float(request.constraints.get("high_vol_shock_multiplier", 2.5) or 2.5)
        runtime_failure_conditions = self._resolve_failure_conditions(request=request)
        failure_check_interval_bars = int(
            request.constraints.get("failure_check_interval_bars", max(1, rebalance_step)) or max(1, rebalance_step)
        )
        failure_check_interval_bars = max(1, failure_check_interval_bars)

        orders: list[BacktestOrder] = []
        trades: list[BacktestTrade] = []
        positions: list[PositionSnapshot] = []
        equity_curve: list[dict[str, float | int | str]] = []
        rejected_rows: list[dict[str, Any]] = []
        pending_by_fill_idx: dict[int, list[dict[str, Any]]] = {}
        instrument_cashflows: dict[str, dict[str, float]] = {}
        regime_periods: list[dict[str, Any]] = []
        risk_actions: list[dict[str, Any]] = []
        optimizer_diagnostics: list[dict[str, Any]] = []
        constraint_actions: list[dict[str, Any]] = []
        risk_contribution_ts: list[dict[str, Any]] = []
        budget_deviation_values: list[float] = []
        circuit_breaker_trigger_times: list[str] = []
        failure_condition_events: list[dict[str, Any]] = []
        failure_condition_state: dict[str, str] = {}

        cash = initial_cash
        position_lots: list[dict[str, Any]] = []
        turnover_notional = 0.0
        total_commission = 0.0
        total_slippage = 0.0
        peak_equity = initial_cash
        equity_values: list[float] = []
        stop_trading = False
        in_high_vol = False
        active_regime_start: str | None = None
        failure_block_triggered = False

        close_returns = self._returns_from_closes([bar.close for bar in bars])
        cross_returns = self._build_cross_asset_returns(
            bars=bars,
            base_returns=close_returns,
            universe=optimizer_universe,
            primary_symbol=symbol,
            constraints=request.constraints,
            high_vol_assets=high_vol_assets,
            high_vol_shock_start=high_vol_shock_start,
            high_vol_shock_multiplier=high_vol_shock_mult,
        )
        for idx, bar in enumerate(bars):
            position_qty = self._position_qty(position_lots)
            for pending in pending_by_fill_idx.pop(idx, []):
                order: BacktestOrder = pending["order"]
                signed_qty = float(pending["signed_qty"])
                side = "buy" if signed_qty > 0 else "sell"
                base_price = bar.open if execution_model == "next_open" else bar.close

                if price_limit_pct is not None and self._hit_price_limit(side=side, bar=bar, limit_pct=price_limit_pct):
                    order.status = "rejected"
                    self._set_order_reason(
                        order=order,
                        market=market,
                        raw_reason="price_limit_blocked",
                        default_reason_msg="Price limit constraint blocks aggressive fill.",
                    )
                    rejected_rows.append(self._rejected_payload(order))
                    continue

                recent_returns = close_returns[max(0, idx - lookback) : idx + 1]
                slippage_bps = self._dynamic_slippage_bps(
                    base_slippage_bps=base_slippage_bps,
                    spread_bps=bar.spread_bps,
                    recent_returns=recent_returns,
                )
                direction = 1.0 if signed_qty > 0 else -1.0
                fill_price = base_price * (1.0 + direction * slippage_bps / 10000.0)
                fill_qty = abs(signed_qty)
                commission = fill_qty * fill_price * commission_bps / 10000.0
                slippage = fill_qty * abs(fill_price - base_price)

                if signed_qty < 0:
                    sellable_qty = self._sellable_qty(
                        position_lots=position_lots,
                        as_of=bar.ts.date(),
                        t_plus_one=rules.t_plus_one(),
                    )
                    if fill_qty > sellable_qty + 1e-9:
                        order.status = "rejected"
                        self._set_order_reason(
                            order=order,
                            market=market,
                            raw_reason="t_plus_one_blocked" if rules.t_plus_one() else "insufficient_sellable_qty",
                            default_reason_msg="Sell quantity exceeds sellable lots under market settlement rules.",
                        )
                        rejected_rows.append(self._rejected_payload(order))
                        continue

                if signed_qty > 0:
                    cash -= fill_qty * fill_price + commission
                    position_lots.append(
                        {
                            "qty": fill_qty,
                            "price": fill_price,
                            "acquired_date": bar.ts.date(),
                        }
                    )
                else:
                    cash += fill_qty * fill_price - commission
                    self._consume_lots_for_sell(
                        position_lots=position_lots,
                        sell_qty=fill_qty,
                        as_of=bar.ts.date(),
                        t_plus_one=rules.t_plus_one(),
                    )

                total_commission += commission
                total_slippage += slippage
                ledger = instrument_cashflows.setdefault(
                    symbol,
                    {"buy_notional": 0.0, "sell_notional": 0.0, "cost": 0.0, "end_qty": 0.0},
                )
                notional = fill_qty * fill_price
                if signed_qty > 0:
                    ledger["buy_notional"] += notional
                    ledger["end_qty"] += fill_qty
                else:
                    ledger["sell_notional"] += notional
                    ledger["end_qty"] -= fill_qty
                ledger["cost"] += commission + slippage
                position_qty = self._position_qty(position_lots)
                prior_reason = order.reason
                order.status = "filled"
                order.reason_code = "FILLED"
                order.reason_msg = (
                    f"filled@{execution_model}; signal={pending['signal']:.4f}; "
                    f"target_exposure={pending['target_exposure']:.4f}"
                )
                order.user_friendly_msg = "订单已成交。"
                order.reason = f"{prior_reason}; {order.reason_msg}" if prior_reason else order.reason_msg
                trades.append(
                    BacktestTrade(
                        order_id=order.order_id,
                        time=bar.ts,
                        instrument=symbol,
                        side=side,
                        price=round(fill_price, 6),
                        qty=round(fill_qty, 6),
                        commission=round(commission, 6),
                        slippage=round(slippage, 6),
                    )
                )

            position_qty = self._position_qty(position_lots)
            avg_price = self._avg_price(position_lots)
            market_value = position_qty * bar.close
            equity = cash + market_value
            peak_equity = max(peak_equity, equity)
            drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
            unrealized_pnl = (bar.close - avg_price) * position_qty if position_qty != 0 else 0.0
            trailing_returns = close_returns[max(0, idx - regime_vol_window + 1) : idx + 1]
            trailing_vol = statistics.pstdev(trailing_returns) if len(trailing_returns) > 1 else 0.0
            high_vol_now = trailing_vol >= regime_vol_threshold
            if high_vol_now and not in_high_vol:
                in_high_vol = True
                active_regime_start = bar.ts.isoformat()
                risk_actions.append(
                    {
                        "time": bar.ts.isoformat(),
                        "action": "regime_enter_high_vol",
                        "detail": f"rolling_vol={trailing_vol:.6f} threshold={regime_vol_threshold:.6f}",
                    }
                )
            if (not high_vol_now) and in_high_vol:
                in_high_vol = False
                regime_periods.append(
                    {
                        "regime": "high_vol",
                        "start": active_regime_start,
                        "end": bar.ts.isoformat(),
                        "trigger": "rolling_vol_threshold",
                    }
                )
                active_regime_start = None
                risk_actions.append(
                    {
                        "time": bar.ts.isoformat(),
                        "action": "regime_exit_high_vol",
                        "detail": f"rolling_vol={trailing_vol:.6f} threshold={regime_vol_threshold:.6f}",
                    }
                )

            evaluate_failure_checks = (
                bool(runtime_failure_conditions)
                and (
                    idx == 0
                    or (idx % rebalance_step == 0)
                    or (idx % failure_check_interval_bars == 0)
                )
            )
            if evaluate_failure_checks:
                rolling_volume = statistics.fmean(
                    [row.volume for row in bars[max(0, idx - lookback + 1) : idx + 1]]
                )
                rolling_volume_avg = statistics.fmean(
                    [row.volume for row in bars[max(0, idx - max(lookback * 2, 2) + 1) : idx + 1]]
                )
                rolling_spread_avg = statistics.fmean(
                    [row.spread_bps for row in bars[max(0, idx - max(lookback * 2, 2) + 1) : idx + 1]]
                )
                baseline_returns = close_returns[max(0, idx - max(lookback * 3, 5) + 1) : idx + 1]
                baseline_volatility = statistics.pstdev(baseline_returns) if len(baseline_returns) > 1 else trailing_vol
                turnover_proxy = turnover_notional / max(1.0, equity)
                exposure_concentration = abs(market_value) / max(1.0, equity)
                failure_results = self.failure_check_registry.evaluate(
                    conditions=runtime_failure_conditions,
                    context={
                        "market": market,
                        "symbol": symbol,
                        "ts": bar.ts.isoformat(),
                        "rolling_volume": rolling_volume,
                        "rolling_volume_avg": rolling_volume_avg,
                        "spread_bps": bar.spread_bps,
                        "rolling_spread_bps_avg": rolling_spread_avg,
                        "rolling_volatility": trailing_vol,
                        "baseline_volatility": baseline_volatility,
                        "turnover_proxy": turnover_proxy,
                        "exposure_concentration": exposure_concentration,
                    },
                )
                for row in failure_results:
                    prior_level = failure_condition_state.get(row.code)
                    if prior_level == row.level:
                        continue
                    failure_condition_state[row.code] = row.level
                    event_row = {
                        "time": bar.ts.isoformat(),
                        "code": row.code,
                        "level": row.level,
                        "message": row.message,
                        "metrics": row.metrics,
                    }
                    failure_condition_events.append(event_row)
                    if row.level in {"warn", "block"}:
                        risk_actions.append(
                            {
                                "time": bar.ts.isoformat(),
                                "action": f"failure_condition_{row.level.lower()}",
                                "detail": f"{row.code}: {row.message}",
                            }
                        )
                        event_bus.publish(
                            event_type="risk.event",
                            session_id="workbench",
                            payload={
                                "event_type": f"failure_condition_{row.level.lower()}",
                                "severity": "high" if row.level == "block" else "medium",
                                "message": row.message,
                                "source": "backtest_failure_conditions",
                                "metrics": {"code": row.code, **row.metrics},
                            },
                        )
                    if row.level == "block":
                        stop_trading = True
                        failure_block_triggered = True

            if (
                circuit_breaker.get("enabled", True)
                and (not stop_trading)
                and str(circuit_breaker.get("rule", {}).get("type", "drawdown")) == "drawdown"
                and drawdown >= drawdown_limit
            ):
                circuit_breaker_trigger_times.append(bar.ts.isoformat())
                if position_qty > 1e-9:
                    stop_trading, cash, total_commission, total_slippage = self._apply_drawdown_circuit_breaker(
                        bar=bar,
                        symbol=symbol,
                        position_qty=position_qty,
                        execution_model=execution_model,
                        commission_bps=commission_bps,
                        base_slippage_bps=base_slippage_bps,
                        orders=orders,
                        trades=trades,
                        position_lots=position_lots,
                        cash=cash,
                        total_commission=total_commission,
                        total_slippage=total_slippage,
                        close_returns=close_returns,
                        idx=idx,
                        lookback=lookback,
                        instrument_cashflows=instrument_cashflows,
                        risk_actions=risk_actions,
                    )
                else:
                    stop_trading = True
                    risk_actions.append(
                        {
                            "time": bar.ts.isoformat(),
                            "action": "circuit_breaker_stop_trading",
                            "detail": f"drawdown={drawdown:.6f} limit={drawdown_limit:.6f}",
                        }
                    )
                position_qty = self._position_qty(position_lots)
                avg_price = self._avg_price(position_lots)
                market_value = position_qty * bar.close
                equity = cash + market_value
                peak_equity = max(peak_equity, equity)
                drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
                unrealized_pnl = (bar.close - avg_price) * position_qty if position_qty != 0 else 0.0

            equity_values.append(equity)

            equity_curve.append(
                {
                    "x": idx + 1,
                    "ts": bar.ts.isoformat(),
                    "equity": round(equity, 6),
                    "drawdown": round(drawdown, 6),
                }
            )
            positions.append(
                PositionSnapshot(
                    time=bar.ts,
                    instrument=symbol,
                    qty=round(position_qty, 6),
                    avg_price=round(avg_price, 6),
                    market_price=round(bar.close, 6),
                    market_value=round(market_value, 6),
                    cash=round(cash, 6),
                    equity=round(equity, 6),
                    unrealized_pnl=round(unrealized_pnl, 6),
                )
            )

            if idx >= len(bars) - 1:
                continue
            if not (idx == 0 or idx % rebalance_step == 0):
                continue
            if stop_trading:
                continue

            start = max(0, idx - lookback + 1)
            window = close_returns[start : idx + 1] or close_returns[: idx + 1]
            signal = self._signal_for_family(family, window, threshold)
            if position_sizing == "inverse_vol":
                vol = statistics.pstdev(window) if len(window) > 1 else 0.01
                signal *= min(1.5, max(0.4, 0.02 / max(0.002, vol)))
            elif position_sizing == "equal_risk":
                signal *= 0.75
            elif position_sizing == "score_weighted":
                signal *= 0.9

            raw_target_exposure = max(-1.0, min(1.0, signal)) * exposure_scalar * budget_scale
            if high_vol_now:
                raw_target_exposure *= regime_exposure_scale
                risk_actions.append(
                    {
                        "time": bar.ts.isoformat(),
                        "action": "regime_exposure_scaled",
                        "detail": f"scale={regime_exposure_scale:.3f} rolling_vol={trailing_vol:.6f}",
                    }
                )
            cov_start = max(0, idx - covariance_window + 1)
            cross_window = {
                inst: (cross_returns.get(inst, [])[cov_start : idx + 1] or cross_returns.get(inst, [0.0]))
                for inst in optimizer_universe
            }
            covariance = self._covariance_matrix(cross_window, optimizer_universe)
            volatilities = {
                inst: (statistics.pstdev(cross_window.get(inst, [])) if len(cross_window.get(inst, [])) > 1 else 0.01)
                for inst in optimizer_universe
            }
            rolling_vol = float(volatilities.get(symbol, 0.01))
            signal_map = self._signal_map_for_universe(
                base_signal=signal,
                universe=optimizer_universe,
                ts=bar.ts.isoformat(),
            )
            optimizer_result = optimizer.optimize(
                OptimizerInput(
                    scores=signal_map,
                    expected_returns=signal_map,
                    volatilities=volatilities,
                    covariance=covariance,
                    risk_budget=risk_budget_vector,
                    gross_target=abs(raw_target_exposure),
                    constraints={
                        "max_position_weight": max_position_weight,
                        "max_gross_leverage": max_gross_leverage,
                        "allow_short": False,
                        "max_iter": int(request.constraints.get("optimizer_max_iter", 240) or 240),
                        "tol": float(request.constraints.get("optimizer_tol", 1e-4) or 1e-4),
                    },
                )
            )
            optimized_weight = float(optimizer_result.weights.get(symbol, 0.0))
            achieved_budget = {}
            if isinstance(optimizer_result.diagnostics, dict):
                raw_achieved = optimizer_result.diagnostics.get("achieved_budget")
                if isinstance(raw_achieved, dict):
                    achieved_budget = {str(key): float(value) for key, value in raw_achieved.items()}
            deviation_l1 = float(
                optimizer_result.diagnostics.get("budget_deviation_l1", 0.0)
                if isinstance(optimizer_result.diagnostics, dict)
                else 0.0
            )
            budget_deviation_values.append(abs(deviation_l1))
            risk_contribution_ts.append(
                {
                    "time": bar.ts.isoformat(),
                    "target_budget": risk_budget_vector,
                    "achieved_budget": achieved_budget,
                    "weights": {inst: round(float(optimizer_result.weights.get(inst, 0.0)), 8) for inst in optimizer_universe},
                    "deviation_l1": round(abs(deviation_l1), 8),
                }
            )
            optimizer_diagnostics.append(
                {
                    "time": bar.ts.isoformat(),
                    "optimizer": optimizer_name,
                    "symbol": symbol,
                    "signal": round(signal, 6),
                    "raw_target_exposure": round(raw_target_exposure, 6),
                    "optimized_weight": round(optimized_weight, 6),
                    "gross_target": round(abs(raw_target_exposure), 6),
                    "risk_budget_vector": risk_budget_vector,
                    "covariance": covariance,
                    "details": optimizer_result.diagnostics,
                }
            )
            constraint_result = self.constraint_solver.solve(
                ConstraintInput(
                    weights={inst: float(optimizer_result.weights.get(inst, 0.0)) for inst in optimizer_universe},
                    sectors=optimizer_sectors,
                    max_position_weight=max_position_weight,
                    max_gross_leverage=max_gross_leverage,
                    sector_neutral=sector_neutral,
                    max_sector_exposure=max_sector_exposure,
                )
            )
            for action in constraint_result.actions:
                if not isinstance(action, dict):
                    continue
                constraint_actions.append(
                    {
                        "time": bar.ts.isoformat(),
                        "optimizer": optimizer_name,
                        "symbol": symbol,
                        **action,
                    }
                )

            if constraint_result.rejected:
                proposed_notional = raw_target_exposure * equity
                proposed_qty = proposed_notional / bar.close if bar.close > 0 else 0.0
                proposed_qty = (
                    self._round_to_lot(proposed_qty, lot_size=lot_size, fractional=rules.supports_fractional_qty())
                    if auto_round_lot
                    else proposed_qty
                )
                delta_qty = proposed_qty - position_qty
                if abs(delta_qty) >= max(0.0001, lot_size * 0.5):
                    side = "buy" if delta_qty > 0 else "sell"
                    order = BacktestOrder(
                        time=bar.ts,
                        instrument=symbol,
                        side=side,
                        qty=round(abs(delta_qty), 6),
                        order_type="market",
                        status="rejected",
                        reason_code="ORDER_REJECTED",
                        reason_msg="Order rejected by ex-ante constraint solver.",
                        user_friendly_msg="订单未通过事前约束校验。",
                        reason=constraint_result.reason_code or "ex_ante_constraint_reject",
                    )
                    self._set_order_reason(
                        order=order,
                        market=market,
                        raw_reason=constraint_result.reason_code or "ex_ante_constraint_reject",
                        default_reason_msg="Order rejected by ex-ante constraint solver.",
                    )
                    orders.append(order)
                    rejected_rows.append(self._rejected_payload(order))
                continue

            target_exposure = float(constraint_result.weights.get(symbol, 0.0))
            target_notional = target_exposure * equity
            raw_target_qty = target_notional / bar.close if bar.close > 0 else 0.0
            target_qty = (
                self._round_to_lot(raw_target_qty, lot_size=lot_size, fractional=rules.supports_fractional_qty())
                if auto_round_lot
                else raw_target_qty
            )
            if high_vol_now and regime_pause_new_positions and abs(target_qty) > abs(position_qty):
                target_qty = position_qty
                risk_actions.append(
                    {
                        "time": bar.ts.isoformat(),
                        "action": "regime_pause_new_positions",
                        "detail": "high-vol regime blocks exposure increase",
                    }
                )
            delta_qty = target_qty - position_qty
            if abs(delta_qty) < max(0.0001, lot_size * 0.5):
                continue

            side = "buy" if delta_qty > 0 else "sell"
            order_qty = abs(delta_qty)
            order = BacktestOrder(
                time=bar.ts,
                instrument=symbol,
                side=side,
                qty=round(order_qty, 6),
                order_type="market",
                status="submitted",
                reason_code="SUBMITTED",
                reason_msg=f"optimizer={optimizer_name} signal={signal:.4f} target_exposure={target_exposure:.4f}",
                user_friendly_msg="订单已提交，等待撮合成交。",
                reason=f"optimizer={optimizer_name} signal={signal:.4f} target_exposure={target_exposure:.4f}",
            )
            orders.append(order)

            instrument = Instrument(
                instrument_id=f"{market}_{symbol}",
                symbol=symbol,
                asset_class="crypto" if market == "CRYPTO" else "equity",
                venue=market,
                currency="USD",
                tick_size=0.01,
                lot_size=max(lot_size, 0.0001),
                trading_hours=TradingHours(timezone="UTC", sessions=[]),
                meta={"ref_price": str(bar.close)},
            )
            valid = rules.validate_order(instrument=instrument, quantity=order_qty)
            if not valid.accepted:
                order.status = "rejected"
                self._set_order_reason(
                    order=order,
                    market=market,
                    raw_reason=valid.reason or "market_rules_reject",
                    default_reason_msg=f"Order rejected by {market} market rules.",
                )
                rejected_rows.append(self._rejected_payload(order))
                continue

            if side == "sell":
                sellable_qty = self._sellable_qty(
                    position_lots=position_lots,
                    as_of=bar.ts.date(),
                    t_plus_one=rules.t_plus_one(),
                )
                if order_qty > sellable_qty + 1e-9:
                    order.status = "rejected"
                    self._set_order_reason(
                        order=order,
                        market=market,
                        raw_reason="t_plus_one_blocked" if rules.t_plus_one() else "insufficient_sellable_qty",
                        default_reason_msg="Sell quantity exceeds sellable lots under market settlement rules.",
                    )
                    rejected_rows.append(self._rejected_payload(order))
                    continue

            fill_idx = idx + 1
            if market == "JP" and not rules.in_trading_session(bar.ts):
                order.status = "queued"
                self._set_order_reason(
                    order=order,
                    market=market,
                    raw_reason="queued_until_next_session",
                    default_reason_msg="Outside JP trading session, queued to next session.",
                )
                fill_idx = idx + 1

            pending_by_fill_idx.setdefault(fill_idx, []).append(
                {
                    "order": order,
                    "signed_qty": delta_qty,
                    "signal": signal,
                    "target_exposure": target_exposure,
                }
            )
            turnover_notional += order_qty * bar.close

        if active_regime_start is not None:
            regime_periods.append(
                {
                    "regime": "high_vol",
                    "start": active_regime_start,
                    "end": bars[-1].ts.isoformat(),
                    "trigger": "rolling_vol_threshold",
                }
            )

        start_equity = equity_values[0] if equity_values else initial_cash
        end_equity = equity_values[-1] if equity_values else initial_cash
        daily_returns = self._returns_from_equity(equity_values)
        volatility = statistics.pstdev(daily_returns) if len(daily_returns) > 1 else 0.0
        mean_ret = statistics.fmean(daily_returns) if daily_returns else 0.0
        sharpe = (mean_ret / volatility) * math.sqrt(252) if volatility > 0 else 0.0
        total_return = (end_equity / start_equity) - 1.0 if start_equity > 0 else 0.0
        max_drawdown = self._max_drawdown_from_equity(equity_values)
        average_equity = statistics.fmean(equity_values) if equity_values else initial_cash
        turnover = turnover_notional / average_equity if average_equity > 0 else 0.0
        total_cost = total_commission + total_slippage
        cost_drag = total_cost / start_equity if start_equity > 0 else 0.0
        instrument_pnl_contrib, sector_pnl_contrib = self._build_attribution(
            instrument_cashflows=instrument_cashflows,
            instrument_last_price={symbol: bars[-1].close},
            instrument_sector={symbol: sector},
        )

        monthly_returns = self._build_monthly_returns(equity_values)
        trigger_intervals: list[dict[str, Any]] = []
        for start_time in circuit_breaker_trigger_times:
            trigger_intervals.append(
                {
                    "start": start_time,
                    "end": bars[-1].ts.isoformat() if stop_trading else start_time,
                    "reason": "drawdown_threshold_breach",
                }
            )
        circuit_breaker_summary = {
            "enabled": bool(circuit_breaker.get("enabled", True)),
            "rule": dict(circuit_breaker.get("rule", {})),
            "trigger_count": len(circuit_breaker_trigger_times),
            "trigger_intervals": trigger_intervals,
            "execution_support": {
                "drawdown": True,
                "consecutive_losses": False,
                "vol_spike": False,
            },
        }
        budget_dev_mean = statistics.fmean(budget_deviation_values) if budget_deviation_values else 0.0
        budget_dev_max = max(budget_deviation_values) if budget_deviation_values else 0.0
        metrics = {
            "total_return": round(total_return, 6),
            "volatility": round(volatility, 6),
            "sharpe": round(sharpe, 6),
            "max_drawdown": round(max_drawdown, 6),
            "trade_count": len(trades),
            "order_count": len(orders),
            "reject_count": len(rejected_rows),
            "turnover": round(turnover, 6),
            "cost_drag": round(cost_drag, 6),
            "ending_equity": round(end_equity, 6),
            "budget_deviation_mean": round(budget_dev_mean, 6),
            "budget_deviation_max": round(budget_dev_max, 6),
        }
        diagnostics = {
            "lookahead_check": "pass",
            "execution_model": execution_model,
            "cost_model": {
                "commission_bps": commission_bps,
                "base_slippage_bps": base_slippage_bps,
            },
            "market_rules": {
                "market": market,
                "t_plus_one": rules.t_plus_one(),
                "lot_size": lot_size,
                "supports_fractional_qty": rules.supports_fractional_qty(),
                "min_notional": rules.min_notional(),
                "is_24x7": rules.is_24x7(),
            },
            "risk_management": {
                "regime_vol_window": regime_vol_window,
                "regime_vol_threshold": regime_vol_threshold,
                "regime_exposure_scale_high_vol": regime_exposure_scale,
                "regime_pause_new_positions": regime_pause_new_positions,
                "drawdown_limit": drawdown_limit,
                "stop_trading_triggered": stop_trading,
                "failure_condition_block_triggered": failure_block_triggered,
                "circuit_breaker": circuit_breaker_summary,
            },
            "portfolio_optimization": {
                "optimizer": optimizer_name,
                "optimizer_universe": optimizer_universe,
                "covariance_window": covariance_window,
                "risk_budget_vector": risk_budget_vector,
                "max_position_weight": max_position_weight,
                "max_gross_leverage": max_gross_leverage,
                "max_sector_exposure": max_sector_exposure,
                "sector_neutral": sector_neutral,
            },
            "regime_periods": regime_periods,
            "risk_actions": risk_actions,
            "optimizer_diagnostics": optimizer_diagnostics,
            "risk_contribution_ts": risk_contribution_ts,
            "budget_deviation": {
                "mean_l1": round(budget_dev_mean, 6),
                "max_l1": round(budget_dev_max, 6),
                "observations": len(budget_deviation_values),
            },
            "constraint_actions": constraint_actions,
            "failure_condition_checks": {
                "check_interval_bars": failure_check_interval_bars,
                "configured": [row.model_dump(mode="json") for row in runtime_failure_conditions],
                "events": failure_condition_events,
                "last_levels": failure_condition_state,
            },
            "rejected_orders": rejected_rows,
            "instrument_pnl_contrib": instrument_pnl_contrib,
            "sector_pnl_contrib": sector_pnl_contrib,
            "notes": "event-driven backtest with market-rules constraints",
            "request_constraints": request.constraints,
            "evaluation_plan": request.evaluation_plan,
            "series": {"equity_curve": equity_curve, "monthly_returns": monthly_returns},
            "strategy_decision": strategy_decision_payload,
            "factor_lineage": {
                "factor_versions": [row.model_dump(mode="json") for row in factor_versions],
                "reason": factor_versions_reason,
            },
        }

        return BacktestReport(
            dataset_version=request.dataset_version,
            strategy_version=request.strategy_version,
            strategy_decision=strategy_decision_payload,
            factor_versions=factor_versions,
            factor_versions_reason=factor_versions_reason,
            metrics=metrics,
            charts=["equity_curve", "drawdown_curve", "monthly_heatmap", "orders", "trades", "positions"],
            diagnostics=diagnostics,
            evidence_refs=self._coerce_evidence_refs(request.evaluation_plan),
            equity_curve=equity_curve,
            orders=orders,
            trades=trades,
            positions=positions,
            positions_ts=positions,
            cost_breakdown={
                "commission": round(total_commission, 6),
                "slippage": round(total_slippage, 6),
                "commission_sum": round(total_commission, 6),
                "slippage_sum": round(total_slippage, 6),
                "total": round(total_cost, 6),
            },
            attribution={
                "instrument_pnl_contrib": instrument_pnl_contrib,
                "sector_pnl_contrib": sector_pnl_contrib,
            },
        )

    def _resolve_strategy_decision(self, request: BacktestRequest) -> dict[str, Any]:
        rows: list[Any] = []
        if isinstance(request.constraints, dict):
            rows.append(request.constraints.get("strategy_decision"))
        if isinstance(request.evaluation_plan, dict):
            rows.append(request.evaluation_plan.get("strategy_decision"))
        for row in rows:
            if isinstance(row, dict) and row:
                return row
        return {}

    def _resolve_factor_versions(self, request: BacktestRequest) -> tuple[list[FactorVersionRef], str | None]:
        refs: list[FactorVersionRef] = []
        seen: set[tuple[str, str]] = set()

        def _add(factor_id: Any, version: Any) -> None:
            fid = str(factor_id or "").strip()
            ver = str(version or "").strip()
            if not fid or not ver:
                return
            key = (fid, ver)
            if key in seen:
                return
            seen.add(key)
            refs.append(FactorVersionRef(factor_id=fid, version=ver))

        for item in request.factor_versions:
            _add(getattr(item, "factor_id", None), getattr(item, "version", None))

        constraints = request.constraints if isinstance(request.constraints, dict) else {}
        evaluation_plan = request.evaluation_plan if isinstance(request.evaluation_plan, dict) else {}

        self._collect_factor_version_refs(
            refs_add=_add,
            container=constraints,
            fallback_factor_id=request.strategy_id,
        )
        self._collect_factor_version_refs(
            refs_add=_add,
            container=evaluation_plan,
            fallback_factor_id=request.strategy_id,
        )

        if refs:
            return refs, None

        explicit_no_factor = bool(constraints.get("no_factor_strategy")) or bool(evaluation_plan.get("no_factor_strategy"))
        if constraints.get("use_factors") is False:
            explicit_no_factor = True
        if explicit_no_factor:
            return [], "strategy_explicitly_no_factor"

        # Keep lineage non-empty when caller omitted factor references.
        refs.append(FactorVersionRef(factor_id=str(request.strategy_id), version="untracked"))
        return refs, "factor_version_not_provided_fallback"

    def _resolve_failure_conditions(self, *, request: BacktestRequest) -> list[Any]:
        rows: list[Any] = []
        constraints = request.constraints if isinstance(request.constraints, dict) else {}
        evaluation_plan = request.evaluation_plan if isinstance(request.evaluation_plan, dict) else {}
        for container in (constraints, evaluation_plan):
            raw = container.get("failure_conditions")
            rows.extend(normalize_failure_conditions(raw, default_applies_to="strategy"))
        dedup: dict[tuple[str, str], Any] = {}
        for row in rows:
            code = str(getattr(row, "code", "")).strip().upper()
            applies = str(getattr(row, "applies_to", "strategy")).strip().lower()
            if not code:
                continue
            dedup[(code, applies)] = row
        return list(dedup.values())

    def _collect_factor_version_refs(
        self,
        *,
        refs_add: Any,
        container: dict[str, Any],
        fallback_factor_id: str,
    ) -> None:
        raw_refs = container.get("factor_versions")
        if isinstance(raw_refs, list):
            for item in raw_refs:
                if isinstance(item, dict):
                    refs_add(item.get("factor_id"), item.get("version"))
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    refs_add(item[0], item[1])
                elif isinstance(item, str):
                    token = item.strip()
                    if ":" in token:
                        fid, ver = token.split(":", 1)
                        refs_add(fid, ver)
                    else:
                        refs_add(fallback_factor_id, token)

        raw_single = container.get("factor_version")
        if isinstance(raw_single, str) and raw_single.strip():
            refs_add(container.get("factor_id", fallback_factor_id), raw_single)

    def _coerce_evidence_refs(self, evaluation_plan: dict[str, Any]) -> list[str]:
        raw = evaluation_plan.get("evidence_refs")
        if not isinstance(raw, list):
            return []
        refs: list[str] = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                refs.append(item.strip())
        return list(dict.fromkeys(refs))

    def _rejected_payload(self, order: BacktestOrder) -> dict[str, Any]:
        return {
            "order_id": str(order.order_id),
            "time": order.time.isoformat(),
            "side": order.side,
            "qty": order.qty,
            "reason": order.reason,
            "reason_code": order.reason_code,
            "reason_msg": order.reason_msg,
            "user_friendly_msg": order.user_friendly_msg,
        }

    def _set_order_reason(
        self,
        *,
        order: BacktestOrder,
        market: str,
        raw_reason: str,
        default_reason_msg: str,
    ) -> None:
        canonical, user_msg = self._normalize_reason(raw_reason=raw_reason, market=market)
        order.reason = raw_reason
        order.reason_code = canonical
        order.reason_msg = default_reason_msg
        order.user_friendly_msg = user_msg

    def _normalize_reason(self, *, raw_reason: str, market: str) -> tuple[str, str]:
        reason = (raw_reason or "").strip().lower()
        venue = market.upper()
        if reason == "t_plus_one_blocked":
            return "CN_T1_SELL_BLOCKED", "因A股T+1规则，当日买入不可卖出。"
        if reason in {"cn_lot_must_be_100_multiple", "below_cn_min_lot_100"}:
            return "CN_LOT_SIZE", "因A股最小下单单位为100股，下单数量需为100的整数倍。"
        if reason == "price_limit_blocked":
            return "PRICE_LIMIT", "触发涨跌停限制，当前价格无法成交。"
        if reason == "queued_until_next_session":
            return "OUT_OF_SESSION", "当前不在交易时段，订单已排队到下一交易时段。"
        if reason == "below_crypto_min_notional":
            return "CRYPTO_MIN_NOTIONAL", "订单金额低于最小名义金额限制。"
        if reason == "insufficient_sellable_qty":
            return "INSUFFICIENT_SELLABLE_QTY", "可卖数量不足，无法完成卖出。"
        if reason == "jp_lot_must_be_100_multiple":
            return "JP_LOT_SIZE", "日本市场下单数量需满足最小交易单位。"
        if reason in {"invalid_lot_multiple", "below_min_lot"}:
            if venue == "CN":
                return "CN_LOT_SIZE", "因A股最小下单单位为100股，下单数量需为100的整数倍。"
            if venue == "JP":
                return "JP_LOT_SIZE", "日本市场下单数量需满足最小交易单位。"
            return "LOT_SIZE", "下单数量不满足最小交易单位。"
        if reason == "invalid_quantity":
            return "INVALID_QUANTITY", "下单数量无效，请调整后重试。"
        if reason == "market_rules_reject":
            return "MARKET_RULE_REJECT", "订单未通过市场规则校验。"
        if reason == "ex_ante_invalid_max_position_weight":
            return "EX_ANTE_INVALID_MAX_POSITION_WEIGHT", "风控参数 max_position_weight 无效，订单被拒绝。"
        if reason == "ex_ante_invalid_max_gross_leverage":
            return "EX_ANTE_INVALID_MAX_GROSS_LEVERAGE", "风控参数 max_gross_leverage 无效，订单被拒绝。"
        if reason == "ex_ante_invalid_max_sector_exposure":
            return "EX_ANTE_INVALID_MAX_SECTOR_EXPOSURE", "风控参数 max_sector_exposure 无效，订单被拒绝。"
        if reason == "ex_ante_constraint_reject":
            return "EX_ANTE_CONSTRAINT_REJECT", "订单未通过事前约束求解，未发送到交易执行。"
        return "ORDER_REJECTED", "订单被拒绝，请检查市场规则与风控限制。"

    def _apply_drawdown_circuit_breaker(
        self,
        *,
        bar: OHLCVBar,
        symbol: str,
        position_qty: float,
        execution_model: str,
        commission_bps: float,
        base_slippage_bps: float,
        orders: list[BacktestOrder],
        trades: list[BacktestTrade],
        position_lots: list[dict[str, Any]],
        cash: float,
        total_commission: float,
        total_slippage: float,
        close_returns: list[float],
        idx: int,
        lookback: int,
        instrument_cashflows: dict[str, dict[str, float]],
        risk_actions: list[dict[str, Any]],
    ) -> tuple[bool, float, float, float]:
        side = "sell" if position_qty > 0 else "buy"
        qty = abs(position_qty)
        if qty <= 1e-9:
            return True, cash, total_commission, total_slippage
        order = BacktestOrder(
            time=bar.ts,
            instrument=symbol,
            side=side,
            qty=round(qty, 6),
            order_type="market",
            status="filled",
            reason_code="drawdown_circuit_breaker_flatten",
            reason_msg="Drawdown limit breached, flatten and stop trading.",
            reason="drawdown_circuit_breaker_flatten",
        )
        orders.append(order)
        base_price = bar.open if execution_model == "next_open" else bar.close
        recent_returns = close_returns[max(0, idx - lookback) : idx + 1]
        slippage_bps = self._dynamic_slippage_bps(
            base_slippage_bps=base_slippage_bps,
            spread_bps=bar.spread_bps,
            recent_returns=recent_returns,
        )
        direction = -1.0 if side == "sell" else 1.0
        fill_price = base_price * (1.0 + direction * slippage_bps / 10000.0)
        commission = qty * fill_price * commission_bps / 10000.0
        slippage = qty * abs(fill_price - base_price)
        if side == "sell":
            cash += qty * fill_price - commission
            self._consume_lots_for_sell(
                position_lots=position_lots,
                sell_qty=qty,
                as_of=bar.ts.date(),
                t_plus_one=False,
            )
        else:
            cash -= qty * fill_price + commission
            position_lots.clear()
        trades.append(
            BacktestTrade(
                order_id=order.order_id,
                time=bar.ts,
                instrument=symbol,
                side=side,
                price=round(fill_price, 6),
                qty=round(qty, 6),
                commission=round(commission, 6),
                slippage=round(slippage, 6),
            )
        )
        ledger = instrument_cashflows.setdefault(
            symbol,
            {"buy_notional": 0.0, "sell_notional": 0.0, "cost": 0.0, "end_qty": 0.0},
        )
        notional = qty * fill_price
        if side == "sell":
            ledger["sell_notional"] += notional
            ledger["end_qty"] -= qty
        else:
            ledger["buy_notional"] += notional
            ledger["end_qty"] += qty
        ledger["cost"] += commission + slippage
        total_commission += commission
        total_slippage += slippage
        risk_actions.append(
            {
                "time": bar.ts.isoformat(),
                "action": "drawdown_circuit_breaker_flatten",
                "detail": f"flatten_qty={qty:.6f} side={side}",
            }
        )
        risk_actions.append(
            {
                "time": bar.ts.isoformat(),
                "action": "circuit_breaker_stop_trading",
                "detail": "new orders disabled after drawdown breach",
            }
        )
        return True, cash, total_commission, total_slippage

    def _build_attribution(
        self,
        *,
        instrument_cashflows: dict[str, dict[str, float]],
        instrument_last_price: dict[str, float],
        instrument_sector: dict[str, str],
    ) -> tuple[dict[str, float], dict[str, float]]:
        instrument_pnl_contrib: dict[str, float] = {}
        sector_pnl_contrib: dict[str, float] = {}
        for instrument, ledger in instrument_cashflows.items():
            end_qty = float(ledger.get("end_qty", 0.0))
            last_price = float(instrument_last_price.get(instrument, 0.0))
            pnl = (
                float(ledger.get("sell_notional", 0.0))
                + (end_qty * last_price)
                - float(ledger.get("buy_notional", 0.0))
                - float(ledger.get("cost", 0.0))
            )
            rounded = round(pnl, 6)
            instrument_pnl_contrib[instrument] = rounded
            sector = instrument_sector.get(instrument, "Unknown")
            sector_pnl_contrib[sector] = round(sector_pnl_contrib.get(sector, 0.0) + rounded, 6)
        return instrument_pnl_contrib, sector_pnl_contrib

    def _default_sector(self, symbol: str) -> str:
        text = symbol.upper()
        if any(tag in text for tag in ["BTC", "ETH", "SOL"]):
            return "Crypto"
        if any(tag in text for tag in ["BANK", "FIN"]):
            return "Financials"
        if any(tag in text for tag in ["600", "601", "000", "SZ", "SS"]):
            return "Industrials"
        if any(tag in text for tag in ["7203", ".T"]):
            return "Automotive"
        return "Technology"

    def _position_qty(self, position_lots: list[dict[str, Any]]) -> float:
        return float(sum(float(row.get("qty", 0.0)) for row in position_lots))

    def _avg_price(self, position_lots: list[dict[str, Any]]) -> float:
        total_qty = self._position_qty(position_lots)
        if total_qty <= 0:
            return 0.0
        total_cost = sum(float(row.get("qty", 0.0)) * float(row.get("price", 0.0)) for row in position_lots)
        return total_cost / total_qty

    def _sellable_qty(self, *, position_lots: list[dict[str, Any]], as_of: date, t_plus_one: bool) -> float:
        if not t_plus_one:
            return self._position_qty(position_lots)
        total = 0.0
        for lot in position_lots:
            acquired = lot.get("acquired_date")
            if isinstance(acquired, date) and acquired < as_of:
                total += float(lot.get("qty", 0.0))
        return total

    def _consume_lots_for_sell(
        self,
        *,
        position_lots: list[dict[str, Any]],
        sell_qty: float,
        as_of: date,
        t_plus_one: bool,
    ) -> None:
        remaining = sell_qty
        for lot in position_lots:
            if remaining <= 1e-9:
                break
            acquired = lot.get("acquired_date")
            if t_plus_one and isinstance(acquired, date) and acquired >= as_of:
                continue
            lot_qty = float(lot.get("qty", 0.0))
            take = min(lot_qty, remaining)
            lot["qty"] = lot_qty - take
            remaining -= take
        position_lots[:] = [lot for lot in position_lots if float(lot.get("qty", 0.0)) > 1e-9]

    def _hit_price_limit(self, *, side: str, bar: OHLCVBar, limit_pct: float) -> bool:
        if bar.open <= 0:
            return False
        move = (bar.close / bar.open) - 1.0
        if side == "buy":
            return move >= limit_pct * 0.98
        return move <= -limit_pct * 0.98

    def _dynamic_slippage_bps(
        self,
        *,
        base_slippage_bps: float,
        spread_bps: float,
        recent_returns: list[float],
    ) -> float:
        vol = statistics.pstdev(recent_returns) if len(recent_returns) > 1 else 0.0
        vol_component = min(20.0, max(0.0, vol * 10000.0 * 0.15))
        spread_component = max(0.0, spread_bps * 0.15)
        return base_slippage_bps + spread_component + vol_component

    def _round_to_lot(self, qty: float, *, lot_size: float, fractional: bool) -> float:
        if fractional:
            if lot_size <= 0:
                return qty
            units = math.floor(abs(qty) / lot_size)
            sign = 1 if qty >= 0 else -1
            return sign * units * lot_size
        step = int(max(1, round(lot_size)))
        units = int(abs(qty) / step)
        sign = 1 if qty >= 0 else -1
        return float(sign * units * step)

    def _returns_from_closes(self, closes: list[float]) -> list[float]:
        out: list[float] = []
        for idx, value in enumerate(closes):
            if idx == 0 or closes[idx - 1] == 0:
                out.append(0.0)
            else:
                out.append((value / closes[idx - 1]) - 1.0)
        return out

    def _returns_from_equity(self, equity_values: list[float]) -> list[float]:
        out: list[float] = []
        for idx, value in enumerate(equity_values):
            if idx == 0 or equity_values[idx - 1] == 0:
                out.append(0.0)
            else:
                out.append((value / equity_values[idx - 1]) - 1.0)
        return out

    def _build_monthly_returns(self, equity_values: list[float]) -> dict[str, float]:
        monthly: dict[str, float] = {}
        if not equity_values:
            return monthly
        month_open = equity_values[0]
        month_idx = 0
        for idx, equity in enumerate(equity_values, start=1):
            if idx % 21 == 0:
                month_idx += 1
                monthly[f"M{month_idx:02d}"] = round((equity / month_open) - 1.0, 6) if month_open > 0 else 0.0
                month_open = equity
        if (len(equity_values) % 21) != 0:
            month_idx += 1
            last = equity_values[-1]
            monthly[f"M{month_idx:02d}"] = round((last / month_open) - 1.0, 6) if month_open > 0 else 0.0
        return monthly

    def _max_drawdown_from_equity(self, equity_values: list[float]) -> float:
        peak = equity_values[0] if equity_values else 1.0
        mdd = 0.0
        for equity in equity_values:
            peak = max(peak, equity)
            dd = (peak - equity) / peak if peak > 0 else 0.0
            mdd = max(mdd, dd)
        return mdd

    def _normalize_circuit_breaker(self, *, raw: Any, default_drawdown_limit: float) -> dict[str, Any]:
        allowed = {"consecutive_losses", "drawdown", "vol_spike"}
        fallback = {
            "enabled": True,
            "rule": {
                "type": "drawdown",
                "threshold": float(max(0.0, default_drawdown_limit)),
                "cool_down_days": 5,
            },
        }
        if not isinstance(raw, dict):
            return fallback
        enabled = raw.get("enabled")
        if not isinstance(enabled, bool):
            enabled = bool(fallback["enabled"])
        rule = raw.get("rule")
        if not isinstance(rule, dict):
            return {**fallback, "enabled": enabled}
        rule_type = str(rule.get("type", "drawdown")).strip().lower()
        if rule_type not in allowed:
            rule_type = "drawdown"
        threshold = rule.get("threshold")
        if not isinstance(threshold, (int, float)):
            threshold = fallback["rule"]["threshold"]
        cool_down_days = rule.get("cool_down_days")
        if not isinstance(cool_down_days, (int, float)):
            cool_down_days = fallback["rule"]["cool_down_days"]
        return {
            "enabled": enabled,
            "rule": {
                "type": rule_type,
                "threshold": float(max(0.0, float(threshold))),
                "cool_down_days": int(max(0, int(cool_down_days))),
            },
        }

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in out:
                out.append(text)
        return out

    def _optimizer_universe(self, *, symbol: str, constraints: dict[str, Any]) -> list[str]:
        universe = [symbol]
        raw = self._string_list(constraints.get("portfolio_universe"))
        for item in raw:
            if item not in universe:
                universe.append(item)
        return universe

    def _optimizer_sectors(
        self,
        *,
        symbol: str,
        fallback_sector: str,
        universe: list[str],
        constraints: dict[str, Any],
    ) -> dict[str, str]:
        out = {symbol: fallback_sector}
        raw_map = constraints.get("sector_map")
        if isinstance(raw_map, dict):
            for key, value in raw_map.items():
                inst = str(key).strip()
                sec = str(value).strip()
                if inst and sec:
                    out[inst] = sec
        for inst in universe:
            out.setdefault(inst, self._default_sector(inst))
        return out

    def _risk_budget_vector(
        self,
        *,
        universe: list[str],
        constraints: dict[str, Any],
        risk_budget_label: str,
    ) -> dict[str, float]:
        raw = constraints.get("risk_budget_vector")
        if isinstance(raw, dict):
            cleaned: dict[str, float] = {}
            for inst in universe:
                value = raw.get(inst)
                if isinstance(value, (int, float)) and float(value) >= 0:
                    cleaned[inst] = float(value)
            if sum(cleaned.values()) > 0:
                total = sum(cleaned.values())
                return {inst: round(cleaned.get(inst, 0.0) / total, 8) for inst in universe}
        if isinstance(raw, list) and len(raw) == len(universe):
            vals = [float(value) if isinstance(value, (int, float)) else 0.0 for value in raw]
            vals = [max(0.0, value) for value in vals]
            if sum(vals) > 0:
                total = sum(vals)
                return {inst: round(vals[idx] / total, 8) for idx, inst in enumerate(universe)}
        if len(universe) == 2:
            ratio = self._parse_budget_ratio(risk_budget_label)
            if ratio is not None:
                return {universe[0]: round(ratio, 8), universe[1]: round(1.0 - ratio, 8)}
        equal = 1.0 / max(1, len(universe))
        return {inst: round(equal, 8) for inst in universe}

    def _parse_budget_ratio(self, text: str) -> float | None:
        low = text.lower().strip()
        if "/" in low:
            parts = low.split("/", 1)
            try:
                left = float(parts[0])
                right = float(parts[1])
            except ValueError:
                return None
            if left >= 0 and right > 0 and (left + right) > 0:
                return left / (left + right)
        if "60" in low and "40" in low:
            return 0.6
        if "70" in low and "30" in low:
            return 0.7
        return None

    def _build_cross_asset_returns(
        self,
        *,
        bars: list[OHLCVBar],
        base_returns: list[float],
        universe: list[str],
        primary_symbol: str,
        constraints: dict[str, Any],
        high_vol_assets: list[str],
        high_vol_shock_start: int,
        high_vol_shock_multiplier: float,
    ) -> dict[str, list[float]]:
        beta_map = constraints.get("asset_beta_map") if isinstance(constraints.get("asset_beta_map"), dict) else {}
        vol_map = constraints.get("asset_vol_multipliers") if isinstance(constraints.get("asset_vol_multipliers"), dict) else {}
        out: dict[str, list[float]] = {}
        for inst_idx, inst in enumerate(universe):
            if inst == primary_symbol:
                out[inst] = list(base_returns)
                continue
            beta = float(beta_map.get(inst, 0.9 - min(0.3, inst_idx * 0.05))) if isinstance(beta_map, dict) else 0.85
            vol_mul = float(vol_map.get(inst, 1.1 + inst_idx * 0.12)) if isinstance(vol_map, dict) else (1.1 + inst_idx * 0.12)
            series: list[float] = []
            for idx in range(len(base_returns)):
                base_ret = base_returns[idx] if idx < len(base_returns) else 0.0
                ts_text = bars[idx].ts.isoformat() if idx < len(bars) else str(idx)
                noise = self._deterministic_noise(f"{inst}|{ts_text}|{idx}")
                local_vol = vol_mul
                if inst in high_vol_assets and idx >= high_vol_shock_start:
                    local_vol *= max(1.0, high_vol_shock_multiplier)
                series.append((base_ret * beta) + (noise * 0.004 * local_vol))
            out[inst] = series
        return out

    def _signal_map_for_universe(self, *, base_signal: float, universe: list[str], ts: str) -> dict[str, float]:
        out: dict[str, float] = {}
        for idx, inst in enumerate(universe):
            noise = self._deterministic_noise(f"signal|{inst}|{ts}|{idx}")
            scale = 1.0 + min(0.2, idx * 0.05)
            out[inst] = base_signal * scale + noise * 0.03
        return out

    def _covariance_matrix(
        self,
        window_returns: dict[str, list[float]],
        universe: list[str],
    ) -> dict[str, dict[str, float]]:
        matrix: dict[str, dict[str, float]] = {}
        for i, left in enumerate(universe):
            left_series = window_returns.get(left, [])
            matrix[left] = {}
            for j, right in enumerate(universe):
                right_series = window_returns.get(right, [])
                cov = self._cov(left_series, right_series)
                if i == j:
                    cov = max(1e-8, cov)
                matrix[left][right] = cov
        return matrix

    def _cov(self, x: list[float], y: list[float]) -> float:
        n = min(len(x), len(y))
        if n <= 1:
            return 0.0
        xs = x[:n]
        ys = y[:n]
        mean_x = statistics.fmean(xs)
        mean_y = statistics.fmean(ys)
        total = 0.0
        for idx in range(n):
            total += (xs[idx] - mean_x) * (ys[idx] - mean_y)
        return total / max(1, n - 1)

    def _deterministic_noise(self, key: str) -> float:
        raw = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
        value = int(raw, 16)
        return (value / 0xFFFFFFFF) - 0.5

    def _risk_budget_scale(self, risk_budget: str) -> float:
        if "6" in risk_budget:
            return 0.6
        if "7" in risk_budget:
            return 0.7
        if "8" in risk_budget:
            return 0.8
        if "9" in risk_budget:
            return 0.9
        if "10" in risk_budget:
            return 1.0
        return 0.85

    def _signal_for_family(self, family: str, window: list[float], threshold: float) -> float:
        mean_ret = statistics.fmean(window) if window else 0.0
        vol = statistics.pstdev(window) if len(window) > 1 else 0.01

        if family == "trend":
            return 1.0 if mean_ret > threshold else -0.35
        if family == "trend_with_vol_filter":
            return 0.9 if (mean_ret > threshold and vol < 0.03) else 0.2
        if family == "mean_reversion":
            return -0.9 if mean_ret > threshold else 0.9
        if family == "value":
            return 0.8 if mean_ret < max(threshold, 0.0001) else 0.25
        if family == "quality_value":
            return 0.7 if mean_ret <= threshold else 0.2
        if family == "value_with_momentum_filter":
            return 0.7 if (-0.03 < mean_ret < 0.0) else 0.1
        if family == "risk_parity":
            return min(1.0, max(0.2, 0.02 / max(0.004, vol)))
        if family == "regime_allocation":
            return 0.85 if vol < 0.02 else 0.3
        if family == "defensive_carry":
            return 0.55 if mean_ret > -0.001 else 0.25
        return 0.6 if mean_ret >= 0 else -0.2
