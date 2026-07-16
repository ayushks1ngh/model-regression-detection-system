"""Deterministic sequential local evaluation runner."""

import json
import logging
import string
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from model_regression_detection.providers.contracts import (
    InferenceMessage,
    InferenceRequest,
    InferenceResult,
    Provider,
)
from model_regression_detection.specification.loader import specification_hashes
from model_regression_detection.specification.models import EvaluationSpecification, GoldenCase

logger = logging.getLogger(__name__)
_formatter = string.Formatter()


class ExecutionModel(BaseModel):
    """Strict immutable base for local execution evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CaseExecutionResult(ExecutionModel):
    """Terminal provider evidence for one golden case."""

    case_key: str
    ordinal: Annotated[int, Field(ge=0)]
    request_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    provider_result: InferenceResult


class LocalRunResult(ExecutionModel):
    """Complete sequential local run result in deterministic case order."""

    status: Literal["completed"]
    suite: str
    configuration_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    dataset_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    total_cases: Annotated[int, Field(ge=1)]
    successful_cases: Annotated[int, Field(ge=0)]
    error_cases: Annotated[int, Field(ge=0)]
    cases: tuple[CaseExecutionResult, ...]


def _json_text(value: object) -> str:
    """Render scalar or structured JSON inputs predictably for templates."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _render_template(template: str, case: GoldenCase) -> str:
    """Render only simple named format fields from validated case inputs."""
    values = {key: _json_text(value) for key, value in case.inputs.items()}
    for _, field_name, format_spec, conversion in _formatter.parse(template):
        if field_name is None:
            continue
        if not field_name or any(character in field_name for character in ".[]"):
            raise ValueError(f"Unsupported prompt field expression: {field_name!r}")
        if format_spec or conversion:
            raise ValueError(f"Prompt field formatting is unsupported: {field_name!r}")
    return template.format_map(values)


def _build_request(
    specification: EvaluationSpecification,
    case: GoldenCase,
) -> InferenceRequest:
    """Build a normalized request from an immutable specification and case."""
    return InferenceRequest(
        request_id=case.key,
        model_id=specification.model.model_id,
        messages=tuple(
            InferenceMessage(role=message.role, content=_render_template(message.content, case))
            for message in specification.prompt.messages
        ),
        temperature=specification.model.temperature,
        max_output_tokens=specification.model.max_output_tokens,
        timeout_seconds=specification.model.timeout_seconds,
    )


def _request_hash(request: InferenceRequest) -> str:
    """Hash one rendered request deterministically."""
    payload = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return sha256(payload).hexdigest()


async def execute_local(
    specification: EvaluationSpecification,
    provider: Provider,
) -> LocalRunResult:
    """Execute every golden case sequentially and preserve all terminal results."""
    hashes = specification_hashes(specification)
    results: list[CaseExecutionResult] = []
    for ordinal, case in enumerate(specification.cases):
        request = _build_request(specification, case)
        logger.info(
            "local_case_started",
            extra={"suite": specification.suite, "case_key": case.key},
        )
        provider_result = await provider.generate(request)
        logger.info(
            "local_case_completed",
            extra={
                "suite": specification.suite,
                "case_key": case.key,
                "provider_status": provider_result.status,
            },
        )
        results.append(
            CaseExecutionResult(
                case_key=case.key,
                ordinal=ordinal,
                request_hash=_request_hash(request),
                provider_result=provider_result,
            )
        )

    successful_cases = sum(result.provider_result.status == "success" for result in results)
    return LocalRunResult(
        status="completed",
        suite=specification.suite,
        configuration_hash=hashes.configuration,
        dataset_hash=hashes.dataset,
        total_cases=len(results),
        successful_cases=successful_cases,
        error_cases=len(results) - successful_cases,
        cases=tuple(results),
    )
