"""Run submission and status routes."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from model_regression_detection.api.auth import optional_project_id
from model_regression_detection.api.dependencies import get_session
from model_regression_detection.api.schemas import (
    CancelRunResponse,
    CaseEvidenceResponse,
    RunCreateCommand,
    RunCreateResponse,
    RunReportResponse,
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
    auth_project_id: Annotated[str | None, Depends(optional_project_id)] = None,
) -> RunCreateResponse:
    """Freeze an evaluation specification into an immutable run snapshot."""
    if idempotency_key is not None and (
        len(idempotency_key) == 0 or len(idempotency_key) > _MAX_IDEMPOTENCY_KEY_LENGTH
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must be between 1 and 200 characters",
        )
    effective_project_id = auth_project_id or command.project_id
    if auth_project_id is not None and auth_project_id != command.project_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token is scoped to a different project",
        )
    hashes = specification_hashes(command.specification)
    repository = RunRepository(session)
    await repository.ensure_project(
        effective_project_id, effective_project_id, effective_project_id
    )
    request_hash = content_hash(command.model_dump(mode="json")) if idempotency_key else None
    try:
        run_id = await repository.create_run(
            effective_project_id,
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
        project_id=effective_project_id,
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
    auth_project_id: Annotated[str | None, Depends(optional_project_id)] = None,
) -> RunStatusResponse:
    """Return the current status of a persisted run."""
    run = await RunRepository(session).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if auth_project_id is not None and run.project_id != auth_project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )
    run_state: Literal["created", "running", "completed", "failed", "cancelling", "cancelled"] = (
        run.state  # type: ignore[assignment]
    )
    run_gate_outcome: Literal["pass", "fail", "error"] | None = run.gate_outcome  # type: ignore[assignment]
    return RunStatusResponse(
        run_id=run.id,
        project_id=run.project_id,
        suite=run.suite,
        state=run_state,
        gate_outcome=run_gate_outcome,
        total_cases=run.total_cases,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


@router.get(
    "/runs/{run_id}/report",
    response_model=RunReportResponse,
    summary="Retrieve full run report with case evidence",
)
async def get_run_report(
    run_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    auth_project_id: Annotated[str | None, Depends(optional_project_id)] = None,
) -> RunReportResponse:
    """Return the full report for a completed run, including case evidence."""
    run = await RunRepository(session).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if auth_project_id is not None and run.project_id != auth_project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )
    run_state: Literal["created", "running", "completed", "failed", "cancelling", "cancelled"] = (
        run.state  # type: ignore[assignment]
    )
    run_gate_outcome: Literal["pass", "fail", "error"] | None = run.gate_outcome  # type: ignore[assignment]
    cases = tuple(
        CaseEvidenceResponse(
            case_key=case_row.case_key,
            ordinal=case_row.ordinal,
            outcome=case_row.outcome,
            provider_status=case_row.provider_status,
            cost=float(case_row.cost) if case_row.cost is not None else None,
            evidence=case_row.evidence,
        )
        for case_row in run.cases
    )
    return RunReportResponse(
        run_id=run.id,
        project_id=run.project_id,
        suite=run.suite,
        state=run_state,
        gate_outcome=run_gate_outcome,
        total_cases=run.total_cases,
        metrics=run.metrics,
        cases=cases,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


@router.post(
    "/runs/{run_id}/cancel",
    response_model=CancelRunResponse,
    summary="Request idempotent cancellation of a run",
)
async def cancel_run(
    run_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    auth_project_id: Annotated[str | None, Depends(optional_project_id)] = None,
) -> CancelRunResponse:
    """Request cancellation of a non-terminal run.

    - ``created`` runs are immediately moved to ``cancelled``.
    - ``running`` runs are moved to ``cancelling`` so the worker
      detects the signal.
    - Already cancelled runs return their current state idempotently.
    - Terminal runs (completed/failed) return a 409 Conflict.
    """
    repository = RunRepository(session)
    run = await repository.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if auth_project_id is not None and run.project_id != auth_project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )
    already_cancelled = run.state in ("cancelling", "cancelled")
    if already_cancelled:
        run_state: Literal["cancelling", "cancelled"] = run.state  # type: ignore[assignment]
        return CancelRunResponse(run_id=run.id, state=run_state, already_cancelled=True)

    try:
        # False means terminal — handled below
        changed = await repository.cancel_run(run_id)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from None
    await session.commit()
    if not changed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run is already in a terminal state (completed/failed)",
        )
    run = await repository.get_run(run_id)
    assert run is not None
    run_state = run.state  # type: ignore[assignment]
    return CancelRunResponse(run_id=run.id, state=run_state, already_cancelled=False)
