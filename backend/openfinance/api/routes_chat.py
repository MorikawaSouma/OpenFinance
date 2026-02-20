import hashlib
import json
import re
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from openfinance.core.audit import AuditLogEntry, FileAuditStore
from openfinance.core.chat import ChatStore, ChatTurn
from openfinance.core.config import settings
from openfinance.core.events import event_bus
from openfinance.data.registry import DatasetRegistry
from openfinance.quant.backtest.report import BacktestReport, BacktestRequest
from openfinance.quant.backtest.run_registry import RunRegistry
from openfinance.research.pipeline import PipelineRequest, ResearchPipelineEngine
from openfinance.research.plan_registry import PlanRegistry

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    trace_id: str
    assistant_message: str
    evidence_pack_id: str
    cards: dict[str, dict] = Field(default_factory=dict)
    developer_payload: dict[str, str | dict | list] = Field(default_factory=dict)
    turns: list[ChatTurn]


@lru_cache(maxsize=1)
def _audit_store() -> FileAuditStore:
    return FileAuditStore(settings.audit_log_file)


@lru_cache(maxsize=1)
def _chat_store() -> ChatStore:
    return ChatStore(settings.chat_session_store_file)


@lru_cache(maxsize=1)
def _pipeline_engine() -> ResearchPipelineEngine:
    return ResearchPipelineEngine(
        audit_store=_audit_store(),
        dataset_registry=DatasetRegistry(settings.dataset_registry_file, settings.data_root),
        run_registry=RunRegistry(settings.run_registry_file),
        plan_registry=PlanRegistry(settings.plan_registry_file),
    )


def _infer_market(text: str) -> str:
    low = text.lower()
    if ("\u65e5\u7ecf" in text) or ("\u65e5\u672c" in text) or ("nikkei" in low) or (" jp " in f" {low} "):
        return "JP"
    if ("a\u80a1" in text) or ("\u6caa\u6df1" in text) or (" cn " in f" {low} "):
        return "CN"
    if ("crypto" in low) or ("\u52a0\u5bc6" in text) or ("\u6bd4\u7279\u5e01" in text):
        return "CRYPTO"
    return "US"


def _contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _detect_user_language(text: str) -> str:
    lower = text.lower()
    if "reply in english" in lower or "answer in english" in lower:
        return "en"
    if "请用中文" in text or "中文回答" in text:
        return "zh"
    zh_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    en_chars = len(re.findall(r"[a-zA-Z]", text))
    if zh_chars == 0:
        return "en"
    if zh_chars >= max(2, en_chars // 3):
        return "zh"
    return "en"


def _emit_chat_delta(trace_id: str, session_id: str, text: str) -> None:
    for i in range(0, len(text), 64):
        event_bus.publish(
            event_type="chat.delta",
            trace_id=trace_id,
            session_id=session_id,
            payload={"delta": text[i : i + 64]},
        )


def _plan_summary_items(plan: dict) -> list[str]:
    market = ",".join(plan.get("markets", []))
    objectives = ", ".join(plan.get("objectives", []))
    families = ", ".join(plan.get("candidate_strategy_families", []))
    return [
        f"market(s): {market}",
        f"objectives: {objectives}",
        f"families: {families}",
        f"experiments: {len(plan.get('experiment_matrix', []))}",
    ]


def _evidence_reference_lines(sources: list[dict]) -> list[str]:
    out: list[str] = []
    for source in sources[:2]:
        ts = source.get("published_at") or source.get("timestamp") or "n/a"
        out.append(f"- {source.get('title', 'untitled')} ({ts})")
    return out


def _expert_card_items(agent_outputs: list[dict]) -> list[str]:
    out: list[str] = []
    for row in agent_outputs:
        name = str(row.get("agent_name") or "agent")
        claim = str(row.get("claim") or row.get("summary") or "").strip()
        citations = row.get("citations", [])
        cite_titles: list[str] = []
        if isinstance(citations, list):
            for cite in citations[:2]:
                if not isinstance(cite, dict):
                    continue
                title = str(cite.get("title") or "").strip()
                ts = str(cite.get("timestamp") or "n/a")
                if title:
                    cite_titles.append(f"{title} ({ts})")
        cite_text = "; ".join(cite_titles) if cite_titles else "no citation"
        out.append(f"{name}: {claim} | cites: {cite_text}")
    return out


def _strategy_decision_card_items(strategy_decision: dict) -> list[str]:
    selected = strategy_decision.get("selected") if isinstance(strategy_decision, dict) else {}
    selected_name = str(selected.get("name") or "n/a")
    selected_rationale = str(selected.get("rationale") or "").strip()
    selected_tradeoff = str(selected.get("tradeoff_summary") or "").strip()
    items = [
        f"selected: {selected_name}",
        f"rationale: {selected_rationale or 'n/a'}",
        f"tradeoff: {selected_tradeoff or 'n/a'}",
    ]
    candidates = strategy_decision.get("candidates") if isinstance(strategy_decision, dict) else []
    if isinstance(candidates, list):
        for row in candidates[:3]:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "candidate")
            cost_profile = str(row.get("cost_profile") or "n/a")
            why_not = str(row.get("why_not_selected") or "n/a")
            items.append(f"{name} | cost={cost_profile} | why_not_selected={why_not}")
    return items


