# PostgreSQL-Backed Worker

Milestone 11 adds a worker process that claims persisted runs, executes them, and writes back terminal evidence. The API from M10 only creates runs; this worker is what actually moves them from `created` to `completed` or `failed`.

## Run the worker

```bash
export MRDS_DATABASE_URL="postgresql+asyncpg://user:pw@localhost:5432/mrds"
export MRDS_OPENROUTER_API_KEY="sk-..."
uv run mrds worker
```

For local smoke testing without OpenRouter, set `MRDS_WORKER_FAKE_PROVIDER=1` instead of an API key. The fake provider returns a permanent error for any case it has no scripted response for, so runs will complete with `gate_outcome: error` rather than hang.

## Claim semantics

Claiming uses one atomic conditional `UPDATE ... WHERE state = <expected> RETURNING id`:

1. Prefer runs currently in `created`.
2. Otherwise, reclaim a `running` run whose lease has expired.

Because the `WHERE` clause re-checks the expected prior state, at most one concurrent worker can win a given row — this is verified directly against two workers racing for the same run.

## Lease lifecycle

- Claiming sets `state=running`, `worker_id`, and `lease_expires_at` (default 60 seconds, configurable with `--lease-seconds`).
- Completion checks that the calling worker still owns the lease before writing terminal evidence. A worker whose lease was reclaimed by someone else cannot overwrite the winner's results.
- Heartbeat renewal runs as a background task during execution, extending the lease every `lease_seconds / 3` seconds (minimum 1s). If the worker loses its lease (another worker reclaimed it), heartbeat logs a warning but does not abort execution; `complete_run` will reject the stale write at the end.
- Retryable provider errors (rate limits, timeouts, transient upstream failures) are retried with exponential backoff: `base_delay * 2^attempt`, capped at `max_retry_delay_seconds` (default 30s), up to `max_retries` (default 3). Permanent errors are never retried. Configurable via `mrds worker --max-retries`, `--base-retry-delay-seconds`, and `--max-retry-delay-seconds`.

## Startup reconciliation

On startup, the worker calls `reconcile_stranded_runs` to fail any runs stuck in `running` state with an expired lease. Runs that were never claimed (`created`) are left for the poll loop to pick up, unless they exceed `max_created_age_seconds`. Reconciled runs receive `state=failed`, `execution_status=reconciled`, and `gate_outcome=error` with a `metrics.reason` field.

## Graceful shutdown

`mrds worker` installs `SIGINT`/`SIGTERM` handlers that request the poll loop to stop after its current iteration. The database engine is disposed on exit.

## Verify

```bash
uv run pytest tests/test_worker.py
```

Or end-to-end with a real database:

```bash
uv run alembic upgrade head
uv run uvicorn model_regression_detection.main:app --port 8000 &
MRDS_WORKER_FAKE_PROVIDER=1 uv run mrds worker &
curl -s -X POST http://127.0.0.1:8000/api/v1/runs \
  -H "Content-Type: application/json" \
  -d '{"project_id":"demo","specification": {"...": "..."}}'
# poll GET /api/v1/runs/{run_id} until state is completed or failed
```

## Known defect fixed in this milestone

The initial implementation added the run row and its idempotency record to the session in the same flush. PostgreSQL enforces foreign-key insert ordering strictly within a flush and raised `ForeignKeyViolationError` on every idempotent submission — a real bug, not a test artifact. SQLite did not enforce this ordering, so it was invisible in the default offline test suite. The fix flushes the run insert first, then the idempotency record separately. A regression test (`test_postgres_first_idempotent_submission_succeeds`) now exercises this path against real PostgreSQL.

## Deferred

Run cancellation and configurable retry budgets are deferred to later milestones.
