from openfinance.agents.schemas import AgentOutput
from openfinance.data.contracts.instruments import Instrument, TradingHours, TradingSession
from openfinance.quant.backtest.evaluation_plan import BacktestEvaluationPlan
from openfinance.quant.backtest.report import BacktestReport, BacktestRequest
from openfinance.quant.backtest.strategy_runtime_action_regime import build_strategy_runtime_action_regime_details
from openfinance.quant.backtest.strategy_runtime_attribution_execution import (
    build_strategy_runtime_attribution_execution_details,
)
from openfinance.quant.backtest.strategy_runtime_control_action_deep import (
    build_strategy_runtime_control_action_deep_details,
)
from openfinance.quant.backtest.strategy_runtime_control_optimizer import (
    build_strategy_runtime_control_optimizer_details,
)
from openfinance.quant.backtest.strategy_runtime_diagnostics import (
    build_strategy_compare_result_details,
    build_strategy_robustness_result_details,
    build_strategy_runtime_diagnostics_result,
)
from openfinance.quant.backtest.strategy_runtime_summary import (
    build_strategy_compare_outcome_summary,
    build_strategy_robustness_outcome_summary,
    build_strategy_runtime_outcome_summary,
)
from openfinance.quant.backtest.strategy_trace import build_strategy_trace_artifact
from openfinance.quant.factors.factor_spec import FactorInput, FactorSpec, ValidationPlan
from openfinance.quant.factors.report import DecayPoint, FactorReport
from openfinance.research.strategy_compilation import (
    StrategyCompilationPlan,
    build_strategy_compile_runtime_context,
    build_strategy_compilation_plan,
    get_strategy_compile_runtime_provenance_preset,
    get_strategy_compilation_policy_rule_surface,
)
from openfinance.research.strategy_request_builder import build_strategy_backtest_request
from openfinance.research.strategy_decision import StrategyDecision
from openfinance.research.strategy_spec import StrategySpec
from openfinance.research.strategy_validation import StrategyValidationResult, StrategyValidator
from openfinance.trading.domain import Order


def test_instrument_contract() -> None:
    instrument = Instrument(
        instrument_id="us_eq_aapl",
        symbol="AAPL",
        asset_class="equity",
        venue="NASDAQ",
        currency="USD",
        tick_size=0.01,
        lot_size=1,
        trading_hours=TradingHours(
            timezone="America/New_York",
            sessions=[TradingSession(start="09:30", end="16:00")],
        ),
    )
    assert instrument.symbol == "AAPL"


def test_factor_spec_contract() -> None:
    spec = FactorSpec(
        factor_id="value_basic",
        factor_version="0.1.0",
        description="Simple value factor",
        inputs=[FactorInput(name="pe_ratio", source="fundamentals")],
        validation_plan=ValidationPlan(
            in_sample_start="2020-01-01",
            in_sample_end="2022-12-31",
            out_sample_start="2023-01-01",
            out_sample_end="2024-12-31",
        ),
    )
    assert spec.inputs[0].availability_lag == "0s"


def test_backtest_report_contract() -> None:
    request = BacktestRequest(
        dataset_version="ds_v1",
        strategy_id="mean_reversion",
        strategy_version="0.1.0",
        market="US",
        start="2020-01-01",
        end="2024-01-01",
    )
    report = BacktestReport(
        dataset_version=request.dataset_version,
        strategy_version=request.strategy_version,
    )
    assert report.dataset_version == "ds_v1"
    assert isinstance(report.factor_versions, list)
    assert isinstance(request.evaluation_plan, BacktestEvaluationPlan)


