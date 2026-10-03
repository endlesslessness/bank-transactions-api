"""Асинхронный движок SQLAlchemy и фабрика сессий.

Движок создаётся один раз на уровне модуля и переиспользуется всеми
запросами: так пул соединений не пересоздаётся на каждый запрос.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Выдать асинхронную сессию базы данных.

    Сессия закрывается при выходе из контекста, а соединение
    возвращается в пул. Откат данных на себя берут сервисы: они
    явно управляют границами транзакций.

    Yields:
        Асинхронная сессия SQLAlchemy.
    """
    async with session_factory() as session:
        yield session
