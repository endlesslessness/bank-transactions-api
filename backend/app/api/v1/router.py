"""Агрегатор маршрутов API версии 1.

Собирает эндпоинты отдельных доменов в один роутер, который
подключается в ``app.main`` с префиксом ``/api/v1``.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import accounts, auth, transactions

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(accounts.router)
api_router.include_router(transactions.router)
