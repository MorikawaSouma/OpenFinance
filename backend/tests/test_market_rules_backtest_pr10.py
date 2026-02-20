from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from openfinance.core.audit import FileAuditStore
from openfinance.data.contracts.dataset import OHLCVBar
from openfinance.data.mock_factory import MockDataFactory, MockDatasetConfig
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.backtest.report import BacktestRequest
from openfinance.quant.backtest.run_registry import RunRegistry
from openfinance.quant.backtest.runner import BacktestRunner


def _build_runner(tmp_path: Path) -> tuple[DatasetRegistry, RunRegistry, FileAuditStore, BacktestRunner]:
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


def _cn_dataset_for_t1(tmp_path: Path) -> tuple[DatasetRegistry, str]:
    dataset_registry = DatasetRegistry(
        registry_file=str(tmp_path / "registry" / "datasets.jsonl"),
        data_root=str(tmp_path / "data"),
    )
    dataset = MockDataFactory().generate(
        MockDatasetConfig(
            dataset_id="cn_t1_demo",
            market="CN",
            symbol="600519.SS",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 15),
            seed=101,
        )
    )
    bars: list[OHLCVBar] = []
    base_day = date(2024, 1, 1)
    for idx in range(10):
        ts = datetime.combine(base_day + timedelta(days=idx), time(15, 0), tzinfo=UTC)
        open_px = 100.0 + idx
        close_px = open_px + 2.0
        bars.append(
            OHLCVBar(
                ts=ts,
                open=open_px,
                high=close_px * 1.01,
                low=open_px * 0.99,
                close=close_px,
                volume=1_000_000 + idx * 1000,
                spread_bps=6.0,
                is_missing=False,
                is_outlier=False,
            )
        )
    dataset.market = bars
    entry = dataset_registry.register(dataset)
    return dataset_registry, entry.dataset_version


def test_cn_t_plus_one_and_lot_rejects_are_enforced_and_audited(tmp_path: Path) -> None:
    dataset_registry, dataset_version = _cn_dataset_for_t1(tmp_path / "cn")
    run_registry = RunRegistry(str(tmp_path / "cn" / "registry" / "runs.jsonl"))
    audit_store = FileAuditStore(str(tmp_path / "cn" / "registry" / "audit.jsonl"))
    runner = BacktestRunner(
        dataset_registry=dataset_registry,
        run_registry=run_registry,
        audit_store=audit_store,
        report_root=str(tmp_path / "cn" / "reports"),
    )

    # Case 1: odd-lot attempt should fail (auto_round_lot disabled).
    odd_lot_report = runner.run(
        BacktestRequest(
            dataset_version=dataset_version,
            strategy_id="cn_rule_test",
            strategy_version="0.1.0",
            market="CN",
            start="2024-01-01",
            end="2024-01-20",
                constraints={
                    "strategy_family": "mean_reversion",
                    "rebalance": "daily",
                    "lookback_days": 2,
                    "signal_threshold": 1.0,
                    "auto_round_lot": False,
                    "initial_cash": 20_000.0,
                    "max_position": 0.12,
                },
            )
    )
    assert any(order.reason == "cn_lot_must_be_100_multiple" for order in odd_lot_report.orders)
    assert any(
        order.reason_code == "CN_LOT_SIZE" and "100股" in order.user_friendly_msg
        for order in odd_lot_report.orders
        if order.status == "rejected"
    )

    # Case 2: T+0 sell attempt should fail under T+1 even when lot rounding is enabled.
    t1_report = runner.run(
        BacktestRequest(
            dataset_version=dataset_version,
            strategy_id="cn_rule_test",
            strategy_version="0.1.1",
            market="CN",
            start="2024-01-01",
            end="2024-01-20",
            constraints={
                "strategy_family": "mean_reversion",
                "rebalance": "daily",
                "lookback_days": 2,
                "signal_threshold": 0.0,
                "auto_round_lot": True,
                "initial_cash": 2_000_000.0,
                "max_position": 0.2,
            },
        )
    )
    assert any(order.reason == "t_plus_one_blocked" for order in t1_report.orders)
    assert any(
        order.reason_code == "CN_T1_SELL_BLOCKED" and "T+1" in order.user_friendly_msg
        for order in t1_report.orders
        if order.status == "rejected"
    )

    audit_rows = audit_store.list_all()
    reject_rows = [row for row in audit_rows if row.event_type == "backtest.order.rejected"]
    assert len(reject_rows) >= 2
    reasons = {str(row.payload.get("reason")) for row in reject_rows}
    reason_codes = {str(row.payload.get("reason_code")) for row in reject_rows}
    assert "cn_lot_must_be_100_multiple" in reasons
    assert "t_plus_one_blocked" in reasons
    assert "CN_LOT_SIZE" in reason_codes
    assert "CN_T1_SELL_BLOCKED" in reason_codes


