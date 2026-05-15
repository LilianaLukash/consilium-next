from __future__ import annotations

import uuid

from fastapi import HTTPException, Request, Response

from app.config import settings
from app.users_db import guest_runs_started, increment_guest_runs


def ensure_guest_cookie(request: Request, response: Response) -> str:
    name = settings.guest_cookie_name
    gid = request.cookies.get(name)
    if not gid:
        gid = str(uuid.uuid4())
        response.set_cookie(
            key=name,
            value=gid,
            max_age=settings.guest_cookie_max_age_days * 86400,
            httponly=True,
            samesite="lax",
            secure=settings.is_production,
        )
    return gid


def assert_guest_may_run(guest_id: str) -> None:
    """First run free; from second run onward require registration."""
    if guest_runs_started(guest_id) >= settings.guest_free_runs:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "AUTH_REQUIRED",
                "message": "Бесплатная проба использована. Войдите или зарегистрируйтесь.",
                "guest_runs": guest_runs_started(guest_id),
            },
        )


def register_guest_run_start(guest_id: str) -> int:
    return increment_guest_runs(guest_id)
