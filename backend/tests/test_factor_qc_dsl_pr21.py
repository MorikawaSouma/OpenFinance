from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.data.mock_factory import MockDataFactory, MockDatasetConfig
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.factors.engine import FactorEngine
from openfinance.quant.factors.factor_spec import FactorInput, FactorSpec, ValidationPlan
from openfinance.quant.factors.registry import FactorRegistry


def _dataset(tmp_path: Path, *, dataset_id: str = "pr21_formula") -> tuple[DatasetRegistry, str]:
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
            end_date=date(2023, 6, 30),
            seed=77,
        )
    )
    entry = registry.register(dataset)
    return registry, entry.dataset_version


def _spec(formula: str, factor_id: str = "dsl_factor") -> FactorSpec:
    return FactorSpec(
        factor_id=factor_id,
        factor_version="draft",
        description="PR21 DSL factor",
        inputs=[
            FactorInput(name="close", source="market", availability_lag="0s"),
            FactorInput(name="open", source="market", availability_lag="0s"),
            FactorInput(name="volume", source="market", availability_lag="0s"),
        ],
        params={"formula": formula, "lookback_days": 20, "decay_lags": 5},
        validation_plan=ValidationPlan(
            in_sample_start="2023-01-01",
            in_sample_end="2023-04-30",
            out_sample_start="2023-05-01",
            out_sample_end="2023-06-30",
        ),
    )


def test_pr21_factor_qc_report_contains_turnover_and_oos(tmp_path: Path) -> None:
    dataset_registry, dataset_version = _dataset(tmp_path, dataset_id="pr21_qc")
    engine = FactorEngine(
        dataset_registry=dataset_registry,
        factor_registry=FactorRegistry(str(tmp_path / "registry" / "factors.sqlite3")),
        artifact_root=str(tmp_path / "artifacts" / "factors"),
    )
    result = engine.run(
        factor_spec=_spec("Rank(Ts_Mean(close, 20))", factor_id="qc_rank_mean"),
        dataset_version=dataset_version,
        factor_version="qc_rank_mean_v1",
        seed=7,
    )
    report = result.report
    assert report.observation_count > 0
    assert 0.0 <= report.coverage <= 1.0
    assert 0.0 <= report.missing_rate <= 1.0
    assert 0.0 <= report.turnover_proxy <= 1.0
    assert report.in_sample_observation_count + report.out_sample_observation_count == report.observation_count
    assert report.oos_split_ratio >= 0.5
    assert isinstance(report.in_sample_ic_mean, float)
    assert isinstance(report.out_sample_ic_mean, float)
    assert report.dsl_execution_plan is not None


def test_pr21_three_dsl_factors_can_compute_and_save(tmp_path: Path) -> None:
    dataset_registry, dataset_version = _dataset(tmp_path, dataset_id="pr21_three_factors")
    factor_registry = FactorRegistry(str(tmp_path / "registry" / "factors.sqlite3"))
    engine = FactorEngine(
        dataset_registry=dataset_registry,
        factor_registry=factor_registry,
        artifact_root=str(tmp_path / "artifacts" / "factors"),
    )
    formulas = {
        "dsl_rank_mean": "Rank(Ts_Mean(close, 20))",
        "dsl_z_momentum": "ZScore(momentum_20)",
        "dsl_winsorized": "Winsorize(Clip((close-open)/open, -0.2, 0.2), 0.05, 0.95)",
    }
    versions: list[str] = []
    for factor_id, formula in formulas.items():
        version = f"{factor_id}_v1"
        result = engine.run(
            factor_spec=_spec(formula, factor_id=factor_id),
            dataset_version=dataset_version,
            factor_version=version,
            seed=11,
        )
        assert result.factor_version == version
        assert result.report.observation_count > 0
        versions.append(version)

    entries = factor_registry.list_entries(limit=20)
    saved_versions = {entry.version for entry in entries}
    for version in versions:
        assert version in saved_versions


def test_pr21_factor_library_route_shows_oos_fields() -> None:
    client = TestClient(app)
    ds_task = client.post(
        "/workbench/datasets/generate",
        json={
            "dataset_id": "pr21_factor_library",
            "market": "US",
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-03-15",
            "seed": 66,
            "base_price": 100.0,
        },
    )
    assert ds_task.status_code == 200
    task_id = ds_task.json()["task_id"]

    import time

    done = None
    for _ in range(80):
        done = client.get(f"/workbench/tasks/{task_id}").json()
        if done["status"] in {"done", "failed"}:
            break
        time.sleep(0.1)
    assert done is not None and done["status"] == "done"
    dataset_version = done["result"]["dataset_version"]

    formulas = [
        ("pr21_rank", "Rank(Ts_Mean(close, 10))"),
        ("pr21_zscore", "ZScore(momentum_20)"),
        ("pr21_clip", "Clip((close-open)/open, -0.15, 0.15)"),
    ]
    versions: list[str] = []
    for factor_id, formula in formulas:
        version = f"{factor_id}_v1"
        run = client.post(
            "/workbench/factors/run",
            json={
                "dataset_version": dataset_version,
                "factor_id": factor_id,
                "factor_version": version,
                "formula": formula,
                "inputs": ["close", "open", "volume"],
                "availability_lag": "0s",
                "failure_conditions": ["high_volatility", "policy_shock"],
                "cost_sensitivity_level": "medium",
                "cost_sensitivity_rationale": "Moderate turnover expected from rank-style rebalances.",
                "expected_horizon": "swing",
                "decay_lags": 4,
            },
        )
        assert run.status_code == 200
        versions.append(version)

    for version in versions:
        detail = client.get(f"/workbench/factors/{version}")
        assert detail.status_code == 200
        report = detail.json()["report"]
        assert "turnover_proxy" in report
        assert "in_sample_ic_mean" in report
        assert "out_sample_ic_mean" in report
        assert "oos_split_ratio" in report
