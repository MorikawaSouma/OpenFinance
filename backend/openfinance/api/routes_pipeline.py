from functools import lru_cache
from threading import Thread
import traceback
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException

from openfinance.core.audit import FileAuditStore
from openfinance.core.config import settings
from openfinance.core.events import event_bus
from openfinance.core.tasks import TaskRecord, get_task_manager
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.backtest.run_registry import RunRegistry
from openfinance.research.pipeline import (
    MigrationPreflightBlockedError,
    PipelineRequest,
    PipelineResponse,
    PlanCreateRequest,
    PlanCreateResponse,
    ResearchPipelineEngine,
)
from openfinance.research.plan_registry import PlanRegistry

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@lru_cache(maxsize=1)
def _engine() -> ResearchPipelineEngine:
    return ResearchPipelineEngine(
        audit_store=FileAuditStore(settings.audit_log_file),
        dataset_registry=DatasetRegistry(settings.dataset_registry_file, settings.data_root),
        run_registry=RunRegistry(settings.run_registry_file),
        plan_registry=PlanRegistry(settings.plan_registry_file),
    )


@lru_cache(maxsize=1)
def _task_manager():
    return get_task_manager()


class PipelineRunTaskRequest(PipelineRequest):
    session_id: str | None = None


def _task_payload(task: TaskRecord, **extra: Any) -> dict[str, Any]:
    payload = {
        "task_id": str(task.task_id),
        "parent_task_id": str(task.parent_task_id) if task.parent_task_id else None,
        "type": task.task_type,
        "status": task.status,
        "progress": task.progress,
        "message": task.message,
        "result": task.result,
        "result_ref": task.result_ref,
        "meta": task.meta,
        "error": task.error,
        "task": task.model_dump(mode="json"),
    }
    payload.update(extra)
    return payload


def _emit_task_state(event_type: str, trace_id: UUID, task: TaskRecord, *, session_id: str, **extra: Any) -> None:
    payload = _task_payload(task, **extra)
    event_bus.publish(
        event_type=event_type,
        trace_id=str(trace_id),
        session_id=session_id,
        payload=payload,
    )


def _emit_observable_event(event_type: str, *, trace_id: UUID, session_id: str, payload: dict[str, Any]) -> None:
    event_bus.publish(
        event_type=event_type,
        trace_id=str(trace_id),
        session_id=session_id,
        payload=payload,
    )


def _stage_progress_pct(*, stage: str, completed_variants: int, total_variants: int) -> int:
    total = max(1, total_variants)
    stage_key = stage.lower().strip()
    if stage_key in {"pipeline.start", "plan.compose"}:
        return 8
    if stage_key == "evidence.pack":
        return 16
    if stage_key == "dataset.prepare":
        return 22
    if stage_key in {"variant.factor", "variant.strategy", "variant.backtest", "variant.start", "variants.running"}:
        return min(90, 25 + int((completed_variants / total) * 65))
    if stage_key == "backtest.compare":
        return 92
    if stage_key == "paper.trade":
        return 96
    if stage_key == "pipeline.done":
        return 99
    return min(90, 20 + int((completed_variants / total) * 65))


