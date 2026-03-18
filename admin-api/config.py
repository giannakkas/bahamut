import logging
from functools import lru_cache

from pydantic_settings import BaseSettings

logger = logging.getLogger("bahamut.config")

_DEFAULT_SECRET = "change-this-to-a-real-secret-key-at-least-32-chars"


class Settings(BaseSettings):
    jwt_secret: str = _DEFAULT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480
    jwt_refresh_expire_minutes: int = 10080  # 7 days

    admin_username: str = "admin"
    admin_password: str = "bahamut2026"

    cors_origins: str = "http://localhost:3000"

    database_url: str = "sqlite:///./bahamut.db"

    log_level: str = "INFO"

    # Set to false to disable /docs and /redoc in production
    enable_docs: bool = True

    host: str = "0.0.0.0"
    port: int = 8000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse comma-separated origins, strip whitespace and trailing slashes."""
        return [
            o.strip().rstrip("/")
            for o in self.cors_origins.split(",")
            if o.strip()
        ]

    def validate_for_production(self) -> None:
        """Log warnings for insecure defaults. Call at startup."""
        if self.jwt_secret == _DEFAULT_SECRET:
            logger.warning(
                "⚠️  JWT_SECRET is using the default value. "
                "Set a strong random secret via JWT_SECRET env var before production."
            )
        if self.admin_password == "bahamut2026":
            logger.warning(
                "⚠️  ADMIN_PASSWORD is using the default value. "
                "Set a strong password via ADMIN_PASSWORD env var before production."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