def test_strategy_trace_artifact_contract() -> None:
    validation = StrategyValidationResult(
        strategy_id="demo_strategy",
        strategy_version="0.1.0",
        market="US",
        status="ok",
        compile_ready=True,
        summary="compile ready",
    )
    compilation = StrategyCompilationPlan(
        strategy_id="demo_strategy",
        strategy_version="0.1.0",
        market="US",
        compile_ready=True,
        validation_status="ok",
        decision_status="not_provided",
        summary="compile map ready",
    )

    trace = build_strategy_trace_artifact(
        trace_object="BacktestReport",
        strategy_validation=validation,
        strategy_compilation=compilation,
        evaluation_plan=BacktestEvaluationPlan(
            strategy_validation=validation,
            strategy_compilation=compilation,
            evidence_refs=["evidence_pack:demo"],
            factor_versions=[{"factor_id": "factor_demo", "version": "factor-demo-v1"}],
        ),
        factor_versions=[{"factor_id": "factor_demo", "version": "factor-demo-v1"}],
        factor_lineage_reason="report_factor_versions",
    )

    assert trace is not None
    assert trace.schema_version == "strategy_trace_artifact.v1"
    assert trace.trace_object == "BacktestReport"
    assert trace.strategy_validation is not None
    assert trace.strategy_validation.schema_version == "strategy_validation.v1"
    assert trace.strategy_compilation is not None
    assert trace.strategy_compilation.schema_version == "strategy_compilation.v1"
    assert trace.evaluation_plan is not None
    assert trace.evaluation_plan.schema_version == "backtest_evaluation_plan.v1"
    assert trace.factor_lineage.factor_versions[0].version == "factor-demo-v1"
    assert trace.factor_lineage.reason == "report_factor_versions"


def test_strategy_runtime_summary_contracts() -> None:
    runtime = build_strategy_runtime_outcome_summary(
        summary_object="BacktestReport",
        run_id="run_demo",
        dataset_version="ds_v1",
        market="US",
        strategy_version="0.1.0",
        metrics={"sharpe": 1.2, "max_drawdown": -0.08, "trade_count": 12},
        strategy_trace=build_strategy_trace_artifact(
            trace_object="BacktestReport",
            evaluation_plan=BacktestEvaluationPlan(
                evidence_refs=["evidence_pack:demo"],
                factor_versions=[{"factor_id": "factor_demo", "version": "factor-demo-v1"}],
            ),
            factor_versions=[{"factor_id": "factor_demo", "version": "factor-demo-v1"}],
        ),
    )
    compare = build_strategy_compare_outcome_summary(
        compare_id="cmp_demo",
        baseline_market="US",
        rows=[
            runtime,
            build_strategy_runtime_outcome_summary(
                summary_object="MarketCompareRow",
                run_id="run_demo_jp",
                dataset_version="ds_v2",
                market="JP",
                strategy_version="0.1.0",
                metrics={"sharpe": 0.8, "max_drawdown": -0.12, "trade_count": 10},
                warning_count=1,
                highest_warning_severity="medium",
            ),
        ],
    )
    robustness = build_strategy_robustness_outcome_summary(
        robustness_id="rob_demo",
        market="US",
        variant_count=8,
        sharpe_std=0.11,
        mdd_worst_case=-0.14,
        stability_score=0.76,
        worst_case_source_type="stress",
        worst_case_run_id="run_demo",
        base_runtime_summary=runtime,
    )

    assert runtime.schema_version == "strategy_runtime_outcome_summary.v1"
    assert runtime.factor_lineage_count == 1
    assert runtime.evidence_ref_count == 1
    assert compare.schema_version == "strategy_compare_outcome_summary.v1"
    assert compare.market_count == 2
    assert compare.warning_count == 1
    assert robustness.schema_version == "strategy_robustness_outcome_summary.v1"
    assert robustness.base_runtime_summary is not None
    assert robustness.base_runtime_summary.run_id == "run_demo"


