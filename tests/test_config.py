"""Tests for strict settings behavior."""

import pytest
from pydantic import ValidationError

from model_regression_detection.config import Environment, Settings


def test_settings_normalize_log_level() -> None:
    settings = Settings(log_level="warning", environment=Environment.TEST)

    assert settings.log_level == "WARNING"


def test_settings_reject_invalid_port() -> None:
    with pytest.raises(ValidationError):
        Settings(port=0)


def test_settings_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Settings(unknown_setting="value")  # type: ignore[call-arg]


def test_settings_reject_unknown_environment() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="qa")  # type: ignore[arg-type]


def test_settings_reject_invalid_log_level() -> None:
    with pytest.raises(ValidationError, match="Unsupported log level"):
        Settings(log_level="verbose")
