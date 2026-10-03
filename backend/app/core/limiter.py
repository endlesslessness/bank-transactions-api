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
    # Заголовки X-RateLimit и Retry-After нужны клиенту, чтобы корректно
    # отступить после 429. slowapi требует от каждого эндпоинта с
    # декоратором @limiter.limit отдельный параметр response: Response —
    # без него он падает с ошибкой при попытке встроить заголовки.
    headers_enabled=True,
)
