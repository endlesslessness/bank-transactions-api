"""Бизнес-логика банковских переводов.

Здесь решаются две задачи, ради которых проект и существует:

* **Атомарность.** Средства списываются и зачисляются в одной
  транзакции базы, а счета предварительно блокируются через
  ``SELECT ... FOR UPDATE``. Без блокировки два параллельных
  перевода со счёта видели бы один и тот же баланс и оба прошли бы
  проверку, хотя суммарно денег на счёте не хватает.
* **Идемпотентность.** Повторный запрос с тем же заголовком
  ``Idempotency-Key`` не создаёт вторую транзакцию, а возвращает
  первую. Ключ хранится в Redis «с запасом времени», а сама
  транзакция остаётся в базе навсегда.
"""

import logging
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.models.account import Account
from app.models.transaction import Transaction, TransactionStatus
from app.schemas.transaction import TransactionCreate, TransactionList
from app.services.exceptions import (
    AccountInactiveError,
    AccountNotFoundError,
    CurrencyMismatchError,
    InsufficientFundsError,
    SameAccountTransferError,
    TransactionNotFoundError,
)

logger = logging.getLogger(__name__)

IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60
"""Сколько хранить ключ идемпотентности в Redis.

Ключ нужен, чтобы быстро отвечать на повтор. День — с запасом:
клиент обычно повторяет запрос из-за сетевого сбоя в первые минуты,
а уникальность в базе всё равно остаётся последним рубежом.
"""


def _idempotency_cache_key(user_id: int, idempotency_key: str) -> str:
    """Собрать ключ Redis для пары пользователь/ключ идемпотентности.

    Идентификатор пользователя входит в ключ, поэтому два разных
    клиента с одинаковым ключом не мешают друг другу.

    Args:
        user_id: Идентификатор пользователя.
        idempotency_key: Ключ идемпотентности из заголовка.

    Returns:
        Ключ для хранения в Redis.
    """
    return f"idempotency:{user_id}:{idempotency_key}"


async def _find_by_idempotency_key(
    session: AsyncSession,
    idempotency_key: str,
) -> Transaction | None:
    """Найти ранее созданную транзакцию по ключу идемпотентности.

    Ключ уникален в базе, поэтому искать по нему можно без
    ограничения по пользователю.

    Args:
        session: Асинхронная сессия базы данных.
        idempotency_key: Ключ идемпотентности.

    Returns:
        Найденная транзакция либо ``None``.
    """
    return await session.scalar(
        select(Transaction).where(Transaction.idempotency_key == idempotency_key)
    )


async def _lock_accounts(
    session: AsyncSession,
    from_account_id: int,
    to_account_id: int,
) -> tuple[Account, Account]:
    """Заблокировать оба счёта перевода и проверить их владельца.

    Счета блокируются в порядке возрастания идентификаторов: если
    два перевода идут навстречу друг другу и блокируют счета в
    разном порядке, они встанут в тупик друг на друга.

    Args:
        session: Асинхронная сессия базы данных.
        from_account_id: Счёт-отправитель.
        to_account_id: Счёт-получатель.

    Returns:
        Пара счетов: отправитель и получатель.

    Raises:
        AccountNotFoundError: Если хотя бы один счёт не найден или
            принадлежит другому пользователю.
    """
    # Сортировка по id задаёт единый порядок блокировки для всех
    # переводов и исключает взаимные блокировки.
    first_id, second_id = sorted((from_account_id, to_account_id))

    first = await session.scalar(
        select(Account).where(Account.id == first_id).with_for_update()
    )
    second = await session.scalar(
        select(Account).where(Account.id == second_id).with_for_update()
    )
    if first is None or second is None:
        raise AccountNotFoundError("Счёт не найден")

    by_id = {first.id: first, second.id: second}
    return by_id[from_account_id], by_id[to_account_id]


