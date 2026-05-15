from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: str, *, role: str = "user") -> str:
    exp = _now() + timedelta(minutes=settings.jwt_access_minutes)
    payload = {"sub": user_id, "role": role, "type": "access", "exp": exp}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: str) -> tuple[str, str, datetime]:
    raw = secrets.token_urlsafe(48)
    token_hash = hash_refresh_token(raw)
    exp = _now() + timedelta(days=settings.jwt_refresh_days)
    return raw, token_hash, exp


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def decode_access_token(token: str) -> dict | None:
    try:
        data = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if data.get("type") != "access":
            return None
        return data
    except jwt.PyJWTError:
        return None


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)
