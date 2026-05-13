# Investment Research Agent — Claude Code Context

> This file is the single source of truth for Claude Code working on this project.
> Read this fully before writing any code, creating any file, or making any architectural decision.

---

## What we are building

A **private investment research operating system** — not a trading bot.

The system runs automated research on a small watchlist of stocks (3–5 tickers), twice per day. It analyzes data, remembers previous research, produces structured recommendations, and eventually learns from its mistakes.

**What it is NOT:**
- Not a trading bot. No automated order execution. Ever.
- Not an LLM that answers "should I buy?" The LLM is an analyst, not the decision-maker.
- Not a simple script. This is a production-grade, versioned, auditable research system.

**Core principle: LLM as analyst, deterministic engine as decision-maker.**

Good LLM tasks:
- Summarize news
- Extract risk events
- Compare new info to previous thesis
- Generate bull/bear case narrative
- Identify missing details
- Write the final human-readable explanation

Bad LLM task:
- "Should I buy this stock?" ← Never. The scoring engine decides.

---

## Project location

All code lives inside: `investment-consultant/`

```
investment-consultant/
├── CLAUDE.md                  ← this file
├── docker-compose.yml
├── pyproject.toml
├── Makefile
├── .env.example
├── README.md
│
├── apps/
│   ├── api/                   ← FastAPI service
│   ├── worker/                ← Celery worker
│   └── cli/                   ← CLI tools
│
└── packages/
    ├── core/                  ← shared config, logging, errors
    ├── db/                    ← SQLAlchemy models, migrations, repos
    ├── broker/                ← IBKR via ib_insync (read-only)
    ├── market_data/           ← yfinance + Polygon providers
    ├── news/                  ← NewsAPI provider
    ├── filings/               ← SEC EDGAR (later)
    ├── memory/                ← ChromaDB client, retriever, indexer
    ├── ai/                    ← Claude API client, prompts, schemas
    ├── research_graph/        ← LangGraph research workflow
    ├── decision_engine/       ← deterministic scoring + policy
    ├── backtesting/           ← backtesting.py engine (later)
    └── reports/               ← markdown + HTML report generation
```

The UI is a **separate project** using an existing Next.js skeleton. Do not create any frontend code here. The API must expose clean, typed REST endpoints that the frontend will consume later.

---

## Tech stack — every version is pinned

### Runtime
- Python 3.12

### Web & API
- FastAPI (latest stable)
- Uvicorn
- Pydantic v2 — all schemas, all LLM outputs, all API payloads

### Database
- Supabase PostgreSQL (local Docker for dev)
- SQLAlchemy 2 with async support
- Alembic for migrations

### Task queue
- Redis
- Celery with Celery Beat for scheduling

### AI & agents
- `anthropic` SDK — Claude Sonnet 4 for orchestration, Claude Haiku 4.5 for sub-tasks
- LangGraph — multi-node research workflow
- ChromaDB — vector memory store

### Data providers
- `ib_insync` — Interactive Brokers (read-only)
- `yfinance` — OHLCV + fundamentals (initial)
- `pandas-ta` — technical indicators
- `NewsAPI` — news headlines

### Dev tooling
- Docker Compose — one command to run everything
- Ruff — linting + formatting
- mypy — type checking
- pytest — testing
- structured logging (JSON, correlation IDs)

---

## Architecture: how the system works

### High-level flow (runs twice daily)

```
Scheduler (Celery Beat)
    ↓
FastAPI trigger / Celery task
    ↓
LangGraph Research Flow (per ticker)
    ↓
Data Providers + ChromaDB + Claude
    ↓
Deterministic Scoring Engine
    ↓
Risk Policy Engine (hard gates)
    ↓
Neutral Recommendation
    ↓
IBKR Portfolio Context
    ↓
Personalized Recommendation
    ↓
Report Generation
    ↓
Persist to Postgres + Index to ChromaDB
```

### Two-recommendation design

Every run produces TWO recommendations per ticker:

