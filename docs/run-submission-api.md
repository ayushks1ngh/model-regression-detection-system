# Run Submission and Status API

Milestone 10 adds HTTP endpoints to submit an immutable evaluation run and query its status. Submission only freezes the specification into a persisted snapshot; it does not execute the run. Execution and completion are introduced by the worker in M11.

## Endpoints

### `POST /api/v1/runs`

Request body:

```json
{
  "project_id": "my-project",
  "specification": { "schema_version": "1", "...": "..." }
}
```

An optional `Idempotency-Key` header (1–200 characters) makes retried submissions safe:

- Same key, same request body → returns the original run (`202`).
- Same key, different request body → `409 Conflict`.
- No key → always creates a new run.

Response (`202 Accepted`):

```json
{
  "run_id": "…",
  "project_id": "my-project",
  "suite": "customer-support-smoke",
  "state": "created",
  "configuration_hash": "…",
  "dataset_hash": "…"
}
```

The project is created automatically on first use. The full validated specification is stored as the run's immutable snapshot; it cannot change after creation.

### `GET /api/v1/runs/{run_id}`

Returns current run state (`created`, `completed`, or `failed`), gate outcome (`null` until completion), case count, and timestamps. Returns `404` for an unknown run ID.

## Persistence requirement

Both endpoints require a configured database (`MRDS_DATABASE_URL`) with migrations applied. Without one, they return `503 Service Unavailable`; `/health/live` and `/health/ready` remain unaffected.

## Verify

```bash
export MRDS_DATABASE_URL="postgresql+asyncpg://user:pw@localhost:5432/mrds"
uv run alembic upgrade head
uv run uvicorn model_regression_detection.main:app --port 8000 &
curl -s -X POST http://127.0.0.1:8000/api/v1/runs \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-1" \
  -d '{"project_id":"demo","specification": {"schema_version":"1", "...": "..."}}'
```

Or run the offline test suite:

```bash
uv run pytest tests/test_runs_api.py tests/test_persistence.py
```

## Deferred

Execution, cancellation, comparison, and reporting endpoints are introduced in M11 onward. M11 adds the worker that executes `created` runs; see [`docs/worker.md`](docs/worker.md). M11 adds the worker that executes `created` runs; see [`docs/worker.md`](docs/worker.md).
