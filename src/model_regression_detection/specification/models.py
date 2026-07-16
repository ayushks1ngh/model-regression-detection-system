"""Strict evaluation specification models for schema version 1."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from model_regression_detection.domain.versions import VersionedTargetRef

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]


class StrictModel(BaseModel):
    """Base model that rejects unknown fields and permits immutable snapshots."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class MessageRole(StrEnum):
    """Supported provider-neutral chat message roles."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class PromptMessage(StrictModel):
    """A versioned prompt message template."""

    role: MessageRole
    content: Annotated[str, Field(min_length=1, max_length=100_000)]


class PromptDefinition(StrictModel):
    """Prompt version and its provider-neutral message templates."""

    target: VersionedTargetRef
    messages: Annotated[tuple[PromptMessage, ...], Field(min_length=1, max_length=100)]
    variables: Annotated[tuple[Identifier, ...], Field(max_length=100)] = ()

    @model_validator(mode="after")
    def validate_prompt(self) -> "PromptDefinition":
        """Require prompt provenance and unique declared variables."""
        if self.target.kind.value != "prompt":
            raise ValueError("prompt.target.kind must be 'prompt'")
        if len(self.variables) != len(set(self.variables)):
            raise ValueError("prompt variables must be unique")
        return self


class ModelDefinition(StrictModel):
    """Model version and bounded generation parameters."""

    target: VersionedTargetRef
    provider: Literal["openrouter"]
    model_id: Annotated[str, Field(min_length=1, max_length=300)]
    temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.0
    max_output_tokens: Annotated[int, Field(ge=1, le=1_000_000)] = 1024
    timeout_seconds: Annotated[float, Field(gt=0.0, le=600.0)] = 60.0

    @model_validator(mode="after")
    def validate_kind(self) -> "ModelDefinition":
        """Require model provenance to use the model target kind."""
        if self.target.kind.value != "model":
            raise ValueError("model.target.kind must be 'model'")
        return self


class AgentDefinition(StrictModel):
    """Agent version metadata; execution semantics are deferred beyond M2."""

    target: VersionedTargetRef
    name: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str | None, Field(max_length=2_000)] = None

    @model_validator(mode="after")
    def validate_kind(self) -> "AgentDefinition":
        """Require agent provenance to use the agent target kind."""
        if self.target.kind.value != "agent":
            raise ValueError("agent.target.kind must be 'agent'")
        return self


class EvaluatorType(StrEnum):
    """Evaluator declarations supported by the M2 schema."""

    EXACT_MATCH = "exact_match"
    NORMALIZED_MATCH = "normalized_match"
    CONTAINS = "contains"
    REGEX = "regex"
    JSON_VALID = "json_valid"
    JSON_SCHEMA = "json_schema"


class EvaluatorDefinition(StrictModel):
    """A built-in evaluator declaration; execution is introduced later."""

    name: Identifier
    type: EvaluatorType
    required: bool = True


class GoldenCase(StrictModel):
    """One stable golden-dataset case."""

    key: Identifier
    inputs: dict[str, JsonValue]
    expected: JsonValue | None = None
    evaluators: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=50)]
    critical: bool = False
    tags: Annotated[tuple[Identifier, ...], Field(max_length=50)] = ()

    @model_validator(mode="after")
    def validate_collections(self) -> "GoldenCase":
        """Reject duplicate evaluator and tag declarations."""
        if len(self.evaluators) != len(set(self.evaluators)):
            raise ValueError("case evaluators must be unique")
        if len(self.tags) != len(set(self.tags)):
            raise ValueError("case tags must be unique")
        return self


class RegressionPolicy(StrictModel):
    """Fixed initial regression policy declaration."""

    minimum_pass_rate: Annotated[float, Field(ge=0.0, le=1.0)] = 1.0
    maximum_pass_rate_drop: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    maximum_error_rate: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    critical_cases_must_pass: bool = True
    maximum_latency_increase_percent: Annotated[float | None, Field(ge=0.0)] = None
    maximum_cost_increase_percent: Annotated[float | None, Field(ge=0.0)] = None


class ExecutionLimits(StrictModel):
    """Optional bounded per-run execution limits."""

    max_cases: Annotated[int | None, Field(ge=1, le=100_000)] = None
    max_output_tokens: Annotated[int | None, Field(ge=1, le=1_000_000)] = None
    max_concurrency: Annotated[int, Field(ge=1, le=64)] = 1
    max_estimated_cost: Annotated[float | None, Field(ge=0.0)] = None
    max_total_cost: Annotated[float | None, Field(ge=0.0)] = None
    estimated_cost_per_case: Annotated[float | None, Field(ge=0.0)] = None


class EvaluationSpecificationV1(StrictModel):
    """Complete immutable evaluation specification for schema version 1."""

    schema_version: Literal["1"]
    suite: Identifier
    prompt: PromptDefinition
    model: ModelDefinition
    agent: AgentDefinition | None = None
    evaluators: Annotated[tuple[EvaluatorDefinition, ...], Field(min_length=1, max_length=50)]
    cases: Annotated[tuple[GoldenCase, ...], Field(min_length=1, max_length=100_000)]
    policy: RegressionPolicy
    limits: ExecutionLimits = Field(default_factory=lambda: ExecutionLimits())
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> "EvaluationSpecificationV1":
        """Validate unique identities and all case references."""
        case_keys = [case.key for case in self.cases]
        if len(case_keys) != len(set(case_keys)):
            raise ValueError("case keys must be unique")

        evaluator_names = [evaluator.name for evaluator in self.evaluators]
        if len(evaluator_names) != len(set(evaluator_names)):
            raise ValueError("evaluator names must be unique")
        known_evaluators = set(evaluator_names)

        declared_variables = set(self.prompt.variables)
        for case in self.cases:
            unknown = set(case.evaluators) - known_evaluators
            if unknown:
                raise ValueError(
                    f"case {case.key!r} references unknown evaluators: {sorted(unknown)}"
                )
            missing = declared_variables - set(case.inputs)
            unexpected = set(case.inputs) - declared_variables
            if missing:
                raise ValueError(f"case {case.key!r} is missing prompt inputs: {sorted(missing)}")
            if unexpected:
                raise ValueError(
                    f"case {case.key!r} has unexpected prompt inputs: {sorted(unexpected)}"
                )
        return self


EvaluationSpecification = EvaluationSpecificationV1


def validate_python(data: object) -> EvaluationSpecification:
    """Validate untrusted decoded data against the supported schema version."""
    if not isinstance(data, dict):
        raise ValueError("evaluation specification root must be an object")
    schema_version = data.get("schema_version")
    if schema_version != "1":
        raise ValueError(f"Unsupported schema_version: {schema_version!r}")
    return EvaluationSpecificationV1.model_validate(data)
