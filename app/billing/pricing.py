from __future__ import annotations

from decimal import Decimal

from app.config import settings
from app.model_registry import ModelInfo, fetch_models

MARKUP = Decimal("1.40")  # +40% к OpenRouter


def _dec(val: float | str | None) -> Decimal:
    if val is None:
        return Decimal("0")
    return Decimal(str(val))


async def get_model_pricing(model_id: str) -> tuple[Decimal, Decimal]:
    """USD per 1M tokens: (input, output)."""
    models = await fetch_models()
    by_id = {m.id: m for m in models}
    m = by_id.get(model_id)
    if m:
        return _dec(m.input_price_per_m), _dec(m.output_price_per_m)
    return Decimal("1.0"), Decimal("3.0")


def compute_provider_cost(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    input_price_per_m: Decimal,
    output_price_per_m: Decimal,
) -> Decimal:
    inp = _dec(prompt_tokens) * input_price_per_m / Decimal("1000000")
    out = _dec(completion_tokens) * output_price_per_m / Decimal("1000000")
    return (inp + out).quantize(Decimal("0.000001"))


def compute_client_cost(provider_cost: Decimal) -> Decimal:
    markup = _dec(settings.billing_markup_multiplier)
    return (provider_cost * markup).quantize(Decimal("0.000001"))


async def compute_run_cost(
    model_id: str,
    *,
    prompt_tokens: int,
    completion_tokens: int,
) -> tuple[Decimal, Decimal]:
    inp_p, out_p = await get_model_pricing(model_id)
    provider = compute_provider_cost(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        input_price_per_m=inp_p,
        output_price_per_m=out_p,
    )
    client = compute_client_cost(provider)
    return provider, client
