"""Tests for structured logging."""

import json
import logging

from model_regression_detection.config import Settings
from model_regression_detection.logging import JsonFormatter, bind_request_id, reset_request_id


def test_json_formatter_emits_request_context_and_extra_fields() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="request complete",
        args=(),
        exc_info=None,
    )
    record.duration_ms = 1.25
    token = bind_request_id("request-123")
    try:
        payload = json.loads(formatter.format(record))
    finally:
        reset_request_id(token)

    assert payload["message"] == "request complete"
    assert payload["request_id"] == "request-123"
    assert payload["duration_ms"] == 1.25


def test_settings_are_compatible_with_json_logging() -> None:
    settings = Settings(log_format="json")

    assert settings.log_format == "json"
