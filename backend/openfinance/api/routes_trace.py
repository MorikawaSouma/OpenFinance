import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from openfinance.api.routes_chat import _chat_store
from openfinance.core.audit import AuditLogEntry, FileAuditStore
from openfinance.core.config import settings
from openfinance.core.events import event_bus
from openfinance.knowledge.service import KnowledgeService, build_default_knowledge_service
from openfinance.quant.backtest.report import BacktestReport
from openfinance.quant.backtest.run_registry import RunRegistry, RunRegistryEntry
from openfinance.research.plan_registry import PlanRegistry

router = APIRouter(tags=["trace"])


class RestoreReportHeader(BaseModel):
    run_id: str
    audit_trace_id: str
    dataset_version: str
    strategy_id: str
    strategy_version: str
    market: str
    start: str
    end: str
    factor_versions: list[dict[str, str]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    report_path: str | None = None
    report_missing: bool = False


class RestoreBacktestRequest(BaseModel):
    run_id: str | None = None
    request: dict[str, Any]
    source: str = "registry"


class RestoreBundle(BaseModel):
    trace_id: str
    partial_restore: bool = False
    missing: list[str] = Field(default_factory=list)
    summary: str
    plan: dict[str, Any] | None = None
    evidence_packs: list[dict[str, Any]] = Field(default_factory=list)
    agent_outputs: list[dict[str, Any]] = Field(default_factory=list)
    backtest_requests: list[RestoreBacktestRequest] = Field(default_factory=list)
    reports_headers: list[RestoreReportHeader] = Field(default_factory=list)
    session_state: dict[str, Any] = Field(default_factory=dict)


@lru_cache(maxsize=1)
def _audit_store() -> FileAuditStore:
    return FileAuditStore(settings.audit_log_file)


@lru_cache(maxsize=1)
def _run_registry() -> RunRegistry:
    return RunRegistry(settings.run_registry_file)


@lru_cache(maxsize=1)
def _plan_registry() -> PlanRegistry:
    return PlanRegistry(settings.plan_registry_file)


@lru_cache(maxsize=1)
def _knowledge() -> KnowledgeService:
    return build_default_knowledge_service()


def _extract_values(payload: Any, key: str) -> list[str]:
    out: list[str] = []
    if isinstance(payload, dict):
        for k, value in payload.items():
            if k == key and isinstance(value, str) and value.strip():
                out.append(value.strip())
            else:
                out.extend(_extract_values(value, key))
    elif isinstance(payload, list):
        for item in payload:
            out.extend(_extract_values(item, key))
    return out


def _to_iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, str) and value.strip():
        return value
    return None


def _report_header_from_entry(entry: RunRegistryEntry, missing: list[str]) -> RestoreReportHeader:
    report_path = Path(entry.report_path)
    if not report_path.exists():
        missing.append(f"report:{entry.run_id}")
        req = entry.request
        return RestoreReportHeader(
            run_id=str(entry.run_id),
            audit_trace_id=str(entry.audit_trace_id),
            dataset_version=entry.dataset_version,
            strategy_id=entry.strategy_id,
            strategy_version=entry.strategy_version,
            market=str(req.get("market", "US")),
            start=str(req.get("start", "")),
            end=str(req.get("end", "")),
            factor_versions=list(req.get("factor_versions", [])) if isinstance(req.get("factor_versions"), list) else [],
            metrics={},
            created_at=None,
            report_path=str(report_path),
            report_missing=True,
        )
    report = BacktestReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    return RestoreReportHeader(
        run_id=str(report.run_id),
        audit_trace_id=str(report.audit_trace_id),
        dataset_version=report.dataset_version,
        strategy_id=entry.strategy_id,
        strategy_version=report.strategy_version,
        market=str(entry.request.get("market", "US")),
        start=str(entry.request.get("start", "")),
        end=str(entry.request.get("end", "")),
        factor_versions=[row.model_dump(mode="json") for row in report.factor_versions],
        metrics=dict(report.metrics),
        created_at=report.created_at.isoformat(),
        report_path=str(report_path),
        report_missing=False,
    )


