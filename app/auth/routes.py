from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field

from app.auth.deps import get_actor, require_registered_user
from app.security.password_policy import validate_password_strength
from app.security.rate_limit import rate_limit
from app.auth.email_util import send_password_reset_email, send_verification_email
from app.auth.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    new_opaque_token,
    verify_password,
)
from app.config import settings
from app.users_db import (
    add_balance,
    consume_email_verification,
    consume_password_reset,
    create_user,
    get_user_by_email,
    get_user_by_google,
    get_user_by_id,
    guest_runs_started,
    revoke_all_refresh_tokens_for_user,
    revoke_refresh_token,
    save_email_verification_token,
    save_password_reset_token,
    save_refresh_token,
    get_refresh_token,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class RefreshBody(BaseModel):
    refresh_token: str


class VerifyEmailBody(BaseModel):
    token: str


class ForgotPasswordBody(BaseModel):
    email: EmailStr


class ResetPasswordBody(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)


def _tokens_response(user: dict) -> dict:
    access = create_access_token(user["id"], role=user.get("role") or "user")
    raw_refresh, token_hash, exp = create_refresh_token(user["id"])
    save_refresh_token(user["id"], token_hash, exp)
    return {
        "access_token": access,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "user": _public_user(user),
    }


def _public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user.get("email"),
        "role": user.get("role"),
        "email_verified": bool(user.get("email_verified")),
        "balance_usd": user.get("balance_usd"),
    }


@router.get("/me")
async def auth_me(actor=Depends(get_actor)):
    if actor.is_master:
        return {
            "mode": "master",
            "user": {
                "id": actor.user_id,
                "email": actor.email,
                "role": "master",
                "balance_usd": str(actor.balance_usd),
                "email_verified": True,
            },
            "guest_runs": None,
        }
    if actor.is_authenticated:
        user = get_user_by_id(actor.user_id or "")
        return {"mode": "user", "user": _public_user(user or {}), "guest_runs": None}
    return {
        "mode": "guest",
        "user": None,
        "guest_id": actor.guest_id,
        "guest_runs": guest_runs_started(actor.guest_id or ""),
        "guest_free_runs": settings.guest_free_runs,
    }


@router.post("/register")
async def register(body: RegisterBody, request: Request):
    rate_limit(request, key="auth_register", max_calls=8, window_seconds=60)
    validate_password_strength(body.password)
    if get_user_by_email(body.email):
        raise HTTPException(400, detail={"code": "EMAIL_EXISTS", "message": "Email уже зарегистрирован"})
    user = create_user(
        email=body.email,
        password_hash=hash_password(body.password),
        email_verified=False,
    )
    if settings.signup_bonus_usd > 0:
        from decimal import Decimal

        add_balance(
            user["id"],
            Decimal(str(settings.signup_bonus_usd)),
            tx_type="signup_bonus",
            description="Welcome bonus",
        )
        user = get_user_by_id(user["id"]) or user
    token = new_opaque_token()
    exp = datetime.now(timezone.utc) + timedelta(days=2)
    save_email_verification_token(user["id"], token, exp)
    send_verification_email(body.email, token)
    return {"message": "Проверьте почту для подтверждения", "user": _public_user(user)}


@router.post("/verify-email")
async def verify_email(body: VerifyEmailBody):
    uid = consume_email_verification(body.token)
    if not uid:
        raise HTTPException(400, detail={"code": "INVALID_TOKEN", "message": "Недействительный токен"})
    user = get_user_by_id(uid)
    return {"message": "Email подтверждён", "user": _public_user(user or {})}


@router.post("/login")
async def login(body: LoginBody, request: Request):
    rate_limit(request, key="auth_login", max_calls=12, window_seconds=60)
    user = get_user_by_email(body.email)
    if not user or not user.get("password_hash"):
        raise HTTPException(401, detail={"code": "INVALID_CREDENTIALS", "message": "Неверный email или пароль"})
    if not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, detail={"code": "INVALID_CREDENTIALS", "message": "Неверный email или пароль"})
    if not user.get("email_verified"):
        raise HTTPException(403, detail={"code": "EMAIL_NOT_VERIFIED", "message": "Подтвердите email"})
    return _tokens_response(user)


@router.post("/refresh")
async def refresh(body: RefreshBody):
    th = hash_refresh_token(body.refresh_token)
    row = get_refresh_token(th)
    if not row:
        raise HTTPException(401, detail={"code": "INVALID_REFRESH", "message": "Сессия истекла"})
    exp = datetime.fromisoformat(row["expires_at"])
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < datetime.now(timezone.utc):
        raise HTTPException(401, detail={"code": "INVALID_REFRESH", "message": "Сессия истекла"})
    user = get_user_by_id(row["user_id"])
    if not user:
        raise HTTPException(401, detail={"code": "INVALID_REFRESH"})
    revoke_refresh_token(th)
    return _tokens_response(user)


@router.post("/logout")
async def logout(body: RefreshBody):
    revoke_refresh_token(hash_refresh_token(body.refresh_token))
    return {"ok": True}


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordBody, request: Request):
    rate_limit(request, key="auth_forgot", max_calls=6, window_seconds=60)
    user = get_user_by_email(body.email)
    if user:
        token = new_opaque_token()
        exp = datetime.now(timezone.utc) + timedelta(hours=2)
        save_password_reset_token(user["id"], token, exp)
        send_password_reset_email(body.email, token)
    return {"message": "Если email зарегистрирован, отправили ссылку для сброса"}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordBody, request: Request):
    rate_limit(request, key="auth_reset", max_calls=8, window_seconds=60)
    validate_password_strength(body.password)
    uid = consume_password_reset(body.token)
    if not uid:
        raise HTTPException(400, detail={"code": "INVALID_TOKEN"})
    from app.database import get_conn, utc_now

    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (hash_password(body.password), utc_now(), uid),
        )
    revoke_all_refresh_tokens_for_user(uid)
    user = get_user_by_id(uid)
    return {"message": "Пароль обновлён", "user": _public_user(user or {})}


@router.get("/google/start")
async def google_start():
    if not settings.google_client_id:
        raise HTTPException(503, detail="Google OAuth не настроен")
    from urllib.parse import urlencode

    params = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@router.get("/google/callback")
async def google_callback(code: str = Query(...)):
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(503, detail="Google OAuth не настроен")
    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_res.raise_for_status()
        tokens = token_res.json()
        access = tokens.get("access_token")
        if not access:
            raise HTTPException(400, "No access_token from Google")
        ui_res = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access}"},
        )
        ui_res.raise_for_status()
        info = ui_res.json()
    google_id = info.get("id")
    email = info.get("email")
    if not google_id or not email:
        raise HTTPException(400, "Google profile incomplete")
    user = get_user_by_google(google_id) or get_user_by_email(email)
    if not user:
        user = create_user(email=email, google_id=google_id, email_verified=True)
        if settings.signup_bonus_usd > 0:
            from decimal import Decimal

            add_balance(
                user["id"],
                Decimal(str(settings.signup_bonus_usd)),
                tx_type="signup_bonus",
                description="Welcome bonus",
            )
            user = get_user_by_id(user["id"]) or user
    tokens_out = _tokens_response(user)
    from urllib.parse import urlencode

    q = urlencode(
        {
            "access_token": tokens_out["access_token"],
            "refresh_token": tokens_out["refresh_token"],
        }
    )
    return RedirectResponse(f"{settings.app_public_url.rstrip('/')}/auth.html?{q}")
