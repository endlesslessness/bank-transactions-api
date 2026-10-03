"""Бизнес-логика аутентификации: регистрация, вход, обновление токена.

Пароли хешируются, а JWT-токены выпускаются через ``core.security``.
Слой не знает про HTTP: наружу отдаются модели ORM и доменные
исключения, а коды ответов проставляют эндпоинты.
"""

import logging

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserLogin
from app.services.exceptions import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    UsernameAlreadyTakenError,
)

logger = logging.getLogger(__name__)


async def _is_email_taken(session: AsyncSession, email: str) -> bool:
    """Проверить, занят ли email.

    Args:
        session: Асинхронная сессия базы данных.
        email: Проверяемый адрес.

    Returns:
        ``True``, если пользователь с таким email уже есть.
    """
    result = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(func.lower(User.email) == email.lower())
    )
    return bool(result)


async def _is_username_taken(session: AsyncSession, username: str) -> bool:
    """Проверить, занят ли логин.

    Args:
        session: Асинхронная сессия базы данных.
        username: Проверяемый логин.

    Returns:
        ``True``, если пользователь с таким логином уже есть.
    """
    result = await session.scalar(
        select(func.count()).select_from(User).where(User.username == username)
    )
    return bool(result)


def _build_token_pair(user: User) -> Token:
    """Выпустить пару access/refresh токенов для пользователя.

    Args:
        user: Пользователь, для которого выпускаются токены.

    Returns:
        Пара токенов вместе со сроком жизни access-токена.
    """
    subject = str(user.id)
    return Token(
        access_token=create_access_token(subject),
        refresh_token=create_refresh_token(subject),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


async def register_user(session: AsyncSession, payload: UserCreate) -> User:
    """Зарегистрировать нового пользователя.

    Уникальность email и логина проверяется заранее, чтобы вернуть
    понятную ошибку вместо ``IntegrityError``; ограничение на уровне
    базы остаётся как страховка от гонки между параллельными
    запросами.

    Args:
        session: Асинхронная сессия базы данных.
        payload: Данные нового пользователя.

    Returns:
        Созданный пользователь.

    Raises:
        EmailAlreadyRegisteredError: Если email уже занят.
        UsernameAlreadyTakenError: Если логин уже занят.
    """
    normalized_email = str(payload.email).lower()

    if await _is_email_taken(session, normalized_email):
        raise EmailAlreadyRegisteredError("Пользователь с таким email уже существует")
    if await _is_username_taken(session, payload.username):
        raise UsernameAlreadyTakenError("Этот логин уже занят")

    user = User(
        email=normalized_email,
        username=payload.username,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    session.add(user)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # Нельзя сказать, какое именно поле нарушило уникальность,
        # поэтому проверяем оба и сообщаем о конкретном конфликте.
        if await _is_email_taken(session, normalized_email):
            raise EmailAlreadyRegisteredError(
                "Пользователь с таким email уже существует"
            ) from exc
        if await _is_username_taken(session, payload.username):
            raise UsernameAlreadyTakenError("Этот логин уже занят") from exc
        raise

    await session.refresh(user)
    logger.info(
        "Зарегистрирован пользователь id=%s username=%s", user.id, user.username
    )
    return user


async def authenticate_user(session: AsyncSession, payload: UserLogin) -> User:
    """Проверить учётные данные и вернуть пользователя.

    Args:
        session: Асинхронная сессия базы данных.
        payload: Логин (или email) и пароль.

    Returns:
        Активный пользователь с верным паролем.

    Raises:
        InvalidCredentialsError: Если пользователь не найден, пароль неверен
            либо учётная запись деактивирована. Причины намеренно не
            различаются, чтобы по ответу нельзя было перебирать email.
    """
    conditions = []
    if payload.email is not None:
        conditions.append(func.lower(User.email) == payload.email.lower())
    if payload.username is not None:
        conditions.append(User.username == payload.username)

    user: User | None = None
    if conditions:
        user = await session.scalar(select(User).where(or_(*conditions)))

    if user is None or not verify_password(payload.password, user.hashed_password):
        logger.info("Неудачная попытка входа")
        raise InvalidCredentialsError("Неверный логин или пароль")

    if not user.is_active:
        raise InvalidCredentialsError("Учётная запись деактивирована")

    logger.info("Выполнен вход пользователя id=%s", user.id)
    return user


async def issue_token_pair(user: User) -> Token:
    """Выпустить пару токенов для уже аутентифицированного пользователя.

    Args:
        user: Аутентифицированный пользователь.

    Returns:
        Пара access/refresh токенов.
    """
    return _build_token_pair(user)


async def refresh_access_token(session: AsyncSession, refresh_token: str) -> Token:
    """Обновить access-токен по refresh-токену.

    Пара токенов выпускается заново: refresh-токен не хранится в базе,
    поэтому отозвать его до истечения срока нельзя — это осознанное
    упрощение для учебного проекта.

    Args:
        session: Асинхронная сессия базы данных.
        refresh_token: Ранее выданный refresh-токен.

    Returns:
        Новая пара access/refresh токенов.

    Raises:
        InvalidCredentialsError: Если токен недействителен, просрочен или
            принадлежит несуществующему либо деактивированному пользователю.
    """
    try:
        subject = decode_token(refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise InvalidCredentialsError("Refresh-токен недействителен или истёк") from exc

    try:
        user_id = int(subject)
    except ValueError as exc:
        raise InvalidCredentialsError("Некорректный refresh-токен") from exc

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise InvalidCredentialsError("Пользователь не найден или деактивирован")

    return _build_token_pair(user)
