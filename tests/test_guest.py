from fastapi.testclient import TestClient

from app.auth.guest import assert_guest_may_run, register_guest_run_start
from app.config import settings
from fastapi import HTTPException
import pytest


def test_guest_free_run_then_blocked():
    gid = "guest-test-uuid"
    assert_guest_may_run(gid)
    register_guest_run_start(gid)
    with pytest.raises(HTTPException) as exc:
        assert_guest_may_run(gid)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "AUTH_REQUIRED"


def test_auth_me_guest(client: TestClient):
    res = client.get("/api/auth/me")
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "guest"
    assert data["guest_free_runs"] == settings.guest_free_runs
