"""Тесты аутентификации."""

import uuid
from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
ME_URL = "/api/v1/auth/me"


async def test_register_creates_user(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Регистрация сохраняет пользователя и возвращает его профиль."""
    email = f"{uuid.uuid4().hex}@example.com"
    username = f"user{uuid.uuid4().hex[:8]}"

    response = await client.post(
        REGISTER_URL,
        json={
            "email": email,
            "username": username,
            "password": "Secret123",
            "full_name": "Иван Иванов",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == email
    assert body["username"] == username
    assert body["is_active"] is True
    # Пароль не должен попадать в ответ.
    assert "password" not in body
    assert "hashed_password" not in body

    user = await db_session.scalar(select(User).where(User.username == username))
    assert user is not None
    assert user.hashed_password != "Secret123"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "username": "valid_user", "password": "Secret123"},
        {"email": "a@b.ru", "username": "ab", "password": "Secret123"},
        {"email": "a@b.ru", "username": "valid_user", "password": "short"},
        {"email": "a@b.ru", "username": "bad login", "password": "Secret123"},
    ],
)
async def test_register_rejects_invalid_payload(
    client: AsyncClient,
    payload: dict[str, str],
) -> None:
    """Некорректные данные регистрации отклоняются валидатором."""
    response = await client.post(REGISTER_URL, json=payload)
    assert response.status_code == 422


async def test_register_rejects_duplicate_email(client: AsyncClient) -> None:
    """Повторный email возвращает 409."""
    email = f"{uuid.uuid4().hex}@example.com"
    payload = {"email": email, "username": "first_user", "password": "Secret123"}

    first = await client.post(REGISTER_URL, json=payload)
    assert first.status_code == 201

    duplicate = await client.post(
        REGISTER_URL,
        json={"email": email, "username": "second_user", "password": "Secret123"},
    )
    assert duplicate.status_code == 409
    assert "email" in duplicate.json()["detail"].lower()


async def test_register_rejects_duplicate_username(client: AsyncClient) -> None:
    """Повторный логин возвращает 409."""
    username = f"user{uuid.uuid4().hex[:8]}"
    payload = {
        "email": f"{uuid.uuid4().hex}@example.com",
        "username": username,
        "password": "Secret123",
    }

    first = await client.post(REGISTER_URL, json=payload)
    assert first.status_code == 201

    duplicate = await client.post(
        REGISTER_URL,
        json={**payload, "email": f"{uuid.uuid4().hex}@example.com"},
    )
    assert duplicate.status_code == 409


async def test_register_normalizes_email(client: AsyncClient) -> None:
    """Email сохраняется в нижнем регистре, чтобы не плодить дубли."""
    local = uuid.uuid4().hex
    response = await client.post(
        REGISTER_URL,
        json={
            "email": f"{local}@Example.COM",
            "username": f"u{local[:8]}",
            "password": "Secret123",
        },
    )

    assert response.status_code == 201
    assert response.json()["email"] == f"{local}@example.com"


async def test_login_by_username(client: AsyncClient, user: User) -> None:
    """Вход по логину выдаёт пару токенов."""
    response = await client.post(
        LOGIN_URL,
        json={"username": user.username, "password": "Secret123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["access_token"]
    assert body["refresh_token"]


async def test_login_by_email(client: AsyncClient, user: User) -> None:
    """Вход по email работает так же, как вход по логину."""
    response = await client.post(
        LOGIN_URL,
        json={"email": user.email, "password": "Secret123"},
    )
    assert response.status_code == 200


async def test_login_wrong_password(client: AsyncClient, user: User) -> None:
    """Неверный пароль не выдаёт токены."""
    response = await client.post(
        LOGIN_URL,
        json={"username": user.username, "password": "WrongPass1"},
    )

    assert response.status_code == 401
    assert "access_token" not in response.json()


async def test_login_unknown_user_gives_same_error(
    client: AsyncClient,
    user: User,
) -> None:
    """Неизвестный пользователь и неверный пароль дают одинаковый ответ.

    Иначе по тексту ошибки можно было бы перебирать зарегистрированные
    email: существующий отвечал бы «неверный пароль».
    """
    wrong_password = await client.post(
        LOGIN_URL,
        json={"username": user.username, "password": "WrongPass1"},
    )
    unknown = await client.post(
        LOGIN_URL,
        json={"username": "no_such_user", "password": "Secret123"},
    )

    assert wrong_password.status_code == unknown.status_code == 401
    assert wrong_password.json()["detail"] == unknown.json()["detail"]


async def test_login_requires_identifier(client: AsyncClient) -> None:
    """Без email и логина запрос не проходит валидацию бизнес-логики."""
    response = await client.post(LOGIN_URL, json={"password": "Secret123"})
    assert response.status_code == 422


async def test_get_me_returns_profile(
    client: AsyncClient,
    user: User,
    auth_headers: Callable[[User, str | None], dict[str, str]],
) -> None:
    """Эндпоинт /me возвращает профиль владельца токена."""
    response = await client.get(ME_URL, headers=auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == user.id
    assert body["email"] == user.email


async def test_get_me_requires_token(client: AsyncClient) -> None:
    """Без заголовка Authorization запрос отклоняется."""
    response = await client.get(ME_URL)
    assert response.status_code == 401


async def test_get_me_rejects_invalid_token(client: AsyncClient) -> None:
    """Подделанный токен не проходит проверку подписи."""
    response = await client.get(
        ME_URL,
        headers={"Authorization": "Bearer not.a.real.token"},
    )
    assert response.status_code == 401


async def test_refresh_issues_new_tokens(
    client: AsyncClient,
    user: User,
    auth_headers: Callable[[User, str | None], dict[str, str]],
) -> None:
    """Refresh-токен обменивается на новую пару токенов."""
    login = await client.post(
        LOGIN_URL,
        json={"username": user.username, "password": "Secret123"},
    )
    refresh_token = login.json()["refresh_token"]

    response = await client.post(
        REFRESH_URL,
        json={"refresh_token": refresh_token},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]


async def test_access_token_cannot_be_used_for_refresh(
    client: AsyncClient,
    user: User,
    auth_headers: Callable[[User, str | None], dict[str, str]],
) -> None:
    """Access-токен не принимается на месте refresh-токена."""
    access = auth_headers(user)["Authorization"].removeprefix("Bearer ")

    response = await client.post(REFRESH_URL, json={"refresh_token": access})

    assert response.status_code == 401


async def test_refresh_rejects_garbage(client: AsyncClient) -> None:
    """Мусор вместо refresh-токена отклоняется."""
    response = await client.post(REFRESH_URL, json={"refresh_token": "garbage"})
    assert response.status_code == 401


async def test_inactive_user_cannot_login(
    client: AsyncClient,
    db_session: AsyncSession,
    user: User,
) -> None:
    """Деактивированный пользователь не может войти."""
    user.is_active = False
    await db_session.commit()

    response = await client.post(
        LOGIN_URL,
        json={"username": user.username, "password": "Secret123"},
    )
    assert response.status_code == 401


async def test_inactive_user_token_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
    user: User,
    auth_headers: Callable[[User, str | None], dict[str, str]],
) -> None:
    """Токен деактивированного пользователя перестаёт работать."""
    headers = auth_headers(user)

    user.is_active = False
    await db_session.commit()

    response = await client.get(ME_URL, headers=headers)
    assert response.status_code == 401
