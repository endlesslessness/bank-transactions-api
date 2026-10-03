"""Общие зависимости FastAPI: аутентификация и параметры пагинации.

Зависимости решают, кто обращается к эндпоинту, и достают из базы
соответствующего пользователя, чтобы эндпоинты оставались тонкими.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenError, decode_token
from app.db.session import get_session
from app.models.user import User

bearer_scheme = HTTPBearer(
    auto_error=False,
    description="JWT access-токен, полученный при логине",
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
"""Зависимость с асинхронной сессией базы данных."""

CredentialsDep = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(bearer_scheme),
]
"""Зависимость с заголовком ``Authorization``, если он передан."""


async def get_current_user(
    session: SessionDep,
    credentials: CredentialsDep,
) -> User:
    """Получить текущего пользователя по access-токену.

    Args:
        session: Асинхронная сессия базы данных.
        credentials: Учётные данные из заголовка ``Authorization``.

    Returns:
        Активный пользователь, которому принадлежит токен.

    Raises:
        HTTPException: 401, если заголовок отсутствует, токен недействителен
            либо пользователь удалён или деактивирован.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Требуется авторизация",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise unauthorized

    try:
        subject = decode_token(credentials.credentials, expected_type="access")
    except TokenError as exc:
        raise unauthorized from exc

    try:
        user_id = int(subject)
    except ValueError as exc:
        raise unauthorized from exc

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
"""Зависимость с текущим авторизованным пользователем."""


class Pagination:
    """Параметры постраничной выдачи.

    Defaults:
        page: Номер страницы, начиная с 1.
        size: Размер страницы.
    """

    def __init__(
        self,
        page: Annotated[int, Query(ge=1, description="Номер страницы")] = 1,
        size: Annotated[int, Query(ge=1, le=100, description="Размер страницы")] = 50,
    ) -> None:
        """Сохранить номер и размер страницы.

        Args:
            page: Номер страницы, начиная с 1.
            size: Размер страницы.
        """
        self.page = page
        self.size = size

    @property
    def offset(self) -> int:
        """Вычислить смещение для SQL LIMIT/OFFSET.

        Returns:
            Количество записей, которые нужно пропустить.
        """
        return (self.page - 1) * self.size


PaginationDep = Annotated[Pagination, Depends()]
"""Зависимость с параметрами пагинации."""