def _detect_modify_intent(message: str) -> tuple[str, dict[str, float]]:
    text = message.lower()
    ops: dict[str, float] = {}
    if ("成本" in message) or ("commission" in text) or ("slippage" in text) or ("cost" in text):
        if ("翻倍" in message) or ("double" in text):
            ops["cost_multiplier"] = 2.0
        else:
            mul = re.search(r"(?:成本|cost).{0,8}?(\d+(?:\.\d+)?)\s*倍", message, flags=re.IGNORECASE)
            if mul:
                ops["cost_multiplier"] = float(mul.group(1))
    dd_to = re.search(
        r"(?:回撤|drawdown).{0,20}?(?:改到|降到|到|目标)\s*(\d+(?:\.\d+)?)\s*%",
        message,
        flags=re.IGNORECASE,
    )
    if dd_to:
        ops["max_drawdown_target"] = float(dd_to.group(1)) / 100.0

    if ops and (
        ("再跑" in message)
        or ("重跑" in message)
        or ("再来一次" in message)
        or ("run again" in text)
        or ("回测" in message)
    ):
        return "modify_last_run", ops
    return "new_research", {}

def _mutated_strategy_version(base: str, ops: dict[str, float]) -> str:
    payload = json.dumps({"base": base, "ops": ops}, sort_keys=True, ensure_ascii=False)
    suffix = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]
    return f"{base}-iter-{suffix}"


def _metrics_diff(old_metrics: dict[str, object], new_metrics: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    keys = sorted(set(old_metrics.keys()) | set(new_metrics.keys()))
    for key in keys:
        old_v = old_metrics.get(key)
        new_v = new_metrics.get(key)
        if isinstance(old_v, (int, float)) and isinstance(new_v, (int, float)):
            delta: float | str = round(float(new_v) - float(old_v), 6)
        else:
            delta = "-"
        rows.append({"metric": key, "old": old_v, "new": new_v, "delta": delta})
    return rows


def _cost_diff(old_report: BacktestReport, new_report: BacktestReport) -> dict[str, float]:
    keys = ["commission_sum", "slippage_sum", "total"]
    out: dict[str, float] = {}
    for key in keys:
        old_v = float((old_report.cost_breakdown or {}).get(key, 0.0))
        new_v = float((new_report.cost_breakdown or {}).get(key, 0.0))
        out[f"{key}_old"] = round(old_v, 6)
        out[f"{key}_new"] = round(new_v, 6)
        out[f"{key}_delta"] = round(new_v - old_v, 6)
    return out


def _risk_action_diff(old_report: BacktestReport, new_report: BacktestReport) -> dict[str, object]:
    def _action_counts(report: BacktestReport) -> dict[str, int]:
        actions = report.diagnostics.get("risk_actions", [])
        rows = actions if isinstance(actions, list) else []
        counts: dict[str, int] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("action") or "unknown")
            counts[name] = counts.get(name, 0) + 1
        return counts

    old_counts = _action_counts(old_report)
    new_counts = _action_counts(new_report)
    all_keys = sorted(set(old_counts.keys()) | set(new_counts.keys()))
    delta: dict[str, int] = {}
    for key in all_keys:
        delta[key] = new_counts.get(key, 0) - old_counts.get(key, 0)
    return {
        "old_total": sum(old_counts.values()),
        "new_total": sum(new_counts.values()),
        "delta_total": sum(new_counts.values()) - sum(old_counts.values()),
        "old_by_action": old_counts,
        "new_by_action": new_counts,
        "delta_by_action": delta,
    }


