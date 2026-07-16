# Persistence

Milestone 9 adds optional PostgreSQL persistence for completed evaluation runs. The application and local runner remain fully usable without a database; persistence and readiness activate only when `MRDS_DATABASE_URL` is set.

## Configuration

```bash
export MRDS_DATABASE_URL="postgresql+asyncpg://user:password@host:5432/mrds"
```

- The application uses the async `asyncpg` driver at runtime.
- Alembic migrations run over a synchronous driver; the environment rewrites `+asyncpg` to `+psycopg2` automatically.
- When unset, `/health/ready` reports `not_configured` and the API still serves liveness.

## Schema

The initial migration creates three tables:

- `projects`: logical owner of runs.
- `runs`: immutable run identity, hashes, execution status, gate outcome, aggregate metrics.
- `case_results`: per-case outcome, provider status, cost, and full evidence JSON, unique per `(run_id, case_key)`.

JSON columns use PostgreSQL `JSONB` and portable `JSON` elsewhere so the same models run under SQLite in tests.

## Migrations

```bash
MRDS_DATABASE_URL="postgresql+asyncpg://user:password@host:5432/mrds" uv run alembic upgrade head
MRDS_DATABASE_URL="postgresql+asyncpg://user:password@host:5432/mrds" uv run alembic downgrade base
```

## Readiness

- `GET /health/live` never depends on the database.
- `GET /health/ready` returns `200` with `database: ok` when connectivity succeeds, `503` with `database: unavailable` when a configured database is unreachable, and `200` with `database: not_configured` when no database is set.

## Tests

Offline tests run against in-memory SQLite and always execute. A PostgreSQL round-trip test runs only when `MRDS_TEST_POSTGRES_URL` is set:

```bash
MRDS_TEST_POSTGRES_URL="postgresql+asyncpg://postgres:pw@127.0.0.1:5432/mrds" \
  uv run pytest tests/test_persistence.py::test_postgres_round_trip
```

## Deferred

Run submission APIs, workers, and baseline persistence build on this schema in later milestones. M9 provides the schema, migrations, repository, and readiness only.
