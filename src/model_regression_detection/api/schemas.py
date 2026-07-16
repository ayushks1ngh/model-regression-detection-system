"""HTTP response schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from model_regression_detection.config import Environment
from model_regression_detection.domain.versions import TargetKind


class LiveResponse(BaseModel):
    """Liveness response containing no dependency or secret information."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    service: str
    version: str
    environment: Environment
    timestamp: datetime
    supported_target_kinds: tuple[TargetKind, ...]


class ReadyResponse(BaseModel):
    """Readiness response reflecting required dependency availability."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "not_ready"]
    database: Literal["ok", "unavailable", "not_configured"]
