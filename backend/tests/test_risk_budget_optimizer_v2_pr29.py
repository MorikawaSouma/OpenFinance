from datetime import date
from pathlib import Path

from openfinance.core.audit import FileAuditStore
from openfinance.data.mock_factory import MockDataFactory, MockDatasetConfig
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.backtest.report import BacktestRequest
from openfinance.quant.backtest.run_registry import RunRegistry
from openfinance.quant.backtest.runner import BacktestRunner
from openfinance.quant.portfolio import OptimizerInput, RiskBudgetOptimizerV2


def test_pr29_risk_budget_optimizer_v2_tracks_60_40_budget() -> None:
    optimizer = RiskBudgetOptimizerV2()
    inp = OptimizerInput(
        scores={"ASSET_A": 1.0, "ASSET_B": 1.0},
        expected_returns={"ASSET_A": 0.02, "ASSET_B": 0.02},
        volatilities={"ASSET_A": 0.20, "ASSET_B": 0.30},
        covariance={
            "ASSET_A": {"ASSET_A": 0.20**2, "ASSET_B": 0.012},
            "ASSET_B": {"ASSET_A": 0.012, "ASSET_B": 0.30**2},
        },
        risk_budget={"ASSET_A": 0.6, "ASSET_B": 0.4},
        gross_target=1.0,
    )
    result = optimizer.optimize(inp)
    achieved = result.diagnostics.get("achieved_budget", {})
    assert isinstance(achieved, dict)
    assert abs(float(achieved.get("ASSET_A", 0.0)) - 0.6) <= 0.15
    assert abs(float(achieved.get("ASSET_B", 0.0)) - 0.4) <= 0.15
    assert "covariance" in result.diagnostics
    # Higher volatility asset should carry less weight under same budget intent.
    assert abs(result.weights["ASSET_B"]) < abs(result.weights["ASSET_A"])


def _runner(tmp_path: Path) -> tuple[DatasetRegistry, BacktestRunner]:
    dataset_registry = DatasetRegistry(
        registry_file=str(tmp_path / "registry" / "datasets.jsonl"),
        data_root=str(tmp_path / "data"),
    )
    runner = BacktestRunner(
        dataset_registry=dataset_registry,
        run_registry=RunRegistry(str(tmp_path / "registry" / "runs.jsonl")),
        audit_store=FileAuditStore(str(tmp_path / "registry" / "audit.jsonl")),
        report_root=str(tmp_path / "reports"),
    )
    return dataset_registry, runner


def test_pr29_runner_reports_risk_contribution_and_high_vol_weight_drop(tmp_path: Path) -> None:
    dataset_registry, runner = _runner(tmp_path / "runner")
    dataset = MockDataFactory().generate(
        MockDatasetConfig(
            dataset_id="pr29_runner",
            market="US",
            symbol="AAPL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31),
            seed=529,
        )
    )
    entry = dataset_registry.register(dataset)
    report = runner.run(
        BacktestRequest(
            dataset_version=entry.dataset_version,
            strategy_id="pr29_cov_budget",
            strategy_version="0.1.0",
            market="US",
            start="2024-01-01",
            end="2024-03-31",
            constraints={
                "strategy_family": "trend",
                "rebalance": "daily",
                "lookback_days": 10,
                "cov_lookback_days": 12,
                "signal_threshold": -1.0,
                "position_sizing": "risk_budget",
                "portfolio_optimizer": "risk_budget_v2",
                "portfolio_universe": ["AAPL", "RISKY"],
                "risk_budget_vector": {"AAPL": 0.6, "RISKY": 0.4},
                "high_vol_assets": ["RISKY"],
                "high_vol_shock_start": 25,
                "high_vol_shock_multiplier": 4.0,
                "max_position_weight": 1.0,
                "max_gross_leverage": 1.0,
                "max_sector_exposure": 1.0,
                "auto_round_lot": False,
            },
        )
    )
    rc_ts = report.diagnostics.get("risk_contribution_ts", [])
    assert isinstance(rc_ts, list)
    assert len(rc_ts) >= 8
    budget_dev = report.diagnostics.get("budget_deviation", {})
    assert isinstance(budget_dev, dict)
    assert float(budget_dev.get("mean_l1", 0.0)) >= 0.0
    assert "budget_deviation_mean" in report.metrics
    assert report.control_optimizer_details is not None
    assert report.control_optimizer_details.schema_version == "strategy_runtime_control_optimizer.v1"
    assert report.control_optimizer_details.budget_detail.observations >= 1
    assert len(report.control_optimizer_details.risk_contribution_points) >= 1
    assert len(report.control_optimizer_details.optimizer_diagnostics) >= 1
    assert report.control_action_deep_details is not None
    assert report.control_action_deep_details.schema_version == "strategy_runtime_control_action_deep.v1"
    assert report.control_action_deep_details.budget_breakdown.observations >= 1
    assert report.control_action_deep_details.risk_contribution_breakdown.point_count >= 1
    assert len(report.control_action_deep_details.optimizer_steps) >= 1

    early_rows = [row for idx, row in enumerate(rc_ts) if idx < max(2, len(rc_ts) // 3)]
    late_rows = [row for idx, row in enumerate(rc_ts) if idx >= max(2, len(rc_ts) * 2 // 3)]
    assert early_rows and late_rows
    early_risky = sum(float((row.get("weights") or {}).get("RISKY", 0.0)) for row in early_rows) / len(early_rows)
    late_risky = sum(float((row.get("weights") or {}).get("RISKY", 0.0)) for row in late_rows) / len(late_rows)
    assert abs(late_risky) < abs(early_risky)
