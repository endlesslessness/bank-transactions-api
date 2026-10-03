"""Бизнес-логика банковских счетов.

Сервис работает только со счетами текущего пользователя: чужие счета
выглядят как отсутствующие, поэтому по ответу нельзя узнать,
существует ли счёт другого клиента.
"""

import logging
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.schemas.account import AccountBalance, AccountCreate
from app.services.exceptions import AccountNotFoundError

logger = logging.getLogger(__name__)

ACCOUNT_PREFIX = "RU"
"""Префикс номера счёта, чтобы он был узнаваем в выписке."""


def generate_account_number() -> str:
    """Сгенерировать уникальный номер счёта.

    Формат повторяет банковский: 5 цифр банка, 10 цифр счёта и
    3 цифры филиала. Случайная часть делает номер непредсказуемым,
    а уникальность дополнительно гарантирует ограничение в базе.

    Returns:
        Номер счёта из 18 цифр.
    """
    bank = secrets.randbelow(100_000)
    account = secrets.randbelow(10_000_000_000)
    branch = secrets.randbelow(1_000)
    return f"{ACCOUNT_PREFIX}{bank:05d}{account:010d}{branch:03d}"


async def create_account(
    session: AsyncSession,
    user_id: int,
    payload: AccountCreate,
) -> Account:
    """Создать счёт для пользователя.

    Args:
        session: Асинхронная сессия базы данных.
        user_id: Идентификатор владельца нового счёта.
        payload: Параметры создаваемого счёта.

    Returns:
        Созданный счёт.
    """
    account = Account(
        user_id=user_id,
        account_number=generate_account_number(),
        balance=payload.initial_balance,
        currency=payload.currency,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)

    logger.info(
        "Создан счёт id=%s number=%s для пользователя id=%s",
        account.id,
        account.account_number,
        user_id,
    )
    return account


async def list_accounts(
    session: AsyncSession,
    user_id: int,
) -> list[Account]:
    """Получить все счета пользователя.

    Сортировка по дате создания даёт стабильный порядок между
    запросами, иначе счета «прыгали» бы в выдаче.

    Args:
        session: Асинхронная сессия базы данных.
        user_id: Идентификатор владельца.

    Returns:
        Счета пользователя, от новых к старым.
    """
    result = await session.scalars(
        select(Account)
        .where(Account.user_id == user_id)
        .order_by(Account.created_at.desc(), Account.id.desc())
    )
    return list(result.all())


async def get_account(
    session: AsyncSession,
    user_id: int,
    account_id: int,
) -> Account:
    """Получить счёт пользователя по идентификатору.

    Args:
        session: Асинхронная сессия базы данных.
        user_id: Идентификатор владельца.
        account_id: Идентификатор счёта.

    Returns:
        Найденный счёт.

    Raises:
        AccountNotFoundError: Если счёт не найден или принадлежит другому
            пользователю.
    """
    account = await session.scalar(
        select(Account).where(
            Account.id == account_id,
            Account.user_id == user_id,
        )
    )
    if account is None:
        raise AccountNotFoundError("Счёт не найден")
    return account


async def get_balance(
    session: AsyncSession,
    user_id: int,
    account_id: int,
) -> AccountBalance:
    """Получить текущий баланс счёта.

    Args:
        session: Асинхронная сессия базы данных.
        user_id: Идентификатор владельца.
        account_id: Идентификатор счёта.

    Returns:
        Номер счёта, баланс и валюта.

    Raises:
        AccountNotFoundError: Если счёт не найден или принадлежит другому
            пользователю.
    """
    account = await get_account(session, user_id, account_id)
    return AccountBalance(
        account_id=account.id,
        account_number=account.account_number,
        balance=account.balance,
        currency=account.currency,
    )
