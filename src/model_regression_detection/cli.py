"""Operational command-line interface."""

import asyncio
import contextlib
import json
import os
import signal
import time
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

EXIT_PASS = 0
EXIT_REGRESSION = 1
EXIT_ERROR = 2
EXIT_TIMEOUT = 3


def _gate_exit_code(gate_outcome: str | None) -> int:
    """Map gate outcome to CI exit code."""
    if gate_outcome == "pass":
        return EXIT_PASS
    if gate_outcome == "fail":
        return EXIT_REGRESSION
    return EXIT_ERROR


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
        raise typer.Exit(code=EXIT_ERROR) from None

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
        raise typer.Exit(code=EXIT_ERROR) from None

    try:
        report = asyncio.run(execute_local_evaluation(specification, FakeProvider(responses)))
    except LimitExceededError as exc:
        typer.echo(f"Execution limit exceeded [{exc.code}]: {exc}", err=True)
        raise typer.Exit(code=EXIT_ERROR) from None
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
def submit(
    specification_path: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, resolve_path=True),
    ],
    project_id: Annotated[
        str,
        typer.Option(help="Project ID to associate the run with."),
    ],
    url: Annotated[
        str,
        typer.Option(help="Base URL of the API service."),
    ] = "http://127.0.0.1:8000",
    idempotency_key: Annotated[
        str | None,
        typer.Option("--idempotency-key", help="Optional idempotency key."),
    ] = None,
    timeout_seconds: Annotated[
        float,
        typer.Option(min=0.1, max=120.0, help="Request timeout in seconds."),
    ] = 30.0,
) -> None:
    """Submit an evaluation specification to the API and print the run ID."""
    try:
        specification = load_specification(specification_path)
    except SpecificationLoadError as exc:
        typer.echo(f"Failed to load specification: {exc}", err=True)
        raise typer.Exit(code=EXIT_ERROR) from None

    spec_data = json.loads(specification.model_dump_json())
    body = {"project_id": project_id, "specification": spec_data}
    headers = {"Content-Type": "application/json"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    endpoint = f"{url.rstrip('/')}/api/v1/runs"
    try:
        response = httpx.post(
            endpoint, json=body, headers=headers, timeout=timeout_seconds
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500] if exc.response.text else str(exc)
        typer.echo(f"Submit failed (HTTP {exc.response.status_code}): {detail}", err=True)
        raise typer.Exit(code=EXIT_ERROR) from None
    except httpx.TimeoutException:
        typer.echo("Submit request timed out", err=True)
        raise typer.Exit(code=EXIT_TIMEOUT) from None
    except httpx.HTTPError as exc:
        typer.echo(f"Submit request failed: {exc}", err=True)
        raise typer.Exit(code=EXIT_ERROR) from None

    run_id = payload.get("run_id", "")
    typer.echo(run_id)


@app.command()
def status(
    run_id: Annotated[
        str,
        typer.Argument(help="Run ID to query."),
    ],
    url: Annotated[
        str,
        typer.Option(help="Base URL of the API service."),
    ] = "http://127.0.0.1:8000",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON output."),
    ] = False,
    timeout_seconds: Annotated[
        float,
        typer.Option(min=0.1, max=60.0, help="Request timeout in seconds."),
    ] = 10.0,
) -> None:
    """Query the current status of a persisted run."""
    endpoint = f"{url.rstrip('/')}/api/v1/runs/{run_id}"
    try:
        response = httpx.get(endpoint, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            typer.echo(f"Run {run_id} not found", err=True)
            raise typer.Exit(code=EXIT_ERROR) from None
        detail = exc.response.text[:500] if exc.response.text else str(exc)
        typer.echo(f"Status check failed (HTTP {exc.response.status_code}): {detail}", err=True)
        raise typer.Exit(code=EXIT_ERROR) from None
    except httpx.TimeoutException:
        typer.echo("Status request timed out", err=True)
        raise typer.Exit(code=EXIT_TIMEOUT) from None
    except httpx.HTTPError as exc:
        typer.echo(f"Status request failed: {exc}", err=True)
        raise typer.Exit(code=EXIT_ERROR) from None

    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True))
        raise typer.Exit(code=_gate_exit_code(payload.get("gate_outcome")))

    state = payload.get("state", "unknown")
    gate = payload.get("gate_outcome") or "none"
    total = payload.get("total_cases") or "?"
    typer.echo(
        f"run_id={run_id} state={state} gate={gate} total_cases={total}"
    )
    raise typer.Exit(code=_gate_exit_code(payload.get("gate_outcome")))


