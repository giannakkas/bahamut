from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── Core ──
    environment: str = "development"
    log_level: str = "INFO"
    app_name: str = "Bahamut.AI"
    api_version: str = "v1"

    # ── Database ──
    database_url: str = "postgresql+asyncpg://bahamut:bahamut_dev_2026@localhost:5432/bahamut"
    database_url_sync: str = "postgresql://bahamut:bahamut_dev_2026@localhost:5432/bahamut"

    # ── Redis ──
    redis_url: str = "redis://localhost:6379/0"

    # ── Auth ──
    jwt_secret: str = "dev-jwt-secret-change-in-production-2026"
    jwt_refresh_secret: str = "dev-refresh-secret-change-in-production"
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 7

    # ── External APIs ──
    anthropic_api_key: str = ""
    oanda_api_key: str = ""
    oanda_account_id: str = ""
    twelve_data_key: str = ""
    newsapi_key: str = ""
    fred_api_key: str = ""

    # ── Agent Configuration ──
    max_agent_timeout_seconds: int = 10
    signal_cycle_interval_seconds: int = 900  # 15 min
    max_slippage_bps: int = 50

    # ── CORS ──
    cors_origins: list[str] = ["http://localhost:3000"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
