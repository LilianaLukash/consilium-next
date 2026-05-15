from __future__ import annotations

from decimal import Decimal

from fastapi import Depends, HTTPException, Request, Response

from app.auth.context import ActorContext
from app.auth.guest import ensure_guest_cookie
from app.auth.security import decode_access_token
from app.config import settings
from app.security.network import is_local_client
from app.users_db import get_or_create_master_user, get_user_by_id


def _user_to_actor(user: dict) -> ActorContext:
    return ActorContext(
        user_id=user["id"],
        email=user.get("email"),
        role=user.get("role") or "user",
        balance_usd=Decimal(user.get("balance_usd") or "0"),
        is_master=user.get("role") == "master",
        is_guest=False,
        email_verified=bool(user.get("email_verified")),
    )


def _master_actor_if_allowed(request: Request) -> ActorContext | None:
    if not settings.master_mode_allowed:
        return None
    if not is_local_client(request):
        return None
    return _user_to_actor(get_or_create_master_user())


async def get_actor(request: Request, response: Response) -> ActorContext:
    master = _master_actor_if_allowed(request)
    if master is not None:
        return master

    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        payload = decode_access_token(token)
        if payload and payload.get("sub"):
            user = get_user_by_id(str(payload["sub"]))
            if user:
                actor = _user_to_actor(user)
                if payload.get("role") == "master" and actor.role != "master":
                    raise HTTPException(
                        status_code=401,
                        detail={"code": "INVALID_TOKEN", "message": "Недействительный токен"},
                    )
                return actor

    guest_id = ensure_guest_cookie(request, response)
    return ActorContext(
        guest_id=guest_id,
        is_guest=True,
        role="guest",
    )


async def require_registered_user(actor: ActorContext = Depends(get_actor)) -> ActorContext:
    if actor.bypass_limits:
        return actor
    if actor.is_authenticated:
        if not actor.email_verified and actor.role != "master":
            raise HTTPException(
                status_code=403,
                detail={"code": "EMAIL_NOT_VERIFIED", "message": "Подтвердите email"},
            )
        return actor
    raise HTTPException(
        status_code=401,
        detail={"code": "AUTH_REQUIRED", "message": "Требуется вход или регистрация"},
    )


def enforce_council_access(actor: ActorContext) -> None:
    if actor.bypass_limits:
        return
    if actor.is_authenticated:
        return
    if actor.is_guest and actor.guest_id:
        from app.auth.guest import assert_guest_may_run

        assert_guest_may_run(actor.guest_id)
        return
    raise HTTPException(status_code=401, detail={"code": "AUTH_REQUIRED"})
