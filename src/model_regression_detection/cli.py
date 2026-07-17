"""Operational command-line interface."""

import asyncio
import contextlib
import json
import os
import signal
from pathlib import Path
from typing import Annotated

import httpx
import typer

from model_regression_detection import __version__
from model_regression_detection.config import get_settings
from model_regression_detection.execution import execute_local_evaluation
from model_regression_detection.execution.limits import LimitExceededError
from model_regression_detection.persistence.engine import create_engine, create_session_factory
from model_regression_detection.providers.contracts import Provider
from model_regression_detection.providers.fake import FakeProvider
from model_regression_detection.providers.fixtures import load_fake_responses
from model_regression_detection.providers.openrouter import OpenRouterProvider
from model_regression_detection.reporting import build_json_report
from model_regression_detection.specification import (
    SpecificationLoadError,
    load_specification,
    specification_hashes,
)
from model_regression_detection.workers import Worker

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


@app.command()
def worker(
    lease_seconds: Annotated[
        int,
        typer.Option(min=5, max=3600, help="Worker lease duration in seconds."),
    ] = 60,
    poll_interval_seconds: Annotated[
        float,
        typer.Option(min=0.1, max=60.0, help="Idle poll interval in seconds."),
    ] = 1.0,
) -> None:
    """Run a durable worker that claims and executes persisted runs.

    Requires MRDS_DATABASE_URL. Requires MRDS_OPENROUTER_API_KEY unless
    MRDS_WORKER_FAKE_PROVIDER is set, which is intended for local smoke testing only.
    """
    settings = get_settings()
    if settings.database_url is None:
        typer.echo("Worker requires MRDS_DATABASE_URL to be configured", err=True)
        raise typer.Exit(code=2)

    if os.environ.get("MRDS_WORKER_FAKE_PROVIDER"):
        provider: Provider = FakeProvider({})
    else:
        api_key = os.environ.get("MRDS_OPENROUTER_API_KEY")
        if not api_key:
            typer.echo("Worker requires MRDS_OPENROUTER_API_KEY to be configured", err=True)
            raise typer.Exit(code=2)
        provider = OpenRouterProvider(api_key_provider=lambda: api_key)

    async def _run() -> None:
        engine = create_engine(settings.database_url)  # type: ignore[arg-type]
        session_factory = create_session_factory(engine)
        instance = Worker(
            session_factory,
            provider,
            lease_seconds=lease_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, AttributeError):
                loop.add_signal_handler(sig, instance.request_stop)
        typer.echo(f"worker started worker_id={instance.worker_id}")
        try:
            await instance.run_forever()
        finally:
            await engine.dispose()
        typer.echo("worker stopped")

    asyncio.run(_run())
