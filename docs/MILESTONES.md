# Milestone History — Detailed Log

> Moved out of CLAUDE.md to keep context lean. CLAUDE.md holds the one-line summary
> per milestone; this file holds the full detail. Append new milestone detail here.

---

## M1 — Production skeleton

FastAPI, Docker Compose, Postgres, Redis, Celery, Chroma, Alembic, health endpoints, structured JSON logging, tests/lint/mypy.

## M2 — Core research database

Tables: research_runs, research_run_tickers, watchlist_symbols, investor_profiles, strategy_versions, prompt_versions, recommendations, evidence, job events, audit logs.

## M3 — LangGraph v0

Research graph runs ticker research and persists recommendations end-to-end.

## M4–M7 — Market / fundamentals / LLM / memory

- Market data ingestion + technical signals (yfinance, pandas-ta)
- Fundamentals snapshots + scoring
- Optional LLM analysis with strict Pydantic schemas; no direct action upgrades from LLM
- ChromaDB memory for previous recommendations and manual notes

## M8 — News

- `packages/news` with fake provider + NewsAPI provider
- `news_items` table
- `fetch_news` graph node
- News score in neutral recommendation
- `NEWS_ANALYSIS` and `NEWS_ITEM` evidence rows
- `GET /api/v1/news/{symbol}/latest`
- `NEWS_ENABLED=false` is valid; missing news never crashes a run

## M9 — Portfolio

- Tables: `portfolio_accounts`, `portfolio_positions`, `portfolio_snapshots`
- Portfolio fit score replaces old stub
- Personalized recommendation uses real portfolio context
- `position_sizing_json` added to personalized recs
- `GET/POST /api/v1/portfolio` endpoints
- Bug fixed: portfolio mutations now commit; research sessions see positions
- `load_portfolio_context` sets `current_position_weight > 0` when position exists
- `score_breakdown_json` moves `portfolio_context` from missing → completed; sets `component_quality_scores.portfolio_context = 1.0`; recomputes completeness

## M9.5 — Trade history + trading profile

New tables: `ibkr_executions`, `manual_trades`, `trading_profile_snapshots`

New packages:

- `packages/broker/ibkr/schemas.py`
- `packages/broker/ibkr/client.py`
- `packages/broker/ibkr/fake_client.py`
- `packages/broker/ibkr/mapper.py`
- `packages/broker/ibkr/trade_history.py`
- `packages/broker/ibkr/sync_runner.py`

`packages/portfolio/trading_profile.py` computes:

- FIFO matching, win rate, profit factor
- Avg winner/loser %, avg holding days
- Concentration score, disposition effect score, recency bias score
- Behavioral flags

`packages/portfolio/trade_history_service.py`:

- Sync IBKR executions into DB
- Merge IBKR + manual trades
- Build + save trading profile snapshots
- Get per-symbol stats

APIs added:

```
POST /api/v1/portfolio/trades
GET  /api/v1/portfolio/trades
GET  /api/v1/portfolio/trading-profile
POST /api/v1/portfolio/trading-profile/rebuild
GET  /api/v1/portfolio/trading-profile/{symbol}
POST /api/v1/portfolio/sync-ibkr
```

Research graph loads `symbol_trading_stats` and `behavioral_flags` into state. LLM prompt receives bounded trading profile context when available.

## M9.6 — Broker account support + IBKR connection fix

New table: `broker_accounts`

Nullable `broker_account_id` FK added to: `ibkr_executions`, `manual_trades`, `trading_profile_snapshots`

`IBKRClient` now uses `IBKRConnectionConfig`. Supports `connection_mode`:

- `LOCAL_TWS`
- `HOSTED_GATEWAY`

`readonly=False` is rejected at config level.
Secrets not stored in DB; only `secret_ref` metadata allowed.
Hosted gateway architecture documented in `docs/ibkr-hosted-gateway.md` and `docker-compose.ibkr-gateway.example.yml`.

APIs added:

```
GET   /api/v1/portfolio/broker-accounts
POST  /api/v1/portfolio/broker-accounts
GET   /api/v1/portfolio/broker-accounts/{id}
PATCH /api/v1/portfolio/broker-accounts/{id}
POST  /api/v1/portfolio/broker-accounts/{id}/sync-ibkr
POST  /api/v1/portfolio/sync-ibkr   ← dev default still works
```

**Critical IBKR event loop fix (M9.6):**
Old bug: `ib_insync` raised "Future attached to a different loop" inside FastAPI/Uvicorn.
Fix: `packages/broker/ibkr/sync_runner.py` runs the full connect → fetch → disconnect sequence inside `asyncio.to_thread` + `asyncio.run()`, giving `ib_insync` its own isolated event loop. This is working.

