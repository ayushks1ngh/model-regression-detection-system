"""Tests for run cancellation and operational controls."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from model_regression_detection.config import Environment, Settings
from model_regression_detection.execution import CancellationToken, execute_local
from model_regression_detection.execution.models import LocalRunResult
from model_regression_detection.execution.report import execute_local_evaluation
from model_regression_detection.main import create_app
from model_regression_detection.persistence import Base
from model_regression_detection.persistence.models import RunRow
from model_regression_detection.persistence.repository import RunRepository
from model_regression_detection.providers import FakeProvider, FakeResponse
from model_regression_detection.providers.contracts import InferenceResult
from model_regression_detection.specification.models import EvaluationSpecificationV1
from tests.test_specification import valid_document

pytestmark = pytest.mark.anyio


async def _sqlite_engine() -> AsyncEngine:
    """Create an in-memory SQLite engine with the schema applied."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine


async def _create_run(factory: async_sessionmaker[AsyncSession]) -> str:
    """Create one project-scoped run in the created state and return its ID."""
    specification = EvaluationSpecificationV1.model_validate(valid_document())
    async with factory() as session:
        repository = RunRepository(session)
        await repository.ensure_project("proj-1", "proj-1", "One")
        run_id = await repository.create_run(
            "proj-1", specification, "a" * 64, "b" * 64, None, None
        )
        await session.commit()
    return run_id


# ── CancellationToken ────────────────────────────────────────────────────


async def test_cancellation_token_not_cancelled_by_default() -> None:
    token = CancellationToken()
    assert token.cancelled is False


async def test_cancellation_token_cancelled_after_request() -> None:
    token = CancellationToken()
    token.request_cancel()
    assert token.cancelled is True


async def test_cancellation_token_wait_returns_when_cancelled() -> None:
    token = CancellationToken()

    async def cancel_soon() -> None:
        await asyncio.sleep(0.01)
        token.request_cancel()

    async with asyncio.TaskGroup() as tg:
        tg.create_task(cancel_soon())
        await token.wait_cancel()

    assert token.cancelled is True


# ── Repository: cancel_run ───────────────────────────────────────────────


async def test_cancel_created_run_transitions_to_cancelled() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    async with factory() as session:
        repo = RunRepository(session)
        result = await repo.cancel_run(run_id)
        await session.commit()
        assert result is True

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        assert run.state == "cancelled"
        assert run.completed_at is not None
    await engine.dispose()


async def test_cancel_running_run_transitions_to_cancelling() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    async with factory() as session:
        repo = RunRepository(session)
        claimed = await repo.claim_next_run("worker-1", lease_seconds=60)
        assert claimed == run_id
        await session.commit()

    async with factory() as session:
        repo = RunRepository(session)
        result = await repo.cancel_run(run_id)
        await session.commit()
        assert result is True

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        assert run.state == "cancelling"
    await engine.dispose()


# ── API cancel endpoint ──────────────────────────────────────────────────


async def _create_schema(database_url: str) -> None:
    """Apply the ORM schema to a fresh test database, mirroring a migrated deployment."""
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'cancel_api_test.db'}"
    asyncio.run(_create_schema(database_url))
    settings = Settings(
        environment=Environment.TEST,
        log_format="text",
        database_url=database_url,
    )
    with TestClient(create_app(settings)) as test_client:
        test_client.app.state._test_db_path = database_url.replace(
            "sqlite+aiosqlite:///", ""
        )
        yield test_client


def submit(client: TestClient, idempotency_key: str | None = None) -> dict[str, object]:
    """Submit a run and return the parsed response body."""
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
    response = client.post(
        "/api/v1/runs",
        json={"project_id": "proj-1", "specification": valid_document()},
        headers=headers,
    )
    assert response.status_code == 202
    return response.json()


def test_cancel_created_run_returns_cancelled(client: TestClient) -> None:
    created = submit(client)
    run_id = created["run_id"]

    response = client.post(f"/api/v1/runs/{run_id}/cancel")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == run_id
    assert payload["state"] == "cancelled"
    assert payload["already_cancelled"] is False


def test_cancel_already_cancelled_returns_idempotent(client: TestClient) -> None:
    created = submit(client)
    run_id = created["run_id"]

    assert client.post(f"/api/v1/runs/{run_id}/cancel").status_code == 200
    response = client.post(f"/api/v1/runs/{run_id}/cancel")

    assert response.status_code == 200
    payload = response.json()
    assert payload["already_cancelled"] is True
    assert payload["state"] == "cancelled"


