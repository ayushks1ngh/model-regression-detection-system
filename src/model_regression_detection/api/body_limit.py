"""Middleware that enforces a configurable request body size limit."""

import logging
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_413_REQUEST_ENTITY_TOO_LARGE

logger = logging.getLogger(__name__)


class RequestBodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds the configured maximum.

    Appliles to all request methods that carry a body.  Responses are plain
    text with status 413.  Requests without a Content-Length header are
    *not* intercepted (streaming bodies cannot be efficiently pre-flighted).
    """

    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        *,
        max_bytes: int,
    ) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                pass
            else:
                if length > self._max_bytes:
                    logger.warning(
                        "request_body_too_large",
                        extra={
                            "method": request.method,
                            "path": request.url.path,
                            "content_length": length,
                            "max_bytes": self._max_bytes,
                        },
                    )
                    return Response(
                        status_code=HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        content=f"Request body exceeds {self._max_bytes} byte limit.",
                    )

        return await call_next(request)
