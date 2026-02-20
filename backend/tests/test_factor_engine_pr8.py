from datetime import date
from pathlib import Path

from openfinance.data.mock_factory import MockDataFactory, MockDatasetConfig
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.factors.engine import FactorEngine
from openfinance.quant.factors.factor_spec import FactorInput, FactorSpec, ValidationPlan
from openfinance.quant.factors.registry import FactorRegistry


def _make_dataset(tmp_path: Path, *, market: str, symbol: str, dataset_id: str, seed: int) -> tuple[DatasetRegistry, str]:
    dataset_registry = DatasetRegistry(
        registry_file=str(tmp_path / "registry" / "datasets.jsonl"),
        data_root=str(tmp_path / "data"),
    )
    dataset = MockDataFactory().generate(
        MockDatasetConfig(
            dataset_id=dataset_id,
            market=market,
            symbol=symbol,
            start_date=date(2023, 1, 1),
            end_date=date(2023, 6, 30),
            seed=seed,
        )
    )
    entry = dataset_registry.register(dataset)
    return dataset_registry, entry.dataset_version


def _spec(factor_id: str, *, lookback: int = 20, universe: list[str] | None = None) -> FactorSpec:
    params: dict[str, int | str | list[str]] = {"lookback_days": lookback, "decay_lags": 5}
    if universe:
        params["universe"] = universe
    return FactorSpec(
        factor_id=factor_id,
        factor_version="draft",
        description=f"spec for {factor_id}",
        inputs=[FactorInput(name=factor_id, source="market")],
        params=params,
        validation_plan=ValidationPlan(
            in_sample_start="2023-01-01",
            in_sample_end="2023-04-30",
            out_sample_start="2023-05-01",
            out_sample_end="2023-06-30",
        ),
    )


def test_factor_registry_and_engine_cache(tmp_path: Path) -> None:
    dataset_registry, dataset_version = _make_dataset(
        tmp_path,
        market="US",
        symbol="AAPL",
        dataset_id="pr8_us",
        seed=7,
    )
    factor_registry = FactorRegistry(str(tmp_path / "registry" / "factors.sqlite3"))
    engine = FactorEngine(
        dataset_registry=dataset_registry,
        factor_registry=factor_registry,
        artifact_root=str(tmp_path / "artifacts" / "factors"),
    )

    result_1 = engine.run(factor_spec=_spec("momentum_1d", lookback=5), dataset_version=dataset_version, seed=11)
    assert result_1.cached is False
    assert result_1.report.observation_count > 10
    assert len(result_1.report.decay_curve) == 5
    assert Path(result_1.artifact_path).exists()

    row = factor_registry.get(factor_id="momentum_1d", version=result_1.factor_version)
    assert row is not None
    assert row.dataset_schema_version == "1.0.0"
    assert row.spec["factor_id"] == "momentum_1d"

    result_2 = engine.run(factor_spec=_spec("momentum_1d", lookback=5), dataset_version=dataset_version, seed=11)
    assert result_2.cached is True
    assert result_2.report.ic_mean == result_1.report.ic_mean
    assert result_2.report.rank_ic_mean == result_1.report.rank_ic_mean


def test_factor_engine_supports_six_factors_and_multi_market_universe(tmp_path: Path) -> None:
    us_registry, us_dataset = _make_dataset(
        tmp_path / "us",
        market="US",
        symbol="AAPL",
        dataset_id="pr8_us_multi",
        seed=13,
    )
    crypto_registry, crypto_dataset = _make_dataset(
        tmp_path / "crypto",
        market="CRYPTO",
        symbol="BTCUSDT",
        dataset_id="pr8_crypto",
        seed=13,
    )

    us_engine = FactorEngine(
        dataset_registry=us_registry,
        factor_registry=FactorRegistry(str(tmp_path / "us" / "registry" / "factors.sqlite3")),
        artifact_root=str(tmp_path / "us" / "artifacts" / "factors"),
    )
    crypto_engine = FactorEngine(
        dataset_registry=crypto_registry,
        factor_registry=FactorRegistry(str(tmp_path / "crypto" / "registry" / "factors.sqlite3")),
        artifact_root=str(tmp_path / "crypto" / "artifacts" / "factors"),
    )

    factor_ids = [
        "momentum_1d",
        "mean_reversion",
        "volatility",
        "volume_surprise",
        "intraday_return",
        "carry_proxy",
    ]
    for factor_id in factor_ids:
        result = us_engine.run(
            factor_spec=_spec(factor_id, lookback=20, universe=["MSFT", "GOOG", "AMZN"]),
            dataset_version=us_dataset,
            seed=17,
        )
        assert result.report.observation_count > 0
        assert len(result.factor_series) > 0
        instruments = {row.instrument for row in result.factor_series}
        assert "AAPL" in instruments
        assert len(instruments) >= 3

    carry_result = crypto_engine.run(
        factor_spec=_spec("carry_proxy", lookback=10, universe=["ETHUSDT", "SOLUSDT"]),
        dataset_version=crypto_dataset,
        seed=23,
    )
    assert carry_result.report.market == "CRYPTO"
    assert any(abs(row.value) > 0.0 for row in carry_result.factor_series)
