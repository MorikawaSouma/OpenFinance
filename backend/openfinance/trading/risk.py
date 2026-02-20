import json
import sqlite3
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class RiskDecision(BaseModel):
    allowed: bool
    reason: str = ""


class RiskEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    severity: str = "high"
    message: str
    source: str = "risk_monitor"
    metrics: dict[str, float | int | str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RiskSnapshot(BaseModel):
    account_equity: float
    peak_equity: float
    current_drawdown: float
    rolling_volatility: float
    realized_volatility: float
    status: str = "normal"  # normal | warn | blocked
    max_account_drawdown_limit: float
    abnormal_volatility_limit: float
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RiskEventStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    source TEXT NOT NULL,
                    metrics TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def append(self, event: RiskEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO risk_events
                (event_id, event_type, severity, message, source, metrics, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(event.event_id),
                    event.event_type,
                    event.severity,
                    event.message,
                    event.source,
                    json.dumps(event.metrics, ensure_ascii=False),
                    event.created_at.isoformat(),
                ),
            )
            conn.commit()

    def list_recent(self, limit: int = 50) -> list[RiskEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT event_id, event_type, severity, message, source, metrics, created_at
                FROM risk_events
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        out: list[RiskEvent] = []
        for row in rows:
            try:
                metrics = json.loads(row[5]) if row[5] else {}
            except json.JSONDecodeError:
                metrics = {}
            out.append(
                RiskEvent(
                    event_id=UUID(row[0]),
                    event_type=row[1],
                    severity=row[2],
                    message=row[3],
                    source=row[4],
                    metrics=metrics if isinstance(metrics, dict) else {},
                    created_at=datetime.fromisoformat(row[6]),
                )
            )
        return out


class RiskMonitor:
    def __init__(
        self,
        *,
        max_account_drawdown: float = 0.05,
        abnormal_volatility_threshold: float = 0.03,
        rolling_window: int = 20,
        warn_ratio: float = 0.7,
        initial_equity: float = 1_000_000.0,
    ) -> None:
        self.max_account_drawdown = max(0.0, float(max_account_drawdown))
        self.abnormal_volatility_threshold = max(0.0, float(abnormal_volatility_threshold))
        self.rolling_window = max(3, int(rolling_window))
        self.warn_ratio = min(0.95, max(0.2, float(warn_ratio)))
        self._equity_history: list[float] = [max(1.0, float(initial_equity))]
        self._return_history: list[float] = []
        self._peak_equity: float = self._equity_history[0]
        self._blocked: bool = False
        self._triggered_types: set[str] = set()
        self._snapshot = RiskSnapshot(
            account_equity=self._equity_history[0],
            peak_equity=self._peak_equity,
            current_drawdown=0.0,
            rolling_volatility=0.0,
            realized_volatility=0.0,
            status="normal",
            max_account_drawdown_limit=self.max_account_drawdown,
            abnormal_volatility_limit=self.abnormal_volatility_threshold,
        )

    def snapshot(self) -> RiskSnapshot:
        return self._snapshot.model_copy(deep=True)

    def clear_blocked(self) -> RiskSnapshot:
        self._blocked = False
        self._triggered_types.clear()
        if self._snapshot.status == "blocked":
            self._snapshot.status = "normal"
        self._snapshot.last_updated = datetime.now(UTC)
        return self.snapshot()

    def update(
        self,
        *,
        account_equity: float,
        source: str = "manual",
        timestamp: datetime | None = None,
    ) -> tuple[RiskSnapshot, list[RiskEvent]]:
        ts = timestamp or datetime.now(UTC)
        equity = max(1.0, float(account_equity))
        prev = self._equity_history[-1] if self._equity_history else equity
        if prev > 0:
            self._return_history.append((equity / prev) - 1.0)
        self._equity_history.append(equity)
        if len(self._equity_history) > 5000:
            self._equity_history = self._equity_history[-5000:]
        if len(self._return_history) > 5000:
            self._return_history = self._return_history[-5000:]

        self._peak_equity = max(self._peak_equity, equity)
        drawdown = (self._peak_equity - equity) / self._peak_equity if self._peak_equity > 0 else 0.0
        rolling_slice = self._return_history[-self.rolling_window :]
        rolling_vol = statistics.pstdev(rolling_slice) if len(rolling_slice) > 1 else 0.0
        realized_vol = statistics.pstdev(self._return_history) if len(self._return_history) > 1 else 0.0

        drawdown_breach = drawdown >= self.max_account_drawdown and self.max_account_drawdown > 0
        vol_breach = rolling_vol >= self.abnormal_volatility_threshold and self.abnormal_volatility_threshold > 0

        events: list[RiskEvent] = []
        if drawdown_breach:
            events.extend(
                self._emit_once(
                    event_type="max_account_drawdown_breach",
                    message=(
                        f"账户回撤超过 {self.max_account_drawdown * 100:.1f}% 已自动停机，"
                        f"当前回撤 {drawdown * 100:.2f}%"
                    ),
                    source=source,
                    metrics={
                        "current_drawdown": round(drawdown, 6),
                        "drawdown_limit": round(self.max_account_drawdown, 6),
                        "account_equity": round(equity, 6),
                        "peak_equity": round(self._peak_equity, 6),
                    },
                    created_at=ts,
                )
            )
        if vol_breach:
            events.extend(
                self._emit_once(
                    event_type="abnormal_volatility_breach",
                    message=(
                        f"账户波动率超过阈值 {self.abnormal_volatility_threshold * 100:.2f}% ，"
                        f"当前滚动波动率 {rolling_vol * 100:.2f}%"
                    ),
                    source=source,
                    metrics={
                        "rolling_volatility": round(rolling_vol, 6),
                        "realized_volatility": round(realized_vol, 6),
                        "volatility_limit": round(self.abnormal_volatility_threshold, 6),
                        "window": self.rolling_window,
                    },
                    created_at=ts,
                )
            )

        if drawdown_breach or vol_breach:
            self._blocked = True
        if self._blocked:
            status = "blocked"
        else:
            warn_dd = drawdown >= (self.max_account_drawdown * self.warn_ratio)
            warn_vol = rolling_vol >= (self.abnormal_volatility_threshold * self.warn_ratio)
            status = "warn" if (warn_dd or warn_vol) else "normal"

        self._snapshot = RiskSnapshot(
            account_equity=equity,
            peak_equity=self._peak_equity,
            current_drawdown=round(drawdown, 6),
            rolling_volatility=round(rolling_vol, 6),
            realized_volatility=round(realized_vol, 6),
            status=status,
            max_account_drawdown_limit=self.max_account_drawdown,
            abnormal_volatility_limit=self.abnormal_volatility_threshold,
            last_updated=ts,
        )
        return self.snapshot(), events

    def _emit_once(
        self,
        *,
        event_type: str,
        message: str,
        source: str,
        metrics: dict[str, float | int | str],
        created_at: datetime,
    ) -> list[RiskEvent]:
        if event_type in self._triggered_types:
            return []
        self._triggered_types.add(event_type)
        return [
            RiskEvent(
                event_type=event_type,
                severity="high",
                message=message,
                source=source,
                metrics=metrics,
                created_at=created_at,
            )
        ]


class RiskGate(BaseModel):
    max_order_qty: float = Field(default=10000.0, gt=0)
    live_enabled: bool = False
    paper_enabled: bool = True
    kill_switch_enabled: bool = False

    def check_order(self, quantity: float, is_live: bool) -> RiskDecision:
        if self.kill_switch_enabled:
            return RiskDecision(allowed=False, reason="kill_switch_enabled")
        if quantity <= 0:
            return RiskDecision(allowed=False, reason="invalid_quantity")
        if quantity > self.max_order_qty:
            return RiskDecision(allowed=False, reason="quantity_limit_exceeded")
        if (not is_live) and (not self.paper_enabled):
            return RiskDecision(allowed=False, reason="paper_trading_stopped")
        if is_live and not self.live_enabled:
            return RiskDecision(allowed=False, reason="live_trading_disabled")
        return RiskDecision(allowed=True, reason="ok")
