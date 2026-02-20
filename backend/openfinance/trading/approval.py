import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


ApprovalStatus = Literal["requested", "pending", "approved", "enabled", "revoked", "expired"]


class ApprovalTransition(BaseModel):
    from_status: ApprovalStatus
    to_status: ApprovalStatus
    actor: str
    reason: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApprovalRequest(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    target: str
    action: str
    status: ApprovalStatus = "requested"
    context: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    transitions: list[ApprovalTransition] = Field(default_factory=list)


class ApprovalService:
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
                CREATE TABLE IF NOT EXISTS approval_requests (
                    request_id TEXT PRIMARY KEY,
                    target TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    context TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def create_request(
        self,
        *,
        target: str,
        action: str,
        context: dict[str, object] | None = None,
        actor: str = "user",
        expires_in_hours: int = 24,
    ) -> ApprovalRequest:
        now = datetime.now(UTC)
        expires_at = now + timedelta(hours=max(1, expires_in_hours))
        request = ApprovalRequest(
            target=target,
            action=action,
            status="requested",
            context=context or {},
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO approval_requests
                (request_id, target, action, status, context, created_at, updated_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(request.request_id),
                    request.target,
                    request.action,
                    request.status,
                    json.dumps(request.context, ensure_ascii=False),
                    request.created_at.isoformat(),
                    request.updated_at.isoformat(),
                    request.expires_at.isoformat() if request.expires_at else None,
                ),
            )
            conn.commit()
        # requested -> pending
        return self.transition(
            request_id=request.request_id,
            to_status="pending",
            actor=actor,
            reason="queued_for_review",
        )

    def transition(
        self,
        *,
        request_id: UUID | str,
        to_status: ApprovalStatus,
        actor: str,
        reason: str = "",
    ) -> ApprovalRequest:
        current = self.get(request_id)
        if current is None:
            raise ValueError(f"approval request not found: {request_id}")
        if current.status == to_status:
            return current
        if not self._is_valid_transition(current.status, to_status):
            raise ValueError(f"invalid transition: {current.status} -> {to_status}")

        now = datetime.now(UTC)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE approval_requests
                SET status = ?, updated_at = ?
                WHERE request_id = ?
                """,
                (to_status, now.isoformat(), str(current.request_id)),
            )
            conn.execute(
                """
                INSERT INTO approval_transitions
                (request_id, from_status, to_status, actor, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(current.request_id),
                    current.status,
                    to_status,
                    actor,
                    reason,
                    now.isoformat(),
                ),
            )
            conn.commit()
        updated = self.get(current.request_id)
        if updated is None:
            raise RuntimeError("approval request vanished after transition")
        return updated

    def approve(self, request_id: UUID | str, actor: str = "admin", reason: str = "") -> ApprovalRequest:
        return self.transition(request_id=request_id, to_status="approved", actor=actor, reason=reason)

    def enable(self, request_id: UUID | str, actor: str = "system", reason: str = "") -> ApprovalRequest:
        return self.transition(request_id=request_id, to_status="enabled", actor=actor, reason=reason)

    def revoke(self, request_id: UUID | str, actor: str = "admin", reason: str = "") -> ApprovalRequest:
        current = self.get(request_id)
        if current is None:
            raise ValueError(f"approval request not found: {request_id}")
        if current.status == "revoked":
            return current
        return self.transition(request_id=request_id, to_status="revoked", actor=actor, reason=reason)

    def expire_stale(self) -> None:
        now = datetime.now(UTC)
        for row in self.list_requests():
            if row.status in {"revoked", "expired"}:
                continue
            if row.expires_at is not None and row.expires_at <= now:
                try:
                    self.transition(
                        request_id=row.request_id,
                        to_status="expired",
                        actor="system",
                        reason="ttl_expired",
                    )
                except ValueError:
                    continue

    def ensure_pending_request(
        self,
        *,
        target: str,
        action: str,
        context: dict[str, object] | None = None,
        actor: str = "user",
    ) -> ApprovalRequest:
        self.expire_stale()
        current = self.latest_for_target(target=target, action=action)
        if current is None:
            return self.create_request(target=target, action=action, context=context, actor=actor)
        if current.status in {"pending", "approved", "enabled"}:
            return current
        if current.status in {"revoked", "expired"}:
            return self.create_request(target=target, action=action, context=context, actor=actor)
        return current

    def latest_for_target(self, *, target: str, action: str) -> ApprovalRequest | None:
        self.expire_stale()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT request_id, target, action, status, context, created_at, updated_at, expires_at
                FROM approval_requests
                WHERE target = ? AND action = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (target, action),
            ).fetchone()
        if row is None:
            return None
        return self._to_request(row)

    def get(self, request_id: UUID | str) -> ApprovalRequest | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT request_id, target, action, status, context, created_at, updated_at, expires_at
                FROM approval_requests
                WHERE request_id = ?
                """,
                (str(request_id),),
            ).fetchone()
        if row is None:
            return None
        return self._to_request(row)

    def list_requests(self, limit: int = 200) -> list[ApprovalRequest]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT request_id, target, action, status, context, created_at, updated_at, expires_at
                FROM approval_requests
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._to_request(row) for row in rows]

    def _to_request(self, row: tuple) -> ApprovalRequest:
        request_id = UUID(str(row[0]))
        transitions = self._list_transitions(request_id)
        return ApprovalRequest(
            request_id=request_id,
            target=row[1],
            action=row[2],
            status=row[3],
            context=json.loads(row[4] or "{}"),
            created_at=datetime.fromisoformat(row[5]),
            updated_at=datetime.fromisoformat(row[6]),
            expires_at=datetime.fromisoformat(row[7]) if row[7] else None,
            transitions=transitions,
        )

    def _list_transitions(self, request_id: UUID) -> list[ApprovalTransition]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT from_status, to_status, actor, reason, created_at
                FROM approval_transitions
                WHERE request_id = ?
                ORDER BY id ASC
                """,
                (str(request_id),),
            ).fetchall()
        out: list[ApprovalTransition] = []
        for row in rows:
            out.append(
                ApprovalTransition(
                    from_status=row[0],
                    to_status=row[1],
                    actor=row[2],
                    reason=row[3],
                    created_at=datetime.fromisoformat(row[4]),
                )
            )
        return out

    def _is_valid_transition(self, from_status: ApprovalStatus, to_status: ApprovalStatus) -> bool:
        allowed: dict[ApprovalStatus, set[ApprovalStatus]] = {
            "requested": {"pending", "revoked", "expired"},
            "pending": {"approved", "revoked", "expired"},
            "approved": {"enabled", "revoked", "expired"},
            "enabled": {"revoked", "expired"},
            "revoked": set(),
            "expired": set(),
        }
        return to_status in allowed[from_status]
