"""Rate limiting на основе slowapi.

Лимитчик создаётся один раз на уровне модуля: декоратор ``@limiter.limit``
используется в эндпоинтах, поэтому объект должен быть общим. Ключом
выступает IP-адрес клиента, а значение ``settings.RATE_LIMIT`` задаёт
предел по умолчанию для всех маршрутов.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT],
    # slowapi отдаёт TooManyRequests без CORS-заголовков, из-за чего
    # браузер показывает ошибку вместо внятного ответа. Заголовки
    # проставляет middleware, а не обработчик.
    headers_enabled=True,
)
