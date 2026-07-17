"""Tests for async persistence and the run repository."""

import os

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

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
