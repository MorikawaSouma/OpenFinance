from datetime import date
from pathlib import Path

from openfinance.core.audit import FileAuditStore
from openfinance.data.mock_factory import MockDataFactory, MockDatasetConfig
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.backtest.report import BacktestRequest
from openfinance.quant.backtest.run_registry import RunRegistry
from openfinance.quant.backtest.runner import BacktestRunner


def _runner(tmp_path: Path) -> tuple[DatasetRegistry, RunRegistry, FileAuditStore, BacktestRunner]:
    dataset_registry = DatasetRegistry(
        registry_file=str(tmp_path / "registry" / "datasets.jsonl"),
        data_root=str(tmp_path / "data"),
    )
    run_registry = RunRegistry(str(tmp_path / "registry" / "runs.jsonl"))
    audit_store = FileAuditStore(str(tmp_path / "registry" / "audit.jsonl"))
    runner = BacktestRunner(
        dataset_registry=dataset_registry,
        run_registry=run_registry,
        audit_store=audit_store,
        report_root=str(tmp_path / "reports"),
    )
    return dataset_registry, run_registry, audit_store, runner


def test_high_vol_regime_triggers_risk_actions(tmp_path: Path) -> None:
    dataset_registry, _, _, runner = _runner(tmp_path / "regime")
    dataset = MockDataFactory().generate(
        MockDatasetConfig(
            dataset_id="pr16_regime",
            market="US",
            symbol="AAPL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31),
            seed=77,
            inject_high_vol_segment=True,
            high_vol_start_day=5,
            high_vol_end_day=40,
            high_vol_scale=6.0,
        )
    )
    entry = dataset_registry.register(dataset)
    report = runner.run(
        BacktestRequest(
            dataset_version=entry.dataset_version,
            strategy_id="risk_regime_test",
            strategy_version="0.1.0",
            market="US",
            start="2024-01-01",
            end="2024-03-31",
            constraints={
                "strategy_family": "trend",
                "rebalance": "daily",
                "lookback_days": 3,
                "signal_threshold": 0.0,
                "max_position": 0.2,
                "regime_vol_window": 5,
                "regime_vol_threshold": 0.02,
                "regime_exposure_scale_high_vol": 0.3,
                "regime_pause_new_positions": True,
                "max_drawdown_target": 0.25,
            },
        )
    )
    regime_periods = report.diagnostics.get("regime_periods", [])
    risk_actions = report.diagnostics.get("risk_actions", [])
    assert isinstance(regime_periods, list)
    assert len(regime_periods) >= 1
    assert any(action.get("action") == "regime_enter_high_vol" for action in risk_actions if isinstance(action, dict))
    assert any(action.get("action") == "regime_exposure_scaled" for action in risk_actions if isinstance(action, dict))


def test_drawdown_circuit_breaker_stops_trading_and_audits(tmp_path: Path) -> None:
    dataset_registry, _, audit_store, runner = _runner(tmp_path / "circuit")
    dataset = MockDataFactory().generate(
        MockDatasetConfig(
            dataset_id="pr16_circuit",
            market="US",
            symbol="AAPL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 2, 20),
            seed=91,
            inject_high_vol_segment=True,
            high_vol_start_day=3,
            high_vol_end_day=25,
            high_vol_scale=7.0,
        )
    )
    entry = dataset_registry.register(dataset)
    report = runner.run(
        BacktestRequest(
            dataset_version=entry.dataset_version,
            strategy_id="risk_circuit_test",
            strategy_version="0.1.0",
            market="US",
            start="2024-01-01",
            end="2024-02-20",
            constraints={
                "strategy_family": "trend",
                "rebalance": "daily",
                "lookback_days": 2,
                "signal_threshold": 0.0,
                "max_position": 0.25,
                "regime_vol_window": 4,
                "regime_vol_threshold": 0.02,
                "max_drawdown_target": 0.0,
            },
        )
    )
    risk_actions = report.diagnostics.get("risk_actions", [])
    assert any(
        action.get("action") in {"drawdown_circuit_breaker_flatten", "circuit_breaker_stop_trading"}
        for action in risk_actions
        if isinstance(action, dict)
    )
    risk_mgmt = report.diagnostics.get("risk_management", {})
    assert risk_mgmt.get("stop_trading_triggered") is True
    cb = risk_mgmt.get("circuit_breaker", {})
    assert cb.get("trigger_count", 0) >= 1
    intervals = cb.get("trigger_intervals", [])
    assert isinstance(intervals, list) and len(intervals) >= 1
    assert intervals[0].get("start")
    assert intervals[0].get("end")
    audit_rows = audit_store.list_all()
    assert any(row.event_type == "backtest.risk.action" for row in audit_rows)
