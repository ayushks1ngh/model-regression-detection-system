"""Run submission and status routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from model_regression_detection.api.dependencies import get_session
from model_regression_detection.api.schemas import (
    RunCreateCommand,
    RunCreateResponse,
    RunStatusResponse,
)
from model_regression_detection.persistence import RunRepository
from model_regression_detection.persistence.repository import IdempotencyConflictError
from model_regression_detection.specification.loader import content_hash, specification_hashes

router = APIRouter(prefix="/api/v1", tags=["runs"])

_MAX_IDEMPOTENCY_KEY_LENGTH = 200


@router.post(
    "/runs",
    response_model=RunCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an immutable evaluation run",
)
async def create_run(
    command: RunCreateCommand,
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RunCreateResponse:
    """Freeze an evaluation specification into an immutable run snapshot."""
    if idempotency_key is not None and (
        len(idempotency_key) == 0 or len(idempotency_key) > _MAX_IDEMPOTENCY_KEY_LENGTH
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must be between 1 and 200 characters",
        )
    hashes = specification_hashes(command.specification)
    repository = RunRepository(session)
    await repository.ensure_project(command.project_id, command.project_id, command.project_id)
    request_hash = content_hash(command.model_dump(mode="json")) if idempotency_key else None
    try:
        run_id = await repository.create_run(
            command.project_id,
            command.specification,
            hashes.configuration,
            hashes.dataset,
            idempotency_key,
            request_hash,
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()
    return RunCreateResponse(
        run_id=run_id,
        project_id=command.project_id,
        suite=command.specification.suite,
        state="created",
        configuration_hash=hashes.configuration,
        dataset_hash=hashes.dataset,
    )


@router.get(
    "/runs/{run_id}",
    response_model=RunStatusResponse,
    summary="Retrieve run status",
)
async def get_run(
    run_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunStatusResponse:
    """Return the current status of a persisted run."""
    run = await RunRepository(session).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return RunStatusResponse(
        run_id=run.id,
        project_id=run.project_id,
        suite=run.suite,
        state=run.state,  # type: ignore[arg-type]
        gate_outcome=run.gate_outcome,  # type: ignore[arg-type]
        total_cases=run.total_cases,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )
