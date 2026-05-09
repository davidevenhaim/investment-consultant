# Investment Research Agent

Private investment research operating system. Runs automated research on a small watchlist, produces deterministic scored recommendations, and learns from mistakes.

**Not a trading bot. No automated order execution.**

---

## Quick start

```bash
make up        # start all services (postgres, redis, chroma, api, worker, beat)
make migrate   # apply all Alembic migrations
make seed      # seed strategy version + investor profile
make test      # run test suite (no network required)
make lint      # ruff + mypy
```

---

## Triggering a research run

```bash
# With explicit symbols
curl -X POST http://localhost:8000/api/v1/research-runs \
  -H "Content-Type: application/json" \
  -d '{"run_type": "MANUAL", "symbols": ["AAPL", "NVDA"]}'

# Using active watchlist
curl -X POST http://localhost:8000/api/v1/research-runs \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Note — first run for a symbol fetches 5 years of daily price history from yfinance.**
Subsequent runs are fast (data is cached in `market_prices` table).
The graph runs synchronously and the POST returns when all tickers complete.

---

## Reading results

```bash
# Latest recommendations per watchlist symbol
curl http://localhost:8000/api/v1/recommendations/latest | jq .

# Stored price data for a symbol
curl http://localhost:8000/api/v1/market-data/AAPL/latest | jq .

# List research runs
curl http://localhost:8000/api/v1/research-runs | jq .
```

---

## Adding to watchlist

```bash
curl -X POST http://localhost:8000/api/v1/watchlist \
  -H "Content-Type: application/json" \
  -d '{"symbol": "AAPL"}'
```

---

## Architecture

See `CLAUDE.md` for full architecture. Current milestone: **M5 — Fundamentals/Valuation + Policy Engine**.

**First run for a symbol fetches both 5y market data (yfinance) and company fundamentals (yfinance .info). Subsequent runs are fast — data is cached in DB (market_prices, company_fundamentals). Tests mock yfinance; no network required.**

```
POST /api/v1/research-runs
  → LoadTickerContext
  → RetrieveMemory (stub, M6)
  → FetchMarketData (yfinance, 5y OHLCV, cached in market_prices)
  → ComputeSignals (SMA, RSI, ATR, momentum, relative strength vs SPY)
  → FetchFundamentals (yfinance .info, cached in company_fundamentals, max_age=7d)
  → NeutralRecommendation (real: technical + risk + fundamental + valuation; stubs: news/portfolio)
  → PersonalizedRecommendation (deterministic policy engine: 7 gates)
  → PersistResults (DB commit, price_at_recommendation + completeness metadata set)
```

Endpoints added in M5:

```bash
# Company fundamentals
curl http://localhost:8000/api/v1/fundamentals/AAPL/latest | jq .
```

### Score components

| Component | Max | Status |
|-----------|-----|--------|
| Technical | 20 | Real (M4) |
| Risk | 15 | Real (M4) |
| Fundamental | 20 | Real (M5) |
| Valuation | 15 | Real (M5) |
| News | 15 | Stub (M8) |
| Portfolio fit | 15 | Stub (M9) |

### Action thresholds

| Score | Action |
|-------|--------|
| ≥ 85 | STRONG_BUY |
| ≥ 70 | BUY_CANDIDATE |
| ≥ 50 | HOLD |
| ≥ 35 | REDUCE |
| < 35 + position | SELL |
| < 35 no position | NO_ACTION |

---

## Tests

```bash
make test
# 124 tests, ~20s
# No network required — yfinance is mocked in all tests
# Tests use a separate `investment_test` database (created/dropped each session)
```

---

## Migrations

```bash
make migrate          # apply head
alembic history       # see migration chain
alembic downgrade -1  # roll back one step
```

Current migration chain:
- `a8f3b291c7e4` — Initial schema (M2): all research tables
- `b2e4d1f8a903` — Add `market_prices` table (M4)
- `c3f5a8b2e1d7` — Add `company_fundamentals` table (M5)
