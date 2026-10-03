"""Хеширование паролей и работа с JWT-токенами.

Пароли хешируются через passlib/bcrypt, а токены подписываются
python-jose. Access- и refresh-токены различаются типом ``type``
внутри payload: это не даёт refresh-токену использоваться там, где
ожидается access-токен, и наоборот.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Final

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

BCRYPT_MAX_BYTES: Final[int] = 72
"""Максимальный размер пароля, который принимает bcrypt.

bcrypt учитывает только первые 72 байта. Более длинный пароль
обрубается, чтобы два разных пароля с общим длинным префиксом не
оказались одинаковыми после хеширования.
"""

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class TokenError(Exception):
    """Ошибка проверки или создания JWT-токена.

    Наружу не отдаются детали реализации: вызывающий код превращает
    исключение в 401, не раскрывая клиенту причину отказа.
    """


def _prepare_password(password: str) -> bytes:
    """Подготовить пароль к хешированию.

    Args:
        password: Пароль в открытом виде.

    Returns:
        Пароль в байтах, обрезанный до 72 байт.
    """
    return password.encode("utf-8")[:BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """Захешировать пароль.

    Args:
        password: Пароль в открытом виде.

    Returns:
        Хеш пароля, безопасный для хранения в базе.
    """
    return pwd_context.hash(_prepare_password(password))


def verify_password(password: str, hashed_password: str) -> bool:
    """Проверить, соответствует ли пароль сохранённому хешу.

    Args:
        password: Проверяемый пароль в открытом виде.
        hashed_password: Хеш из базы данных.

    Returns:
        ``True``, если пароль верный, иначе ``False``.
    """
    return pwd_context.verify(_prepare_password(password), hashed_password)


def create_token(
    subject: str,
    token_type: str,
    expires_delta: timedelta,
) -> str:
    """Создать подписанный JWT-токен.

    Args:
        subject: Идентификатор пользователя, попадающий в ``sub``.
        token_type: Тип токена (``access`` или ``refresh``).
        expires_delta: Срок жизни токена.

    Returns:
        Подписанный JWT-токен.

    Raises:
        TokenError: Если токен не удалось создать.
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    try:
        return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    except JWTError as exc:
        raise TokenError("Не удалось создать токен") from exc


def create_access_token(subject: str) -> str:
    """Создать access-токен с коротким сроком жизни.

    Args:
        subject: Идентификатор пользователя.

    Returns:
        Подписанный JWT-токен.
    """
    return create_token(
        subject=subject,
        token_type="access",
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(subject: str) -> str:
    """Создать refresh-токен с длительным сроком жизни.

    Args:
        subject: Идентификатор пользователя.

    Returns:
        Подписанный JWT-токен.
    """
    return create_token(
        subject=subject,
        token_type="refresh",
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, expected_type: str) -> str:
    """Проверить токен и вернуть идентификатор пользователя.

    Args:
        token: JWT-токен из заголовка ``Authorization``.
        expected_type: Ожидаемый тип токена.

    Returns:
        Идентификатор пользователя из ``sub``.

    Raises:
        TokenError: Если токен просрочен, подделан или его тип не
            совпадает с ожидаемым.
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
    except JWTError as exc:
        raise TokenError("Токен недействителен или истёк") from exc

    if payload.get("type") != expected_type:
        raise TokenError(f"Ожидался токен типа {expected_type}")

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise TokenError("Токен не содержит идентификатор пользователя")

    return subject
