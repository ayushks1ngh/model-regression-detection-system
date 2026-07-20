"""PostgreSQL-backed worker that executes claimed runs and persists results."""

import asyncio
import contextlib
import logging
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from model_regression_detection.execution.cancellation import CancellationToken
from model_regression_detection.execution.report import (
    LocalEvaluationReport,
    execute_local_evaluation,
)
from model_regression_detection.persistence.repository import RunRepository
from model_regression_detection.providers.contracts import (
    InferenceRequest,
    InferenceResult,
    Provider,
)
from model_regression_detection.specification.models import EvaluationSpecificationV1

logger = logging.getLogger(__name__)

_DEFAULT_LEASE_SECONDS = 60
_DEFAULT_POLL_INTERVAL_SECONDS = 1.0
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BASE_RETRY_DELAY_SECONDS = 1.0
_DEFAULT_MAX_RETRY_DELAY_SECONDS = 30.0


class RetryProvider:
    """Wrap a Provider and retry transient failures with exponential backoff."""

    def __init__(
        self,
        inner: Provider,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        base_delay_seconds: float = _DEFAULT_BASE_RETRY_DELAY_SECONDS,
        max_delay_seconds: float = _DEFAULT_MAX_RETRY_DELAY_SECONDS,
    ) -> None:
        self._inner = inner
        self._max_retries = max_retries
        self._base_delay = base_delay_seconds
        self._max_delay = max_delay_seconds

    async def generate(self, request: InferenceRequest) -> InferenceResult:
        for attempt in range(self._max_retries + 1):
            result = await self._inner.generate(request)
            err = result.error
            if result.status != "error" or err is None or not err.retryable:
                return result
            if attempt < self._max_retries:
                delay = min(self._base_delay * (2**attempt), self._max_delay)
                logger.info(
                    "provider_retry",
                    extra={
                        "request_id": request.request_id,
                        "attempt": attempt + 1,
                        "max_retries": self._max_retries,
                        "delay_seconds": delay,
                        "error_code": err.code,
                    },
                )
                await asyncio.sleep(delay)
        return result


class Worker:
    """Poll for runnable runs, execute them, and persist terminal evidence."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider: Provider,
        worker_id: str | None = None,
        lease_seconds: int = _DEFAULT_LEASE_SECONDS,
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        base_retry_delay_seconds: float = _DEFAULT_BASE_RETRY_DELAY_SECONDS,
        max_retry_delay_seconds: float = _DEFAULT_MAX_RETRY_DELAY_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self.worker_id = worker_id or uuid4().hex
        self._lease_seconds = lease_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._stopping = asyncio.Event()
        self._max_retries = max_retries
        self._base_retry_delay = base_retry_delay_seconds
        self._max_retry_delay = max_retry_delay_seconds

    def request_stop(self) -> None:
        """Signal the run loop to stop after the current iteration."""
        self._stopping.set()

    async def run_forever(self) -> None:
        """Poll for and execute runs until stop is requested."""
        await self._reconcile_on_startup()

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

        logger.info(
            "worker_claimed_run", extra={"run_id": run_id, "worker_id": self.worker_id}
        )

        # Re-check cancellation after claim — a cancel could have raced in
        if await self._is_cancelled(run_id):
            await self._acknowledge_cancel(run_id)
            return True

        async with self._session_factory() as session:
            repository = RunRepository(session)
            run = await repository.get_run(run_id)
            if run is None:  # pragma: no cover - defensive, cannot happen after a valid claim
                return True
            specification = EvaluationSpecificationV1.model_validate(run.snapshot)

        cancellation_token = CancellationToken()
        report = await self._execute_with_heartbeat(run_id, specification, cancellation_token)

        if cancellation_token.cancelled:
            async with self._session_factory() as session:
                repository = RunRepository(session)
                acked = await repository.acknowledge_cancellation(
                    run_id, self.worker_id, report
                )
                await session.commit()
            logger.info(
                "worker_cancelled_run",
                extra={
                    "run_id": run_id,
                    "worker_id": self.worker_id,
                    "acknowledged": acked,
                },
            )
            return True

        async with self._session_factory() as session:
            repository = RunRepository(session)
            completed = await repository.complete_run(
                run_id, report, worker_id=self.worker_id
            )
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

    async def _is_cancelled(self, run_id: str) -> bool:
        """Quick check if a run has been marked for cancellation."""
        async with self._session_factory() as session:
            run = await RunRepository(session).get_run(run_id)
            if run is None:
                return True
            return run.state in ("cancelling", "cancelled")

    async def _acknowledge_cancel(self, run_id: str) -> None:
        """Acknowledge cancellation of a run that was claimed but already cancelled."""
        async with self._session_factory() as session:
            await RunRepository(session).acknowledge_cancellation(run_id, self.worker_id)
            await session.commit()

    async def _reconcile_on_startup(self) -> None:
        """Reconcile stranded runs at worker startup."""
        try:
            async with self._session_factory() as session:
                repo = RunRepository(session)
                count = await repo.reconcile_stranded_runs()
                await session.commit()
                if count > 0:
                    logger.info(
                        "worker_reconciled_stranded_runs",
                        extra={"count": count, "worker_id": self.worker_id},
                    )
        except Exception:
            logger.exception("worker_startup_reconciliation_failed")

    async def _execute_with_heartbeat(
        self,
        run_id: str,
        specification: EvaluationSpecificationV1,
        cancellation_token: CancellationToken,
    ) -> LocalEvaluationReport:
        """Execute the run while periodically extending the lease.

        When the heartbeat detects the run has transitioned to ``cancelling``
        (set by the cancel API), the cancellation token is triggered so that
        ``execute_local`` stops between cases.
        """
        stop_heartbeat = asyncio.Event()
        heartbeat_interval = max(self._lease_seconds // 3, 1)

        async def _heartbeat_loop() -> None:
            while not stop_heartbeat.is_set():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        stop_heartbeat.wait(), timeout=heartbeat_interval
                    )
                if stop_heartbeat.is_set():
                    return
                async with self._session_factory() as hb_session:
                    repo = RunRepository(hb_session)
                    ok = await repo.heartbeat(
                        run_id, self.worker_id, self._lease_seconds
                    )
                    await hb_session.commit()
                    if not ok:
                        logger.warning(
                            "heartbeat_lost_lease",
                            extra={
                                "run_id": run_id,
                                "worker_id": self.worker_id,
                            },
                        )
                        cancellation_token.request_cancel()
                        return

        heartbeat_task = asyncio.create_task(_heartbeat_loop())
        try:
            retrying = RetryProvider(
                self._provider,
                max_retries=self._max_retries,
                base_delay_seconds=self._base_retry_delay,
                max_delay_seconds=self._max_retry_delay,
            )
            return await execute_local_evaluation(
                specification, retrying, cancellation_token
            )
        finally:
            stop_heartbeat.set()
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task