def submit_pipeline_run_task(request: PipelineRunTaskRequest) -> TaskRecord:
    tm = _task_manager()
    trace_id = uuid4()
    session_id = str(request.session_id or "pipeline").strip() or "pipeline"
    market = str(request.market or "").strip().upper() or str(settings.default_market or "US").strip().upper()
    parent = tm.create(
        task_type="pipeline_run",
        message="queued",
        status="queued",
        meta={
            "session_id": session_id,
            "trace_id": str(trace_id),
            "intent": "pipeline_run",
            "market": market,
        },
    )
    _emit_task_state(
        "task.created",
        trace_id,
        parent,
        session_id=session_id,
        role="parent",
        stage="pipeline.start",
    )

    def _worker() -> None:
        child_by_variant: dict[str, UUID] = {}
        child_task_ids: list[str] = []
        completed_children = 0
        total_variants_hint = 0

        def _upsert_parent_running(*, stage: str, completed_variants: int, total_variants: int, message_text: str) -> None:
            prev = tm.get(parent.task_id)
            parent_running = tm.update(
                parent.task_id,
                status="running",
                progress=_stage_progress_pct(
                    stage=stage,
                    completed_variants=completed_variants,
                    total_variants=total_variants,
                ),
                message=message_text,
                meta={
                    **(prev.meta if prev else {}),
                    "last_stage": stage,
                    "last_heartbeat_at": datetime.now(UTC).isoformat(),
                    "last_elapsed_ms": int(prev.meta.get("last_elapsed_ms", 0) if (prev and isinstance(prev.meta, dict)) else 0),
                    "completed_variants": completed_variants,
                    "total_variants": total_variants,
                },
            )
            _emit_task_state(
                "task.progress",
                trace_id,
                parent_running,
                session_id=session_id,
                role="parent",
                stage=stage,
                completed_variants=completed_variants,
                total_variants=total_variants,
            )

        def _ensure_child(variant_id: str, *, variant_index: int, total_variants: int) -> UUID:
            nonlocal total_variants_hint
            total_variants_hint = max(total_variants_hint, total_variants)
            existing = child_by_variant.get(variant_id)
            if existing is not None:
                return existing
            child = tm.create(
                task_type="backtest_variant",
                message=f"queued: {variant_id}",
                parent_task_id=parent.task_id,
                status="queued",
                meta={
                    "session_id": session_id,
                    "trace_id": str(trace_id),
                    "market": market,
                    "variant_id": variant_id,
                    "variant_index": variant_index,
                    "variant_total": total_variants,
                },
            )
            child_by_variant[variant_id] = child.task_id
            child_task_ids.append(str(child.task_id))
            _emit_task_state(
                "task.created",
                trace_id,
                child,
                session_id=session_id,
                role="child",
                parent_task_id=str(parent.task_id),
                variant_id=variant_id,
            )
            return child.task_id

        def _pipeline_progress(event_type: str, payload: dict[str, Any]) -> None:
            nonlocal completed_children, total_variants_hint
            variant_id = str(payload.get("variant_id") or "").strip()
            variant_index = int(payload.get("variant_index") or 1)
            total_variants = int(payload.get("total_variants") or total_variants_hint or 1)
            completed_variants = int(payload.get("completed_variants") or completed_children)
            stage = str(payload.get("stage") or "").strip()
            if total_variants > 0:
                total_variants_hint = max(total_variants_hint, total_variants)

            def _heartbeat_meta(base_meta: dict[str, Any] | None = None) -> dict[str, Any]:
                return {
                    **(base_meta or {}),
                    "last_stage": stage or "pipeline.running",
                    "last_heartbeat_at": datetime.now(UTC).isoformat(),
                    "last_elapsed_ms": int(payload.get("elapsed_ms") or 0),
                    "completed_variants": completed_variants,
                    "total_variants": max(1, total_variants_hint or total_variants),
                    "status_text": str(payload.get("status_text") or ""),
                }

            if event_type == "task.variant_started" and variant_id:
                child_id = _ensure_child(variant_id, variant_index=variant_index, total_variants=total_variants)
                child_running = tm.update(
                    child_id,
                    status="running",
                    progress=12,
                    message=f"running: {variant_id}",
                    meta=_heartbeat_meta((tm.get(child_id).meta if tm.get(child_id) else {})),
                )
                _emit_task_state(
                    "task.variant_started",
                    trace_id,
                    child_running,
                    session_id=session_id,
                    role="child",
                    parent_task_id=str(parent.task_id),
                    variant_id=variant_id,
                    stage="running",
                )
                _emit_task_state(
                    "task.progress",
                    trace_id,
                    child_running,
                    session_id=session_id,
                    role="child",
                    parent_task_id=str(parent.task_id),
                    variant_id=variant_id,
                    stage="running",
                )
                _upsert_parent_running(
                    stage="variants.running",
                    completed_variants=completed_variants,
                    total_variants=max(1, total_variants_hint or total_variants),
                    message_text=f"{completed_variants}/{max(1, total_variants_hint or total_variants)} variants completed",
                )
                return

            if event_type == "task.heartbeat":
                elapsed_ms = int(payload.get("elapsed_ms") or 0)
                status_text = str(payload.get("status_text") or "")
                if variant_id:
                    child_id = _ensure_child(variant_id, variant_index=variant_index, total_variants=total_variants)
                    child_prev = tm.get(child_id)
                    if child_prev is not None and child_prev.status in {"done", "error", "failed", "canceled"}:
                        return
                    child_running = tm.update(
                        child_id,
                        status="running",
                        progress=int(child_prev.progress if child_prev else 0),
                        message=status_text or (child_prev.message if child_prev else f"{stage}: {variant_id}"),
                        meta=_heartbeat_meta((child_prev.meta if child_prev else {})),
                    )
                    _emit_task_state(
                        "task.heartbeat",
                        trace_id,
                        child_running,
                        session_id=session_id,
                        role="child",
                        parent_task_id=str(parent.task_id),
                        variant_id=variant_id,
                        stage=stage or "running",
                        elapsed_ms=elapsed_ms,
                        status_text=status_text,
                    )
                    return
                parent_prev = tm.get(parent.task_id)
                parent_running = tm.update(
                    parent.task_id,
                    status="running",
                    progress=parent_prev.progress if parent_prev else 0,
                    message=status_text or (parent_prev.message if parent_prev else "pipeline running"),
                    meta=_heartbeat_meta((parent_prev.meta if parent_prev else {})),
                )
                _emit_task_state(
                    "task.heartbeat",
                    trace_id,
                    parent_running,
                    session_id=session_id,
                    role="parent",
                    parent_task_id=str(parent.task_id),
                    stage=stage or "pipeline.running",
                    elapsed_ms=elapsed_ms,
                    status_text=status_text,
                )
                return

            if event_type == "task.progress" and variant_id:
                child_id = _ensure_child(variant_id, variant_index=variant_index, total_variants=total_variants)
                if stage and not stage.startswith("variant."):
                    _upsert_parent_running(
                        stage=stage,
                        completed_variants=completed_variants,
                        total_variants=max(1, total_variants_hint or total_variants),
                        message_text=f"{completed_variants}/{max(1, total_variants_hint or total_variants)} variants completed",
                    )
                    return
                child_prev = tm.get(child_id)
                if child_prev is not None and child_prev.status in {"done", "error", "failed", "canceled"}:
                    return
                child_progress = 35 if stage == "variant.factor" else 52 if stage == "variant.strategy" else 72 if stage == "variant.backtest" else 28
                child_running = tm.update(
                    child_id,
                    status="running",
                    progress=child_progress,
                    message=f"{stage or 'running'}: {variant_id}",
                    meta=_heartbeat_meta((child_prev.meta if child_prev else {})),
                )
                child_stage = stage.replace("variant.", "") if stage else "running"
                _emit_task_state(
                    "task.progress",
                    trace_id,
                    child_running,
                    session_id=session_id,
                    role="child",
                    parent_task_id=str(parent.task_id),
                    variant_id=variant_id,
                    stage=child_stage,
                )
                return

            if event_type == "task.variant_done" and variant_id:
                child_id = _ensure_child(variant_id, variant_index=variant_index, total_variants=total_variants)
                run_id = str(payload.get("run_id") or "").strip()
                child_done = tm.update(
                    child_id,
                    status="done",
                    progress=100,
                    message=f"done: {variant_id}",
                    result={
                        "market": market,
                        "metrics": payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {},
                    },
                    result_ref={
                        "run_id": run_id,
                        "report_id": run_id,
                        "open_path": f"/reports/{run_id}" if run_id else "",
                    },
                )
                _emit_task_state(
                    "task.variant_done",
                    trace_id,
                    child_done,
                    session_id=session_id,
                    role="child",
                    parent_task_id=str(parent.task_id),
                    variant_id=variant_id,
                    run_id=run_id,
                )
                _emit_task_state(
                    "task.done",
                    trace_id,
                    child_done,
                    session_id=session_id,
                    role="child",
                    parent_task_id=str(parent.task_id),
                    variant_id=variant_id,
                    run_id=run_id,
                )
                completed_children = max(completed_children, int(payload.get("completed_variants") or completed_children + 1))
                _upsert_parent_running(
                    stage="variants.running",
                    completed_variants=completed_children,
                    total_variants=max(1, total_variants_hint or total_variants),
                    message_text=f"{completed_children}/{max(1, total_variants_hint or total_variants)} variants completed",
                )
                return

            if event_type == "task.progress" and not variant_id:
                _upsert_parent_running(
                    stage=stage or "pipeline.running",
                    completed_variants=completed_variants,
                    total_variants=max(1, total_variants_hint or total_variants),
                    message_text=f"{completed_variants}/{max(1, total_variants_hint or total_variants)} variants completed",
                )
                return

            if event_type == "task.error" and variant_id:
                child_id = _ensure_child(variant_id, variant_index=variant_index, total_variants=total_variants)
                err_text = str(payload.get("error_message") or "variant failed")
                prev = tm.get(child_id)
                child_error = tm.update(
                    child_id,
                    status="error",
                    progress=100,
                    message=f"error: {variant_id}",
                    error=err_text,
                    meta={
                        **(prev.meta if prev else {}),
                        "stacktrace": str(payload.get("stacktrace") or ""),
                    },
                )
                _emit_task_state(
                    "task.error",
                    trace_id,
                    child_error,
                    session_id=session_id,
                    role="child",
                    parent_task_id=str(parent.task_id),
                    variant_id=variant_id,
                    error_message=err_text,
                )
                return

            if event_type in {
                "agent.dispatched",
                "agent.completed",
                "tool.call.started",
                "tool.call.finished",
                "artifact.created",
                "audit.tail",
                "reasoning.step.created",
                "reasoning.step.updated",
                "reasoning.trace.final",
            }:
                linked_task_id = str(parent.task_id)
                if variant_id and variant_id in child_by_variant:
                    linked_task_id = str(child_by_variant[variant_id])
                _emit_observable_event(
                    event_type,
                    trace_id=trace_id,
                    session_id=session_id,
                    payload={
                        **payload,
                        "task_id": linked_task_id,
                        "parent_task_id": str(parent.task_id),
                        "session_id": session_id,
                        "trace_id": str(trace_id),
                    },
                )
                return

        try:
            _upsert_parent_running(stage="pipeline.start", completed_variants=0, total_variants=1, message_text="pipeline running")
            pipe = _engine().run(
                PipelineRequest.model_validate(request.model_dump()),
                trace_id=str(trace_id),
                progress_callback=_pipeline_progress,
            )
            run_market = str(getattr(pipe, "market", market) or market).strip().upper()
            parent_done = tm.update(
                parent.task_id,
                status="done",
                progress=100,
                message=f"{len(pipe.experiments)}/{len(pipe.experiments)} variants completed",
                result={
                    "run_id": str(pipe.run_id),
                    "plan_id": str(pipe.plan_id),
                    "dataset_version": str(pipe.dataset_version),
                    "strategy_version": str(pipe.strategy_version),
                    "market": run_market,
                    "reasoning_steps": list(getattr(pipe, "reasoning_steps", []) or []),
                    "summary": {
                        "selected_strategy": str(pipe.strategy_version),
                        "metrics": dict(pipe.backtest_metrics),
                        "factor_version": str(pipe.factor_version),
                        "evidence_pack_id": str(pipe.evidence_pack_id),
                        "trace_id": str(pipe.trace_id),
                        "reasoning_step_count": len(list(getattr(pipe, "reasoning_steps", []) or [])),
                    },
                    "pipeline_response": pipe.model_dump(mode="json"),
                },
                result_ref={
                    "run_id": str(pipe.run_id),
                    "report_id": str(pipe.run_id),
                    "open_path": f"/reports/{pipe.run_id}",
                    "compare_path": "/reports",
                    "plan_id": str(pipe.plan_id),
                    "evidence_pack_id": str(pipe.evidence_pack_id),
                },
                meta={
                    **(tm.get(parent.task_id).meta if tm.get(parent.task_id) else {}),
                    "child_task_ids": child_task_ids,
                    "evidence_pack_id": str(pipe.evidence_pack_id),
                    "last_stage": "pipeline.done",
                    "last_heartbeat_at": datetime.now(UTC).isoformat(),
                },
            )
            _emit_task_state(
                "task.done",
                trace_id,
                parent_done,
                session_id=session_id,
                role="parent",
                parent_task_id=str(parent.task_id),
                run_id=str(pipe.run_id),
                child_task_ids=child_task_ids,
            )
        except Exception as ex:
            parent_prev = tm.get(parent.task_id)
            parent_error = tm.update(
                parent.task_id,
                status="error",
                progress=100,
                message="pipeline failed",
                error=str(ex),
                meta={
                    **(parent_prev.meta if parent_prev else {}),
                    "stacktrace": traceback.format_exc(),
                    "child_task_ids": child_task_ids,
                    "last_stage": "pipeline.failed",
                    "last_heartbeat_at": datetime.now(UTC).isoformat(),
                },
            )
            _emit_task_state(
                "task.error",
                trace_id,
                parent_error,
                session_id=session_id,
                role="parent",
                parent_task_id=str(parent.task_id),
                error_message=str(ex),
            )
            for child_id in child_task_ids:
                child_uuid = UUID(child_id)
                row = tm.get(child_uuid)
                if row is None or row.status == "done":
                    continue
                child_error = tm.update(
                    child_uuid,
                    status="error",
                    progress=100,
                    message="cancelled due to parent failure",
                    error=str(ex),
                )
                _emit_task_state(
                    "task.error",
                    trace_id,
                    child_error,
                    session_id=session_id,
                    role="child",
                    parent_task_id=str(parent.task_id),
                )

    Thread(target=_worker, daemon=True).start()
    return parent


@router.post("/run", response_model=PipelineResponse)
def run_pipeline(request: PipelineRequest) -> PipelineResponse:
    try:
        return _engine().run(request)
    except MigrationPreflightBlockedError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(exc),
                "preflight_warnings": [row.model_dump(mode="json") for row in exc.warnings],
                "action_required": "Set migration_preflight_confirmed=true or auto_adjust_for_market_rules=true.",
            },
        ) from exc


@router.post("/run/submit", response_model=TaskRecord)
def submit_pipeline(request: PipelineRunTaskRequest) -> TaskRecord:
    try:
        return submit_pipeline_run_task(request)
    except MigrationPreflightBlockedError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(exc),
                "preflight_warnings": [row.model_dump(mode="json") for row in exc.warnings],
                "action_required": "Set migration_preflight_confirmed=true or auto_adjust_for_market_rules=true.",
            },
        ) from exc


@router.post("/plan", response_model=PlanCreateResponse)
def create_plan(request: PlanCreateRequest) -> PlanCreateResponse:
    return _engine().create_plan(request)
