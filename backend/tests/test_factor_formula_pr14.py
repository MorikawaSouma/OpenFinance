from datetime import date
from pathlib import Path

import pytest

from openfinance.data.mock_factory import MockDataFactory, MockDatasetConfig
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.factors.engine import FactorEngine
from openfinance.quant.factors.factor_spec import FactorInput, FactorSpec, ValidationPlan
from openfinance.quant.factors.registry import FactorRegistry


def _dataset(tmp_path: Path) -> tuple[DatasetRegistry, str]:
    registry = DatasetRegistry(
        registry_file=str(tmp_path / "registry" / "datasets.jsonl"),
        data_root=str(tmp_path / "data"),
    )
    dataset = MockDataFactory().generate(
        MockDatasetConfig(
            dataset_id="pr14_formula",
            market="US",
            symbol="AAPL",
            start_date=date(2023, 1, 1),
            end_date=date(2023, 4, 30),
            seed=33,
        )
    )
    entry = registry.register(dataset)
    return registry, entry.dataset_version


def _formula_spec(formula: str) -> FactorSpec:
    return FactorSpec(
        factor_id="formula_intraday",
        factor_version="draft",
        description="formula factor",
        inputs=[
            FactorInput(name="close", source="market", availability_lag="0s"),
            FactorInput(name="open", source="market", availability_lag="0s"),
        ],
        params={"formula": formula, "decay_lags": 4, "lookback_days": 10},
        validation_plan=ValidationPlan(
            in_sample_start="2023-01-01",
            in_sample_end="2023-03-15",
            out_sample_start="2023-03-16",
            out_sample_end="2023-04-30",
        ),
    )


def test_formula_factor_runs_registers_and_reuses(tmp_path: Path) -> None:
    dataset_registry, dataset_version = _dataset(tmp_path)
    factor_registry = FactorRegistry(str(tmp_path / "registry" / "factors.sqlite3"))
    engine = FactorEngine(
        dataset_registry=dataset_registry,
        factor_registry=factor_registry,
        artifact_root=str(tmp_path / "artifacts" / "factors"),
    )

    spec = _formula_spec("(close-open)/open")
    result_1 = engine.run(
        factor_spec=spec,
        dataset_version=dataset_version,
        factor_version="formula_v1",
        seed=101,
    )
    assert result_1.cached is False
    assert result_1.factor_version == "formula_v1"
    assert result_1.report.ic_mean is not None
    assert len(result_1.report.decay_curve) == 4
    assert 0.0 <= result_1.report.coverage <= 1.0

    entry = factor_registry.get(factor_id="formula_intraday", version="formula_v1")
    assert entry is not None
    assert "formula:(close-open)/open" in entry.inputs_signature
    assert entry.availability_lag == "0s"

    result_2 = engine.run(
        factor_spec=spec,
        dataset_version=dataset_version,
        factor_version="formula_v1",
        seed=101,
    )
    assert result_2.cached is True
    assert result_2.report.ic_mean == result_1.report.ic_mean


def test_formula_factor_blocks_unsafe_expression(tmp_path: Path) -> None:
    dataset_registry, dataset_version = _dataset(tmp_path)
    engine = FactorEngine(
        dataset_registry=dataset_registry,
        factor_registry=FactorRegistry(str(tmp_path / "registry" / "factors.sqlite3")),
        artifact_root=str(tmp_path / "artifacts" / "factors"),
    )
    with pytest.raises(ValueError):
        engine.run(
            factor_spec=_formula_spec("__import__('os').system('calc')"),
            dataset_version=dataset_version,
            factor_version="formula_blocked",
            seed=1,
        )
