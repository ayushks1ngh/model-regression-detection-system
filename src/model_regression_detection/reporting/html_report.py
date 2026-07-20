"""Self-contained safe HTML report generation."""

from html import escape

from model_regression_detection import __version__
from model_regression_detection.policy.models import (
    BaselineComparison,
    RuleDecision,
    RuleStatus,
)
from model_regression_detection.reporting.models import (
    JsonReport,
    ReportCase,
    ReportEvaluation,
)

_MAX_DIFF_LINES = 50


def _css() -> str:
    return """\
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;\
font-size:14px;line-height:1.5;color:#1a1a2e;background:#f5f6fa;padding:20px}
.container{max-width:960px;margin:0 auto}
.card{background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1);\
padding:20px;margin-bottom:16px}
h1{font-size:20px;margin-bottom:4px}
h2{font-size:16px;margin-bottom:12px;padding-bottom:6px;border-bottom:1px solid #e0e0e0}
.badge{display:inline-block;padding:3px 10px;border-radius:12px;\
font-size:12px;font-weight:600;text-transform:uppercase}
.badge-pass{background:#d4edda;color:#155724}
.badge-fail{background:#f8d7da;color:#721c24}
.badge-error{background:#fff3cd;color:#856404}
.badge-ok{background:#d4edda;color:#155724}
.badge-violated{background:#f8d7da;color:#721c24}
.badge-ie{background:#fff3cd;color:#856404}
.badge-na{background:#e2e3e5;color:#383d41}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #eee}
th{font-weight:600;color:#555;font-size:12px;text-transform:uppercase}
code{font-family:'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace;\
font-size:12px;background:#f0f0f0;padding:1px 4px;border-radius:3px}
pre{font-family:'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace;\
font-size:12px;background:#1a1a2e;color:#f8f8f2;padding:12px;border-radius:6px;\
overflow-x:auto;white-space:pre-wrap;word-break:break-all;max-height:400px}
.delta-up{color:#155724}
.delta-down{color:#721c24}
.footer{text-align:center;color:#888;font-size:12px;padding:16px}
.eval-passed{color:#155724}
.eval-failed{color:#721c24}
.eval-errored{color:#856404}
.eval-na{color:#888}
"""


def _outcome_badge(outcome: str) -> str:
    cls = {"pass": "badge-pass", "fail": "badge-fail", "error": "badge-error"}
    return f'<span class="badge {cls.get(outcome, "badge-na")}">{escape(outcome)}</span>'


def _status_badge(status: RuleStatus) -> str:
    cls = {
        RuleStatus.PASSED: "badge-ok",
        RuleStatus.VIOLATED: "badge-violated",
        RuleStatus.INSUFFICIENT_EVIDENCE: "badge-ie",
        RuleStatus.NOT_APPLICABLE: "badge-na",
    }
    return f'<span class="badge {cls.get(status, "badge-na")}">{escape(status.value)}</span>'


def _h(text: str) -> str:
    """HTML-escape a string."""
    return escape(text, quote=True)


def _provenance_section(report: JsonReport) -> str:
    p = report.provenance
    lines = [
        "<div class='card'>",
        "<h2>Provenance</h2>",
        "<table>",
        f"<tr><th>Suite</th><td>{_h(p.suite)}</td></tr>",
        f"<tr><th>Configuration</th><td><code>{_h(p.configuration_hash)}</code></td></tr>",
        f"<tr><th>Dataset</th><td><code>{_h(p.dataset_hash)}</code></td></tr>",
        f"<tr><th>Prompt</th><td>{_h(p.prompt.target_id)} v{_h(p.prompt.version)}</td></tr>",
        f"<tr><th>Model</th><td>{_h(p.model.target_id)} v{_h(p.model.version)}</td></tr>",
    ]
    if p.agent:
        lines.append(
            f"<tr><th>Agent</th><td>{_h(p.agent.target_id)} v{_h(p.agent.version)}</td></tr>"
        )
    lines.append("</table></div>")
    return "\n".join(lines)


