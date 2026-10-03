"""Доменные исключения бизнес-логики.

Сервисы выбрасывают эти исключения вместо ``HTTPException``: так
бизнес-правила не зависят от HTTP-слоя, а эндпоинт превращает
исключение в нужный код ответа.
"""

from decimal import Decimal


class DomainError(Exception):
    """Базовое исключение бизнес-логики.

    Attributes:
        message: Текст ошибки, безопасный для показа клиенту.
    """

    def __init__(self, message: str) -> None:
        """Сохранить текст ошибки.

        Args:
            message: Текст ошибки, безопасный для показа клиенту.
        """
        super().__init__(message)
        self.message = message


class EmailAlreadyRegisteredError(DomainError):
    """Пользователь с таким email уже зарегистрирован."""


class UsernameAlreadyTakenError(DomainError):
    """Логин уже занят другим пользователем."""


class InvalidCredentialsError(DomainError):
    """Логин или пароль указаны неверно."""


class UserNotFoundError(DomainError):
    """Пользователь не найден."""


class AccountNotFoundError(DomainError):
    """Счёт не найден или принадлежит другому пользователю."""


class AccountInactiveError(DomainError):
    """Счёт закрыт и не может участвовать в операциях."""


class InsufficientFundsError(DomainError):
    """На счёте недостаточно средств для перевода.

    Attributes:
        available: Фактически доступный остаток.
        required: Требуемая сумма перевода.
    """

    def __init__(self, available: Decimal, required: Decimal) -> None:
        """Запомнить доступный остаток и требуемую сумму.

        Args:
            available: Фактически доступный остаток.
            required: Требуемая сумма перевода.
        """
        super().__init__(
            f"Недостаточно средств: доступно {available}, требуется {required}"
        )
        self.available = available
        self.required = required


class SameAccountTransferError(DomainError):
    """Перевод задан между одним и тем же счётом."""


class CurrencyMismatchError(DomainError):
    """Валюты счетов отправителя и получателя различаются.

    Attributes:
        from_currency: Валюта счёта-отправителя.
        to_currency: Валюта счёта-получателя.
    """

    def __init__(self, from_currency: str, to_currency: str) -> None:
        """Запомнить валюты, участвующие в переводе.

        Args:
            from_currency: Валюта счёта-отправителя.
            to_currency: Валюта счёта-получателя.
        """
        super().__init__(f"Валюты счетов не совпадают: {from_currency} и {to_currency}")
        self.from_currency = from_currency
        self.to_currency = to_currency


class TransactionNotFoundError(DomainError):
    """Транзакция не найдена или принадлежит другому пользователю."""
