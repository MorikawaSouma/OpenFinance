import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    role: str  # user | assistant | system
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatSession(BaseModel):
    session_id: UUID = Field(default_factory=uuid4)
    turns: list[ChatTurn] = Field(default_factory=list)
    last_run_id: str | None = None
    last_plan_id: str | None = None
    last_report_id: str | None = None
    last_dataset_version: str | None = None
    runs_by_session: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatStore:
    def __init__(self, storage_file: str | None = None) -> None:
        self._lock = Lock()
        self._sessions: dict[UUID, ChatSession] = {}
        self._storage_path = Path(storage_file) if storage_file else None
        if self._storage_path is not None:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            self._load()

    def _load(self) -> None:
        if self._storage_path is None or (not self._storage_path.exists()):
            return
        try:
            raw = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        rows: list[Any]
        if isinstance(raw, list):
            rows = raw
        elif isinstance(raw, dict):
            rows = list(raw.values())
        else:
            rows = []
        loaded: dict[UUID, ChatSession] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                session = ChatSession.model_validate(row)
            except ValueError:
                continue
            loaded[session.session_id] = session
        with self._lock:
            self._sessions = loaded

    def _save_locked(self) -> None:
        if self._storage_path is None:
            return
        payload = [session.model_dump(mode="json") for session in self._sessions.values()]
        self._storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_or_create(self, session_id: UUID | None = None) -> ChatSession:
        with self._lock:
            if session_id and session_id in self._sessions:
                return self._sessions[session_id]
            session = ChatSession(session_id=session_id or uuid4())
            self._sessions[session.session_id] = session
            self._save_locked()
            return session

    def append_turn(self, session_id: UUID, role: str, content: str) -> ChatSession:
        with self._lock:
            session = self._sessions.get(session_id) or ChatSession(session_id=session_id)
            session.turns.append(ChatTurn(role=role, content=content))
            session.updated_at = datetime.now(UTC)
            self._sessions[session_id] = session
            self._save_locked()
            return session

    def set_last_context(
        self,
        session_id: UUID,
        *,
        last_run_id: str | None = None,
        last_plan_id: str | None = None,
        last_report_id: str | None = None,
        last_dataset_version: str | None = None,
    ) -> ChatSession:
        with self._lock:
            session = self._sessions.get(session_id) or ChatSession(session_id=session_id)
            if last_run_id is not None:
                session.last_run_id = last_run_id
            if last_plan_id is not None:
                session.last_plan_id = last_plan_id
            if last_report_id is not None:
                session.last_report_id = last_report_id
            if last_dataset_version is not None:
                session.last_dataset_version = last_dataset_version
            if last_run_id:
                exists = any(str(row.get("run_id")) == last_run_id for row in session.runs_by_session)
                if not exists:
                    session.runs_by_session.append(
                        {
                            "run_id": last_run_id,
                            "plan_id": session.last_plan_id,
                            "report_id": session.last_report_id,
                            "dataset_version": session.last_dataset_version,
                            "metrics": {},
                            "created_at": datetime.now(UTC).isoformat(),
                        }
                    )
                    session.runs_by_session = session.runs_by_session[-20:]
            session.updated_at = datetime.now(UTC)
            self._sessions[session_id] = session
            self._save_locked()
            return session

    def register_run(
        self,
        session_id: UUID,
        *,
        run_id: str,
        plan_id: str | None = None,
        report_id: str | None = None,
        dataset_version: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> ChatSession:
        with self._lock:
            session = self._sessions.get(session_id) or ChatSession(session_id=session_id)
            session.last_run_id = run_id
            session.last_plan_id = plan_id if plan_id is not None else session.last_plan_id
            session.last_report_id = report_id if report_id is not None else session.last_report_id
            session.last_dataset_version = dataset_version if dataset_version is not None else session.last_dataset_version
            row = {
                "run_id": run_id,
                "plan_id": session.last_plan_id,
                "report_id": session.last_report_id,
                "dataset_version": session.last_dataset_version,
                "metrics": dict(metrics or {}),
                "created_at": datetime.now(UTC).isoformat(),
            }
            # Keep a unique run list while preserving recency order.
            session.runs_by_session = [item for item in session.runs_by_session if str(item.get("run_id")) != run_id]
            session.runs_by_session.append(row)
            session.runs_by_session = session.runs_by_session[-20:]
            session.updated_at = datetime.now(UTC)
            self._sessions[session_id] = session
            self._save_locked()
            return session

    def get_last_context(self, session_id: UUID) -> tuple[str | None, str | None]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None, None
            return session.last_run_id, session.last_plan_id

    def get_last_memory(self, session_id: UUID) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return {
                    "last_run_id": None,
                    "last_plan_id": None,
                    "last_report_id": None,
                    "last_dataset_version": None,
                    "runs_by_session": [],
                }
            return {
                "last_run_id": session.last_run_id,
                "last_plan_id": session.last_plan_id,
                "last_report_id": session.last_report_id,
                "last_dataset_version": session.last_dataset_version,
                "runs_by_session": list(session.runs_by_session),
            }

    def get_recent_runs(self, session_id: UUID, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return []
            rows = list(session.runs_by_session)
        return rows[-max(1, limit) :]

    def resolve_run_reference(self, session_id: UUID, query_text: str) -> str | None:
        text = query_text.lower()
        rows = self.get_recent_runs(session_id, limit=20)
        if not rows:
            return None
        if ("上上次" in query_text) or ("previous previous" in text) or ("second previous" in text):
            return str(rows[-3]["run_id"]) if len(rows) >= 3 else None
        if ("上次" in query_text) or ("previous" in text) or ("last run" in text):
            return str(rows[-2]["run_id"]) if len(rows) >= 2 else None
        if ("收益更高" in query_text) or ("higher return" in text) or ("best return" in text):
            best = None
            best_ret = float("-inf")
            for row in rows:
                metrics = row.get("metrics", {})
                if not isinstance(metrics, dict):
                    continue
                value = metrics.get("total_return")
                if isinstance(value, (int, float)) and float(value) > best_ret:
                    best_ret = float(value)
                    best = row
            return str(best["run_id"]) if best else None
        return str(rows[-1]["run_id"])

    def resolve_compare_pair(self, session_id: UUID, query_text: str) -> tuple[str, str] | None:
        rows = self.get_recent_runs(session_id, limit=20)
        if len(rows) < 2:
            return None
        current_run_id = str(rows[-1]["run_id"])
        baseline_run_id = self.resolve_run_reference(session_id, query_text)
        if baseline_run_id is None or baseline_run_id == current_run_id:
            baseline_run_id = str(rows[-2]["run_id"])
        return current_run_id, baseline_run_id

    def list_turns(self, session_id: UUID) -> list[ChatTurn]:
        with self._lock:
            return list(self._sessions.get(session_id, ChatSession(session_id=session_id)).turns)

    def list_sessions(self) -> list[ChatSession]:
        with self._lock:
            rows = list(self._sessions.values())
        return sorted(rows, key=lambda x: x.updated_at, reverse=True)