def test_strategy_runtime_diagnostics_contracts() -> None:
    runtime = build_strategy_runtime_diagnostics_result(
        diagnostics_object="BacktestReport",
        diagnostics={
            "execution_model": "next_open",
            "cost_model": {"commission_bps": 4.0, "base_slippage_bps": 7.0},
            "market_rules": {
                "market": "US",
                "t_plus_one": False,
                "lot_size": 1,
                "supports_fractional_qty": True,
                "min_notional": 0.0,
                "is_24x7": False,
            },
            "risk_management": {
                "drawdown_limit": 0.12,
                "stop_trading_triggered": False,
                "failure_condition_block_triggered": False,
                "circuit_breaker": {"enabled": True, "trigger_count": 1},
            },
            "portfolio_optimization": {
                "optimizer": "risk_budget_v2",
                "optimizer_universe": ["AAPL", "MSFT"],
                "covariance_window": 20,
            },
            "budget_deviation": {"mean_l1": 0.01, "max_l1": 0.03, "observations": 4},
            "risk_actions": [{"action": "vol_scale_down"}, {"action": "vol_scale_down"}],
            "constraint_actions": [{"action": "max_position_cap"}],
            "optimizer_diagnostics": [{"optimizer": "risk_budget_v2"}],
            "rejected_orders": [{"reason": "lot_size"}],
            "failure_condition_checks": {"events": [{"type": "drawdown_limit"}]},
            "regime_periods": [{"regime": "high_vol"}],
            "notes": "event-driven backtest with market-rules constraints",
        },
    )
    compare = build_strategy_compare_result_details(
        compare_id="cmp_demo",
        baseline_market="US",
        diff_rows=[
            {
                "market": "US",
                "run_id": "run_us",
                "dataset_version": "ds_us",
                "sharpe": 1.1,
                "max_drawdown": -0.08,
                "turnover": 0.5,
                "warning_count": 0,
            },
            {
                "market": "JP",
                "run_id": "run_jp",
                "dataset_version": "ds_jp",
                "sharpe": 0.9,
                "max_drawdown": -0.11,
                "turnover": 0.4,
                "warning_count": 1,
                "highest_warning_severity": "medium",
            },
        ],
        market_warnings={
            "JP": [{"code": "lot_size_precision_mismatch", "severity": "medium"}],
            "US": [],
        },
    )
    robustness = build_strategy_robustness_result_details(
        robustness_id="rob_demo",
        variant_rows=[
            {
                "variant_id": "v1",
                "group": "cost_sensitivity",
                "scenario": "double_cost",
                "run_id": "run_v1",
                "commission_bps": 10.0,
                "slippage_bps": 16.0,
                "sharpe": 0.8,
                "max_drawdown": -0.15,
                "total_return": 0.07,
                "cost_drag": 0.02,
                "turnover": 0.4,
            }
        ],
        regime_metric_count=2,
        stress_metric_count=2,
        best_variant_id="v_best",
        worst_variant_id="v_worst",
    )

    assert runtime.schema_version == "strategy_runtime_diagnostics.v1"
    assert runtime.action_counts.risk_action_count == 2
    assert runtime.action_counts.regime_period_count == 1
    assert compare.schema_version == "strategy_compare_result_details.v1"
    assert len(compare.diff_rows) == 2
    assert compare.warning_summaries[0].market in {"JP", "US"}
    assert robustness.schema_version == "strategy_robustness_result_details.v1"
    assert robustness.regime_metric_count == 2
    assert robustness.stress_metric_count == 2


def test_strategy_runtime_action_regime_contracts() -> None:
    details = build_strategy_runtime_action_regime_details(
        detail_object="BacktestReport",
        diagnostics={
            "risk_actions": [
                {"time": "2024-01-01T00:00:00Z", "action": "regime_enter_high_vol", "detail": "rolling_vol=0.03"},
                {"time": "2024-01-02T00:00:00Z", "action": "regime_exposure_scaled", "detail": "scale=0.3"},
            ],
            "constraint_actions": [
                {
                    "time": "2024-01-03T00:00:00Z",
                    "optimizer": "risk_budget_v2",
                    "symbol": "AAPL",
                    "action": "max_position_weight_cap",
                    "instrument": "AAPL",
                    "before": 0.3,
                    "after": 0.2,
                }
            ],
            "failure_condition_checks": {
                "events": [
                    {
                        "time": "2024-01-04T00:00:00Z",
                        "code": "ABNORMAL_VOL_SPIKE",
                        "level": "warn",
                        "message": "vol spike",
                        "metrics": {"score": 2.1, "rolling_volatility": 0.04},
                    }
                ]
            },
            "regime_periods": [
                {
                    "regime": "high_vol",
                    "start": "2024-01-01T00:00:00Z",
                    "end": "2024-01-05T00:00:00Z",
                    "trigger": "rolling_vol_threshold",
                }
            ],
        },
    )

    assert details.schema_version == "strategy_runtime_action_regime.v1"
    assert len(details.risk_actions) == 2
    assert len(details.constraint_actions) == 1
    assert len(details.failure_condition_events) == 1
    assert details.failure_condition_events[0].metric_keys == ["rolling_volatility", "score"]
    assert len(details.regime_periods) == 1


