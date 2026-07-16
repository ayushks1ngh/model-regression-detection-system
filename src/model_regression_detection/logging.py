"""Structured logging configuration and request context."""

import json
import logging
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from types import TracebackType
from typing import Any

from model_regression_detection.config import Settings

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_STANDARD_RECORD_KEYS = frozenset(logging.makeLogRecord({}).__dict__)


def bind_request_id(request_id: str) -> Token[str | None]:
    """Bind a correlation identifier to the current execution context."""
    return _request_id.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the preceding request context."""
    _request_id.reset(token)


class JsonFormatter(logging.Formatter):
    """Render log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize a record with stable core fields and safe structured extras."""
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = _request_id.get()
        if request_id is not None:
            payload["request_id"] = request_id

        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_KEYS and key not in {"message", "asctime"}:
                payload[key] = value

        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False, separators=(",", ":"))


class TextFormatter(logging.Formatter):
    """Render concise human-readable logs for local development."""

    def format(self, record: logging.LogRecord) -> str:
        """Include a request identifier when one is bound."""
        request_id = _request_id.get() or "-"
        original = record.__dict__.get("request_id")
        record.__dict__["request_id"] = request_id
        try:
            return super().format(record)
        finally:
            if original is None:
                record.__dict__.pop("request_id", None)
            else:
                record.__dict__["request_id"] = original


def configure_logging(settings: Settings) -> None:
    """Configure root logging once for the current process."""
    handler = logging.StreamHandler()
    if settings.log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            TextFormatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s")
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)


def exception_type(
    exc_type: type[BaseException] | None,
    exc_value: BaseException | None,
    traceback: TracebackType | None,
) -> str | None:
    """Return a safe exception class name for optional operational logging."""
    del exc_value, traceback
    return exc_type.__name__ if exc_type is not None else None
