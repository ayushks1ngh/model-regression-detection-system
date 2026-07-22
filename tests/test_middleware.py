"""Tests for metrics, body limit, and health/readiness endpoints."""

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


def test_metrics_endpoint_returns_text(client: TestClient) -> None:
    """Metrics endpoint responds (even without prometheus_client)."""
    response = client.get("/metrics")
    assert response.status_code in (200, 501)
    assert "text/plain" in response.headers["content-type"]


def test_liveness_endpoint(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "model-regression-detection-system"
    assert "version" in payload
    assert "timestamp" in payload
    assert "supported_target_kinds" in payload


def test_readiness_without_database(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["database"] == "not_configured"


def test_body_limit_rejects_oversized_requests() -> None:
    settings = Settings(
        environment=Environment.TEST,
        log_format="text",
        max_request_body_size=100,
    )
    with TestClient(create_app(settings)) as small_limit_client:
        response = small_limit_client.post(
            "/api/v1/runs",
            content="x" * 200,
            headers={"Content-Type": "application/json", "Content-Length": "200"},
        )
        assert response.status_code == 413


def test_body_limit_allows_small_requests() -> None:
    settings = Settings(
        environment=Environment.TEST,
        log_format="text",
        max_request_body_size=1_000_000,
    )
    with TestClient(create_app(settings)) as normal_client:
        response = normal_client.get("/health/live")
        assert response.status_code == 200
