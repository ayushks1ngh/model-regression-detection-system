"""FastAPI application factory and composition root."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from model_regression_detection import __version__
from model_regression_detection.api.baselines import router as baselines_router
from model_regression_detection.api.middleware import RequestContextMiddleware
from model_regression_detection.api.routes import router as health_router
from model_regression_detection.api.runs import router as runs_router
from model_regression_detection.config import Settings, get_settings
from model_regression_detection.logging import configure_logging
from model_regression_detection.persistence.engine import (
    create_engine,
    create_session_factory,
    dispose_engine,
)

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an isolated application instance with validated dependencies."""
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = (
            create_engine(resolved_settings.database_url)
            if resolved_settings.database_url is not None
            else None
        )
        application.state.db_engine = engine
        application.state.db_session_factory = (
            create_session_factory(engine) if engine is not None else None
        )
        logger.info(
            "application_started",
            extra={
                "service": resolved_settings.app_name,
                "version": __version__,
                "environment": resolved_settings.environment.value,
                "database_configured": engine is not None,
            },
        )
        yield
        if engine is not None:
            await dispose_engine(engine)
        logger.info("application_stopped", extra={"service": resolved_settings.app_name})

    application = FastAPI(
        title=resolved_settings.app_name,
        version=__version__,
        docs_url="/docs" if resolved_settings.environment.value != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.add_middleware(
        RequestContextMiddleware,
        header_name=resolved_settings.request_id_header,
    )
    application.include_router(health_router)
    application.include_router(runs_router)
    application.include_router(baselines_router)
    return application


app = create_app()
