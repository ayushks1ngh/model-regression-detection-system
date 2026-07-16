"""Tests for command-line operations."""

import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from model_regression_detection.cli import app

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip()


def test_health_command_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(
        url: str,
        *,
        timeout: float,
        follow_redirects: bool,
    ) -> httpx.Response:
        assert url == "http://service.test/health/live"
        assert timeout == 2.0
        assert follow_redirects is False
        request = httpx.Request("GET", url)
        return httpx.Response(
            200,
            request=request,
            json={"status": "ok", "service": "mrds", "version": "0.1.0"},
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    result = runner.invoke(
        app,
        ["health", "--url", "http://service.test/", "--timeout-seconds", "2"],
    )

    assert result.exit_code == 0
    assert "ok service=mrds version=0.1.0" in result.stdout


def test_health_command_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(*args: object, **kwargs: object) -> httpx.Response:
        del args, kwargs
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(httpx, "get", fake_get)
    result = runner.invoke(app, ["health"])

    assert result.exit_code == 1
    assert "Health check failed: ConnectError" in result.stderr


def test_health_command_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(*args: object, **kwargs: object) -> httpx.Response:
        del args, kwargs
        request = httpx.Request("GET", "http://service.test/health/live")
        response = httpx.Response(200, request=request, content=b"not-json")
        response.json = lambda: (_ for _ in ()).throw(json.JSONDecodeError("bad", "x", 0))  # type: ignore[method-assign]
        return response

    monkeypatch.setattr(httpx, "get", fake_get)
    result = runner.invoke(app, ["health"])

    assert result.exit_code == 1
    assert "Health check failed: JSONDecodeError" in result.stderr


def test_validate_command_json_output() -> None:
    path = Path(__file__).parents[1] / "examples" / "evaluation.yaml"

    result = runner.invoke(app, ["validate", str(path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "valid"
    assert payload["case_count"] == 2
    assert sorted(payload["targets"]) == ["agent", "model", "prompt"]
    assert len(payload["configuration_hash"]) == 64
    assert len(payload["dataset_hash"]) == 64


def test_validate_command_reports_validation_failure(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text('{"schema_version":"999"}', encoding="utf-8")

    result = runner.invoke(app, ["validate", str(path)])

    assert result.exit_code == 2
    assert "Unsupported schema_version" in result.stderr


def test_run_local_command_writes_deterministic_result(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    output = tmp_path / "run.json"

    result = runner.invoke(
        app,
        [
            "run-local",
            str(root / "examples" / "evaluation.yaml"),
            "--responses",
            str(root / "examples" / "fake-responses.json"),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert "total=2 success=1 errors=1 gate=error" in result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["run"]["status"] == "completed"
    assert [case["case_key"] for case in payload["run"]["cases"]] == ["refund-policy", "greeting"]
    assert payload["gate"]["outcome"] == "error"


def test_run_local_command_rejects_invalid_fixture(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    fixture = tmp_path / "invalid.json"
    fixture.write_text('{"responses":{"refund-policy":{}}}', encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run-local",
            str(root / "examples" / "evaluation.yaml"),
            "--responses",
            str(fixture),
        ],
    )

    assert result.exit_code == 2
    assert "exactly one of output or error is required" in result.stderr


def test_run_local_command_writes_versioned_report(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    report = tmp_path / "report.json"

    result = runner.invoke(
        app,
        [
            "run-local",
            str(root / "examples" / "evaluation.yaml"),
            "--responses",
            str(root / "examples" / "fake-responses.json"),
            "--report",
            str(report),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1"
    assert payload["gate_outcome"] == "error"
    assert payload["provenance"]["suite"] == "customer-support-smoke"
    assert [case["case_key"] for case in payload["cases"]] == ["refund-policy", "greeting"]