def _restore_summary(*, trace_id: str, run_count: int, plan_id: str | None, missing: list[str]) -> str:
    core = f"已恢复到 trace_id={trace_id}，载入 {run_count} 个历史 run。"
    if plan_id:
        core = f"{core} plan_id={plan_id}。"
    if missing:
        core = f"{core} 部分工件缺失（{len(missing)} 项），已按可用信息部分恢复。"
    return f"{core} 你可以继续提问：成本翻倍再跑一次。"


@router.get("/trace/{trace_id}/restore", response_model=RestoreBundle)
def restore_trace_context(trace_id: str, session_id: str | None = Query(default=None)) -> RestoreBundle:
    try:
        target_trace = UUID(trace_id)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail="invalid trace_id") from ex

    audit_rows = [row for row in _audit_store().list_all() if row.trace_id == target_trace]
    run_registry = _run_registry()
    trace_run_entries = [row for row in run_registry.list_entries() if str(row.audit_trace_id) == trace_id]
    if (not audit_rows) and (not trace_run_entries):
        raise HTTPException(status_code=404, detail="trace not found")

    missing: list[str] = []
    plan_id: str | None = None
    for row in audit_rows:
        candidates = _extract_values(row.payload, "plan_id")
        if candidates:
            plan_id = candidates[0]
            break
    if not plan_id:
        for entry in trace_run_entries:
            request = entry.request if isinstance(entry.request, dict) else {}
            constraints = request.get("constraints", {}) if isinstance(request.get("constraints"), dict) else {}
            candidate = str(constraints.get("plan_id") or request.get("plan_id") or "").strip()
            if candidate:
                plan_id = candidate
                break

    plan_payload = _plan_registry().get_plan_payload(plan_id) if plan_id else None
    if plan_id and (plan_payload is None):
        missing.append(f"plan:{plan_id}")

    evidence_ids: set[str] = set()
    evidence_snapshot_by_id: dict[str, dict[str, Any]] = {}
    run_ids: set[str] = set()
    backtest_requests: list[RestoreBacktestRequest] = []
    backtest_req_dedup: set[str] = set()
    agent_outputs: list[dict[str, Any]] = []
    agent_out_dedup: set[str] = set()

    for row in audit_rows:
        for eid in _extract_values(row.payload, "evidence_pack_id"):
            evidence_ids.add(eid)
        for rid in _extract_values(row.payload, "run_id"):
            run_ids.add(rid)
        payload_req = row.payload.get("backtest_request")
        if isinstance(payload_req, dict):
            key = json.dumps(payload_req, sort_keys=True, ensure_ascii=False)
            if key not in backtest_req_dedup:
                backtest_req_dedup.add(key)
                backtest_requests.append(RestoreBacktestRequest(request=payload_req, source="audit"))
        payload_agents = row.payload.get("agent_outputs")
        if isinstance(payload_agents, list):
            for item in payload_agents:
                if not isinstance(item, dict):
                    continue
                key = json.dumps(item, sort_keys=True, ensure_ascii=False)
                if key not in agent_out_dedup:
                    agent_out_dedup.add(key)
                    agent_outputs.append(item)
        if row.event_type == "pipeline.evidence.done":
            eid = str(row.payload.get("evidence_pack_id") or "").strip()
            if eid:
                evidence_snapshot_by_id[eid] = {
                    "evidence_pack_id": eid,
                    "created_at": _to_iso(row.created_at),
                    "query": "",
                    "sources": list(row.payload.get("sources", [])) if isinstance(row.payload.get("sources"), list) else [],
                    "key_points": [],
                    "credibility_score": 0.5,
                    "time_relevance": 0.5,
                    "credibility_breakdown": {},
                    "restored_from": "audit_snapshot",
                }

    for entry in trace_run_entries:
        for eid in _extract_values(entry.request, "evidence_pack_id"):
            evidence_ids.add(eid)
        run_ids.add(str(entry.run_id))

    if isinstance(plan_payload, dict):
        tool_context = plan_payload.get("tool_context", {})
        if isinstance(tool_context, dict):
            plan_agents = tool_context.get("agent_outputs")
            if isinstance(plan_agents, list):
                for item in plan_agents:
                    if not isinstance(item, dict):
                        continue
                    key = json.dumps(item, sort_keys=True, ensure_ascii=False)
                    if key not in agent_out_dedup:
                        agent_out_dedup.add(key)
                        agent_outputs.append(item)
        maybe_eid = str(plan_payload.get("tool_context", {}).get("evidence_pack_id", "")).strip()
        if maybe_eid:
            evidence_ids.add(maybe_eid)

    evidence_packs: list[dict[str, Any]] = []
    for eid in sorted(evidence_ids):
        pack = _knowledge().get_pack(eid)
        if pack is not None:
            evidence_packs.append(pack.model_dump(mode="json"))
            continue
        missing.append(f"evidence_pack:{eid}")
        if eid in evidence_snapshot_by_id:
            evidence_packs.append(evidence_snapshot_by_id[eid])

    by_run_id: dict[str, RunRegistryEntry] = {str(row.run_id): row for row in trace_run_entries}
    for rid in sorted(run_ids):
        entry = run_registry.get_entry(rid)
        if entry is not None:
            by_run_id[str(entry.run_id)] = entry
    reports_headers = [_report_header_from_entry(row, missing) for row in by_run_id.values()]
    reports_headers.sort(key=lambda row: (row.created_at or "", row.run_id))

    for row in reports_headers:
        entry = by_run_id.get(row.run_id)
        if entry is None:
            continue
        key = json.dumps(entry.request, sort_keys=True, ensure_ascii=False)
        if key in backtest_req_dedup:
            continue
        backtest_req_dedup.add(key)
        backtest_requests.append(RestoreBacktestRequest(run_id=row.run_id, request=entry.request, source="registry"))

    parsed_session_id: UUID | None = None
    if session_id:
        try:
            parsed_session_id = UUID(session_id)
        except ValueError as ex:
            raise HTTPException(status_code=400, detail="invalid session_id") from ex
    session = _chat_store().get_or_create(parsed_session_id)

    if plan_id:
        _chat_store().set_last_context(session.session_id, last_plan_id=plan_id)
    for row in reports_headers:
        _chat_store().register_run(
            session.session_id,
            run_id=row.run_id,
            plan_id=plan_id,
            report_id=row.run_id,
            dataset_version=row.dataset_version,
            metrics=row.metrics,
        )

    missing = list(dict.fromkeys(missing))
    restore_text = _restore_summary(
        trace_id=trace_id,
        run_count=len(reports_headers),
        plan_id=plan_id,
        missing=missing,
    )
    _chat_store().append_turn(session.session_id, role="system", content=restore_text)
    session_memory = _chat_store().get_last_memory(session.session_id)
    session_state = {
        "session_id": str(session.session_id),
        "last_plan_id": session_memory.get("last_plan_id"),
        "last_run_id": session_memory.get("last_run_id"),
        "last_report_id": session_memory.get("last_report_id"),
        "last_dataset_version": session_memory.get("last_dataset_version"),
        "runs_by_session": session_memory.get("runs_by_session", []),
        "restore_message": restore_text,
    }

    _audit_store().append(
        AuditLogEntry(
            trace_id=target_trace,
            event_type="trace.restore",
            payload={
                "session_id": str(session.session_id),
                "trace_id": trace_id,
                "partial_restore": bool(missing),
                "missing": missing,
                "run_count": len(reports_headers),
                "plan_id": plan_id,
            },
            created_at=datetime.now(UTC),
        )
    )
    event_bus.publish(
        event_type="trace.restore",
        trace_id=trace_id,
        session_id=str(session.session_id),
        payload={
            "message": restore_text,
            "partial_restore": bool(missing),
            "missing": missing,
            "plan_id": plan_id,
            "run_count": len(reports_headers),
        },
    )

    return RestoreBundle(
        trace_id=trace_id,
        partial_restore=bool(missing),
        missing=missing,
        summary=restore_text,
        plan=plan_payload if isinstance(plan_payload, dict) else None,
        evidence_packs=evidence_packs,
        agent_outputs=agent_outputs,
        backtest_requests=backtest_requests,
        reports_headers=reports_headers,
        session_state=session_state,
    )
