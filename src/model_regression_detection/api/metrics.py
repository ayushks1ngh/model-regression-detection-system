"""Prometheus operational metrics endpoint for MRDS."""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route

try:
    from prometheus_client import REGISTRY, Counter, Histogram, generate_latest

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Metrics definitions (no-op sentinels when prometheus_client is absent)
# ---------------------------------------------------------------------------

_http_requests_total: Any = None
_http_request_duration_seconds: Any = None
_wsgi_requests_total: Any = None

if _PROMETHEUS_AVAILABLE:
    _http_requests_total = Counter(
        "mrds_http_requests_total",
        "Total HTTP requests by method, path, and status",
        ["method", "path", "status"],
    )
    _http_request_duration_seconds = Histogram(
        "mrds_http_request_duration_seconds",
        "HTTP request latency in seconds by method and path",
        ["method", "path"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )
    _wsgi_requests_total = Counter(
        "mrds_wsgi_requests_total",
        "Total WSGI requests by method and status",
        ["method", "status"],
    )


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record HTTP request count and duration for Prometheus."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not _PROMETHEUS_AVAILABLE:
            return await call_next(request)

        import time

        start = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - start

        path = request.url.path if request.url.path else "/"
        status = str(response.status_code)
        _http_requests_total.labels(method=request.method, path=path, status=status).inc()
        _http_request_duration_seconds.labels(method=request.method, path=path).observe(duration)
        _wsgi_requests_total.labels(method=request.method, status=status).inc()

        return response


async def metrics_endpoint(request: Request) -> Response:
    """Return Prometheus-formatted metrics at ``/metrics``."""
    del request
    if not _PROMETHEUS_AVAILABLE:
        return PlainTextResponse(
            "# prometheus_client is not installed\n",
            status_code=501,
            media_type="text/plain; version=0.0.4",
        )
    return Response(
        content=generate_latest(REGISTRY).decode("utf-8"),
        media_type="text/plain; version=0.0.4",
    )


metrics_route = Route("/metrics", endpoint=metrics_endpoint, methods=["GET"])
