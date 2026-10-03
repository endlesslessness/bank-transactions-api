"""Тесты банковских переводов, идемпотентности и атомарности."""

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from decimal import Decimal

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.transaction import TransactionCreate
from app.services import transaction as transaction_service
from app.services.exceptions import DomainError

TRANSACTIONS_URL = "/api/v1/transactions"

AuthHeaders = Callable[[User, str | None], dict[str, str]]
KeyFactory = Callable[[], str]


async def test_create_transfer_moves_money(
    client: AsyncClient,
    user: User,
    account: Account,
    second_account: Account,
    db_session: AsyncSession,
    auth_headers: AuthHeaders,
    idempotency_key: KeyFactory,
) -> None:
    """Успешный перевод списывает и зачисляет сумму."""
    response = await client.post(
        TRANSACTIONS_URL,
        headers={**auth_headers(user), "Idempotency-Key": idempotency_key()},
        json={
            "from_account_id": account.id,
            "to_account_id": second_account.id,
            "amount": "300.00",
            "description": "Оплата услуг",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["amount"] == "300.00"
    assert body["status"] == "completed"
    assert body["currency"] == "RUB"
    assert body["description"] == "Оплата услуг"
    assert body["completed_at"] is not None

    await db_session.refresh(account)
    await db_session.refresh(second_account)
    assert account.balance == Decimal("700.00")
    assert second_account.balance == Decimal("500.00")


async def test_same_idempotency_key_does_not_debit_twice(
    client: AsyncClient,
    user: User,
    account: Account,
    second_account: Account,
    db_session: AsyncSession,
    auth_headers: AuthHeaders,
) -> None:
    """Повтор с тем же ключом возвращает первую транзакцию.

    Клиент повторяет запрос после сетевого сбоя; средства должны
    списаться один раз, иначе деньги уйдут дважды.
    """
    key = "repeat-key-1"
    payload = {
        "from_account_id": account.id,
        "to_account_id": second_account.id,
        "amount": "150.00",
    }
    headers = {**auth_headers(user), "Idempotency-Key": key}

    first = await client.post(TRANSACTIONS_URL, headers=headers, json=payload)
    second = await client.post(TRANSACTIONS_URL, headers=headers, json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    await db_session.refresh(account)
    await db_session.refresh(second_account)
    assert account.balance == Decimal("850.00")
    assert second_account.balance == Decimal("350.00")


async def test_idempotent_replay_of_failed_transfer_does_not_block_retry(
    client: AsyncClient,
    user: User,
    account: Account,
    second_account: Account,
    auth_headers: AuthHeaders,
) -> None:
    """Неудачный перевод не занимает ключ: его можно повторить.

    Иначе после временной нехватки средств клиент не смог бы
    повторить платёж с тем же ключом.
    """
    key = "retry-after-failure"
    headers = {**auth_headers(user), "Idempotency-Key": key}

    failed = await client.post(
        TRANSACTIONS_URL,
        headers=headers,
        json={
            "from_account_id": account.id,
            "to_account_id": second_account.id,
            "amount": "99999.00",
        },
    )
    assert failed.status_code == 409

    succeeded = await client.post(
        TRANSACTIONS_URL,
        headers=headers,
        json={
            "from_account_id": account.id,
            "to_account_id": second_account.id,
            "amount": "50.00",
        },
    )
    assert succeeded.status_code == 201


async def test_missing_idempotency_key_is_rejected(
    client: AsyncClient,
    user: User,
    account: Account,
    second_account: Account,
    auth_headers: AuthHeaders,
) -> None:
    """Без ключа идемпотентности перевод не выполняется."""
    response = await client.post(
        TRANSACTIONS_URL,
        headers=auth_headers(user),
        json={
            "from_account_id": account.id,
            "to_account_id": second_account.id,
            "amount": "10.00",
        },
    )

    assert response.status_code == 400
    assert "Idempotency-Key" in response.json()["detail"]


async def test_idempotency_key_length_is_limited(
    client: AsyncClient,
    user: User,
    account: Account,
    second_account: Account,
    auth_headers: AuthHeaders,
) -> None:
    """Слишком длинный ключ отклоняется, а не обрезается."""
    response = await client.post(
        TRANSACTIONS_URL,
        headers={**auth_headers(user), "Idempotency-Key": "k" * 65},
        json={
            "from_account_id": account.id,
            "to_account_id": second_account.id,
            "amount": "10.00",
        },
    )

    assert response.status_code == 400


async def test_insufficient_funds_rejected(
    client: AsyncClient,
    user: User,
    account: Account,
    second_account: Account,
    db_session: AsyncSession,
    auth_headers: AuthHeaders,
    idempotency_key: KeyFactory,
) -> None:
    """Перевод сверх баланса отклоняется и не меняет остатки."""
    response = await client.post(
        TRANSACTIONS_URL,
        headers={**auth_headers(user), "Idempotency-Key": idempotency_key()},
        json={
            "from_account_id": account.id,
            "to_account_id": second_account.id,
            "amount": "5000.00",
        },
    )

    assert response.status_code == 409
    assert "Недостаточно средств" in response.json()["detail"]

    await db_session.refresh(account)
    await db_session.refresh(second_account)
    assert account.balance == Decimal("1000.00")
    assert second_account.balance == Decimal("200.00")


async def test_transfer_to_same_account_rejected(
    client: AsyncClient,
    user: User,
    account: Account,
    auth_headers: AuthHeaders,
    idempotency_key: KeyFactory,
) -> None:
    """Перевод самому себе не имеет смысла и запрещён."""
    response = await client.post(
        TRANSACTIONS_URL,
        headers={**auth_headers(user), "Idempotency-Key": idempotency_key()},
        json={
            "from_account_id": account.id,
            "to_account_id": account.id,
            "amount": "10.00",
        },
    )

    assert response.status_code == 409


async def test_currency_mismatch_rejected(
    client: AsyncClient,
    user: User,
    account: Account,
    db_session: AsyncSession,
    auth_headers: AuthHeaders,
    idempotency_key: KeyFactory,
) -> None:
    """Перевод между счетами в разных валютах запрещён."""
    usd_account = Account(
        user_id=user.id,
        account_number="RU000000000000000009",
        balance=Decimal("1000.00"),
        currency="USD",
    )
    db_session.add(usd_account)
    await db_session.commit()
    await db_session.refresh(usd_account)

    response = await client.post(
        TRANSACTIONS_URL,
        headers={**auth_headers(user), "Idempotency-Key": idempotency_key()},
        json={
            "from_account_id": account.id,
            "to_account_id": usd_account.id,
            "amount": "10.00",
        },
    )

    assert response.status_code == 409
    assert "Валюты" in response.json()["detail"]


async def test_cannot_transfer_to_other_users_account(
    client: AsyncClient,
    user: User,
    other_user: User,
    account: Account,
    db_session: AsyncSession,
    auth_headers: AuthHeaders,
    idempotency_key: KeyFactory,
) -> None:
    """Чужой счёт недоступен для перевода.

    Иначе клиент перебором идентификаторов проверял бы, какие счета
    существуют, и мог бы пополнять чужие счета.
    """
    victim_account = Account(
        user_id=other_user.id,
        account_number="RU000000000000000008",
        balance=Decimal("10.00"),
        currency="RUB",
    )
    db_session.add(victim_account)
    await db_session.commit()
    await db_session.refresh(victim_account)

    response = await client.post(
        TRANSACTIONS_URL,
        headers={**auth_headers(user), "Idempotency-Key": idempotency_key()},
        json={
            "from_account_id": account.id,
            "to_account_id": victim_account.id,
            "amount": "10.00",
        },
    )

    assert response.status_code == 404

    await db_session.refresh(victim_account)
    assert victim_account.balance == Decimal("10.00")


async def test_cannot_debit_other_users_account(
    client: AsyncClient,
    user: User,
    other_user: User,
    account: Account,
    second_account: Account,
    db_session: AsyncSession,
    auth_headers: AuthHeaders,
    idempotency_key: KeyFactory,
) -> None:
    """Нельзя списать средства с чужого счёта."""
    victim_account = Account(
        user_id=other_user.id,
        account_number="RU000000000000000007",
        balance=Decimal("500.00"),
        currency="RUB",
    )
    db_session.add(victim_account)
    await db_session.commit()
    await db_session.refresh(victim_account)

    response = await client.post(
        TRANSACTIONS_URL,
        headers={**auth_headers(user), "Idempotency-Key": idempotency_key()},
        json={
            "from_account_id": victim_account.id,
            "to_account_id": account.id,
            "amount": "100.00",
        },
    )

    assert response.status_code == 404

    await db_session.refresh(victim_account)
    await db_session.refresh(account)
    assert victim_account.balance == Decimal("500.00")
    assert account.balance == Decimal("1000.00")


async def test_concurrent_transfers_never_overdraw(
    user: User,
    account: Account,
    second_account: Account,
    redis_client: Redis,
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
) -> None:
    """Параллельные переводы не уводят баланс в минус.

    Блокировка строк должна удержать параллельные переводы: иначе все
    они увидят одну и ту же сумму на счёте и пройдут проверку, хотя
    денег хватает только на часть из них.

    Каждый перевод выполняется в собственной сессии: общая сессия
    фикстуры не годится, SQLAlchemy не допускает параллельного
    использования одной сессии, и проверялась бы не блокировка
    строк, а её отсутствие.
    """
    payload = TransactionCreate(
        from_account_id=account.id,
        to_account_id=second_account.id,
        amount=Decimal("150.00"),
    )

    async def send(index: int) -> bool:
        """Выполнить перевод в отдельной сессии.

        Args:
            index: Номер попытки, используется как ключ идемпотентности.

        Returns:
            ``True``, если перевод прошёл, иначе ``False``.
        """
        async with session_factory() as session:
            try:
                await transaction_service.create_transfer(
                    session,
                    user.id,
                    payload,
                    f"concurrent-{index}",
                )
            except DomainError:
                return False
            return True

    results = await asyncio.gather(*(send(index) for index in range(10)))

    succeeded = sum(results)
    assert succeeded == 6, (
        f"при балансе 1000 и переводах по 150 должно пройти ровно 6, "
        f"получилось {succeeded}"
    )

    async with session_factory() as session:
        refreshed_source = await session.get(Account, account.id)
        refreshed_target = await session.get(Account, second_account.id)
        assert refreshed_source is not None
        assert refreshed_target is not None
        assert refreshed_source.balance == Decimal("100.00")
        # На счёте получателя был стартовый баланс 200 плюс шесть
        # переводов по 150.
        assert refreshed_target.balance == Decimal("1100.00")


async def test_history_lists_transfers(
    client: AsyncClient,
    user: User,
    account: Account,
    second_account: Account,
    auth_headers: AuthHeaders,
    idempotency_key: KeyFactory,
) -> None:
    """История содержит исходящие и входящие операции."""
    headers = auth_headers(user)
    await client.post(
        TRANSACTIONS_URL,
        headers={**headers, "Idempotency-Key": idempotency_key()},
        json={
            "from_account_id": account.id,
            "to_account_id": second_account.id,
            "amount": "100.00",
        },
    )

    response = await client.get(TRANSACTIONS_URL, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["amount"] == "100.00"
    assert body["page"] == 1


async def test_history_filtered_by_account(
    client: AsyncClient,
    user: User,
    account: Account,
    second_account: Account,
    auth_headers: AuthHeaders,
    idempotency_key: KeyFactory,
) -> None:
    """Фильтр по счёту оставляет только операции по нему."""
    headers = auth_headers(user)
    await client.post(
        TRANSACTIONS_URL,
        headers={**headers, "Idempotency-Key": idempotency_key()},
        json={
            "from_account_id": account.id,
            "to_account_id": second_account.id,
            "amount": "100.00",
        },
    )

    response = await client.get(
        f"{TRANSACTIONS_URL}?account_id={account.id}",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1


async def test_history_filtered_by_status(
    client: AsyncClient,
    user: User,
    account: Account,
    second_account: Account,
    auth_headers: AuthHeaders,
    idempotency_key: KeyFactory,
) -> None:
    """Фильтр по статусу отбрасывает несовпадающие записи."""
    headers = auth_headers(user)
    await client.post(
        TRANSACTIONS_URL,
        headers={**headers, "Idempotency-Key": idempotency_key()},
        json={
            "from_account_id": account.id,
            "to_account_id": second_account.id,
            "amount": "100.00",
        },
    )

    completed = await client.get(
        f"{TRANSACTIONS_URL}?status=completed",
        headers=headers,
    )
    failed = await client.get(f"{TRANSACTIONS_URL}?status=failed", headers=headers)

    assert completed.json()["total"] == 1
    assert failed.json()["total"] == 0


async def test_history_does_not_show_other_users_transactions(
    client: AsyncClient,
    user: User,
    other_user: User,
    account: Account,
    second_account: Account,
    auth_headers: AuthHeaders,
    idempotency_key: KeyFactory,
) -> None:
    """Пользователь не видит операции других."""
    await client.post(
        TRANSACTIONS_URL,
        headers={**auth_headers(user), "Idempotency-Key": idempotency_key()},
        json={
            "from_account_id": account.id,
            "to_account_id": second_account.id,
            "amount": "100.00",
        },
    )

    response = await client.get(
        TRANSACTIONS_URL,
        headers=auth_headers(other_user),
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_get_transaction_detail(
    client: AsyncClient,
    user: User,
    account: Account,
    second_account: Account,
    auth_headers: AuthHeaders,
    idempotency_key: KeyFactory,
) -> None:
    """Детали транзакции доступны её участнику."""
    created = await client.post(
        TRANSACTIONS_URL,
        headers={**auth_headers(user), "Idempotency-Key": idempotency_key()},
        json={
            "from_account_id": account.id,
            "to_account_id": second_account.id,
            "amount": "100.00",
        },
    )
    transaction_id = created.json()["id"]

    response = await client.get(
        f"{TRANSACTIONS_URL}/{transaction_id}",
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    assert response.json()["id"] == transaction_id


async def test_cannot_read_other_users_transaction(
    client: AsyncClient,
    user: User,
    other_user: User,
    account: Account,
    second_account: Account,
    db_session: AsyncSession,
    auth_headers: AuthHeaders,
    idempotency_key: KeyFactory,
) -> None:
    """Чужая транзакция отдаёт 404."""
    created = await client.post(
        TRANSACTIONS_URL,
        headers={**auth_headers(user), "Idempotency-Key": idempotency_key()},
        json={
            "from_account_id": account.id,
            "to_account_id": second_account.id,
            "amount": "100.00",
        },
    )
    transaction_id = created.json()["id"]

    response = await client.get(
        f"{TRANSACTIONS_URL}/{transaction_id}",
        headers=auth_headers(other_user),
    )

    assert response.status_code == 404


async def test_transaction_requires_authentication(client: AsyncClient) -> None:
    """Без токена перевод невозможен."""
    response = await client.get(TRANSACTIONS_URL)
    assert response.status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {"from_account_id": 0, "to_account_id": 2, "amount": "10.00"},
        {"from_account_id": 1, "to_account_id": 2, "amount": "0"},
        {"from_account_id": 1, "to_account_id": 2, "amount": "-10.00"},
        {"from_account_id": 1, "to_account_id": 2},
    ],
)
async def test_transfer_rejects_invalid_payload(
    client: AsyncClient,
    user: User,
    account: Account,
    second_account: Account,
    auth_headers: AuthHeaders,
    idempotency_key: KeyFactory,
    payload: dict[str, object],
) -> None:
    """Некорректные параметры перевода отклоняются валидатором."""
    response = await client.post(
        TRANSACTIONS_URL,
        headers={**auth_headers(user), "Idempotency-Key": idempotency_key()},
        json=payload,
    )
    assert response.status_code == 422


async def test_transaction_record_created_in_database(
    client: AsyncClient,
    user: User,
    account: Account,
    second_account: Account,
    db_session: AsyncSession,
    auth_headers: AuthHeaders,
    idempotency_key: KeyFactory,
) -> None:
    """Транзакция фиксируется в базе со всеми полями."""
    key = "db-check-key"

    await client.post(
        TRANSACTIONS_URL,
        headers={**auth_headers(user), "Idempotency-Key": key},
        json={
            "from_account_id": account.id,
            "to_account_id": second_account.id,
            "amount": "250.00",
            "description": "Проверка",
        },
    )

    transaction = await db_session.scalar(
        select(Transaction).where(Transaction.idempotency_key == key),
    )

    assert transaction is not None
    assert transaction.amount == Decimal("250.00")
    assert transaction.status == "completed"
    assert transaction.description == "Проверка"


async def test_transfer_uses_decimal_not_float(
    client: AsyncClient,
    user: User,
    account: Account,
    second_account: Account,
    db_session: AsyncSession,
    auth_headers: AuthHeaders,
    idempotency_key: KeyFactory,
) -> None:
    """Сложение десятичных дробей не накапливает ошибку округления.

    Работа с float дала бы 0.30000000000000004 вместо 0.30.
    """
    headers = {**auth_headers(user)}
    for _ in range(3):
        await client.post(
            TRANSACTIONS_URL,
            headers={**headers, "Idempotency-Key": idempotency_key()},
            json={
                "from_account_id": account.id,
                "to_account_id": second_account.id,
                "amount": "0.10",
            },
        )

    await db_session.refresh(second_account)
    assert second_account.balance == Decimal("200.30")
