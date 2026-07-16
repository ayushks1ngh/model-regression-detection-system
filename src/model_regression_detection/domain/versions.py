"""Immutable references to supported evaluation target versions.

Milestone 1 defines identity only. Evaluation, storage, and comparison behavior are deferred.
"""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class TargetKind(StrEnum):
    """Kinds of versioned artifacts the product is designed to evaluate."""

    PROMPT = "prompt"
    MODEL = "model"
    AGENT = "agent"


class VersionedTargetRef(BaseModel):
    """A strict immutable reference to a prompt, model, or agent version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: TargetKind
    target_id: Annotated[str, Field(min_length=1, max_length=200)]
    version: Annotated[str, Field(min_length=1, max_length=200)]
    content_hash: Annotated[
        str,
        Field(pattern=r"^[a-f0-9]{64}$", description="Lowercase SHA-256 content digest"),
    ]
