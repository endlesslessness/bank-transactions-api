"""Общие фикстуры тестов.

Тесты работают с отдельной базой ``bank_test`` и отдельной базой
Redis, чтобы не затрагивать данные разработки. Схема пересоздаётся
один раз за сессию, а после каждого теста все изменения
откатываются.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Переменные окружения выставляются до импорта приложения: pydantic-settings
# читает .env, но переменные окружения имеют приоритет.
os.environ["DATABASE_URL"] = "postgresql+asyncpg://bank:bank@db:5432/bank_test"
os.environ["REDIS_URL"] = "redis://redis:6379/1"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["DEBUG"] = "false"

from app.core.redis import close_redis, init_redis  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Account, User  # noqa: E402

TEST_DATABASE_URL = os.environ["DATABASE_URL"]

# NullPool обязателен: пул переиспользовал бы соединение из другого
# цикла событий, и asyncpg падал бы с ошибкой «attached to a
# different loop».
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    poolclass=NullPool,
    echo=False,
)
test_session_factory = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(scope="session", autouse=True)
def prepare_database() -> Iterator[None]:
    """Пересоздать схему в тестовой базе до запуска тестов.

    Схема готовится в собственном цикле событий через ``asyncio.run``:
    так она не делит цикл с тестами, каждый из которых работает в
    своём. Все таблицы удаляются и создаются заново, поэтому тесты не
    зависят от порядка запуска и от данных прошлых прогонов.
    """

    async def _create_schema() -> None:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(_create_schema())
    yield
    asyncio.run(test_engine.dispose())


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Выдать сессию базы, очищая таблицы после теста.

    Тесты коммитят данные по-настоящему, а не внутри откатываемой
    внешней транзакции. Так записи видны другим соединениям, что
    необходимо для проверки блокировок строк: переводы из
    параллельных задач обязаны видеть те же счета, что и тест.
    Изоляция обеспечивается очисткой таблиц после каждого теста.

    Yields:
        Сессия, привязанная к тестовой базе.
    """
    async with test_session_factory() as session:
        yield session

    async with test_engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE users, accounts, transactions RESTART IDENTITY CASCADE"),
        )


@pytest.fixture
def session_factory() -> Callable[[], AbstractAsyncContextManager[AsyncSession]]:
    """Вернуть фабрику сессий для тестов с несколькими соединениями.

    Обычные тесты пользуются фикстурой ``db_session``, но проверки
    блокировок строк выполняют запросы из параллельных задач, и каждой
    нужна собственная сессия: SQLAlchemy не допускает параллельного
    использования одной сессии.

    Returns:
        Фабрика асинхронных сессий.
    """
    return test_session_factory


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[Redis]:
    """Поднять клиент Redis на время теста.

    Отдельная фикстура нужна тестам, которые обращаются к Redis
    напрямую, минуя HTTP-клиент: например, проверке идемпотентности.

    Yields:
        Подключённый клиент Redis.
    """
    client = await init_redis()
    yield client
    await close_redis()


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession,
    redis_client: Redis,
) -> AsyncGenerator[AsyncClient, None]:
    """Выдать HTTP-клиент, подключённый к приложению.

    Приложение тестируется как ASGI-приложение: запросы идут без
    сети, а lifespan не запускается, поэтому Redis поднимается
    отдельно, а сессия базы подменяется на тестовую.

    Args:
        db_session: Сессия тестовой базы.
        redis_client: Подключённый клиент Redis.

    Yields:
        Клиент httpx с подменённой зависимостью сессии.
    """
    from app.core.limiter import limiter

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    # Ключ переопределения — тот же объект get_session, который стоит
    # в Depends() в api.deps, иначе подмена не сработает.
    app.dependency_overrides[get_session] = override_get_session

    # Лимиты запросов в тестах не проверяются: регистрация разрешена
    # 5 раз в минуту, а набор тестов создаёт больше пяти пользователей.
    limiter.enabled = False

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as http_client:
            yield http_client
    finally:
        limiter.enabled = True
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def user(db_session: AsyncSession) -> User:
    """Создать пользователя для тестов.

    Args:
        db_session: Сессия базы данных.

    Returns:
        Сохранённый пользователь с паролем ``Secret123``.
    """
    test_user = User(
        email="tester@example.com",
        username="tester",
        hashed_password=hash_password("Secret123"),
        full_name="Тестовый Пользователь",
    )
    db_session.add(test_user)
    await db_session.commit()
    await db_session.refresh(test_user)
    return test_user


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    """Создать второго пользователя для проверки изоляции данных.

    Args:
        db_session: Сессия базы данных.

    Returns:
        Сохранённый пользователь с паролем ``Secret123``.
    """
    test_user = User(
        email="other@example.com",
        username="other",
        hashed_password=hash_password("Secret123"),
    )
    db_session.add(test_user)
    await db_session.commit()
    await db_session.refresh(test_user)
    return test_user


@pytest_asyncio.fixture
async def account(db_session: AsyncSession, user: User) -> Account:
    """Создать счёт с балансом 1000 RUB.

    Args:
        db_session: Сессия базы данных.
        user: Владелец счёта.

    Returns:
        Сохранённый счёт.
    """
    test_account = Account(
        user_id=user.id,
        account_number="RU000000000000000001",
        balance=Decimal("1000.00"),
        currency="RUB",
    )
    db_session.add(test_account)
    await db_session.commit()
    await db_session.refresh(test_account)
    return test_account


@pytest_asyncio.fixture
async def second_account(db_session: AsyncSession, user: User) -> Account:
    """Создать второй счёт того же пользователя с балансом 200 RUB.

    Args:
        db_session: Сессия базы данных.
        user: Владелец счёта.

    Returns:
        Сохранённый счёт.
    """
    test_account = Account(
        user_id=user.id,
        account_number="RU000000000000000002",
        balance=Decimal("200.00"),
        currency="RUB",
    )
    db_session.add(test_account)
    await db_session.commit()
    await db_session.refresh(test_account)
    return test_account


@pytest.fixture
def auth_headers() -> Callable[[User, str | None], dict[str, str]]:
    """Собрать заголовок авторизации для пользователя.

    Returns:
        Функция, принимающая пользователя и необязательный готовый
            токен и возвращающая заголовки запроса.
    """

    def _build(user_obj: User, token: str | None = None) -> dict[str, str]:
        access = token if token is not None else create_access_token(str(user_obj.id))
        return {"Authorization": f"Bearer {access}"}

    return _build


@pytest.fixture
def idempotency_key() -> Callable[[], str]:
    """Выдать уникальный ключ идемпотентности для теста.

    Returns:
        Функция, возвращающая новый ключ при каждом вызове.
    """

    def _new() -> str:
        return str(uuid.uuid4())

    return _new