def _detect_compare_intent(message: str) -> bool:
    text = message.lower()
    triggers = [
        "比上次",
        "上次差",
        "上上次",
        "why worse",
        "worse than last",
        "compare",
        "difference",
        "差在哪里",
        "为什么这次",
        "收益更高",
    ]
    return any(token in message or token in text for token in triggers)

def _safe_num(metrics: dict[str, object], key: str) -> float | None:
    value = metrics.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _attribution_diff(old_report: BacktestReport, new_report: BacktestReport) -> dict[str, object]:
    old_attr = old_report.attribution or {}
    new_attr = new_report.attribution or {}
    old_instr = old_attr.get("instrument_pnl_contrib") if isinstance(old_attr, dict) else {}
    new_instr = new_attr.get("instrument_pnl_contrib") if isinstance(new_attr, dict) else {}
    old_sector = old_attr.get("sector_pnl_contrib") if isinstance(old_attr, dict) else {}
    new_sector = new_attr.get("sector_pnl_contrib") if isinstance(new_attr, dict) else {}

    def _delta_map(old_map: object, new_map: object) -> list[dict[str, object]]:
        old_rows = old_map if isinstance(old_map, dict) else {}
        new_rows = new_map if isinstance(new_map, dict) else {}
        keys = sorted(set(old_rows.keys()) | set(new_rows.keys()))
        out: list[dict[str, object]] = []
        for key in keys:
            ov = old_rows.get(key, 0.0)
            nv = new_rows.get(key, 0.0)
            if isinstance(ov, (int, float)) and isinstance(nv, (int, float)):
                out.append(
                    {
                        "key": str(key),
                        "old": round(float(ov), 6),
                        "new": round(float(nv), 6),
                        "delta": round(float(nv) - float(ov), 6),
                    }
                )
        return sorted(out, key=lambda row: abs(float(row["delta"])), reverse=True)

    return {
        "instrument_delta_top": _delta_map(old_instr, new_instr)[:5],
        "sector_delta_top": _delta_map(old_sector, new_sector)[:5],
    }


def _compare_explanation(*, old_report: BacktestReport, new_report: BacktestReport, cost_diff: dict[str, float]) -> str:
    old_sharpe = _safe_num(old_report.metrics, "sharpe")
    new_sharpe = _safe_num(new_report.metrics, "sharpe")
    old_mdd = _safe_num(old_report.metrics, "max_drawdown")
    new_mdd = _safe_num(new_report.metrics, "max_drawdown")
    old_ret = _safe_num(old_report.metrics, "total_return")
    new_ret = _safe_num(new_report.metrics, "total_return")
    reason_lines: list[str] = []
    if old_sharpe is not None and new_sharpe is not None:
        reason_lines.append(f"Sharpe: {old_sharpe:.4f} -> {new_sharpe:.4f} ({new_sharpe - old_sharpe:+.4f})")
    if old_mdd is not None and new_mdd is not None:
        reason_lines.append(f"MaxDrawdown: {old_mdd:.4f} -> {new_mdd:.4f} ({new_mdd - old_mdd:+.4f})")
    if old_ret is not None and new_ret is not None:
        reason_lines.append(f"TotalReturn: {old_ret:.4f} -> {new_ret:.4f} ({new_ret - old_ret:+.4f})")
    reason_lines.append(f"Cost total delta: {cost_diff.get('total_delta', 0.0):+.6f}")
    return "\n".join(reason_lines)


