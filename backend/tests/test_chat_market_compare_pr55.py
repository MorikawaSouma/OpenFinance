from pathlib import Path

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.api.routes_chat import (
    _audit_store,
    _chat_store,
    _general_info_answerer,
    _knowledge,
    _market_compare_builder,
    _pipeline_engine,
)
from openfinance.core.config import settings


def _configure_paths(tmp_path: Path) -> None:
    settings.chat_session_store_file = str(tmp_path / "registry" / "chat_sessions.json")
    settings.audit_log_file = str(tmp_path / "registry" / "audit.jsonl")
    settings.dataset_registry_file = str(tmp_path / "registry" / "datasets.jsonl")
    settings.run_registry_file = str(tmp_path / "registry" / "runs.jsonl")
    settings.plan_registry_file = str(tmp_path / "registry" / "plans.jsonl")
    settings.evidence_db_file = str(tmp_path / "registry" / "evidence.sqlite3")
    settings.data_root = str(tmp_path / "data")
    _chat_store.cache_clear()
    _pipeline_engine.cache_clear()
    _audit_store.cache_clear()
    _knowledge.cache_clear()
    _general_info_answerer.cache_clear()
    _market_compare_builder.cache_clear()


def test_market_compare_returns_structured_cards_and_nonzero_confidence(tmp_path: Path) -> None:
    _configure_paths(tmp_path)
    client = TestClient(app)
    query = "鎶婄編鑲″拰鏃ヨ偂鏀惧湪鍚屼竴妗嗘灦瀵规瘮锛岄噸鐐圭湅鍥炴挙涓庢尝鍔?
    resp = client.post("/chat/message", json={"message": query, "include_debug": True})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["mode"] == "market_compare"
    cards = payload["cards"]
    card_types = {row["type"] for row in cards}
    assert {"summary", "comparison_table", "key_differences", "evidence", "confidence", "next_steps"}.issubset(card_types)

    table_card = next(row for row in cards if row["type"] == "comparison_table")
    table_rows = table_card.get("table") or []
    assert any(str(row.get("metric")) == "Drawdown" for row in table_rows)
    assert any(str(row.get("metric")) == "Volatility" for row in table_rows)

    evidence_card = next(row for row in cards if row["type"] == "evidence")
    grouped = evidence_card.get("items") or []
    markets = {str(row.get("market")) for row in grouped if isinstance(row, dict)}
    assert {"US", "JP"}.issubset(markets)
    for row in grouped:
        if not isinstance(row, dict):
            continue
        evidence_rows = row.get("evidence") or []
        assert len(evidence_rows) >= 2
        for ev in evidence_rows:
            title = str((ev or {}).get("title") or "")
            assert query not in title

    confidence_card = next(row for row in cards if row["type"] == "confidence")
    confidence_value = float(confidence_card.get("content") or 0.0)
    assert confidence_value > 0.0

    key_diff = next(row for row in cards if row["type"] == "key_differences")
    items = key_diff.get("items") or []
    assert items
    for row in items:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "")
        assert "..." not in text

    debug = payload["debug"]
    assert debug["intent"] == "market_compare"
    assert len(debug.get("citations") or []) >= 4
    assert debug.get("market_compare", {}).get("confidence", 0.0) > 0.0
