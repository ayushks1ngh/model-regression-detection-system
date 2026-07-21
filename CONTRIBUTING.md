# Contributing

## Development setup

```bash
uv sync --dev
pre-commit install   # if configured
```

## Code quality

```bash
make lint        # ruff
make typecheck   # mypy
make test        # pytest
make coverage    # pytest with coverage report
make security-scan  # bandit + pip-audit
```

Before opening a PR, ensure `make lint && make typecheck && make test` passes.

---

## Production runbooks

### 1. Application will not start

**Symptoms:** Container exits immediately; `docker compose logs` shows a startup error.

**Checklist:**

1. **Database connectivity** — Verify `MRDS_DATABASE_URL` is correct and the Postgres
   instance is reachable. Run `pg_isready` from the api/worker container:
   ```bash
   docker compose exec api pg_isready -U mrds -d mrds
   ```
2. **Migrations** — The entrypoint runs `alembic upgrade head` automatically.
   If it fails, run manually:
   ```bash
   docker compose exec api alembic upgrade head
   ```
3. **Environment** — Confirm `MRDS_ENVIRONMENT` is set to `production` in production.
4. **Secrets** — `MRDS_OPENROUTER_API_KEY` must be set for the worker; use
   `MRDS_WORKER_FAKE_PROVIDER=1` only for local smoke testing.

---

### 2. Worker crashes or stalls

**Symptoms:** Runs stay in `running` or `created` state indefinitely;
worker logs show repeated errors or no activity.

**Checklist:**

1. **Provider quota** — Check OpenRouter rate-limit headers in worker logs.
   If rate-limited, increase `max_retries` or reduce concurrent runs.
2. **Heartbeat loss** — The worker heartbeat extends the lease every
   `lease_seconds // 3` seconds. If the DB is slow or the worker is
   overloaded, the lease expires and another worker reclaims the run.
   - Check `heartbeat_lost_lease` log entries.
   - Increase `lease_seconds` (default: 60) for long-running evaluations.
3. **Stranded runs** — On startup the worker reconciles runs whose lease
   has expired. To force-reconcile without a restart:
   ```sql
   UPDATE runs SET state = 'failed', execution_status = 'reconciled'
   WHERE state = 'running' AND lease_expires_at < NOW() - INTERVAL '5 minutes';
   ```
4. **OOM kill** — Check `docker compose logs worker` for `Killed` messages.
   Increase memory limit in `docker-compose.yml`.

---

### 3. API returns 429 Too Many Requests

**Symptoms:** Clients receive HTTP 429 responses.

**Causes and remedies:**

- The default rate limit is **100 requests per 60-second window per token**.
- To raise the limit, modify `MAX_REQUESTS` in
  `src/model_regression_detection/api/ratelimit.py` or inject a higher value
  via the middleware constructor.
- If rate limits are being hit by legitimate traffic, request a dedicated token.

---

### 4. Database backup and restore

**Automated backup:**

```bash
# From the host (requires psql client)
./scripts/backup.sh ./backups

# Scheduled via cron (daily at 2 AM):
0 2 * * * cd /opt/mrds && ./scripts/backup.sh /backups
```

**Restore:**

```bash
./scripts/restore.sh /backups/mrds_20260721_020000.sql.gz
```

The restore script drops the existing database, recreates it, and applies
the dump. **Use with caution in production.**

---

### 5. Monitoring and alerting

- **`/health/live`** — Liveness probe (always returns 200 when the process is alive).
- **`/health/ready`** — Readiness probe (checks DB connectivity).
- **`/metrics`** — Prometheus endpoint exposing:
  - `mrds_http_requests_total` — Request count by method, path, status.
  - `mrds_http_request_duration_seconds` — Latency histogram.
  - `mrds_wsgi_requests_total` — WSGI-level request count.

**Suggested Prometheus alerts:**

| Alert | Expression | For |
|---|---|---|
| High error rate | `rate(mrds_http_requests_total{status=~"5.."}[5m]) > 0.05` | 5m |
| Worker stalled | `absent(rate(mrds_http_requests_total{path=~"/api/v1/runs"}[10m]))` | 10m |
| High latency p99 | `histogram_quantile(0.99, rate(mrds_http_request_duration_seconds_bucket[5m])) > 5.0` | 5m |

---

### 6. Rolling upgrade

1. Pull the latest image:
   ```bash
   docker compose pull
   ```
2. Recreate the API (zero-downtime if behind a load balancer):
   ```bash
   docker compose up -d --no-deps --scale worker=0 api
   ```
3. Run database migrations (the entrypoint runs them automatically):
   ```bash
   docker compose exec api alembic upgrade head
   ```
4. Recreate the worker:
   ```bash
   docker compose up -d --no-deps worker
   ```
