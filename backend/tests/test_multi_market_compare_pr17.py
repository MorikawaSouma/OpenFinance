from fastapi.testclient import TestClient

from openfinance.api.main import app


def test_multi_market_compare_endpoint_returns_diff_table() -> None:
    client = TestClient(app)
    resp = client.post(
        "/workbench/reports/multi-market/compare",
        json={
            "markets": ["US", "JP"],
            "strategy_id": "compare_demo",
            "strategy_version": "compare-v1",
            "strategy_family": "trend",
            "rebalance": "weekly",
            "lookback_days": 20,
            "start": "2024-01-01",
            "end": "2024-03-31",
            "commission_bps": 5,
            "slippage_bps": 8,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["baseline_market"] == "US"
    assert len(payload["rows"]) == 2
    markets = {row["market"] for row in payload["rows"]}
    assert markets == {"US", "JP"}
    assert len(payload["diff_table"]) == 2
    assert all("sharpe" in row for row in payload["diff_table"])
    assert all("max_drawdown" in row for row in payload["diff_table"])
    assert all("turnover" in row for row in payload["diff_table"])
    assert "market_warnings" in payload
    assert "migration_warnings" in payload
    assert isinstance(payload["migration_warnings"], list)


def test_multi_market_compare_requires_at_least_two_markets() -> None:
    client = TestClient(app)
    resp = client.post(
        "/workbench/reports/multi-market/compare",
        json={"markets": ["US"], "start": "2024-01-01", "end": "2024-03-31"},
    )
    assert resp.status_code == 400


def test_multi_market_compare_cn_high_freq_warns_t_plus_one() -> None:
    client = TestClient(app)
    resp = client.post(
        "/workbench/reports/multi-market/compare",
        json={
            "markets": ["US", "CN"],
            "strategy_id": "compare_cn_t1",
            "strategy_version": "compare-cn-v1",
            "strategy_family": "trend",
            "rebalance": "daily",
            "lookback_days": 2,
            "signal_threshold": 0.0,
            "auto_round_lot": False,
            "start": "2024-01-01",
            "end": "2024-03-31",
            "commission_bps": 5,
            "slippage_bps": 8,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    cn_warnings = payload["market_warnings"].get("CN", [])
    assert any(item.get("code") == "cn_t_plus_one_high_frequency" for item in cn_warnings)
    cn_row = next((row for row in payload["diff_table"] if row.get("market") == "CN"), None)
    assert cn_row is not None
    assert int(cn_row.get("warning_count", 0)) >= 1
