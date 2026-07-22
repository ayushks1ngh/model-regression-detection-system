"""Tests for baseline promotion and retrieval API."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

from model_regression_detection.config import Environment, Settings
from model_regression_detection.execution.report import execute_local_evaluation
from model_regression_detection.main import create_app
from model_regression_detection.persistence import Base, RunRepository
from model_regression_detection.providers import FakeProvider, FakeResponse
from model_regression_detection.specification.models import EvaluationSpecificationV1
from tests.test_specification import valid_document


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[tuple[TestClient, str]]:
    db = f"sqlite+aiosqlite:///{tmp_path / 'baselines_test.db'}"
    engine = create_async_engine(db)
    asyncio.run(_init_db(engine))

    settings = Settings(
        environment=Environment.TEST,
        log_format="text",
        database_url=db,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client, _run_id


_run_id: str = ""


async def _init_db(engine: object) -> None:
    async with engine.begin() as conn:  # type: ignore[union-attr]
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)  # type: ignore[arg-type]
    spec = EvaluationSpecificationV1.model_validate(valid_document())
    report = await execute_local_evaluation(
        spec, FakeProvider({"refund": FakeResponse(output="30 days", cost=0.02)})
    )
    async with factory() as session:
        repo = RunRepository(session)
        await repo.ensure_project("proj-b", "proj-b", "Baseline API Test")
        run_id = await repo.create_run(
            "proj-b",
            spec,
            report.run.configuration_hash,
            report.run.dataset_hash,
            None,
            None,
        )
        await repo.complete_run(run_id, report)
        await session.commit()
    global _run_id
    _run_id = run_id
    await engine.dispose()


def test_promote_and_get_baseline(ctx: tuple[TestClient, str]) -> None:
    client, run_id = ctx
    promote = client.post(
        f"/api/v1/projects/proj-b/baselines/production?run_id={run_id}",
        json={"reason": "Clean pass"},
    )
    assert promote.status_code == 200
    payload = promote.json()
    assert payload["channel"] == "production"
    assert payload["run_id"] == run_id
    assert payload["reason"] == "Clean pass"
    assert payload["previous_run_id"] is None
    assert payload["created"] is True

    get = client.get("/api/v1/projects/proj-b/baselines/production")
    assert get.status_code == 200
    assert get.json()["run_id"] == run_id


def test_promote_rejects_missing_run_id(ctx: tuple[TestClient, str]) -> None:
    client, _ = ctx
    resp = client.post(
        "/api/v1/projects/proj-b/baselines/production",
        json={"reason": "no run_id"},
    )
    assert resp.status_code == 400


def test_get_unknown_baseline_returns_404(ctx: tuple[TestClient, str]) -> None:
    client, _ = ctx
    resp = client.get("/api/v1/projects/proj-b/baselines/nonexistent")
    assert resp.status_code == 404


def test_list_baselines(ctx: tuple[TestClient, str]) -> None:
    client, run_id = ctx
    client.post(
        f"/api/v1/projects/proj-b/baselines/prod?run_id={run_id}",
        json={"reason": "prod"},
    )
    client.post(
        f"/api/v1/projects/proj-b/baselines/staging?run_id={run_id}",
        json={"reason": "staging"},
    )

    resp = client.get("/api/v1/projects/proj-b/baselines")
    assert resp.status_code == 200
    channels = [b["channel"] for b in resp.json()]
    assert channels == ["prod", "staging"]


def test_baselines_return_503_when_db_not_configured() -> None:
    settings = Settings(environment=Environment.TEST, log_format="text")
    with TestClient(create_app(settings)) as no_db:
        resp = no_db.post(
            "/api/v1/projects/proj-x/baselines/main?run_id=some-run",
            json={"reason": "test"},
        )
        assert resp.status_code == 503