def test_strategy_runtime_control_optimizer_contracts() -> None:
    details = build_strategy_runtime_control_optimizer_details(
        detail_object="BacktestReport",
        diagnostics={
            "rejected_orders": [
                {
                    "time": "2024-01-05T00:00:00Z",
                    "instrument": "AAPL",
                    "side": "buy",
                    "qty": 100,
                    "reason": "lot_size",
                    "reason_code": "LOT_SIZE_BLOCK",
                }
            ],
            "optimizer_diagnostics": [
                {
                    "time": "2024-01-04T00:00:00Z",
                    "optimizer": "risk_budget_v2",
                    "symbol": "AAPL",
                    "signal": 0.12,
                    "raw_target_exposure": 0.8,
                    "optimized_weight": 0.6,
                    "gross_target": 1.0,
                    "details": {
                        "budget_deviation_l1": 0.07,
                        "assets": ["AAPL", "MSFT"],
                    },
                }
            ],
            "risk_management": {
                "circuit_breaker": {
                    "trigger_intervals": [
                        {
                            "start": "2024-01-10T00:00:00Z",
                            "end": "2024-01-12T00:00:00Z",
                            "reason": "drawdown_threshold_breach",
                        }
                    ]
                }
            },
            "budget_deviation": {"mean_l1": 0.01, "max_l1": 0.03, "observations": 4},
            "risk_contribution_ts": [
                {
                    "time": "2024-01-11T00:00:00Z",
                    "deviation_l1": 0.02,
                    "target_budget": {"AAPL": 0.6, "MSFT": 0.4},
                    "achieved_budget": {"AAPL": 0.58, "MSFT": 0.42},
                    "weights": {"AAPL": 0.55, "MSFT": 0.45},
                }
            ],
        },
    )

    assert details.schema_version == "strategy_runtime_control_optimizer.v1"
    assert details.detail_object == "BacktestReport"
    assert len(details.rejected_orders) == 1
    assert len(details.optimizer_diagnostics) == 1
    assert len(details.circuit_breaker_intervals) == 1
    assert details.budget_detail.observations == 4
    assert details.budget_detail.latest_target_budget["AAPL"] == 0.6
    assert len(details.risk_contribution_points) == 1