def _metrics_section(report: JsonReport) -> str:
    m = report.metrics
    return f"""\
<div class='card'>
<h2>Metrics</h2>
<table>
<tr><th>Total cases</th><td>{m.total_cases}</td></tr>
<tr><th>Passed</th><td>{m.passed_cases} ({m.pass_rate * 100:.1f}%)</td></tr>
<tr><th>Failed</th><td>{m.failed_cases}</td></tr>
<tr><th>Errors</th><td>{m.error_cases} ({m.error_rate * 100:.1f}%)</td></tr>
<tr><th>Total latency</th><td>{m.total_latency_ms:.1f} ms</td></tr>
<tr><th>Total tokens</th><td>{m.total_tokens:,} \
({m.input_tokens:,} in / {m.output_tokens:,} out)</td></tr>
</table>
</div>"""


def _observed_str(rule: RuleDecision) -> str:
    observed = rule.observed
    if observed is None:
        return "—"
    if rule.unit in {"count", "boolean"}:
        return str(observed)
    if rule.unit == "ratio":
        return f"{observed:.2%}"
    return f"{observed:.1f}%"


def _threshold_str(rule: RuleDecision) -> str:
    thr = rule.threshold
    if thr is None:
        return "—"
    if rule.unit in {"count", "boolean"}:
        return str(thr)
    if rule.unit == "ratio":
        return f"{thr:.2%}"
    return f"{thr:.1f}%"


def _rules_section(rules: tuple[RuleDecision, ...]) -> str:
    rows: list[str] = []
    for rule in rules:
        obs_str: str = _observed_str(rule)
        thr_str: str = _threshold_str(rule)
        rows.append(
            f"<tr><td>{_h(rule.rule_id)}</td>"
            f"<td>{_status_badge(rule.status)}</td>"
            f"<td>{obs_str}</td>"
            f"<td>{thr_str}</td>"
            f"<td>{_h(rule.explanation)}</td></tr>"
        )
    return f"""\
<div class='card'>
<h2>Rules</h2>
<table>
<thead><tr><th>Rule</th><th>Status</th><th>Observed</th><th>Threshold</th><th>Explanation</th></tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
</div>"""


def _format_delta(val: float | None, unit: str) -> str:
    if val is None:
        return "—"
    if unit == "%":
        return f"{val:+.1f}%"
    if unit == "ratio":
        return f"{val:+.2%}"
    return f"{val:+g}"


def _baseline_section(baseline: BaselineComparison | None) -> str:
    if baseline is None:
        return ""
    config_ok = baseline.configuration_match and baseline.dataset_match
    match_icon = "&#x2705;" if config_ok else "&#x26A0;"
    rows = [
        f"<tr><td>Configuration match</td><td>{match_icon} {_h(str(config_ok))}</td></tr>",
        f"<tr><td>Matching cases</td><td>{len(baseline.matching_case_keys)}"
        f" / {baseline.total_cases_baseline}</td></tr>",
    ]
    if baseline.missing_in_candidate:
        rows.append(
            "<tr><td>Missing in candidate</td><td>"
            f"{', '.join(_h(k) for k in baseline.missing_in_candidate)}</td></tr>"
        )
    if baseline.missing_in_baseline:
        rows.append(
            "<tr><td>Missing in baseline</td><td>"
            f"{', '.join(_h(k) for k in baseline.missing_in_baseline)}</td></tr>"
        )
    rows.append(
        "<tr><td>Pass rate baseline</td><td>"
        f"{_format_delta(baseline.pass_rate_baseline, 'ratio')}</td></tr>"
    )
    rows.append(
        "<tr><td>Pass rate candidate</td><td>"
        f"{_format_delta(baseline.pass_rate_candidate, 'ratio')}</td></tr>"
    )
    rows.append(
        "<tr><td>Pass rate drop</td><td>"
        f"{_format_delta(baseline.pass_rate_drop, 'ratio')}</td></tr>"
    )
    rows.append(
        f"<tr><td>Latency baseline</td><td>{baseline.latency_ms_baseline:.1f} ms</td></tr>"
    )
    rows.append(
        f"<tr><td>Latency candidate</td><td>{baseline.latency_ms_candidate:.1f} ms</td></tr>"
    )
    rows.append(
        "<tr><td>Latency increase</td><td>"
        f"{_format_delta(baseline.latency_increase_pct, '%')}</td></tr>"
    )
    if baseline.cost_increase_pct is not None:
        rows.append(
            "<tr><td>Cost increase</td><td>"
            f"{_format_delta(baseline.cost_increase_pct, '%')}</td></tr>"
        )
    return f"""\
<div class='card'>
<h2>Baseline comparison</h2>
<table>
{''.join(rows)}
</table>
</div>"""


def _case_eval_row(eval: ReportEvaluation) -> str:
    cls = {
        "passed": "eval-passed",
        "failed": "eval-failed",
        "errored": "eval-errored",
    }
    css = cls.get(eval.status.value, "eval-na")
    return (
        f"<tr class='{css}'><td>{_h(eval.evaluator_name)}</td>"
        f"<td>{_h(eval.status.value)}</td>"
        f"<td>{_h(eval.explanation)}</td></tr>"
    )


def _case_section(case: ReportCase) -> str:
    eval_rows = "\n".join(_case_eval_row(e) for e in case.evaluations)
    error_info = ""
    if case.provider_error:
        error_info = (
            f"<tr><td>Provider error</td><td colspan='2'>{_h(case.provider_error.code)}: "
            f"{_h(case.provider_error.message)}</td></tr>"
        )
    output = _h(case.output_excerpt) if case.output_excerpt else "—"
    return f"""\
<div class='card'>
<h2>Case: {_h(case.case_key)} {_outcome_badge(case.outcome.value)}</h2>
<table>
<tr><td>Ordinal</td><td>{case.ordinal}</td></tr>
<tr><td>Critical</td><td>{case.critical}</td></tr>
<tr><td>Provider status</td><td>{case.provider_status}</td></tr>
<tr><td>Resolved model</td><td>{_h(case.resolved_model) if case.resolved_model else '—'}</td></tr>
<tr><td>Latency</td><td>{case.latency_ms:.1f} ms</td></tr>
<tr><td>Output excerpt</td><td><pre>{output}</pre></td></tr>
{error_info}
</table>
<h3>Evaluations</h3>
<table>
<thead><tr><th>Evaluator</th><th>Status</th><th>Explanation</th></tr></thead>
<tbody>
{eval_rows}
</tbody>
</table>
</div>"""


def build_html_report(
    report: JsonReport,
    baseline: BaselineComparison | None = None,
) -> str:
    """Generate a self-contained, safely-escaped HTML report.

    All user-controlled content is HTML-escaped. The page includes a CSP
    meta tag and has no external dependencies.
    """
    provenance = _provenance_section(report)
    metrics = _metrics_section(report)
    rules = _rules_section(report.rules)
    baseline_html = _baseline_section(baseline)
    cases_html = "\n".join(_case_section(c) for c in report.cases)

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" \
content="default-src 'self'; style-src 'unsafe-inline'; script-src 'none'; img-src 'self' data:;">
<title>Evaluation Report — {_h(report.provenance.suite)}</title>
<style>{_css()}</style>
</head>
<body>
<div class="container">
<div class="card">
<h1>Evaluation Report: {_h(report.provenance.suite)}</h1>
<p>Gate outcome: {_outcome_badge(report.gate_outcome.value)} \
&nbsp; Generated by {_h(__version__)}</p>
</div>
{provenance}
{metrics}
{rules}
{baseline_html}
{cases_html}
<div class="footer">
<p>Schema version {report.schema_version} &middot; Generator {_h(__version__)}</p>
</div>
</div>
</body>
</html>"""
