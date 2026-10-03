"""Агрегатор маршрутов API версии 1.

Собирает эндпоинты отдельных доменов в один роутер, который
подключается в ``app.main`` с префиксом ``/api/v1``.
"""

from fastapi import APIRouter

api_router = APIRouter()
