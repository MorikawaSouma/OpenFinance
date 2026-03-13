import time
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.core.audit import FileAuditStore
from openfinance.data.mock_factory import MockDataFactory, MockDatasetConfig
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.backtest.meta_runner import MetaBacktestConfig, MetaBacktestRunner
from openfinance.quant.backtest.report import BacktestRequest, CostModel
from openfinance.quant.backtest.run_registry import RunRegistry
from openfinance.quant.backtest.runner import BacktestRunner


def _wait_done(client: TestClient, task_id: str, timeout: float = 8.0) -> dict:
    start = time.time()
    while time.time() - start <= timeout:
        row = client.get(f"/workbench/tasks/{task_id}").json()
        if row["status"] in {"done", "failed", "error"}:
            return row
        time.sleep(0.1)
    raise TimeoutError(task_id)


def test_meta_backtest_runner_generates_robustness_report(tmp_path: Path) -> None:
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

    dataset = MockDataFactory().generate(
        MockDatasetConfig(
            dataset_id="pr23_meta_runner",
            market="US",
            symbol="AAPL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 2, 20),
            seed=551,
            inject_high_vol_segment=True,
            high_vol_start_day=10,
            high_vol_end_day=25,
            high_vol_scale=4.0,
        )
    )
    entry = dataset_registry.register(dataset)
    base_request = BacktestRequest(
        dataset_version=entry.dataset_version,
        strategy_id="robustness_test",
        strategy_version="robust-v1",
        market="US",
        start="2024-01-01",
        end="2024-02-20",
        cost_model=CostModel(commission_bps=4.0, slippage_bps=7.0),
        constraints={
            "strategy_family": "trend",
            "rebalance": "weekly",
            "lookback_days": 20,
            "signal_threshold": 0.0,
            "max_position": 0.12,
            "leverage_limit": 1.0,
        },
    )
    report = MetaBacktestRunner(runner).run(base_request, MetaBacktestConfig(max_variants=8))
    assert report.summary.variant_count >= 6
    assert len(report.variants) == report.summary.variant_count
    assert len(report.table) == report.summary.variant_count
    groups = {row.group for row in report.variants}
    assert "cost_sensitivity" in groups
    assert "param_perturbation" in groups
    impact = report.summary.cost_double_impact
    assert "sharpe_delta" in impact
    assert "max_drawdown_delta" in impact
    assert len(report.regime_metrics) >= 2
    assert {row.regime_id for row in report.regime_metrics} >= {"low_vol", "high_vol"}
    assert len(report.stress_metrics) >= 2
    low_row = next(row for row in report.regime_metrics if row.regime_id == "low_vol")
    high_row = next(row for row in report.regime_metrics if row.regime_id == "high_vol")
    assert (
        float(high_row.metrics.get("max_drawdown", 0.0)) != float(low_row.metrics.get("max_drawdown", 0.0))
        or float(high_row.metrics.get("sharpe", 0.0)) != float(low_row.metrics.get("sharpe", 0.0))
    )
    assert report.worst_case_summary.source_type in {"regime", "stress"}
    assert report.worst_case_summary.scenario_id != ""


def test_robustness_route_generates_variant_table() -> None:
    client = TestClient(app)
    ds_task = client.post(
        "/workbench/datasets/generate",
        json={
            "dataset_id": "pr23_route_dataset",
            "market": "US",
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-02-15",
            "seed": 552,
            "base_price": 100.0,
            "inject_high_vol_segment": True,
            "high_vol_start_day": 8,
            "high_vol_end_day": 22,
            "high_vol_scale": 4.0,
        },
    )
    assert ds_task.status_code == 200
    ds_done = _wait_done(client, ds_task.json()["task_id"])
    assert ds_done["status"] == "done"
    dataset_version = ds_done["result"]["dataset_version"]

    resp = client.post(
        "/workbench/reports/robustness/run",
        json={
            "dataset_version": dataset_version,
            "strategy_id": "robustness_route_test",
            "strategy_version": "robust-route-v1",
            "market": "US",
            "start": "2024-01-01",
            "end": "2024-02-15",
            "strategy_family": "trend",
            "rebalance": "weekly",
            "lookback_days": 20,
            "signal_threshold": 0.0,
            "commission_bps": 5.0,
            "slippage_bps": 8.0,
            "max_variants": 7,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["summary"]["variant_count"] >= 6
    assert len(payload["variants"]) == payload["summary"]["variant_count"]
    assert len(payload["table"]) == payload["summary"]["variant_count"]
    assert "cost_double_impact" in payload["summary"]
    assert "sharpe_delta" in payload["summary"]["cost_double_impact"]
    assert len(payload["regime_metrics"]) >= 2
    regime_ids = {row["regime_id"] for row in payload["regime_metrics"]}
    assert {"low_vol", "high_vol"}.issubset(regime_ids)
    assert len(payload["stress_metrics"]) >= 2
    assert payload["worst_case_summary"]["source_type"] in {"regime", "stress"}
    assert payload["worst_case_summary"]["scenario_id"] != ""


def test_robustness_route_creates_parent_child_tasks_with_result_links() -> None:
    client = TestClient(app)
    ds_task = client.post(
        "/workbench/datasets/generate",
        json={
            "dataset_id": "pr55_task_tree_dataset",
            "market": "US",
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-02-15",
            "seed": 560,
            "base_price": 100.0,
        },
    )
    assert ds_task.status_code == 200
    ds_done = _wait_done(client, ds_task.json()["task_id"])
    assert ds_done["status"] == "done"
    dataset_version = ds_done["result"]["dataset_version"]

    resp = client.post(
        "/workbench/reports/robustness/run",
        json={
            "dataset_version": dataset_version,
            "strategy_id": "robustness_obs_test",
            "strategy_version": "robust-obs-v1",
            "market": "US",
            "start": "2024-01-01",
            "end": "2024-02-15",
            "strategy_family": "trend",
            "rebalance": "weekly",
            "lookback_days": 20,
            "signal_threshold": 0.0,
            "commission_bps": 5.0,
            "slippage_bps": 8.0,
            "max_variants": 8,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    parent_task_id = str(payload.get("parent_task_id") or "")
    child_task_ids = payload.get("child_task_ids") or []
    assert parent_task_id
    assert len(child_task_ids) >= 6

    tasks = client.get("/workbench/tasks").json()
    parent = next((row for row in tasks if str(row.get("task_id")) == parent_task_id), None)
    assert parent is not None
    assert parent["status"] == "done"
    assert int(parent.get("progress", 0)) == 100
    assert str((parent.get("result_ref") or {}).get("open_path") or "").startswith("/reports")

    children = [row for row in tasks if str(row.get("parent_task_id") or "") == parent_task_id]
    assert len(children) >= 6
    for row in children:
        assert row["status"] == "done"
        result_ref = row.get("result_ref") or {}
        assert str(result_ref.get("run_id") or "")
        assert str(result_ref.get("open_path") or "").startswith("/reports/")
