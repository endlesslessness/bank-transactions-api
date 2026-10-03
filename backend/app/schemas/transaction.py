"""Pydantic-схемы банковской транзакции."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.transaction import TransactionStatus


class TransactionCreate(BaseModel):
    """Запрос на перевод денежных средств.

    Ключ идемпотентности передаётся заголовком ``Idempotency-Key``,
    а не телом запроса: он относится к HTTP-вызову, а не к бизнес-сущности.

    Attributes:
        from_account_id: Счёт-отправитель.
        to_account_id: Счёт-получатель.
        amount: Сумма перевода, строго больше нуля.
        description: Назначение платежа, необязательное.
    """

    from_account_id: int = Field(gt=0)
    to_account_id: int = Field(gt=0)
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    description: str | None = Field(default=None, max_length=255)


class TransactionRead(BaseModel):
    """Транзакция в ответе API.

    Attributes:
        id: Идентификатор транзакции.
        from_account_id: Счёт-отправитель.
        to_account_id: Счёт-получатель.
        amount: Сумма перевода.
        currency: Код валюты по ISO 4217.
        status: Статус транзакции.
        description: Назначение платежа.
        idempotency_key: Ключ идемпотентности.
        created_at: Дата и время создания.
        completed_at: Дата и время завершения.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    from_account_id: int
    to_account_id: int
    amount: Decimal
    currency: str
    status: TransactionStatus
    description: str | None
    idempotency_key: str
    created_at: datetime
    completed_at: datetime | None


class TransactionList(BaseModel):
    """Страница списка транзакций.

    Attributes:
        items: Транзакции текущей страницы.
        total: Всего транзакций, удовлетворяющих фильтру.
        page: Номер текущей страницы, начиная с 1.
        size: Размер страницы.
    """

    items: list[TransactionRead]
    total: int
    page: int
    size: int
