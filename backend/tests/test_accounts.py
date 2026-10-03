"""Тесты банковских счетов."""

from collections.abc import Callable

import pytest
from httpx import AsyncClient

from app.models.account import Account
from app.models.user import User

ACCOUNTS_URL = "/api/v1/accounts"

AuthHeaders = Callable[[User, str | None], dict[str, str]]


async def test_create_account(
    client: AsyncClient,
    user: User,
    auth_headers: AuthHeaders,
) -> None:
    """Создание счёта возвращает номер, валюту и начальный баланс."""
    response = await client.post(
        ACCOUNTS_URL,
        headers=auth_headers(user),
        json={"currency": "RUB", "initial_balance": "500.00"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["currency"] == "RUB"
    assert body["balance"] == "500.00"
    assert body["is_active"] is True
    assert body["user_id"] == user.id
    assert body["account_number"].startswith("RU")
    assert len(body["account_number"]) == 20


async def test_create_account_defaults_to_zero_balance(
    client: AsyncClient,
    user: User,
    auth_headers: AuthHeaders,
) -> None:
    """Без начального остатка счёт открывается с нулевым балансом."""
    response = await client.post(
        ACCOUNTS_URL,
        headers=auth_headers(user),
        json={"currency": "USD"},
    )

    assert response.status_code == 201
    assert response.json()["balance"] == "0.00"


async def test_account_numbers_are_unique(
    client: AsyncClient,
    user: User,
    auth_headers: AuthHeaders,
) -> None:
    """Каждый счёт получает уникальный номер."""
    numbers = set()
    for _ in range(3):
        response = await client.post(
            ACCOUNTS_URL,
            headers=auth_headers(user),
            json={"currency": "RUB"},
        )
        numbers.add(response.json()["account_number"])

    assert len(numbers) == 3


@pytest.mark.parametrize(
    "payload",
    [
        {"currency": "russian rubles"},
        {"currency": "RU"},
        {"currency": "RUB", "initial_balance": "-100.00"},
        {"currency": "RUB", "initial_balance": "abc"},
    ],
)
async def test_create_account_rejects_invalid_payload(
    client: AsyncClient,
    user: User,
    auth_headers: AuthHeaders,
    payload: dict[str, str],
) -> None:
    """Некорректные параметры счёта отклоняются валидатором."""
    response = await client.post(
        ACCOUNTS_URL,
        headers=auth_headers(user),
        json=payload,
    )
    assert response.status_code == 422


async def test_list_accounts(
    client: AsyncClient,
    user: User,
    account: Account,
    second_account: Account,
    auth_headers: AuthHeaders,
) -> None:
    """Список содержит только счета текущего пользователя."""
    response = await client.get(ACCOUNTS_URL, headers=auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert {item["id"] for item in body} == {account.id, second_account.id}


async def test_list_accounts_empty_for_new_user(
    client: AsyncClient,
    other_user: User,
    auth_headers: AuthHeaders,
) -> None:
    """У нового пользователя список счетов пуст."""
    response = await client.get(ACCOUNTS_URL, headers=auth_headers(other_user))

    assert response.status_code == 200
    assert response.json() == []


async def test_get_account(
    client: AsyncClient,
    user: User,
    account: Account,
    auth_headers: AuthHeaders,
) -> None:
    """Детали счёта возвращают его данные."""
    response = await client.get(
        f"{ACCOUNTS_URL}/{account.id}",
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    assert response.json()["id"] == account.id
    assert response.json()["balance"] == "1000.00"


async def test_get_account_balance(
    client: AsyncClient,
    user: User,
    account: Account,
    auth_headers: AuthHeaders,
) -> None:
    """Эндпоинт баланса возвращает сумму и валюту."""
    response = await client.get(
        f"{ACCOUNTS_URL}/{account.id}/balance",
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["balance"] == "1000.00"
    assert body["currency"] == "RUB"
    assert body["account_number"] == account.account_number


async def test_get_account_not_found(
    client: AsyncClient,
    user: User,
    auth_headers: AuthHeaders,
) -> None:
    """Несуществующий счёт возвращает 404."""
    response = await client.get(
        f"{ACCOUNTS_URL}/999999",
        headers=auth_headers(user),
    )
    assert response.status_code == 404


async def test_cannot_read_other_users_account(
    client: AsyncClient,
    other_user: User,
    account: Account,
    auth_headers: AuthHeaders,
) -> None:
    """Чужой счёт отдаёт 404, а не 403.

    Ответ 403 подтверждал бы, что счёт существует, и позволял бы
    перебирать чужие счета по идентификатору.
    """
    response = await client.get(
        f"{ACCOUNTS_URL}/{account.id}",
        headers=auth_headers(other_user),
    )
    assert response.status_code == 404


async def test_cannot_read_other_users_balance(
    client: AsyncClient,
    other_user: User,
    account: Account,
    auth_headers: AuthHeaders,
) -> None:
    """Баланс чужого счёта недоступен."""
    response = await client.get(
        f"{ACCOUNTS_URL}/{account.id}/balance",
        headers=auth_headers(other_user),
    )
    assert response.status_code == 404


@pytest.mark.parametrize("path", ["", "/1", "/1/balance"])
async def test_endpoints_require_authentication(client: AsyncClient, path: str) -> None:
    """Без токена все маршруты счетов закрыты."""
    response = await client.get(f"{ACCOUNTS_URL}{path}")
    assert response.status_code == 401
