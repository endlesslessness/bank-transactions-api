"""SQLAlchemy-модель банковского счёта."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.transaction import Transaction
    from app.models.user import User


class Account(Base):
    """Банковский счёт пользователя.

    Денежные суммы хранятся в ``Numeric(18, 2)`` и читаются как
    ``Decimal`` — использование ``float`` привело бы к потере
    точности при сложении и сравнении.

    Attributes:
        id: Первичный ключ.
        user_id: Идентификатор владельца счёта.
        account_number: Номер счёта, уникальный.
        balance: Текущий баланс счёта.
        currency: Код валюты по ISO 4217.
        is_active: Признак активного счёта.
        created_at: Дата и время создания записи.
        user: Владелец счёта.
        outgoing: Транзакции, где счёт является отправителем.
        incoming: Транзакции, где счёт является получателем.
    """

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    account_number: Mapped[str] = mapped_column(String(34), unique=True)
    balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2, asdecimal=True),
        default=Decimal("0.00"),
        server_default=text("0"),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        server_default=text("'RUB'"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    user: Mapped[User] = relationship(back_populates="accounts")

    outgoing: Mapped[list[Transaction]] = relationship(
        back_populates="from_account",
        foreign_keys="Transaction.from_account_id",
    )

    incoming: Mapped[list[Transaction]] = relationship(
        back_populates="to_account",
        foreign_keys="Transaction.to_account_id",
    )
