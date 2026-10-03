"""Конфигурация приложения, загружаемая из переменных окружения и файла .env."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Настройки приложения Bank Transactions API.

    Attributes:
        DATABASE_URL: Асинхронный DSN подключения к PostgreSQL.
        REDIS_URL: URL подключения к Redis.
        SECRET_KEY: Секрет, используемый для подписи JWT.
        ALGORITHM: Алгоритм подписи JWT.
        ACCESS_TOKEN_EXPIRE_MINUTES: Срок жизни access-токена в минутах.
        REFRESH_TOKEN_EXPIRE_DAYS: Срок жизни refresh-токена в днях.
        PROJECT_NAME: Название проекта.
        VERSION: Версия приложения.
    """

    model_config = SettingsConfigDict(
        env_file=_BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    PROJECT_NAME: str = "Bank Transactions API"
    VERSION: str = "1.0.0"


settings = Settings()
