from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth.security import create_access_token, create_refresh_token, hash_refresh_token
from app.auth.security import hash_password
from app.users_db import create_user, get_refresh_token, save_refresh_token
from tests.conftest import auth_headers, register_verified_user


def test_register_rejects_weak_password(client: TestClient):
    res = client.post(
        "/api/auth/register",
        json={"email": "weak@example.com", "password": "passwordonly"},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "WEAK_PASSWORD"


def test_register_and_login_flow(client: TestClient):
    res = client.post(
        "/api/auth/register",
        json={"email": "new@example.com", "password": "Welcome1"},
    )
    assert res.status_code == 200
    login = client.post(
        "/api/auth/login",
        json={"email": "new@example.com", "password": "Welcome1"},
    )
    assert login.status_code == 403
    assert login.json()["detail"]["code"] == "EMAIL_NOT_VERIFIED"


def test_login_after_verified_user(client: TestClient, verified_user):
    user = verified_user["user"]
    login = client.post(
        "/api/auth/login",
        json={"email": user["email"], "password": verified_user["password"]},
    )
    assert login.status_code == 200
    assert "access_token" in login.json()


def test_jwt_master_role_mismatch_rejected(client: TestClient, verified_user):
    user = verified_user["user"]
    forged = create_access_token(user["id"], role="master")
    res = client.get("/api/auth/me", headers=auth_headers(forged))
    assert res.status_code == 401


def test_reset_password_revokes_refresh_tokens(client: TestClient):
    from app.users_db import save_password_reset_token

    user = create_user(
        email="reset@example.com",
        password_hash=hash_password("Oldpass1"),
        email_verified=True,
    )
    raw_refresh, token_hash, exp = create_refresh_token(user["id"])
    save_refresh_token(user["id"], token_hash, exp)
    assert get_refresh_token(token_hash) is not None

    token = "reset-opaque-token"
    save_password_reset_token(
        user["id"],
        token,
        datetime.now(timezone.utc) + timedelta(hours=1),
    )
    res = client.post(
        "/api/auth/reset-password",
        json={"token": token, "password": "Newpass2"},
    )
    assert res.status_code == 200
    assert get_refresh_token(token_hash) is None

    login = client.post(
        "/api/auth/login",
        json={"email": "reset@example.com", "password": "Newpass2"},
    )
    assert login.status_code == 200
