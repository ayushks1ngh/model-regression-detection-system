"""Tests for versioned evaluation-target references."""

import pytest
from pydantic import ValidationError

from model_regression_detection.domain.versions import TargetKind, VersionedTargetRef


@pytest.mark.parametrize("kind", list(TargetKind))
def test_all_required_target_kinds_are_supported(kind: TargetKind) -> None:
    reference = VersionedTargetRef(
        kind=kind,
        target_id=f"{kind.value}-id",
        version="v1",
        content_hash="a" * 64,
    )

    assert reference.kind is kind


def test_target_reference_is_immutable() -> None:
    reference = VersionedTargetRef(
        kind=TargetKind.PROMPT,
        target_id="support-agent-system-prompt",
        version="v1",
        content_hash="b" * 64,
    )

    with pytest.raises(ValidationError):
        reference.version = "v2"  # type: ignore[misc]


def test_target_reference_requires_sha256_digest() -> None:
    with pytest.raises(ValidationError):
        VersionedTargetRef(
            kind=TargetKind.AGENT,
            target_id="support-agent",
            version="v1",
            content_hash="not-a-sha256",
        )
