"""SQLAlchemy ORM models for the minimal persistence schema."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Dialect,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator, TypeEngine

_MONEY_PRECISION = 20
_MONEY_SCALE = 10


class PortableJson(TypeDecorator[Any]):
    """Use PostgreSQL JSONB when available and portable JSON elsewhere."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        """Select the dialect-specific JSON implementation."""
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class Base(DeclarativeBase):
    """Declarative base for all persistence models."""


class ProjectRow(Base):
    """A logical project that owns evaluation runs."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    runs: Mapped[list["RunRow"]] = relationship(back_populates="project")


class RunRow(Base):
    """One evaluation run: an immutable snapshot plus mutable lifecycle state."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    suite: Mapped[str] = mapped_column(String(200))
    configuration_hash: Mapped[str] = mapped_column(String(64))
    dataset_hash: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict[str, Any]] = mapped_column(PortableJson)
    state: Mapped[str] = mapped_column(String(32))
    execution_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gate_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    total_cases: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(PortableJson, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[ProjectRow] = relationship(back_populates="runs")
    cases: Mapped[list["CaseRow"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="CaseRow.ordinal",
    )


class CaseRow(Base):
    """One case result belonging to a run."""

    __tablename__ = "case_results"
    __table_args__ = (UniqueConstraint("run_id", "case_key", name="uq_case_results_run_case"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    case_key: Mapped[str] = mapped_column(String(128))
    ordinal: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(32))
    provider_status: Mapped[str] = mapped_column(String(16))
    cost: Mapped[Any | None] = mapped_column(Numeric(_MONEY_PRECISION, _MONEY_SCALE), nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(PortableJson)

    run: Mapped[RunRow] = relationship(back_populates="cases")


class IdempotencyRecordRow(Base):
    """Maps a project-scoped idempotency key to the run it created."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_idempotency_project_key"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
