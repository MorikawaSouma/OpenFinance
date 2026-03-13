from uuid import uuid4

from fastapi.testclient import TestClient

from openfinance.api.main import app
from openfinance.core.audit import AuditLogEntry, FileAuditStore
from openfinance.core.config import settings


def _create_pipeline_run(client: TestClient) -> dict:
    resp = client.post(
        "/pipeline/run",
        json={
            "question": "Give me an executable trend strategy and run three experiment variants",
            "market": "US",
            "run_paper_trade": False,
            "experiments": 3,
        },
    )
    assert resp.status_code == 200
    return resp.json()


def test_pr40_restore_trace_supports_modify_rerun() -> None:
    client = TestClient(app)
    run_payload = _create_pipeline_run(client)
    run_id = str(run_payload["run_id"])
    run_report = client.get(f"/workbench/runs/{run_id}")
    assert run_report.status_code == 200
    trace_id = str(run_report.json()["audit_trace_id"])

    restore = client.get(f"/trace/{trace_id}/restore")
    assert restore.status_code == 200
    bundle = restore.json()
    assert bundle["trace_id"] == trace_id
    assert bundle["reports_headers"]
    assert any(str(row.get("run_id")) == run_id for row in bundle["reports_headers"])
    session_state = bundle["session_state"]
    assert session_state["last_run_id"] == run_id
    assert session_state["last_plan_id"] == run_payload["plan_id"]

    chat_resp = client.post(
        "/chat/message",
        json={
            "session_id": session_state["session_id"],
            "message": "Double cost and run again.",
            "include_debug": True,
        },
    )
    assert chat_resp.status_code == 200
    chat_payload = chat_resp.json()
    dev_payload = chat_payload.get("debug", {})
    assert chat_payload["mode"] == "modify_last_run"
    assert dev_payload.get("intent") == "modify_last_run"
    assert str(dev_payload.get("old_run_id")) == run_id
    assert str(dev_payload.get("run_id")) != run_id


def test_pr40_restore_partial_when_artifacts_missing() -> None:
    client = TestClient(app)
    trace_id = uuid4()
    FileAuditStore(settings.audit_log_file).append(
        AuditLogEntry(
            trace_id=trace_id,
            event_type="trace.seed",
            payload={
                "plan_id": "plan_missing_for_restore",
                "evidence_pack_id": "00000000-0000-0000-0000-000000000000",
            },
        )
    )

    restore = client.get(f"/trace/{trace_id}/restore")
    assert restore.status_code == 200
    payload = restore.json()
    assert payload["partial_restore"] is True
    missing = payload.get("missing", [])
    assert "plan:plan_missing_for_restore" in missing
    assert any(str(row).startswith("evidence_pack:") for row in missing)
    assert payload["session_state"].get("session_id")
