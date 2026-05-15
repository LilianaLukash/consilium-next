"""Simple in-memory rate limiting (per IP + route)."""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request

_lock = Lock()
_buckets: dict[str, list[float]] = defaultdict(list)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def rate_limit(request: Request, *, key: str, max_calls: int, window_seconds: int) -> None:
    ip = _client_ip(request)
    bucket_key = f"{key}:{ip}"
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        hits = [t for t in _buckets[bucket_key] if t > cutoff]
        if len(hits) >= max_calls:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "RATE_LIMITED",
                    "message": "Слишком много запросов. Подождите минуту.",
                },
            )
        hits.append(now)
        _buckets[bucket_key] = hits


def reset_rate_limits() -> None:
    """For tests only."""
    with _lock:
        _buckets.clear()
