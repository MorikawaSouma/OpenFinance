from datetime import date
from pathlib import Path

from openfinance.core.audit import FileAuditStore
from openfinance.data.mock_factory import MockDataFactory, MockDatasetConfig
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.backtest.report import BacktestRequest
from openfinance.quant.backtest.run_registry import RunRegistry
from openfinance.quant.backtest.runner import BacktestRunner


def test_backtest_runner_end_to_end(tmp_path: Path) -> None:
    dataset_registry = DatasetRegistry(
        registry_file=str(tmp_path / "registry" / "datasets.jsonl"),
        data_root=str(tmp_path / "data"),
    )
    run_registry = RunRegistry(str(tmp_path / "registry" / "runs.jsonl"))
    audit_store = FileAuditStore(str(tmp_path / "registry" / "audit.jsonl"))

    dataset = MockDataFactory().generate(
        MockDatasetConfig(
            dataset_id="runner_demo",
            market="US",
            symbol="AAPL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 2, 1),
            seed=123,
        )
    )
    entry = dataset_registry.register(dataset)

    runner = BacktestRunner(
        dataset_registry=dataset_registry,
        run_registry=run_registry,
        audit_store=audit_store,
        report_root=str(tmp_path / "reports"),
    )
    report = runner.run(
        BacktestRequest(
            dataset_version=entry.dataset_version,
            strategy_id="placeholder_strategy",
            strategy_version="0.1.0",
            market="US",
            start="2024-01-01",
            end="2024-02-01",
        )
    )

    assert report.dataset_version == entry.dataset_version
    assert "total_return" in report.metrics
    assert "order_count" in report.metrics
    assert "trade_count" in report.metrics
    assert isinstance(report.orders, list)
    assert isinstance(report.trades, list)
    assert isinstance(report.positions, list)
    assert isinstance(report.positions_ts, list)
    assert "commission" in report.cost_breakdown
    assert "slippage" in report.cost_breakdown
    assert "commission_sum" in report.cost_breakdown
    assert "slippage_sum" in report.cost_breakdown
    assert "instrument_pnl_contrib" in report.attribution
    assert "sector_pnl_contrib" in report.attribution
    assert len(report.equity_curve) > 0
    assert report.metrics["trade_count"] == len(report.trades)
    assert isinstance(report.factor_versions, list)
    assert len(report.factor_versions) >= 1
    assert report.factor_versions[0].version
    if report.orders:
        assert hasattr(report.orders[0], "reason_code")
        assert hasattr(report.orders[0], "reason_msg")
    assert len(run_registry.list_entries()) == 1
    assert len(audit_store.list_all()) >= 1
