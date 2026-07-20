"""Tests for async persistence and the run repository."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from model_regression_detection.execution.report import (
    LocalEvaluationReport,
    execute_local_evaluation,
)
from model_regression_detection.persistence import (
    Base,
    RunRepository,
    database_ready,
    dispose_engine,
)
from model_regression_detection.persistence.models import CaseRow, RunRow
from model_regression_detection.persistence.repository import IdempotencyConflictError
from model_regression_detection.providers import FakeProvider, FakeResponse
from model_regression_detection.specification.models import EvaluationSpecificationV1
from tests.test_specification import valid_document

pytestmark = pytest.mark.anyio


async def _sqlite_engine() -> AsyncEngine:
    """Create an in-memory SQLite engine with the schema applied."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine


def _specification() -> EvaluationSpecificationV1:
    """Build the shared validated specification fixture."""
    return EvaluationSpecificationV1.model_validate(valid_document())


async def _report(specification: EvaluationSpecificationV1) -> LocalEvaluationReport:
    """Execute the fixture specification and return its evaluation report."""
    return await execute_local_evaluation(
        specification,
        FakeProvider({"refund": FakeResponse(output="30 days", cost=0.02)}),
    )


async def test_database_ready_true_for_live_engine() -> None:
    engine = await _sqlite_engine()
    assert await database_ready(engine) is True
    await dispose_engine(engine)


async def test_create_then_complete_run() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    specification = _specification()
    report = await _report(specification)

    async with factory() as session:
        repository = RunRepository(session)
        await repository.ensure_project("proj-1", "proj-1", "Project One")
        run_id = await repository.create_run(
            "proj-1",
            specification,
            report.run.configuration_hash,
            report.run.dataset_hash,
            None,
            None,
        )
        await session.commit()

    async with factory() as session:
        created = await RunRepository(session).get_run(run_id)
        assert created is not None
        assert created.state == "created"
        assert created.gate_outcome is None
        assert created.cases == []

    async with factory() as session:
        await RunRepository(session).complete_run(run_id, report)
        await session.commit()

    async with factory() as session:
        completed = await RunRepository(session).get_run(run_id)
        assert completed is not None
        assert completed.state == "completed"
        assert completed.gate_outcome == report.gate.outcome.value
        assert [case.case_key for case in completed.cases] == ["refund"]
    await dispose_engine(engine)


async def test_completing_unknown_run_raises() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    report = await _report(_specification())

    async with factory() as session:
        with pytest.raises(LookupError):
            await RunRepository(session).complete_run("missing-run", report)
    await dispose_engine(engine)


async def test_idempotent_submission_returns_same_run() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    specification = _specification()

    async with factory() as session:
        repository = RunRepository(session)
        await repository.ensure_project("proj-1", "proj-1", "One")
        first_id = await repository.create_run(
            "proj-1", specification, "a" * 64, "b" * 64, "key-1", "hash-1"
        )
        await session.commit()

    async with factory() as session:
        second_id = await RunRepository(session).create_run(
            "proj-1", specification, "a" * 64, "b" * 64, "key-1", "hash-1"
        )
        await session.commit()

    assert first_id == second_id
    await dispose_engine(engine)


async def test_idempotent_submission_conflict_on_different_body() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    specification = _specification()

    async with factory() as session:
        repository = RunRepository(session)
        await repository.ensure_project("proj-1", "proj-1", "One")
        await repository.create_run("proj-1", specification, "a" * 64, "b" * 64, "key-1", "hash-1")
        await session.commit()

    async with factory() as session:
        with pytest.raises(IdempotencyConflictError):
            await RunRepository(session).create_run(
                "proj-1", specification, "a" * 64, "b" * 64, "key-1", "hash-2"
            )
    await dispose_engine(engine)