**Neutral recommendation** — stock-only view
- Question: "Is this security attractive on its own merits?"
- Uses: market data, technicals, news, memory, fundamentals
- Does NOT use: portfolio, position size, cost basis, cash

**Personalized recommendation** — portfolio-aware view
- Question: "Given the neutral view and MY portfolio, what should I do?"
- Uses: neutral recommendation + IBKR position + risk profile
- Can override neutral: stock might be BUY_CANDIDATE but HOLD because position is already at max weight

### Recommendation vocabulary

Use only these action labels — never raw "BUY/SELL/HOLD":

```
STRONG_BUY      — score 85-100, risk policy passes
BUY_CANDIDATE   — score 70-84
HOLD            — score 50-69
REDUCE          — score 35-49
SELL            — score 0-34 with position
NO_ACTION       — score 0-34 without position
WATCHLIST       — interesting but missing data
```

---

## LangGraph research flow

### Full graph (build toward this)

```
START
  ↓ LoadRunContext
  ↓ LoadTickerContext
  ↓ RetrieveResearchMemory      ← ChromaDB: previous thesis, last rec, risks, past mistakes
  ↓ FetchMarketData             ← yfinance OHLCV
  ↓ ComputeTechnicalSignals     ← pandas-ta: RSI, MACD, EMA, momentum, volatility
  ↓ FetchNews                  ← NewsAPI
  ↓ AnalyzeNewsWithLLM          ← Claude: summarize, extract risks, sentiment score
  ↓ CompareToPreviousThesis     ← Claude: what changed? thesis drift?
  ↓ MissingDetailsCheck         ← Claude: what important info is missing?
  ↓ NeutralScoring              ← DETERMINISTIC: scoring engine, no LLM
  ↓ CreateNeutralRecommendation ← Pydantic model, saved to DB
  ↓ LoadPortfolioContext        ← IBKR snapshot from DB
  ↓ ApplyPersonalRiskPolicy     ← DETERMINISTIC: policy engine, no LLM
  ↓ CreatePersonalizedRecommendation ← Pydantic model, saved to DB
  ↓ WriteFinalExplanation       ← Claude: human-readable summary
  ↓ PersistResults              ← Postgres
  ↓ IndexReportToChroma         ← ChromaDB
  ↓ END
```

### Early simplified graph (Milestone 3)

```
START
  ↓ LoadTickerContext
  ↓ RetrieveMemory
  ↓ FetchMarketData (mock initially)
  ↓ ComputeSignals
  ↓ NeutralRecommendation
  ↓ PersonalizedRecommendation
  ↓ PersistResults
  ↓ END
```

### LangGraph state

All nodes share a typed state object. Never pass raw dicts between nodes.

```python
class ResearchState(TypedDict):
    # run context
    run_id: str
    symbol: str
    as_of_time: datetime
    strategy_version: str
    prompt_version: str

    # retrieved memory
    previous_thesis: str | None
    last_recommendation: dict | None
    past_mistakes: list[dict]

    # market data
    ohlcv: pd.DataFrame | None
    technical_signals: dict | None

    # news
    news_items: list[dict]
    news_analysis: NewsAnalysis | None  # Pydantic

    # LLM outputs
    thesis_comparison: ThesisComparison | None  # Pydantic
    missing_details: MissingDetailsResult | None  # Pydantic
    bull_bear_case: BullBearCase | None  # Pydantic

    # scoring
    score_breakdown: ScoreBreakdown | None  # Pydantic
    neutral_recommendation: NeutralRecommendation | None  # Pydantic

    # portfolio
    portfolio_snapshot: PortfolioSnapshot | None
    personalized_recommendation: PersonalizedRecommendation | None  # Pydantic

    # errors + quality
    errors: list[str]
    data_quality_score: float
    confidence_penalties: list[float]
```

---

## Deterministic scoring engine

The scoring engine is the decision authority. No LLM involved.

### Score components

