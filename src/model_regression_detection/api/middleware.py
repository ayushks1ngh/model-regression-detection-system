"""HTTP request correlation middleware."""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Final
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from model_regression_detection.logging import bind_request_id, reset_request_id

logger = logging.getLogger(__name__)
_MAX_REQUEST_ID_LENGTH: Final = 128


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a bounded request ID and emit one structured access event."""

    def __init__(self, app: Callable[..., Awaitable[None]], *, header_name: str) -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Correlate request logs while rejecting unsafe caller-provided identifiers."""
        supplied_id = request.headers.get(self.header_name)
        request_id = (
            supplied_id
            if supplied_id is not None and 0 < len(supplied_id) <= _MAX_REQUEST_ID_LENGTH
            else str(uuid4())
        )
        token = bind_request_id(request_id)
        started = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            response.headers[self.header_name] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            logger.info(
                "http_request_completed",
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_status": response.status_code if response is not None else 500,
                    "duration_ms": duration_ms,
                },
            )
            reset_request_id(token)
