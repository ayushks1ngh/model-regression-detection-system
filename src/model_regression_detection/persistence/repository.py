"""Repository for persisting and reconstructing evaluation runs."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from model_regression_detection.execution.report import LocalEvaluationReport
from model_regression_detection.persistence.models import (
    CaseRow,
    IdempotencyRecordRow,
    ProjectRow,
    RunRow,
)
from model_regression_detection.specification.models import EvaluationSpecification


class IdempotencyConflictError(ValueError):
    """Raised when a reused idempotency key carries a different request body."""


class RunRepository:
    """Persist evaluation runs across their lifecycle and read them back."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_project(self, project_id: str, slug: str, name: str) -> ProjectRow:
        """Return an existing project or create it within the current transaction."""
        existing = await self._session.get(ProjectRow, project_id)
        if existing is not None:
            return existing
        project = ProjectRow(id=project_id, slug=slug, name=name)
        self._session.add(project)
        await self._session.flush()
        return project

    async def find_idempotent_run(
        self,
        project_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> str:
        """Return the existing run ID for a reused key, or raise on a body mismatch."""
        result = await self._session.execute(
            select(IdempotencyRecordRow).where(
                IdempotencyRecordRow.project_id == project_id,
                IdempotencyRecordRow.idempotency_key == idempotency_key,
            )
        )
        record = result.scalar_one()
        if record.request_hash != request_hash:
            raise IdempotencyConflictError(
                f"Idempotency key {idempotency_key!r} was used with a different request body"
            )
        return record.run_id

    async def create_run(
        self,
        project_id: str,
        specification: EvaluationSpecification,
        configuration_hash: str,
        dataset_hash: str,
        idempotency_key: str | None,
        request_hash: str | None,
    ) -> str:
        """Create an immutable run snapshot in the created state.

        When an idempotency key is supplied and already recorded for this project,
        the existing run ID is returned instead of creating a duplicate run.
        """
        run_id = uuid4().hex
        run = RunRow(
            id=run_id,
            project_id=project_id,
            suite=specification.suite,
            configuration_hash=configuration_hash,
            dataset_hash=dataset_hash,
            snapshot=specification.model_dump(mode="json"),
            state="created",
        )
        self._session.add(run)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            raise

        if idempotency_key is None:
            return run_id

        self._session.add(
            IdempotencyRecordRow(
                id=uuid4().hex,
                project_id=project_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash or "",
                run_id=run_id,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            return await self.find_idempotent_run(project_id, idempotency_key, request_hash or "")
        return run_id

    async def complete_run(
        self,
        run_id: str,
        report: LocalEvaluationReport,
        worker_id: str | None = None,
    ) -> bool:
        """Transition a running run to a terminal state with full evidence.

        When worker_id is provided, completion is rejected (returns False) if this
        worker no longer holds the run's lease, preventing a stale worker from
        overwriting evidence selected by whoever reclaimed the run.
        """
        run = await self._session.get(RunRow, run_id)
        if run is None:
            raise LookupError(f"Run {run_id!r} does not exist")
        if worker_id is not None and run.worker_id != worker_id:
            return False
        summaries = {case.case_key: case for case in report.gate.cases}
        run.execution_status = report.run.status
        run.gate_outcome = report.gate.outcome.value
        run.total_cases = report.run.total_cases
        run.metrics = report.gate.metrics.model_dump(mode="json")
        run.state = "completed" if report.run.status == "completed" else "failed"
        run.completed_at = datetime.now(UTC)
        for case in report.run.cases:
            cost = case.provider_result.cost
            self._session.add(
                CaseRow(
                    id=uuid4().hex,
                    run_id=run_id,
                    case_key=case.case_key,
                    ordinal=case.ordinal,
                    outcome=summaries[case.case_key].outcome.value,
                    provider_status=case.provider_result.status,
                    cost=Decimal(str(cost)) if cost is not None else None,
                    evidence=case.model_dump(mode="json"),
                )
            )
        await self._session.flush()
        return True

    async def claim_next_run(self, worker_id: str, lease_seconds: int) -> str | None:
        """Atomically claim one runnable run for this worker, or return None.

        A run is runnable when it is newly created, or when a previous worker's
        lease on a running run has expired. The conditional UPDATE guarantees at
        most one concurrent worker can win the claim for a given run.
        """
        now = datetime.now(UTC)
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        for candidate_state, extra_condition in (
            ("created", RunRow.state == "created"),
            ("running", (RunRow.state == "running") & (RunRow.lease_expires_at < now)),
        ):
            result = await self._session.execute(
                select(RunRow.id).where(extra_condition).order_by(RunRow.created_at).limit(1)
            )
            run_id = result.scalar_one_or_none()
            if run_id is None:
                continue
            update_result = await self._session.execute(
                update(RunRow)
                .where(RunRow.id == run_id, RunRow.state == candidate_state)
                .values(state="running", worker_id=worker_id, lease_expires_at=lease_expires_at)
            )
            await self._session.flush()
            if update_result.rowcount == 1:
                return run_id
        return None

    async def heartbeat(self, run_id: str, worker_id: str, lease_seconds: int) -> bool:
        """Extend a run's lease; return False if this worker no longer owns it."""
        lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        result = await self._session.execute(
            update(RunRow)
            .where(RunRow.id == run_id, RunRow.worker_id == worker_id, RunRow.state == "running")
            .values(lease_expires_at=lease_expires_at)
        )
        await self._session.flush()
        return result.rowcount == 1

    async def get_run(self, run_id: str) -> RunRow | None:
        """Load a run with its ordered cases, or None when absent."""
        result = await self._session.execute(
            select(RunRow).where(RunRow.id == run_id).options(selectinload(RunRow.cases))
        )
        return result.scalar_one_or_none()

    async def list_runs(self, project_id: str) -> list[RunRow]:
        """List runs for a project, most recent first."""
        result = await self._session.execute(
            select(RunRow)
            .where(RunRow.project_id == project_id)
            .order_by(RunRow.created_at.desc(), RunRow.id.desc())
        )
        return list(result.scalars().all())
