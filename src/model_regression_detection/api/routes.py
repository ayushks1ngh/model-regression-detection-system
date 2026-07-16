"""Operational health routes."""

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, status

from model_regression_detection import __version__
from model_regression_detection.api.schemas import LiveResponse, ReadyResponse
from model_regression_detection.config import Settings
from model_regression_detection.domain.versions import TargetKind
from model_regression_detection.persistence import database_ready

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/live",
    response_model=LiveResponse,
    status_code=status.HTTP_200_OK,
    summary="Process liveness",
)
async def live(request: Request) -> LiveResponse:
    """Report that the API process is alive without probing external dependencies."""
    settings: Settings = request.app.state.settings
    return LiveResponse(
        status="ok",
        service=settings.app_name,
        version=__version__,
        environment=settings.environment,
        timestamp=datetime.now(tz=UTC),
        supported_target_kinds=tuple(TargetKind),
    )


@router.get("/ready", response_model=ReadyResponse, summary="Dependency readiness")
async def ready(request: Request, response: Response) -> ReadyResponse:
    """Report readiness, returning 503 when a configured dependency is unavailable."""
    engine = getattr(request.app.state, "db_engine", None)
    if engine is None:
        return ReadyResponse(status="ready", database="not_configured")
    if await database_ready(engine):
        return ReadyResponse(status="ready", database="ok")
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(status="not_ready", database="unavailable")
