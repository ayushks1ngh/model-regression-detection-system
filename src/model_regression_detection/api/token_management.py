"""Token management API — create, list, and revoke project tokens."""

import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from model_regression_detection.api.auth import require_project_id
from model_regression_detection.api.dependencies import get_session
from model_regression_detection.api.tokens import generate_token
from model_regression_detection.persistence.models import ProjectTokenRow
from model_regression_detection.persistence.repository import RunRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["tokens"])


class CreateTokenRequest(BaseModel):
    """Request body to create a new project token."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=200)]


class TokenResponse(BaseModel):
    """A project token (does NOT include the plaintext secret except on creation)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    project_id: str
    name: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class CreateTokenResponse(TokenResponse):
    """Response returned when creating a token — includes the one-time secret."""

    model_config = ConfigDict(extra="forbid")

    token: str


class TokenListResponse(BaseModel):
    """List of active (non-revoked) tokens for a project."""

    model_config = ConfigDict(extra="forbid")

    tokens: list[TokenResponse]


def _normalize_dt(dt: datetime | None) -> datetime | None:
    """Ensure a datetime is timezone-aware UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _token_response(row: ProjectTokenRow) -> TokenResponse:
    return TokenResponse(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        created_at=_normalize_dt(row.created_at) or datetime.now(UTC),
        last_used_at=_normalize_dt(row.last_used_at),
        revoked_at=_normalize_dt(row.revoked_at),
    )


@router.post(
    "/projects/{project_id}/tokens",
    response_model=CreateTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project token",
)
async def create_token(
    project_id: str,
    body: CreateTokenRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _auth_project_id: Annotated[str, Depends(require_project_id)],
) -> CreateTokenResponse:
    """Create a new bearer token scoped to this project.

    The plaintext ``token`` is returned **exactly once**. Store it securely.
    """
    if _auth_project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token is not scoped to this project",
        )
    token_id = uuid4().hex
    secret, token_hash = generate_token(token_id)
    repository = RunRepository(session)
    stored_id = await repository.create_token(project_id, body.name, token_hash, token_id)
    assert stored_id == token_id
    await session.commit()

    logger.info(
        "token_created",
        extra={"project_id": project_id, "token_id": token_id, "token_name": body.name},
    )
    now = datetime.now(UTC)
    return CreateTokenResponse(
        id=token_id,
        project_id=project_id,
        name=body.name,
        token=secret,
        created_at=now,
        last_used_at=None,
        revoked_at=None,
    )


@router.get(
    "/projects/{project_id}/tokens",
    response_model=TokenListResponse,
    summary="List active tokens for a project",
)
async def list_tokens(
    project_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    _auth_project_id: Annotated[str, Depends(require_project_id)],
) -> TokenListResponse:
    """List all non-revoked tokens for the project."""
    if _auth_project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token is not scoped to this project",
        )
    repository = RunRepository(session)
    rows = await repository.list_tokens(project_id)
    return TokenListResponse(tokens=[_token_response(r) for r in rows])


@router.post(
    "/projects/{project_id}/tokens/{token_id}/revoke",
    response_model=TokenResponse,
    summary="Revoke a project token",
)
async def revoke_token(
    project_id: str,
    token_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    _auth_project_id: Annotated[str, Depends(require_project_id)],
) -> TokenResponse:
    """Revoke a token so it can no longer authenticate."""
    if _auth_project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token is not scoped to this project",
        )
    repository = RunRepository(session)
    token_row = await repository.get_token(token_id)
    if token_row is None or token_row.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    revoked = await repository.revoke_token(token_id)
    await session.commit()
    if not revoked:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Token already revoked")
    logger.info(
        "token_revoked",
        extra={"project_id": project_id, "token_id": token_id},
    )
    return _token_response(token_row)
