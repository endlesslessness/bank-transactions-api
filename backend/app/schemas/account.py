"""Pydantic-схемы банковского счёта."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class AccountCreate(BaseModel):
    """Запрос на создание счёта.

    Attributes:
        currency: Код валюты по ISO 4217, например ``RUB``.
        initial_balance: Необязательный начальный остаток счёта.
    """

    currency: str = Field(
        default="RUB",
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    )
    initial_balance: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=16,
        decimal_places=2,
    )


class AccountRead(BaseModel):
    """Счёт в ответе API.

    Attributes:
        id: Идентификатор счёта.
        user_id: Идентификатор владельца.
        account_number: Номер счёта.
        balance: Текущий остаток.
        currency: Код валюты по ISO 4217.
        is_active: Признак активного счёта.
        created_at: Дата и время создания.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    account_number: str
    balance: Decimal
    currency: str
    is_active: bool
    created_at: datetime


class AccountBalance(BaseModel):
    """Ответ с балансом счёта.

    Attributes:
        account_id: Идентификатор счёта.
        account_number: Номер счёта.
        balance: Текущий остаток.
        currency: Код валюты по ISO 4217.
    """

    account_id: int
    account_number: str
    balance: Decimal
    currency: str
