"""Эндпоинты банковских переводов.

Слой тонкий: разбирает заголовки и параметры запроса, вызывает сервис
и переводит доменные исключения в коды ответа.
"""

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status

from app.api.deps import CurrentUser, PaginationDep, SessionDep
from app.core.limiter import limiter
from app.models.transaction import Transaction, TransactionStatus
from app.schemas.transaction import TransactionCreate, TransactionList, TransactionRead
from app.services import transaction as transaction_service
from app.services.exceptions import (
    AccountInactiveError,
    AccountNotFoundError,
    CurrencyMismatchError,
    DomainError,
    InsufficientFundsError,
    SameAccountTransferError,
    TransactionNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transactions", tags=["Транзакции"])


@router.post(
    "",
    response_model=TransactionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать перевод",
    responses={
        status.HTTP_409_CONFLICT: {
            "description": "Ключ идемпотентности уже использован"
        },
    },
)
@limiter.limit("20/minute")
async def create_transaction(
    request: Request,
    response: Response,
    payload: TransactionCreate,
    session: SessionDep,
    current_user: CurrentUser,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        description="Ключ идемпотентности для защиты от повторной оплаты",
    ),
) -> Transaction:
    """Перевести средства между своими счетами.

    Повторный запрос с тем же ``Idempotency-Key`` не создаёт вторую
    транзакцию, а возвращает созданную ранее, поэтому клиент может
    безопасно повторять запрос после сетевого сбоя.

    Args:
        request: Запрос FastAPI (нужен rate limiter).
        response: Ответ FastAPI (нужен rate limiter для заголовков).
        payload: Параметры перевода.
        session: Асинхронная сессия базы данных.
        current_user: Текущий авторизованный пользователь.
        idempotency_key: Ключ идемпотентности из заголовка.

    Returns:
        Созданная транзакция.

    Raises:
        HTTPException: 400, если не передан ключ идемпотентности.
        HTTPException: 404, если счёт не найден или чужой.
        HTTPException: 409, если перевод невозможен: тот же счёт,
            разные валюты, закрытый счёт или нехватка средств.
    """
    if idempotency_key is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Заголовок Idempotency-Key обязателен",
        )

    # Ключ приходит от клиента, поэтому используется только как
    # метка для поиска дубля, но никогда как часть SQL-выражения.
    key = idempotency_key.strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Заголовок Idempotency-Key не может быть пустым",
        )
    if len(key) > 64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Заголовок Idempotency-Key длиннее 64 символов",
        )

    try:
        transaction, created = await transaction_service.create_transfer(
            session,
            current_user.id,
            payload,
            key,
        )
    except (
        SameAccountTransferError,
        CurrencyMismatchError,
        AccountInactiveError,
        InsufficientFundsError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        ) from exc
    except AccountNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc
    except DomainError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.message,
        ) from exc

    if created:
        response.status_code = status.HTTP_201_CREATED
    else:
        # Повторный запрос вернул уже существующую транзакцию —
        # это не создание нового ресурса.
        response.status_code = status.HTTP_200_OK

    return transaction


@router.get(
    "",
    response_model=TransactionList,
    summary="История транзакций",
)
async def list_transactions(
    session: SessionDep,
    current_user: CurrentUser,
    pagination: PaginationDep,
    account_id: int | None = None,
    status_filter: Annotated[
        TransactionStatus | None,
        Query(alias="status", description="Фильтр по статусу транзакции"),
    ] = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> TransactionList:
    """Получить историю операций пользователя с фильтрами и пагинацией.

    Args:
        session: Асинхронная сессия базы данных.
        current_user: Текущий авторизованный пользователь.
        pagination: Параметры пагинации.
        account_id: Показать операции только по этому счёту.
        status_filter: Показать операции только с этим статусом.
        date_from: Показать операции начиная с указанного момента.
        date_to: Показать операции до указанного момента.

    Returns:
        Страница истории транзакций.
    """
    return await transaction_service.list_transactions(
        session,
        current_user.id,
        page=pagination.page,
        size=pagination.size,
        account_id=account_id,
        status=status_filter,
        date_from=date_from,
        date_to=date_to,
    )


@router.get(
    "/{transaction_id}",
    response_model=TransactionRead,
    summary="Детали транзакции",
)
async def get_transaction(
    transaction_id: int,
    session: SessionDep,
    current_user: CurrentUser,
) -> Transaction:
    """Вернуть транзакцию по её идентификатору.

    Args:
        transaction_id: Идентификатор транзакции.
        session: Асинхронная сессия базы данных.
        current_user: Текущий авторизованный пользователь.

    Returns:
        Найденная транзакция.

    Raises:
        HTTPException: 404, если транзакция не найдена или не
            принадлежит пользователю.
    """
    try:
        return await transaction_service.get_transaction(
            session,
            current_user.id,
            transaction_id,
        )
    except TransactionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc
