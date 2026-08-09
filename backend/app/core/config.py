from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    APP_NAME: str = "hf-market-engine"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "dev-secret-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24h
    ALGORITHM: str = "HS256"

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

    # Pricing (display only – billing layer ready)
    PLAN_PRO_PRICE: int = 59
    PLAN_ADVANCED_PRICE: int = 199
    PLAN_TEAM_PRICE: int = 699
    PLAN_WHITELABEL_SETUP: int = 5000
    PLAN_WHITELABEL_MONTHLY: int = 1499

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
