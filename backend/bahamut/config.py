from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
import os


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    environment: str = "development"
    log_level: str = "INFO"
    app_name: str = "Bahamut.AI"

    database_url: str = "postgresql://bahamut:bahamut_dev_2026@localhost:5432/bahamut"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "dev-jwt-secret-change-in-production-2026"
    jwt_refresh_secret: str = "dev-refresh-secret-change-in-production"
    jwt_access_expire_minutes: int = 1440
    jwt_refresh_expire_days: int = 7

    anthropic_api_key: str = ""
    oanda_api_key: str = ""
    oanda_account_id: str = ""
    twelve_data_key: str = ""
    newsapi_key: str = ""
    fred_api_key: str = ""

    max_agent_timeout_seconds: int = 10
    signal_cycle_interval_seconds: int = 900
    max_slippage_bps: int = 50

    cors_origins: list[str] = ["*"]
    port: int = 8000

    @property
    def database_url_async(self) -> str:
        url = self.database_url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @property
    def database_url_sync(self) -> str:
        url = self.database_url
        if url.startswith("postgresql+asyncpg://"):
            return url.replace("postgresql+asyncpg://", "postgresql://", 1)
        return url


@lru_cache()
def get_settings() -> Settings:
    s = Settings()
    # Force read from env if pydantic missed it
    if not s.twelve_data_key and os.environ.get("TWELVE_DATA_KEY"):
        object.__setattr__(s, 'twelve_data_key', os.environ["TWELVE_DATA_KEY"])
    if not s.anthropic_api_key and os.environ.get("ANTHROPIC_API_KEY"):
        object.__setattr__(s, 'anthropic_api_key', os.environ["ANTHROPIC_API_KEY"])
    return s
