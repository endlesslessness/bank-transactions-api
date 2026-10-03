"""Эндпоинты банковских счетов.

Слой тонкий: разбирает запрос, вызывает сервис и переводит доменные
исключения в коды ответа.
"""

import logging

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.core.limiter import limiter
from app.models.account import Account
from app.schemas.account import AccountBalance, AccountCreate, AccountRead
from app.services import account as account_service
from app.services.exceptions import AccountNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/accounts", tags=["Счета"])


@router.get(
    "",
    response_model=list[AccountRead],
    summary="Список своих счетов",
)
async def list_accounts(
    session: SessionDep,
    current_user: CurrentUser,
) -> list[Account]:
    """Вернуть все счета текущего пользователя.

    Args:
        session: Асинхронная сессия базы данных.
        current_user: Текущий авторизованный пользователь.

    Returns:
        Счета пользователя от новых к старым.
    """
    return await account_service.list_accounts(session, current_user.id)


@router.post(
    "",
    response_model=AccountRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать счёт",
)
@limiter.limit("10/minute")
async def create_account(
    request: Request,
    response: Response,
    payload: AccountCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Account:
    """Открыть новый счёт с необязательным начальным остатком.

    Args:
        request: Запрос FastAPI (нужен rate limiter).
        response: Ответ FastAPI (нужен rate limiter для заголовков).
        payload: Параметры создаваемого счёта.
        session: Асинхронная сессия базы данных.
        current_user: Текущий авторизованный пользователь.

    Returns:
        Созданный счёт.
    """
    return await account_service.create_account(session, current_user.id, payload)


@router.get(
    "/{account_id}",
    response_model=AccountRead,
    summary="Детали счёта",
)
async def get_account(
    account_id: int,
    session: SessionDep,
    current_user: CurrentUser,
) -> Account:
    """Вернуть счёт по его идентификатору.

    Args:
        account_id: Идентификатор счёта.
        session: Асинхронная сессия базы данных.
        current_user: Текущий авторизованный пользователь.

    Returns:
        Найденный счёт.

    Raises:
        HTTPException: 404, если счёт не найден или принадлежит другому
            пользователю.
    """
    try:
        return await account_service.get_account(session, current_user.id, account_id)
    except AccountNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc


@router.get(
    "/{account_id}/balance",
    response_model=AccountBalance,
    summary="Баланс счёта",
)
async def get_account_balance(
    account_id: int,
    session: SessionDep,
    current_user: CurrentUser,
) -> AccountBalance:
    """Вернуть текущий баланс счёта.

    Args:
        account_id: Идентификатор счёта.
        session: Асинхронная сессия базы данных.
        current_user: Текущий авторизованный пользователь.

    Returns:
        Номер счёта, баланс и валюта.

    Raises:
        HTTPException: 404, если счёт не найден или принадлежит другому
            пользователю.
    """
    try:
        return await account_service.get_balance(session, current_user.id, account_id)
    except AccountNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc
