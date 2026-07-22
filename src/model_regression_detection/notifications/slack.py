"""Bounded, retryable Slack webhook notification for terminal runs."""

import json
import time
from typing import Any

import httpx

from model_regression_detection.policy.models import GateOutcome
from model_regression_detection.reporting.models import JsonReport

_MAX_RETRIES = 3
_RETRY_BASE_DELAY_S = 1.0
_MAX_MESSAGE_LENGTH = 3_800
_HTTP_TIMEOUT_S = 10.0


def _outcome_emoji(outcome: GateOutcome) -> str:
    return {
        GateOutcome.PASS: "✅",
        GateOutcome.FAIL: "❌",
        GateOutcome.ERROR: "⚠️",
    }.get(outcome, "⚪")


def _build_message(report: JsonReport, report_url: str | None = None) -> dict[str, Any]:
    """Build a Slack Blocks payload from an evaluation report.

    The message is bounded to fit within Slack's 4000-character limit and
    contains no raw case outputs (only summaries and outcomes).
    """
    emoji = _outcome_emoji(report.gate_outcome)
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} MRDS Evaluation: {report.provenance.suite}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Gate outcome:* {report.gate_outcome.value}\n"
                    f"*Suite:* {report.provenance.suite}\n"
                    f"*Configuration:* `{report.provenance.configuration_hash[:12]}…`\n"
                    f"*Dataset:* `{report.provenance.dataset_hash[:12]}…`"
                ),
            },
        },
        {"type": "divider"},
    ]

    m = report.metrics
    metrics_text = (
        f"*Metrics*\n"
        f"• Pass rate: {m.pass_rate * 100:.1f}% ({m.passed_cases}/{m.total_cases})\n"
        f"• Error rate: {m.error_rate * 100:.1f}% ({m.error_cases}/{m.total_cases})\n"
        f"• Total latency: {m.total_latency_ms:.1f} ms\n"
        f"• Total tokens: {m.total_tokens:,}"
    )
    blocks.append(
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": metrics_text},
        }
    )

    violated = [r for r in report.rules if r.status.value == "violated"]
    if violated:
        rule_lines = ["*Violated rules*"]
        for rule in violated:
            rule_lines.append(f"• *{rule.rule_id}* — {rule.explanation}")
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(rule_lines)},
            }
        )

    if report_url:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Report:* {report_url}",
                },
            }
        )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"MRDS v{report.generator_version} | Schema {report.schema_version}",
                }
            ],
        }
    )

    return {"text": f"MRDS Evaluation: {report.provenance.suite}", "blocks": blocks}


def _message_length(blocks: list[dict[str, Any]]) -> int:
    """Approximate total character length of a blocks payload."""
    text = json.dumps(blocks)
    return len(text)


def _truncate_blocks(
    blocks: list[dict[str, Any]], max_len: int = _MAX_MESSAGE_LENGTH
) -> list[dict[str, Any]]:
    """Remove trailing non-essential blocks until the payload fits."""
    while blocks and _message_length(blocks) > max_len:
        for idx in range(len(blocks) - 1, -1, -1):
            if blocks[idx]["type"] in {"section", "context", "divider"}:
                blocks.pop(idx)
                break
        else:
            break
    return blocks


def send_slack_notification(
    webhook_url: str,
    report: JsonReport,
    report_url: str | None = None,
) -> bool:
    """Send a bounded Slack notification for a completed evaluation run.

    Returns ``True`` on successful delivery, ``False`` on failure.
    Notification failure **never** raises — it cannot change a gate outcome.

    Retries up to ``_MAX_RETRIES`` times with exponential backoff on
    transient HTTP errors (5xx, timeout).
    """
    payload = _build_message(report, report_url)
    payload["blocks"] = _truncate_blocks(payload["blocks"])

    for attempt in range(_MAX_RETRIES):
        try:
            response = httpx.post(
                webhook_url,
                json=payload,
                timeout=_HTTP_TIMEOUT_S,
            )
            if response.is_success:
                return True
            if 500 <= response.status_code < 600:
                pass
            else:
                return False
        except (httpx.TimeoutException, httpx.TransportError):
            pass

        if attempt < _MAX_RETRIES - 1:
            delay = _RETRY_BASE_DELAY_S * (2**attempt)
            time.sleep(delay)

    return False
