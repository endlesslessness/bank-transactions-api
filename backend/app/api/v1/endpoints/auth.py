"""Эндпоинты аутентификации.

Слой тонкий: разбирает запрос, вызывает сервис и переводит доменные
исключения в коды ответа. Вся логика живёт в ``services.auth``.
"""

import logging

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.core.limiter import limiter
from app.models.user import User
from app.schemas.user import RefreshRequest, Token, UserCreate, UserLogin, UserRead
from app.services import auth as auth_service
from app.services.exceptions import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    UsernameAlreadyTakenError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Аутентификация"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Регистрация нового пользователя",
)
@limiter.limit("5/minute")
async def register(
    request: Request,
    response: Response,
    payload: UserCreate,
    session: SessionDep,
) -> User:
    """Зарегистрировать нового пользователя.

    Args:
        request: Запрос FastAPI (нужен rate limiter).
        response: Ответ FastAPI (нужен rate limiter для заголовков).
        payload: Данные нового пользователя.
        session: Асинхронная сессия базы данных.

    Returns:
        Созданный пользователь.

    Raises:
        HTTPException: 409, если email или логин уже заняты.
    """
    try:
        return await auth_service.register_user(session, payload)
    except (EmailAlreadyRegisteredError, UsernameAlreadyTakenError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        ) from exc


@router.post(
    "/login",
    response_model=Token,
    summary="Вход в систему",
)
@limiter.limit("10/minute")
async def login(
    request: Request,
    response: Response,
    payload: UserLogin,
    session: SessionDep,
) -> Token:
    """Аутентифицировать пользователя по email или логину.

    Args:
        request: Запрос FastAPI (нужен rate limiter).
        response: Ответ FastAPI (нужен rate limiter для заголовков).
        payload: Учётные данные.
        session: Асинхронная сессия базы данных.

    Returns:
        Пара access- и refresh-токенов.

    Raises:
        HTTPException: 401, если учётные данные неверны.
        HTTPException: 422, если не переданы ни email, ни логин.
    """
    if payload.email is None and payload.username is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Укажите email или логин",
        )

    try:
        user = await auth_service.authenticate_user(session, payload)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return await auth_service.issue_token_pair(user)


@router.post(
    "/refresh",
    response_model=Token,
    summary="Обновить access-токен",
)
@limiter.limit("20/minute")
async def refresh(
    request: Request,
    response: Response,
    payload: RefreshRequest,
    session: SessionDep,
) -> Token:
    """Выдать новую пару токенов по refresh-токену.

    Args:
        request: Запрос FastAPI (нужен rate limiter).
        response: Ответ FastAPI (нужен rate limiter для заголовков).
        payload: Тело с refresh-токеном.
        session: Асинхронная сессия базы данных.

    Returns:
        Новая пара access- и refresh-токенов.

    Raises:
        HTTPException: 401, если refresh-токен недействителен или истёк.
    """
    try:
        return await auth_service.refresh_access_token(session, payload.refresh_token)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@router.get(
    "/me",
    response_model=UserRead,
    summary="Текущий пользователь",
)
async def read_me(current_user: CurrentUser) -> User:
    """Вернуть профиль пользователя по access-токену.

    Args:
        current_user: Пользователь из access-токена.

    Returns:
        Профиль текущего пользователя.
    """
    return current_user