Verified real IBKR sync result:

```json
{ "inserted": 0, "message": "Synced 0 executions from IBKR; 0 new." }
```

Logs confirmed: `ibkr_connect_attempt` → `ibkr_connected` → `ibkr_executions_fetched` → `ibkr_disconnected` → `ibkr_executions_synced`. `broker_accounts.last_sync_status` = `"success"`.

**Important discovery:** `reqExecutions` / `reqExecutionsAsync` only returns executions from the current TWS/Gateway session — not 12-month historical fills. Zero executions = no current-session fills, not a connection failure. For real historical trade history, use IBKR Flex Query (M9.7).

## M9.7 — IBKR Flex Query historical trade import

**Goal:** Implement Flex Query as a separate read-only source for 12-month historical trades. Keep existing `reqExecutions` current-session sync intact.

Files:

```
packages/broker/ibkr/flex_schemas.py
packages/broker/ibkr/flex_client.py
packages/broker/ibkr/flex_parser.py       ← XML/CSV parsing
packages/broker/ibkr/flex_mapper.py       ← Flex trade → IBKRExecution
packages/broker/ibkr/fake_flex_client.py
```

**Config design:**

- `flex_query_id` stored in `broker_accounts.metadata_json`
- `flex_token_secret_ref` stored as reference only — never raw token in DB
- Dev: env var `IBKR_FLEX_TOKEN` acceptable if clearly marked local/dev

**APIs:**

```
POST /api/v1/portfolio/broker-accounts/{id}/sync-flex
POST /api/v1/portfolio/sync-flex   ← dev default
```

Endpoint flow:

1. Resolve broker account
2. Fetch Flex statement/trades via Flex Query API
3. Normalize to `IBKRExecution` schema via mapper
4. Save via `sync_ibkr_executions(..., broker_account_id=...)`
5. Rebuild trading profile for that `broker_account_id`
6. Commit
7. Return `{ inserted, fetched, profile_snapshot_id }`

**Services reused (do not rewrite):**

- `portfolio.trade_history_service.sync_ibkr_executions()`
- `portfolio.trade_history_service.load_all_executions()`
- `portfolio.trade_history_service.build_and_save_profile()`
- `portfolio.trade_history_service.get_symbol_trading_stats()`
- `broker.ibkr.schemas.IBKRExecution`

**Safety constraints:**

- Read-only only — never submit orders
- No raw credentials in DB fields
- `IBKR_ENABLED=false` must not break anything
- Flex failure must not crash research runs — degrade gracefully
- Normalize Flex data through internal schemas before touching portfolio/research graph

## M11 — Backtesting + Learning Loop

New tables: `recommendation_outcomes`, `learning_events`

New packages:

- `packages/backtesting/__init__.py`
- `packages/backtesting/schemas.py` — `ForwardOutcome` dataclass
- `packages/backtesting/service.py` — `compute_forward_outcome`, `measure_recommendation_outcome`, `measure_latest_recommendations`, `generate_learning_event_from_outcome`
- `packages/backtesting/repository.py` — `RecommendationOutcomeRepository`, `LearningEventRepository`

Migration: `g8h9i0j1k2l3_add_backtesting_tables.py`

APIs added:

```
POST /api/v1/backtesting/outcomes/measure-latest
GET  /api/v1/backtesting/outcomes
GET  /api/v1/backtesting/learning-events
POST /api/v1/backtesting/learning-events/{id}/review
```

Design:

- All outcome logic is deterministic (no LLM in M11)
- `compute_forward_outcome` returns `INSUFFICIENT_DATA` — never raises — when bars are sparse
- Outcomes are unique on `(recommendation_type, recommendation_id, horizon_days, benchmark_symbol)` — idempotent re-measurement
- Learning events are rule-based: BUY→LOSS, HOLD→MISSED_UPSIDE, REDUCE→MISSED_UPSIDE, big drawdown
- All endpoints are user-scoped via `CurrentUser`
- Uses existing `MarketPriceRepository.get_bars()` for price data

Outcome label rules:

```
BUY_CANDIDATE / STRONG_BUY:
  +3% return or positive relative return  → WIN
  -3% return or -5% relative             → LOSS
  otherwise                               → NEUTRAL

HOLD:
  +10% forward return                     → MISSED_UPSIDE
  -3% forward return                      → LOSS
  otherwise                               → NEUTRAL

REDUCE / SELL / NO_ACTION:
  -5% forward return                      → AVOIDED_LOSS
  +10% forward return                     → MISSED_UPSIDE
  otherwise                               → NEUTRAL
```

