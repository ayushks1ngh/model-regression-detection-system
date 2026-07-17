"""PostgreSQL-backed worker that executes claimed runs and persists results."""

import asyncio
import contextlib
import logging
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from model_regression_detection.execution.report import execute_local_evaluation
from model_regression_detection.persistence.repository import RunRepository
from model_regression_detection.providers.contracts import Provider
from model_regression_detection.specification.models import EvaluationSpecificationV1

logger = logging.getLogger(__name__)

_DEFAULT_LEASE_SECONDS = 60
_DEFAULT_POLL_INTERVAL_SECONDS = 1.0


class Worker:
    """Poll for runnable runs, execute them, and persist terminal evidence."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider: Provider,
        worker_id: str | None = None,
        lease_seconds: int = _DEFAULT_LEASE_SECONDS,
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self.worker_id = worker_id or uuid4().hex
        self._lease_seconds = lease_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._stopping = asyncio.Event()

    def request_stop(self) -> None:
        """Signal the run loop to stop after the current iteration."""
        self._stopping.set()

    async def run_forever(self) -> None:
        """Poll for and execute runs until stop is requested."""
        while not self._stopping.is_set():
            processed = await self.run_once()
            if not processed:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self._poll_interval_seconds
                    )

    async def run_once(self) -> bool:
        """Claim and execute at most one run. Return True if a run was processed."""
        async with self._session_factory() as session:
            run_id = await RunRepository(session).claim_next_run(
                self.worker_id, self._lease_seconds
            )
            await session.commit()
        if run_id is None:
            return False

        logger.info("worker_claimed_run", extra={"run_id": run_id, "worker_id": self.worker_id})
        async with self._session_factory() as session:
            repository = RunRepository(session)
            run = await repository.get_run(run_id)
            if run is None:  # pragma: no cover - defensive, cannot happen after a valid claim
                return True
            specification = EvaluationSpecificationV1.model_validate(run.snapshot)

        report = await execute_local_evaluation(specification, self._provider)

        async with self._session_factory() as session:
            repository = RunRepository(session)
            completed = await repository.complete_run(run_id, report, worker_id=self.worker_id)
            await session.commit()
        logger.info(
            "worker_finished_run",
            extra={
                "run_id": run_id,
                "worker_id": self.worker_id,
                "gate_outcome": report.gate.outcome.value,
                "lease_retained": completed,
            },
        )
        return True
