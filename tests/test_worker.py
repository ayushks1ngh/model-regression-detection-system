"""Tests for the PostgreSQL-backed worker."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from model_regression_detection.execution import CancellationToken
from model_regression_detection.execution.report import execute_local_evaluation
from model_regression_detection.persistence import Base
from model_regression_detection.persistence.models import RunRow
from model_regression_detection.persistence.repository import RunRepository
from model_regression_detection.providers import (
    ErrorCategory,
    FakeProvider,
    FakeResponse,
    InferenceMessage,
    InferenceRequest,
    InferenceResult,
    ProviderError,
)
from model_regression_detection.specification.models import EvaluationSpecificationV1
from model_regression_detection.workers import RetryProvider, Worker
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


async def test_run_once_executes_and_completes_a_run() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)
    worker = Worker(factory, FakeProvider({"refund": FakeResponse(output="30 days")}))

    processed = await worker.run_once()

    assert processed is True
    async with factory() as session:
        run = await RunRepository(session).get_run(run_id)
        assert run is not None
        assert run.state == "completed"
        assert run.gate_outcome is not None
    await engine.dispose()


async def test_run_once_returns_false_when_nothing_to_claim() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    worker = Worker(factory, FakeProvider({}))

    assert await worker.run_once() is False
    await engine.dispose()


async def test_two_workers_never_claim_the_same_run() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _create_run(factory)

    async with factory() as session:
        repository = RunRepository(session)
        first_claim = await repository.claim_next_run("worker-a", lease_seconds=60)
        second_claim = await repository.claim_next_run("worker-b", lease_seconds=60)
        await session.commit()

    assert first_claim is not None
    assert second_claim is None
    await engine.dispose()


async def test_expired_lease_can_be_reclaimed_by_another_worker() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    async with factory() as session:
        claimed = await RunRepository(session).claim_next_run("worker-a", lease_seconds=60)
        await session.commit()
    assert claimed == run_id

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    async with factory() as session:
        reclaimed = await RunRepository(session).claim_next_run("worker-b", lease_seconds=60)
        await session.commit()

    assert reclaimed == run_id
    await engine.dispose()


async def test_stale_worker_cannot_finalize_after_lease_reclaimed() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    async with factory() as session:
        await RunRepository(session).claim_next_run("worker-a", lease_seconds=60)
        await session.commit()
    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        run.state = "running"
        run.worker_id = "worker-b"
        await session.commit()

    specification = EvaluationSpecificationV1.model_validate(valid_document())
    report = await execute_local_evaluation(
        specification, FakeProvider({"refund": FakeResponse(output="30 days")})
    )

    async with factory() as session:
        accepted = await RunRepository(session).complete_run(run_id, report, worker_id="worker-a")
        await session.commit()

    assert accepted is False
    async with factory() as session:
        run = await RunRepository(session).get_run(run_id)
        assert run is not None
        assert run.state == "running"
    await engine.dispose()


async def test_worker_id_defaults_to_a_unique_value() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    first = Worker(factory, FakeProvider({}))
    second = Worker(factory, FakeProvider({}))

    assert first.worker_id != second.worker_id
    await engine.dispose()


async def test_run_forever_stops_on_request() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    worker = Worker(factory, FakeProvider({}), poll_interval_seconds=0.01)

    worker.request_stop()
    await worker.run_forever()
    await engine.dispose()


# --- M12: RetryProvider tests ---


class _CountingProvider:
    """Provider that tracks calls and returns configurable results."""

    def __init__(self, results: list[InferenceResult]) -> None:
        self._results = list(results)
        self.call_count = 0

    async def generate(self, request: InferenceRequest) -> InferenceResult:
        self.call_count += 1
        return self._results.pop(0)


_SAMPLE_MESSAGE = (InferenceMessage(role="user", content="hello"),)


async def test_retry_provider_retries_on_retryable_error() -> None:
    success = InferenceResult(status="success", output="ok", latency_ms=0.0)
    retryable = InferenceResult(
        status="error",
        latency_ms=0.0,
        error=ProviderError(
            category=ErrorCategory.RATE_LIMITED,
            code="over_limit",
            message="Too fast",
            retryable=True,
        ),
    )
    inner = _CountingProvider([retryable, success])
    wrapped = RetryProvider(inner, max_retries=3, base_delay_seconds=0.01)

    request = InferenceRequest(
        request_id="test",
        model_id="m",
        messages=_SAMPLE_MESSAGE,
        temperature=0.0,
        max_output_tokens=100,
        timeout_seconds=5.0,
    )
    result = await wrapped.generate(request)

    assert result.status == "success"
    assert inner.call_count == 2


async def test_retry_provider_does_not_retry_permanent_error() -> None:
    permanent = InferenceResult(
        status="error",
        latency_ms=0.0,
        error=ProviderError(
            category=ErrorCategory.INVALID_REQUEST,
            code="bad_input",
            message="Bad request",
            retryable=False,
        ),
    )
    inner = _CountingProvider([permanent])
    wrapped = RetryProvider(inner, max_retries=3, base_delay_seconds=0.01)

    request = InferenceRequest(
        request_id="test",
        model_id="m",
        messages=_SAMPLE_MESSAGE,
        temperature=0.0,
        max_output_tokens=100,
        timeout_seconds=5.0,
    )
    result = await wrapped.generate(request)

    assert result.status == "error"
    assert inner.call_count == 1


async def test_retry_provider_stops_after_max_retries() -> None:
    retryable = InferenceResult(
        status="error",
        latency_ms=0.0,
        error=ProviderError(
            category=ErrorCategory.TRANSIENT_UPSTREAM,
            code="upstream_down",
            message="Server error",
            retryable=True,
        ),
    )
    inner = _CountingProvider([retryable, retryable, retryable, retryable])
    wrapped = RetryProvider(inner, max_retries=3, base_delay_seconds=0.01)

    request = InferenceRequest(
        request_id="test",
        model_id="m",
        messages=_SAMPLE_MESSAGE,
        temperature=0.0,
        max_output_tokens=100,
        timeout_seconds=5.0,
    )
    result = await wrapped.generate(request)

    assert result.status == "error"
    assert inner.call_count == 4  # initial + 3 retries


async def test_retry_provider_immediate_success_no_retries() -> None:
    success = InferenceResult(status="success", output="ok", latency_ms=0.0)
    inner = _CountingProvider([success])
    wrapped = RetryProvider(inner, max_retries=3, base_delay_seconds=0.01)

    request = InferenceRequest(
        request_id="test",
        model_id="m",
        messages=_SAMPLE_MESSAGE,
        temperature=0.0,
        max_output_tokens=100,
        timeout_seconds=5.0,
    )
    result = await wrapped.generate(request)

    assert result.status == "success"
    assert inner.call_count == 1


# --- M12: Heartbeat tests ---


async def test_heartbeat_extends_lease_during_execution() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    async with factory() as session:
        await RunRepository(session).claim_next_run("worker-hb", lease_seconds=3)
        await session.commit()

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        run.state = "running"

    class _SlowProvider:
        async def generate(self, request: InferenceRequest) -> InferenceResult:
            import asyncio as _asyncio

            await _asyncio.sleep(1.5)
            return InferenceResult(status="success", output="30 days", latency_ms=0.0)

    worker = Worker(
        factory,
        _SlowProvider(),
        worker_id="worker-hb",
        lease_seconds=3,
    )
    specification = EvaluationSpecificationV1.model_validate(valid_document())
    cancellation_token = CancellationToken()
    await worker._execute_with_heartbeat(run_id, specification, cancellation_token)

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        assert run.lease_expires_at is not None
        now = datetime.now(UTC).replace(tzinfo=None)
        raw = run.lease_expires_at
        expiry = raw.replace(tzinfo=None) if raw.tzinfo else raw
        assert expiry > now - timedelta(seconds=2)
    await engine.dispose()


async def test_run_once_with_retryable_provider_succeeds() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    class _RetryOnceProvider:
        def __init__(self) -> None:
            self._attempts: dict[str, int] = {}

        async def generate(self, request: InferenceRequest) -> InferenceResult:
            key = request.request_id
            self._attempts[key] = self._attempts.get(key, 0) + 1
            if self._attempts[key] == 1:
                return InferenceResult(
                    status="error",
                    latency_ms=0.0,
                    error=ProviderError(
                        category=ErrorCategory.RATE_LIMITED,
                        code="over_limit",
                        message="Too fast",
                        retryable=True,
                    ),
                )
            return InferenceResult(status="success", output="30 days", latency_ms=0.0)

    worker = Worker(
        factory,
        _RetryOnceProvider(),
        max_retries=3,
        base_retry_delay_seconds=0.01,
    )

    processed = await worker.run_once()

    assert processed is True
    async with factory() as session:
        run = await RunRepository(session).get_run(run_id)
        assert run is not None
        assert run.state == "completed"
    await engine.dispose()


# --- M13: Startup reconciliation ---


async def test_worker_reconciles_stranded_on_startup() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_run(factory)

    async with factory() as session:
        await RunRepository(session).claim_next_run("worker-a", lease_seconds=60)
        await session.commit()

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=60)
        await session.commit()

    worker = Worker(factory, FakeProvider({}), poll_interval_seconds=0.01)
    worker.request_stop()
    await worker.run_forever()

    async with factory() as session:
        run = await RunRepository(session).get_run(run_id)
        assert run is not None
        assert run.state == "failed"
        assert run.execution_status == "reconciled"
    await engine.dispose()
