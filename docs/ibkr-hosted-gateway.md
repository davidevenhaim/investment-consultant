# IBKR Hosted Gateway — Architecture and Setup

## Why hosted gateway per user

Interactive Brokers does not have a REST API. All programmatic access requires
connecting to a running TWS or IB Gateway application, which:

- Must be running on the user's local machine (LOCAL_TWS), or
- Can run in a Docker container that the system manages (HOSTED_GATEWAY)

For a single-user dev setup, LOCAL_TWS is fine — you run TWS or IB Gateway on your
machine and point Docker to `host.docker.internal`. For a multi-user or always-on
production scenario, each user needs their own Gateway container because:

1. IBKR sessions are personal — each user logs in with their own credentials
2. TWS/Gateway maintains stateful session — one process per account
3. The API port is exclusive per running instance

---

## Connection modes

| Mode | Where Gateway runs | Use case |
|---|---|---|
| `LOCAL_TWS` | Host machine (user's Mac/PC) | Single user, dev, learning |
| `HOSTED_GATEWAY` | Docker container managed by the system | Production, always-on |

The `broker_accounts` table stores which mode each account uses, along with
the host/port to connect to. Secrets (IBKR username/password) are **never** stored
in this table.

---

## Dev architecture (LOCAL_TWS)

```
API container
  └─► broker_account config (connection_mode=LOCAL_TWS, host=host.docker.internal, port=7497)
        └─► host machine TWS/IB Gateway (user logged in manually)
              └─► IBKR servers
```

Setup steps:
1. Download and run TWS or IB Gateway on your host machine
2. In TWS: Configure → API → Settings → Enable ActiveX and Socket Clients
3. Set port to 7497 (paper) or 7496 (live)
4. Add your Docker bridge IP to Trusted IPs (usually 172.17.0.1 on Mac)
5. In .env: set `IBKR_ENABLED=true`, `IBKR_HOST=host.docker.internal`, `IBKR_PORT=7497`
6. Restart services: `make down && make up`
7. Create or verify broker account: `GET /api/v1/portfolio/broker-accounts`
8. Sync: `POST /api/v1/portfolio/sync-ibkr`

---

## Production architecture (HOSTED_GATEWAY)

```
API/Worker containers
  └─► broker_accounts table (connection_mode=HOSTED_GATEWAY, host=ibkr-gateway-user1, port=4002)
        └─► ibkr-gateway-user1 container (IB Gateway + automated login)
              └─► IBKR servers
```

Each user gets their own IB Gateway container. The `broker_accounts` table stores
the container hostname and port — not credentials. Credentials live in a secret
manager (Docker secrets, AWS Secrets Manager, Kubernetes secrets).

The `metadata_json` field can store references to secrets but **never secrets themselves**:
```json
{
  "gateway_container_name": "ibkr-gateway-user1",
  "secret_ref": "arn:aws:secretsmanager:us-east-1:123456789:secret/ibkr-user1"
}
```

---

## Risks and constraints

| Risk | Mitigation |
|---|---|
| IBKR 2FA / session expiration | Gateway auto-login tools (e.g. IBC) handle re-auth; session expires ~24h |
| One Gateway per user = resource cost | ~1 CPU / 512MB RAM per container; acceptable for small user counts |
| IBKR blocks simultaneous logins | Strictly one Gateway per account; never run two |
| Network isolation | Gateway containers must only be reachable from API/worker, not public internet |
| Credential leakage | Never store passwords in DB; use Docker secrets or a secret manager |

---

## Future orchestration options

**Local development (current):**
- Docker Compose with `docker-compose.ibkr-gateway.example.yml`
- Manual login flow; suitable for 1–2 users

**Small production (next step):**
- Docker Compose with health checks and automatic restart
- IBC (IB Controller) for automated login
- Secrets via Docker secrets

**Medium production:**
- AWS ECS Fargate: one Task per broker account, spawned on demand
- Secrets in AWS Secrets Manager, referenced by `secret_ref` in `metadata_json`
- ALB routing by `broker_account_id`

**Large production:**
- Kubernetes StatefulSet or Deployment per broker account
- Operator pattern for lifecycle management
- Pod anti-affinity to ensure one Gateway per node

---

## TODOs for future milestones

These are explicitly **not** implemented in M9.6:

- [ ] **M10 — broker_sync_jobs table**: Track sync job status, retry logic, scheduling
- [ ] **M10 — Celery-based async broker sync**: Queue sync jobs, don't block API requests
- [ ] **M10 — gateway lifecycle manager**: Start/stop Gateway containers on demand
- [ ] **M10 — health checks**: Ping Gateway before attempting sync
- [ ] **M11 — secret manager integration**: Load credentials from Vault/AWS SM at sync time
- [ ] **M12 — user_id enforcement**: Once auth exists, enforce non-null user_id on broker_accounts
- [ ] **M12 — per-user Chroma isolation**: Namespace memory collections by user_id
- [ ] **M12 — per-user recommendation isolation**: Research runs scoped to user's accounts
