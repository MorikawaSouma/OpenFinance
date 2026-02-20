from datetime import date
from pathlib import Path

from openfinance.core.audit import FileAuditStore
from openfinance.data.mock_factory import MockDataFactory, MockDatasetConfig
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.backtest.report import BacktestRequest, CostModel
from openfinance.quant.backtest.run_registry import RunRegistry
from openfinance.quant.backtest.runner import BacktestRunner


def test_cost_doubling_changes_cost_breakdown(tmp_path: Path) -> None:
    dataset_registry = DatasetRegistry(
        registry_file=str(tmp_path / "registry" / "datasets.jsonl"),
        data_root=str(tmp_path / "data"),
    )
    run_registry = RunRegistry(str(tmp_path / "registry" / "runs.jsonl"))
    audit_store = FileAuditStore(str(tmp_path / "registry" / "audit.jsonl"))

    dataset = MockDataFactory().generate(
        MockDatasetConfig(
            dataset_id="pr15_cost",
            market="US",
            symbol="AAPL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31),
            seed=55,
        )
    )
    entry = dataset_registry.register(dataset)
    runner = BacktestRunner(
        dataset_registry=dataset_registry,
        run_registry=run_registry,
        audit_store=audit_store,
        report_root=str(tmp_path / "reports"),
    )

    low_cost = runner.run(
        BacktestRequest(
            dataset_version=entry.dataset_version,
            strategy_id="pr15",
            strategy_version="low_cost",
            market="US",
            start="2024-01-01",
            end="2024-03-31",
            cost_model=CostModel(commission_bps=5, slippage_bps=6),
        )
    )
    high_cost = runner.run(
        BacktestRequest(
            dataset_version=entry.dataset_version,
            strategy_id="pr15",
            strategy_version="high_cost",
            market="US",
            start="2024-01-01",
            end="2024-03-31",
            cost_model=CostModel(commission_bps=10, slippage_bps=12),
        )
    )

    assert high_cost.cost_breakdown["commission_sum"] > low_cost.cost_breakdown["commission_sum"]
    assert high_cost.cost_breakdown["slippage_sum"] > low_cost.cost_breakdown["slippage_sum"]
    assert high_cost.cost_breakdown["total"] > low_cost.cost_breakdown["total"]