Tests: `tests/backtesting/test_outcome_service.py` (21), `tests/api/test_backtesting.py` (12).

Known limitations / follow-ups:

- No LLM analysis of learning events yet — all rule-based
- No personalized recommendation outcome measurement (only NEUTRAL for now)
- `min_bar_fraction` threshold is approximate — can be tuned per horizon
- No outcome aggregation endpoints (win rate summary, by symbol, by action) yet
- `benchmark_symbol` defaults to SPY but no SPY bars in seed data — benchmark fields may be null

## M12 — Async Research Runs + Twice-Daily Scheduler

New enum values:

- `ResearchRunStatus.QUEUED` — run created, waiting for Celery worker
- `ResearchRunType.SCHEDULED` — run created by Celery beat

New settings (all in `core/config.py`, override via env):

```
SCHEDULED_RESEARCH_ENABLED=false      # default off — set true to activate beat runs
SCHEDULED_RESEARCH_USER_ID=00000000-0000-0000-0000-000000000001
SCHEDULED_RESEARCH_HOURS=9,16         # UTC hours for beat schedule
SCHEDULED_RESEARCH_MINUTE=30
```

New Celery tasks (`apps/worker/tasks/research.py`):

- `run_research_run_task(research_run_id, user_id, broker_account_id)` — executes one run
- `scheduled_research_task()` — creates + enqueues runs for configured user's watchlist

Testable async helpers (call directly in tests):

- `_execute_research_run_async(research_run_id, user_id, broker_account_id)`
- `_execute_scheduled_research_async()`

API change (`POST /api/v1/research-runs`):

- New field: `async_execution: bool = false`
- `false` (default): existing sync behavior, returns COMPLETED
- `true`: creates QUEUED run, enqueues Celery task, returns immediately

Repository additions (`packages/db/repositories.py`):

- `ResearchRunRepository.get_by_id_internal(run_id)` — no user filter, for worker
- `ResearchRunRepository.has_recent_scheduled_run(user_id, hours)` — dedup guard

Run lifecycle:

```
Sync path:  CREATED → RUNNING → COMPLETED / FAILED
Async path: CREATED → QUEUED → RUNNING → COMPLETED / FAILED
```

Trigger async run manually:

```bash
RUN_ID=$(curl -s -X POST http://localhost:8000/api/v1/research-runs \
  -H "Content-Type: application/json" \
  -d '{"symbols":["AAPL"],"async_execution":true}' | jq -r '.data.id')
curl -s http://localhost:8000/api/v1/research-runs/$RUN_ID | jq '.data | {id,status}'
```

Trigger scheduled task manually:

```bash
make trigger-scheduled-research
# or:
docker compose exec -T worker celery -A apps.worker.celery_app call \
  apps.worker.tasks.research.scheduled_research_task
```

Known limitations:

- Scheduled research targets `SCHEDULED_RESEARCH_USER_ID` only (dev default)
- No Celery task retry/backoff yet — `max_retries=0`
- No UI showing async run progress
- Beat schedule built once at import time from `get_settings()`; changing
  `SCHEDULED_RESEARCH_HOURS` requires worker restart

## M12.1 — Historical Graph Replay Job Seeding

Replay creates dated research runs that look like historical advisor decisions. Useful for
pipeline testing and "follow the real advisor" backtests, but **not institutional-grade
historical backtests** (see as-of-date limitations table below).

### Data model (no migration needed)

`ResearchRun.metadata_json` (JSONB) stores:

```json
{
  "historical_replay": true,
  "replay_batch_id": "<uuid>",
  "as_of_date": "2026-01-15",
  "source": "historical_graph_replay",
  "cadence": "weekly"
}
```

`ResearchRunType.HISTORICAL_REPLAY` added (String column, no DB migration needed).
`ResearchState.as_of_date: str | None` added — carried through graph to persist node.

### Timestamp override for advisor backtest compatibility

When a replay run completes:

- `ResearchRun.finished_at` → `as_of_date 16:00 UTC`
- `NeutralRecommendation.created_at` → `as_of_date 16:00 UTC`

Ensures advisor backtest queries (`ResearchRun.finished_at >= start_date`) find replay runs
in the correct date window; `NeutralRecommendation.created_at` used for chronological trade placement.

### Replay batch API

```
POST /api/v1/research-runs/historical-replay
```

Request:

```json
{
  "start_date": "2026-01-01",
  "end_date": "2026-05-13",
  "symbols": ["AAPL", "NVDA"],
  "cadence": "weekly",
  "async_execution": true
}
```

Cadences: `daily`, `weekly`, `monthly`. Default `weekly`. Max 120 runs. Always async (sync → 422).

