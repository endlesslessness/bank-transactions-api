"""Точка входа приложения Bank Transactions API."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
