import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

from app.main import app


@pytest.mark.asyncio
async def test_health_database_connected() -> None:
    """GET /health retorna status ok com banco conectado."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()

    with patch("app.api.deps.AsyncSessionLocal") as mock_local:
        mock_local.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_local.return_value.__aexit__ = AsyncMock(return_value=False)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "database" in data
    assert "env" in data


@pytest.mark.asyncio
async def test_health_database_error() -> None:
    """GET /health retorna database=error quando banco falha."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=Exception("connection refused"))

    with patch("app.api.deps.AsyncSessionLocal") as mock_local:
        mock_local.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_local.return_value.__aexit__ = AsyncMock(return_value=False)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "error"
