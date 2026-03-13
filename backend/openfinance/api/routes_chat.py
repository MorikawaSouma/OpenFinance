import hashlib
import json
import logging
import re
import time
import traceback
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from openfinance.api.routes_workbench import (
    MultiMarketCompareRequest,
    RobustnessRunRequest,
    submit_multi_market_compare_task,
    submit_robustness_task,
)
from openfinance.api.routes_trading import _service as _trading_service

from openfinance.agents.schemas import ReasoningEvidenceRef, ReasoningTraceStep
from openfinance.chat.general_info import GeneralInfoAnswerer
from openfinance.chat.market_compare import MarketCompareBuilder
from openfinance.core.audit import AuditLogEntry, FileAuditStore
from openfinance.core.chat import ChatStore, ChatTurn
from openfinance.core.config import settings
from openfinance.core.events import event_bus
from openfinance.core.tasks import TaskRecord, get_task_manager
from openfinance.data.registry import DatasetRegistry
from openfinance.knowledge.evidence import EvidencePack
from openfinance.knowledge.service import KnowledgeService, build_default_knowledge_service
from openfinance.markets.plugins import build_market_rules_provider
from openfinance.quant.backtest.migration import MigrationChecker, MigrationWarning
from openfinance.quant.backtest.report import BacktestReport, BacktestRequest
from openfinance.quant.backtest.run_registry import RunRegistry
from openfinance.research.pipeline import PipelineRequest, ResearchPipelineEngine
from openfinance.research.plan_registry import PlanRegistry

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    include_debug: bool = False


class PresentationMetric(BaseModel):
    name: str
    value: str | float | int | None = None
    delta: str | float | None = None


class PresentationAction(BaseModel):
    label: str
    action: str
    payload: dict[str, str | float | int | bool] = Field(default_factory=dict)


