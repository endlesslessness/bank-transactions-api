"""SQLAlchemy-модель пользователя."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.account import Account


class User(Base):
    """Пользователь системы.

    Уникальный ``email`` и ``username`` защищают идентификаторы, а
    ``hashed_password`` хранит только хеш пароля — сам пароль в базе
    отсутствует.

    Attributes:
        id: Первичный ключ.
        email: Адрес электронной почты, уникальный.
        username: Логин, уникальный.
        hashed_password: Хеш пароля, созданный через passlib.
        full_name: Полное имя, необязательное.
        is_active: Признак активного пользователя.
        created_at: Дата и время создания записи.
        accounts: Счета, принадлежащие пользователю.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    accounts: Mapped[list[Account]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
