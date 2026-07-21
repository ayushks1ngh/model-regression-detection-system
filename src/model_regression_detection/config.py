"""Typed application configuration."""

import logging
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Supported deployment environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Application settings loaded strictly from MRDS-prefixed environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="MRDS_",
        extra="forbid",
        case_sensitive=False,
        validate_default=True,
    )

    app_name: Annotated[str, Field(min_length=1, max_length=100)] = (
        "model-regression-detection-system"
    )
    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    host: str = "0.0.0.0"  # noqa: S104 - configurable server bind default
    port: Annotated[int, Field(ge=1, le=65535)] = 8000
    request_id_header: Annotated[str, Field(min_length=1, max_length=100)] = "X-Request-ID"
    max_request_body_size: Annotated[int, Field(ge=1, le=100_000_000)] = 10_000_000
    database_url: Annotated[str | None, Field(min_length=1, max_length=500)] = None

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Normalize and validate standard-library logging levels."""
        normalized = value.upper()
        if normalized not in logging.getLevelNamesMapping():
            msg = f"Unsupported log level: {value!r}"
            raise ValueError(msg)
        return normalized


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable settings instance."""
    return Settings()
