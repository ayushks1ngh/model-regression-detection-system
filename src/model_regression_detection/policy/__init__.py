"""Deterministic local aggregation and fixed policy evaluation."""

from model_regression_detection.policy.models import (
    BaselineComparison,
    CaseOutcome,
    CaseSummary,
    GateDecision,
    GateOutcome,
    RuleDecision,
    RuleStatus,
    RunMetrics,
)

__all__ = [
    "BaselineComparison",
    "CaseOutcome",
    "CaseSummary",
    "GateDecision",
    "GateOutcome",
    "RuleDecision",
    "RuleStatus",
    "RunMetrics",
    "aggregate_and_decide",
    "compare_and_decide",
]


def __getattr__(name: str) -> object:
    """Lazy-import engine functions to break circular imports."""
    if name in {"aggregate_and_decide", "compare_and_decide"}:
        import model_regression_detection.policy.engine as _engine

        return getattr(_engine, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
