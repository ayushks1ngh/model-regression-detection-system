"""Safe loading and canonical hashing of evaluation specifications."""

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Final, cast

import yaml
from pydantic import JsonValue, ValidationError
from yaml import YAMLError

from model_regression_detection.specification.models import EvaluationSpecification, validate_python

_MAX_SPEC_BYTES: Final = 10 * 1024 * 1024
_SUPPORTED_SUFFIXES: Final = frozenset({".json", ".yaml", ".yml"})


class SpecificationLoadError(ValueError):
    """Raised when a specification cannot be safely decoded or validated."""


@dataclass(frozen=True, slots=True)
class SpecificationHashes:
    """Canonical SHA-256 digests for configuration and golden cases."""

    configuration: str
    dataset: str


def canonical_json(value: JsonValue) -> bytes:
    """Serialize JSON-compatible data deterministically as UTF-8 bytes."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_hash(value: JsonValue) -> str:
    """Return a lowercase SHA-256 digest of canonical JSON data."""
    return sha256(canonical_json(value)).hexdigest()


def specification_hashes(specification: EvaluationSpecification) -> SpecificationHashes:
    """Hash the full configuration and dataset case manifest independently."""
    document = cast(JsonValue, specification.model_dump(mode="json", exclude_none=True))
    if not isinstance(document, dict):  # pragma: no cover - Pydantic models always dump mappings
        raise TypeError("specification serialization must be an object")
    case_manifest = document.pop("cases")
    return SpecificationHashes(
        configuration=content_hash(document),
        dataset=content_hash(case_manifest),
    )


def _decode_document(raw: bytes, suffix: str) -> object:
    """Decode a bounded JSON or safe YAML document."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SpecificationLoadError("Specification must be UTF-8") from exc

    try:
        if suffix == ".json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (json.JSONDecodeError, YAMLError) as exc:
        raise SpecificationLoadError(
            f"Invalid {suffix.removeprefix('.').upper()} document: {exc}"
        ) from exc


def load_specification(path: Path) -> EvaluationSpecification:
    """Load and validate a bounded specification file without executing YAML tags."""
    suffix = path.suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        raise SpecificationLoadError(f"Unsupported specification extension: {suffix or '<none>'}")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise SpecificationLoadError(f"Unable to read specification: {exc}") from exc
    if size > _MAX_SPEC_BYTES:
        raise SpecificationLoadError(f"Specification exceeds {_MAX_SPEC_BYTES} bytes")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SpecificationLoadError(f"Unable to read specification: {exc}") from exc

    try:
        return validate_python(_decode_document(raw, suffix))
    except (ValidationError, ValueError) as exc:
        raise SpecificationLoadError(str(exc)) from exc
