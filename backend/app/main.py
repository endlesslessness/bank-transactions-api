"""Точка входа приложения Bank Transactions API."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.limiter import limiter
from app.core.redis import close_redis, init_redis
from app.db.session import engine

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def rate_limit_exceeded_handler(request: Request, exc: Exception) -> Response:
    """Сформировать ответ на превышение лимита запросов.

    Обработчик slowapi принимает ``RateLimitExceeded``, а Starlette
    ожидает обработчик на любое исключение, поэтому здесь тонкая
    обёртка. Она же добавляет к ответу 429 заголовки ``Retry-After``
    и ``X-RateLimit``, чтобы клиент знал, сколько ждать.

    Args:
        request: Запрос, превысивший лимит.
        exc: Исключение превышения лимита.

    Returns:
        Ответ 429 с заголовками rate limit.
    """
    if isinstance(exc, RateLimitExceeded):
        return _rate_limit_exceeded_handler(request, exc)
    return JSONResponse(
        status_code=429,
        content={"detail": "Превышен лимит запросов"},
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Управлять ресурсами приложения на протяжении его жизни.

    При старте проверяется связь с Redis, при остановке закрываются
    соединения с Redis и пул PostgreSQL.

    Args:
        app: Приложение FastAPI.

    Yields:
        ``None`` — управление передаётся приложению на время работы.
    """
    await init_redis()
    logger.info("Приложение %s запущено", settings.PROJECT_NAME)
    yield
    await close_redis()
    await engine.dispose()
    logger.info("Приложение остановлено")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)

app.state.limiter = limiter

# Без этого обработчика ответ 429 не содержит Retry-After и X-RateLimit,
# и клиент не понимает, сколько ждать до следующей попытки.
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["Служебные"])
async def health() -> dict[str, str]:
    """Проверить, что приложение отвечает.

    Returns:
        Строка со статусом ``ok``.
    """
    return {"status": "ok"}
