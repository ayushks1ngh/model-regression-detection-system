"""Operational health routes."""

from datetime import UTC, datetime

from fastapi import APIRouter, Request, status

from model_regression_detection import __version__
from model_regression_detection.api.schemas import LiveResponse
from model_regression_detection.config import Settings
from model_regression_detection.domain.versions import TargetKind

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
