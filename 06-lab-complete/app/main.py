"""Production FastAPI entry point."""

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from time import perf_counter

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from utils.mock_llm import ask as llm_ask

from .auth import verify_api_key
from .config import settings
from .cost_guard import billing_period, check_budget, record_cost
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


@app.post("/ask")
def ask(body: AskRequest, key: str = Depends(verify_api_key)):
    try:
        check_rate_limit(key)
        budget_key, expires_at = billing_period()
        check_budget(budget_key)
        answer = llm_ask(body.question)
        # The mock supplies text only. Use whitespace-delimited tokens as a lab estimate.
        record_cost(budget_key, expires_at, len(body.question.split()), len(answer.split()))
    except RedisError:
        log_event("redis_unavailable")
        raise HTTPException(status_code=503, detail="Redis unavailable") from None
    return {"question": body.question, "answer": answer}
