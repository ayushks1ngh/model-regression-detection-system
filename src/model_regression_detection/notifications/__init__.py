"""Bounded, retryable notifications that never change gate outcomes."""

from model_regression_detection.notifications.slack import send_slack_notification

__all__ = ["send_slack_notification"]