```
Technical score:     0–20  (RSI, MACD, momentum, moving averages)
Fundamental score:   0–20  (P/E, P/B, revenue growth — later)
Valuation score:     0–15  (vs sector, vs history — later)
News score:          0–15  (sentiment, event severity)
Portfolio fit:       0–15  (concentration, correlation)
Risk score:          0–15  (volatility, beta, drawdown)
─────────────────────────
Total:               0–100
```

### Action mapping

```python
def score_to_action(score: float, has_position: bool) -> RecommendationAction:
    if score >= 85:   return STRONG_BUY      # if risk policy passes
    if score >= 70:   return BUY_CANDIDATE
    if score >= 50:   return HOLD
    if score >= 35:   return REDUCE
    if has_position:  return SELL
    return NO_ACTION
```

### Risk policy hard gates

These override any score:

```python
NO_BUY if current_position_weight > max_single_stock_weight
NO_BUY if confidence < minimum_confidence_threshold
NO_BUY if data_quality_score < minimum_data_quality
NO_BUY if missing_details.severity == "CRITICAL"
NO_STRONG_BUY before earnings (unless explicitly allowed)
NEVER automated trading
NEVER options, margin, or shorting
```

---

## Database schema — core tables

Every table must have `created_at` and `updated_at`. Use UUIDs for all PKs.

### Key tables

**research_runs** — one row per automated run
```sql
id, run_type, status, started_at, finished_at,
strategy_version_id, prompt_version_id,
error_message, created_at
```

**research_run_tickers** — one row per ticker per run
```sql
id, research_run_id, symbol, status,
started_at, finished_at, error_message
```

**neutral_recommendations** — the stock-only view
```sql
id, research_run_id, symbol, action, score, confidence,
time_horizon, score_breakdown_json, what_changed_json,
main_reasons_json, main_risks_json, missing_details_json,
final_reason, strategy_version_id, prompt_version_id,
as_of_time, price_at_recommendation, created_at
```

**personalized_recommendations** — the portfolio-aware view
```sql
id, neutral_recommendation_id, portfolio_snapshot_id,
investor_profile_id, symbol, personal_action,
position_sizing_json, policy_checks_json,
current_position_weight, max_allowed_weight,
personal_reason, created_at
```

**recommendation_evidence** — every piece of evidence cited
```sql
id, recommendation_id, recommendation_type, evidence_type,
source, source_id, summary, url, published_at,
payload_json, created_at
```

**strategy_versions** — versioned scoring config
```sql
id, version, description, scoring_config_json,
risk_policy_json, is_active, created_at
```

**prompt_versions** — versioned LLM prompts
```sql
id, name, version, prompt_text, output_schema_json,
is_active, created_at
```

**audit_logs** — immutable event trail
```sql
id, event_type, entity_type, entity_id, actor,
payload_json, correlation_id, created_at
```

---

## ChromaDB memory collections

### Initial collections
```
company_research_memory     ← previous theses, analysis notes
recommendation_reports      ← full run reports
personal_investment_notes   ← manual notes about positions
```

### Later collections
```
filing_chunks               ← SEC 10-K/10-Q chunked
earnings_transcript_chunks  ← earnings call transcripts
news_summaries              ← LLM-summarized news
recommendation_postmortems  ← post-mortem reports
strategy_lessons            ← lessons extracted from failures
mistake_patterns            ← recurring error patterns
```

### Retrieval strategy (important)

Never pure semantic search alone. Before every research run, retrieve:
1. Symbol-filtered: `where symbol == ticker` — always
2. Recency-weighted: prefer items from last 30 days
3. Similarity: semantic match on current context

Retrieve in this order:
1. Previous thesis for this symbol
2. Last recommendation for this symbol
3. Important risks flagged in previous runs
4. Past mistakes relevant to this symbol or pattern

---

## Claude API usage

### Model selection
- Orchestration / synthesis: `claude-sonnet-4-20250514`
- Structured extraction / sub-tasks: `claude-haiku-4-5-20251001`

### All LLM outputs must be Pydantic-validated

