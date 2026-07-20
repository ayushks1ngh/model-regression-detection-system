"""Tests for structured logging."""

import json
import logging
import sys

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


def test_exception_type_returns_none_for_no_exception() -> None:
    from model_regression_detection.logging import exception_type

    assert exception_type(None, None, None) is None


def test_exception_type_returns_qualified_name() -> None:
    from model_regression_detection.logging import exception_type

    try:
        raise ValueError("test")
    except ValueError as exc:
        assert exception_type(type(exc), exc, exc.__traceback__) == "ValueError"


def test_json_formatter_includes_exception_info() -> None:
    from model_regression_detection.logging import JsonFormatter

    formatter = JsonFormatter()
    try:
        raise RuntimeError("something broke")
    except RuntimeError:
        exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=10,
            msg="failed",
            args=(),
            exc_info=exc_info,
        )
    payload = json.loads(formatter.format(record))

    assert "exception" in payload