def _load_report_by_run(run_id: str) -> BacktestReport | None:
    entry = _pipeline_engine().run_registry.get_entry(run_id)
    if entry is None:
        return None
    report_path = Path(entry.report_path)
    if not report_path.exists():
        return None
    return BacktestReport.model_validate_json(report_path.read_text(encoding="utf-8"))


def _run_session_compare(session_id: UUID, message: str) -> tuple[str, str, BacktestReport, BacktestReport] | None:
    pair = _chat_store().resolve_compare_pair(session_id, message)
    if pair is None:
        return None
    current_run_id, baseline_run_id = pair
    current_report = _load_report_by_run(current_run_id)
    baseline_report = _load_report_by_run(baseline_run_id)
    if current_report is None or baseline_report is None:
        return None
    return current_run_id, baseline_run_id, current_report, baseline_report


def _run_iterative_mutation(session_id: UUID, message: str) -> tuple[dict, BacktestRequest, BacktestReport, BacktestReport] | None:
    last_run_id, last_plan_id = _chat_store().get_last_context(session_id)
    if not last_run_id:
        return None
    run_registry = _pipeline_engine().run_registry
    entry = run_registry.get_entry(last_run_id)
    if entry is None:
        return None
    old_report_path = Path(entry.report_path)
    if not old_report_path.exists():
        return None
    old_report = BacktestReport.model_validate_json(old_report_path.read_text(encoding="utf-8"))
    base_request = BacktestRequest.model_validate(entry.request)
    _, ops = _detect_modify_intent(message)

    next_cost = base_request.cost_model.model_copy(deep=True)
    if "cost_multiplier" in ops:
        multiplier = max(0.1, ops["cost_multiplier"])
        next_cost.commission_bps = round(float(next_cost.commission_bps) * multiplier, 6)
        next_cost.slippage_bps = round(float(next_cost.slippage_bps) * multiplier, 6)
    next_constraints = dict(base_request.constraints)
    if "max_drawdown_target" in ops:
        next_constraints["max_drawdown_target"] = round(max(0.01, min(0.5, ops["max_drawdown_target"])), 4)

    new_request = base_request.model_copy(
        update={
            "strategy_version": _mutated_strategy_version(base_request.strategy_version, ops),
            "cost_model": next_cost,
            "constraints": next_constraints,
            "evaluation_plan": {
                **dict(base_request.evaluation_plan),
                "iteration_source_run_id": str(entry.run_id),
                "chat_modify_ops": ops,
            },
        },
        deep=True,
    )
    new_report = _pipeline_engine().runner.run(new_request)
    _chat_store().register_run(
        session_id,
        run_id=str(new_report.run_id),
        plan_id=last_plan_id,
        report_id=str(new_report.run_id),
        dataset_version=new_report.dataset_version,
        metrics=dict(new_report.metrics),
    )
    return (
        {
            "last_run_id": str(entry.run_id),
            "last_plan_id": last_plan_id,
            "ops": ops,
        },
        new_request,
        old_report,
        new_report,
    )


