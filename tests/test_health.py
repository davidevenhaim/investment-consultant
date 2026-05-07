from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routers.health import ServiceHealth


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_returns_ok(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "ok"
    assert body["data"]["version"] == "0.1.0"
    assert "request_id" in body["meta"]
    assert "timestamp" in body["meta"]


def test_health_includes_correlation_id(client: TestClient) -> None:
    resp = client.get("/api/v1/health", headers={"X-Correlation-ID": "test-123"})
    assert resp.headers["X-Correlation-ID"] == "test-123"


def test_health_generates_correlation_id_when_missing(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert "X-Correlation-ID" in resp.headers
    assert len(resp.headers["X-Correlation-ID"]) == 36  # UUID format


@patch("apps.api.routers.health._check_postgres", new_callable=AsyncMock)
@patch("apps.api.routers.health._check_redis", new_callable=AsyncMock)
@patch("apps.api.routers.health._check_chroma", new_callable=AsyncMock)
def test_health_detailed_all_ok(
    mock_chroma: AsyncMock,
    mock_redis: AsyncMock,
    mock_postgres: AsyncMock,
    client: TestClient,
) -> None:
    mock_postgres.return_value = ServiceHealth(status="ok", latency_ms=1.5)
    mock_redis.return_value = ServiceHealth(status="ok", latency_ms=0.5)
    mock_chroma.return_value = ServiceHealth(status="ok", latency_ms=2.0)

    resp = client.get("/api/v1/health/detailed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "ok"
    assert body["data"]["services"]["postgres"]["status"] == "ok"
    assert body["data"]["services"]["redis"]["status"] == "ok"
    assert body["data"]["services"]["chroma"]["status"] == "ok"


@patch("apps.api.routers.health._check_postgres", new_callable=AsyncMock)
@patch("apps.api.routers.health._check_redis", new_callable=AsyncMock)
@patch("apps.api.routers.health._check_chroma", new_callable=AsyncMock)
def test_health_detailed_degraded_when_one_fails(
    mock_chroma: AsyncMock,
    mock_redis: AsyncMock,
    mock_postgres: AsyncMock,
    client: TestClient,
) -> None:
    mock_postgres.return_value = ServiceHealth(status="error", message="Connection refused")
    mock_redis.return_value = ServiceHealth(status="ok", latency_ms=0.5)
    mock_chroma.return_value = ServiceHealth(status="ok", latency_ms=2.0)

    resp = client.get("/api/v1/health/detailed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "error"
    assert body["data"]["services"]["postgres"]["status"] == "error"
