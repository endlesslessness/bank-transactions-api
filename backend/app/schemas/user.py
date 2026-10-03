"""Pydantic-схемы пользователя и аутентификации."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    """Общие поля пользователя.

    Attributes:
        email: Адрес электронной почты.
        username: Логин.
        full_name: Полное имя, необязательное.
    """

    email: EmailStr
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    full_name: str | None = Field(default=None, max_length=255)


class UserCreate(UserBase):
    """Запрос на регистрацию.

    Пароль ограничен 72 байтами — столько учитывает bcrypt, и всё
    что длиннее, не даёт никакой дополнительной стойкости.
    """

    password: str = Field(min_length=8, max_length=72)


class UserLogin(BaseModel):
    """Запрос на аутентификацию.

    Принимается либо email, либо логин: пользователю не нужно
    помнить, какое из двух полей он указывал при регистрации.
    """

    email: EmailStr | None = None
    username: str | None = Field(default=None, min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=72)


class UserRead(UserBase):
    """Пользователь в ответе API.

    Хеш пароля наружу не отдаётся: в модели есть только безопасные
    для публикации поля.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    """Ответ на успешную аутентификацию.

    Attributes:
        access_token: Короткоживущий токен для доступа к API.
        refresh_token: Долгоживущий токен для обновления доступа.
        token_type: Тип заголовка авторизации, всегда ``bearer``.
        expires_in: Срок жизни access-токена в секундах.
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    """Запрос на обновление access-токена.

    Attributes:
        refresh_token: Ранее выданный refresh-токен.
    """

    refresh_token: str
