"""M10.3: broker sync IntegrityError (race/duplicate) maps to safe HTTP responses."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError


@pytest.mark.asyncio
async def test_sync_flex_global_integrity_error_returns_409_safe_body(
    api_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IBKR_FLEX_ENABLED", "true")
    monkeypatch.setenv("IBKR_FLEX_TOKEN", "flex-secret-token-xyz")
    monkeypatch.setenv("IBKR_FLEX_QUERY_ID", "flex-query-123")
    from core.config import get_settings

    get_settings.cache_clear()

    async def boom(*_a: object, **_k: object) -> None:
        raise IntegrityError("stmt", {}, Exception("orig"))

    monkeypatch.setattr(
        "portfolio.trade_history_service.sync_ibkr_flex_executions",
        boom,
    )

    resp = await api_client.post("/api/v1/portfolio/sync-flex")
    assert resp.status_code == 409
    body = resp.json()
    detail = body.get("error", {}).get("message") or body.get("detail")
    if isinstance(detail, list):
        detail = detail[0].get("msg", "")
    text = str(body) + str(detail)
    assert "duplicate key" not in text.lower()
    assert "stmt" not in text.lower()
    assert "flex-secret-token" not in text
    assert "flex-secret-token" not in str(body)
    assert "Broker sync conflict" in text

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_sync_flex_account_integrity_error_returns_409(
    api_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IBKR_FLEX_ENABLED", "true")
    monkeypatch.setenv("IBKR_FLEX_TOKEN", "supersecretflex")
    monkeypatch.setenv("IBKR_FLEX_QUERY_ID", "q1")
    from core.config import get_settings

    get_settings.cache_clear()

    create = await api_client.post(
        "/api/v1/portfolio/broker-accounts",
        json={
            "provider": "IBKR",
            "display_name": "Flex IE Test",
            "connection_mode": "LOCAL_TWS",
            "readonly": True,
        },
    )
    assert create.status_code == 200
    account_id = create.json()["data"]["id"]

    async def boom(*_a: object, **_k: object) -> None:
        raise IntegrityError("insert", {}, Exception("dup"))

    monkeypatch.setattr(
        "portfolio.trade_history_service.sync_ibkr_flex_executions",
        boom,
    )

    resp = await api_client.post(f"/api/v1/portfolio/broker-accounts/{account_id}/sync-flex")
    assert resp.status_code == 409
    body = resp.json()
    blob = str(body)
    assert str(account_id) not in blob
    assert "supersecretflex" not in blob
    assert "duplicate key" not in blob.lower()

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_sync_ibkr_integrity_error_returns_409(
    api_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IBKR_ENABLED", "true")
    from core.config import get_settings

    get_settings.cache_clear()

    async def fake_to_thread(fn: object, *args: object, **kwargs: object) -> list[Any]:
        return []

    import asyncio

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    async def boom(*_a: object, **_k: object) -> None:
        raise IntegrityError("x", {}, Exception("y"))

    monkeypatch.setattr("portfolio.trade_history_service.sync_ibkr_executions", boom)

    resp = await api_client.post("/api/v1/portfolio/sync-ibkr")
    assert resp.status_code == 409
    assert "Broker sync conflict" in str(resp.json())

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_sync_ibkr_account_integrity_error_returns_409(
    api_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IBKR_ENABLED", "true")
    from core.config import get_settings

    get_settings.cache_clear()

    create = await api_client.post(
        "/api/v1/portfolio/broker-accounts",
        json={
            "provider": "IBKR",
            "display_name": "IBKR IE",
            "connection_mode": "LOCAL_TWS",
            "readonly": True,
        },
    )
    aid = create.json()["data"]["id"]

    async def fake_to_thread(fn: object, *args: object, **kwargs: object) -> list[Any]:
        return []

    import asyncio

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    async def boom(*_a: object, **_k: object) -> None:
        raise IntegrityError("x", {}, Exception("y"))

    monkeypatch.setattr("portfolio.trade_history_service.sync_ibkr_executions", boom)

    resp = await api_client.post(f"/api/v1/portfolio/broker-accounts/{aid}/sync-ibkr")
    assert resp.status_code == 409

    get_settings.cache_clear()
