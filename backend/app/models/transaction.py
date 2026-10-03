"""SQLAlchemy-модель транзакции и её статусы."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.account import Account


class TransactionStatus(StrEnum):
    """Статус банковской транзакции.

    Наследуется от ``StrEnum``, поэтому значение совместимо с ``str``
    и сериализуется в JSON как обычная строка.
    """

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


def _enum_values(enum_cls: type[TransactionStatus]) -> list[str]:
    """Вернуть значения элементов перечисления, а не их имена.

    Без этого SQLAlchemy сохранял бы в базу имена элементов
    (``PENDING``) вместо значений (``pending``), и CHECK-ограничение
    отклоняло бы любую запись.

    Args:
        enum_cls: Класс перечисления.

    Returns:
        Список значений элементов перечисления.
    """
    return [member.value for member in enum_cls]


class Transaction(Base):
    """Перевод денежных средств между счетами.

    Транзакция ссылается на два счёта одновременно, поэтому оба
    внешних ключа объявлены явно, а связи разведены через
    ``foreign_keys``. Ключ ``idempotency_key`` уникален — это
    основа защиты от повторного проведения одного и того же перевода.

    Attributes:
        id: Первичный ключ.
        from_account_id: Счёт-отправитель.
        to_account_id: Счёт-получатель.
        amount: Сумма перевода.
        currency: Код валюты по ISO 4217.
        status: Текущий статус транзакции.
        description: Назначение платежа, необязательное.
        idempotency_key: Ключ идемпотентности, уникальный.
        created_at: Дата и время создания записи.
        completed_at: Дата и время завершения, необязательное.
        from_account: Счёт-отправитель.
        to_account: Счёт-получатель.
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        index=True,
    )
    to_account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2, asdecimal=True),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[TransactionStatus] = mapped_column(
        SAEnum(
            TransactionStatus,
            native_enum=False,
            values_callable=_enum_values,
            validate_strings=True,
            length=16,
        ),
        nullable=False,
        server_default=TransactionStatus.PENDING.value,
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    from_account: Mapped[Account] = relationship(
        back_populates="outgoing",
        foreign_keys=[from_account_id],
    )

    to_account: Mapped[Account] = relationship(
        back_populates="incoming",
        foreign_keys=[to_account_id],
    )
