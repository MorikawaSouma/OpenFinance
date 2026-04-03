from statistics import fmean
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _typed_float_map(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, float] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip()
        number = _to_float(raw_value)
        if not key or number is None:
            continue
        out[key] = number
    return out


class StrategyRuntimeCostDetail(BaseModel):
    commission_sum: float | None = None
    slippage_sum: float | None = None
    total_cost: float | None = None
    trade_count: int = 0
    order_count: int = 0
    avg_total_cost_per_trade: float | None = None
    avg_total_cost_per_order: float | None = None
    cost_drag: float | None = None


class StrategyRuntimeAttributionRow(BaseModel):
    label: str
    pnl: float
    abs_share: float | None = None


class StrategyRuntimeAttributionDetail(BaseModel):
    instrument_rows: list[StrategyRuntimeAttributionRow] = Field(default_factory=list)
    sector_rows: list[StrategyRuntimeAttributionRow] = Field(default_factory=list)
    instrument_count: int = 0
    sector_count: int = 0
    top_instrument: StrategyRuntimeAttributionRow | None = None
    worst_instrument: StrategyRuntimeAttributionRow | None = None
    top_sector: StrategyRuntimeAttributionRow | None = None
    worst_sector: StrategyRuntimeAttributionRow | None = None


class StrategyRuntimeExecutionStyleDetail(BaseModel):
    execution_model: str | None = None
    order_count: int = 0
    filled_order_count: int = 0
    rejected_order_count: int = 0
    queued_order_count: int = 0
    trade_count: int = 0
    buy_trade_count: int = 0
    sell_trade_count: int = 0
    fill_rate: float | None = None
    avg_trade_qty: float | None = None
    order_status_counts: dict[str, int] = Field(default_factory=dict)
    reject_reason_counts: dict[str, int] = Field(default_factory=dict)
    dominant_reject_reason: str | None = None


class StrategyRuntimeAttributionExecutionDetails(BaseModel):
    schema_version: str = "strategy_runtime_attribution_execution.v1"
    detail_object: Literal["BacktestReport", "MarketCompareRow", "RobustnessVariant", "RestoreReportHeader"] = (
        "BacktestReport"
    )
    cost_detail: StrategyRuntimeCostDetail = Field(default_factory=StrategyRuntimeCostDetail)
    attribution_detail: StrategyRuntimeAttributionDetail = Field(default_factory=StrategyRuntimeAttributionDetail)
    execution_style_detail: StrategyRuntimeExecutionStyleDetail = Field(default_factory=StrategyRuntimeExecutionStyleDetail)
    summary: str = ""


def parse_strategy_runtime_attribution_execution_details(
    raw: StrategyRuntimeAttributionExecutionDetails | dict[str, Any] | None,
) -> StrategyRuntimeAttributionExecutionDetails | None:
    if raw is None:
        return None
    if isinstance(raw, StrategyRuntimeAttributionExecutionDetails):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return StrategyRuntimeAttributionExecutionDetails.model_validate(raw)
    except ValidationError:
        return None


def resolve_strategy_runtime_attribution_execution_details(
    *,
    detail_object: Literal["BacktestReport", "MarketCompareRow", "RobustnessVariant", "RestoreReportHeader"],
    details: StrategyRuntimeAttributionExecutionDetails | dict[str, Any] | None,
    cost_breakdown: dict[str, Any] | None,
    attribution: dict[str, Any] | None,
    diagnostics: dict[str, Any] | None,
    orders: list[Any] | None,
    trades: list[Any] | None,
    metrics: dict[str, Any] | None,
) -> StrategyRuntimeAttributionExecutionDetails:
    parsed = parse_strategy_runtime_attribution_execution_details(details)
    if parsed is not None and parsed.detail_object == detail_object:
        return parsed
    return build_strategy_runtime_attribution_execution_details(
        detail_object=detail_object,
        cost_breakdown=cost_breakdown,
        attribution=attribution,
        diagnostics=diagnostics,
        orders=orders,
        trades=trades,
        metrics=metrics,
    )


