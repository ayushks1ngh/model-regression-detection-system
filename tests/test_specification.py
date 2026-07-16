"""Tests for M2 evaluation specification contracts."""

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from model_regression_detection.specification import (
    SpecificationLoadError,
    load_specification,
    specification_hashes,
)


def valid_document() -> dict[str, Any]:
    """Return a complete schema-v1 document for isolated mutation."""
    return {
        "schema_version": "1",
        "suite": "support-smoke",
        "prompt": {
            "target": {
                "kind": "prompt",
                "target_id": "support-prompt",
                "version": "v1",
                "content_hash": "a" * 64,
            },
            "messages": [{"role": "user", "content": "Answer: {request}"}],
            "variables": ["request"],
        },
        "model": {
            "target": {
                "kind": "model",
                "target_id": "gpt-mini",
                "version": "2025-04-14",
                "content_hash": "b" * 64,
            },
            "provider": "openrouter",
            "model_id": "openai/gpt-4.1-mini",
            "temperature": 0.0,
            "max_output_tokens": 100,
            "timeout_seconds": 10.0,
        },
        "agent": {
            "target": {
                "kind": "agent",
                "target_id": "support-agent",
                "version": "v1",
                "content_hash": "c" * 64,
            },
            "name": "Support Agent",
        },
        "evaluators": [{"name": "answer-match", "type": "normalized_match"}],
        "cases": [
            {
                "key": "refund",
                "inputs": {"request": "Refund policy?"},
                "expected": "30 days",
                "evaluators": ["answer-match"],
                "critical": True,
            }
        ],
        "policy": {
            "minimum_pass_rate": 1.0,
            "maximum_pass_rate_drop": 0.0,
            "maximum_error_rate": 0.0,
            "critical_cases_must_pass": True,
        },
    }


def write_json(tmp_path: Path, document: object, name: str = "evaluation.json") -> Path:
    """Write a JSON fixture and return its path."""
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_loads_prompt_model_and_agent_versions(tmp_path: Path) -> None:
    specification = load_specification(write_json(tmp_path, valid_document()))

    assert specification.prompt.target.kind.value == "prompt"
    assert specification.model.target.kind.value == "model"
    assert specification.agent is not None
    assert specification.agent.target.kind.value == "agent"


def test_equivalent_json_key_order_has_identical_hashes(tmp_path: Path) -> None:
    document = valid_document()
    reversed_document = dict(reversed(list(deepcopy(document).items())))

    first = load_specification(write_json(tmp_path, document, "first.json"))
    second = load_specification(write_json(tmp_path, reversed_document, "second.json"))

    assert specification_hashes(first) == specification_hashes(second)


def test_semantic_configuration_change_changes_only_configuration_hash(tmp_path: Path) -> None:
    original_document = valid_document()
    changed_document = deepcopy(original_document)
    changed_document["model"]["temperature"] = 0.5

    original = specification_hashes(load_specification(write_json(tmp_path, original_document)))
    changed = specification_hashes(
        load_specification(write_json(tmp_path, changed_document, "changed.json"))
    )

    assert original.configuration != changed.configuration
    assert original.dataset == changed.dataset


def test_case_change_changes_only_dataset_hash(tmp_path: Path) -> None:
    original_document = valid_document()
    changed_document = deepcopy(original_document)
    changed_document["cases"][0]["expected"] = "14 days"

    original = specification_hashes(load_specification(write_json(tmp_path, original_document)))
    changed = specification_hashes(
        load_specification(write_json(tmp_path, changed_document, "changed.json"))
    )

    assert original.configuration == changed.configuration
    assert original.dataset != changed.dataset


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data.update(schema_version="2"), "Unsupported schema_version"),
        (lambda data: data.update(unknown=True), "Extra inputs are not permitted"),
        (lambda data: data["cases"].append(deepcopy(data["cases"][0])), "case keys must be unique"),
        (lambda data: data["cases"][0].update(inputs={}), "missing prompt inputs"),
        (
            lambda data: data["cases"][0].update(evaluators=["missing"]),
            "references unknown evaluators",
        ),
        (lambda data: data["prompt"]["target"].update(kind="agent"), "must be 'prompt'"),
    ],
)
def test_rejects_invalid_documents(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], object],
    message: str,
) -> None:
    document = valid_document()
    mutation(document)

    with pytest.raises(SpecificationLoadError, match=message):
        load_specification(write_json(tmp_path, document))


def test_safe_yaml_rejects_executable_tags(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.yaml"
    path.write_text("!!python/object/apply:os.system ['echo unsafe']", encoding="utf-8")

    with pytest.raises(SpecificationLoadError, match="Invalid YAML"):
        load_specification(path)


def test_rejects_unsupported_extension(tmp_path: Path) -> None:
    path = tmp_path / "evaluation.toml"
    path.write_text("schema_version = '1'", encoding="utf-8")

    with pytest.raises(SpecificationLoadError, match="Unsupported specification extension"):
        load_specification(path)


def test_example_specification_is_valid() -> None:
    path = Path(__file__).parents[1] / "examples" / "evaluation.yaml"

    specification = load_specification(path)

    assert specification.suite == "customer-support-smoke"
    assert len(specification.cases) == 2
