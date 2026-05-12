"""Research run API tests — require DB. M3: graph runs synchronously, returns COMPLETED."""

import pytest

from apps.api.dependencies.auth import DEV_DEFAULT_USER_ID


@pytest.mark.asyncio
async def test_create_run_with_empty_watchlist_fails(api_client) -> None:
    resp = await api_client.post("/api/v1/research-runs", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_run_returns_completed(api_client) -> None:
    resp = await api_client.post(
        "/api/v1/research-runs",
        json={"run_type": "MANUAL", "symbols": ["AAPL", "NVDA"]},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["run_type"] == "MANUAL"
    assert data["status"] == "COMPLETED"
    assert len(data["tickers"]) == 2
    ticker_symbols = {t["symbol"] for t in data["tickers"]}
    assert ticker_symbols == {"AAPL", "NVDA"}


@pytest.mark.asyncio
async def test_create_run_tickers_are_completed(api_client) -> None:
    resp = await api_client.post("/api/v1/research-runs", json={"symbols": ["TSLA"]})
    assert resp.status_code == 201
    tickers = resp.json()["data"]["tickers"]
    assert all(t["status"] == "COMPLETED" for t in tickers)


@pytest.mark.asyncio
async def test_create_run_uses_watchlist_when_no_symbols(api_client) -> None:
    await api_client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
    await api_client.post("/api/v1/watchlist", json={"symbol": "NVDA"})

    resp = await api_client.post("/api/v1/research-runs", json={})
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["status"] == "COMPLETED"
    symbols = {t["symbol"] for t in data["tickers"]}
    assert {"AAPL", "NVDA"}.issubset(symbols)


@pytest.mark.asyncio
async def test_get_run_by_id(api_client) -> None:
    create = await api_client.post("/api/v1/research-runs", json={"symbols": ["AAPL"]})
    run_id = create.json()["data"]["id"]

    resp = await api_client.get(f"/api/v1/research-runs/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == run_id


@pytest.mark.asyncio
async def test_get_nonexistent_run_returns_404(api_client) -> None:
    import uuid

    resp = await api_client.get(f"/api/v1/research-runs/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_research_runs(api_client) -> None:
    await api_client.post("/api/v1/research-runs", json={"symbols": ["AAPL"]})
    await api_client.post("/api/v1/research-runs", json={"symbols": ["NVDA"]})

    resp = await api_client.get("/api/v1/research-runs")
    assert resp.status_code == 200
    assert len(resp.json()["data"]) >= 2


@pytest.mark.asyncio
async def test_recommendations_populated_after_run(api_client) -> None:
    """After a run, GET /recommendations/latest returns data for those symbols."""
    await api_client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
    await api_client.post("/api/v1/research-runs", json={"symbols": ["AAPL"]})

    resp = await api_client.get("/api/v1/recommendations/latest")
    assert resp.status_code == 200
    data = resp.json()["data"]
    aapl = next((r for r in data if r["symbol"] == "AAPL"), None)
    assert aapl is not None
    assert aapl["neutral"] is not None
    assert aapl["neutral"]["score"] > 0
    assert aapl["neutral"]["action"] in (
        "BUY_CANDIDATE",
        "HOLD",
        "STRONG_BUY",
        "REDUCE",
        "NO_ACTION",
    )


# ── GET /research-runs/{run_id}/recommendations ───────────────────────────────


@pytest.mark.asyncio
async def test_run_recommendations_unknown_run_returns_404(api_client) -> None:
    import uuid

    resp = await api_client.get(f"/api/v1/research-runs/{uuid.uuid4()}/recommendations")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_run_recommendations_no_recs_returns_empty_list(
    api_client,
    db_session,
) -> None:
    """A run that exists but whose graph produced nothing returns empty recommendations."""
    import uuid as uuid_mod

    from db.models import ResearchRun

    # Create stale data first; the empty run endpoint must not leak these symbols.
    await api_client.post("/api/v1/research-runs", json={"symbols": ["TSLA"]})

    empty_run = ResearchRun(
        id=uuid_mod.uuid4(),
        user_id=DEV_DEFAULT_USER_ID,
        run_type="MANUAL",
        status="CREATED",
    )
    db_session.add(empty_run)
    await db_session.flush()

    resp = await api_client.get(f"/api/v1/research-runs/{empty_run.id}/recommendations")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert str(data["research_run_id"]) == str(empty_run.id)
    assert data["recommendations"] == []
    assert {r["symbol"] for r in data["recommendations"]} == set()


@pytest.mark.asyncio
async def test_run_recommendations_failed_run_has_no_recs(
    api_client,
    db_session,
) -> None:
    """A FAILED run with no recs returns run context + empty recommendations list."""
    import datetime as dt
    import uuid as uuid_mod

    from db.models import ResearchRun

    failed_run = ResearchRun(
        id=uuid_mod.uuid4(),
        user_id=DEV_DEFAULT_USER_ID,
        run_type="MANUAL",
        status="FAILED",
        started_at=dt.datetime.now(dt.UTC),
        finished_at=dt.datetime.now(dt.UTC),
    )
    db_session.add(failed_run)
    await db_session.flush()

    resp = await api_client.get(f"/api/v1/research-runs/{failed_run.id}/recommendations")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert str(data["research_run_id"]) == str(failed_run.id)
    assert data["status"] == "FAILED"
    assert data["recommendations"] == []


@pytest.mark.asyncio
async def test_run_recommendations_newer_run_scoped_correctly(api_client) -> None:
    """Newer run AAPL/AMD/NVDA endpoint returns only those symbols, not older TSLA."""
    await api_client.post("/api/v1/research-runs", json={"symbols": ["TSLA"]})
    newer = await api_client.post(
        "/api/v1/research-runs", json={"symbols": ["AAPL", "AMD", "NVDA"]}
    )
    newer_run_id = newer.json()["data"]["id"]

    resp = await api_client.get(f"/api/v1/research-runs/{newer_run_id}/recommendations")
    assert resp.status_code == 200
    data = resp.json()["data"]
    symbols = {r["symbol"] for r in data["recommendations"]}
    assert symbols == {"AAPL", "AMD", "NVDA"}
    assert "TSLA" not in symbols


@pytest.mark.asyncio
async def test_run_recommendations_older_run_returns_its_symbols(api_client) -> None:
    """Older TSLA run endpoint returns only TSLA, not newer run's symbols."""
    older = await api_client.post("/api/v1/research-runs", json={"symbols": ["TSLA"]})
    older_run_id = older.json()["data"]["id"]
    await api_client.post("/api/v1/research-runs", json={"symbols": ["AAPL", "AMD", "NVDA"]})

    resp = await api_client.get(f"/api/v1/research-runs/{older_run_id}/recommendations")
    assert resp.status_code == 200
    data = resp.json()["data"]
    symbols = {r["symbol"] for r in data["recommendations"]}
    assert symbols == {"TSLA"}


@pytest.mark.asyncio
async def test_run_recommendations_personalized_included(api_client) -> None:
    """Each recommendation item has neutral + personalized (or null) and evidence list."""
    run_resp = await api_client.post(
        "/api/v1/research-runs", json={"symbols": ["AAPL", "AMD", "NVDA"]}
    )
    run_id = run_resp.json()["data"]["id"]

    resp = await api_client.get(f"/api/v1/research-runs/{run_id}/recommendations")
    assert resp.status_code == 200
    recs = resp.json()["data"]["recommendations"]
    assert len(recs) == 3

    for item in recs:
        assert "symbol" in item
        assert "neutral" in item
        assert item["neutral"] is not None
        assert "personalized" in item
        assert "evidence" in item
        assert isinstance(item["evidence"], list)


@pytest.mark.asyncio
async def test_run_recommendations_amd_watchlist_action(api_client) -> None:
    """AMD with no portfolio → personalized must be WATCHLIST, NO_ACTION, or HOLD."""
    run_resp = await api_client.post(
        "/api/v1/research-runs", json={"symbols": ["AAPL", "AMD", "NVDA"]}
    )
    run_id = run_resp.json()["data"]["id"]

    resp = await api_client.get(f"/api/v1/research-runs/{run_id}/recommendations")
    assert resp.status_code == 200
    recs = resp.json()["data"]["recommendations"]

    amd = next((r for r in recs if r["symbol"] == "AMD"), None)
    assert amd is not None
    pers = amd.get("personalized")
    if pers is not None:
        assert pers["personal_action"] in ("WATCHLIST", "NO_ACTION", "HOLD"), (
            f"AMD personalized action unexpected: {pers['personal_action']}"
        )


@pytest.mark.asyncio
async def test_run_recommendations_run_context_fields(api_client) -> None:
    """Response includes run-level context fields."""
    run_resp = await api_client.post("/api/v1/research-runs", json={"symbols": ["AAPL"]})
    run_id = run_resp.json()["data"]["id"]

    resp = await api_client.get(f"/api/v1/research-runs/{run_id}/recommendations")
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert str(data["research_run_id"]) == run_id
    assert data["status"] == "COMPLETED"
    assert "run_type" in data
    assert "created_at" in data
    assert "started_at" in data
    assert "finished_at" in data
    assert isinstance(data["recommendations"], list)


@pytest.mark.asyncio
async def test_run_recommendations_does_not_affect_latest(api_client) -> None:
    """/recommendations/latest is unaffected by the new endpoint."""
    await api_client.post("/api/v1/research-runs", json={"symbols": ["TSLA"]})
    newer = await api_client.post(
        "/api/v1/research-runs", json={"symbols": ["AAPL", "AMD", "NVDA"]}
    )
    newer_run_id = newer.json()["data"]["id"]

    # New endpoint for older run returns TSLA scoped to that run
    older_run_resp = await api_client.get("/api/v1/research-runs")
    older_run_id = next(
        r["id"]
        for r in older_run_resp.json()["data"]
        if r["id"] != newer_run_id
    )
    older_recs = await api_client.get(
        f"/api/v1/research-runs/{older_run_id}/recommendations"
    )
    assert "TSLA" in {r["symbol"] for r in older_recs.json()["data"]["recommendations"]}

    # /latest still returns only the newest run's symbols
    latest = await api_client.get("/api/v1/recommendations/latest")
    latest_symbols = {d["symbol"] for d in latest.json()["data"]}
    assert "AAPL" in latest_symbols
    assert "TSLA" not in latest_symbols
