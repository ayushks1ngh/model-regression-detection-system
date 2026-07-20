"""Tests for run submission and status API endpoints."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from model_regression_detection.config import Environment, Settings
from model_regression_detection.main import create_app
from model_regression_detection.persistence import Base
from tests.test_specification import valid_document


async def _create_schema(database_url: str) -> None:
    """Apply the ORM schema to a fresh test database, mirroring a migrated deployment."""
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'runs_api_test.db'}"
    asyncio.run(_create_schema(database_url))
    settings = Settings(
        environment=Environment.TEST,
        log_format="text",
        database_url=database_url,
    )
    with TestClient(create_app(settings)) as test_client:
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


def test_create_run_returns_frozen_snapshot_hashes(client: TestClient) -> None:
    payload = submit(client)

    assert payload["state"] == "created"
    assert payload["project_id"] == "proj-1"
    assert len(payload["configuration_hash"]) == 64
    assert len(payload["dataset_hash"]) == 64


def test_get_run_status_after_creation(client: TestClient) -> None:
    created = submit(client)

    response = client.get(f"/api/v1/runs/{created['run_id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "created"
    assert payload["gate_outcome"] is None
    assert payload["total_cases"] is None


def test_get_unknown_run_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/runs/does-not-exist")

    assert response.status_code == 404


def test_invalid_specification_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/runs",
        json={"project_id": "proj-1", "specification": {"schema_version": "999"}},
    )

    assert response.status_code == 422


def test_idempotent_submission_returns_same_run(client: TestClient) -> None:
    first = submit(client, idempotency_key="key-abc")
    second = submit(client, idempotency_key="key-abc")

    assert first["run_id"] == second["run_id"]


def test_idempotency_conflict_on_different_project(client: TestClient) -> None:
    submit(client, idempotency_key="key-conflict")

    response = client.post(
        "/api/v1/runs",
        json={"project_id": "proj-2", "specification": valid_document()},
        headers={"Idempotency-Key": "key-conflict"},
    )

    assert response.status_code == 202


def test_idempotency_conflict_on_different_body_same_project(client: TestClient) -> None:
    submit(client, idempotency_key="key-body")
    changed = valid_document()
    changed["suite"] = "a-different-suite"

    response = client.post(
        "/api/v1/runs",
        json={"project_id": "proj-1", "specification": changed},
        headers={"Idempotency-Key": "key-body"},
    )

    assert response.status_code == 409


def test_empty_idempotency_key_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/runs",
        json={"project_id": "proj-1", "specification": valid_document()},
        headers={"Idempotency-Key": ""},
    )

    assert response.status_code == 400


def test_run_report_returns_full_evidence(client: TestClient) -> None:
    created = submit(client)
    run_id = created["run_id"]

    response = client.get(f"/api/v1/runs/{run_id}/report")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == run_id
    assert payload["state"] == "created"
    assert payload["gate_outcome"] is None
    assert payload["total_cases"] is None
    assert payload["metrics"] is None
    assert isinstance(payload["cases"], list)


def test_run_report_returns_404_for_unknown_run(client: TestClient) -> None:
    response = client.get("/api/v1/runs/does-not-exist/report")

    assert response.status_code == 404


def test_runs_api_returns_503_when_persistence_not_configured() -> None:
    settings = Settings(environment=Environment.TEST, log_format="text")
    with TestClient(create_app(settings)) as no_db_client:
        response = no_db_client.post(
            "/api/v1/runs",
            json={"project_id": "proj-1", "specification": valid_document()},
        )

    assert response.status_code == 503