def test_strategy_runtime_control_action_deep_contracts() -> None:
    details = build_strategy_runtime_control_action_deep_details(
        detail_object="BacktestReport",
        diagnostics={
            "optimizer_diagnostics": [
                {
                    "time": "2024-01-04T00:00:00Z",
                    "optimizer": "risk_budget_v2",
                    "risk_budget_vector": {"AAPL": 0.6, "MSFT": 0.4},
                    "covariance": {
                        "AAPL": {"AAPL": 0.01, "MSFT": 0.002},
                        "MSFT": {"AAPL": 0.002, "MSFT": 0.02},
                    },
                    "details": {
                        "method": "covariance_risk_budget_v2",
                        "budget_deviation_l1": 0.07,
                        "loss_final": 0.0002,
                        "assets": ["AAPL", "MSFT"],
                        "raw_weights": {"AAPL": 0.55, "MSFT": 0.45},
                        "target_budget": {"AAPL": 0.6, "MSFT": 0.4},
                        "achieved_budget": {"AAPL": 0.58, "MSFT": 0.42},
                        "direction": {"AAPL": 1.0, "MSFT": 1.0},
                    },
                }
            ],
            "risk_management": {
                "stop_trading_triggered": True,
                "circuit_breaker": {
                    "enabled": True,
                    "trigger_count": 1,
                    "rule": {"type": "drawdown", "threshold": 0.1},
                    "execution_support": {
                        "drawdown": True,
                        "consecutive_losses": False,
                        "vol_spike": False,
                    },
                    "trigger_intervals": [
                        {
                            "start": "2024-01-10T00:00:00Z",
                            "end": "2024-01-12T00:00:00Z",
                            "reason": "drawdown_threshold_breach",
                        }
                    ],
                }
            },
            "budget_deviation": {"mean_l1": 0.01, "max_l1": 0.03, "observations": 4},
            "risk_contribution_ts": [
                {
                    "time": "2024-01-11T00:00:00Z",
                    "deviation_l1": 0.02,
                    "target_budget": {"AAPL": 0.6, "MSFT": 0.4},
                    "achieved_budget": {"AAPL": 0.58, "MSFT": 0.42},
                    "weights": {"AAPL": 0.55, "MSFT": 0.45},
                },
                {
                    "time": "2024-01-12T00:00:00Z",
                    "deviation_l1": 0.04,
                    "target_budget": {"AAPL": 0.6, "MSFT": 0.4},
                    "achieved_budget": {"AAPL": 0.54, "MSFT": 0.46},
                    "weights": {"AAPL": 0.52, "MSFT": 0.48},
                },
            ],
        },
    )

    assert details.schema_version == "strategy_runtime_control_action_deep.v1"
    assert details.detail_object == "BacktestReport"
    assert len(details.optimizer_steps) == 1
    assert details.optimizer_steps[0].method == "covariance_risk_budget_v2"
    assert details.optimizer_steps[0].covariance_asset_count == 2
    assert details.circuit_breaker_state.rule_type == "drawdown"
    assert details.circuit_breaker_state.execution_support.drawdown is True
    assert len(details.circuit_breaker_state.intervals) == 1
    assert details.budget_breakdown.peak_deviation_l1 == 0.04
    assert details.risk_contribution_breakdown.point_count == 2
    assert details.risk_contribution_breakdown.latest is not None
    assert details.risk_contribution_breakdown.latest.gap_by_asset["MSFT"] == 0.06


def test_strategy_runtime_attribution_execution_contracts() -> None:
    details = build_strategy_runtime_attribution_execution_details(
        detail_object="BacktestReport",
        cost_breakdown={
            "commission_sum": 12.5,
            "slippage_sum": 8.25,
            "total": 20.75,
        },
        attribution={
            "instrument_pnl_contrib": {"AAPL": 1200.0, "MSFT": -350.0},
            "sector_pnl_contrib": {"Technology": 850.0, "Defensive": -120.0},
        },
        diagnostics={"execution_model": "next_open"},
        orders=[
            {"status": "filled", "reason_code": "SUBMITTED"},
            {"status": "rejected", "reason_code": "LOT_SIZE_BLOCK"},
            {"status": "queued", "reason_code": "QUEUED"},
        ],
        trades=[
            {"side": "buy", "qty": 100, "commission": 5.0, "slippage": 3.0},
            {"side": "sell", "qty": 60, "commission": 7.5, "slippage": 5.25},
        ],
        metrics={"cost_drag": 0.0123},
    )

    assert details.schema_version == "strategy_runtime_attribution_execution.v1"
    assert details.detail_object == "BacktestReport"
    assert details.cost_detail.total_cost == 20.75
    assert details.cost_detail.trade_count == 2
    assert details.attribution_detail.top_instrument is not None
    assert details.attribution_detail.top_instrument.label == "AAPL"
    assert details.execution_style_detail.execution_model == "next_open"
    assert details.execution_style_detail.rejected_order_count == 1
    assert details.execution_style_detail.dominant_reject_reason == "LOT_SIZE_BLOCK"


def test_strategy_validation_contract() -> None:
    result = StrategyValidationResult(
        strategy_id="demo_strategy",
        strategy_version="0.1.0",
        market="US",
        status="ok",
        compile_ready=True,
        summary="compile ready",
    )
    assert result.next_output == "BacktestRequest"