def _build_attribution_rows(value: Any) -> list[StrategyRuntimeAttributionRow]:
    typed = _typed_float_map(value)
    total_abs = sum(abs(number) for number in typed.values())
    rows = [
        StrategyRuntimeAttributionRow(
            label=label,
            pnl=round(number, 6),
            abs_share=round(abs(number) / total_abs, 6) if total_abs > 0 else None,
        )
        for label, number in sorted(typed.items(), key=lambda item: abs(item[1]), reverse=True)
    ]
    return rows


def _build_attribution_detail(attribution: dict[str, Any] | None, diagnostics: dict[str, Any] | None) -> StrategyRuntimeAttributionDetail:
    typed_attr = attribution if isinstance(attribution, dict) else {}
    typed_diag = diagnostics if isinstance(diagnostics, dict) else {}
    instrument_rows = _build_attribution_rows(
        typed_attr.get("instrument_pnl_contrib")
        if isinstance(typed_attr.get("instrument_pnl_contrib"), dict)
        else typed_diag.get("instrument_pnl_contrib")
    )
    sector_rows = _build_attribution_rows(
        typed_attr.get("sector_pnl_contrib")
        if isinstance(typed_attr.get("sector_pnl_contrib"), dict)
        else typed_diag.get("sector_pnl_contrib")
    )
    return StrategyRuntimeAttributionDetail(
        instrument_rows=instrument_rows,
        sector_rows=sector_rows,
        instrument_count=len(instrument_rows),
        sector_count=len(sector_rows),
        top_instrument=max(instrument_rows, key=lambda row: row.pnl) if instrument_rows else None,
        worst_instrument=min(instrument_rows, key=lambda row: row.pnl) if instrument_rows else None,
        top_sector=max(sector_rows, key=lambda row: row.pnl) if sector_rows else None,
        worst_sector=min(sector_rows, key=lambda row: row.pnl) if sector_rows else None,
    )


def _build_cost_detail(
    cost_breakdown: dict[str, Any] | None,
    *,
    orders: list[Any],
    trades: list[Any],
    metrics: dict[str, Any] | None,
) -> StrategyRuntimeCostDetail:
    payload = cost_breakdown if isinstance(cost_breakdown, dict) else {}
    commission_sum = _to_float(payload.get("commission_sum"))
    if commission_sum is None:
        commission_sum = _to_float(payload.get("commission"))
    slippage_sum = _to_float(payload.get("slippage_sum"))
    if slippage_sum is None:
        slippage_sum = _to_float(payload.get("slippage"))
    if commission_sum is None:
        commission_sum = round(sum(float(_read(row, "commission") or 0.0) for row in trades), 6)
    if slippage_sum is None:
        slippage_sum = round(sum(float(_read(row, "slippage") or 0.0) for row in trades), 6)
    total_cost = _to_float(payload.get("total"))
    if total_cost is None:
        total_cost = round(float(commission_sum or 0.0) + float(slippage_sum or 0.0), 6)
    trade_count = len(trades)
    order_count = len(orders)
    return StrategyRuntimeCostDetail(
        commission_sum=round(float(commission_sum or 0.0), 6),
        slippage_sum=round(float(slippage_sum or 0.0), 6),
        total_cost=round(float(total_cost or 0.0), 6),
        trade_count=trade_count,
        order_count=order_count,
        avg_total_cost_per_trade=round(float(total_cost or 0.0) / trade_count, 6) if trade_count > 0 else None,
        avg_total_cost_per_order=round(float(total_cost or 0.0) / order_count, 6) if order_count > 0 else None,
        cost_drag=_to_float((metrics or {}).get("cost_drag")) if isinstance(metrics, dict) else None,
    )


