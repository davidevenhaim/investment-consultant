# IBKR Flex Query — Historical Trade Import

## Why Flex Query?

`reqExecutions` (the TWS/IB Gateway API) only returns executions from the **current session**. Historical months of trade data require the **IBKR Flex Query Web Service**, a separate REST-like API that generates XML reports of your account activity.

## How the Flow Works

```
1. POST SendRequest
   https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest
   ?t=<token>&q=<queryId>&v=3
   → returns <ReferenceCode>1234567890</ReferenceCode>

2. Poll GetStatement (repeat until ready)
   https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement
   ?t=<token>&q=<referenceCode>&v=3
   → returns FlexQueryResponse XML when ready
     or <ErrorCode>1003</ErrorCode> (queued)
     or <ErrorCode>1004</ErrorCode> (generating)

3. Parse XML → FlexExecution records → persist to ibkr_executions
```

## Setting Up in IBKR

1. Log in to IBKR Client Portal
2. Navigate to **Reports → Flex Queries**
3. Create a new Activity Flex Query:
   - Include: **Trades** section
   - Fields: tradeID, symbol, buySell, quantity, tradePrice, ibCommission, currency, tradeDate, tradeTime, exchange, orderReference
   - Date range: select what you need (e.g. last 3 years)
4. Note the **Query ID** from the query list
5. Generate a **Flex Web Service Token** under **Settings → Account Settings → Flex Web Service**

## Configuration

```bash
# .env
IBKR_FLEX_ENABLED=true
IBKR_FLEX_TOKEN=your_token_here
IBKR_FLEX_QUERY_ID=your_query_id_here

# Optional tuning (defaults are sane)
IBKR_FLEX_MAX_POLLS=10
IBKR_FLEX_POLL_INTERVAL_SECONDS=3
IBKR_FLEX_TIMEOUT_SECONDS=60
```

Token is **never logged** — only a SHA256 12-char hash is used in log lines.

## API Endpoints

### Global sync (dev / single-account setup)
```
POST /api/v1/portfolio/sync-flex
```
Uses `IBKR_FLEX_TOKEN` and `IBKR_FLEX_QUERY_ID` from environment.

### Per-account sync
```
POST /api/v1/portfolio/broker-accounts/{broker_account_id}/sync-flex
```
Checks `broker_account.metadata_json["flex_token_env"]` for an env-var name that holds the token, then falls back to global settings.

Both endpoints return:
```json
{
  "data": {
    "fetched": 42,
    "inserted": 38,
    "skipped_duplicates": 4,
    "profile_snapshot_id": "uuid-of-snapshot"
  }
}
```

### Diagnostics CLI
```bash
docker compose exec api python -m apps.cli.ibkr_flex_diagnostics
```
Tests the full flow without writing to DB. Outputs JSON with connection status, parse counts, and any errors.

## Deduplication

Executions are deduplicated using a deterministic **exec_id**:

- If IBKR provides a `tradeID` attribute: `exec_id = "flex-{tradeID}"`
- Otherwise: `exec_id = "flex-" + SHA256(source|account|symbol|side|qty|price|date|time)[:32]`

The `ibkr_executions` table has a unique constraint on `exec_id`, so re-importing the same date range is idempotent.

## Architecture

| File | Role |
|------|------|
| `packages/broker/ibkr/flex_schemas.py` | `FlexExecution` Pydantic model |
| `packages/broker/ibkr/flex_parser.py` | XML → `FlexExecution` list |
| `packages/broker/ibkr/flex_client.py` | HTTP client (SendRequest + polling) |
| `packages/portfolio/trade_history_service.py` | `sync_ibkr_flex_executions()` service function |
| `apps/api/routers/portfolio.py` | API endpoints |
| `apps/cli/ibkr_flex_diagnostics.py` | Diagnostics CLI |

## Security Notes

- Token lives only in environment variables — never in DB or logs
- `_hash_token()` produces a 12-char SHA256 prefix safe for log lines
- XML is parsed from IBKR's servers (trusted source); `S314` suppressed with `# noqa`
- The service is **read-only** — no orders, no writes to IBKR

## Error Handling

| Condition | Result |
|-----------|--------|
| `IBKR_FLEX_ENABLED=false` | `503 Service Unavailable` |
| Token/query_id missing | `400 Bad Request` |
| HTTP timeout or connection error | `IBKRFlexError` → `503` |
| Statement not ready after max polls | `IBKRFlexError` → `503` |
| XML parse failure | `ValueError` caught, `503` |
| DB error | Exception propagates, `mark_sync_failure` called |

On any exception, `BrokerAccountRepository.mark_sync_failure()` is called to record the failure timestamp and message.
