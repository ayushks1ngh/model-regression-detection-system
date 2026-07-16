"""Repository for persisting and reconstructing evaluation runs."""

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from model_regression_detection.execution.report import LocalEvaluationReport
from model_regression_detection.persistence.models import CaseRow, ProjectRow, RunRow


class RunRepository:
    """Persist completed evaluation reports and read them back."""

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

    async def save_report(self, project_id: str, report: LocalEvaluationReport) -> str:
        """Persist a completed report and its cases atomically, returning the run ID."""
        run_id = uuid4().hex
        summaries = {case.case_key: case for case in report.gate.cases}
        run = RunRow(
            id=run_id,
            project_id=project_id,
            suite=report.run.suite,
            configuration_hash=report.run.configuration_hash,
            dataset_hash=report.run.dataset_hash,
            execution_status=report.run.status,
            gate_outcome=report.gate.outcome.value,
            total_cases=report.run.total_cases,
            metrics=report.gate.metrics.model_dump(mode="json"),
        )
        self._session.add(run)
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
        return run_id

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
