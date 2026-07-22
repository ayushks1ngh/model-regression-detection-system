"""Tests for run cancel endpoint and extended run API coverage."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from model_regression_detection.config import Environment, Settings
from model_regression_detection.execution.report import execute_local_evaluation
from model_regression_detection.main import create_app
from model_regression_detection.persistence import Base, RunRepository
from model_regression_detection.providers import FakeProvider, FakeResponse
from model_regression_detection.specification.models import EvaluationSpecificationV1
from tests.test_specification import valid_document


async def _bootstrap(db_url: str) -> tuple[str, str]:
    """Bootstrap DB, create a project and two runs: one created, one completed."""
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    spec = EvaluationSpecificationV1.model_validate(valid_document())
    report = await execute_local_evaluation(
        spec, FakeProvider({"refund": FakeResponse(output="30 days", cost=0.01)})
    )

    async with factory() as session:
        repo = RunRepository(session)
        await repo.ensure_project("proj-cancel", "proj-cancel", "Cancel Test")
        created_id = await repo.create_run("proj-cancel", spec, "hash1", "hash2", None, None)
        completed_id = await repo.create_run("proj-cancel", spec, "hash1", "hash2", None, None)
        await repo.complete_run(completed_id, report)
        await session.commit()
    await engine.dispose()
    return created_id, completed_id


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[tuple[TestClient, str, str]]:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'cancel_test.db'}"
    created_id, completed_id = asyncio.run(_bootstrap(db_url))
    settings = Settings(
        environment=Environment.TEST,
        log_format="text",
        database_url=db_url,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client, created_id, completed_id


def test_cancel_created_run_transitions_to_cancelled(
    ctx: tuple[TestClient, str, str],
) -> None:
    client, created_id, _ = ctx
    resp = client.post(f"/api/v1/runs/{created_id}/cancel")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["state"] == "cancelled"
    assert payload["already_cancelled"] is False


def test_cancel_completed_run_returns_409(
    ctx: tuple[TestClient, str, str],
) -> None:
    client, _, completed_id = ctx
    resp = client.post(f"/api/v1/runs/{completed_id}/cancel")
    assert resp.status_code == 409


def test_cancel_nonexistent_run_returns_404(
    ctx: tuple[TestClient, str, str],
) -> None:
    client, _, _ = ctx
    resp = client.post("/api/v1/runs/nonexistent-run/cancel")
    assert resp.status_code == 404


def test_cancel_already_cancelled_is_idempotent(
    ctx: tuple[TestClient, str, str],
) -> None:
    client, created_id, _ = ctx
    client.post(f"/api/v1/runs/{created_id}/cancel")
    resp = client.post(f"/api/v1/runs/{created_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["already_cancelled"] is True


def test_get_run_report_for_completed_run(
    ctx: tuple[TestClient, str, str],
) -> None:
    client, _, completed_id = ctx
    resp = client.get(f"/api/v1/runs/{completed_id}/report")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["state"] == "completed"
    assert payload["gate_outcome"] is not None
    assert isinstance(payload["cases"], list)
    assert payload["metrics"] is not None


def test_get_run_status_for_completed_run(
    ctx: tuple[TestClient, str, str],
) -> None:
    client, _, completed_id = ctx
    resp = client.get(f"/api/v1/runs/{completed_id}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["state"] == "completed"
    assert payload["gate_outcome"] is not None
    assert payload["total_cases"] is not None
