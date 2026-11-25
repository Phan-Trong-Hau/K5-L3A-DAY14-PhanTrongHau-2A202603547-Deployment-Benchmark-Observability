"""Track shared LLM spend in integer nano-USD by UTC billing period."""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from .config import settings
from .redis_client import r

NANO_USD = 1_000_000_000
INPUT_PRICE = 150
OUTPUT_PRICE = 600


def billing_period() -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if settings.daily_budget_usd is not None:
        return f"day14:spend:{today:%Y-%m-%d}", int((today + timedelta(days=1)).timestamp())
    next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    return f"day14:spend:{today:%Y-%m}", int(next_month.timestamp())


def check_budget(key: str) -> None:
    limit = settings.daily_budget_usd
    if limit is None:
        limit = settings.monthly_budget_usd
    spent = int(r.get(key) or 0)
    if spent >= limit * NANO_USD:
        raise HTTPException(status_code=402, detail="LLM budget exhausted")


def record_cost(key: str, expires_at: int, input_tokens: int, output_tokens: int) -> None:
    cost = input_tokens * INPUT_PRICE + output_tokens * OUTPUT_PRICE
    with r.pipeline() as transaction:
        transaction.incrby(key, cost)
        transaction.expireat(key, expires_at)
        transaction.execute()
