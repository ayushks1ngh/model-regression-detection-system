"""Fake-provider response fixture loading for local CLI runs."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from model_regression_detection.providers.contracts import ProviderError
from model_regression_detection.providers.fake import FakeResponse


class FakeResponseDocument(BaseModel):
    """Strict serializable fake response fixture."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    output: str | None = None
    error: ProviderError | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def validate_outcome(self) -> "FakeResponseDocument":
        """Require one fake outcome per case."""
        if (self.output is None) == (self.error is None):
            raise ValueError("exactly one of output or error is required")
        return self


class FakeFixtureDocument(BaseModel):
    """Map case keys to deterministic fake provider responses."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    responses: dict[str, FakeResponseDocument]


def load_fake_responses(path: Path) -> dict[str, FakeResponse]:
    """Load a strict JSON fake-provider fixture."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    document = FakeFixtureDocument.model_validate(raw)
    return {
        case_key: FakeResponse(
            output=response.output,
            error=response.error,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
        )
        for case_key, response in document.responses.items()
    }
