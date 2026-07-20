"""Baseline promotion and retrieval API routes."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from model_regression_detection.api.dependencies import get_session
from model_regression_detection.persistence.repository import RunRepository

router = APIRouter(prefix="/api/v1", tags=["baselines"])


def _ensure_utc(dt: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


class PromoteRequest(BaseModel):
    """Request body to promote a run to a named baseline channel."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=1000)


class BaselineResponse(BaseModel):
    """A named baseline channel pointing to a promoted run."""

    model_config = ConfigDict(extra="forbid")

    channel: str
    run_id: str
    reason: str | None
    previous_run_id: str | None
    promoted_at: datetime


class PromoteResponse(BaseModel):
    """Response after promoting a run to a baseline channel."""

    model_config = ConfigDict(extra="forbid")

    channel: str
    run_id: str
    reason: str | None
    previous_run_id: str | None
    promoted_at: datetime
    created: bool


@router.post(
    "/projects/{project_id}/baselines/{channel}",
    response_model=PromoteResponse,
    status_code=status.HTTP_200_OK,
    summary="Promote a completed run to a named baseline",
)
async def promote_run(
    project_id: str,
    channel: str,
    body: PromoteRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    run_id: str | None = None,
) -> PromoteResponse:
    """Promote a completed passing run to the given baseline channel.

    The run_id is passed as a query parameter. Exactly one concurrent
    promotion wins per channel; duplicate attempts with the same run
    return the existing baseline without error.
    """
    if run_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="run_id query parameter is required",
        )
    repository = RunRepository(session)
    result = await repository.promote_run(project_id, channel, run_id, body.reason)
    await session.commit()
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Run {run_id!r} does not exist, is not completed, or did not pass",
        )
    created, record = result
    return PromoteResponse(
        channel=record.channel,
        run_id=record.run_id,
        reason=record.reason,
        previous_run_id=record.previous_run_id,
        promoted_at=_ensure_utc(record.promoted_at),
        created=created,
    )


@router.get(
    "/projects/{project_id}/baselines/{channel}",
    response_model=BaselineResponse,
    summary="Get a named baseline",
)
async def get_baseline(
    project_id: str,
    channel: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BaselineResponse:
    """Return the run currently promoted to the given baseline channel."""
    repository = RunRepository(session)
    record = await repository.get_baseline(project_id, channel)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Baseline {channel!r} not found for project {project_id!r}",
        )
    return BaselineResponse(
        channel=record.channel,
        run_id=record.run_id,
        reason=record.reason,
        previous_run_id=record.previous_run_id,
        promoted_at=_ensure_utc(record.promoted_at),
    )


@router.get(
    "/projects/{project_id}/baselines",
    response_model=list[BaselineResponse],
    summary="List all baselines for a project",
)
async def list_baselines(
    project_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[BaselineResponse]:
    """List all named baselines for a project."""
    repository = RunRepository(session)
    records = await repository.list_baselines(project_id)
    return [
        BaselineResponse(
            channel=r.channel,
            run_id=r.run_id,
            reason=r.reason,
            previous_run_id=r.previous_run_id,
            promoted_at=_ensure_utc(r.promoted_at),
        )
        for r in records
    ]
