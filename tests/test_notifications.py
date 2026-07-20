"""Tests for bounded, retryable Slack notifications (M19)."""

import json
from unittest.mock import patch

from model_regression_detection.domain.versions import VersionedTargetRef
from model_regression_detection.notifications.slack import (
    _MAX_RETRIES,
    _build_message,
    _message_length,
    _truncate_blocks,
    send_slack_notification,
)
from model_regression_detection.policy.models import (
    GateOutcome,
    RuleDecision,
    RuleStatus,
    RunMetrics,
)
from model_regression_detection.reporting.models import (
    REPORT_SCHEMA_VERSION,
    JsonReport,
    ReportProvenance,
)


def _sample_report(gate: GateOutcome = GateOutcome.PASS) -> JsonReport:
    target = VersionedTargetRef(
        kind="prompt",
        target_id="test-prompt",
        version="1",
        content_hash="a" * 64,
    )
    model_target = VersionedTargetRef(
        kind="model",
        target_id="gpt-4",
        version="1",
        content_hash="b" * 64,
    )
    provenance = ReportProvenance(
        suite="test-suite",
        configuration_hash="c" * 64,
        dataset_hash="d" * 64,
        prompt=target,
        model=model_target,
        agent=None,
    )
    metrics = RunMetrics(
        total_cases=10,
        passed_cases=8,
        failed_cases=1,
        error_cases=1,
        pass_rate=0.8,
        error_rate=0.1,
        critical_failed_cases=(),
        critical_error_cases=(),
        total_latency_ms=500.0,
        input_tokens=1000,
        output_tokens=500,
        total_tokens=1500,
        cases_with_unknown_usage=0,
    )
    rules = (
        RuleDecision(
            rule_id="minimum_pass_rate",
            status=RuleStatus.PASSED if gate == GateOutcome.PASS else RuleStatus.VIOLATED,
            observed=0.8,
            threshold=0.7,
            unit="ratio",
            explanation="Pass rate meets the minimum"
            if gate == GateOutcome.PASS
            else "Pass rate is below the minimum",
        ),
    )
    return JsonReport(
        schema_version=REPORT_SCHEMA_VERSION,
        generator_version="0.1.0",
        gate_outcome=gate.value,
        provenance=provenance,
        metrics=metrics,
        rules=rules,
        cases=(),
        metadata={},
    )


def test_header_contains_suite_name() -> None:
    report = _sample_report()
    payload = _build_message(report)
    assert "test-suite" in json.dumps(payload)


def test_includes_gate_outcome() -> None:
    report = _sample_report(GateOutcome.PASS)
    payload = _build_message(report)
    text = json.dumps(payload)
    assert "pass" in text


def test_includes_fail_indicator_on_regression() -> None:
    report = _sample_report(GateOutcome.FAIL)
    payload = _build_message(report)
    text = str(payload)
    assert "❌" in text or "\\u274c" in text
    assert "fail" in json.dumps(payload)


def test_includes_violated_rules() -> None:
    report = _sample_report(GateOutcome.FAIL)
    payload = _build_message(report)
    text = json.dumps(payload)
    assert "minimum_pass_rate" in text
    assert "Violated" in text


def test_includes_report_url_when_provided() -> None:
    report = _sample_report()
    payload = _build_message(report, report_url="https://example.com/report")
    assert "https://example.com/report" in json.dumps(payload)


def test_omits_report_url_when_not_provided() -> None:
    report = _sample_report()
    payload = _build_message(report)
    assert "https://" not in json.dumps(payload)


def test_message_is_bounded() -> None:
    report = _sample_report()
    payload = _build_message(report)
    length = _message_length(payload["blocks"])
    assert length < 3_800


def test_truncate_reduces_length() -> None:
    large_blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "x" * 2_000}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "y" * 2_000}},
    ]
    result = _truncate_blocks(large_blocks, max_len=2_500)
    assert _message_length(result) <= 2_500


def test_header_always_retained() -> None:
    report = _sample_report()
    payload = _build_message(report)
    blocks = payload["blocks"]
    result = _truncate_blocks(blocks, max_len=100)
    assert any(b["type"] == "header" for b in result)


def test_success_returns_true() -> None:
    report = _sample_report()
    with patch("model_regression_detection.notifications.slack.httpx.post") as mock_post:
        mock = type("MockResponse", (), {})()
        mock.is_success = True
        mock.status_code = 200
        mock.request = None  # type: ignore[assignment]
        mock_post.return_value = mock
        result = send_slack_notification("https://hooks.slack.com/test", report)
    assert result is True


def test_http_400_returns_false_no_retry() -> None:
    report = _sample_report()
    with patch("model_regression_detection.notifications.slack.httpx.post") as mock_post:
        mock = type("MockResponse", (), {})()
        mock.is_success = False
        mock.status_code = 400
        mock.request = type("Req", (), {})()
        mock_post.return_value = mock
        result = send_slack_notification("https://hooks.slack.com/test", report)
    assert result is False


def test_http_500_retries_then_returns_false() -> None:
    report = _sample_report()
    with patch("model_regression_detection.notifications.slack.httpx.post") as mock_post:
        mock = type("MockResponse", (), {})()
        mock.is_success = False
        mock.status_code = 500
        mock.request = type("Req", (), {})()
        mock_post.return_value = mock
        result = send_slack_notification("https://hooks.slack.com/test", report)
    assert result is False
    assert mock_post.call_count == _MAX_RETRIES


def test_timeout_retries_then_returns_false() -> None:
    import httpx

    report = _sample_report()
    with patch("model_regression_detection.notifications.slack.httpx.post") as mock_post:
        mock_post.side_effect = httpx.TimeoutException("timeout")
        result = send_slack_notification("https://hooks.slack.com/test", report)
    assert result is False
    assert mock_post.call_count == _MAX_RETRIES


def test_eventually_succeeds_after_retries() -> None:
    import httpx

    report = _sample_report()
    call_count = 0

    def side_effect(*args: object, **kwargs: object) -> object:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.TimeoutException("timeout")
        mock = type("MockResponse", (), {})()
        mock.is_success = True
        mock.status_code = 200
        mock.request = None  # type: ignore[assignment]
        return mock

    with patch("model_regression_detection.notifications.slack.httpx.post") as mock_post:
        mock_post.side_effect = side_effect
        result = send_slack_notification("https://hooks.slack.com/test", report)
    assert result is True
    assert call_count == 3
