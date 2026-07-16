"""Tests for health API behavior."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from model_regression_detection.config import Environment, Settings
from model_regression_detection.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(environment=Environment.TEST, log_format="text")
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_live_returns_typed_service_metadata(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "model-regression-detection-system"
    assert payload["environment"] == "test"
    assert payload["supported_target_kinds"] == ["prompt", "model", "agent"]
    assert response.headers["X-Request-ID"]


def test_live_preserves_valid_request_id(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "ci-request-42"})

    assert response.headers["X-Request-ID"] == "ci-request-42"


def test_live_replaces_oversized_request_id(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "x" * 129})

    assert response.headers["X-Request-ID"] != "x" * 129
    assert len(response.headers["X-Request-ID"]) == 36


def test_production_disables_interactive_docs() -> None:
    app = create_app(Settings(environment=Environment.PRODUCTION, log_format="text"))
    with TestClient(app) as production_client:
        response = production_client.get("/docs")

    assert response.status_code == 404


def test_ready_without_database_reports_not_configured(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["database"] == "not_configured"


def test_ready_with_database_checks_connectivity() -> None:
    settings = Settings(
        environment=Environment.TEST,
        log_format="text",
        database_url="sqlite+aiosqlite:///:memory:",
    )
    with TestClient(create_app(settings)) as db_client:
        response = db_client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["database"] == "ok"
