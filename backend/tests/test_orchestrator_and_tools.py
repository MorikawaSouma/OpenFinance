from pathlib import Path

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.core.config import settings


def test_orchestrator_route_and_audit_chain() -> None:
    client = TestClient(app)
    response = client.post(
        "/orchestrator/run",
        json={
            "prompt": "Evaluate AAPL with risk controls",
            "active_agents": ["Strategy", "RiskManager", "ComplianceAudit"],
            "tool_calls": ["read_dataset_versions", "read_run_versions"],
            "evidence_pack_id": "ep_test_001",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "trace_id" in payload
    assert len(payload["outputs"]) >= 2
    assert "read_dataset_versions" in payload["tool_results"]
    assert all("ep_test_001" in row.get("evidence_refs", []) for row in payload["outputs"])

    audit_path = Path(settings.audit_log_file)
    assert audit_path.exists()
    lines = [line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any('"event_type": "agent.output"' in line for line in lines)
    assert any('"event_type": "tool.call"' in line for line in lines)
