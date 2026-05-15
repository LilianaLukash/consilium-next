from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.billing.service import ensure_can_start_council
from app.auth.context import ActorContext
from app.security.bootstrap import validate_settings
from fastapi import HTTPException
from app.users_db import add_balance, create_user


def test_production_rejects_master_mode(monkeypatch):
    import app.config as config

    monkeypatch.setattr(config.settings, "environment", "production")
    monkeypatch.setattr(config.settings, "master_mode", True)
    monkeypatch.setattr(config.settings, "jwt_secret", "x" * 40)
    monkeypatch.setattr(config.settings, "openrouter_api_key", "sk-test")
    with pytest.raises(RuntimeError, match="MASTER_MODE"):
        validate_settings()


def test_insufficient_balance_blocks_council():
    actor = ActorContext(
        user_id="u1",
        balance_usd=Decimal("0.01"),
        is_guest=False,
        role="user",
        email_verified=True,
    )
    with pytest.raises(HTTPException) as exc:
        ensure_can_start_council(actor)
    assert exc.value.status_code == 402


def test_stripe_topup_idempotent():
    user = create_user(email="pay@example.com", email_verified=True)
    amount = Decimal("5.00")
    sid = "cs_test_session_123"
    b1 = add_balance(user["id"], amount, tx_type="stripe_topup", description="t", stripe_session_id=sid)
    b2 = add_balance(user["id"], amount, tx_type="stripe_topup", description="t", stripe_session_id=sid)
    assert b1 == b2


def test_security_headers_on_health(client: TestClient):
    res = client.get("/api/health")
    assert res.headers.get("x-content-type-options") == "nosniff"
    assert res.headers.get("x-frame-options") == "DENY"
