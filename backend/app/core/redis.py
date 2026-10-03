"""Асинхронный клиент Redis и управление его жизненным циклом.

Redis отвечает за идемпотентность переводов и за хранение ответов
кэша, поэтому подключение создаётся один раз при старте приложения
и закрывается при остановке.
"""

import logging

from redis.asyncio import Redis, from_url

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client: Redis | None = None


def get_redis() -> Redis:
    """Вернуть общий клиент Redis.

    Returns:
        Клиент Redis, созданный при старте приложения.

    Raises:
        RuntimeError: Если клиент не инициализирован. Обращаться к
            Redis нужно только внутри lifespan — это гарантирует, что
            подключение живо и не создаётся на каждый запрос.
    """
    if _redis_client is None:
        raise RuntimeError("Redis не инициализирован: вызови init_redis()")
    return _redis_client


async def init_redis() -> Redis:
    """Создать клиент Redis и проверить связь с сервером.

    Returns:
        Инициализированный клиент Redis.
    """
    global _redis_client
    _redis_client = from_url(settings.REDIS_URL, encoding="utf-8")
    await _redis_client.ping()
    logger.info("Redis подключён: %s", settings.REDIS_URL)
    return _redis_client


async def close_redis() -> None:
    """Закрыть соединение с Redis.

    Ошибки закрытия подавляются: они не должны мешать штатному
    завершению приложения.
    """
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
            logger.info("Соединение с Redis закрыто")
        except Exception:  # noqa: BLE001 - ошибка закрытия не критична
            logger.warning("Не удалось закрыть соединение с Redis", exc_info=True)
        finally:
            _redis_client = None
