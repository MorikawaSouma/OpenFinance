from datetime import date
from pathlib import Path

from openfinance.core.audit import FileAuditStore
from openfinance.data.mock_factory import MockDataFactory, MockDatasetConfig
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.backtest.report import BacktestRequest
from openfinance.quant.backtest.run_registry import RunRegistry
from openfinance.quant.backtest.runner import BacktestRunner


def _runner(tmp_path: Path) -> tuple[DatasetRegistry, FileAuditStore, BacktestRunner]:
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
    return dataset_registry, audit_store, runner


def test_pr22_max_sector_exposure_is_auto_adjusted_and_audited(tmp_path: Path) -> None:
    dataset_registry, audit_store, runner = _runner(tmp_path / "sector_cap")
    dataset = MockDataFactory().generate(
        MockDatasetConfig(
            dataset_id="pr22_sector_cap",
            market="US",
            symbol="AAPL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 2, 29),
            seed=222,
        )
    )
    entry = dataset_registry.register(dataset)
    report = runner.run(
        BacktestRequest(
            dataset_version=entry.dataset_version,
            strategy_id="pr22_sector_cap",
            strategy_version="0.1.0",
            market="US",
            start="2024-01-01",
            end="2024-02-29",
            constraints={
                "strategy_family": "trend",
                "rebalance": "daily",
                "lookback_days": 2,
                "signal_threshold": -1.0,
                "max_position": 0.8,
                "leverage_limit": 1.0,
                "portfolio_optimizer": "score_based",
                "max_position_weight": 0.8,
                "max_gross_leverage": 1.0,
                "max_sector_exposure": 0.2,
                "sector_neutral": False,
                "auto_round_lot": False,
            },
        )
    )

    actions = report.diagnostics.get("constraint_actions", [])
    assert any(action.get("action") == "max_sector_exposure_scale" for action in actions if isinstance(action, dict))
    assert any(
        float(action.get("after_gross", 0.0)) <= 0.200001
        for action in actions
        if isinstance(action, dict) and action.get("action") == "max_sector_exposure_scale"
    )
    audit_rows = audit_store.list_all()
    assert any(
        row.event_type == "backtest.constraint.action" and row.payload.get("action") == "max_sector_exposure_scale"
        for row in audit_rows
    )


def test_pr22_invalid_ex_ante_constraints_reject_orders_with_reason_code(tmp_path: Path) -> None:
    dataset_registry, _, runner = _runner(tmp_path / "invalid_constraints")
    dataset = MockDataFactory().generate(
        MockDatasetConfig(
            dataset_id="pr22_invalid_constraints",
            market="US",
            symbol="AAPL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            seed=333,
        )
    )
    entry = dataset_registry.register(dataset)
    report = runner.run(
        BacktestRequest(
            dataset_version=entry.dataset_version,
            strategy_id="pr22_invalid_constraints",
            strategy_version="0.1.0",
            market="US",
            start="2024-01-01",
            end="2024-01-31",
            constraints={
                "strategy_family": "trend",
                "rebalance": "daily",
                "lookback_days": 2,
                "signal_threshold": -1.0,
                "max_position": 0.6,
                "portfolio_optimizer": "score_based",
                "max_position_weight": 0.6,
                "max_gross_leverage": 1.0,
                "max_sector_exposure": 0.0,
                "auto_round_lot": False,
            },
        )
    )
    rejected = [order for order in report.orders if order.status == "rejected"]
    assert len(rejected) > 0
    assert any(order.reason_code == "EX_ANTE_INVALID_MAX_SECTOR_EXPOSURE" for order in rejected)
