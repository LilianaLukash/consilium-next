from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth.deps import get_actor, require_registered_user
from app.auth.context import ActorContext
from app.config import settings
from app.users_db import list_balance_transactions, list_usage_logs

router = APIRouter(prefix="/api/billing", tags=["billing"])


class TopUpBody(BaseModel):
    amount_usd: float = Field(gt=0, le=500)


@router.get("/balance")
async def get_balance(actor: ActorContext = Depends(get_actor)):
    if actor.bypass_limits:
        return {"balance_usd": str(actor.balance_usd), "unlimited": True}
    if actor.is_authenticated:
        return {"balance_usd": str(actor.balance_usd), "unlimited": False}
    return {"balance_usd": "0", "unlimited": False, "guest": True}


@router.get("/usage")
async def get_usage(actor: ActorContext = Depends(require_registered_user), limit: int = 50):
    logs = list_usage_logs(actor.user_id or "", limit=limit)
    return {"usage": logs}


@router.get("/transactions")
async def get_transactions(actor: ActorContext = Depends(require_registered_user), limit: int = 50):
    txs = list_balance_transactions(actor.user_id or "", limit=limit)
    return {"transactions": txs}


@router.post("/stripe/checkout")
async def stripe_checkout(body: TopUpBody, actor: ActorContext = Depends(require_registered_user)):
    if not settings.stripe_secret_key:
        raise HTTPException(503, detail="Stripe не настроен")
    import stripe

    stripe.api_key = settings.stripe_secret_key
    amount_cents = int(round(body.amount_usd * 100))
    session = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[
            {
                "price_data": {
                    "currency": settings.stripe_currency,
                    "product_data": {"name": "Consilium balance top-up"},
                    "unit_amount": amount_cents,
                },
                "quantity": 1,
            }
        ],
        metadata={"user_id": actor.user_id or ""},
        success_url=f"{settings.app_public_url.rstrip('/')}/?payment=success",
        cancel_url=f"{settings.app_public_url.rstrip('/')}/?payment=cancel",
    )
    return {"checkout_url": session.url, "session_id": session.id}


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    if not settings.stripe_webhook_secret:
        raise HTTPException(503, detail="Webhook secret not configured")
    import stripe

    stripe.api_key = settings.stripe_secret_key
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, settings.stripe_webhook_secret)
    except Exception as e:
        raise HTTPException(400, detail=str(e)) from e

    if event["type"] == "checkout.session.completed":
        sess = event["data"]["object"]
        user_id = (sess.get("metadata") or {}).get("user_id")
        amount_total = sess.get("amount_total") or 0
        session_id = sess.get("id")
        if user_id and amount_total and session_id:
            amount_usd = Decimal(str(amount_total)) / Decimal("100")
            from app.users_db import add_balance, stripe_topup_exists

            if not stripe_topup_exists(session_id):
                add_balance(
                    user_id,
                    amount_usd,
                    tx_type="stripe_topup",
                    description="Stripe top-up",
                    stripe_session_id=session_id,
                )
    return {"received": True}
