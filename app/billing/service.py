from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException

from app.auth.context import ActorContext
from app.billing.pricing import compute_run_cost
from app.config import settings
from app.openrouter import ChatUsage
from app.users_db import deduct_balance, get_user_by_id, record_usage


class InsufficientBalanceError(Exception):
    pass


async def record_chat_usage(
    actor: ActorContext,
    *,
    session_id: str | None,
    model: str,
    usage: ChatUsage,
    label: str = "agent",
) -> tuple[Decimal, Decimal]:
    """Charge user for one model call. Master/guest skip deduction."""
    provider, client = await compute_run_cost(
        model,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
    )

    record_usage(
        user_id=actor.user_id,
        guest_id=actor.guest_id,
        session_id=session_id,
        model=model,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        provider_cost=provider,
        client_cost=client,
    )

    if actor.bypass_limits:
        return provider, client

    if actor.is_guest:
        return provider, client

    if not actor.user_id:
        return provider, client

    try:
        deduct_balance(actor.user_id, client, description=f"{label}: {model}", session_id=session_id)
    except ValueError as e:
        if str(e) == "INSUFFICIENT_BALANCE":
            raise InsufficientBalanceError() from e
        raise
    return provider, client


def ensure_can_start_council(actor: ActorContext) -> None:
    if actor.bypass_limits:
        return
    if actor.is_guest:
        return
    if not actor.user_id:
        return
    min_bal = Decimal(str(settings.min_balance_to_run_usd))
    if actor.balance_usd < min_bal:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "INSUFFICIENT_BALANCE",
                "message": f"Минимальный баланс для запуска: ${min_bal}",
                "balance_usd": str(actor.balance_usd),
            },
        )


def refresh_actor_balance(actor: ActorContext) -> ActorContext:
    if not actor.user_id:
        return actor
    user = get_user_by_id(actor.user_id)
    if user:
        actor.balance_usd = Decimal(user["balance_usd"])
    return actor
