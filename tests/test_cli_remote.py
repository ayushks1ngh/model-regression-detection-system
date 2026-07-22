"""Tests for CLI submit/status/wait/download commands (M17)."""

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from model_regression_detection.cli import EXIT_ERROR, EXIT_PASS, EXIT_REGRESSION, EXIT_TIMEOUT, app
from tests.test_specification import valid_document

runner = CliRunner()


def _mock_response(status_code: int, json_data: dict) -> object:
    mock = type("MockResponse", (), {})()
    mock.status_code = status_code
    mock.json = lambda: json_data
    mock.text = json.dumps(json_data)
    if status_code >= 400:

        def _raise() -> None:
            raise httpx_exc(status_code, mock)

        mock.raise_for_status = _raise
    else:
        mock.raise_for_status = lambda: None
    return mock


def httpx_exc(status_code: int, response: object) -> Exception:
    import httpx

    return httpx.HTTPStatusError(
        "error",
        request=type("Req", (), {})(),
        response=response,  # type: ignore[arg-type]
    )


def _write_spec(tmp_path: Path, name: str = "spec.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(valid_document()), encoding="utf-8")
    return path


def test_submit_success(tmp_path: Path) -> None:
    spec = _write_spec(tmp_path)
    with patch("model_regression_detection.cli.httpx.post") as mock_post:
        mock_post.return_value = _mock_response(202, {"run_id": "run-abc"})
        result = runner.invoke(app, ["submit", str(spec), "--project-id", "proj-1"])

    assert result.exit_code == EXIT_PASS
    assert "run-abc" in result.stdout


def test_submit_spec_load_error(tmp_path: Path) -> None:
    spec = tmp_path / "nonexistent.json"
    result = runner.invoke(app, ["submit", str(spec), "--project-id", "proj-1"])

    assert result.exit_code == EXIT_ERROR


def test_submit_timeout(tmp_path: Path) -> None:
    import httpx

    spec = _write_spec(tmp_path)
    with patch("model_regression_detection.cli.httpx.post") as mock_post:
        mock_post.side_effect = httpx.TimeoutException("timeout")
        result = runner.invoke(app, ["submit", str(spec), "--project-id", "proj-1"])

    assert result.exit_code == EXIT_TIMEOUT


def test_submit_http_error(tmp_path: Path) -> None:
    spec = _write_spec(tmp_path)
    with patch("model_regression_detection.cli.httpx.post") as mock_post:
        mock_post.return_value = _mock_response(400, {"detail": "bad request"})
        result = runner.invoke(app, ["submit", str(spec), "--project-id", "proj-1"])

    assert result.exit_code == EXIT_ERROR


def test_with_runner() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == EXIT_PASS


def test_status_pass() -> None:
    with patch("model_regression_detection.cli.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(
            200, {"state": "completed", "gate_outcome": "pass", "total_cases": 5}
        )
        result = runner.invoke(app, ["status", "run-abc"])

    assert result.exit_code == EXIT_PASS
    assert "completed" in result.stdout
    assert "pass" in result.stdout


def test_status_fail() -> None:
    with patch("model_regression_detection.cli.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(
            200, {"state": "completed", "gate_outcome": "fail", "total_cases": 5}
        )
        result = runner.invoke(app, ["status", "run-abc"])

    assert result.exit_code == EXIT_REGRESSION


def test_status_gate_error() -> None:
    with patch("model_regression_detection.cli.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(200, {"state": "failed", "gate_outcome": "error"})
        result = runner.invoke(app, ["status", "run-abc"])

    assert result.exit_code == EXIT_ERROR


def test_status_404() -> None:
    with patch("model_regression_detection.cli.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(404, {"detail": "not found"})
        result = runner.invoke(app, ["status", "run-abc"])

    assert result.exit_code == EXIT_ERROR


def test_status_json_output() -> None:
    with patch("model_regression_detection.cli.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(200, {"state": "completed", "gate_outcome": "pass"})
        result = runner.invoke(app, ["status", "run-abc", "--json"])

    assert result.exit_code == EXIT_PASS
    parsed = json.loads(result.stdout)
    assert parsed["state"] == "completed"


def test_wait_completes_successfully() -> None:
    with patch("model_regression_detection.cli.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(
            200, {"state": "completed", "gate_outcome": "pass", "total_cases": 5}
        )
        result = runner.invoke(app, ["wait", "run-abc", "--timeout-seconds", "10"])

    assert result.exit_code == EXIT_PASS
    assert "completed" in result.stdout


def test_wait_fail_outcome() -> None:
    with patch("model_regression_detection.cli.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(200, {"state": "completed", "gate_outcome": "fail"})
        result = runner.invoke(app, ["wait", "run-abc", "--timeout-seconds", "10"])

    assert result.exit_code == EXIT_REGRESSION


def test_wait_404() -> None:
    with patch("model_regression_detection.cli.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(404, {"detail": "not found"})
        result = runner.invoke(app, ["wait", "run-abc", "--timeout-seconds", "10"])

    assert result.exit_code == EXIT_ERROR


def test_wait_timeout() -> None:
    with patch("model_regression_detection.cli.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(200, {"state": "created", "gate_outcome": None})
        result = runner.invoke(
            app, ["wait", "run-abc", "--timeout-seconds", "1", "--poll-interval", "0.1"]
        )

    assert result.exit_code == EXIT_TIMEOUT


def test_wait_json_output() -> None:
    with patch("model_regression_detection.cli.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(200, {"state": "completed", "gate_outcome": "pass"})
        result = runner.invoke(app, ["wait", "run-abc", "--timeout-seconds", "10", "--json"])

    assert result.exit_code == EXIT_PASS
    parsed = json.loads(result.stdout)
    assert parsed["state"] == "completed"


def test_download_success(tmp_path: Path) -> None:
    output = tmp_path / "report.json"

    with patch("model_regression_detection.cli.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(
            200,
            {
                "run_id": "run-abc",
                "gate_outcome": "pass",
                "state": "completed",
                "cases": [],
            },
        )
        result = runner.invoke(app, ["download", "run-abc", "--output-path", str(output)])

    assert result.exit_code == EXIT_PASS
    assert output.exists()
    data = json.loads(output.read_text())
    assert data["run_id"] == "run-abc"


def test_download_fail_gate(tmp_path: Path) -> None:
    output = tmp_path / "report.json"

    with patch("model_regression_detection.cli.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(
            200,
            {
                "run_id": "run-abc",
                "gate_outcome": "fail",
                "state": "completed",
                "cases": [],
            },
        )
        result = runner.invoke(app, ["download", "run-abc", "--output-path", str(output)])

    assert result.exit_code == EXIT_REGRESSION


def test_submit_with_idempotency_key(tmp_path: Path) -> None:
    spec = _write_spec(tmp_path)
    with patch("model_regression_detection.cli.httpx.post") as mock_post:
        mock_post.return_value = _mock_response(202, {"run_id": "run-xyz"})
        result = runner.invoke(
            app,
            [
                "submit",
                str(spec),
                "--project-id",
                "proj-1",
                "--idempotency-key",
                "key-123",
            ],
        )

    assert result.exit_code == EXIT_PASS
    assert "run-xyz" in result.stdout


def test_submit_http_500(tmp_path: Path) -> None:
    spec = _write_spec(tmp_path)
    with patch("model_regression_detection.cli.httpx.post") as mock_post:
        mock_post.return_value = _mock_response(500, {"detail": "server error"})
        result = runner.invoke(app, ["submit", str(spec), "--project-id", "proj-1"])

    assert result.exit_code == EXIT_ERROR


def test_wait_polls_until_completion() -> None:
    call_count = 0

    def side_effect(*args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return _mock_response(200, {"state": "created", "gate_outcome": None})
        return _mock_response(200, {"state": "completed", "gate_outcome": "pass", "total_cases": 5})

    with patch("model_regression_detection.cli.httpx.get") as mock_get:
        mock_get.side_effect = side_effect
        result = runner.invoke(
            app,
            ["wait", "run-abc", "--timeout-seconds", "10", "--poll-interval", "0.1"],
        )

    assert result.exit_code == EXIT_PASS
    assert call_count == 3


def test_download_404(tmp_path: Path) -> None:
    output = tmp_path / "report.json"

    with patch("model_regression_detection.cli.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(404, {"detail": "not found"})
        result = runner.invoke(app, ["download", "run-abc", "--output-path", str(output)])

    assert result.exit_code == EXIT_ERROR
    assert not output.exists()
