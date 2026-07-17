"""Durable worker that executes runs claimed from PostgreSQL."""

from model_regression_detection.workers.worker import Worker

__all__ = ["Worker"]
