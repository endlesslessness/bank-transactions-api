"""Тесты служебных маршрутов приложения."""

from httpx import AsyncClient


async def test_root_lists_service_sections(client: AsyncClient) -> None:
    """Корень API отвечает подсказкой, а не 404."""
    response = await client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["api"] == "/api/v1"
    assert body["docs"] == "/docs"
    assert body["health"] == "/health"
    assert body["service"]
    assert body["version"]


async def test_root_survives_redirects(client: AsyncClient) -> None:
    """Корень не редиректит: иначе браузер показал бы 307."""
    response = await client.get("/", follow_redirects=False)

    assert response.status_code == 200


async def test_health_returns_ok(client: AsyncClient) -> None:
    """Healthcheck отвечает статусом ``ok``."""
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
