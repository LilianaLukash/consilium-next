"""Local-only checks for dev master mode."""

from __future__ import annotations

from starlette.requests import Request

_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def is_local_client(request: Request) -> bool:
    if request.client is None:
        return False
    host = (request.client.host or "").lower()
    if host in _LOCAL_HOSTS:
        return True
    if host.startswith("127."):
        return True
    return False
