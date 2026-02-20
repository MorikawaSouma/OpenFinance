import time
from datetime import date
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.data.mock_factory import MockDataFactory, MockDatasetConfig
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.factors.engine import FactorEngine
from openfinance.quant.factors.factor_spec import FactorInput, FactorSpec, ValidationPlan
from openfinance.quant.factors.registry import FactorRegistry


def _dataset(tmp_path: Path, *, dataset_id: str = "pr28_health") -> tuple[DatasetRegistry, str]:
    registry = DatasetRegistry(
        registry_file=str(tmp_path / "registry" / "datasets.jsonl"),
        data_root=str(tmp_path / "data"),
    )
    dataset = MockDataFactory().generate(
        MockDatasetConfig(
            dataset_id=dataset_id,
            market="US",
            symbol="AAPL",
            start_date=date(2023, 1, 1),
            end_date=date(2023, 7, 31),
            seed=28,
        )
    )
    entry = registry.register(dataset)
    return registry, entry.dataset_version


def _spec(formula: str, factor_id: str = "dsl_health_factor") -> FactorSpec:
    return FactorSpec(
        factor_id=factor_id,
        factor_version="draft",
        description="PR28 health report DSL",
        inputs=[
            FactorInput(name="close", source="market", availability_lag="0s"),
            FactorInput(name="open", source="market", availability_lag="0s"),
            FactorInput(name="volume", source="market", availability_lag="0s"),
        ],
        params={"formula": formula, "lookback_days": 20, "decay_lags": 5},
        validation_plan=ValidationPlan(
            in_sample_start="2023-01-01",
            in_sample_end="2023-05-01",
            out_sample_start="2023-05-02",
            out_sample_end="2023-07-31",
        ),
    )


def test_pr28_health_report_generated_for_dsl_factor(tmp_path: Path) -> None:
    dataset_registry, dataset_version = _dataset(tmp_path, dataset_id="pr28_health_report")
    engine = FactorEngine(
        dataset_registry=dataset_registry,
        factor_registry=FactorRegistry(str(tmp_path / "registry" / "factors.sqlite3")),
        artifact_root=str(tmp_path / "artifacts" / "factors"),
    )
    version = "pr28_health_v1"
    result = engine.run(
        factor_spec=_spec("Rank(Ts_Mean(close, 20))", factor_id="pr28_dsl"),
        dataset_version=dataset_version,
        factor_version=version,
        seed=9,
    )
    report = result.report
    assert report.health_report is not None
    assert report.health_report.sensitivity_grid_size >= 5
    assert len(report.health_report.sensitivity) >= 5
    assert report.health_report.oos_gap >= 0.0
    assert report.health_report.stability_score >= 0.0
    assert report.health_report_artifact_path is not None
    assert Path(report.health_report_artifact_path).exists()

    baseline_row = next((row for row in report.health_report.sensitivity if row.variant_id == "baseline"), None)
    assert baseline_row is not None
    window_rows = [row for row in report.health_report.sensitivity if "window" in row.params]
    assert window_rows
    assert any(row.params.get("window") != baseline_row.params.get("window") for row in window_rows)
    assert any(abs(float(row.ic_delta)) >= 0.0 for row in window_rows)


def _wait_task(client: TestClient, task_id: str, timeout_s: float = 6.0) -> dict:
    t0 = time.time()
    while time.time() - t0 <= timeout_s:
        payload = client.get(f"/workbench/tasks/{task_id}").json()
        if payload["status"] in {"done", "failed"}:
            return payload
        time.sleep(0.1)
    raise TimeoutError(f"task timeout: {task_id}")


def test_pr28_workbench_audit_links_factor_to_health_artifact() -> None:
    client = TestClient(app)
    ds_task = client.post(
        "/workbench/datasets/generate",
        json={
            "dataset_id": "pr28_factor_run",
            "market": "US",
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-03-10",
            "seed": 18,
            "base_price": 100.0,
        },
    )
    assert ds_task.status_code == 200
    done = _wait_task(client, ds_task.json()["task_id"])
    assert done["status"] == "done"
    dataset_version = done["result"]["dataset_version"]
    factor_version = f"pr28_api_{uuid4().hex[:8]}"

    run = client.post(
        "/workbench/factors/run",
        json={
            "dataset_version": dataset_version,
            "factor_id": "pr28_api_factor",
            "factor_version": factor_version,
            "formula": "Rank(Ts_Mean(close, 20))",
            "inputs": ["close", "open", "volume"],
            "availability_lag": "0s",
            "failure_conditions": ["range_bound_market", "liquidity_dry_up"],
            "cost_sensitivity_level": "medium",
            "cost_sensitivity_rationale": "Signal requires periodic rebalancing with moderate turnover.",
            "expected_horizon": "swing",
            "decay_lags": 5,
        },
    )
    assert run.status_code == 200
    report = run.json()["report"]
    assert "health_report" in report
    assert report["health_report"] is not None
    health_path = report.get("health_report_artifact_path")
    assert isinstance(health_path, str) and len(health_path) > 0
    assert Path(health_path).exists()

    audit = client.get("/workbench/audit")
    assert audit.status_code == 200
    rows = audit.json()
    matched = [
        row
        for row in rows
        if row.get("event_type") == "factor.health_report.linked"
        and (row.get("payload") or {}).get("factor_version") == factor_version
    ]
    assert matched
    assert matched[-1]["payload"].get("health_report_artifact_path") == health_path
