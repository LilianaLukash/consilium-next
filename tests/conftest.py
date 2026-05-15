from __future__ import annotations

import os
import sqlite3
import tempfile
from decimal import Decimal

import pytest

_TEST_DB = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
os.environ.setdefault("CONSILIUM_DB_PATH", _TEST_DB.name)
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("MASTER_MODE", "false")
os.environ.setdefault(
    "JWT_SECRET",
    "test-jwt-secret-must-be-at-least-thirty-two-chars",
)
os.environ.setdefault("OPENROUTER_API_KEY", "")

_CLEAR_TABLES = (
    "refresh_tokens",
    "email_verification_tokens",
    "password_reset_tokens",
    "usage_logs",
    "balance_transactions",
    "guest_profiles",
    "messages",
    "verdicts",
    "user_comments",
    "attachments",
    "sessions",
    "users",
)


def _wipe_db() -> None:
    from app.database import get_conn, init_db

    init_db()
    with get_conn() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in _CLEAR_TABLES:
            try:
                conn.execute(f"DELETE FROM {table}")
            except sqlite3.OperationalError:
                pass
        conn.execute("PRAGMA foreign_keys = ON")


@pytest.fixture(scope="session", autouse=True)
def _init_test_db():
    _wipe_db()
    yield


@pytest.fixture(autouse=True)
def clean_db():
    _wipe_db()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def register_verified_user(client, email: str = "user@example.com", password: str = "Secret1a"):
    from app.auth.security import hash_password
    from app.users_db import create_user

    user = create_user(
        email=email,
        password_hash=hash_password(password),
        email_verified=True,
        balance_usd=Decimal("10.00"),
    )
    return user, password


def auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def verified_user(client):
    user, password = register_verified_user(client)
    from app.auth.security import create_access_token

    token = create_access_token(user["id"], role=user.get("role") or "user")
    return {"user": user, "password": password, "token": token}