Response:

```json
{
  "data": {
    "replay_batch_id": "...",
    "count": 20,
    "runs": [{"id": "...", "as_of_date": "2026-01-01", "status": "QUEUED", "symbols": [...]}]
  }
}
```

Replay runs are classified as `REAL` for advisor backtest source filtering (no `scenario_seed` flag).

## M12.2 — As-Of-Date Aware Nodes

Goal: important graph nodes respect `state.as_of_date` so historical replay runs do not use
future market or news data.

### Market data (`ensure_price_history` + `fetch_market_data` node)

- `as_of_date: dt.date | None` parameter added to `ensure_price_history()` in `packages/market_data/service.py`
- Reference date (`ref_date`) is `as_of_date` for replay, `today` for live runs
- Staleness check uses `ref_date`; `fetch_end` capped at `ref_date` (never fetches future bars)
- `repo.get_bars()` called with `end_date=as_of_date` — returned slice always capped
- `compute_signals` passes same `as_of_date` to SPY benchmark fetch

### News (`fetch_news_for_symbol` + `fetch_news` node)

- `as_of_date: dt.date | None` added to `fetch_news_for_symbol()` in `packages/news/service.py`
- **Replay path**: skips external provider entirely; reads DB via `NewsItemRepository.get_recent()` with `until=as_of_date EOD`
- **Live path**: unchanged
- `get_recent()` gained `until: dt.datetime | None` parameter (`published_at <= until`)

### Debug metadata

`fetch_market_data_ok`, `compute_signals_ok`, `node_fetch_news_ok` log lines include `as_of_date`.

### As-of-date status table

| Component                        | Status                                                      |
| -------------------------------- | ----------------------------------------------------------- |
| Market data bars                 | ✅ Capped at `as_of_date`                                   |
| SPY benchmark for signals        | ✅ Capped at `as_of_date`                                   |
| News articles                    | ✅ DB-only, capped at `as_of_date`                          |
| Fundamentals snapshot            | ⚠️ Still uses latest snapshot; no as-of-date filter         |
| Memory/ChromaDB retrieval        | ⚠️ Retrieves current memory; no temporal filter             |
| Portfolio context                | ⚠️ Uses current portfolio positions                         |
| Provider-sourced historical news | ⚠️ NewsAPI free tier limited history; DB must be pre-seeded |

## M12.7 — Historical Replay Batch Observability

New API endpoints (`apps/api/routers/research_runs.py`):

```
GET  /api/v1/research-runs/historical-replay/{replay_batch_id}
     → batch status: total, completed/failed/running/queued counts,
       progress_pct, elapsed_seconds, per-run list with as_of_date + status
POST /api/v1/research-runs/historical-replay/{replay_batch_id}/backtest
     → advisor backtest over a completed replay batch;
       date window derived from batch min/max as_of_date;
       supports initial_positions (pre-seeded holdings at start_date price)
```

New CLI tool (`apps/cli/replay_status.py`):

```bash
python -m apps.cli.replay_status <replay_batch_id> [--user-id <uuid>]
```

Repository: `ResearchRunRepository.get_by_replay_batch_id(replay_batch_id, user_id)`.

Bug fix: replay Celery tasks get an isolated event loop (same pattern as `sync_runner.py`).

## M12.7.2 — Position-Aware Recommendation Evaluation

New API endpoints:

```
GET  /api/v1/research-runs/historical-replay/{replay_batch_id}/report
     → deterministic quality report; no LLM, no external I/O
POST /api/v1/research-runs/historical-replay/{replay_batch_id}/evaluation
```

New module (`packages/backtesting/replay_report.py`):

- `build_report_point(...)` — one timeline dict per run×symbol
- `build_timeline_changes(points)` — per-step change records with `explanation` string
- `build_timeline_summary(points)` — aggregate stats
- Pure Python: no DB, no LLM, no I/O

`advisor_simulation.run_advisor_backtest()` gains:

- `pinned_run_ids: list[uuid.UUID] | None` — bypass date/source filter
- `initial_positions: list[dict] | None` — pre-seed holdings priced at `start_date`; raises `ValueError` if cost exceeds `initial_cash`

New schemas (`packages/db/schemas.py`): `InitialPositionItem`, `ReplayBatchBacktestRequest`.

Repository additions:

- `RecommendationRepository.get_neutral_recs_by_run_ids(run_ids)`
- `RecommendationRepository.get_latest_personalized_by_neutral_ids(neutral_ids)`

Tests: `tests/api/test_historical_replay.py`, `tests/api/test_replay_report.py`,
`tests/backtesting/test_advisor_simulation.py`.
