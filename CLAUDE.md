# Investment Research Agent — Claude Code Context

> Single source of truth for Claude Code working on this project.
> Read fully before writing code or making architectural decisions.
> Detailed per-milestone history lives in `docs/MILESTONES.md`. Governance/philosophy in `Principles.md`.

---

## What we are building

A **private investment research operating system** — not a trading bot.

Automated research on a small watchlist (3–5 tickers), twice daily. Analyzes data, remembers previous research, produces structured recommendations, learns from mistakes.

**What it is NOT:**

- Not a trading bot. No automated order execution. Ever.
- Not an LLM that answers "should I buy?" The LLM is an analyst, not the decision-maker.
- Not a simple script. Production-grade, versioned, auditable.

**Core principle: LLM as analyst, deterministic engine as decision-maker.**

Good LLM tasks: summarize news, extract risk events, compare to previous thesis, bull/bear narrative, identify missing details, write final human-readable explanation.

Bad LLM task: "Should I buy this stock?" ← Never. The scoring engine decides.

---

## Project layout

```
investment-consultant/
├── CLAUDE.md
├── Principles.md              ← governance, safety rules, philosophy
├── docs/                      ← MILESTONES.md, ibkr-flex-query.md, ibkr-hosted-gateway.md
├── docker-compose.yml
├── pyproject.toml
├── Makefile
│
├── apps/
│   ├── api/                   ← FastAPI service (routers in apps/api/routers/)
│   ├── worker/                ← Celery worker + beat tasks
│   └── cli/                   ← CLI tools (incl. replay_status.py)
│
└── packages/
    ├── core/                  ← shared config, logging, errors
    ├── db/                    ← SQLAlchemy models, migrations, repositories, schemas
    ├── broker/                ← IBKR: ib_insync client, sync_runner, Flex Query (read-only)
    ├── market_data/           ← yfinance provider + price history service
    ├── fundamentals/          ← fundamentals snapshots, scoring, provider
    ├── news/                  ← NewsAPI + fake provider, scoring
    ├── social/                ← StockTwits API + X scraper (host-only), scoring
    ├── filings/               ← SEC EDGAR (later)
    ├── memory/                ← ChromaDB client, retriever, indexer
    ├── ai/                    ← Claude API client, prompts, schemas
    ├── local_llm/             ← Ollama integration for local inference
    ├── research_graph/        ← LangGraph research workflow (nodes/, state.py, runner.py)
    ├── decision_engine/       ← deterministic scoring + risk policy
    ├── portfolio/             ← portfolio context, trade history, trading profile
    ├── backtesting/           ← outcomes, advisor simulation, replay reports
    └── reports/               ← markdown + HTML report generation
```

UI is a **separate Next.js project**. No frontend code here. API exposes clean, typed REST endpoints.

---

## Tech stack

- Python 3.12, fully typed (mypy strict)
- FastAPI + Uvicorn, Pydantic v2 everywhere
- Postgres (Supabase-compatible), SQLAlchemy 2 async, Alembic
- Redis + Celery + Celery Beat
- `anthropic` SDK — Sonnet for orchestration, Haiku for sub-tasks; LangGraph; ChromaDB
- `ib_insync` (read-only), `yfinance`, `pandas-ta`, NewsAPI
- Docker Compose, Ruff, mypy, pytest, structured JSON logging with correlation IDs

---

## Architecture

### High-level flow (twice daily)

```
Celery Beat → Celery task → LangGraph research flow (per ticker)
  → data providers + ChromaDB + Claude
  → deterministic scoring engine
  → risk policy engine (hard gates)
  → neutral recommendation
  → IBKR portfolio context
  → personalized recommendation
  → report generation
  → persist to Postgres + index to ChromaDB
```

### Two-recommendation design

Every run produces TWO recommendations per ticker:

- **Neutral** — "Is this security attractive on its own merits?" Uses market data, technicals, news, memory, fundamentals. NOT portfolio.
- **Personalized** — "Given the neutral view and MY portfolio, what should I do?" Uses neutral rec + IBKR position + risk profile. Can override neutral (e.g., BUY_CANDIDATE → HOLD at max weight).

### Recommendation vocabulary (never raw BUY/SELL/HOLD)

```
STRONG_BUY      — score 85-100, risk policy passes
BUY_CANDIDATE   — score 70-84
HOLD            — score 50-69
REDUCE          — score 35-49
SELL            — score 0-34 with position
NO_ACTION       — score 0-34 without position
WATCHLIST       — interesting but missing data
```

### LangGraph research flow

```
START
  ↓ LoadRunContext / LoadTickerContext
  ↓ RetrieveResearchMemory      ← ChromaDB: previous thesis, last rec, risks, past mistakes
  ↓ FetchMarketData             ← yfinance OHLCV (as_of_date aware)
  ↓ ComputeTechnicalSignals     ← pandas-ta: RSI, MACD, EMA, momentum, volatility
  ↓ FetchFundamentals
  ↓ FetchNews                   ← NewsAPI live / DB-only for replay
  ↓ AnalyzeNewsWithLLM / CompareToPreviousThesis / MissingDetailsCheck   ← Claude
  ↓ NeutralScoring              ← DETERMINISTIC, no LLM
  ↓ CreateNeutralRecommendation ← Pydantic, saved to DB
  ↓ LoadPortfolioContext        ← IBKR snapshot from DB
  ↓ ApplyPersonalRiskPolicy     ← DETERMINISTIC, no LLM
  ↓ CreatePersonalizedRecommendation
  ↓ WriteFinalExplanation       ← Claude
  ↓ PersistResults → IndexReportToChroma
  ↓ END
```

