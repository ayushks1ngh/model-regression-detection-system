"""Operational command-line interface."""

import asyncio
import json
from pathlib import Path
from typing import Annotated

import httpx
import typer

from model_regression_detection import __version__
from model_regression_detection.execution import execute_local_evaluation
from model_regression_detection.execution.limits import LimitExceededError
from model_regression_detection.providers.fake import FakeProvider
from model_regression_detection.providers.fixtures import load_fake_responses
from model_regression_detection.reporting import build_json_report
from model_regression_detection.specification import (
    SpecificationLoadError,
    load_specification,
    specification_hashes,
)

app = typer.Typer(
    name="mrds",
    help="Operate the Model Regression Detection System.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


@app.command("validate")
def validate_specification(
    path: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, resolve_path=True),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit a machine-readable validation summary."),
    ] = False,
) -> None:
    """Validate and hash an evaluation specification without executing it."""
    try:
        specification = load_specification(path)
    except SpecificationLoadError as exc:
        typer.echo(f"Specification validation failed: {exc}", err=True)
        raise typer.Exit(code=2) from None

    hashes = specification_hashes(specification)
    targets = {
        "prompt": specification.prompt.target.model_dump(mode="json"),
        "model": specification.model.target.model_dump(mode="json"),
    }
    if specification.agent is not None:
        targets["agent"] = specification.agent.target.model_dump(mode="json")
    summary = {
        "status": "valid",
        "schema_version": specification.schema_version,
        "suite": specification.suite,
        "case_count": len(specification.cases),
        "evaluator_count": len(specification.evaluators),
        "configuration_hash": hashes.configuration,
        "dataset_hash": hashes.dataset,
        "targets": targets,
    }
    if json_output:
        typer.echo(json.dumps(summary, sort_keys=True, separators=(",", ":")))
        return
    typer.echo(
        f"valid suite={specification.suite} schema={specification.schema_version} "
        f"cases={len(specification.cases)} evaluators={len(specification.evaluators)}"
    )
    typer.echo(f"configuration_hash={hashes.configuration}")
    typer.echo(f"dataset_hash={hashes.dataset}")


@app.command("run-local")
def run_local(
    specification_path: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, resolve_path=True),
    ],
    responses_path: Annotated[
        Path,
        typer.Option(
            "--responses",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Strict JSON fake-provider response fixture.",
        ),
    ],
    output_path: Annotated[
        Path | None,
        typer.Option("--output", dir_okay=False, help="Optional raw run/gate JSON output path."),
    ] = None,
    report_path: Annotated[
        Path | None,
        typer.Option("--report", dir_okay=False, help="Optional versioned JSON report path."),
    ] = None,
) -> None:
    """Run every case sequentially against deterministic fake responses."""
    try:
        specification = load_specification(specification_path)
        responses = load_fake_responses(responses_path)
    except (SpecificationLoadError, OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"Local run input failed: {exc}", err=True)
        raise typer.Exit(code=2) from None

    try:
        report = asyncio.run(execute_local_evaluation(specification, FakeProvider(responses)))
    except LimitExceededError as exc:
        typer.echo(f"Execution limit exceeded [{exc.code}]: {exc}", err=True)
        raise typer.Exit(code=2) from None
    serialized = report.model_dump_json(indent=2)
    if output_path is not None:
        output_path.write_text(f"{serialized}\n", encoding="utf-8")
    if report_path is not None:
        json_report = build_json_report(specification, report)
        report_path.write_text(f"{json_report.model_dump_json(indent=2)}\n", encoding="utf-8")
    typer.echo(
        f"completed suite={report.run.suite} total={report.run.total_cases} "
        f"success={report.run.successful_cases} errors={report.run.error_cases} "
        f"gate={report.gate.outcome.value}"
    )
    if output_path is None and report_path is None:
        typer.echo(serialized)


@app.command()
def version() -> None:
    """Print the installed application version."""
    typer.echo(__version__)


@app.command()
def health(
    url: Annotated[
        str,
        typer.Option(help="Base URL of the API service."),
    ] = "http://127.0.0.1:8000",
    timeout_seconds: Annotated[
        float,
        typer.Option(min=0.1, max=60.0, help="Request timeout in seconds."),
    ] = 5.0,
) -> None:
    """Check service liveness and return a nonzero exit status on failure."""
    endpoint = f"{url.rstrip('/')}/health/live"
    try:
        response = httpx.get(endpoint, timeout=timeout_seconds, follow_redirects=False)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        typer.echo(f"Health check failed: {type(exc).__name__}", err=True)
        raise typer.Exit(code=1) from None

    if payload.get("status") != "ok":
        typer.echo("Health check failed: unexpected service status", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"ok service={payload.get('service', 'unknown')} version={payload.get('version')}")
