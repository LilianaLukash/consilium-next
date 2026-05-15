from fastapi.testclient import TestClient

from app.database import create_session
from tests.conftest import auth_headers, register_verified_user


def test_session_detail_denies_other_user(client: TestClient):
    user_a, _ = register_verified_user(client, "a@example.com")
    user_b, _ = register_verified_user(client, "b@example.com")
    sid = create_session("test prompt for session", user_id=user_a["id"])

    from app.auth.security import create_access_token

    token_b = create_access_token(user_b["id"])
    res = client.get(f"/api/sessions/{sid}", headers=auth_headers(token_b))
    assert res.status_code == 403

    token_a = create_access_token(user_a["id"])
    ok = client.get(f"/api/sessions/{sid}", headers=auth_headers(token_a))
    assert ok.status_code == 200