def _build_execution_style_detail(
    diagnostics: dict[str, Any] | None,
    *,
    orders: list[Any],
    trades: list[Any],
) -> StrategyRuntimeExecutionStyleDetail:
    order_status_counts: dict[str, int] = {}
    reject_reason_counts: dict[str, int] = {}
    for row in orders:
        status = str(_read(row, "status") or "").strip().lower()
        if status:
            order_status_counts[status] = order_status_counts.get(status, 0) + 1
        if status == "rejected":
            reason = str(_read(row, "reason_code") or _read(row, "reason") or "").strip()
            if reason:
                reject_reason_counts[reason] = reject_reason_counts.get(reason, 0) + 1
    trade_count = len(trades)
    buy_trade_count = 0
    sell_trade_count = 0
    trade_qtys: list[float] = []
    for row in trades:
        side = str(_read(row, "side") or "").strip().lower()
        if side == "buy":
            buy_trade_count += 1
        elif side == "sell":
            sell_trade_count += 1
        qty = _to_float(_read(row, "qty"))
        if qty is not None:
            trade_qtys.append(qty)
    dominant_reject_reason = None
    if reject_reason_counts:
        dominant_reject_reason = max(
            reject_reason_counts.items(),
            key=lambda item: (item[1], item[0]),
        )[0]
    order_count = len(orders)
    filled_order_count = order_status_counts.get("filled", 0)
    rejected_order_count = order_status_counts.get("rejected", 0)
    queued_order_count = order_status_counts.get("queued", 0)
    payload = diagnostics if isinstance(diagnostics, dict) else {}
    return StrategyRuntimeExecutionStyleDetail(
        execution_model=str(payload.get("execution_model") or "").strip() or None,
        order_count=order_count,
        filled_order_count=filled_order_count,
        rejected_order_count=rejected_order_count,
        queued_order_count=queued_order_count,
        trade_count=trade_count,
        buy_trade_count=buy_trade_count,
        sell_trade_count=sell_trade_count,
        fill_rate=round(filled_order_count / order_count, 6) if order_count > 0 else None,
        avg_trade_qty=round(fmean(trade_qtys), 6) if trade_qtys else None,
        order_status_counts=order_status_counts,
        reject_reason_counts=reject_reason_counts,
        dominant_reject_reason=dominant_reject_reason,
    )


def build_strategy_runtime_attribution_execution_details(
    *,
    detail_object: Literal["BacktestReport", "MarketCompareRow", "RobustnessVariant", "RestoreReportHeader"],
    cost_breakdown: dict[str, Any] | None,
    attribution: dict[str, Any] | None,
    diagnostics: dict[str, Any] | None,
    orders: list[Any] | None,
    trades: list[Any] | None,
    metrics: dict[str, Any] | None,
) -> StrategyRuntimeAttributionExecutionDetails:
    order_rows = list(orders) if isinstance(orders, list) else []
    trade_rows = list(trades) if isinstance(trades, list) else []
    cost_detail = _build_cost_detail(cost_breakdown, orders=order_rows, trades=trade_rows, metrics=metrics)
    attribution_detail = _build_attribution_detail(attribution, diagnostics)
    execution_style_detail = _build_execution_style_detail(diagnostics, orders=order_rows, trades=trade_rows)

    summary_parts: list[str] = []
    if cost_detail.total_cost is not None:
        summary_parts.append(f"total_cost={cost_detail.total_cost}")
    if execution_style_detail.fill_rate is not None:
        summary_parts.append(f"fill_rate={execution_style_detail.fill_rate}")
    if attribution_detail.top_instrument is not None:
        summary_parts.append(f"top_instr={attribution_detail.top_instrument.label}")
    if attribution_detail.top_sector is not None:
        summary_parts.append(f"top_sector={attribution_detail.top_sector.label}")

    return StrategyRuntimeAttributionExecutionDetails(
        detail_object=detail_object,
        cost_detail=cost_detail,
        attribution_detail=attribution_detail,
        execution_style_detail=execution_style_detail,
        summary="; ".join(summary_parts),
    )