def test_strategy_validation_ignores_compile_time_overlays_in_decision_alignment() -> None:
    spec = StrategySpec(
        strategy_id="demo_strategy",
        strategy_version="0.1.0",
        market="JP",
        strategy_family="regime_allocation",
        rebalance="weekly",
        lookback_days=45,
        signal_threshold=0.001,
        position_sizing="risk_budget",
        risk_budget="vol_target_8pct",
        max_position=0.2,
        stop_loss=0.06,
        leverage_limit=1.2,
        rationale="demo",
        evidence_refs=["evidence_pack:demo"],
    )
    decision = StrategyDecision.model_validate(
        {
            "selected": {
                "name": "RiskBudgetAllocator",
                "spec": {
                    "strategy_family": "regime_allocation",
                    "rebalance": "weekly",
                    "lookback_days": 45,
                    "signal_threshold": 0.001,
                    "position_sizing": "risk_budget",
                    "risk_budget": "vol_target_8pct",
                    "max_position": 0.2,
                    "leverage_limit": 1.0,
                },
                "rationale": "demo",
                "tradeoff_summary": "demo",
            },
        }
    )

    result = StrategyValidator().validate_spec(spec, decision=decision)

    assert result.decision_status == "aligned"
    assert result.compile_ready is True


def test_strategy_compilation_contract() -> None:
    plan = StrategyCompilationPlan(
        strategy_id="demo_strategy",
        strategy_version="0.1.0",
        market="US",
        compile_ready=True,
        validation_status="ok",
        decision_status="not_provided",
        summary="compile map ready",
    )
    assert plan.executable_object == "BacktestRequest"
    assert plan.compilation_profile.schema_version == "strategy_compilation_profile.v1"


def test_strategy_compilation_rule_surface_contains_reviewable_rules() -> None:
    surface = get_strategy_compilation_policy_rule_surface()

    assert surface.schema_version == "strategy_compilation_policy_rules.v1"
    assert surface.rule_surface_id == "strategy_compilation.backtest.v1"
    rule_ids = {row.rule_id for row in surface.rules}
    assert "runtime.execution_model_supported" in rule_ids
    assert "runtime.execution_model_unsupported" in rule_ids
    assert "override.constraints.auto_round_lot.requires_review" in rule_ids
    assert "migration.trading_session_coverage_gap" in rule_ids
    assert "migration.lot_size_precision_mismatch" in rule_ids


def test_strategy_compile_runtime_context_builder_normalizes_supported_modes() -> None:
    pipeline_context = build_strategy_compile_runtime_context(
        dataset_version="ds_pipeline",
        start="2024-01-01",
        end="2024-02-01",
        provenance_mode="pipeline_managed",
    )
    user_context = build_strategy_compile_runtime_context(
        dataset_version="ds_user",
        start="2024-01-01",
        end="2024-02-01",
        auto_round_lot=True,
        provenance_mode="user_requested",
    )
    variant_context = build_strategy_compile_runtime_context(
        dataset_version="ds_variant",
        start="2024-01-01",
        end="2024-02-01",
        auto_round_lot=True,
        provenance_mode="runtime_variant",
    )

    assert pipeline_context.window_classification == "runtime_derived"
    assert pipeline_context.window_configured_by == "runtime_pipeline"
    assert pipeline_context.cost_model_classification == "runtime_derived"
    assert pipeline_context.cost_model_configured_by == "runtime_pipeline"

    assert user_context.window_classification == "user_configurable"
    assert user_context.window_configured_by == "user_request"
    assert user_context.cost_model_classification == "user_configurable"
    assert user_context.cost_model_configured_by == "user_request"
    assert user_context.auto_round_lot_configured_by == "user_request"

    assert variant_context.window_classification == "user_configurable"
    assert variant_context.window_configured_by == "user_request"
    assert variant_context.cost_model_classification == "runtime_derived"
    assert variant_context.cost_model_configured_by == "runtime_pipeline"
    assert variant_context.auto_round_lot_configured_by == "runtime_pipeline"

    preset = get_strategy_compile_runtime_provenance_preset("runtime_variant")
    assert preset.mode == "runtime_variant"
    assert preset.cost_model_configured_by == "runtime_pipeline"
    assert variant_context.provenance_mode == "runtime_variant"