All nodes share typed `ResearchState` (packages/research_graph/state.py). Never pass raw dicts between nodes.

---

## Deterministic scoring engine

The scoring engine is the decision authority. No LLM involved.

```
Technical score:     0–20  (RSI, MACD, momentum, moving averages)
Fundamental score:   0–20  (P/E, P/B, revenue growth)
Valuation score:     0–15  (vs sector, vs history)
News score:          0–15  (sentiment, event severity)
Portfolio fit:       0–15  (concentration, correlation)
Risk score:          0–15  (volatility, beta, drawdown)
─────────────────────────
Total:               0–100
```

Action mapping: ≥85 STRONG_BUY (if policy passes), ≥70 BUY_CANDIDATE, ≥50 HOLD, ≥35 REDUCE, else SELL (with position) / NO_ACTION.

### Risk policy hard gates (override any score)

```
NO_BUY if current_position_weight > max_single_stock_weight
NO_BUY if confidence < minimum_confidence_threshold
NO_BUY if data_quality_score < minimum_data_quality
NO_BUY if missing_details.severity == "CRITICAL"
NO_STRONG_BUY before earnings (unless explicitly allowed)
NEVER automated trading; NEVER options, margin, shorting
```

---

## Database

Every table has `created_at` / `updated_at`. UUID PKs. All models in `packages/db/models.py`.

Core tables: `research_runs`, `research_run_tickers`, `watchlist_symbols`, `investor_profiles`,
`neutral_recommendations`, `personalized_recommendations`, `recommendation_evidence`,
`strategy_versions`, `prompt_versions`, `audit_logs`, `news_items`, `market_prices`,
`fundamentals_snapshots`.

Portfolio/broker: `portfolio_accounts`, `portfolio_positions`, `portfolio_snapshots`,
`broker_accounts`, `ibkr_executions`, `manual_trades`, `trading_profile_snapshots`.

Backtesting/learning: `recommendation_outcomes`, `learning_events`,
`advisor_backtest_runs`, `advisor_backtest_trades`, `advisor_backtest_equity_points`,
`advisor_backtest_analyses`.

Migrations: every schema change = new Alembic migration; never edit existing migrations.

---

## ChromaDB memory

Collections: `company_research_memory`, `recommendation_reports`, `personal_investment_notes`.
Later: filing chunks, transcripts, news summaries, postmortems, strategy lessons, mistake patterns.

Retrieval — never pure semantic search alone. Before each run retrieve in order:

1. Previous thesis for symbol (`where symbol == ticker`, always)
2. Last recommendation for symbol
3. Important risks flagged in previous runs
4. Past mistakes relevant to symbol/pattern
   Recency-weighted (prefer last 30 days) + semantic match on current context.

---

## Claude API usage

- Orchestration/synthesis: `claude-sonnet-4-20250514`; extraction/sub-tasks: `claude-haiku-4-5-20251001`
- Every LLM call returns a validated Pydantic model
- Graceful degradation is mandatory: LLM failure → log error, append confidence penalty, set field None, continue. Never crash a research run.

---

## API design

Base URL `/api/v1`. All endpoints user-scoped via `CurrentUser`.
Response envelope: `{ "data": ..., "meta": { request_id, timestamp } }`; errors `{ "error": { code, message, detail }, "meta": ... }`.

```
POST   /research-runs                       ← trigger run (async_execution: bool)
GET    /research-runs, /research-runs/{id}
POST   /research-runs/historical-replay     ← seed replay batch (daily/weekly/monthly, max 120)
GET    /research-runs/historical-replay/{batch_id}            ← batch status/progress
POST   /research-runs/historical-replay/{batch_id}/backtest   ← advisor backtest over batch
GET    /research-runs/historical-replay/{batch_id}/report     ← deterministic quality report
POST   /research-runs/historical-replay/{batch_id}/evaluation

GET    /recommendations/latest, /{id}, /{id}/evidence

GET    /portfolio/snapshot, /portfolio/history
POST/GET /portfolio/trades
GET    /portfolio/trading-profile, /trading-profile/{symbol}
POST   /portfolio/trading-profile/rebuild
GET/POST/PATCH /portfolio/broker-accounts[...]
POST   /portfolio/sync-ibkr, /sync-flex, /broker-accounts/{id}/sync-ibkr|sync-flex

POST   /backtesting/outcomes/measure-latest
GET    /backtesting/outcomes, /backtesting/learning-events
POST   /backtesting/learning-events/{id}/review
POST/GET /backtesting/advisor-runs/{id}/analysis

GET    /news/{symbol}/latest
GET    /fundamentals/{symbol}/latest
GET    /market-data/{symbol}/latest
GET/PUT /risk-profile
GET/POST/DELETE /watchlist[...]
GET    /strategy/versions, /strategy/active
GET    /health, /health/detailed
```