class PresentationCard(BaseModel):
    card_id: str | None = None
    type: str
    title: str
    content: str | None = None
    subtitle: str | None = None
    metrics: list[PresentationMetric] = Field(default_factory=list)
    items: list[dict[str, Any] | str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    table: list[dict[str, str | float | int | None]] = Field(default_factory=list)
    actions: list[PresentationAction] = Field(default_factory=list)


class RiskSnapshot(BaseModel):
    live_lock_status: str
    kill_switch: bool
    drawdown: float
    volatility: float
    limits: dict[str, float] = Field(default_factory=dict)
    risk_level: str
    live_trading_enabled: bool = False
    paper_trading_enabled: bool = False
    updated_at: str


class ApprovalSnapshotRow(BaseModel):
    request_id: str
    status: str
    created_at: str
    target: str
    use_case: str | None = None
    plan_id: str | None = None


class ApprovalsSnapshot(BaseModel):
    items: list[ApprovalSnapshotRow] = Field(default_factory=list)
    updated_at: str


class ChatResponse(BaseModel):
    session_id: str
    trace_id: str
    message_id: str
    mode: str
    language: str
    assistant_message: str
    evidence_pack_id: str
    cards: list[PresentationCard] = Field(default_factory=list)
    risk_snapshot: RiskSnapshot | None = None
    approvals_snapshot: ApprovalsSnapshot | None = None
    debug: dict[str, Any] = Field(default_factory=dict)
    turns: list[ChatTurn]


@lru_cache(maxsize=1)
def _audit_store() -> FileAuditStore:
    return FileAuditStore(settings.audit_log_file)


@lru_cache(maxsize=1)
def _chat_store() -> ChatStore:
    return ChatStore(settings.chat_session_store_file)


@lru_cache(maxsize=1)
def _task_manager():
    return get_task_manager()


@lru_cache(maxsize=1)
def _pipeline_engine() -> ResearchPipelineEngine:
    return ResearchPipelineEngine(
        audit_store=_audit_store(),
        dataset_registry=DatasetRegistry(settings.dataset_registry_file, settings.data_root),
        run_registry=RunRegistry(settings.run_registry_file),
        plan_registry=PlanRegistry(settings.plan_registry_file),
    )


@lru_cache(maxsize=1)
def _knowledge() -> KnowledgeService:
    return build_default_knowledge_service()


@lru_cache(maxsize=1)
def _general_info_answerer() -> GeneralInfoAnswerer:
    return GeneralInfoAnswerer()


@lru_cache(maxsize=1)
def _market_compare_builder() -> MarketCompareBuilder:
    return MarketCompareBuilder()


@lru_cache(maxsize=1)
def _migration_checker() -> MigrationChecker:
    return MigrationChecker()


@lru_cache(maxsize=1)
def _market_rules_provider():
    return build_market_rules_provider()


def _build_risk_snapshot() -> RiskSnapshot:
    status = _trading_service().status()
    now = datetime.now(UTC).isoformat()
    lock_state = str(status.live_approval_state or ("enabled" if status.live_trading_enabled else "locked"))
    return RiskSnapshot(
        live_lock_status=lock_state,
        kill_switch=bool(status.kill_switch_enabled),
        drawdown=float(status.current_drawdown or 0.0),
        volatility=float(status.current_volatility or 0.0),
        limits={
            "max_account_drawdown_limit": float(status.max_account_drawdown_limit or 0.0),
            "abnormal_volatility_limit": float(status.abnormal_volatility_limit or 0.0),
            "risk_max_order_qty": float(status.risk_max_order_qty or 0.0),
        },
        risk_level=str(status.risk_status or "normal"),
        live_trading_enabled=bool(status.live_trading_enabled),
        paper_trading_enabled=bool(status.paper_trading_enabled),
        updated_at=now,
    )


def _build_approvals_snapshot(*, limit: int = 8) -> ApprovalsSnapshot:
    rows = _trading_service().list_approvals()
    normalized = sorted(rows, key=lambda item: item.created_at, reverse=True)[: max(1, limit)]
    return ApprovalsSnapshot(
        items=[
            ApprovalSnapshotRow(
                request_id=str(item.request_id),
                status=str(item.status),
                created_at=item.created_at.isoformat(),
                target=str(item.target),
                use_case=str((item.context or {}).get("use_case") or "").strip() or None,
                plan_id=str((item.context or {}).get("plan_id") or "").strip() or None,
            )
            for item in normalized
        ],
        updated_at=datetime.now(UTC).isoformat(),
    )


def _emit_reasoning_step_event(
    *,
    trace_id: str,
    session_id: str,
    step: ReasoningTraceStep,
    event_type: str = "reasoning.step.created",
) -> None:
    payload = {
        "step": step.model_dump(mode="json"),
        "agent_name": step.agent_name,
        "step_idx": step.step_idx,
        "step_type": step.step_type,
        "title": step.title,
        "summary": step.summary,
        "evidence_refs": [row.model_dump(mode="json") for row in step.evidence_refs],
        "parse_error": step.parse_error,
        "prompt_hash": step.prompt_hash,
    }
    _audit_store().append(
        AuditLogEntry(
            trace_id=UUID(trace_id),
            event_type=event_type,
            payload=payload,
            created_at=datetime.now(UTC),
        )
    )
    event_bus.publish(
        event_type=event_type,
        trace_id=trace_id,
        session_id=session_id,
        payload=payload,
    )


def _build_general_info_reasoning_steps(
    *,
    trace_id: str,
    session_id: str,
    market: str,
    citations: list[dict[str, Any]],
    llm_prompt_hash: str,
) -> list[ReasoningTraceStep]:
    now = datetime.now(UTC).isoformat()
    evidence_refs = [
        ReasoningEvidenceRef(
            source_id=str(row.get("source_id") or ""),
            title=str(row.get("title") or ""),
            ts=str(row.get("timestamp") or ""),
        )
        for row in citations[:3]
        if str(row.get("source_id") or "").strip()
    ]
    return [
        ReasoningTraceStep(
            trace_id=trace_id,
            task_id="",
            session_id=session_id,
            agent_name="GeneralInfo",
            step_idx=1,
            step_type="hypothesis",
            title="Intent Classification",
            summary=f"Classified request as general market information for {market}.",
            evidence_refs=[],
            confidence_delta=0.0,
            prompt_hash=llm_prompt_hash,
            created_at=now,
        ),
        ReasoningTraceStep(
            trace_id=trace_id,
            task_id="",
            session_id=session_id,
            agent_name="GeneralInfo",
            step_idx=2,
            step_type="evidence_use",
            title="Evidence Retrieval",
            summary=f"Retrieved and ranked {len(evidence_refs)} key sources for synthesis.",
            evidence_refs=evidence_refs,
            confidence_delta=0.08 if evidence_refs else None,
            prompt_hash=llm_prompt_hash,
            created_at=now,
        ),
        ReasoningTraceStep(
            trace_id=trace_id,
            task_id="",
            session_id=session_id,
            agent_name="GeneralInfo",
            step_idx=3,
            step_type="decision",
            title="Answer Synthesis",
            summary="Generated user-safe summary with citations and risk/watch points.",
            evidence_refs=evidence_refs[:2],
            confidence_delta=None,
            prompt_hash=llm_prompt_hash,
            created_at=now,
        ),
    ]


def _infer_market(text: str) -> str:
    market = _detect_explicit_market(text)
    if market:
        return market
    return str(settings.default_market or "US").strip().upper() or "US"


def _normalize_market_value(value: str | None) -> str | None:
    raw = str(value or "").strip().upper()
    if raw in {"US", "CN", "JP", "CRYPTO"}:
        return raw
    alias = {
        "JAPAN": "JP",
        "NIKKEI": "JP",
        "CHINA": "CN",
        "A-SHARE": "CN",
        "A_SHARE": "CN",
        "A SHARE": "CN",
        "US_EQ": "US",
        "U.S.": "US",
        "U.S": "US",
        "USA": "US",
        "BTC": "CRYPTO",
    }.get(raw)
    if alias in {"US", "CN", "JP", "CRYPTO"}:
        return alias
    return None


def _detect_explicit_market(text: str) -> str | None:
    message = str(text or "")
    if not message.strip():
        return None
    low = message.lower()
    markers: list[tuple[int, str]] = []

    # JP
    for token in ("\u65e5\u80a1", "\u65e5\u672c", "\u65e5\u7ecf", "nikkei", "japan"):
        idx = low.find(token.lower())
        if idx >= 0:
            markers.append((idx, "JP"))
    for pattern in (r"(?<![a-zA-Z0-9])JP(?![a-zA-Z0-9])", r"\bjp\b", r"\bjp\s*market\b", "jp市场"):
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            markers.append((match.start(), "JP"))

    # US
    for token in ("\u7f8e\u80a1", "\u6807\u666e", "\u7eb3\u6307", "\u9053\u743c\u65af", "nasdaq", "sp500", "s&p", "dow jones"):
        idx = low.find(token.lower())
        if idx >= 0:
            markers.append((idx, "US"))
    for pattern in (r"(?<![a-zA-Z0-9])US(?![a-zA-Z0-9])", "us市场", r"\bus\s+market\b", r"\bu\.?s\.?\s+market\b"):
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            markers.append((match.start(), "US"))

    # CN
    for token in ("a\u80a1", "\u6caa\u6df1", "\u4e2d\u8bc1", "\u4e2d\u56fd\u5e02\u573a", "china", "cn market"):
        idx = low.find(token.lower())
        if idx >= 0:
            markers.append((idx, "CN"))
    for pattern in (r"(?<![a-zA-Z0-9])CN(?![a-zA-Z0-9])", "cn市场"):
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            markers.append((match.start(), "CN"))

    # CRYPTO
    for token in ("\u52a0\u5bc6", "\u6bd4\u7279\u5e01", "crypto", "bitcoin", "btc"):
        idx = low.find(token.lower())
        if idx >= 0:
            markers.append((idx, "CRYPTO"))

    if not markers:
        return None
    markers.sort(key=lambda item: item[0])
    return markers[0][1]


def resolve_market(
    *,
    message: str,
    session_state: dict[str, Any] | None,
    explicit_request: str | None = None,
) -> tuple[str, str]:
    explicit = _normalize_market_value(explicit_request)
    if explicit:
        return explicit, "explicit_request"

    from_message = _detect_explicit_market(message)
    if from_message:
        return from_message, "explicit_message"

    memory = session_state or {}
    last_market = _normalize_market_value(str(memory.get("last_market") or ""))
    low = str(message or "").lower()
    refers_current_market = any(token in low for token in ["\u5f53\u524d\u5e02\u573a", "current market", "this market"])
    if refers_current_market and last_market:
        return last_market, "session_current_market"
    if last_market:
        return last_market, "session_last_market"
    default_market = _normalize_market_value(str(settings.default_market or "US")) or "US"
    return default_market, "default"


_PREFLIGHT_CONTEXTS: dict[str, dict[str, Any]] = {}
_PREFLIGHT_LOCK = Lock()
_PREFLIGHT_TTL_S = 15 * 60


def _cleanup_preflight_contexts(now_ts: float | None = None) -> None:
    now = float(now_ts or time.time())
    with _PREFLIGHT_LOCK:
        expired = [token for token, row in _PREFLIGHT_CONTEXTS.items() if now - float(row.get("created_ts") or now) > _PREFLIGHT_TTL_S]
        for token in expired:
            _PREFLIGHT_CONTEXTS.pop(token, None)


def _store_preflight_context(
    *,
    session_id: UUID,
    message: str,
    market: str,
    response_language: str,
    warnings: list[dict[str, str]],
) -> str:
    _cleanup_preflight_contexts()
    token = uuid4().hex[:12]
    with _PREFLIGHT_LOCK:
        _PREFLIGHT_CONTEXTS[token] = {
            "session_id": str(session_id),
            "message": message,
            "market": market,
            "response_language": response_language,
            "warnings": warnings,
            "created_ts": time.time(),
            "confirm_ready": False,
        }
    return token


def _get_preflight_context(token: str) -> dict[str, Any] | None:
    _cleanup_preflight_contexts()
    with _PREFLIGHT_LOCK:
        return dict(_PREFLIGHT_CONTEXTS.get(token) or {}) or None


def _mark_preflight_confirm_ready(token: str) -> None:
    with _PREFLIGHT_LOCK:
        row = _PREFLIGHT_CONTEXTS.get(token)
        if not row:
            return
        row["confirm_ready"] = True
        row["created_ts"] = time.time()
        _PREFLIGHT_CONTEXTS[token] = row


def _drop_preflight_context(token: str) -> None:
    with _PREFLIGHT_LOCK:
        _PREFLIGHT_CONTEXTS.pop(token, None)


def _parse_preflight_action(message: str) -> tuple[str, str] | None:
    raw = str(message or "").strip()
    match = re.fullmatch(r"__preflight__:(adjust|proceed|confirm|cancel):([A-Za-z0-9]{6,40})", raw)
    if not match:
        return None
    return str(match.group(1)), str(match.group(2))


def _preflight_suggested_fixes(code: str, market: str) -> list[str]:
    code_key = str(code or "").lower()
    market_key = str(market or "").upper()
    if code_key == "cn_t_plus_one_high_frequency":
        return [
            f"Switch rebalance to daily or weekly for {market_key} market microstructure.",
            "Reduce turnover target and extend lookback horizon.",
        ]
    if code_key == "lot_size_precision_mismatch":
        return [
            "Enable auto_round_lot to satisfy lot-size constraints.",
            "Lower leverage/max_position to reduce lot-size rounding drift.",
        ]
    if code_key == "trading_session_coverage_gap":
        return [
            "Move execution time into local exchange trading session.",
            "Avoid intraday timing assumptions for cross-timezone migration.",
        ]
    return ["Review market rules and adjust rebalance, turnover, and execution assumptions."]


def _is_high_frequency_request(message: str) -> bool:
    low = str(message or "").lower()
    tokens = ["高频", "日内", "intraday", "high frequency", "high-frequency", "hft", "分钟", "minute"]
    return any(token in low or token in str(message or "") for token in tokens)


def _draft_preflight_strategy_spec(*, message: str, market: str) -> dict[str, Any]:
    high_frequency = _is_high_frequency_request(message)
    low = str(message or "").lower()
    auto_round_lot = not ("no round lot" in low or "disable lot round" in low or "禁用手数" in str(message or ""))
    return {
        "market": market,
        "strategy_family": "intraday_high_freq" if high_frequency else "trend",
        "rebalance": "daily" if high_frequency else "weekly",
        "lookback_days": 3 if high_frequency else 20,
        "max_position": 0.15,
        "leverage_limit": 1.0,
        "auto_round_lot": auto_round_lot,
        "run_time_utc": "03:30" if market == "CN" else "14:00",
    }


def _chat_preflight_warnings(*, message: str, market: str) -> list[dict[str, str]]:
    market_key = _normalize_market_value(market) or "US"
    rules = _market_rules_provider().get(market_key)
    warnings: list[MigrationWarning] = _migration_checker().check(
        strategy_spec=_draft_preflight_strategy_spec(message=message, market=market_key),
        market=market_key,
        rules=rules,
    )
    out: list[dict[str, str]] = []
    for item in warnings:
        severity = "block" if str(item.severity).lower() == "high" else "warn"
        out.append(
            {
                "market": market_key,
                "severity": severity,
                "reason_code": str(item.code),
                "title": str(item.title),
                "message": str(item.explanation),
                "suggested_fixes": "; ".join(_preflight_suggested_fixes(str(item.code), market_key)),
            }
        )
    return out


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


def _contains_any(message: str, low: str, tokens: list[str]) -> list[str]:
    hits: list[str] = []
    for token in tokens:
        if any("\u4e00" <= ch <= "\u9fff" for ch in token):
            if token in message:
                hits.append(token)
        else:
            if token in low:
                hits.append(token)
    return hits


def _detect_pipeline_research_intent(message: str) -> tuple[bool, list[str]]:
    low = message.lower()
    explicit_tokens = [
        "\u56de\u6d4b",
        "\u7a33\u5065\u6027",
        "\u53c2\u6570",
        "\u7ed9\u6211\u7b56\u7565",
        "\u7b56\u7565\u5e76\u56de\u6d4b",
        "\u8dd1\u4e00\u4e0b",
        "\u505a\u91cf\u5316",
        "backtest",
        "strategy",
        "run backtest",
        "rerun",
        "run again",
        "robustness",
        "parameter",
        "quant",
    ]
    concept_prefixes = [
        "\u4ec0\u4e48\u662f",
        "\u8bf7\u89e3\u91ca",
        "\u4ecb\u7ecd\u4e00\u4e0b",
        "what is",
        "explain",
        "tell me about",
    ]
    if any(low.strip().startswith(prefix) or message.strip().startswith(prefix) for prefix in concept_prefixes):
        return False, []
    hits = _contains_any(message=message, low=low, tokens=explicit_tokens)
    return len(hits) > 0, hits


def _detect_general_info_intent(message: str) -> tuple[bool, list[str]]:
    low = message.lower()
    query_tokens = [
        "\u6700\u8fd1\u5982\u4f55",
        "\u6700\u8fd1\u600e\u4e48\u6837",
        "\u8fd1\u671f\u600e\u4e48\u6837",
        "\u53d1\u751f\u4e86\u4ec0\u4e48",
        "\u539f\u56e0\u662f\u4ec0\u4e48",
        "\u4e3a\u4ec0\u4e48",
        "\u4ec0\u4e48\u662f",
        "\u6709\u4ec0\u4e48\u91cd\u8981\u6d88\u606f",
        "\u91cd\u8981\u6d88\u606f",
        "\u884c\u60c5\u7efc\u8ff0",
        "how is",
        "what happened",
        "what's happening",
        "why did",
        "what is",
        "important news",
        "market summary",
    ]
    hits = _contains_any(message=message, low=low, tokens=query_tokens)
    if hits:
        return True, hits
    if re.search(r"[\u4e00-\u9fff].*(\u600e\u4e48\u6837|\u5982\u4f55|\u539f\u56e0)", message):
        return True, ["regex:market-summary-cn"]
    if re.search(r"(how|why|what).*(market|stocks|equity|index|macro|crypto)", low):
        return True, ["regex:market-summary-en"]
    return False, []


def _detect_market_compare_intent(message: str) -> tuple[bool, dict[str, str], list[str]]:
    low = message.lower()
    compare_tokens = [
        "对比",
        "比较",
        "同一框架",
        "哪个更稳",
        "美股和日股",
        "us和jp",
        "us vs jp",
        "compare",
        "versus",
        "vs",
        "cross-market",
    ]
    compare_hits = _contains_any(message=message, low=low, tokens=compare_tokens)
    if not compare_hits:
        return False, {}, []

    us_hits = _contains_any(
        message=message,
        low=low,
        tokens=["美股", "us", "u.s.", "sp500", "nasdaq", "dow", "标普", "纳指"],
    )
    jp_hits = _contains_any(
        message=message,
        low=low,
        tokens=["日股", "jp", "japan", "nikkei", "日经", "日本"],
    )
    if us_hits and jp_hits:
        return True, {"left_market": "US", "right_market": "JP"}, compare_hits + us_hits + jp_hits
    return False, {}, compare_hits


def _detect_multi_market_task_intent(message: str) -> tuple[str | None, list[str]]:
    low = message.lower()
    compare_scope_hits = _contains_any(
        message=message,
        low=low,
        tokens=[
            "多市场",
            "可比回测",
            "比较报告",
            "multi-market",
            "comparable backtest",
            "compare report",
            "cross-market report",
        ],
    )
    run_hits = _contains_any(
        message=message,
        low=low,
        tokens=[
            "运行",
            "跑",
            "回测",
            "报告",
            "run",
            "backtest",
            "report",
        ],
    )
    robust_hits = _contains_any(
        message=message,
        low=low,
        tokens=[
            "稳健性",
            "鲁棒",
            "高波动",
            "robustness",
            "stress",
            "high volatility",
        ],
    )
    us_hits = _contains_any(
        message=message,
        low=low,
        tokens=["美股", "us", "u.s.", "sp500", "nasdaq", "标普", "纳指"],
    )
    jp_hits = _contains_any(
        message=message,
        low=low,
        tokens=["日股", "jp", "japan", "nikkei", "日经", "日本"],
    )
    if not (us_hits and jp_hits):
        return None, []
    if robust_hits and run_hits:
        return "multi_market_robustness", robust_hits + run_hits + us_hits + jp_hits
    if compare_scope_hits and run_hits:
        return "multi_market_compare_report", compare_scope_hits + run_hits + us_hits + jp_hits
    return None, []


def _detect_risk_control_intent(message: str) -> tuple[str | None, dict[str, str]]:
    text = str(message or "")
    low = text.lower()
    if any(token in text for token in ["解锁交易", "申请解锁", "开启实盘"]) or "unlock live" in low or "request unlock" in low:
        return "risk_request_unlock", {}
    if any(token in text for token in ["开启纸交易", "启动纸交易"]) or "start paper" in low:
        return "risk_paper_start", {}
    if any(token in text for token in ["停止纸交易", "关闭纸交易"]) or "stop paper" in low:
        return "risk_paper_stop", {}
    if any(token in text for token in ["打开熔断", "开启熔断", "打开kill switch"]) or "enable kill switch" in low:
        return "risk_kill_switch_on", {}
    if any(token in text for token in ["关闭熔断", "取消熔断", "关闭kill switch"]) or "disable kill switch" in low:
        return "risk_kill_switch_off", {}

    action_patterns = [
        ("risk_approval_approve", r"(?:approve|批准)\s+([0-9a-fA-F-]{8,})"),
        ("risk_approval_enable", r"(?:enable|启用)\s+([0-9a-fA-F-]{8,})"),
        ("risk_approval_revoke", r"(?:revoke|撤销)\s+([0-9a-fA-F-]{8,})"),
    ]
    for intent, pattern in action_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return intent, {"request_id": str(match.group(1))}
    return None, {}


def _ui_text(language: str, *, zh: str, en: str) -> str:
    return zh if language == "zh" else en


def _build_message_id(turn: ChatTurn, *, fallback: str) -> str:
    created = turn.created_at.isoformat() if hasattr(turn.created_at, "isoformat") else str(turn.created_at)
    role = str(turn.role or "assistant")
    if created and role:
        return f"{role}:{created}"
    return fallback


def _attach_card_ids(*, message_id: str, cards: list[PresentationCard]) -> list[PresentationCard]:
    dedup: list[PresentationCard] = []
    seen_card_ids: set[str] = set()
    seen_fingerprints: set[str] = set()
    for idx, card in enumerate(cards):
        next_id = str(card.card_id or f"{message_id}:{card.type}:{idx}")
        body = card.model_dump(mode="json")
        body.pop("card_id", None)
        fingerprint = hashlib.sha1(
            json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if next_id in seen_card_ids or fingerprint in seen_fingerprints:
            continue
        seen_card_ids.add(next_id)
        seen_fingerprints.add(fingerprint)
        dedup.append(card.model_copy(update={"card_id": next_id}, deep=True))
    return dedup


def _safe_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _format_metric_value(metric: str, value: object) -> str:
    number = _safe_float(value)
    if number is None:
        return "-"
    if metric in {"max_drawdown", "total_return", "turnover", "annual_turnover", "cost_drag"}:
        return f"{number * 100:.2f}%"
    return f"{number:.4f}"


def _metric_label(metric: str) -> str:
    mapping = {
        "sharpe": "Sharpe",
        "max_drawdown": "MDD",
        "total_return": "Return",
        "turnover": "Turnover",
        "annual_turnover": "Turnover",
        "cost_drag": "Cost Drag",
    }
    return mapping.get(metric, metric)


def _build_metrics_card(metrics: dict[str, object]) -> list[PresentationMetric]:
    preferred = ["sharpe", "max_drawdown", "total_return", "turnover", "annual_turnover", "cost_drag"]
    rows: list[PresentationMetric] = []
    seen = set()
    for key in preferred:
        if key in metrics and key not in seen:
            rows.append(PresentationMetric(name=_metric_label(key), value=_format_metric_value(key, metrics.get(key))))
            seen.add(key)
    return rows[:4]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _looks_like_user_query(title: str, query: str) -> bool:
    norm_title = _normalize_text(title)
    norm_query = _normalize_text(query)
    if not norm_title or not norm_query:
        return False
    if norm_title == norm_query:
        return True
    if len(norm_title) >= 8 and (norm_title.startswith(norm_query) or norm_query.startswith(norm_title)):
        return True
    return False


def _build_evidence_items(
    *,
    sources: list[dict[str, object]],
    query: str,
    language: str,
    max_count: int = 5,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen = set()
    for source in sources:
        title = str(source.get("title") or "").strip()
        if not title:
            continue
        if _looks_like_user_query(title, query):
            continue
        ts = _source_timestamp(source)
        snippet = _compact_text(str(source.get("snippet") or ""))
        source_name = str(source.get("source_type") or "unknown")
        uri = str(source.get("uri") or source.get("url") or "").strip()
        key = f"{title}|{ts}"
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "title": title,
                "source": source_name,
                "ts": ts,
                "snippet": snippet or _ui_text(
                    language,
                    zh="来源片段缺失，请查看原始条目。",
                    en="Snippet unavailable. Open source entry for details.",
                ),
                "uri": uri,
            }
        )
        if len(rows) >= max_count:
            break
    if rows:
        return rows
    return [
        {
            "title": _ui_text(language, zh="暂无可引用证据", en="No citable evidence yet"),
            "source": "knowledge",
            "ts": "n/a",
            "snippet": _ui_text(
                language,
                zh="当前检索结果缺少可展示来源，建议刷新证据或扩大时间范围。",
                en="Current retrieval returned no display-ready sources. Refresh evidence or widen the time range.",
            ),
            "uri": "",
        }
    ]


def _build_next_steps(
    *,
    language: str,
    intent: str,
    market: str,
    evidence_pack_id: str | None = None,
) -> list[PresentationAction]:
    if intent == "general_info_query":
        return [
            PresentationAction(
                label=_ui_text(language, zh="生成低回撤策略并回测", en="Create low-drawdown strategy"),
                action="followup_prompt",
                payload={
                    "message": _ui_text(
                        language,
                        zh=f"基于当前{market}市场，给我一个低回撤策略并回测。",
                        en=f"Build a low-drawdown strategy for {market} and run backtest.",
                    )
                },
            ),
            PresentationAction(
                label=_ui_text(language, zh="对比市场（US vs JP）", en="Compare markets US vs JP"),
                action="followup_prompt",
                payload={
                    "message": _ui_text(
                        language,
                        zh="把美股和日股放在同一框架对比，重点看回撤与波动。",
                        en="Compare US vs JP under the same framework, focusing on drawdown and volatility.",
                    )
                },
            ),
            PresentationAction(
                label=_ui_text(language, zh="刷新证据", en="Refresh evidence"),
                action="refresh_evidence",
                payload={"market": market},
            ),
        ]
    rows = [
        PresentationAction(
            label=_ui_text(language, zh="做稳健性：成本 x2", en="Run robustness: cost x2"),
            action="followup_prompt",
            payload={"message": _ui_text(language, zh="成本翻倍再跑一次并比较差异。", en="Double costs and rerun with diff.")},
        ),
        PresentationAction(
            label=_ui_text(language, zh="降低换手约束再试", en="Try lower turnover"),
            action="followup_prompt",
            payload={
                "message": _ui_text(
                    language,
                    zh="在控制回撤的前提下，进一步降低换手并重跑。",
                    en="Lower turnover under drawdown control and rerun.",
                )
            },
        ),
        PresentationAction(
            label=_ui_text(language, zh="跨市场对比（US vs JP）", en="Cross-market compare"),
            action="followup_prompt",
            payload={"message": _ui_text(language, zh="把该策略在 US 与 JP 上做可比回测。", en="Run comparable backtests on US and JP.")},
        ),
    ]
    if evidence_pack_id:
        rows.append(
            PresentationAction(
                label=_ui_text(language, zh="查看证据包", en="Inspect evidence pack"),
                action="open_evidence_pack",
                payload={"evidence_pack_id": evidence_pack_id},
            )
        )
    return rows[:4]


def _diff_narrative(*, language: str, old_report: BacktestReport, new_report: BacktestReport, cost_diff: dict[str, float]) -> str:
    old_sharpe = _safe_num(old_report.metrics, "sharpe")
    new_sharpe = _safe_num(new_report.metrics, "sharpe")
    old_mdd = _safe_num(old_report.metrics, "max_drawdown")
    new_mdd = _safe_num(new_report.metrics, "max_drawdown")
    old_ret = _safe_num(old_report.metrics, "total_return")
    new_ret = _safe_num(new_report.metrics, "total_return")
    if language == "zh":
        rows: list[str] = []
        if old_mdd is not None and new_mdd is not None:
            sign = "降低" if (new_mdd - old_mdd) < 0 else "上升"
            rows.append(f"最大回撤{sign}{abs(new_mdd - old_mdd) * 100:.2f}%。")
        if old_ret is not None and new_ret is not None:
            sign = "提升" if (new_ret - old_ret) >= 0 else "下降"
            rows.append(f"总收益{sign}{abs(new_ret - old_ret) * 100:.2f}%。")
        if old_sharpe is not None and new_sharpe is not None:
            sign = "提升" if (new_sharpe - old_sharpe) >= 0 else "下降"
            rows.append(f"Sharpe {sign}{abs(new_sharpe - old_sharpe):.3f}。")
        rows.append(f"总交易成本变化 {cost_diff.get('total_delta', 0.0):+.6f}。")
        return " ".join(rows)
    rows_en: list[str] = []
    if old_mdd is not None and new_mdd is not None:
        direction = "decreased" if (new_mdd - old_mdd) < 0 else "increased"
        rows_en.append(f"Max drawdown {direction} by {abs(new_mdd - old_mdd) * 100:.2f}%.")
    if old_ret is not None and new_ret is not None:
        direction = "improved" if (new_ret - old_ret) >= 0 else "declined"
        rows_en.append(f"Total return {direction} by {abs(new_ret - old_ret) * 100:.2f}%.")
    if old_sharpe is not None and new_sharpe is not None:
        direction = "improved" if (new_sharpe - old_sharpe) >= 0 else "declined"
        rows_en.append(f"Sharpe {direction} by {abs(new_sharpe - old_sharpe):.3f}.")
    rows_en.append(f"Total trading cost delta {cost_diff.get('total_delta', 0.0):+.6f}.")
    return " ".join(rows_en)


def _diff_table_rows(old_report: BacktestReport, new_report: BacktestReport, cost_diff: dict[str, float]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    metrics_map = [
        ("Sharpe", "sharpe"),
        ("MDD", "max_drawdown"),
        ("Return", "total_return"),
    ]
    for label, key in metrics_map:
        old_v = _safe_float(old_report.metrics.get(key))
        new_v = _safe_float(new_report.metrics.get(key))
        if old_v is None or new_v is None:
            continue
        if key in {"max_drawdown", "total_return"}:
            before = f"{old_v * 100:.2f}%"
            after = f"{new_v * 100:.2f}%"
            delta = f"{(new_v - old_v) * 100:+.2f}%"
        else:
            before = f"{old_v:.4f}"
            after = f"{new_v:.4f}"
            delta = f"{(new_v - old_v):+.4f}"
        rows.append({"metric": label, "before": before, "after": after, "delta": delta})
    rows.append(
        {
            "metric": "Cost",
            "before": f"{cost_diff.get('total_old', 0.0):.6f}",
            "after": f"{cost_diff.get('total_new', 0.0):.6f}",
            "delta": f"{cost_diff.get('total_delta', 0.0):+.6f}",
        }
    )
    return rows


def _emit_chat_delta(trace_id: str, session_id: str, text: str) -> None:
    for i in range(0, len(text), 64):
        event_bus.publish(
            event_type="chat.delta",
            trace_id=trace_id,
            session_id=session_id,
            payload={"delta": text[i : i + 64]},
        )


def _task_payload(task: TaskRecord, **extra: Any) -> dict[str, Any]:
    payload = {
        "task_id": str(task.task_id),
        "parent_task_id": str(task.parent_task_id) if task.parent_task_id else None,
        "task_type": task.task_type,
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


def _emit_task_state(event_type: str, *, trace_id: str, session_id: str, task: TaskRecord, **extra: Any) -> None:
    payload = _task_payload(task, trace_id=trace_id, session_id=session_id, **extra)
    _audit_store().append(
        AuditLogEntry(
            trace_id=UUID(trace_id),
            event_type=event_type,
            payload=payload,
            created_at=datetime.now(UTC),
        )
    )
    event_bus.publish(
        event_type=event_type,
        trace_id=trace_id,
        session_id=session_id,
        payload=payload,
    )


def _task_short_label(task_id: str, language: str) -> str:
    short = task_id.replace("-", "")[:8]
    return f"任务 #{short}" if language == "zh" else f"Task #{short}"


def _stage_progress_pct(*, stage: str, completed_variants: int, total_variants: int) -> int:
    total = max(1, total_variants)
    stage_key = stage.strip().lower()
    if stage_key in {"pipeline.start", "plan.compose"}:
        return 5
    if stage_key == "evidence.pack":
        return 12
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


def _submit_pipeline_task(
    *,
    session_id: UUID,
    message: str,
    market: str,
    response_language: str,
    trace_id: str,
    migration_preflight_confirmed: bool = False,
    auto_adjust_for_market_rules: bool = False,
    preflight_warnings: list[dict[str, str]] | None = None,
) -> TaskRecord:
    tm = _task_manager()
    locked_market = _normalize_market_value(market) or "US"
    normalized_preflight = list(preflight_warnings or [])
    parent = tm.create(
        task_type="pipeline_run",
        message="queued",
        status="queued",
        meta={
            "session_id": str(session_id),
            "trace_id": trace_id,
            "intent": "pipeline_research",
            "market": locked_market,
            "migration_preflight_confirmed": bool(migration_preflight_confirmed),
            "auto_adjust_for_market_rules": bool(auto_adjust_for_market_rules),
            "preflight_warning_count": len(normalized_preflight),
            "preflight_warnings": normalized_preflight,
        },
    )
    _emit_task_state(
        "task.created",
        trace_id=trace_id,
        session_id=str(session_id),
        task=parent,
        role="parent",
        stage="pipeline.start",
    )

    def _worker() -> None:
        child_by_variant: dict[str, UUID] = {}
        child_task_ids: list[str] = []
        completed_children = 0
        total_variants_hint = 0

        def _emit_pipeline_observable_event(event_type: str, payload: dict[str, Any]) -> None:
            variant_id = str(payload.get("variant_id") or "").strip()
            linked_task_id = str(parent.task_id)
            if variant_id and variant_id in child_by_variant:
                linked_task_id = str(child_by_variant[variant_id])
            enriched = {
                **payload,
                "task_id": linked_task_id,
                "parent_task_id": str(parent.task_id),
                "session_id": str(session_id),
                "trace_id": trace_id,
            }
            run_id = str(payload.get("run_id") or "").strip()
            if run_id:
                enriched["run_id"] = run_id
            _audit_store().append(
                AuditLogEntry(
                    trace_id=UUID(trace_id),
                    event_type=event_type,
                    payload=enriched,
                    created_at=datetime.now(UTC),
                )
            )
            event_bus.publish(
                event_type=event_type,
                trace_id=trace_id,
                session_id=str(session_id),
                payload=enriched,
            )

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
                trace_id=trace_id,
                session_id=str(session_id),
                task=parent_running,
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
                    "session_id": str(session_id),
                    "trace_id": trace_id,
                    "market": locked_market,
                    "variant_id": variant_id,
                    "variant_index": variant_index,
                    "variant_total": total_variants,
                },
            )
            child_by_variant[variant_id] = child.task_id
            child_task_ids.append(str(child.task_id))
            _emit_task_state(
                "task.created",
                trace_id=trace_id,
                session_id=str(session_id),
                task=child,
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
                now_iso = datetime.now(UTC).isoformat()
                return {
                    **(base_meta or {}),
                    "last_stage": stage or "pipeline.running",
                    "last_heartbeat_at": now_iso,
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
                    trace_id=trace_id,
                    session_id=str(session_id),
                    task=child_running,
                    role="child",
                    parent_task_id=str(parent.task_id),
                    variant_id=variant_id,
                    stage="running",
                )
                _emit_task_state(
                    "task.progress",
                    trace_id=trace_id,
                    session_id=str(session_id),
                    task=child_running,
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
                        trace_id=trace_id,
                        session_id=str(session_id),
                        task=child_running,
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
                    trace_id=trace_id,
                    session_id=str(session_id),
                    task=parent_running,
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
                    trace_id=trace_id,
                    session_id=str(session_id),
                    task=child_running,
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
                        "market": locked_market,
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
                    trace_id=trace_id,
                    session_id=str(session_id),
                    task=child_done,
                    role="child",
                    parent_task_id=str(parent.task_id),
                    variant_id=variant_id,
                    run_id=run_id,
                )
                _emit_task_state(
                    "task.done",
                    trace_id=trace_id,
                    session_id=str(session_id),
                    task=child_done,
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
                    trace_id=trace_id,
                    session_id=str(session_id),
                    task=child_error,
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
                _emit_pipeline_observable_event(event_type, payload)
                return

        try:
            _upsert_parent_running(stage="pipeline.start", completed_variants=0, total_variants=1, message_text="pipeline running")
            pipe = _pipeline_engine().run(
                PipelineRequest(
                    question=message,
                    market=locked_market,
                    max_drawdown_target=0.10,
                    run_paper_trade=True,
                    experiments=3,
                    migration_preflight_confirmed=bool(migration_preflight_confirmed),
                    auto_adjust_for_market_rules=bool(auto_adjust_for_market_rules),
                    response_language="zh" if response_language == "zh" else "en",
                ),
                trace_id=trace_id,
                progress_callback=_pipeline_progress,
            )
            run_market = str(getattr(pipe, "market", locked_market) or locked_market).strip().upper()
            _chat_store().register_run(
                session_id,
                run_id=str(pipe.run_id),
                plan_id=str(pipe.plan_id),
                report_id=str(pipe.run_id),
                dataset_version=str(pipe.dataset_version),
                market=run_market,
                metrics=dict(pipe.backtest_metrics),
            )
            best = pipe.comparison_table[0] if pipe.comparison_table else {}
            final_text = _ui_text(
                response_language,
                zh=(
                    f"任务 {_task_short_label(str(parent.task_id), response_language)} 已完成。"
                    f"最优方案 {best.get('variant_id') or 'n/a'}，Sharpe {best.get('sharpe')}，"
                    f"MDD {best.get('max_drawdown')}，Return {best.get('total_return')}。"
                ),
                en=(
                    f"{_task_short_label(str(parent.task_id), response_language)} completed. "
                    f"Best variant {best.get('variant_id') or 'n/a'}, Sharpe {best.get('sharpe')}, "
                    f"MDD {best.get('max_drawdown')}, Return {best.get('total_return')}."
                ),
            )
            _chat_store().append_turn(session_id, role="assistant", content=final_text)
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
                trace_id=trace_id,
                session_id=str(session_id),
                task=parent_done,
                role="parent",
                parent_task_id=str(parent.task_id),
                run_id=str(pipe.run_id),
                child_task_ids=child_task_ids,
            )
            event_bus.publish(
                event_type="chat.done",
                trace_id=trace_id,
                session_id=str(session_id),
                payload={
                    "message": final_text,
                    "task_id": str(parent.task_id),
                    "run_id": str(pipe.run_id),
                },
            )
        except Exception as ex:
            logger.exception("pipeline_research async task failed: session_id=%s task_id=%s", session_id, parent.task_id)
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
                trace_id=trace_id,
                session_id=str(session_id),
                task=parent_error,
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
                    trace_id=trace_id,
                    session_id=str(session_id),
                    task=child_error,
                    role="child",
                    parent_task_id=str(parent.task_id),
                )
            fail_text = _ui_text(
                response_language,
                zh=f"{_task_short_label(str(parent.task_id), response_language)} 执行失败：{str(ex)}",
                en=f"{_task_short_label(str(parent.task_id), response_language)} failed: {str(ex)}",
            )
            _chat_store().append_turn(session_id, role="assistant", content=fail_text)
            event_bus.publish(
                event_type="chat.done",
                trace_id=trace_id,
                session_id=str(session_id),
                payload={
                    "message": fail_text,
                    "task_id": str(parent.task_id),
                    "error": str(ex),
                },
            )

    Thread(target=_worker, daemon=True).start()
    return parent


def _wait_task_terminal(task_id: UUID, *, timeout_s: float = 1800.0, poll_s: float = 0.3) -> TaskRecord | None:
    tm = _task_manager()
    deadline = time.time() + max(1.0, timeout_s)
    while time.time() <= deadline:
        row = tm.get(task_id)
        if row is not None and row.status in {"done", "error", "failed", "canceled"}:
            return row
        time.sleep(max(0.05, poll_s))
    return tm.get(task_id)


def _submit_multi_market_compare_chat_task(
    *,
    session_id: UUID,
    response_language: str,
) -> TaskRecord:
    return submit_multi_market_compare_task(
        MultiMarketCompareRequest(
            markets=["US", "JP"],
            strategy_id="chat_multi_market_strategy",
            strategy_version=f"chat-mm-{uuid4().hex[:8]}",
            session_id=str(session_id),
        )
    )


def _submit_multi_market_robustness_chat_tasks(
    *,
    session_id: UUID,
) -> tuple[TaskRecord, TaskRecord]:
    us_task = submit_robustness_task(
        RobustnessRunRequest(
            market="US",
            strategy_id="chat_robustness_strategy",
            strategy_version=f"chat-rob-us-{uuid4().hex[:6]}",
            cost_multipliers=[0.5, 1.0, 2.0, 5.0],
            session_id=str(session_id),
        )
    )
    jp_task = submit_robustness_task(
        RobustnessRunRequest(
            market="JP",
            strategy_id="chat_robustness_strategy",
            strategy_version=f"chat-rob-jp-{uuid4().hex[:6]}",
            cost_multipliers=[0.5, 1.0, 2.0, 5.0],
            session_id=str(session_id),
        )
    )
    return us_task, jp_task


def _watch_multi_market_compare_completion(
    *,
    session_id: UUID,
    parent_task_id: UUID,
    response_language: str,
    trace_id: str,
) -> None:
    row = _wait_task_terminal(parent_task_id)
    if row is None:
        return
    if row.status == "done":
        result = row.result if isinstance(row.result, dict) else {}
        diff_table = result.get("diff_table") if isinstance(result.get("diff_table"), list) else []
        us_row = next(
            (item for item in diff_table if isinstance(item, dict) and str(item.get("market", "")).upper() == "US"),
            {},
        )
        jp_row = next(
            (item for item in diff_table if isinstance(item, dict) and str(item.get("market", "")).upper() == "JP"),
            {},
        )
        us_sharpe = us_row.get("sharpe")
        jp_sharpe = jp_row.get("sharpe")
        compare_id = str(result.get("compare_id") or "")
        final_text = _ui_text(
            response_language,
            zh=(
                f"{_task_short_label(str(parent_task_id), response_language)} 已完成。"
                f"US Sharpe {us_sharpe if us_sharpe is not None else '-'}，"
                f"JP Sharpe {jp_sharpe if jp_sharpe is not None else '-'}。"
            ),
            en=(
                f"{_task_short_label(str(parent_task_id), response_language)} completed. "
                f"US Sharpe {us_sharpe if us_sharpe is not None else '-'}, "
                f"JP Sharpe {jp_sharpe if jp_sharpe is not None else '-'}."
            ),
        )
        _chat_store().append_turn(session_id, role="assistant", content=final_text)
        event_bus.publish(
            event_type="chat.done",
            trace_id=trace_id,
            session_id=str(session_id),
            payload={
                "message": final_text,
                "task_id": str(parent_task_id),
                "compare_id": compare_id,
            },
        )
        return
    error_text = str(row.error or row.message or "task failed")
    fail_text = _ui_text(
        response_language,
        zh=f"{_task_short_label(str(parent_task_id), response_language)} 执行失败：{error_text}",
        en=f"{_task_short_label(str(parent_task_id), response_language)} failed: {error_text}",
    )
    _chat_store().append_turn(session_id, role="assistant", content=fail_text)
    event_bus.publish(
        event_type="chat.done",
        trace_id=trace_id,
        session_id=str(session_id),
        payload={
            "message": fail_text,
            "task_id": str(parent_task_id),
            "error": error_text,
        },
    )


def _watch_multi_market_robustness_completion(
    *,
    session_id: UUID,
    us_task_id: UUID,
    jp_task_id: UUID,
    response_language: str,
    trace_id: str,
) -> None:
    us_row = _wait_task_terminal(us_task_id)
    jp_row = _wait_task_terminal(jp_task_id)
    if us_row is None or jp_row is None:
        return
    if us_row.status == "done" and jp_row.status == "done":
        us_summary = ((us_row.result or {}).get("summary") if isinstance(us_row.result, dict) else {}) or {}
        jp_summary = ((jp_row.result or {}).get("summary") if isinstance(jp_row.result, dict) else {}) or {}
        us_mdd = us_summary.get("mdd_worst_case")
        jp_mdd = jp_summary.get("mdd_worst_case")
        final_text = _ui_text(
            response_language,
            zh=(
                "US 与 JP 稳健性比较已完成。"
                f"US 最差回撤 {float(us_mdd) * 100:.2f}% ，JP 最差回撤 {float(jp_mdd) * 100:.2f}%。"
                if isinstance(us_mdd, (int, float)) and isinstance(jp_mdd, (int, float))
                else "US 与 JP 稳健性比较已完成。"
            ),
            en=(
                "US and JP robustness comparison completed. "
                f"US worst MDD {float(us_mdd) * 100:.2f}%, JP worst MDD {float(jp_mdd) * 100:.2f}%."
                if isinstance(us_mdd, (int, float)) and isinstance(jp_mdd, (int, float))
                else "US and JP robustness comparison completed."
            ),
        )
        _chat_store().append_turn(session_id, role="assistant", content=final_text)
        event_bus.publish(
            event_type="chat.done",
            trace_id=trace_id,
            session_id=str(session_id),
            payload={
                "message": final_text,
                "us_task_id": str(us_task_id),
                "jp_task_id": str(jp_task_id),
            },
        )
        return

    errors = [
        str(us_row.error or us_row.message or "") if us_row.status != "done" else "",
        str(jp_row.error or jp_row.message or "") if jp_row.status != "done" else "",
    ]
    err = "; ".join([item for item in errors if item]).strip() or "task failed"
    fail_text = _ui_text(
        response_language,
        zh=f"多市场稳健性任务失败：{err}",
        en=f"Multi-market robustness failed: {err}",
    )
    _chat_store().append_turn(session_id, role="assistant", content=fail_text)
    event_bus.publish(
        event_type="chat.done",
        trace_id=trace_id,
        session_id=str(session_id),
        payload={
            "message": fail_text,
            "us_task_id": str(us_task_id),
            "jp_task_id": str(jp_task_id),
            "error": err,
        },
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


def _multi_market_diff_to_table_rows(diff_table: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in diff_table:
        market = str(row.get("market") or "").strip().upper()
        if market not in {"US", "JP"}:
            continue
        rows.append(
            {
                "metric": f"{market} Sharpe",
                "us": f"{_safe_float(row.get('sharpe')):.4f}" if _safe_float(row.get("sharpe")) is not None else "-",
                "jp": "-",
                "difference": f"Δ vs baseline {float(row.get('sharpe_diff_vs_baseline', 0.0)):+.4f}",
            }
        )
        rows.append(
            {
                "metric": f"{market} MDD",
                "us": f"{_safe_float(row.get('max_drawdown')) * 100:.2f}%" if _safe_float(row.get("max_drawdown")) is not None else "-",
                "jp": "-",
                "difference": f"Δ vs baseline {float(row.get('max_drawdown_diff_vs_baseline', 0.0)) * 100:+.2f}%",
            }
        )
    us_row = next((row for row in diff_table if str(row.get("market", "")).upper() == "US"), None)
    jp_row = next((row for row in diff_table if str(row.get("market", "")).upper() == "JP"), None)
    if us_row and jp_row:
        us_sharpe = _safe_float(us_row.get("sharpe"))
        jp_sharpe = _safe_float(jp_row.get("sharpe"))
        us_mdd = _safe_float(us_row.get("max_drawdown"))
        jp_mdd = _safe_float(jp_row.get("max_drawdown"))
        if us_sharpe is not None and jp_sharpe is not None:
            rows.append(
                {
                    "metric": "Sharpe",
                    "us": f"{us_sharpe:.4f}",
                    "jp": f"{jp_sharpe:.4f}",
                    "difference": f"{(us_sharpe - jp_sharpe):+.4f}",
                }
            )
        if us_mdd is not None and jp_mdd is not None:
            rows.append(
                {
                    "metric": "MDD",
                    "us": f"{us_mdd * 100:.2f}%",
                    "jp": f"{jp_mdd * 100:.2f}%",
                    "difference": f"{(us_mdd - jp_mdd) * 100:+.2f}%",
                }
            )
    return rows


def _robustness_compare_rows(*, us_report: Any, jp_report: Any) -> list[dict[str, str]]:
    us_summary = getattr(us_report, "summary", None)
    jp_summary = getattr(jp_report, "summary", None)
    if us_summary is None or jp_summary is None:
        return []
    rows = [
        {
            "metric": "Sharpe mean",
            "us": f"{float(getattr(us_summary, 'sharpe_mean', 0.0)):.4f}",
            "jp": f"{float(getattr(jp_summary, 'sharpe_mean', 0.0)):.4f}",
            "difference": f"{float(getattr(us_summary, 'sharpe_mean', 0.0)) - float(getattr(jp_summary, 'sharpe_mean', 0.0)):+.4f}",
        },
        {
            "metric": "MDD worst",
            "us": f"{float(getattr(us_summary, 'mdd_worst_case', 0.0)) * 100:.2f}%",
            "jp": f"{float(getattr(jp_summary, 'mdd_worst_case', 0.0)) * 100:.2f}%",
            "difference": (
                f"{(float(getattr(us_summary, 'mdd_worst_case', 0.0)) - float(getattr(jp_summary, 'mdd_worst_case', 0.0))) * 100:+.2f}%"
            ),
        },
        {
            "metric": "Variants",
            "us": str(int(getattr(us_summary, "variant_count", 0))),
            "jp": str(int(getattr(jp_summary, "variant_count", 0))),
            "difference": str(int(getattr(us_summary, "variant_count", 0)) - int(getattr(jp_summary, "variant_count", 0))),
        },
    ]
    return rows


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


def _compact_text(text: str, limit: int = 160) -> str:
    cleaned = " ".join(text.split()).strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit - 1].rstrip()}..."


def _source_timestamp(source: dict[str, object]) -> str:
    raw = source.get("published_at") or source.get("timestamp")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return "n/a"


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
        r"(?:回撤|drawdown).{0,30}?(?:改到|降到|到|目标|target(?:\s*to)?|set\s*to|to)\s*(\d+(?:\.\d+)?)\s*%",
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
    return "no_match", {}

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
        market=str(getattr(new_report, "market", "") or ""),
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
    session_state = _chat_store().get_last_memory(session.session_id)
    resolved_market, market_source = resolve_market(
        message=request.message,
        session_state=session_state,
        explicit_request=None,
    )

    trace_id = str(uuid4())
    response_language = _detect_user_language(request.message)
    event_bus.publish(
        event_type="chat.request.received",
        trace_id=trace_id,
        session_id=str(session.session_id),
        payload={"stage": "chat.request.received"},
    )

    modify_intent, ops = _detect_modify_intent(request.message)
    compare_intent = _detect_compare_intent(request.message)
    risk_intent, risk_intent_payload = _detect_risk_control_intent(request.message)
    market_compare_triggered, market_compare_targets, market_compare_rule_hits = _detect_market_compare_intent(request.message)
    task_intent, task_intent_rule_hits = _detect_multi_market_task_intent(request.message)
    pipeline_triggered, pipeline_rule_hits = _detect_pipeline_research_intent(request.message)
    general_triggered, general_rule_hits = _detect_general_info_intent(request.message)
    intent = "pipeline_research" if pipeline_triggered else "general_info_query"
    if modify_intent == "modify_last_run":
        intent = "modify_last_run"
    elif risk_intent is not None:
        intent = risk_intent
    elif task_intent is not None:
        intent = task_intent
    elif market_compare_triggered and not pipeline_triggered and intent != "modify_last_run":
        intent = "market_compare"
    elif general_triggered and not pipeline_triggered and intent != "modify_last_run":
        intent = "market_compare" if market_compare_triggered else "general_info_query"

    intent_trace = {
        "pipeline_rule_hits": pipeline_rule_hits,
        "general_rule_hits": general_rule_hits,
        "pipeline_triggered": pipeline_triggered,
        "general_triggered": general_triggered,
        "compare_intent": compare_intent,
        "task_intent": task_intent,
        "task_intent_rule_hits": task_intent_rule_hits,
        "market_compare_triggered": market_compare_triggered,
        "market_compare_targets": market_compare_targets,
        "market_compare_rule_hits": market_compare_rule_hits,
        "modify_intent": modify_intent,
        "risk_intent": risk_intent,
        "risk_intent_payload": risk_intent_payload,
    }

    preflight_action = _parse_preflight_action(request.message)
    preflight_action_name = preflight_action[0] if preflight_action else ""
    preflight_action_token = preflight_action[1] if preflight_action else ""
    preflight_context = _get_preflight_context(preflight_action_token) if preflight_action else None
    if preflight_action:
        intent = "pipeline_preflight_gate"
    if preflight_action:
        intent_trace = {
            **intent_trace,
            "preflight_action": preflight_action_name,
            "preflight_action_token": preflight_action_token,
            "preflight_context_found": bool(preflight_context),
        }

    cards: list[PresentationCard] = []
    debug_payload: dict[str, Any] = {}
    evidence_pack_id = "iterative-memory-no-evidence"
    user_answer = ""
    compared: tuple[str, str, BacktestReport, BacktestReport] | None = None
    if compare_intent and not market_compare_triggered:
        compared = _run_session_compare(session.session_id, request.message)
        if compared is not None:
            intent = "session_compare"
        else:
            if market_compare_triggered:
                intent = "market_compare"
            else:
                intent = "pipeline_research" if pipeline_triggered else "general_info_query"

    if intent == "pipeline_preflight_gate":
        ctx = preflight_context or {}
        ctx_session = str(ctx.get("session_id") or "").strip()
        if (not ctx) or (ctx_session and ctx_session != str(session.session_id)):
            user_answer = _ui_text(
                response_language,
                zh="迁移预检上下文已过期。请重新发起回测请求。",
                en="Migration preflight context expired. Please submit the pipeline request again.",
            )
            cards = [
                PresentationCard(
                    type="summary",
                    title=_ui_text(response_language, zh="预检上下文过期", en="Preflight Context Expired"),
                    content=user_answer,
                )
            ]
            debug_payload = {
                "intent": "pipeline_preflight_gate",
                "response_language": response_language,
                "intent_trace": intent_trace,
                "error": "preflight_context_missing",
            }
        else:
            ctx_message = str(ctx.get("message") or "")
            ctx_market = _normalize_market_value(str(ctx.get("market") or "")) or resolved_market
            ctx_language = str(ctx.get("response_language") or response_language)
            warnings_payload = [
                row for row in (ctx.get("warnings") or []) if isinstance(row, dict)
            ]
            accepted_task_id = ""
            if preflight_action_name == "cancel":
                _drop_preflight_context(preflight_action_token)
                evidence_pack_id = "pipeline_preflight:cancelled"
                user_answer = _ui_text(
                    ctx_language,
                    zh="已取消本次迁移执行。你可以调整约束后再试。",
                    en="Migration execution cancelled. You can adjust constraints and retry.",
                )
                cards = [
                    PresentationCard(
                        type="summary",
                        title=_ui_text(ctx_language, zh="已取消", en="Cancelled"),
                        content=user_answer,
                    )
                ]
            elif preflight_action_name == "proceed":
                _mark_preflight_confirm_ready(preflight_action_token)
                evidence_pack_id = f"pipeline_preflight:confirm:{preflight_action_token}"
                _audit_store().append(
                    AuditLogEntry(
                        trace_id=UUID(trace_id),
                        event_type="chat.pipeline.preflight.action",
                        payload={
                            "session_id": str(session.session_id),
                            "task_id": "",
                            "action": "proceed_prompt",
                            "market": ctx_market,
                            "token": preflight_action_token,
                            "warnings": warnings_payload,
                        },
                        created_at=datetime.now(UTC),
                    )
                )
                user_answer = _ui_text(
                    ctx_language,
                    zh="该迁移包含阻断级风险。请二次确认后继续执行。",
                    en="This migration contains blocking risk. Confirm again to proceed.",
                )
                cards = [
                    PresentationCard(
                        type="summary",
                        title=_ui_text(ctx_language, zh="需要二次确认", en="Second Confirmation Required"),
                        content=user_answer,
                    ),
                    PresentationCard(
                        type="next_steps",
                        title=_ui_text(ctx_language, zh="下一步", en="Next Steps"),
                        actions=[
                            PresentationAction(
                                label=_ui_text(ctx_language, zh="确认继续执行", en="Confirm Proceed"),
                                action="followup_prompt",
                                payload={"message": f"__preflight__:confirm:{preflight_action_token}"},
                            ),
                            PresentationAction(
                                label=_ui_text(ctx_language, zh="自动调整并运行", en="Adjust Automatically"),
                                action="followup_prompt",
                                payload={"message": f"__preflight__:adjust:{preflight_action_token}"},
                            ),
                            PresentationAction(
                                label=_ui_text(ctx_language, zh="取消", en="Cancel"),
                                action="followup_prompt",
                                payload={"message": f"__preflight__:cancel:{preflight_action_token}"},
                            ),
                        ],
                    ),
                ]
            elif preflight_action_name in {"adjust", "confirm"}:
                confirm_ready = bool(ctx.get("confirm_ready"))
                if preflight_action_name == "confirm" and (not confirm_ready):
                    evidence_pack_id = f"pipeline_preflight:confirm_required:{preflight_action_token}"
                    user_answer = _ui_text(
                        ctx_language,
                        zh="请先点击“继续执行”再进行最终确认。",
                        en="Please choose proceed first, then confirm.",
                    )
                    cards = [
                        PresentationCard(
                            type="summary",
                            title=_ui_text(ctx_language, zh="确认顺序提示", en="Confirmation Order"),
                            content=user_answer,
                        )
                    ]
                else:
                    _drop_preflight_context(preflight_action_token)
                    _chat_store().set_last_context(session.session_id, last_market=ctx_market)
                    accepted = _submit_pipeline_task(
                        session_id=session.session_id,
                        message=ctx_message,
                        market=ctx_market,
                        response_language=ctx_language,
                        trace_id=trace_id,
                        migration_preflight_confirmed=preflight_action_name == "confirm",
                        auto_adjust_for_market_rules=preflight_action_name == "adjust",
                        preflight_warnings=[dict(row) for row in warnings_payload],
                    )
                    task_id = str(accepted.task_id)
                    accepted_task_id = task_id
                    evidence_pack_id = f"pipeline_task:{task_id}"
                    task_label = _task_short_label(task_id, ctx_language)
                    action_text = (
                        _ui_text(ctx_language, zh="已启用自动规则调整。", en="Auto-adjustment enabled.")
                        if preflight_action_name == "adjust"
                        else _ui_text(ctx_language, zh="已记录风险确认。", en="Risk confirmation recorded.")
                    )
                    user_answer = _ui_text(
                        ctx_language,
                        zh=f"{task_label} 已提交并开始执行。{action_text}",
                        en=f"{task_label} submitted and running. {action_text}",
                    )
                    cards = [
                        PresentationCard(
                            type="summary",
                            title=_ui_text(ctx_language, zh="执行中", en="Running"),
                            content=user_answer,
                            subtitle=f"task_id={task_id}",
                        ),
                        PresentationCard(
                            type="next_steps",
                            title=_ui_text(ctx_language, zh="你可以先查看", en="You can check"),
                            actions=[
                                PresentationAction(
                                    label=_ui_text(ctx_language, zh="打开任务页", en="Open Tasks"),
                                    action="open_task",
                                    payload={"parent_task_id": task_id},
                                )
                            ],
                        ),
                    ]
                    _audit_store().append(
                        AuditLogEntry(
                            trace_id=UUID(trace_id),
                            event_type="chat.pipeline.preflight.action",
                            payload={
                                "session_id": str(session.session_id),
                                "task_id": task_id,
                                "action": preflight_action_name,
                                "market": ctx_market,
                                "warnings": warnings_payload,
                            },
                            created_at=datetime.now(UTC),
                        )
                    )
            else:
                user_answer = _ui_text(
                    response_language,
                    zh="预检动作无效，请重新发起请求。",
                    en="Invalid preflight action. Please submit request again.",
                )
                cards = [
                    PresentationCard(
                        type="summary",
                        title=_ui_text(response_language, zh="动作无效", en="Invalid Action"),
                        content=user_answer,
                    )
                ]
            debug_payload = {
                "intent": "pipeline_preflight_gate",
                "response_language": ctx_language if ctx else response_language,
                "intent_trace": intent_trace,
                "preflight_action": preflight_action_name,
                "preflight_token": preflight_action_token,
                "accepted": bool(accepted_task_id),
                "parent_task_id": accepted_task_id,
                "task_id": accepted_task_id,
                "warnings": warnings_payload if ctx else [],
                "session_memory": _chat_store().get_last_memory(session.session_id),
            }

    elif intent.startswith("risk_"):
        trading = _trading_service()
        action_result: dict[str, Any] = {"intent": intent}
        try:
            if intent == "risk_request_unlock":
                req = trading.request_unlock(
                    target="live_trading",
                    actor="user",
                    context={
                        "session_id": str(session.session_id),
                        "use_case": "chat_request_unlock",
                        "message": request.message[:200],
                    },
                )
                user_answer = _ui_text(
                    response_language,
                    zh=f"已提交解锁申请：{req.request_id}。当前状态 {req.status}。",
                    en=f"Unlock request submitted: {req.request_id}. Current status={req.status}.",
                )
                action_result["request_id"] = str(req.request_id)
                action_result["status"] = str(req.status)
            elif intent == "risk_paper_start":
                status = trading.set_paper_running(True, actor="user")
                user_answer = _ui_text(
                    response_language,
                    zh="纸交易已开启。",
                    en="Paper trading started.",
                )
                action_result["status"] = status.model_dump(mode="json")
            elif intent == "risk_paper_stop":
                status = trading.set_paper_running(False, actor="user")
                user_answer = _ui_text(
                    response_language,
                    zh="纸交易已停止。",
                    en="Paper trading stopped.",
                )
                action_result["status"] = status.model_dump(mode="json")
            elif intent == "risk_kill_switch_on":
                status = trading.set_kill_switch(True)
                user_answer = _ui_text(
                    response_language,
                    zh="Kill switch 已打开。",
                    en="Kill switch enabled.",
                )
                action_result["status"] = status.model_dump(mode="json")
            elif intent == "risk_kill_switch_off":
                status = trading.set_kill_switch(False)
                user_answer = _ui_text(
                    response_language,
                    zh="Kill switch 已关闭。",
                    en="Kill switch disabled.",
                )
                action_result["status"] = status.model_dump(mode="json")
            elif intent == "risk_approval_approve":
                request_id = str(risk_intent_payload.get("request_id") or "").strip()
                req = trading.approve_request(request_id=request_id, actor="admin")
                user_answer = _ui_text(
                    response_language,
                    zh=f"审批 {request_id} 已批准。",
                    en=f"Approval {request_id} marked approved.",
                )
                action_result["request_id"] = request_id
                action_result["status"] = req.model_dump(mode="json")
            elif intent == "risk_approval_enable":
                request_id = str(risk_intent_payload.get("request_id") or "").strip()
                req = trading.enable_request(request_id=request_id, actor="admin")
                user_answer = _ui_text(
                    response_language,
                    zh=f"审批 {request_id} 已启用。",
                    en=f"Approval {request_id} marked enabled.",
                )
                action_result["request_id"] = request_id
                action_result["status"] = req.model_dump(mode="json")
            elif intent == "risk_approval_revoke":
                request_id = str(risk_intent_payload.get("request_id") or "").strip()
                req = trading.revoke_request(request_id=request_id, actor="admin")
                user_answer = _ui_text(
                    response_language,
                    zh=f"审批 {request_id} 已撤销。",
                    en=f"Approval {request_id} revoked.",
                )
                action_result["request_id"] = request_id
                action_result["status"] = req.model_dump(mode="json")
            else:
                user_answer = _ui_text(
                    response_language,
                    zh="未识别的风控动作。",
                    en="Unknown risk-control action.",
                )
            cards = [
                PresentationCard(
                    type="summary",
                    title=_ui_text(response_language, zh="风控更新", en="Risk Control Updated"),
                    content=user_answer,
                )
            ]
        except Exception as ex:
            user_answer = _ui_text(
                response_language,
                zh=f"风控动作失败：{str(ex)}",
                en=f"Risk-control action failed: {str(ex)}",
            )
            cards = [
                PresentationCard(
                    type="summary",
                    title=_ui_text(response_language, zh="操作失败", en="Action Failed"),
                    content=user_answer,
                )
            ]
            action_result["error"] = str(ex)
        debug_payload = {
            "intent": intent,
            "response_language": response_language,
            "intent_trace": intent_trace,
            "risk_action": action_result,
            "session_memory": _chat_store().get_last_memory(session.session_id),
        }

    elif intent == "session_compare" and compared is not None:
        current_run_id, baseline_run_id, current_report, baseline_report = compared
        metrics_diff = _metrics_diff(baseline_report.metrics, current_report.metrics)
        cost_diff = _cost_diff(baseline_report, current_report)
        risk_diff = _risk_action_diff(baseline_report, current_report)
        attribution_diff = _attribution_diff(baseline_report, current_report)
        narrative = _diff_narrative(
            language=response_language,
            old_report=baseline_report,
            new_report=current_report,
            cost_diff=cost_diff,
        )
        runs = _chat_store().get_recent_runs(session.session_id, limit=20)
        current_rank = next((i + 1 for i, row in enumerate(runs) if str(row.get("run_id")) == current_run_id), None)
        baseline_rank = next((i + 1 for i, row in enumerate(runs) if str(row.get("run_id")) == baseline_run_id), None)
        run_label = (
            _ui_text(
                response_language,
                zh=f"Run #{current_rank or '?'}（基于 Run #{baseline_rank or '?'}）",
                en=f"Run #{current_rank or '?'} (based on Run #{baseline_rank or '?'})",
            )
        )
        user_answer = _ui_text(
            response_language,
            zh=f"{run_label} 对比已完成。{narrative}",
            en=f"{run_label} comparison completed. {narrative}",
        )
        cards = [
            PresentationCard(
                type="summary",
                title=_ui_text(response_language, zh="结论", en="Summary"),
                content=user_answer,
                subtitle=_ui_text(
                    response_language,
                    zh="系统已自动关联当前会话最近两次运行进行对比。",
                    en="Compared the two most recent runs from current session memory.",
                ),
            ),
            PresentationCard(
                type="metrics",
                title=_ui_text(response_language, zh="关键指标", en="Key Metrics"),
                metrics=_build_metrics_card(current_report.metrics),
            ),
            PresentationCard(
                type="diff",
                title=_ui_text(response_language, zh="变化对比", en="Diff"),
                content=narrative,
                table=_diff_table_rows(baseline_report, current_report, cost_diff),
            ),
            PresentationCard(
                type="next_steps",
                title=_ui_text(response_language, zh="下一步建议", en="Next Steps"),
                    actions=_build_next_steps(
                        language=response_language,
                        intent="session_compare",
                        market=resolved_market,
                    ),
                ),
            ]
        debug_payload = {
            "intent": "session_compare",
            "response_language": response_language,
            "intent_trace": intent_trace,
            "run_compare": {
                "current_run_id": current_run_id,
                "baseline_run_id": baseline_run_id,
                "metrics_diff": metrics_diff,
                "cost_diff": cost_diff,
                "risk_action_diff": risk_diff,
                "attribution_diff": attribution_diff,
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

    elif intent == "modify_last_run":
        iterative = _run_iterative_mutation(session.session_id, request.message)
        if iterative is not None:
            base_meta, mutated_request, old_report, new_report = iterative
            diffs = _metrics_diff(old_report.metrics, new_report.metrics)
            cost_diff = _cost_diff(old_report, new_report)
            risk_diff = _risk_action_diff(old_report, new_report)
            narrative = _diff_narrative(
                language=response_language,
                old_report=old_report,
                new_report=new_report,
                cost_diff=cost_diff,
            )
            runs = _chat_store().get_recent_runs(session.session_id, limit=20)
            new_rank = next((i + 1 for i, row in enumerate(runs) if str(row.get("run_id")) == str(new_report.run_id)), None)
            old_rank = next((i + 1 for i, row in enumerate(runs) if str(row.get("run_id")) == str(base_meta["last_run_id"])), None)
            run_label = _ui_text(
                response_language,
                zh=f"Run #{new_rank or '?'}（基于 Run #{old_rank or '?'}）",
                en=f"Run #{new_rank or '?'} (based on Run #{old_rank or '?'})",
            )
            user_answer = _ui_text(
                response_language,
                zh=f"{run_label} 已完成参数迭代。{narrative}",
                en=f"{run_label} iterative rerun completed. {narrative}",
            )
            cards = [
                PresentationCard(
                    type="summary",
                    title=_ui_text(response_language, zh="结论", en="Summary"),
                    content=user_answer,
                    subtitle=_ui_text(
                        response_language,
                        zh="系统自动复用上次实验设置，仅修改你指定的参数。",
                        en="Reused last run configuration and mutated only requested parameters.",
                    ),
                ),
                PresentationCard(
                    type="metrics",
                    title=_ui_text(response_language, zh="关键指标", en="Key Metrics"),
                    metrics=_build_metrics_card(new_report.metrics),
                ),
                PresentationCard(
                    type="diff",
                    title=_ui_text(response_language, zh="变化对比", en="Diff"),
                    content=narrative,
                    table=_diff_table_rows(old_report, new_report, cost_diff),
                ),
                PresentationCard(
                    type="next_steps",
                    title=_ui_text(response_language, zh="下一步建议", en="Next Steps"),
                    actions=_build_next_steps(
                        language=response_language,
                        intent="modify_last_run",
                        market=resolved_market,
                    ),
                ),
            ]
            debug_payload = {
                "intent": intent,
                "response_language": response_language,
                "intent_trace": intent_trace,
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
            intent = "pipeline_research"

    if intent == "multi_market_compare_report":
        try:
            parent_task = _submit_multi_market_compare_chat_task(
                session_id=session.session_id,
                response_language=response_language,
            )
            parent_task_id = str(parent_task.task_id)
            task_label = _task_short_label(parent_task_id, response_language)
            evidence_pack_id = f"multi-market-task:{parent_task_id}"
            user_answer = _ui_text(
                response_language,
                zh=f"{task_label} 已提交并开始执行。你可以去 Tasks 页面查看进度，结果完成后会自动同步。",
                en=f"{task_label} submitted and running. Track progress in Tasks; results will sync automatically.",
            )
            next_actions = [
                PresentationAction(
                    label=_ui_text(response_language, zh="打开任务页", en="Open Tasks"),
                    action="open_task",
                    payload={"parent_task_id": parent_task_id},
                ),
                PresentationAction(
                    label=_ui_text(response_language, zh="做稳健性比较", en="Run robustness compare"),
                    action="followup_prompt",
                    payload={
                        "message": _ui_text(
                            response_language,
                            zh="在更高波动假设下，对 US 与 JP 的策略约束做稳健性比较。",
                            en="Run robustness comparison for US and JP under higher volatility.",
                        )
                    },
                ),
            ]
            cards = [
                PresentationCard(
                    type="summary",
                    title=_ui_text(response_language, zh="执行中", en="Running"),
                    content=user_answer,
                    subtitle=f"task_id={parent_task_id}",
                ),
                PresentationCard(
                    type="next_steps",
                    title=_ui_text(response_language, zh="下一步建议", en="Next Steps"),
                    actions=next_actions,
                ),
            ]
            debug_payload = {
                "intent": "multi_market_compare_report",
                "response_language": response_language,
                "intent_trace": intent_trace,
                "accepted": True,
                "parent_task_id": parent_task_id,
                "task_id": parent_task_id,
                "session_memory": _chat_store().get_last_memory(session.session_id),
            }
            Thread(
                target=_watch_multi_market_compare_completion,
                kwargs={
                    "session_id": session.session_id,
                    "parent_task_id": UUID(parent_task_id),
                    "response_language": response_language,
                    "trace_id": trace_id,
                },
                daemon=True,
            ).start()
        except Exception as ex:
            logger.exception("chat multi_market_compare_report failed")
            user_answer = _ui_text(
                response_language,
                zh="多市场可比回测任务失败，已记录错误信息。请在 Tasks 页面查看详情并重试。",
                en="Multi-market comparable backtest failed. Error was recorded; check Tasks and retry.",
            )
            cards = [
                PresentationCard(
                    type="summary",
                    title=_ui_text(response_language, zh="任务失败", en="Task Failed"),
                    content=user_answer,
                    subtitle=str(ex),
                ),
                PresentationCard(
                    type="next_steps",
                    title=_ui_text(response_language, zh="建议操作", en="Suggested Actions"),
                    actions=[
                        PresentationAction(
                            label=_ui_text(response_language, zh="打开任务页", en="Open Tasks"),
                            action="open_task",
                            payload={},
                        )
                    ],
                ),
            ]
            debug_payload = {
                "intent": "multi_market_compare_report",
                "response_language": response_language,
                "intent_trace": intent_trace,
                "error": str(ex),
                "session_memory": _chat_store().get_last_memory(session.session_id),
            }
    elif intent == "multi_market_robustness":
        try:
            us_task, jp_task = _submit_multi_market_robustness_chat_tasks(session_id=session.session_id)
            parent_task_ids = [str(us_task.task_id), str(jp_task.task_id)]
            evidence_pack_id = f"robustness-task:{parent_task_ids[0]}|{parent_task_ids[1]}"
            us_label = _task_short_label(parent_task_ids[0], response_language)
            jp_label = _task_short_label(parent_task_ids[1], response_language)
            user_answer = _ui_text(
                response_language,
                zh=(
                    f"{us_label} 与 {jp_label} 已提交并开始执行。"
                    "你可以去 Tasks 页面查看进度，结果完成后会自动同步。"
                ),
                en=(
                    f"{us_label} and {jp_label} submitted and running. "
                    "Track progress in Tasks; results will sync automatically."
                ),
            )
            cards = [
                PresentationCard(
                    type="summary",
                    title=_ui_text(response_language, zh="执行中", en="Running"),
                    content=user_answer,
                    subtitle=f"task_id={parent_task_ids[0]}, task_id={parent_task_ids[1]}",
                ),
                PresentationCard(
                    type="next_steps",
                    title=_ui_text(response_language, zh="下一步建议", en="Next Steps"),
                    actions=[
                        PresentationAction(
                            label=_ui_text(response_language, zh="打开任务页", en="Open Tasks"),
                            action="open_task",
                            payload={"parent_task_id": parent_task_ids[0] if parent_task_ids[0] else ""},
                        ),
                        PresentationAction(
                            label=_ui_text(response_language, zh="运行多市场可比回测", en="Run multi-market compare"),
                            action="followup_prompt",
                            payload={
                                "message": _ui_text(
                                    response_language,
                                    zh="运行 US vs JP 多市场可比回测报告，重点看回撤和波动。",
                                    en="Run a comparable US vs JP multi-market report focusing on drawdown and volatility.",
                                )
                            },
                        ),
                    ],
                ),
            ]
            debug_payload = {
                "intent": "multi_market_robustness",
                "response_language": response_language,
                "intent_trace": intent_trace,
                "accepted": True,
                "us_parent_task_id": parent_task_ids[0],
                "jp_parent_task_id": parent_task_ids[1],
                "session_memory": _chat_store().get_last_memory(session.session_id),
            }
            Thread(
                target=_watch_multi_market_robustness_completion,
                kwargs={
                    "session_id": session.session_id,
                    "us_task_id": UUID(parent_task_ids[0]),
                    "jp_task_id": UUID(parent_task_ids[1]),
                    "response_language": response_language,
                    "trace_id": trace_id,
                },
                daemon=True,
            ).start()
        except Exception as ex:
            logger.exception("chat multi_market_robustness failed")
            user_answer = _ui_text(
                response_language,
                zh="多市场稳健性任务失败，已记录错误信息。请在 Tasks 页面查看详情并重试。",
                en="Multi-market robustness task failed. Error was recorded; check Tasks and retry.",
            )
            cards = [
                PresentationCard(
                    type="summary",
                    title=_ui_text(response_language, zh="任务失败", en="Task Failed"),
                    content=user_answer,
                    subtitle=str(ex),
                ),
                PresentationCard(
                    type="next_steps",
                    title=_ui_text(response_language, zh="建议操作", en="Suggested Actions"),
                    actions=[
                        PresentationAction(
                            label=_ui_text(response_language, zh="打开任务页", en="Open Tasks"),
                            action="open_task",
                            payload={},
                        )
                    ],
                ),
            ]
            debug_payload = {
                "intent": "multi_market_robustness",
                "response_language": response_language,
                "intent_trace": intent_trace,
                "error": str(ex),
                "session_memory": _chat_store().get_last_memory(session.session_id),
            }
    elif intent == "market_compare":
        us_query = f"{request.message} ; focus on US equities drawdown volatility liquidity policy"
        jp_query = f"{request.message} ; focus on JP equities drawdown volatility liquidity policy"
        us_pack: EvidencePack = _knowledge().retrieve(query=us_query, top_k=6)
        jp_pack: EvidencePack = _knowledge().retrieve(query=jp_query, top_k=6)
        market_compare = _market_compare_builder().build(
            question=request.message,
            response_language=response_language,
            us_pack=us_pack,
            jp_pack=jp_pack,
        )
        evidence_pack_id = f"{us_pack.evidence_pack_id}|{jp_pack.evidence_pack_id}"
        user_answer = market_compare.summary
        comparison_actions = [
            PresentationAction(
                label=_ui_text(response_language, zh="运行多市场对比报告", en="Run multi-market compare report"),
                action="followup_prompt",
                payload={
                    "message": _ui_text(
                        response_language,
                        zh="运行 US vs JP 多市场可比回测报告，重点看回撤和波动。",
                        en="Run a comparable US vs JP multi-market report focusing on drawdown and volatility.",
                    )
                },
            ),
            PresentationAction(
                label=_ui_text(response_language, zh="扩大证据时间窗", en="Expand evidence window"),
                action="followup_prompt",
                payload={
                    "message": _ui_text(
                        response_language,
                        zh="把证据检索窗口扩展到最近90天，并重新比较 US 与 JP。",
                        en="Expand evidence lookback to 90 days and rerun US vs JP comparison.",
                    )
                },
            ),
            PresentationAction(
                label=_ui_text(response_language, zh="高波动下做稳健性", en="Run robustness under higher vol"),
                action="followup_prompt",
                payload={
                    "message": _ui_text(
                        response_language,
                        zh="在更高波动假设下，对 US 与 JP 的策略约束做稳健性比较。",
                        en="Run robustness comparison for US and JP under higher-volatility assumptions.",
                    )
                },
            ),
        ]
        cards = [
            PresentationCard(
                type="summary",
                title=_ui_text(response_language, zh="对比结论", en="Comparison Summary"),
                content=market_compare.summary,
            ),
            PresentationCard(
                type="comparison_table",
                title=_ui_text(response_language, zh="同框架对比表", en="Comparison Table"),
                table=market_compare.table,
            ),
            PresentationCard(
                type="key_differences",
                title=_ui_text(response_language, zh="关键差异", en="Key Differences"),
                items=[row.model_dump(mode="json") for row in market_compare.key_differences],
            ),
            PresentationCard(
                type="evidence",
                title=_ui_text(response_language, zh="分市场证据", en="Evidence by Market"),
                items=[
                    {
                        "market": "US",
                        "evidence": [row.model_dump(mode="json") for row in market_compare.evidence_by_market.get("US", [])],
                    },
                    {
                        "market": "JP",
                        "evidence": [row.model_dump(mode="json") for row in market_compare.evidence_by_market.get("JP", [])],
                    },
                ],
            ),
            PresentationCard(
                type="confidence",
                title=_ui_text(response_language, zh="置信度", en="Confidence"),
                content=f"{market_compare.confidence:.2f}",
                subtitle=market_compare.confidence_reason,
            ),
            PresentationCard(
                type="next_steps",
                title=_ui_text(response_language, zh="下一步建议", en="Next Steps"),
                actions=comparison_actions,
            ),
        ]
        _audit_store().append(
            AuditLogEntry(
                trace_id=UUID(trace_id),
                event_type="chat.market_compare",
                payload={
                    "session_id": str(session.session_id),
                    "left_market": "US",
                    "right_market": "JP",
                    "us_pack_id": str(us_pack.evidence_pack_id),
                    "jp_pack_id": str(jp_pack.evidence_pack_id),
                    "confidence": market_compare.confidence,
                    "citation_count": len(market_compare.citations),
                },
                created_at=datetime.now(UTC),
            )
        )
        debug_payload = {
            "intent": "market_compare",
            "response_language": response_language,
            "intent_trace": intent_trace,
            "left_market": "US",
            "right_market": "JP",
            "us_evidence_pack_id": str(us_pack.evidence_pack_id),
            "jp_evidence_pack_id": str(jp_pack.evidence_pack_id),
            "market_compare": market_compare.model_dump(mode="json"),
            "citations": market_compare.citations,
            "llm_mode": "market_compare_heuristic",
            "session_memory": _chat_store().get_last_memory(session.session_id),
        }
    elif intent == "general_info_query":
        market = resolved_market
        _chat_store().set_last_context(session.session_id, last_market=market)
        evidence_pack: EvidencePack = _knowledge().retrieve(query=request.message, top_k=6)
        evidence_pack_id = str(evidence_pack.evidence_pack_id)
        evidence_sources = [source.model_dump(mode="json") for source in evidence_pack.sources]
        answer_result = _general_info_answerer().answer(
            question=request.message,
            market=market,
            response_language=response_language,
            evidence_pack=evidence_pack,
        )
        answer_payload = answer_result.answer
        citations = [row.model_dump(mode="json") for row in answer_payload.citations]
        evidence_refs = list(dict.fromkeys([row.get("source_id", "") for row in citations if row.get("source_id")]))
        summary_lines = [row if row.startswith("-") else f"- {row}" for row in answer_payload.summary]
        drivers_lines = [row if row.startswith("-") else f"- {row}" for row in answer_payload.drivers]
        risks_lines = [row if row.startswith("-") else f"- {row}" for row in answer_payload.risks]
        watch_lines = [row if row.startswith("-") else f"- {row}" for row in answer_payload.what_to_watch]
        summary_body = "\n".join(summary_lines[:6])
        drivers_body = "\n".join(drivers_lines[:4])
        risks_body = "\n".join(risks_lines[:4])
        watch_body = "\n".join(watch_lines[:4])
        user_answer = (
            f"{market} 市场综述：\n{summary_body}"
            if response_language == "zh"
            else f"{market} market overview:\n{summary_body}"
        )
        evidence_items = [
            {
                "title": str(row.get("title") or ""),
                "source": str(row.get("source_type") or row.get("source") or "unknown"),
                "ts": str(row.get("timestamp") or "n/a"),
                "snippet": str(row.get("snippet") or ""),
                "source_id": str(row.get("source_id") or ""),
                "uri": str(row.get("uri") or ""),
            }
            for row in citations[:3]
        ]
        if not evidence_items:
            evidence_items = _build_evidence_items(
                sources=evidence_sources,
                query=request.message,
                language=response_language,
                max_count=3,
            )
        cards = [
            PresentationCard(
                type="summary",
                title=_ui_text(response_language, zh="结论", en="Summary"),
                content=summary_body,
                subtitle=_ui_text(
                    response_language,
                    zh=f"置信度 {answer_payload.confidence:.2f}",
                    en=f"Confidence {answer_payload.confidence:.2f}",
                ),
            ),
            PresentationCard(
                type="drivers",
                title=_ui_text(response_language, zh="驱动因素", en="Drivers"),
                content=drivers_body,
            ),
            PresentationCard(
                type="evidence",
                title=_ui_text(response_language, zh="关键证据", en="Key Evidence"),
                items=evidence_items,
            ),
            PresentationCard(
                type="risks",
                title=_ui_text(response_language, zh="风险提示", en="Risks"),
                content=risks_body,
            ),
            PresentationCard(
                type="watch",
                title=_ui_text(response_language, zh="关注点", en="What to Watch"),
                content=watch_body,
            ),
            PresentationCard(
                type="next_steps",
                title=_ui_text(response_language, zh="下一步建议", en="Next Steps"),
                actions=_build_next_steps(
                    language=response_language,
                    intent="general_info_query",
                    market=market,
                    evidence_pack_id=evidence_pack_id,
                ),
            ),
        ]
        reasoning_trace = {
            "steps": [
                {
                    "step_type": "intent_classification",
                    "output_summary": "Routed to general_info_query based on non-backtest user intent.",
                },
                {
                    "step_type": "evidence_retrieval",
                    "output_summary": f"Retrieved {len(evidence_sources)} source(s) from KnowledgeService.",
                },
                {
                    "step_type": "llm_synthesis",
                    "output_summary": (
                        f"General info answer generated by LLM model={answer_result.llm_call.model} "
                        f"mode={answer_result.llm_call.mode} latency_ms={answer_result.llm_call.latency_ms}."
                    ),
                },
            ],
            "intent_trace": intent_trace,
        }
        llm_notice = (
            "General Info Answer generated by LLM: "
            f"model={answer_result.llm_call.model} mode={answer_result.llm_call.mode} latency={answer_result.llm_call.latency_ms}ms"
        )
        reasoning_steps = _build_general_info_reasoning_steps(
            trace_id=trace_id,
            session_id=str(session.session_id),
            market=market,
            citations=citations,
            llm_prompt_hash=str(answer_result.llm_call.prompt_hash),
        )
        for step in reasoning_steps:
            _emit_reasoning_step_event(
                trace_id=trace_id,
                session_id=str(session.session_id),
                step=step,
                event_type="reasoning.step.created",
            )
        _audit_store().append(
            AuditLogEntry(
                trace_id=UUID(trace_id),
                event_type="reasoning.trace.final",
                payload={
                    "agent_name": "GeneralInfo",
                    "steps_count": len(reasoning_steps),
                    "steps": [row.model_dump(mode="json") for row in reasoning_steps],
                    "has_parse_error": False,
                    "prompt_hash": str(answer_result.llm_call.prompt_hash),
                },
                created_at=datetime.now(UTC),
            )
        )
        event_bus.publish(
            event_type="reasoning.trace.final",
            trace_id=trace_id,
            session_id=str(session.session_id),
            payload={
                "agent_name": "GeneralInfo",
                "steps_count": len(reasoning_steps),
                "steps": [row.model_dump(mode="json") for row in reasoning_steps],
                "has_parse_error": False,
                "prompt_hash": str(answer_result.llm_call.prompt_hash),
            },
        )
        _audit_store().append(
            AuditLogEntry(
                trace_id=UUID(trace_id),
                event_type="chat.general_info.llm",
                payload={
                    "session_id": str(session.session_id),
                    "market": market,
                    "model": answer_result.llm_call.model,
                    "provider": answer_result.llm_call.provider,
                    "mode": answer_result.llm_call.mode,
                    "prompt_hash": answer_result.llm_call.prompt_hash,
                    "latency_ms": answer_result.llm_call.latency_ms,
                    "token_usage": answer_result.llm_call.token_usage,
                    "citation_count": len(citations),
                    "insufficient_evidence": answer_result.insufficient_evidence,
                },
                created_at=datetime.now(UTC),
            )
        )
        debug_payload = {
            "intent": "general_info_query",
            "response_language": response_language,
            "intent_trace": intent_trace,
            "market": market,
            "market_source": market_source,
            "evidence_pack_id": evidence_pack_id,
            "evidence_refs": evidence_refs,
            "citations": citations,
            "evidence_sources": evidence_sources,
            "general_info_answer": answer_payload.model_dump(mode="json"),
            "general_info_llm": answer_result.llm_call.model_dump(mode="json"),
            "general_info_llm_notice": llm_notice,
            "llm_raw_preview": answer_result.raw_output[:400],
            "reasoning_trace": reasoning_trace,
            "reasoning_steps": [row.model_dump(mode="json") for row in reasoning_steps],
            "llm_mode": answer_result.llm_call.mode,
            "session_memory": _chat_store().get_last_memory(session.session_id),
        }
    elif intent == "pipeline_research":
        _chat_store().set_last_context(session.session_id, last_market=resolved_market)
        draft_warnings = _chat_preflight_warnings(message=request.message, market=resolved_market)
        block_warnings = [row for row in draft_warnings if str(row.get("severity")) == "block"]
        warn_warnings = [row for row in draft_warnings if str(row.get("severity")) != "block"]
        if block_warnings:
            token = _store_preflight_context(
                session_id=session.session_id,
                message=request.message,
                market=resolved_market,
                response_language=response_language,
                warnings=draft_warnings,
            )
            evidence_pack_id = f"pipeline_preflight:{token}"
            warning_lines = [
                f"- [{str(row.get('reason_code') or 'warning')}] {str(row.get('message') or '')}"
                for row in block_warnings[:4]
            ]
            suggestion_lines = [
                f"- {str(row.get('suggested_fixes') or '')}"
                for row in block_warnings[:3]
                if str(row.get("suggested_fixes") or "").strip()
            ]
            warning_body = "\n".join(warning_lines)
            suggestion_body = "\n".join(suggestion_lines)
            user_answer = _ui_text(
                response_language,
                zh="迁移预检发现阻断级规则风险，已停止创建任务。请先确认处理方式。",
                en="Migration preflight found blocking rule risks. Task creation paused pending your decision.",
            )
            cards = [
                PresentationCard(
                    type="summary",
                    title=_ui_text(response_language, zh="Migration Preflight 阻断", en="Migration Preflight Blocked"),
                    content=user_answer,
                    subtitle=f"token={token}",
                ),
                PresentationCard(
                    type="risks",
                    title=_ui_text(response_language, zh="阻断原因", en="Blocking Reasons"),
                    content=warning_body,
                ),
                PresentationCard(
                    type="drivers",
                    title=_ui_text(response_language, zh="建议调整", en="Suggested Fixes"),
                    content=suggestion_body or _ui_text(response_language, zh="- 无可用自动修复建议。", en="- No auto-fix suggestion available."),
                ),
                PresentationCard(
                    type="next_steps",
                    title=_ui_text(response_language, zh="请选择处理方式", en="Choose an Action"),
                    actions=[
                        PresentationAction(
                            label=_ui_text(response_language, zh="自动调整并运行", en="Adjust Automatically"),
                            action="followup_prompt",
                            payload={"message": f"__preflight__:adjust:{token}"},
                        ),
                        PresentationAction(
                            label=_ui_text(response_language, zh="继续执行（需二次确认）", en="Proceed Anyway"),
                            action="followup_prompt",
                            payload={"message": f"__preflight__:proceed:{token}"},
                        ),
                        PresentationAction(
                            label=_ui_text(response_language, zh="取消", en="Cancel"),
                            action="followup_prompt",
                            payload={"message": f"__preflight__:cancel:{token}"},
                        ),
                    ],
                ),
            ]
            _audit_store().append(
                AuditLogEntry(
                    trace_id=UUID(trace_id),
                    event_type="chat.pipeline.preflight.blocked",
                    payload={
                        "session_id": str(session.session_id),
                        "market": resolved_market,
                        "warnings": block_warnings,
                        "token": token,
                    },
                    created_at=datetime.now(UTC),
                )
            )
            debug_payload = {
                "intent": "pipeline_research",
                "accepted": False,
                "preflight_blocked": True,
                "preflight_token": token,
                "preflight_warnings": draft_warnings,
                "market": resolved_market,
                "market_source": market_source,
                "trace_id": trace_id,
                "intent_trace": intent_trace,
                "response_language": response_language,
                "session_memory": _chat_store().get_last_memory(session.session_id),
            }
        else:
            pipeline_task = _submit_pipeline_task(
                session_id=session.session_id,
                message=request.message,
                market=resolved_market,
                response_language=response_language,
                trace_id=trace_id,
                preflight_warnings=draft_warnings,
            )
            task_id = str(pipeline_task.task_id)
            task_label = _task_short_label(task_id, response_language)
            evidence_pack_id = f"pipeline_task:{task_id}"
            user_answer = _ui_text(
                response_language,
                zh=f"{task_label} 已提交并开始执行。你可以去 Tasks 页面查看进度，结果完成后会自动同步。",
                en=f"{task_label} has started. Track progress in Tasks; results will sync automatically when ready.",
            )
            warning_card: list[PresentationCard] = []
            if warn_warnings:
                warn_lines = [
                    f"- [{str(row.get('reason_code') or 'warning')}] {str(row.get('message') or '')}"
                    for row in warn_warnings[:4]
                ]
                warning_card = [
                    PresentationCard(
                        type="risks",
                        title=_ui_text(response_language, zh="迁移预警（未阻断）", en="Migration Warning"),
                        content="\n".join(warn_lines),
                    )
                ]
                _audit_store().append(
                    AuditLogEntry(
                        trace_id=UUID(trace_id),
                        event_type="chat.pipeline.preflight.warn",
                        payload={
                            "session_id": str(session.session_id),
                            "task_id": task_id,
                            "market": resolved_market,
                            "warnings": warn_warnings,
                        },
                        created_at=datetime.now(UTC),
                    )
                )
            cards = [
                *warning_card,
                PresentationCard(
                    type="summary",
                    title=_ui_text(response_language, zh="执行中", en="Running"),
                    content=user_answer,
                    subtitle=_ui_text(
                        response_language,
                        zh=f"task_id={task_id}",
                        en=f"task_id={task_id}",
                    ),
                ),
                PresentationCard(
                    type="next_steps",
                    title=_ui_text(response_language, zh="你可以先查看", en="You can check"),
                    actions=[
                        PresentationAction(
                            label=_ui_text(response_language, zh="打开任务页", en="Open Tasks"),
                            action="open_task",
                            payload={"parent_task_id": task_id},
                        )
                    ],
                ),
            ]
            debug_payload = {
                "intent": "pipeline_research",
                "accepted": True,
                "parent_task_id": task_id,
                "task_id": task_id,
                "market": resolved_market,
                "market_source": market_source,
                "trace_id": trace_id,
                "preflight_warnings": draft_warnings,
                "intent_trace": intent_trace,
                "response_language": response_language,
                "session_memory": _chat_store().get_last_memory(session.session_id),
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
                "plan_id": str(debug_payload.get("plan_id") or ""),
                "pipeline_trace_id": str(debug_payload.get("trace_id") or "iterative"),
                "pipeline_run_id": str(debug_payload.get("run_id") or ""),
                "llm_mode": str(debug_payload.get("llm_mode") or ("iterative_modify" if intent == "modify_last_run" else "unknown")),
                "intent": intent,
            },
            created_at=datetime.now(UTC),
        )
    )

    turns = _chat_store().list_turns(session.session_id)
    assistant_turn = next((turn for turn in reversed(turns) if turn.role == "assistant"), turns[-1] if turns else ChatTurn(role="assistant", content=user_answer))
    message_id = _build_message_id(assistant_turn, fallback=f"assistant:{trace_id}")
    cards = _attach_card_ids(message_id=message_id, cards=cards)
    risk_snapshot: RiskSnapshot | None = None
    approvals_snapshot: ApprovalsSnapshot | None = None
    try:
        risk_snapshot = _build_risk_snapshot()
        approvals_snapshot = _build_approvals_snapshot(limit=8)
    except Exception:
        logger.exception("chat_message failed to build risk/approval snapshots")
    if request.include_debug:
        debug_payload = {
            **debug_payload,
            "message_id": message_id,
            "snapshot_updated_at": (risk_snapshot.updated_at if risk_snapshot else ""),
            "approvals_snapshot_updated_at": (approvals_snapshot.updated_at if approvals_snapshot else ""),
        }
    return ChatResponse(
        session_id=str(session.session_id),
        trace_id=trace_id,
        message_id=message_id,
        mode=intent,
        language=response_language,
        assistant_message=user_answer,
        evidence_pack_id=evidence_pack_id,
        cards=cards,
        risk_snapshot=risk_snapshot,
        approvals_snapshot=approvals_snapshot,
        debug=debug_payload if request.include_debug else {},
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
                "last_market": session.last_market or "",
                "recent_run_ids": [str(row.get("run_id")) for row in session.runs_by_session[-5:]],
            }
        )
    return out


