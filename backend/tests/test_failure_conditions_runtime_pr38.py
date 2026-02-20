from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.api.routes_trading import _service
from openfinance.core.audit import FileAuditStore
from openfinance.core.config import settings
from openfinance.core.events import event_bus
from openfinance.data.mock_factory import MockDataFactory, MockDatasetConfig
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.backtest.report import BacktestRequest
from openfinance.quant.backtest.run_registry import RunRegistry
from openfinance.quant.backtest.runner import BacktestRunner


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


def test_pr38_backtest_liquidity_drought_recorded_in_diagnostics(tmp_path: Path) -> None:
    dataset_registry, runner = _runner(tmp_path / "backtest_failure_checks")
    dataset = MockDataFactory().generate(
        MockDatasetConfig(
            dataset_id="pr38_liquidity_backtest",
            market="US",
            symbol="AAPL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 2, 29),
            seed=404,
        )
    )
    entry = dataset_registry.register(dataset)

    report = runner.run(
        BacktestRequest(
            dataset_version=entry.dataset_version,
            strategy_id="pr38_liquidity_backtest",
            strategy_version="0.1.0",
            market="US",
            start="2024-01-01",
            end="2024-02-29",
            constraints={
                "strategy_family": "trend",
                "rebalance": "daily",
                "lookback_days": 5,
                "signal_threshold": 0.0,
                "max_position": 0.2,
                "failure_conditions": [
                    {
                        "code": "LIQUIDITY_DROUGHT",
                        "params": {
                            "min_volume_ratio": 1.05,
                            "max_spread_ratio": 1.00,
                        },
                        "severity_thresholds": {"warn": 0.01, "block": 5.0},
                        "applies_to": "strategy",
                    }
                ],
                "failure_check_interval_bars": 1,
            },
        )
    )
    checks = report.diagnostics.get("failure_condition_checks", {})
    events = checks.get("events", []) if isinstance(checks, dict) else []
    assert isinstance(events, list)
    assert any((row.get("code") == "LIQUIDITY_DROUGHT") for row in events if isinstance(row, dict))


def test_pr38_paper_block_failure_condition_triggers_kill_switch(tmp_path: Path) -> None:
    settings.approval_db_file = str(tmp_path / "registry" / "approvals.sqlite3")
    settings.audit_log_file = str(tmp_path / "registry" / "audit.jsonl")
    settings.risk_events_db_file = str(tmp_path / "registry" / "risk_events.sqlite3")
    settings.kill_switch_enabled = False
    _service.cache_clear()

    client = TestClient(app)
    before = client.get("/trading/status")
    assert before.status_code == 200
    assert before.json()["kill_switch_enabled"] is False

    blocked = client.post(
        "/trading/paper/orders",
        json={
            "instrument_id": "us_eq_aapl",
            "side": "buy",
            "quantity": 10,
            "order_type": "market",
            "plan_id": "plan_pr38_failure_block",
            "failure_conditions": [
                {
                    "code": "LIQUIDITY_DROUGHT",
                    "params": {"min_volume_ratio": 0.9, "max_spread_ratio": 1.0},
                    "severity_thresholds": {"warn": 0.05, "block": 0.1},
                    "applies_to": "strategy",
                }
            ],
            "failure_context": {
                "rolling_volume": 100000.0,
                "rolling_volume_avg": 300000.0,
                "spread_bps": 30.0,
                "rolling_spread_bps_avg": 10.0,
            },
        },
    )
    assert blocked.status_code == 200
    payload = blocked.json()
    assert payload["accepted"] is False
    assert payload["reason"] == "failure_condition_blocked"

    after = client.get("/trading/status")
    assert after.status_code == 200
    assert after.json()["kill_switch_enabled"] is True

    events = client.get("/trading/risk/events?limit=20")
    assert events.status_code == 200
    rows = events.json()
    assert any(row["event_type"] == "failure_condition_block" for row in rows)
    assert any("LIQUIDITY_DROUGHT" in row["message"] for row in rows)

    sse_rows = [row for row in event_bus.snapshot() if row.get("type") == "risk.event"]
    assert any((row.get("payload") or {}).get("event_type") == "failure_condition_block" for row in sse_rows)
