"""Bearer-token authentication and project-scoped access control."""

import logging
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from model_regression_detection.api.dependencies import get_session
from model_regression_detection.api.tokens import parse_token_id, verify_token
from model_regression_detection.persistence.repository import RunRepository

logger = logging.getLogger(__name__)

_TOKEN_PREFIX = "mrds_"  # noqa: S105


async def require_project_id(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    session: Annotated[AsyncSession, Depends(get_session)] = None,  # type: ignore[assignment]
) -> str:
    """Validate the bearer token and return the project_id it is scoped to.

    Raises ``401`` when the token is missing and ``403`` when it is invalid
    or revoked.
    """
    result = await _resolve_project(authorization, session)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )
    return result


async def optional_project_id(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    session: Annotated[AsyncSession, Depends(get_session)] = None,  # type: ignore[assignment]
) -> str | None:
    """Like ``require_project_id`` but returns ``None`` instead of raising 401.

    Use this in routes that support both authenticated and unauthenticated
    access. When a token is present but invalid, this still raises 403.
    """
    return await _resolve_project(authorization, session)


async def _resolve_project(
    authorization: str | None,
    session: AsyncSession,
) -> str | None:
    """Validate token and return its project_id, or None when no token is present."""
    if authorization is None or not authorization.startswith("Bearer "):
        return None
    secret = authorization.removeprefix("Bearer ")
    token_id = parse_token_id(secret)
    if token_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token format",
        )

    repository = RunRepository(session)
    token_row = await repository.get_token(token_id)
    if token_row is None or not verify_token(secret, token_row.token_hash):
        logger.info("auth_failed", extra={"reason": "invalid_token", "token_id": token_id})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or revoked token",
        )

    await repository.touch_token(token_row.id)
    return token_row.project_id