def test_cancel_completed_run_returns_409(client: TestClient) -> None:
    created = submit(client)
    run_id = created["run_id"]

    # Simulate a completed run by directly updating the DB
    import sqlite3
    db_path = client.app.state._test_db_path
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE runs SET state = 'completed', gate_outcome = 'pass', total_cases = 1, "
        "completed_at = datetime('now') WHERE id = ?",
        (run_id,),
    )
    conn.commit()
    conn.close()

    response = client.post(f"/api/v1/runs/{run_id}/cancel")
    assert response.status_code == 409


def test_cancel_unknown_run_returns_404(client: TestClient) -> None:
    response = client.post("/api/v1/runs/does-not-exist/cancel")
    assert response.status_code == 404


async def test_cancel_already_cancelled_run_is_idempotent() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    async with factory() as session:
        repo = RunRepository(session)
        await repo.cancel_run(run_id)
        await session.commit()

    async with factory() as session:
        repo = RunRepository(session)
        result = await repo.cancel_run(run_id)
        await session.commit()
        assert result is True

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        assert run.state == "cancelled"
    await engine.dispose()


async def test_cancel_completed_run_returns_false() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    async with factory() as session:
        repo = RunRepository(session)
        await repo.claim_next_run("worker-1", lease_seconds=60)
        await session.commit()

    specification = EvaluationSpecificationV1.model_validate(valid_document())
    report = await execute_local_evaluation(
        specification, FakeProvider({"refund": FakeResponse(output="30 days", cost=0.02)})
    )

    async with factory() as session:
        repo = RunRepository(session)
        await repo.complete_run(run_id, report, worker_id="worker-1")
        await session.commit()

    async with factory() as session:
        repo = RunRepository(session)
        result = await repo.cancel_run(run_id)
        await session.commit()
        assert result is False
    await engine.dispose()


async def test_cancel_unknown_run_raises() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        repo = RunRepository(session)
        with pytest.raises(LookupError, match="does not exist"):
            await repo.cancel_run("nonexistent")
    await engine.dispose()


# ── Repository: acknowledge_cancellation ─────────────────────────────────


async def test_acknowledge_cancellation_with_report() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    async with factory() as session:
        repo = RunRepository(session)
        await repo.claim_next_run("worker-1", lease_seconds=60)
        await repo.cancel_run(run_id)
        await session.commit()

    specification = EvaluationSpecificationV1.model_validate(valid_document())
    report = await execute_local_evaluation(
        specification, FakeProvider({"refund": FakeResponse(output="30 days", cost=0.02)})
    )

    async with factory() as session:
        repo = RunRepository(session)
        acked = await repo.acknowledge_cancellation(run_id, "worker-1", report)
        await session.commit()
        assert acked is True

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        assert run.state == "cancelled"
        assert run.gate_outcome == report.gate.outcome.value
        assert run.total_cases == report.run.total_cases
        assert run.metrics is not None
    await engine.dispose()


async def test_acknowledge_cancellation_without_report() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    async with factory() as session:
        repo = RunRepository(session)
        await repo.claim_next_run("worker-1", lease_seconds=60)
        await repo.cancel_run(run_id)
        await session.commit()

    async with factory() as session:
        repo = RunRepository(session)
        acked = await repo.acknowledge_cancellation(run_id, "worker-1")
        await session.commit()
        assert acked is True

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        assert run.state == "cancelled"
        assert run.completed_at is not None
    await engine.dispose()


async def test_acknowledge_cancellation_rejects_wrong_worker() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    async with factory() as session:
        repo = RunRepository(session)
        await repo.claim_next_run("worker-1", lease_seconds=60)
        await repo.cancel_run(run_id)
        await session.commit()

    async with factory() as session:
        repo = RunRepository(session)
        acked = await repo.acknowledge_cancellation(run_id, "worker-2")
        await session.commit()
        assert acked is False
    await engine.dispose()


async def test_acknowledge_cancellation_rejects_wrong_state() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    async with factory() as session:
        repo = RunRepository(session)
        acked = await repo.acknowledge_cancellation(run_id, "worker-1")
        await session.commit()
        assert acked is False  # not in cancelling state
    await engine.dispose()


# ── Repository: reconcile_stranded_runs with cancelling ──────────────────


