from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache


class Settings(BaseSettings):
    APP_NAME: str = "hf-market-engine"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "dev-secret-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    ALGORITHM: str = "HS256"

    # Comma-separated list of allowed CORS origins, e.g.
    # https://app.example.com,https://staging.example.com
    # "*" is only accepted while ENVIRONMENT != production.
    CORS_ORIGINS: str = ""

    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB: str = "hf_market_engine"

    COINGECKO_API_KEY: str = ""
    POLYGON_API_KEY: str = ""
    ALPACA_API_KEY: str = ""
    ALPACA_SECRET_KEY: str = ""
    TWELVE_DATA_API_KEY: str = ""
    FINNHUB_API_KEY: str = ""

    OPENAI_API_KEY: str = ""
    GROK_API_KEY: str = ""

    REDIS_URL: str = "redis://localhost:6379"

    PLAN_PRO_PRICE: int = 59
    PLAN_ADVANCED_PRICE: int = 199
    PLAN_TEAM_PRICE: int = 699
    PLAN_WHITELABEL_SETUP: int = 5000
    PLAN_WHITELABEL_MONTHLY: int = 1499

    # Stripe — use sk_test_... + test price IDs for Test mode
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
        if not self.SECRET_KEY or len(self.SECRET_KEY) < 32:
            raise ValueError(
                "SECRET_KEY must be a strong random value (>= 32 chars) in production"
            )
        if not self.MONGODB_URL.startswith("mongodb://") or "mongodb://mongo:27017" in self.MONGODB_URL:
            raise ValueError(
                "MONGODB_URL must point at the mongo service with authenticated app "
                "credentials (user:pass@mongo:27017) in production"
            )
        if not self.cors_origin_list:
            raise ValueError("CORS_ORIGINS must be set to your real origin(s) in production")
        if "*" in self.cors_origin_list:
            raise ValueError("CORS_ORIGINS may not contain '*' in production")
        return self

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
