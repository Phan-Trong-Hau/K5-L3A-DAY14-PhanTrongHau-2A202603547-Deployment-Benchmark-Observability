"""Keep a bounded list of completed turns per credential and session."""

import json
from hashlib import sha256

from .redis_client import r

MAX_TURNS = 20
SESSION_TTL_SECONDS = 24 * 60 * 60


def history_key(api_key: str, session_id: str) -> str:
    fingerprint = sha256(api_key.encode()).hexdigest()
    session = sha256(session_id.encode()).hexdigest()
    return f"day14:history:{fingerprint}:{session}"


def read_history(key: str, *, last_only: bool = False) -> list[dict[str, str]]:
    return [json.loads(turn) for turn in r.lrange(key, -1 if last_only else 0, -1)]


def append_turn(key: str, question: str, answer: str) -> None:
    turn = json.dumps({"question": question, "answer": answer}, ensure_ascii=False)
    with r.pipeline() as transaction:
        transaction.rpush(key, turn)
        transaction.ltrim(key, -MAX_TURNS, -1)
        transaction.expire(key, SESSION_TTL_SECONDS)
        transaction.execute()
