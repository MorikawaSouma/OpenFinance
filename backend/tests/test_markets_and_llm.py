from datetime import UTC, datetime

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.data.mock_factory import MockDataFactory, MockDatasetConfig


def test_market_rules_endpoints() -> None:
    client = TestClient(app)
    rules = client.get("/markets/rules")
    assert rules.status_code == 200
    payload = rules.json()
    markets = {item["market"] for item in payload}
    assert {"US", "CN", "CRYPTO", "JP"}.issubset(markets)

    cn_fail = client.post(
        "/markets/validate-order",
        json={"market": "CN", "quantity": 50, "symbol": "600519", "lot_size": 100},
    )
    assert cn_fail.status_code == 200
    assert cn_fail.json()["accepted"] is False

    us_ok = client.post(
        "/markets/validate-order",
        json={"market": "US", "quantity": 10, "symbol": "AAPL", "lot_size": 1},
    )
    assert us_ok.status_code == 200
    assert us_ok.json()["accepted"] is True


def test_llm_provider_endpoint() -> None:
    client = TestClient(app)
    providers = client.get("/llm/providers")
    assert providers.status_code == 200
    assert providers.json()[0]["name"] == "zhipu"
    assert providers.json()[0]["mode"] in {"stub", "remote"}

    completion = client.post("/llm/complete", json={"prompt": "hello market"})
    assert completion.status_code == 200
    payload = completion.json()
    assert payload["provider"] == "zhipu"
    assert "glm-4.7" in payload["model"]
    assert payload["mode"] in {"stub", "remote"}


def test_mock_dataset_extended_contracts() -> None:
    dataset = MockDataFactory().generate(
        MockDatasetConfig(
            dataset_id="full_contract_demo",
            market="US",
            symbol="AAPL",
            start_date=datetime(2024, 1, 1, tzinfo=UTC).date(),
            end_date=datetime(2024, 2, 20, tzinfo=UTC).date(),
            seed=100,
            include_survivorship_bias=True,
        )
    )
    assert len(dataset.corporate_actions) >= 1
    assert len(dataset.trading_calendar) >= 1
    assert len(dataset.macro) >= 1
    assert dataset.quality_report.survivorship_bias_enabled is True