def test_crypto_7x24_fractional_and_min_notional(tmp_path: Path) -> None:
    dataset_registry, _, _, runner = _build_runner(tmp_path / "crypto")
    dataset = MockDataFactory().generate(
        MockDatasetConfig(
            dataset_id="crypto_rule_demo",
            market="CRYPTO",
            symbol="BTCUSDT",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 8),
            seed=99,
        )
    )
    entry = dataset_registry.register(dataset)

    assert all(day.is_open for day in dataset.trading_calendar)

    min_notional_report = runner.run(
        BacktestRequest(
            dataset_version=entry.dataset_version,
            strategy_id="crypto_rule_test",
            strategy_version="0.1.0",
            market="CRYPTO",
            start="2024-01-01",
            end="2024-01-08",
                constraints={
                    "strategy_family": "mean_reversion",
                    "rebalance": "daily",
                    "lookback_days": 2,
                    "signal_threshold": 1.0,
                    "auto_round_lot": False,
                    "initial_cash": 5.0,
                    "max_position": 0.1,
                },
            )
        )
    assert any(order.reason == "below_crypto_min_notional" for order in min_notional_report.orders)

    fractional_report = runner.run(
        BacktestRequest(
            dataset_version=entry.dataset_version,
            strategy_id="crypto_rule_test",
            strategy_version="0.1.1",
            market="CRYPTO",
            start="2024-01-01",
            end="2024-01-08",
                constraints={
                    "strategy_family": "mean_reversion",
                    "rebalance": "daily",
                    "lookback_days": 2,
                    "signal_threshold": 1.0,
                    "auto_round_lot": False,
                    "initial_cash": 12_345.0,
                    "max_position": 0.3,
                },
        )
    )
    assert any(abs(trade.qty - round(trade.qty)) > 1e-6 for trade in fractional_report.trades)


def test_jp_non_session_orders_are_queued(tmp_path: Path) -> None:
    dataset_registry, _, _, runner = _build_runner(tmp_path / "jp")
    dataset = MockDataFactory().generate(
        MockDatasetConfig(
            dataset_id="jp_rule_demo",
            market="JP",
            symbol="7203.T",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 20),
            seed=21,
        )
    )
    # Mock bars default to 16:00 UTC in factory, outside JP day session in simplified rule.
    entry = dataset_registry.register(dataset)
    report = runner.run(
        BacktestRequest(
            dataset_version=entry.dataset_version,
            strategy_id="jp_rule_test",
            strategy_version="0.1.0",
            market="JP",
            start="2024-01-01",
            end="2024-01-20",
                constraints={
                    "strategy_family": "mean_reversion",
                    "rebalance": "daily",
                    "lookback_days": 2,
                    "signal_threshold": 1.0,
                    "auto_round_lot": True,
                    "initial_cash": 2_000_000.0,
                    "max_position": 0.2,
                },
        )
    )
    assert any("queued_until_next_session" in order.reason for order in report.orders)
