"""Конфигурация приложения, загружаемая из переменных окружения и файла .env."""

from pathlib import Path
from typing import Annotated, Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _split_csv(value: Any) -> Any:
    """Разбить строку с элементами через запятую на список.

    Переменные окружения не умеют хранить списки, поэтому
    ``CORS_ORIGINS`` задаётся строкой ``a,b,c``. Без ``NoDecode``
    pydantic-settings попытался бы разобрать её как JSON и упал бы с
    ошибкой, поэтому декодирование отключено, а разбор делает этот
    валидатор.

    Args:
        value: Значение из переменной окружения.

    Returns:
        Список строк либо исходное значение, если это не строка.
    """
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    """Настройки приложения Bank Transactions API.

    Attributes:
        ENVIRONMENT: Режим работы приложения (development/production).
        DEBUG: Признак расширенной диагностики.
        DATABASE_URL: Асинхронный DSN подключения к PostgreSQL.
        REDIS_URL: URL подключения к Redis.
        SECRET_KEY: Секрет, используемый для подписи JWT.
        ALGORITHM: Алгоритм подписи JWT.
        ACCESS_TOKEN_EXPIRE_MINUTES: Срок жизни access-токена в минутах.
        REFRESH_TOKEN_EXPIRE_DAYS: Срок жизни refresh-токена в днях.
        CORS_ORIGINS: Список origins, которым разрешён доступ к API.
        RATE_LIMIT: Лимит запросов в формате slowapi (``100/minute``).
        PROJECT_NAME: Название проекта.
        VERSION: Версия приложения.
    """

    model_config = SettingsConfigDict(
        env_file=_BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    CORS_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost"]
    RATE_LIMIT: str = "100/minute"
    PROJECT_NAME: str = "Bank Transactions API"
    VERSION: str = "1.0.0"

    _parse_cors = field_validator("CORS_ORIGINS", mode="before")(_split_csv)


settings = Settings()
