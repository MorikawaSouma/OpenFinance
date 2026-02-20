import queue
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4


class InMemoryEventBus:
    def __init__(self) -> None:
        self._subs: dict[str, queue.Queue[dict]] = {}
        self._history: list[dict] = []
        self._lock = Lock()

    def publish(self, event_type: str, payload: dict, trace_id: str | None = None, session_id: str = "global") -> dict:
        event = {
            "type": event_type,
            "trace_id": trace_id or str(uuid4()),
            "session_id": session_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": payload,
        }
        with self._lock:
            self._history.append(event)
            if len(self._history) > 200:
                self._history = self._history[-200:]
            for sub in self._subs.values():
                sub.put_nowait(event)
        return event

    def subscribe(self, replay: int = 0) -> tuple[str, queue.Queue[dict], list[dict]]:
        sub_id = str(uuid4())
        q: queue.Queue[dict] = queue.Queue()
        with self._lock:
            self._subs[sub_id] = q
            history = self._history[-replay:] if replay > 0 else []
        return sub_id, q, history

    def unsubscribe(self, sub_id: str) -> None:
        with self._lock:
            self._subs.pop(sub_id, None)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self._history)


event_bus = InMemoryEventBus()
