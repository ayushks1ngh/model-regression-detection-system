"""Simple in-memory per-token sliding-window rate limiter."""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Final

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

logger = logging.getLogger(__name__)

WINDOW_SECONDS: Final = 60
MAX_REQUESTS: Final = 100
_EVICTION_INTERVAL: Final = 300  # Evict stale buckets every 5 minutes


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce a per-token request rate limit using an in-memory sliding window.

    Tokens are identified by the ``token_id`` extracted from the
    ``Authorization`` header. Unauthenticated requests are not rate-limited.
    Stale token buckets are periodically evicted to prevent memory growth.
    """

    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        *,
        window_seconds: int = WINDOW_SECONDS,
        max_requests: int = MAX_REQUESTS,
    ) -> None:
        super().__init__(app)
        self._window = window_seconds
        self._max = max_requests
        self._buckets: dict[str, list[float]] = {}
        self._last_eviction: float = time.monotonic()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        self._maybe_evict()
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            from model_regression_detection.api.tokens import parse_token_id

            token_id = parse_token_id(auth.removeprefix("Bearer "))
            if token_id is not None and not self._allow(token_id):
                logger.warning(
                    "rate_limit_exceeded",
                    extra={"token_id": token_id, "path": request.url.path},
                )
                return Response(
                    status_code=HTTP_429_TOO_MANY_REQUESTS,
                    content="Rate limit exceeded. Try again later.",
                )
        return await call_next(request)

    def _allow(self, token_id: str) -> bool:
        """Return True when the request is within the rate limit."""
        now = time.monotonic()
        cutoff = now - self._window
        bucket = self._buckets.setdefault(token_id, [])
        # Prune timestamps outside the window
        self._buckets[token_id] = [t for t in bucket if t > cutoff]
        if len(self._buckets[token_id]) >= self._max:
            return False
        self._buckets[token_id].append(now)
        return True

    def _maybe_evict(self) -> None:
        """Remove token buckets that have no recent activity to prevent unbounded growth."""
        now = time.monotonic()
        if now - self._last_eviction < _EVICTION_INTERVAL:
            return
        self._last_eviction = now
        cutoff = now - self._window
        stale_keys = [k for k, v in self._buckets.items() if not v or v[-1] <= cutoff]
        for key in stale_keys:
            del self._buckets[key]