async def test_reconcile_stranded_cancelling_run() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    async with factory() as session:
        repo = RunRepository(session)
        await repo.claim_next_run("worker-1", lease_seconds=60)
        await repo.cancel_run(run_id)
        await session.commit()

    # Force lease expiry
    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=120)
        await session.commit()

    async with factory() as session:
        repo = RunRepository(session)
        count = await repo.reconcile_stranded_runs(lease_grace_seconds=0)
        await session.commit()
        assert count == 1

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        assert run.state == "cancelled"
        assert run.completed_at is not None
    await engine.dispose()


# ── execute_local with cancellation token ────────────────────────────────


async def test_execute_local_stops_on_cancellation() -> None:
    token = CancellationToken()
    token.request_cancel()

    specification = EvaluationSpecificationV1.model_validate(valid_document())
    result = await execute_local(
        specification,
        FakeProvider({"refund": FakeResponse(output="30 days")}),
        cancellation_token=token,
    )

    assert result.status == "cancelled"
    assert len(result.cases) == 0  # no cases executed


async def test_execute_local_returns_partial_results_on_mid_run_cancel() -> None:
    base = EvaluationSpecificationV1.model_validate(valid_document())
    original_cases = list(base.cases)
    # Add a second case so we can cancel after the first
    specification = base.model_copy(update={"cases": (original_cases[0], original_cases[0])})

    token = CancellationToken()
    call_count = 0

    class _CancelAfterFirstProvider:
        async def generate(self, *args: object, **kwargs: object) -> InferenceResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(0.05)
            return InferenceResult(status="success", output="partial", latency_ms=0.0)

    async def run_with_cancel() -> LocalRunResult:
        result = await execute_local(
            specification, _CancelAfterFirstProvider(), cancellation_token=token
        )
        return result

    async with asyncio.TaskGroup() as tg:
        task = tg.create_task(run_with_cancel())

        await asyncio.sleep(0.01)
        token.request_cancel()

    result = task.result()
    assert result.status == "cancelled"
    assert len(result.cases) == 1  # only first case executed


# ── Worker cancellation ──────────────────────────────────────────────────


async def test_cancelled_created_run_is_not_claimed_by_worker() -> None:
    """A created run that is cancelled should not be picked up by the worker."""
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    from model_regression_detection.workers import Worker

    worker = Worker(factory, FakeProvider({"refund": FakeResponse(output="30 days")}))

    async with factory() as session:
        await RunRepository(session).cancel_run(run_id)
        await session.commit()

    # Worker should not claim the cancelled run
    processed = await worker.run_once()
    assert processed is False

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        assert run.state == "cancelled"
    await engine.dispose()


async def test_worker_detects_cancellation_during_heartbeat() -> None:
    """When a running run is cancelled, the worker detects it via heartbeat failure."""
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    base_spec = EvaluationSpecificationV1.model_validate(valid_document())
    original_cases = list(base_spec.cases)
    # Create unique cases with different keys so the worker has time to observe cancellation
    extra_cases = []
    for i in range(2):
        c = original_cases[0].model_copy(update={"key": f"case-{i}"})
        extra_cases.append(c)
    spec_with_cases = base_spec.model_copy(update={"cases": tuple(original_cases + extra_cases)})

    async with factory() as session:
        repository = RunRepository(session)
        await repository.ensure_project("proj-1", "proj-1", "One")
        run_id = await repository.create_run(
            "proj-1", spec_with_cases, "a" * 64, "b" * 64, None, None
        )
        await session.commit()

    from model_regression_detection.workers import Worker

    call_count = 0

    class _SlowProvider:
        async def generate(self, *args: object, **kwargs: object) -> InferenceResult:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(2.0)
            return InferenceResult(status="success", output="partial", latency_ms=0.0)

    worker = Worker(
        factory,
        _SlowProvider(),
        worker_id="worker-cancel",
        lease_seconds=3,
        poll_interval_seconds=0.1,
    )

    # Start worker execution in background
    async with asyncio.TaskGroup() as tg:
        task = tg.create_task(worker.run_once())

        # Wait for the worker to claim and start executing the first case
        await asyncio.sleep(0.05)

        # Cancel the run while first case is executing
        async with factory() as session:
            await RunRepository(session).cancel_run(run_id)
            await session.commit()

        # Give time for first case to finish and heartbeat to detect cancellation
        await asyncio.sleep(3.0)

    processed = task.result()
    assert processed is True

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        assert run.state == "cancelled"
    await engine.dispose()
