from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "hf-market-engine"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "dev-secret-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    ALGORITHM: str = "HS256"

    # Comma-separated list of allowed CORS origins.
    CORS_ORIGINS: str = ""

    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB: str = "hf_market_engine"

    COINGECKO_API_KEY: str = ""
    POLYGON_API_KEY: str = ""
    ALPACA_API_KEY: str = ""
    ALPACA_SECRET_KEY: str = ""
    TWELVE_DATA_API_KEY: str = ""
    FINNHUB_API_KEY: str = ""

    # Market data honesty contract:
    # demo -> labeled demo only; live -> real providers only, missing stays missing.
    MARKET_DATA_MODE: str = "demo"

# Execution impact model:
    #   "sqrt_law_v1" -> deterministic square-root law (default, honest)
    #   "none"        -> impact fields are null, no fabricated numbers
    #   "legacy_random" -> old random.uniform() behavior (debugging only)
    IMPACT_MODEL: str = "sqrt_law_v1"

    # Archisynapse v1.1 — Ed25519 receipt signing key (hex).
    # Empty in dev = ephemeral key (receipts unverifiable across restarts).
    # REQUIRED in production: receipts without a stable key are worthless
    # as evidence, since the public key changes on every deploy.
    # Generate with:
    #   python -c "from app.core.archisynapse.crypto import generate_signing_key_hex; print(generate_signing_key_hex())"
    ARCHISYNAPSE_SIGNING_KEY: str = ""

    # Capital V2 infrastructure feeds. These are canonical JSON feed endpoints;
    # no feed configured means the corresponding lane remains reference/user
    # assumption data rather than fake live data.
    HARDWARE_OFFERS_URL: str = ""
    HARDWARE_PROVIDER_ID: str = "hardware_feed"
    GPU_OFFERS_URL: str = ""
    GPU_PROVIDER_ID: str = "gpu_feed"
    ENERGY_PRICES_URL: str = ""
    ENERGY_PROVIDER_ID: str = "energy_feed"
    INFRA_PROVIDER_BEARER_TOKEN: str = ""
    INFRA_PROVIDER_TIMEOUT: float = 10.0

    OPENAI_API_KEY: str = ""
    GROK_API_KEY: str = ""

    AI_MODEL: str = ""
    AI_MAX_TOKENS: int = 200
    AI_TEMPERATURE: float = 0.4
    AI_TIMEOUT: float = 20.0
    AI_CACHE_TTL: int = 900

    # ── AI spend enforcement (HARNESS.md §4 kill conditions) ──────────────
    # Hard caps on estimated AI token spend. When a cap is hit, further AI
    # calls return the rule-based fallback instead of billing an API call.
    # This is enforcement, not observability: the loop actually stops.
    # Set to 0.0 to disable a specific cap (not recommended in production).
    AI_BUDGET_USER_DAILY_USD: float = 2.00      # per user, rolling 24h
    AI_BUDGET_GLOBAL_DAILY_USD: float = 50.00   # all users, rolling 24h
    AI_BUDGET_ENFORCE: bool = True              # False = log only, do not block

    # ── Alerting (HARNESS.md §5) ──────────────────────────────────────────
    # Webhook fired on governance events: budget exceeded, receipt write
    # failure, signature verification failure. Slack-compatible payload.
    # Empty = log-only (still recorded, just not pushed anywhere).
    ALERT_WEBHOOK_URL: str = ""
    ALERT_MIN_INTERVAL_SECONDS: int = 300  # dedupe window per alert type

    REDIS_URL: str = "redis://localhost:6379"

    PLAN_PRO_PRICE: int = 59
    PLAN_ADVANCED_PRICE: int = 199
    PLAN_TEAM_PRICE: int = 699
    PLAN_WHITELABEL_SETUP: int = 5000
    PLAN_WHITELABEL_MONTHLY: int = 1499

    # Stripe — use sk_test_... + test price IDs for Test mode.
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_PRO: str = ""
    STRIPE_PRICE_ADVANCED: str = ""
    STRIPE_PRICE_TEAM: str = ""
    STRIPE_PRICE_WHITELABEL: str = ""
    STRIPE_SUCCESS_URL: str = "http://localhost:5173/pricing?upgraded=1"
    STRIPE_CANCEL_URL: str = "http://localhost:5173/pricing?canceled=1"

    @property
    def cors_origin_list(self) -> list[str]:
        if not self.CORS_ORIGINS:
            return []
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @model_validator(mode="after")
    def _validate_production(self) -> "Settings":
        if self.ENVIRONMENT.lower() != "production":
            return self

        secret_lower = (self.SECRET_KEY or "").lower()
        if (
            not self.SECRET_KEY
            or len(self.SECRET_KEY) < 32
            or "change-me" in secret_lower
            or "dev-secret" in secret_lower
            or "replace-me" in secret_lower
        ):
            raise ValueError(
                "SECRET_KEY must be a real random value (>= 32 chars); example/dev placeholders are rejected in production"
            )

        mongo_lower = (self.MONGODB_URL or "").lower()
        if (
            not self.MONGODB_URL.startswith("mongodb://")
            or "mongodb://mongo:27017" in self.MONGODB_URL
            or "change-me" in mongo_lower
            or "replace-me" in mongo_lower
        ):
            raise ValueError(
                "MONGODB_URL must contain real authenticated app credentials in production; placeholder credentials are rejected"
            )

        if not self.cors_origin_list:
            raise ValueError("CORS_ORIGINS must be set to your real origin(s) in production")
        if "*" in self.cors_origin_list:
            raise ValueError("CORS_ORIGINS may not contain '*' in production")
        if not self.ARCHISYNAPSE_SIGNING_KEY:
            raise ValueError(
                "ARCHISYNAPSE_SIGNING_KEY must be set in production. Without a "
                "stable signing key, receipts are signed with an ephemeral key "
                "that changes on every restart, making historical receipts "
                "unverifiable. No receipt = no evidence."
            )
        if len(self.ARCHISYNAPSE_SIGNING_KEY) != 64:
            raise ValueError(
                "ARCHISYNAPSE_SIGNING_KEY must be a 64-character hex string "
                "(32-byte Ed25519 private key)."
            )

        if any("example.com" in origin.lower() for origin in self.cors_origin_list):
            raise ValueError("CORS_ORIGINS still contains an example.com placeholder")

        if self.INFRA_PROVIDER_TIMEOUT <= 0 or self.INFRA_PROVIDER_TIMEOUT > 60:
            raise ValueError("INFRA_PROVIDER_TIMEOUT must be > 0 and <= 60 seconds")
        return self

    @model_validator(mode="after")
    def _validate_market_data_mode(self) -> "Settings":
        if self.MARKET_DATA_MODE not in ("demo", "live"):
            raise ValueError("MARKET_DATA_MODE must be 'demo' or 'live'")
        return self

    @model_validator(mode="after")
    def _validate_impact_model(self) -> "Settings":
        valid = {"sqrt_law_v1", "none", "legacy_random"}
        if self.IMPACT_MODEL not in valid:
            raise ValueError(f"IMPACT_MODEL must be one of {valid}, got '{self.IMPACT_MODEL}'")
        if self.ENVIRONMENT.lower() == "production" and self.IMPACT_MODEL == "legacy_random":
            raise ValueError(
                "IMPACT_MODEL=legacy_random is not allowed in production. "
                "It reports fabricated random figures as execution costs. "
                "Use 'sqrt_law_v1' or 'none' instead."
            )
        return self

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