```python
# Every LLM call returns a typed Pydantic model
# If parsing fails → log error, apply confidence penalty, continue
# Never let LLM failure crash a research run

class NewsAnalysis(BaseModel):
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    key_events: list[str]
    risk_events: list[str]
    what_changed: str
    confidence: float = Field(ge=0.0, le=1.0)

class MissingDetailsResult(BaseModel):
    missing_details: list[str]
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    can_continue: bool
    confidence_penalty: float = Field(ge=0.0, le=1.0)
```

### Graceful degradation

```python
try:
    result = await llm_client.analyze_news(...)
    state["news_analysis"] = result
except LLMParseError:
    state["errors"].append("news_analysis_failed")
    state["confidence_penalties"].append(0.15)
    state["news_analysis"] = None
    # continue — never raise
```

---

## API design

### Base URL: `/api/v1`

### Key endpoints

```
POST   /research-runs              ← trigger a manual run
GET    /research-runs              ← list runs with status
GET    /research-runs/{id}         ← run detail + ticker results

GET    /recommendations/latest     ← latest rec per symbol
GET    /recommendations/{id}       ← full recommendation detail
GET    /recommendations/{id}/evidence ← evidence for a recommendation

GET    /portfolio/snapshot         ← latest IBKR portfolio snapshot
GET    /portfolio/history          ← historical snapshots

GET    /watchlist                  ← current watchlist
POST   /watchlist                  ← add symbol
DELETE /watchlist/{symbol}         ← remove symbol

GET    /strategy/versions          ← all strategy versions
GET    /strategy/active            ← current active strategy

GET    /health                     ← service health check
GET    /health/detailed            ← all services (DB, Redis, Chroma, IBKR)
```

### Response envelope

All responses use a consistent envelope:

```json
{
  "data": { ... },
  "meta": {
    "request_id": "uuid",
    "timestamp": "ISO8601"
  }
}
```

Errors:
```json
{
  "error": {
    "code": "RECOMMENDATION_NOT_FOUND",
    "message": "Human readable message",
    "detail": { ... }
  },
  "meta": { ... }
}
```

---

## Services in Docker Compose

```yaml
services:
  api:       FastAPI, port 8000
  worker:    Celery worker
  beat:      Celery Beat scheduler
  postgres:  Supabase-compatible Postgres, port 5432
  redis:     Redis, port 6379
  chroma:    ChromaDB, port 8001
```

All services must be reachable by name within Docker network.
All secrets via environment variables — never hardcoded.

---

## Environment variables

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/investment

# Redis
REDIS_URL=redis://redis:6379/0

# ChromaDB
CHROMA_HOST=chroma
CHROMA_PORT=8001

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# IBKR (TWS must be running separately)
IBKR_HOST=host.docker.internal
IBKR_PORT=7497
IBKR_CLIENT_ID=1

# News
NEWSAPI_KEY=...

