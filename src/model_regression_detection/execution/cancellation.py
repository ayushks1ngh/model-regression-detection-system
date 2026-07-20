"""Cancellation token for cooperative run cancellation."""

import asyncio
from dataclasses import dataclass, field


@dataclass(frozen=False)
class CancellationToken:
    """Cooperative cancellation signal checked between case executions.

    Not thread-safe; intended for single-worker async contexts.
    """

    _event: asyncio.Event = field(default_factory=asyncio.Event)

    def request_cancel(self) -> None:
        """Signal cancellation as soon as the next cancellation checkpoint."""
        self._event.set()

    @property
    def cancelled(self) -> bool:
        """True when cancellation has been requested."""
        return self._event.is_set()

    async def wait_cancel(self) -> None:
        """Block until cancellation is requested."""
        await self._event.wait()