@app.command()
def wait(
    run_id: Annotated[
        str,
        typer.Argument(help="Run ID to wait for."),
    ],
    url: Annotated[
        str,
        typer.Option(help="Base URL of the API service."),
    ] = "http://127.0.0.1:8000",
    timeout_seconds: Annotated[
        float,
        typer.Option(min=1.0, max=3600.0, help="Maximum time to wait in seconds."),
    ] = 300.0,
    poll_interval: Annotated[
        float,
        typer.Option(min=0.1, max=60.0, help="Poll interval in seconds."),
    ] = 2.0,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON output on completion."),
    ] = False,
) -> None:
    """Poll a run until it completes, fails, or the timeout is reached."""
    endpoint = f"{url.rstrip('/')}/api/v1/runs/{run_id}"
    deadline = time.monotonic() + timeout_seconds

    while True:
        if time.monotonic() >= deadline:
            typer.echo(f"Wait timed out after {timeout_seconds}s", err=True)
            raise typer.Exit(code=EXIT_TIMEOUT)

        try:
            response = httpx.get(endpoint, timeout=10.0)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                typer.echo(f"Run {run_id} not found", err=True)
                raise typer.Exit(code=EXIT_ERROR) from None
            typer.echo(f"Poll failed (HTTP {exc.response.status_code})", err=True)
            raise typer.Exit(code=EXIT_ERROR) from None
        except httpx.TimeoutException:
            typer.echo("Poll request timed out, retrying...", err=True)
            time.sleep(poll_interval)
            continue
        except httpx.HTTPError as exc:
            typer.echo(f"Poll request failed: {exc}", err=True)
            raise typer.Exit(code=EXIT_ERROR) from None

        state = payload.get("state")
        if state in ("completed", "failed"):
            gate = payload.get("gate_outcome") or "error"
            if json_output:
                typer.echo(json.dumps(payload, sort_keys=True))
            else:
                total = payload.get("total_cases") or "?"
                typer.echo(
                    f"run_id={run_id} state={state} gate={gate} total_cases={total}"
                )
            raise typer.Exit(code=_gate_exit_code(gate))

        time.sleep(poll_interval)


@app.command()
def download(
    run_id: Annotated[
        str,
        typer.Argument(help="Run ID to download."),
    ],
    output_path: Annotated[
        Path,
        typer.Option(dir_okay=False, help="Output file path for the report JSON."),
    ],
    url: Annotated[
        str,
        typer.Option(help="Base URL of the API service."),
    ] = "http://127.0.0.1:8000",
    timeout_seconds: Annotated[
        float,
        typer.Option(min=0.1, max=120.0, help="Request timeout in seconds."),
    ] = 30.0,
) -> None:
    """Download the full run report (with case evidence) to a JSON file."""
    endpoint = f"{url.rstrip('/')}/api/v1/runs/{run_id}/report"
    try:
        response = httpx.get(endpoint, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            typer.echo(f"Run {run_id} not found", err=True)
            raise typer.Exit(code=EXIT_ERROR) from None
        detail = exc.response.text[:500] if exc.response.text else str(exc)
        typer.echo(f"Download failed (HTTP {exc.response.status_code}): {detail}", err=True)
        raise typer.Exit(code=EXIT_ERROR) from None
    except httpx.TimeoutException:
        typer.echo("Download request timed out", err=True)
        raise typer.Exit(code=EXIT_TIMEOUT) from None
    except httpx.HTTPError as exc:
        typer.echo(f"Download request failed: {exc}", err=True)
        raise typer.Exit(code=EXIT_ERROR) from None

    output_path.write_text(
        f"{json.dumps(payload, indent=2, sort_keys=True)}\n", encoding="utf-8"
    )
    gate = payload.get("gate_outcome")
    typer.echo(f"Report written to {output_path}")
    raise typer.Exit(code=_gate_exit_code(gate))


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
        raise typer.Exit(code=EXIT_ERROR)

    if os.environ.get("MRDS_WORKER_FAKE_PROVIDER"):
        provider: Provider = FakeProvider({})
    else:
        api_key = os.environ.get("MRDS_OPENROUTER_API_KEY")
        if not api_key:
            typer.echo("Worker requires MRDS_OPENROUTER_API_KEY to be configured", err=True)
            raise typer.Exit(code=EXIT_ERROR)
        provider = OpenRouterProvider(api_key_provider=lambda: api_key)

    async def _run() -> None:
        assert settings.database_url is not None
        engine = create_engine(settings.database_url)
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