# App
ENVIRONMENT=development
LOG_LEVEL=INFO
SECRET_KEY=...
```

---

## Code standards — non-negotiable

### Python style
- Python 3.12, fully typed with mypy strict
- Async everywhere — `async def` for all I/O
- Pydantic v2 for all data structures
- Repository pattern for all DB access — no raw queries in business logic
- Dependency injection via FastAPI `Depends()`

### Error handling
- Custom exception hierarchy in `packages/core/errors.py`
- Never catch bare `Exception` — always specific types
- LLM errors never crash a research run — always degrade gracefully
- All errors logged with correlation IDs

### Logging
- Structured JSON logging
- Every request has a `correlation_id` (UUID, propagated through all services)
- Log at the right level: DEBUG for dev detail, INFO for business events, ERROR for failures

### Testing
- Unit tests for: scoring engine, policy engine, all Pydantic schemas
- Integration tests for: DB repositories, LangGraph graph execution
- Every new module gets tests in the same PR
- `pytest` with `pytest-asyncio`

### Migrations
- Every schema change = new Alembic migration
- Never edit existing migrations
- Migration names: `{timestamp}_{descriptive_name}.py`

---

## Makefile commands

The following must always work:

```bash
make up          # docker compose up -d
make down        # docker compose down
make migrate     # alembic upgrade head
make test        # pytest
make lint        # ruff check + mypy
make format      # ruff format
make logs        # docker compose logs -f
make shell-api   # exec into api container
make run         # trigger a manual research run via CLI
```

---

## Milestones — build in this order

### Phase 0 — Definition (no code)
- M0: Product spec, watchlist, vocabulary, risk profile, safety rules

### Phase 1 — Infrastructure
- M1: Production skeleton (docker-compose, FastAPI, Postgres, Redis, ChromaDB, Celery, health endpoints)
- M2: Core research database (all tables, Alembic migrations, repositories)

### Phase 2 — Research loop (no AI)
- M3: LangGraph v0 with mock data — full graph, all nodes, saves to DB
- M4: Real market data — yfinance, 5yr OHLCV, technical indicators, SPY benchmark
- M5: Deterministic scoring engine — no LLM, full action mapping, policy gates
- M6: ChromaDB memory v0 — indexer, retriever, previous thesis retrieval

### Phase 3 — AI layer
- M7: LLM structured analysis — Claude nodes, Pydantic validation, graceful degradation
- M8: News ingestion — NewsAPI, deduplication, LLM summarization, evidence records

### Phase 4 — Portfolio & automation
- M9: IBKR read-only — positions, P&L, portfolio snapshots
- M10: Twice-daily scheduler — Celery Beat, morning/evening runs, run locking
- M11: Report generation — markdown + HTML, indexed to ChromaDB

### Phase 5 — Learning loop (after research loop is stable)
- M12: Outcome tracking — 1D/7D/30D/90D/180D returns, vs SPY
- M13: Post-mortem graph — failure classification, lesson creation
- M14: Mistake memory retrieval — checks for repeated mistakes before each run
- M15: Strategy improvement proposals — human-approved versioning

### Phase 6 — Hero features
- M16: Backtesting engine
- M17: SEC filings + earnings transcripts
- M18: Next.js dashboard (separate repo)

---

## What to build next

**Currently on Milestone 9.7.**

When asked to build a milestone, always:
1. Read this file first
2. Check which milestone we're on
3. Build only what the milestone specifies — do not jump ahead
4. Ensure `make up && make migrate && make test && make lint` pass before declaring done
5. Ask before making any architectural decision not covered here

---

## Current project state

> Last verified: M11 complete. Next: M11.1 — LLM-assisted learning events, or M12 outcome tracking improvements.

### Quality gate (verified before M9.7)
- `make test` — passing
- `make test-integration` — passing
- `make lint` — ruff clean, mypy clean
- Docker services healthy: api, worker, beat, postgres, redis, chroma

### Completed milestones

**M1 — Production skeleton**
FastAPI, Docker Compose, Postgres, Redis, Celery, Chroma, Alembic, health endpoints, structured JSON logging, tests/lint/mypy.

**M2 — Core research database**
Tables: research_runs, research_run_tickers, watchlist_symbols, investor_profiles, strategy_versions, prompt_versions, recommendations, evidence, job events, audit logs.

**M3 — LangGraph v0**
Research graph runs ticker research and persists recommendations end-to-end.

**M4–M7 — Market / fundamentals / LLM / memory**
- Market data ingestion + technical signals (yfinance, pandas-ta)
- Fundamentals snapshots + scoring
- Optional LLM analysis with strict Pydantic schemas; no direct action upgrades from LLM
- ChromaDB memory for previous recommendations and manual notes

**M8 — News**
- `packages/news` with fake provider + NewsAPI provider
- `news_items` table
- `fetch_news` graph node
- News score in neutral recommendation
- `NEWS_ANALYSIS` and `NEWS_ITEM` evidence rows
- `GET /api/v1/news/{symbol}/latest`
- `NEWS_ENABLED=false` is valid; missing news never crashes a run

**M9 — Portfolio**
- Tables: `portfolio_accounts`, `portfolio_positions`, `portfolio_snapshots`
- Portfolio fit score replaces old stub
- Personalized recommendation uses real portfolio context
- `position_sizing_json` added to personalized recs
- `GET/POST /api/v1/portfolio` endpoints
- Bug fixed: portfolio mutations now commit; research sessions see positions
- `load_portfolio_context` sets `current_position_weight > 0` when position exists
- `score_breakdown_json` moves `portfolio_context` from missing → completed; sets `component_quality_scores.portfolio_context = 1.0`; recomputes completeness

**M9.5 — Trade history + trading profile**

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

**M9.6 — Broker account support + IBKR connection fix**

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

---

### M9.7 — IBKR Flex Query historical trade import

**Goal:** Implement Flex Query as a separate read-only source for 12-month historical trades. Keep existing `reqExecutions` current-session sync intact.

**New files (expected):**
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

**APIs to add:**
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

**Services to reuse (do not rewrite):**
- `portfolio.trade_history_service.sync_ibkr_executions()`
- `portfolio.trade_history_service.load_all_executions()`
- `portfolio.trade_history_service.build_and_save_profile()`
- `portfolio.trade_history_service.get_symbol_trading_stats()`
- `broker.ibkr.schemas.IBKRExecution`

**Tests required:**
- Flex XML parsing
- Mapper: Flex trade → `IBKRExecution`
- Duplicate `exec_id` idempotency
- `broker_account_id` scoping
- API disabled/missing config
- API happy path with fake Flex client
- No raw token leakage in response/logs/schema
- `make test` / `make test-integration` / `make lint` must pass

**Safety constraints for M9.7:**
- Read-only only — never submit orders
- No raw credentials in DB fields
- `IBKR_ENABLED=false` must not break anything
- Flex failure must not crash research runs — degrade gracefully
- Normalize Flex data through internal schemas before touching portfolio/research graph
- LLM never makes trade decisions; scoring engine is judge
- Do not break existing `sync_runner.py` or M9.5/M9.6 APIs

**Handoff format at M9.7 completion:**
Provide: files added/modified, migration if any, how Flex Query works, required config fields, how normalized executions are stored, APIs added, tests added, manual verification commands, known limitations/TODOs.

---

### M11 — Backtesting + Learning Loop

New tables: `recommendation_outcomes`, `learning_events`

New packages:
- `packages/backtesting/__init__.py`
- `packages/backtesting/schemas.py` — `ForwardOutcome` dataclass
- `packages/backtesting/service.py` — `compute_forward_outcome`, `measure_recommendation_outcome`, `measure_latest_recommendations`, `generate_learning_event_from_outcome`
- `packages/backtesting/repository.py` — `RecommendationOutcomeRepository`, `LearningEventRepository`

New Alembic migration: `g8h9i0j1k2l3_add_backtesting_tables.py`

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

Tests added:
- `tests/backtesting/test_outcome_service.py` — 21 tests (pure compute + DB-bound)
- `tests/api/test_backtesting.py` — 12 tests (API isolation, idempotency, user scoping)

Quality gate (M11):
- `make test` — 563 passed
- `make test-integration` — 4 passed
- `make lint` — ruff + mypy clean

Known limitations / M11.1 follow-ups:
- No LLM analysis of learning events yet — all rule-based
- No personalized recommendation outcome measurement (only NEUTRAL for now)
- `min_bar_fraction` threshold is approximate — can be tuned per horizon
- No outcome aggregation endpoints (win rate summary, by symbol, by action) yet
- `benchmark_symbol` defaults to SPY but no SPY bars in seed data — benchmark fields may be null

---

## Safety rules — always enforced

1. No automated trading. No order submission to IBKR. Ever.
2. IBKR connection is read-only. No write operations.
3. No options, margin, or shorting logic.
4. Every recommendation requires human review before action.
5. LLM is never the final decision-maker.
6. The scoring engine and risk policy are always deterministic and auditable.
7. Strategy changes require human approval before activation.
8. All API keys in environment variables — never in code or git.
