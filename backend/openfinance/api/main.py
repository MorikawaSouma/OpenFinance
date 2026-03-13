import json
import logging
import queue
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from openfinance.api.routes_chat import router as chat_router
from openfinance.api.routes_knowledge import router as knowledge_router
from openfinance.api.routes_llm import router as llm_router
from openfinance.api.routes_markets import router as markets_router
from openfinance.api.routes_orchestrator import router as orchestrator_router
from openfinance.api.routes_pipeline import router as pipeline_router
from openfinance.api.routes_research import router as research_router
from openfinance.api.routes_trace import router as trace_router
from openfinance.api.routes_trading import router as trading_router
from openfinance.api.routes_workbench import router as workbench_router
from openfinance.core.config import settings
from openfinance.core.events import event_bus
from openfinance.core.logging import configure_logging

configure_logging()
logger = logging.getLogger(__name__)


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.headers["content-type"] = "application/json; charset=utf-8"


app = FastAPI(title=settings.app_name, version="0.1.0", default_response_class=UTF8JSONResponse)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(orchestrator_router)
app.include_router(research_router)
app.include_router(pipeline_router)
app.include_router(chat_router)
app.include_router(knowledge_router)
app.include_router(llm_router)
app.include_router(markets_router)
app.include_router(trading_router)
app.include_router(workbench_router)
app.include_router(trace_router)


@app.middleware("http")
async def force_utf8_content_type(request: Request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    normalized = content_type.lower()
    if content_type:
        updated_content_type: str | None = None
        if normalized.startswith("application/json") and "charset=" not in normalized:
            updated_content_type = f"{content_type}; charset=utf-8"
        elif normalized.startswith("text/plain") and "charset=" not in normalized:
            updated_content_type = f"{content_type}; charset=utf-8"
        elif normalized.startswith("text/event-stream") and "charset=" not in normalized:
            updated_content_type = f"{content_type}; charset=utf-8"
        if updated_content_type:
            response.headers["content-type"] = updated_content_type
            response.raw_headers = [
                (name, updated_content_type.encode("latin-1")) if name.lower() == b"content-type" else (name, value)
                for name, value in response.raw_headers
            ]
    return response


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "env": settings.env}


@app.get("/events/stream")
def stream() -> StreamingResponse:
    sub_id, sub_q, replay = event_bus.subscribe(replay=20)
    hello = {
        "event_id": str(uuid4()),
        "type": "chat.delta",
        "trace_id": str(uuid4()),
        "session_id": "sse",
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": {"message": "sse connected"},
    }
    logger.info("SSE subscriber connected: %s", sub_id)

    def event_gen():
        def _encode_event(item: dict) -> str:
            event_id = str(item.get("event_id") or "")
            if event_id:
                return f"id: {event_id}\ndata: {json.dumps(item)}\n\n"
            return f"data: {json.dumps(item)}\n\n"

        try:
            yield _encode_event(hello)
            for item in replay:
                yield _encode_event(item)
            while True:
                try:
                    item = sub_q.get(timeout=15)
                    yield _encode_event(item)
                except queue.Empty:
                    heartbeat = {
                        "event_id": str(uuid4()),
                        "type": "audit.trace",
                        "trace_id": str(uuid4()),
                        "session_id": "sse",
                        "timestamp": datetime.now(UTC).isoformat(),
                        "payload": {"heartbeat": True},
                    }
                    yield _encode_event(heartbeat)
        finally:
            event_bus.unsubscribe(sub_id)
            logger.info("SSE subscriber disconnected: %s", sub_id)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