@pytest.mark.skipif(
    not os.environ.get("MRDS_TEST_POSTGRES_URL"),
    reason="Set MRDS_TEST_POSTGRES_URL to run the PostgreSQL integration test",
)
async def test_postgres_first_idempotent_submission_succeeds() -> None:  # pragma: no cover
    """Regression test: PostgreSQL enforces run/idempotency-record insert order.

    SQLite does not enforce this foreign key ordering within one flush by
    default, so this defect was only observable against a real PostgreSQL
    database. create_run must flush the run insert before the idempotency
    record insert.
    """
    engine = create_async_engine(os.environ["MRDS_TEST_POSTGRES_URL"])
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    specification = _specification()

    async with factory() as session:
        repository = RunRepository(session)
        await repository.ensure_project("proj-1", "proj-1", "One")
        await session.commit()

    async with factory() as session:
        run_id = await RunRepository(session).create_run(
            "proj-1", specification, "a" * 64, "b" * 64, "key-1", "hash-1"
        )
        await session.commit()

    assert run_id
    await dispose_engine(engine)


async def test_duplicate_case_key_is_rejected() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        await RunRepository(session).ensure_project("proj-1", "proj-1", "One")
        session.add(
            RunRow(
                id="run-1",
                project_id="proj-1",
                suite="s",
                configuration_hash="a" * 64,
                dataset_hash="b" * 64,
                snapshot={},
                state="completed",
                execution_status="completed",
                gate_outcome="pass",
                total_cases=1,
                metrics={},
            )
        )
        session.add(
            CaseRow(
                id="c1",
                run_id="run-1",
                case_key="dup",
                ordinal=0,
                outcome="passed",
                provider_status="success",
                evidence={},
            )
        )
        session.add(
            CaseRow(
                id="c2",
                run_id="run-1",
                case_key="dup",
                ordinal=1,
                outcome="passed",
                provider_status="success",
                evidence={},
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
    await dispose_engine(engine)


async def test_list_runs_scoped_to_project() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    specification = _specification()
    report = await _report(specification)

    async with factory() as session:
        repository = RunRepository(session)
        await repository.ensure_project("proj-1", "proj-1", "One")
        await repository.ensure_project("proj-2", "proj-2", "Two")
        run_id = await repository.create_run(
            "proj-1",
            specification,
            report.run.configuration_hash,
            report.run.dataset_hash,
            None,
            None,
        )
        await repository.complete_run(run_id, report)
        await session.commit()

    async with factory() as session:
        assert len(await RunRepository(session).list_runs("proj-1")) == 1
        assert await RunRepository(session).list_runs("proj-2") == []
    await dispose_engine(engine)


async def test_failed_transaction_leaves_no_partial_run() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        repository = RunRepository(session)
        await repository.ensure_project("proj-1", "proj-1", "One")
        session.add(
            RunRow(
                id="run-x",
                project_id="proj-1",
                suite="s",
                configuration_hash="a" * 64,
                dataset_hash="b" * 64,
                snapshot={},
                state="completed",
                execution_status="completed",
                gate_outcome="pass",
                total_cases=1,
                metrics={},
            )
        )
        session.add(
            CaseRow(
                id="c1",
                run_id="run-x",
                case_key="dup",
                ordinal=0,
                outcome="passed",
                provider_status="success",
                evidence={},
            )
        )
        session.add(
            CaseRow(
                id="c2",
                run_id="run-x",
                case_key="dup",
                ordinal=1,
                outcome="passed",
                provider_status="success",
                evidence={},
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    async with factory() as session:
        assert await RunRepository(session).get_run("run-x") is None
    await dispose_engine(engine)


@pytest.mark.skipif(
    not os.environ.get("MRDS_TEST_POSTGRES_URL"),
    reason="Set MRDS_TEST_POSTGRES_URL to run the PostgreSQL integration test",
)
async def test_postgres_round_trip() -> None:  # pragma: no cover - opt-in integration test
    engine = create_async_engine(os.environ["MRDS_TEST_POSTGRES_URL"])
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    specification = _specification()
    report = await _report(specification)
    async with factory() as session:
        repository = RunRepository(session)
        await repository.ensure_project("proj-1", "proj-1", "One")
        run_id = await repository.create_run(
            "proj-1",
            specification,
            report.run.configuration_hash,
            report.run.dataset_hash,
            None,
            None,
        )
        await repository.complete_run(run_id, report)
        await session.commit()
    async with factory() as session:
        loaded = await RunRepository(session).get_run(run_id)
        assert loaded is not None
    await dispose_engine(engine)


# --- M13: Stranded run reconciliation ---


async def test_reconcile_fails_stranded_running_runs() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    specification = _specification()

    async with factory() as session:
        repo = RunRepository(session)
        await repo.ensure_project("proj-1", "proj-1", "One")
        run_id = await repo.create_run(
            "proj-1", specification, "a" * 64, "b" * 64, None, None
        )
        await session.commit()

    async with factory() as session:
        repo = RunRepository(session)
        await repo.claim_next_run("worker-a", lease_seconds=60)
        await session.commit()

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=60)
        await session.commit()

    async with factory() as session:
        repo = RunRepository(session)
        count = await repo.reconcile_stranded_runs(lease_grace_seconds=0)
        await session.commit()
        assert count == 1

    async with factory() as session:
        run = await RunRepository(session).get_run(run_id)
        assert run is not None
        assert run.state == "failed"
        assert run.execution_status == "reconciled"
        assert run.gate_outcome == "error"
        assert run.completed_at is not None
    await dispose_engine(engine)


async def test_reconcile_skips_active_leases() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    specification = _specification()

    async with factory() as session:
        repo = RunRepository(session)
        await repo.ensure_project("proj-1", "proj-1", "One")
        run_id = await repo.create_run(
            "proj-1", specification, "a" * 64, "b" * 64, None, None
        )
        await session.commit()

    async with factory() as session:
        await RunRepository(session).claim_next_run("worker-a", lease_seconds=60)
        await session.commit()

    async with factory() as session:
        repo = RunRepository(session)
        count = await repo.reconcile_stranded_runs(lease_grace_seconds=0)
        await session.commit()
        assert count == 0

    async with factory() as session:
        run = await RunRepository(session).get_run(run_id)
        assert run is not None
        assert run.state == "running"
    await dispose_engine(engine)


async def test_reconcile_is_idempotent() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    specification = _specification()

    async with factory() as session:
        repo = RunRepository(session)
        await repo.ensure_project("proj-1", "proj-1", "One")
        run_id = await repo.create_run(
            "proj-1", specification, "a" * 64, "b" * 64, None, None
        )
        await session.commit()

    async with factory() as session:
        await RunRepository(session).claim_next_run("worker-a", lease_seconds=60)
        await session.commit()

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=60)
        await session.commit()

    async with factory() as session:
        repo = RunRepository(session)
        first = await repo.reconcile_stranded_runs(lease_grace_seconds=0)
        await session.commit()
        second = await repo.reconcile_stranded_runs(lease_grace_seconds=0)
        await session.commit()
        assert first == 1
        assert second == 0

    async with factory() as session:
        run = await RunRepository(session).get_run(run_id)
        assert run is not None
        assert run.state == "failed"
    await dispose_engine(engine)


async def test_reconcile_stale_created_runs() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    specification = _specification()

    async with factory() as session:
        repo = RunRepository(session)
        await repo.ensure_project("proj-1", "proj-1", "One")
        run_id = await repo.create_run(
            "proj-1", specification, "a" * 64, "b" * 64, None, None
        )
        await session.commit()

    async with factory() as session:
        run = await session.get(RunRow, run_id)
        assert run is not None
        run.created_at = datetime.now(UTC) - timedelta(days=7)
        await session.commit()

    async with factory() as session:
        repo = RunRepository(session)
        count = await repo.reconcile_stranded_runs(max_created_age_seconds=3600)
        await session.commit()
        assert count == 1

    async with factory() as session:
        run = await RunRepository(session).get_run(run_id)
        assert run is not None
        assert run.state == "failed"
        assert run.metrics["reason"] == "stale_created"
    await dispose_engine(engine)


# --- M14: Baseline promotion ---


async def _create_completed_pass_run(
    factory: async_sessionmaker[AsyncSession],
) -> str:
    """Create a project and completed passing run, returning the run ID."""
    specification = _specification()
    report = await _report(specification)
    async with factory() as session:
        repo = RunRepository(session)
        await repo.ensure_project("proj-baseline", "proj-baseline", "Baseline Test")
        run_id = await repo.create_run(
            "proj-baseline",
            specification,
            report.run.configuration_hash,
            report.run.dataset_hash,
            None,
            None,
        )
        await repo.complete_run(run_id, report)
        await session.commit()
    return run_id


async def test_promote_run_creates_new_baseline() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_completed_pass_run(factory)

    async with factory() as session:
        repo = RunRepository(session)
        result = await repo.promote_run("proj-baseline", "production", run_id, "Good run")
        await session.commit()

    assert result is not None
    created, record = result
    assert created is True
    assert record.channel == "production"
    assert record.run_id == run_id
    assert record.reason == "Good run"
    assert record.previous_run_id is None

    async with factory() as session:
        loaded = await RunRepository(session).get_baseline("proj-baseline", "production")
        assert loaded is not None
        assert loaded.run_id == run_id
    await dispose_engine(engine)


async def test_promote_run_rejects_ineligible_run() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    specification = _specification()

    async with factory() as session:
        repo = RunRepository(session)
        await repo.ensure_project("proj-baseline", "proj-baseline", "Test")
        run_id = await repo.create_run(
            "proj-baseline", specification, "a" * 64, "b" * 64, None, None
        )
        await session.commit()

    async with factory() as session:
        repo = RunRepository(session)
        result = await repo.promote_run("proj-baseline", "production", run_id, "Should fail")
        await session.commit()

    assert result is None
    await dispose_engine(engine)


async def test_promote_run_updates_existing_baseline() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    first_id = await _create_completed_pass_run(factory)
    second_id = await _create_completed_pass_run(factory)

    async with factory() as session:
        repo = RunRepository(session)
        first_result = await repo.promote_run("proj-baseline", "main", first_id, "First")
        await session.commit()
    assert first_result is not None

    async with factory() as session:
        repo = RunRepository(session)
        second_result = await repo.promote_run("proj-baseline", "main", second_id, "Second")
        await session.commit()

    assert second_result is not None
    created, record = second_result
    assert created is False
    assert record.run_id == second_id
    assert record.previous_run_id == first_id
    assert record.reason == "Second"

    async with factory() as session:
        loaded = await RunRepository(session).get_baseline("proj-baseline", "main")
        assert loaded is not None
        assert loaded.run_id == second_id
    await dispose_engine(engine)


async def test_promote_run_same_run_is_idempotent() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_completed_pass_run(factory)

    async with factory() as session:
        repo = RunRepository(session)
        await repo.promote_run("proj-baseline", "stable", run_id, "v1")
        await session.commit()

    async with factory() as session:
        repo = RunRepository(session)
        result = await repo.promote_run("proj-baseline", "stable", run_id, "v1 again")
        await session.commit()

    assert result is not None
    created, record = result
    assert created is True  # already pointed to same run
    assert record.run_id == run_id
    await dispose_engine(engine)


async def test_list_baselines_scoped_to_project() -> None:
    engine = await _sqlite_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    run_id = await _create_completed_pass_run(factory)

    async with factory() as session:
        repo = RunRepository(session)
        await repo.promote_run("proj-baseline", "prod", run_id, "Prod")
        await repo.promote_run("proj-baseline", "staging", run_id, "Staging")
        await session.commit()

    async with factory() as session:
        baselines = await RunRepository(session).list_baselines("proj-baseline")
        assert len(baselines) == 2
        assert [b.channel for b in baselines] == ["prod", "staging"]

    async with factory() as session:
        baselines = await RunRepository(session).list_baselines("other-project")
        assert baselines == []
    await dispose_engine(engine)
