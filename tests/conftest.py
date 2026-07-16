"""Shared pytest configuration."""

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run async contract tests on the asyncio backend used by the service."""
    return "asyncio"