def test_strategy_backtest_request_builder_normalizes_defaults() -> None:
    spec = StrategySpec(
        strategy_id="demo_strategy",
        strategy_version="0.1.0",
        market="US",
        strategy_family="trend",
        rebalance="weekly",
        lookback_days=20,
        signal_threshold=0.0,
        position_sizing="risk_budget",
        risk_budget="vol_target_10pct",
        max_position=0.12,
        stop_loss=0.05,
        leverage_limit=1.0,
        rationale="demo",
        evidence_refs=["evidence_pack:demo"],
    )
    validation = StrategyValidator().validate_spec(spec)
    runtime_context = build_strategy_compile_runtime_context(
        dataset_version="ds_request",
        start="2024-01-01",
        end="2024-03-31",
        execution_model="next_open",
        run_time_utc="14:00",
        commission_bps=4.0,
        slippage_bps=6.0,
        provenance_mode="user_requested",
    )
    compilation = build_strategy_compilation_plan(
        spec,
        validation,
        runtime_context=runtime_context,
    )

    request = build_strategy_backtest_request(
        strategy_id=spec.strategy_id,
        strategy_version=spec.strategy_version,
        market=spec.market,
        runtime_context=runtime_context,
        constraints={"strategy_family": spec.strategy_family},
        factor_versions=[{"factor_id": "factor_demo", "version": "factor-demo-v1"}],
        evaluation_plan={"seed": 7},
        strategy_validation=validation,
        strategy_compilation=compilation,
    )

    assert request.dataset_version == "ds_request"
    assert request.execution_model == "next_open"
    assert request.cost_model.commission_bps == 4.0
    assert request.cost_model.slippage_bps == 6.0
    assert request.constraints["execution_model"] == "next_open"
    assert request.constraints["run_time_utc"] == "14:00"
    assert isinstance(request.evaluation_plan, BacktestEvaluationPlan)
    assert request.evaluation_plan.schema_version == "backtest_evaluation_plan.v1"
    assert request.evaluation_plan.strategy_validation is not None
    assert request.evaluation_plan.strategy_validation.schema_version == "strategy_validation.v1"
    assert request.evaluation_plan.strategy_compilation is not None
    assert request.evaluation_plan.strategy_compilation.schema_version == "strategy_compilation.v1"
    assert request.evaluation_plan.request_input_profile is not None
    assert request.evaluation_plan.request_input_profile.schema_version == "strategy_backtest_request_input_profile.v1"
    assert request.evaluation_plan.request_input_profile.provenance_mode == "user_requested"
    assert request.evaluation_plan.factor_versions[0].version == "factor-demo-v1"
    assert request.evaluation_plan.window is not None
    assert request.evaluation_plan.window.start == "2024-01-01"