---

## Services & environment

Docker Compose services: `api` (8000), `worker`, `beat`, `postgres` (5432), `redis` (6379), `chroma` (8001). All reachable by name in Docker network. All secrets via env vars — never hardcoded.

Key env vars: `DATABASE_URL`, `REDIS_URL`, `CHROMA_HOST/PORT`, `ANTHROPIC_API_KEY`,
`IBKR_HOST/PORT/CLIENT_ID`, `IBKR_FLEX_TOKEN` (dev only), `NEWSAPI_KEY`,
`NEWS_ENABLED`, `IBKR_ENABLED`, `SCHEDULED_RESEARCH_ENABLED/USER_ID/HOURS/MINUTE`,
`LLM_PROVIDER` (`anthropic`|`ollama`), `OLLAMA_RESEARCH_MODEL`,
`SOCIAL_ENABLED`, `SOCIAL_PROVIDER`, `X_SCRAPE_ACCOUNTS`, `X_SESSION_STATE_PATH`,
`ENVIRONMENT`, `LOG_LEVEL`, `SECRET_KEY`. See `.env.example`.

Social replay caveat: StockTwits keeps only ~30 recent messages — replay runs
for dates before ingestion get the neutral 5.0 social stub and no blend, so
replay scores stay comparable. X scraping is host-only (`make scrape-x`);
Docker images have no browsers and the research graph never launches Playwright.

---

## Code standards — non-negotiable

- Python 3.12, mypy strict, async everywhere for I/O
- Pydantic v2 for all data structures; repository pattern for all DB access
- Dependency injection via FastAPI `Depends()`
- Custom exception hierarchy in `packages/core/errors.py`; never catch bare `Exception`
- LLM errors never crash a research run — degrade gracefully
- Structured JSON logging with propagated `correlation_id`
- Every new module gets tests in the same PR (`pytest` + `pytest-asyncio`)
- Unit tests: scoring engine, policy engine, schemas. Integration: repositories, graph execution.

## Makefile — must always work

```bash
make up / down / migrate / test / test-integration / lint / format
make logs / shell-api / run / trigger-scheduled-research
```

---

## Milestones

Build in order. When asked to build a milestone: read this file, check current milestone,
build only what it specifies, ensure `make up && make migrate && make test && make lint`
pass, ask before uncovered architectural decisions.

| Phase                    | Milestones                                                                                                                      | Status  |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------- | ------- |
| 0 Definition             | M0 spec, vocabulary, risk profile                                                                                               | ✅      |
| 1 Infrastructure         | M1 skeleton, M2 core DB                                                                                                         | ✅      |
| 2 Research loop          | M3 LangGraph v0, M4 market data, M5 scoring, M6 memory v0                                                                       | ✅      |
| 3 AI layer               | M7 LLM structured analysis, M8 news                                                                                             | ✅      |
| 4 Portfolio & automation | M9/M9.5/M9.6/M9.7 IBKR+trades+Flex, M10 scheduler, M11 outcomes+learning events                                                 | ✅      |
| 5 Async + replay         | M12 async runs+beat, M12.1 replay seeding, M12.2 as-of-date nodes, M12.7 batch observability, M12.7.2 position-aware evaluation | ✅      |
| 5 Learning loop          | M13 post-mortem graph, M14 mistake memory retrieval, M15 strategy improvement proposals                                         | ⬜ next |
| 6 Hero                   | M16 backtesting engine, M17 filings/transcripts, M18 Next.js dashboard (separate repo)                                          | ⬜      |

**Currently: M12.7.2 complete. Next: M13.**

Full per-milestone detail (files, APIs, migrations, known limitations): `docs/MILESTONES.md`.

### Key operational facts (survive from history)

- **IBKR event loop**: `ib_insync` must run in its own loop — `sync_runner.py` wraps connect→fetch→disconnect in `asyncio.to_thread` + `asyncio.run()`. Replay Celery tasks use the same isolated-loop pattern. Do not break this.
- **`reqExecutions` only returns current TWS session fills** — historical trades come from Flex Query.
- **Replay runs**: `metadata_json.historical_replay=true` + `replay_batch_id` + `as_of_date`; `finished_at` and `NeutralRecommendation.created_at` overridden to `as_of_date 16:00 UTC`. Market data/SPY/news are as-of-date capped; fundamentals, memory, portfolio are NOT (still current) — replay is pipeline-grade, not institutional-grade backtest.
- Beat schedule built at import time — env schedule changes need worker restart.
- Celery tasks have `max_retries=0` (no retry/backoff yet).

---

## Safety rules — always enforced

1. No automated trading. No order submission to IBKR. Ever.
2. IBKR connection is read-only. No write operations.
3. No options, margin, or shorting logic.
4. Every recommendation requires human review before action.
5. LLM is never the final decision-maker.
6. Scoring engine and risk policy are always deterministic and auditable.
7. Strategy changes require human approval before activation.
8. All API keys in environment variables — never in code or git.
