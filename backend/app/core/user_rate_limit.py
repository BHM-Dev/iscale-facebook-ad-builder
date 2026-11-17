"""Per-user sliding-window limits for paid AI endpoints (2026-11-01 review, N6).

Keyed by user id, not IP: Joel and Abel can share an office IP, and a leaked
token is a per-user problem. In-memory is correct here — the backend runs one
uvicorn worker. Limits sit far above a person clicking and far below a script.
"""
import threading
import time
from collections import defaultdict, deque
from typing import Dict, Tuple

from fastapi import Depends, HTTPException

from app.core.deps import get_current_active_user
from app.models import User

_CALLS: Dict[Tuple[str, str], deque] = defaultdict(deque)
_LOCK = threading.Lock()  # sync deps run in the threadpool; two requests can race


def check(bucket: str, user_id: str, max_calls: int, window_seconds: int,
          message: str = "Too many AI requests in a short time — wait a few minutes and try again.") -> None:
    with _LOCK:
        now = time.monotonic()
        calls = _CALLS[(bucket, user_id)]
        while calls and now - calls[0] > window_seconds:
            calls.popleft()
        if len(calls) >= max_calls:
            raise HTTPException(429, message)
        calls.append(now)


def per_user_limit(bucket: str, max_calls: int, window_seconds: int, message: str | None = None):
    def _dep(current_user: User = Depends(get_current_active_user)) -> None:
        if message:
            check(bucket, str(current_user.id), max_calls, window_seconds, message)
        else:
            check(bucket, str(current_user.id), max_calls, window_seconds)
    return _dep


# 60 per 10 minutes per user, shared across the copy endpoints / the remix endpoints.
ai_copy_limit = per_user_limit("ai_copy", 60, 600)
ai_remix_limit = per_user_limit("ai_remix", 60, 600)
