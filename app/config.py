from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "consilium.db"


def resolved_db_path() -> Path:
    """Test override via CONSILIUM_DB_PATH env."""
    import os

    override = os.environ.get("CONSILIUM_DB_PATH", "").strip()
    if override:
        return Path(override)
    return DB_PATH


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openrouter_api_key: str = ""
    openrouter_app_name: str = "Consilium"
    openrouter_app_url: str = "http://localhost:8000"

    max_debate_rounds: int = 2
    max_tokens_per_agent: int = 1100
    max_tokens_diator: int = 1400
    max_tokens_visionary: int = 1200
    max_tokens_diator_debate: int = 550
    # None = не передаём max_tokens в API (лимит только у провайдера)
    max_tokens_synthesis: int | None = None
    synthesis_continuation_attempts: int = 3
    synthesis_timeout_seconds: float = 300.0
    agent_timeout_seconds: float = 180.0
    diator_timeout_seconds: float = 180.0
    early_stop_similarity: float = 0.85

    model_diator: str = "x-ai/grok-4.3"
    model_architect: str = "anthropic/claude-sonnet-4"
    model_critic: str = "anthropic/claude-sonnet-4"
    model_visionary: str = "nousresearch/hermes-4-70b"
    model_synthesis: str = "google/gemini-2.5-pro-preview"

    # Legacy alias (MODEL_OWL); MODEL_DIATOR takes priority when both set
    model_owl: str | None = None

    def resolved_diator_model(self) -> str:
        return self.model_owl or self.model_diator

    # Environment: development | staging | production
    environment: str = "development"
    # Master mode: ONLY when true AND not production (see auth.deps)
    master_mode: bool = False

    # JWT
    jwt_secret: str = "change-me-in-production-use-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_access_minutes: int = 30
    jwt_refresh_days: int = 30

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8001/api/auth/google/callback"

    # Email (optional SMTP; dev logs link to console)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = "noreply@consilium.local"
    app_public_url: str = "http://localhost:8001"

    # Billing
    billing_markup_multiplier: float = 1.4
    min_balance_to_run_usd: float = 0.05
    signup_bonus_usd: float = 2.0
    guest_free_runs: int = 1
    guest_cookie_name: str = "consilium_guest_id"
    guest_cookie_max_age_days: int = 365

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_currency: str = "usd"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")

    @property
    def master_mode_allowed(self) -> bool:
        return self.master_mode and not self.is_production


settings = Settings()