async def create_transfer(
    session: AsyncSession,
    user_id: int,
    payload: TransactionCreate,
    idempotency_key: str,
) -> tuple[Transaction, bool]:
    """Перевести средства между своими счетами.

    Args:
        session: Асинхронная сессия базы данных.
        user_id: Идентификатор владельца счёта-отправителя.
        payload: Параметры перевода.
        idempotency_key: Ключ идемпотентности из заголовка.

    Returns:
        Пара: созданная транзакция и признак ``True``, если она была
        создана этим вызовом, либо ``False``, если вернули ранее
        созданную транзакцию с тем же ключом.

    Raises:
        SameAccountTransferError: Если отправитель и получатель совпадают.
        AccountNotFoundError: Если счёт не найден или принадлежит другому
            пользователю. Перевод разрешён только между своими счетами.
        AccountInactiveError: Если какой-либо из счетов закрыт.
        CurrencyMismatchError: Если валюты счетов различаются.
        InsufficientFundsError: Если на счёте не хватает средств.
    """
    if payload.from_account_id == payload.to_account_id:
        raise SameAccountTransferError("Нельзя перевести средства на тот же счёт")

    # Повтор запроса с тем же ключом возвращает первую транзакцию.
    existing = await _find_by_idempotency_key(session, idempotency_key)
    if existing is not None:
        logger.info(
            "Повторный запрос с ключом %s: вернуна транзакция id=%s",
            idempotency_key,
            existing.id,
        )
        return existing, False

    from_account, to_account = await _lock_accounts(
        session,
        payload.from_account_id,
        payload.to_account_id,
    )

    # Перевод разрешён только между своими счетами: иначе любой
    # авторизованный клиент мог бы перебрать чужие счета по
    # идентификатору и узнать, какие из них существуют.
    if from_account.user_id != user_id or to_account.user_id != user_id:
        raise AccountNotFoundError("Счёт не найден")
    if not from_account.is_active or not to_account.is_active:
        raise AccountInactiveError("Счёт закрыт и не может участвовать в операциях")
    if from_account.currency != to_account.currency:
        raise CurrencyMismatchError(from_account.currency, to_account.currency)
    if from_account.balance < payload.amount:
        raise InsufficientFundsError(from_account.balance, payload.amount)

    from_account.balance -= payload.amount
    to_account.balance += payload.amount

    transaction = Transaction(
        from_account_id=from_account.id,
        to_account_id=to_account.id,
        amount=payload.amount,
        currency=from_account.currency,
        status=TransactionStatus.COMPLETED,
        description=payload.description,
        idempotency_key=idempotency_key,
        completed_at=datetime.now(UTC),
    )
    session.add(transaction)

    try:
        # Списание, зачисление и запись транзакции — одна
        # транзакция: при ошибке не сохранится ни одна из частей.
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Не удалось сохранить перевод %s", idempotency_key)
        raise

    await session.refresh(transaction)

    await _cache_idempotency_key(user_id, idempotency_key, transaction.id)
    logger.info(
        "Перевод создан id=%s счёт %s -> %s сумма=%s %s",
        transaction.id,
        from_account.account_number,
        to_account.account_number,
        payload.amount,
        from_account.currency,
    )
    return transaction, True


async def _cache_idempotency_key(
    user_id: int,
    idempotency_key: str,
    transaction_id: int,
) -> None:
    """Запомнить ключ идемпотентности в Redis.

    Ошибка записи не должна ломать перевод: транзакция уже
    сохранена в базе, а уникальность ключа там всё равно
    проверяется, поэтому Redis здесь только ускоритель.

    Args:
        user_id: Идентификатор пользователя.
        idempotency_key: Ключ идемпотентности.
        transaction_id: Идентификатор созданной транзакции.
    """
    redis: Redis = get_redis()
    try:
        await redis.set(
            _idempotency_cache_key(user_id, idempotency_key),
            transaction_id,
            ex=IDEMPOTENCY_TTL_SECONDS,
        )
    except Exception:  # noqa: BLE001 - потеря кэша не критична
        logger.warning(
            "Не удалось сохранить ключ идемпотентности %s в Redis",
            idempotency_key,
            exc_info=True,
        )


async def list_transactions(
    session: AsyncSession,
    user_id: int,
    page: int,
    size: int,
    account_id: int | None = None,
    status: TransactionStatus | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> TransactionList:
    """Получить историю операций пользователя.

    Показываются переводы, в которых пользователь участвует с любой
    стороны: и исходящие, и входящие.

    Args:
        session: Асинхронная сессия базы данных.
        user_id: Идентификатор пользователя.
        page: Номер страницы, начиная с 1.
        size: Размер страницы.
        account_id: Ограничить выборку операциями по конкретному счёту.
        status: Ограничить выборку по статусу.
        date_from: Включить операции начиная с указанного момента.
        date_to: Включить операции до указанного момента.

    Returns:
        Страница истории с общим количеством подходящих записей.
    """
    user_accounts = select(Account.id).where(Account.user_id == user_id)

    conditions = [
        or_(
            Transaction.from_account_id.in_(user_accounts),
            Transaction.to_account_id.in_(user_accounts),
        )
    ]

    if account_id is not None:
        conditions.append(
            or_(
                Transaction.from_account_id == account_id,
                Transaction.to_account_id == account_id,
            )
        )
    if status is not None:
        conditions.append(Transaction.status == status)
    if date_from is not None:
        conditions.append(Transaction.created_at >= date_from)
    if date_to is not None:
        conditions.append(Transaction.created_at <= date_to)

    total = await session.scalar(
        select(func.count()).select_from(Transaction).where(*conditions)
    )

    result = await session.scalars(
        select(Transaction)
        .where(*conditions)
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .limit(size)
        .offset((page - 1) * size)
    )
    items = list(result.all())

    return TransactionList(
        items=items,
        total=int(total or 0),
        page=page,
        size=size,
    )


async def get_transaction(
    session: AsyncSession,
    user_id: int,
    transaction_id: int,
) -> Transaction:
    """Получить одну транзакцию пользователя.

    Args:
        session: Асинхронная сессия базы данных.
        user_id: Идентификатор пользователя.
        transaction_id: Идентификатор транзакции.

    Returns:
        Найденная транзакция.

    Raises:
        TransactionNotFoundError: Если транзакция не найдена или не
            принадлежит пользователю.
    """
    user_accounts = select(Account.id).where(Account.user_id == user_id)
    transaction = await session.scalar(
        select(Transaction).where(
            Transaction.id == transaction_id,
            or_(
                Transaction.from_account_id.in_(user_accounts),
                Transaction.to_account_id.in_(user_accounts),
            ),
        )
    )
    if transaction is None:
        raise TransactionNotFoundError("Транзакция не найдена")
    return transaction
