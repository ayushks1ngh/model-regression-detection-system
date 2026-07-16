"""Preflight and runtime enforcement of per-run execution limits."""

from model_regression_detection.specification.models import EvaluationSpecification


class LimitExceededError(ValueError):
    """Raised when a run violates a preflight execution limit."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def preflight_check(specification: EvaluationSpecification) -> None:
    """Reject a run before any provider call when a preflight limit is exceeded."""
    limits = specification.limits
    case_count = len(specification.cases)
    if limits.max_cases is not None and case_count > limits.max_cases:
        raise LimitExceededError(
            "max_cases_exceeded",
            f"Run has {case_count} cases but the limit is {limits.max_cases}",
        )
    if limits.max_estimated_cost is not None:
        per_case = limits.estimated_cost_per_case or 0.0
        estimated = per_case * case_count
        if estimated > limits.max_estimated_cost:
            raise LimitExceededError(
                "max_estimated_cost_exceeded",
                f"Estimated cost {estimated} exceeds the limit {limits.max_estimated_cost}",
            )


def effective_output_tokens(specification: EvaluationSpecification) -> int:
    """Return the per-request output-token cap, honoring the tighter of the two limits."""
    model_tokens = specification.model.max_output_tokens
    limit_tokens = specification.limits.max_output_tokens
    if limit_tokens is None:
        return model_tokens
    return min(model_tokens, limit_tokens)