@router.post("/message", response_model=ChatResponse)
def chat_message(request: ChatRequest) -> ChatResponse:
    parsed_session_id = UUID(request.session_id) if request.session_id else None
    session = _chat_store().get_or_create(parsed_session_id)
    _chat_store().append_turn(session.session_id, role="user", content=request.message)

    trace_id = str(uuid4())
    response_language = _detect_user_language(request.message)
    event_bus.publish(
        event_type="task.created",
        trace_id=trace_id,
        session_id=str(session.session_id),
        payload={"stage": "chat.request.received"},
    )

    intent, ops = _detect_modify_intent(request.message)
    compare_intent = _detect_compare_intent(request.message)
    pipe = None
    cards: dict[str, dict] = {}
    developer_payload: dict[str, str | dict | list] = {}
    evidence_pack_id = "iterative-memory-no-evidence"
    if compare_intent:
        compared = _run_session_compare(session.session_id, request.message)
        if compared is not None:
            current_run_id, baseline_run_id, current_report, baseline_report = compared
            metrics_diff = _metrics_diff(baseline_report.metrics, current_report.metrics)
            cost_diff = _cost_diff(baseline_report, current_report)
            risk_diff = _risk_action_diff(baseline_report, current_report)
            attribution_diff = _attribution_diff(baseline_report, current_report)
            key_metrics = [row for row in metrics_diff if row["metric"] in {"total_return", "sharpe", "max_drawdown", "cost_drag"}]
            explanation = _compare_explanation(old_report=baseline_report, new_report=current_report, cost_diff=cost_diff)
            if response_language == "zh":
                user_answer = (
                    "已基于会话上下文自动定位 run 并完成对比分析。\n"
                    f"current_run={current_run_id} vs baseline_run={baseline_run_id}\n"
                    f"{explanation}"
                )
            else:
                user_answer = (
                    "Run comparison completed from session memory.\n"
                    f"current_run={current_run_id} vs baseline_run={baseline_run_id}\n"
                    f"{explanation}"
                )
            cards = {
                "run_compare": {
                    "summary": "Auto compare from session memory (no manual run_id required).",
                    "items": [
                        f"current_run: {current_run_id}",
                        f"baseline_run: {baseline_run_id}",
                        *[
                            f"{row['metric']}: old={row['old']} new={row['new']} delta={row['delta']}"
                            for row in key_metrics
                        ],
                        f"cost_total_delta: {cost_diff.get('total_delta', 0.0)}",
                        f"risk_actions_delta: {risk_diff.get('delta_total', 0)}",
                    ],
                },
                "diff": {
                    "summary": "Detailed metrics / cost / attribution deltas.",
                    "items": [
                        f"metrics_delta_count: {len(metrics_diff)}",
                        f"instrument_delta_top: {json.dumps(attribution_diff['instrument_delta_top'], ensure_ascii=False)}",
                        f"sector_delta_top: {json.dumps(attribution_diff['sector_delta_top'], ensure_ascii=False)}",
                    ],
                },
            }
            developer_payload = {
                "intent": "session_compare",
                "response_language": response_language,
                "run_compare": {
                    "current_run_id": current_run_id,
                    "baseline_run_id": baseline_run_id,
                    "metrics_diff": metrics_diff,
                    "cost_diff": cost_diff,
                    "risk_action_diff": risk_diff,
                    "attribution_diff": attribution_diff,
                    "explanation": explanation,
                },
                "session_memory": _chat_store().get_last_memory(session.session_id),
            }
            _audit_store().append(
                AuditLogEntry(
                    trace_id=UUID(trace_id),
                    event_type="chat.session_compare",
                    payload={
                        "session_id": str(session.session_id),
                        "current_run_id": current_run_id,
                        "baseline_run_id": baseline_run_id,
                    },
                    created_at=datetime.now(UTC),
                )
            )
            intent = "session_compare"
        else:
            intent = "new_research"

    if intent == "modify_last_run":
        iterative = _run_iterative_mutation(session.session_id, request.message)
        if iterative is not None:
            base_meta, mutated_request, old_report, new_report = iterative
            diffs = _metrics_diff(old_report.metrics, new_report.metrics)
            cost_diff = _cost_diff(old_report, new_report)
            risk_diff = _risk_action_diff(old_report, new_report)
            top_diffs = [row for row in diffs if row["metric"] in {"total_return", "sharpe", "max_drawdown", "cost_drag"}]
            if response_language == "zh":
                user_answer = (
                    "已基于同一会话的上次 run 做参数迭代并重跑。\n"
                    f"old_run={base_meta['last_run_id']} -> new_run={new_report.run_id}\n"
                    f"变更项: {json.dumps(base_meta['ops'], ensure_ascii=False)}\n"
                    f"新结果: Sharpe={new_report.metrics.get('sharpe')} | "
                    f"MDD={new_report.metrics.get('max_drawdown')} | Return={new_report.metrics.get('total_return')}\n"
                    "已生成 diff 指标对比，可在 Reports 继续做 run 对比。"
                )
            else:
                user_answer = (
                    "Iterative rerun completed from the previous run in this session.\n"
                    f"old_run={base_meta['last_run_id']} -> new_run={new_report.run_id}\n"
                    f"changes: {json.dumps(base_meta['ops'], ensure_ascii=False)}\n"
                    f"new metrics: Sharpe={new_report.metrics.get('sharpe')} | "
                    f"MDD={new_report.metrics.get('max_drawdown')} | Return={new_report.metrics.get('total_return')}\n"
                    "Diff metrics are ready in Reports."
                )
            cards = {
                "plan": {
                    "summary": "Iterative run cloned from last session run.",
                    "items": [
                        f"intent: {intent}",
                        f"last_run_id: {base_meta['last_run_id']}",
                        f"last_plan_id: {base_meta.get('last_plan_id') or 'n/a'}",
                    ],
                },
                "backtest": {
                    "summary": "Mutated backtest completed.",
                    "items": [f"{k}: {v}" for k, v in new_report.metrics.items()],
                },
                "diff": {
                    "summary": "Metrics delta between previous and current run.",
                    "items": [
                        f"{row['metric']}: old={row['old']} new={row['new']} delta={row['delta']}"
                        for row in top_diffs
                    ],
                },
                "risk": {
                    "summary": "Cost and risk-action delta.",
                    "items": [
                        f"cost_total_delta: {cost_diff['total_delta']}",
                        f"risk_actions_total_delta: {risk_diff['delta_total']}",
                        f"risk_delta_by_action: {json.dumps(risk_diff['delta_by_action'], ensure_ascii=False)}",
                    ],
                },
            }
            developer_payload = {
                "intent": intent,
                "response_language": response_language,
                "ops": base_meta["ops"],
                "plan_id": base_meta.get("last_plan_id"),
                "old_run_id": base_meta["last_run_id"],
                "run_id": str(new_report.run_id),
                "dataset_version": new_report.dataset_version,
                "strategy_version": new_report.strategy_version,
                "mutated_backtest_request": mutated_request.model_dump(mode="json"),
                "metrics_diff": diffs,
                "cost_diff": cost_diff,
                "risk_action_diff": risk_diff,
                "session_memory": _chat_store().get_last_memory(session.session_id),
            }
            _audit_store().append(
                AuditLogEntry(
                    trace_id=UUID(trace_id),
                    event_type="chat.modify_last_run",
                    payload={
                        "session_id": str(session.session_id),
                        "old_run_id": base_meta["last_run_id"],
                        "new_run_id": str(new_report.run_id),
                        "ops": base_meta["ops"],
                        "cost_diff": cost_diff,
                        "risk_action_diff": risk_diff,
                    },
                    created_at=datetime.now(UTC),
                )
            )
        else:
            intent = "new_research"

    if intent not in {"modify_last_run", "session_compare"}:
        market = _infer_market(request.message)
        pipe = _pipeline_engine().run(
            PipelineRequest(
                question=request.message,
                market=market,
                max_drawdown_target=0.10,
                run_paper_trade=True,
                experiments=3,
                response_language="zh" if response_language == "zh" else "en",
            )
        )
        _chat_store().register_run(
            session.session_id,
            run_id=str(pipe.run_id),
            plan_id=str(pipe.plan_id),
            report_id=str(pipe.run_id),
            dataset_version=str(pipe.dataset_version),
            metrics=dict(pipe.backtest_metrics),
        )
        best = pipe.comparison_table[0] if pipe.comparison_table else {}
        evidence_pack_id = pipe.evidence_pack_id
        evidence_lines = _evidence_reference_lines(pipe.evidence_sources)
        if len(evidence_lines) < 2:
            evidence_lines.extend(["- source unavailable (n/a)"] * (2 - len(evidence_lines)))
        if response_language == "zh":
            user_answer = (
                f"研究计划已生成，并完成 {len(pipe.experiments)} 个实验变体回测。\n"
                f"首选方案：{best.get('variant_id')} / {best.get('strategy_family')}\n"
                f"Sharpe={best.get('sharpe')} | MDD={best.get('max_drawdown')} | Return={best.get('total_return')}\n\n"
                f"证据引用：\n{chr(10).join(evidence_lines)}\n\n"
                f"解释：{pipe.interpretation}\n\n"
                f"风控门禁：{pipe.risk_explanation}"
            )
        else:
            user_answer = (
                f"Research plan generated, with {len(pipe.experiments)} experiment variants backtested.\n"
                f"Top pick: {best.get('variant_id')} / {best.get('strategy_family')}\n"
                f"Sharpe={best.get('sharpe')} | MDD={best.get('max_drawdown')} | Return={best.get('total_return')}\n\n"
                f"Evidence references:\n{chr(10).join(evidence_lines)}\n\n"
                f"Interpretation: {pipe.interpretation}\n\n"
                f"Risk gate: {pipe.risk_explanation}"
            )

        plan = pipe.research_plan
        agent_outputs = list(pipe.agent_outputs)
        strategy_decision = dict(pipe.strategy_decision or {})
        cards = {
            "plan": {
                "summary": "Question-specific plan generated.",
                "items": _plan_summary_items(plan),
            },
            "experiments": {
                "summary": f"{len(pipe.comparison_table)} variants compared under same dataset_version.",
                "items": [
                    f"{row.get('variant_id')} | sharpe={row.get('sharpe')} | mdd={row.get('max_drawdown')} | score={row.get('objective_score')}"
                    for row in pipe.comparison_table[:5]
                ],
            },
            "evidence": {
                "summary": f"Evidence pack {pipe.evidence_pack_id} linked to planning and explanation.",
                "items": [
                    f"{source.get('title')} | type={source.get('source_type') or 'unknown'} | "
                    f"ts={source.get('published_at')} | credibility={source.get('credibility_score')}"
                    for source in pipe.evidence_sources
                ],
            },
            "factors": {
                "summary": "Candidate factors and lag controls from plan.",
                "items": [
                    f"{row.get('factor_id')} | lag={row.get('availability_lag')} | source={row.get('source')}"
                    for row in plan.get("candidate_factors", [])[:5]
                ]
                + [
                    f"IC mean: {pipe.factor_report.get('ic_mean')}",
                    f"RankIC mean: {pipe.factor_report.get('rank_ic_mean')}",
                    f"t-stat: {pipe.factor_report.get('t_stat')}",
                ],
            },
            "strategy": {
                "summary": f"Best strategy version {pipe.strategy_version} selected from experiment matrix.",
                "items": [f"{k}: {v}" for k, v in pipe.strategy_config.items() if k in {"rebalance", "lookback_days", "strategy_family", "risk_budget", "max_position"}],
            },
            "strategy_decision": {
                "summary": "A/B strategy candidates with explicit trade-off explanation.",
                "items": _strategy_decision_card_items(strategy_decision),
            },
            "backtest": {
                "summary": "Best run metrics.",
                "items": [f"{k}: {v}" for k, v in pipe.backtest_metrics.items()],
            },
            "interpretation": {
                "summary": "LLM explanation over evidence and experiment results.",
                "items": [pipe.interpretation],
            },
            "experts": {
                "summary": "Evidence-grounded expert claims with citations.",
                "items": _expert_card_items(agent_outputs),
            },
            "risk": {
                "summary": pipe.risk_explanation,
                "items": [f"paper_trade: {pipe.paper_trade_result}"],
            },
        }
        developer_payload = {
            "intent": "new_research",
            "ops": ops,
            "trace_id": pipe.trace_id,
            "plan_id": pipe.plan_id,
            "plan_sections": {
                "value": plan.get("value", {}),
                "macro": plan.get("macro", {}),
                "stats": plan.get("stats", {}),
                "behavior": plan.get("behavior", {}),
            },
            "dataset_version": pipe.dataset_version,
            "strategy_version": pipe.strategy_version,
            "factor_version": pipe.factor_version,
            "factor_report": pipe.factor_report,
            "factor_artifact_path": pipe.factor_artifact_path,
            "run_id": pipe.run_id,
            "evidence_pack_id": pipe.evidence_pack_id,
            "evidence_sources": pipe.evidence_sources,
            "agent_outputs": agent_outputs,
            "llm_mode": pipe.llm_mode,
            "comparison_table": pipe.comparison_table,
            "strategy_decision": strategy_decision,
            "experiments": [row.model_dump(mode="json") for row in pipe.experiments],
            "steps": [row.model_dump(mode="json") for row in pipe.steps],
            "session_memory": _chat_store().get_last_memory(session.session_id),
            "response_language": response_language,
        }

    _chat_store().append_turn(session.session_id, role="assistant", content=user_answer)
    _emit_chat_delta(trace_id=trace_id, session_id=str(session.session_id), text=user_answer)
    event_bus.publish(
        event_type="chat.done",
        trace_id=trace_id,
        session_id=str(session.session_id),
        payload={"message": user_answer},
    )

    _audit_store().append(
        AuditLogEntry(
            trace_id=UUID(trace_id),
            event_type="chat.response",
            payload={
                "session_id": str(session.session_id),
                "plan_id": str(developer_payload.get("plan_id") or ""),
                "pipeline_trace_id": str(developer_payload.get("trace_id") or "iterative"),
                "pipeline_run_id": str(developer_payload.get("run_id") or ""),
                "llm_mode": str(developer_payload.get("llm_mode") or ("iterative_modify" if intent == "modify_last_run" else "unknown")),
                "intent": intent,
            },
            created_at=datetime.now(UTC),
        )
    )

    turns = _chat_store().list_turns(session.session_id)
    return ChatResponse(
        session_id=str(session.session_id),
        trace_id=trace_id,
        assistant_message=user_answer,
        evidence_pack_id=evidence_pack_id,
        cards=cards,
        developer_payload=developer_payload,
        turns=turns,
    )


@router.get("/sessions/{session_id}", response_model=list[ChatTurn])
def chat_history(session_id: str) -> list[ChatTurn]:
    try:
        parsed = UUID(session_id)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail="invalid session_id") from ex
    return _chat_store().list_turns(parsed)


@router.get("/sessions")
def chat_sessions() -> list[dict[str, object]]:
    rows = _chat_store().list_sessions()
    out: list[dict[str, object]] = []
    for session in rows:
        last = session.turns[-1].content if session.turns else ""
        out.append(
            {
                "session_id": str(session.session_id),
                "last_message": last[:80],
                "updated_at": session.updated_at.isoformat(),
                "last_plan_id": session.last_plan_id or "",
                "last_run_id": session.last_run_id or "",
                "last_report_id": session.last_report_id or "",
                "last_dataset_version": session.last_dataset_version or "",
                "recent_run_ids": [str(row.get("run_id")) for row in session.runs_by_session[-5:]],
            }
        )
    return out


