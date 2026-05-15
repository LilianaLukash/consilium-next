"""Startup security checks for production."""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger("consilium.security")

WEAK_JWT_SECRETS = frozenset(
    {
        "change-me-in-production-use-long-random-string",
        "dev-change-me-use-openssl-rand-hex-32",
        "secret",
        "jwt-secret",
    }
)


def validate_settings() -> None:
    errors: list[str] = []

    if settings.is_production:
        if settings.master_mode:
            errors.append("MASTER_MODE must be false when ENVIRONMENT=production")
        if len(settings.jwt_secret) < 32:
            errors.append("JWT_SECRET must be at least 32 characters in production")
        if settings.jwt_secret.lower() in WEAK_JWT_SECRETS:
            errors.append("JWT_SECRET is a known weak/default value")
        if not settings.openrouter_api_key:
            errors.append("OPENROUTER_API_KEY is required in production")
        if settings.stripe_secret_key and not settings.stripe_webhook_secret:
            errors.append("STRIPE_WEBHOOK_SECRET required when Stripe is enabled")

    if settings.master_mode and not settings.is_production:
        logger.warning(
            "MASTER_MODE is ON (development only). Disabled for non-local clients."
        )

    if errors:
        raise RuntimeError("Security configuration failed:\n- " + "\n- ".join(errors))
