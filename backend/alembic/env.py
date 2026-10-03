"""Окружение Alembic для асинхронного SQLAlchemy.

URL для подключения берётся из настроек приложения
(``app.core.config.settings.DATABASE_URL``), поэтому в ``alembic.ini``
не хранится ни одной учётной записи.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(
    obj: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object,
) -> bool:
    """Отфильтровать объекты, которые не нужно сравнивать при autogenerate.

    Args:
        obj: Объект метаданных.
        name: Имя объекта.
        type_: Тип объекта (table, column, index и т.д.).
        reflected: Присутствует ли объект в базе данных.
        compare_to: Соответствующий объект модели.

    Returns:
        ``True``, если объект следует учитывать при сравнении схем.
    """
    return True


def run_migrations_offline() -> None:
    """Выполнить миграции в offline-режиме (генерировать SQL без БД).

    Подключение к базе не устанавливается — используется только URL.
    """
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Выполнить миграции в переданном синхронном соединении.

    Args:
        connection: Синхронное соединение, полученное из асинхронного.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Создать асинхронный движок и выполнить миграции."""
    connectable = create_async_engine(settings.DATABASE_URL, poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Выполнить миграции в online-режиме (с подключением к БД)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
