"""Production FastAPI entry point."""

import json
import logging
import re
from asyncio import sleep
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from time import perf_counter

from fastapi import Depends, FastAPI, HTTPException, Path, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from utils.mock_llm import ask as llm_ask

from .auth import verify_api_key
from .config import settings
from .cost_guard import billing_period, check_budget, record_cost
from .history import append_turn, history_key, read_history
from .rate_limiter import check_rate_limit
from .redis_client import r, redis_healthy

logging.basicConfig(level=settings.log_level.upper(), format="%(message)s")
logger = logging.getLogger("agent")


def log_event(event: str, **fields) -> None:
    logger.info(json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "lvl": "INFO",
        "event": event,
        **fields,
    }))


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_event("startup", environment=settings.environment)
    try:
        yield
    finally:
        # Uvicorn drains in-flight requests before running lifespan shutdown.
        r.close()
        log_event("shutdown")


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = Field(None, min_length=1, max_length=128)
    user_id: str | None = Field(None, min_length=1, max_length=128)


@app.middleware("http")
async def log_request(request: Request, call_next):
    start = perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        log_event("request", method=request.method, path=route.path if route else "unmatched",
                  status=status, ms=round((perf_counter() - start) * 1000, 1))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis unavailable")
    return {"ready": True}


def answer_question(body: AskRequest, key: str) -> str:
    try:
        check_rate_limit(key)
        budget_key, expires_at = billing_period()
        check_budget(budget_key)
        session = body.session_id or body.user_id
        storage_key = history_key(key, session) if session else None
        previous_turns = read_history(storage_key, last_only=True) if storage_key else []
        previous_question = previous_turns[-1]["question"] if previous_turns else None
        answer = llm_ask(body.question, previous_question=previous_question)
        # The mock supplies text only. Use whitespace-delimited tokens as a lab estimate.
        input_tokens = len(body.question.split()) + len((previous_question or "").split())
        record_cost(budget_key, expires_at, input_tokens, len(answer.split()))
        if storage_key:
            append_turn(storage_key, body.question, answer)
    except RedisError:
        log_event("redis_unavailable")
        raise HTTPException(status_code=503, detail="Redis unavailable") from None
    return answer


@app.post("/ask")
def ask(body: AskRequest, key: str = Depends(verify_api_key)):
    answer = answer_question(body, key)
    return {"question": body.question, "answer": answer}


@app.post("/ask/stream", response_class=StreamingResponse)
def ask_stream(body: AskRequest, key: str = Depends(verify_api_key)):
    # Complete admission, accounting and storage before sending response headers.
    answer = answer_question(body, key)

    async def chunks():
        for match in re.finditer(r"\S+\s*|\s+", answer):
            yield match.group()
            await sleep(0.05)

    return StreamingResponse(chunks(), media_type="text/plain",
                             headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"})


@app.get("/sessions/{session_id}/history")
def session_history(session_id: str = Path(..., min_length=1, max_length=128),
                    key: str = Depends(verify_api_key)):
    try:
        return {"session_id": session_id, "turns": read_history(history_key(key, session_id))}
    except RedisError:
        log_event("redis_unavailable")
        raise HTTPException(status_code=503, detail="Redis unavailable") from None