def test_strategy_compilation_tracks_runtime_overlay_and_decision_override() -> None:
    spec = StrategySpec(
        strategy_id="demo_strategy",
        strategy_version="0.1.0",
        market="JP",
        strategy_family="regime_allocation",
        rebalance="weekly",
        lookback_days=45,
        signal_threshold=0.001,
        position_sizing="risk_budget",
        risk_budget="vol_target_8pct",
        max_position=0.2,
        stop_loss=0.06,
        leverage_limit=1.2,
        constraints={"leverage_limit": 1.2},
        rationale="demo",
        evidence_refs=["evidence_pack:demo"],
    )
    decision = StrategyDecision.model_validate(
        {
            "selected": {
                "name": "RiskBudgetAllocator",
                "spec": {
                    "strategy_family": "regime_allocation",
                    "rebalance": "weekly",
                    "lookback_days": 45,
                    "signal_threshold": 0.001,
                    "position_sizing": "risk_budget",
                    "risk_budget": "vol_target_8pct",
                    "max_position": 0.2,
                    "leverage_limit": 1.0,
                },
                "rationale": "demo",
                "tradeoff_summary": "demo",
            },
        }
    )
    validation = StrategyValidator().validate_spec(spec, decision=decision)

    plan = build_strategy_compilation_plan(
        spec,
        validation,
        decision=decision,
        runtime_context=build_strategy_compile_runtime_context(
            dataset_version="ds_demo",
            start="2024-01-01",
            end="2024-02-01",
            execution_model="next_open",
            commission_bps=5.0,
            slippage_bps=8.0,
            provenance_mode="pipeline_managed",
        ),
    )

    assert plan.compile_ready is True
    assert any(row.output_path == "request.execution_model" for row in plan.overlays)
    leverage_overlay = next(row for row in plan.overlays if row.output_path == "constraints.leverage_limit")
    assert leverage_overlay.overridden_source_path == "selected.spec.leverage_limit"
    assert plan.compilation_profile.schema_version == "strategy_compilation_profile.v1"
    assert plan.compilation_policy is not None
    assert plan.compilation_policy.schema_version == "strategy_compilation_policy.v1"
    assert plan.compilation_policy.rule_surface_id == "strategy_compilation.backtest.v1"
    assert plan.compilation_policy.status == "allowed_with_warning"
    trading_session_check = next(row for row in plan.compilation_policy.checks if row.code == "trading_session_coverage_gap")
    assert trading_session_check.rule_id == "migration.trading_session_coverage_gap"
    assert trading_session_check.fact_source == "migration_checker.warning_codes"
    assert any(row.output_path == "request.execution_model" for row in plan.compilation_profile.override_policies)
    assert any(row.output_path == "constraints.leverage_limit" for row in plan.compilation_profile.override_policies)
    assert any(
        row.output_path == "constraints.strategy_family" and row.classification == "user_configurable"
        for row in plan.compilation_profile.input_policies
    )
    assert any(row.output_path == "environment.run_time_utc" for row in plan.compilation_profile.input_policies)


def test_strategy_compilation_policy_blocks_unsupported_execution_model() -> None:
    spec = StrategySpec(
        strategy_id="demo_strategy",
        strategy_version="0.1.0",
        market="US",
        strategy_family="trend",
        rebalance="weekly",
        lookback_days=20,
        signal_threshold=0.0,
        position_sizing="risk_budget",
        risk_budget="vol_target_10pct",
        max_position=0.12,
        stop_loss=0.06,
        leverage_limit=1.0,
        rationale="demo",
        evidence_refs=["evidence_pack:demo"],
    )
    validation = StrategyValidator().validate_spec(spec)

    plan = build_strategy_compilation_plan(
        spec,
        validation,
        runtime_context=build_strategy_compile_runtime_context(
            dataset_version="ds_demo",
            start="2024-01-01",
            end="2024-02-01",
            execution_model="same_bar_close",
            commission_bps=2.0,
            slippage_bps=4.0,
            provenance_mode="pipeline_managed",
        ),
    )

    assert plan.compile_ready is False
    assert plan.compilation_policy is not None
    assert plan.compilation_policy.status == "blocked"
    execution_check = next(row for row in plan.compilation_policy.checks if row.code == "execution_model_supported")
    assert execution_check.outcome == "blocked"
    assert execution_check.rule_id == "runtime.execution_model_unsupported"
    assert execution_check.fact_source == "backtest_runner.supported_execution_models"


def test_agent_output_contract() -> None:
    output = AgentOutput(summary="ok", confidence=0.8)
    assert output.summary == "ok"


def test_factor_report_contract() -> None:
    report = FactorReport(
        factor_id="momentum_1d",
        factor_version="0.1.0",
        dataset_version="ds_v1",
        market="US",
        observation_count=120,
        ic_mean=0.02,
        ic_std=0.11,
        rank_ic_mean=0.03,
        rank_ic_std=0.09,
        t_stat=2.1,
        decay_curve=[DecayPoint(lag=1, ic=0.02), DecayPoint(lag=2, ic=0.01)],
    )
    assert report.factor_id == "momentum_1d"


def test_trading_domain_contract() -> None:
    order = Order(
        instrument_id="us_eq_aapl",
        side="buy",
        quantity=100,
        order_type="market",
    )
    assert order.status == "new"
