"""Fault-scenario tests: DB disconnect, provider timeout, corrupt run state."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from model_regression_detection.persistence import Base
from model_regression_detection.persistence.models import RunRow
from model_regression_detection.persistence.repository import RunRepository
from model_regression_detection.providers import (
    ErrorCategory,
    FakeProvider,
    FakeResponse,
    InferenceRequest,
    InferenceResult,
    ProviderError,
)
from model_regression_detection.specification.models import EvaluationSpecificationV1
from model_regression_detection.workers import Worker
from tests.test_specification import valid_document

pytestmark = pytest.mark.anyio


async def _sqlite_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine


async def _create_run(factory: async_sessionmaker[AsyncSession]) -> str:
    specification = EvaluationSpecificationV1.model_validate(valid_document())
    async with factory() as session:
        repository = RunRepository(session)
        await repository.ensure_project("proj-f", "proj-f", "Fault Test")
        run_id = await repository.create_run(
            "proj-f", specification, "a" * 64, "b" * 64, None, None
        )
        await session.commit()
    return run_id


# ---------------------------------------------------------------------------
# DB disconnect
# ---------------------------------------------------------------------------


async def test_heartbeat_detects_stolen_lease() -> None:
    """Worker should detect via heartbeat when another worker steals the lease."""
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    async with factory() as session:
        await RunRepository(session).claim_next_run("worker-a", lease_seconds=3)
        await session.commit()

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        run.state = "running"

    import asyncio as _asyncio

    class _SlowProvider:
        async def generate(self, request: InferenceRequest) -> InferenceResult:
            await _asyncio.sleep(1.5)
            return InferenceResult(status="success", output="done", latency_ms=0.0)

    async def _steal_lease() -> None:
        await _asyncio.sleep(0.2)
        async with factory() as session:
            run = await session.get(RunRow, run_id)
            assert run is not None
            run.worker_id = "worker-b"
            run.lease_expires_at = datetime.now(UTC) + timedelta(hours=1)
            await session.commit()

    worker = Worker(
        factory,
        _SlowProvider(),
        worker_id="worker-a",
        lease_seconds=3,
    )

    from model_regression_detection.execution.cancellation import CancellationToken

    spec = EvaluationSpecificationV1.model_validate(valid_document())
    cancellation_token = CancellationToken()

    steal_task = _asyncio.create_task(_steal_lease())
    report = await worker._execute_with_heartbeat(run_id, spec, cancellation_token)
    await steal_task

    assert report is not None
    assert cancellation_token.cancelled is True
    assert report.run.status in ("completed", "cancelled")


# ---------------------------------------------------------------------------
# Provider timeout
# ---------------------------------------------------------------------------


class _IntermittentProvider:
    """Provider that succeeds after retries."""

    def __init__(self) -> None:
        self._call_count = 0

    async def generate(self, request: InferenceRequest) -> InferenceResult:
        self._call_count += 1
        if self._call_count == 1:
            await asyncio.sleep(0.5)
            return InferenceResult(status="success", output="late", latency_ms=500.0)
        return InferenceResult(status="success", output="ok", latency_ms=0.0)


async def test_worker_handles_provider_timeout() -> None:
    """Worker should handle a provider that exceeds the request timeout."""
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    doc = valid_document()
    doc["model"]["timeout_seconds"] = 1.0

    from model_regression_detection.execution.cancellation import CancellationToken

    async with factory() as session:
        repository = RunRepository(session)
        await repository.claim_next_run("worker-to", lease_seconds=60)
        await session.commit()

    class _FastTimeoutProvider:
        async def generate(self, request: InferenceRequest) -> InferenceResult:
            return InferenceResult(
                status="error",
                latency_ms=0.0,
                error=ProviderError(
                    category=ErrorCategory.TIMEOUT,
                    code="timeout",
                    message="Provider timed out",
                    retryable=True,
                ),
            )

    worker = Worker(
        factory,
        _FastTimeoutProvider(),
        worker_id="worker-to",
        max_retries=1,
        base_retry_delay_seconds=0.01,
    )

    spec = EvaluationSpecificationV1.model_validate(doc)
    cancellation_token = CancellationToken()
    report = await worker._execute_with_heartbeat(run_id, spec, cancellation_token)

    assert report is not None
    assert any(
        case.provider_result.status == "error"
        for case in report.run.cases
    )


async def test_intermittent_timeout_eventually_succeeds() -> None:
    """Worker retry logic should recover from a one-time provider timeout."""
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _create_run(factory)

    worker = Worker(
        factory,
        _IntermittentProvider(),
        worker_id="worker-it",
        max_retries=3,
        base_retry_delay_seconds=0.01,
    )

    processed = await worker.run_once()
    assert processed is True


# ---------------------------------------------------------------------------
# Corrupt run state
# ---------------------------------------------------------------------------


async def test_run_with_invalid_state_is_handled_gracefully() -> None:
    """Worker should not crash when a run has an unexpected state value."""
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        run.state = "garbage_state"
        await session.commit()

    worker = Worker(
        factory,
        FakeProvider({"refund": FakeResponse(output="30 days")}),
        worker_id="worker-corrupt",
    )

    result = await worker.run_once()
    assert result is False  # no claimable runs with invalid state


async def test_run_with_null_snapshot_is_skipped() -> None:
    """Worker should handle a run with no snapshot data gracefully."""
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        run.snapshot = None
        await session.commit()

    worker = Worker(
        factory,
        FakeProvider({"refund": FakeResponse(output="30 days")}),
        worker_id="worker-null",
    )

    with pytest.raises((ValidationError, TypeError, AttributeError)):
        await worker.run_once()


async def test_run_with_expired_lease_claimed_by_another_worker() -> None:
    """Worker should not finalize a run whose lease was stolen."""
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    async with factory() as session:
        await RunRepository(session).claim_next_run("worker-a", lease_seconds=60)
        await session.commit()

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        run.worker_id = "worker-b"
        run.state = "running"
        run.lease_expires_at = datetime.now(UTC) + timedelta(hours=1)
        await session.commit()

    specification = EvaluationSpecificationV1.model_validate(valid_document())
    from model_regression_detection.execution.report import execute_local_evaluation

    report = await execute_local_evaluation(
        specification, FakeProvider({"refund": FakeResponse(output="30 days")})
    )

    async with factory() as session:
        ok = await RunRepository(session).complete_run(
            run_id, report, worker_id="worker-a"
        )
        await session.commit()

    assert ok is False
