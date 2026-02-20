import json
from datetime import date

from openfinance.data.mock_factory import MockDataFactory, MockDatasetConfig, build_dataset_version
from openfinance.data.registry import DatasetRegistry


def test_dataset_version_is_reproducible() -> None:
    config = MockDatasetConfig(
        dataset_id="demo_ds",
        market="US",
        symbol="AAPL",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        seed=7,
    )
    version_1 = build_dataset_version(config)
    version_2 = build_dataset_version(config)
    assert version_1 == version_2


def test_factory_is_reproducible() -> None:
    config = MockDatasetConfig(
        dataset_id="demo_ds",
        market="US",
        symbol="AAPL",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        seed=42,
    )
    factory = MockDataFactory()
    dataset_1 = factory.generate(config)
    dataset_2 = factory.generate(config)
    assert dataset_1.dataset_version == dataset_2.dataset_version
    assert json.dumps(dataset_1.market[0].model_dump(mode="json"), sort_keys=True) == json.dumps(
        dataset_2.market[0].model_dump(mode="json"), sort_keys=True
    )


def test_dataset_registry_persistence(tmp_path) -> None:
    config = MockDatasetConfig(
        dataset_id="demo_registry",
        market="US",
        symbol="MSFT",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 1),
        seed=99,
    )
    dataset = MockDataFactory().generate(config)
    registry = DatasetRegistry(
        registry_file=str(tmp_path / "registry" / "datasets.jsonl"),
        data_root=str(tmp_path / "data"),
    )
    entry = registry.register(dataset)
    loaded = registry.get_entry(entry.dataset_version)
    assert loaded is not None
    assert loaded.dataset_version == entry.dataset_version
    assert (tmp_path / "data" / f"{entry.dataset_version}.json").exists()
