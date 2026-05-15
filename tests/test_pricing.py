from decimal import Decimal

from app.billing.pricing import compute_client_cost, compute_provider_cost
from app.config import settings


def test_markup_multiplier_default():
    provider = Decimal("1.000000")
    client = compute_client_cost(provider)
    assert client == Decimal("1.400000")


def test_provider_cost_from_tokens():
    cost = compute_provider_cost(
        prompt_tokens=1_000_000,
        completion_tokens=0,
        input_price_per_m=Decimal("2"),
        output_price_per_m=Decimal("3"),
    )
    assert cost == Decimal("2.000000")


def test_settings_markup_matches_constant():
    assert float(settings.billing_markup_multiplier) == 1.4
