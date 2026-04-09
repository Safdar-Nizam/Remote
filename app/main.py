"""
FastAPI application factory.
Sets up middleware, routers, scheduled jobs, and the background queue consumer.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin_cases, admin_replay, admin_ui, webhooks_kissflow, webhooks_notion, webhooks_remote
from app.core.config import get_settings
from app.core.correlation import CorrelationIdMiddleware
from app.core.logging import get_logger, setup_logging
from app.dependencies import get_queue
from app.workers.process_case import process_case_message

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan — starts background workers and scheduled jobs on startup,
    shuts them down gracefully on shutdown.
    """
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("app_starting", queue_backend=settings.queue_backend)

    # Start background queue consumer
    queue = get_queue()
    consumer_task = asyncio.create_task(queue.start_consumer(process_case_message))

    # Start watchdog scheduler
    scheduler_task = None
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from app.workers.sweep_stuck_cases import sweep_stuck_cases

        scheduler = AsyncIOScheduler()
        scheduler.add_job(sweep_stuck_cases, "interval", minutes=5, id="watchdog_sweep")
        scheduler.start()
        logger.info("watchdog_scheduler_started")
    except Exception as e:
        logger.warning("scheduler_init_failed", error=str(e))
        scheduler = None

    logger.info("app_ready")
    yield

    # Shutdown
    logger.info("app_shutting_down")
    queue.stop_consumer()
    consumer_task.cancel()
    if scheduler:
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Onboarding Orchestrator",
        description="Event-driven global onboarding orchestration system connecting Kissflow, Remote, Slack, and Notion.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # ── Middleware ──
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ──
    app.include_router(webhooks_kissflow.router)
    app.include_router(webhooks_remote.router)
    app.include_router(webhooks_notion.router)
    app.include_router(admin_cases.router)
    app.include_router(admin_replay.router)
    app.include_router(admin_ui.router)

    # ── Health check ──
    @app.get("/health", tags=["system"])
    async def health_check():
        queue = get_queue()
        return {
            "status": "healthy",
            "version": "1.0.0",
            "queue_backend": settings.queue_backend,
            "queue_depth": queue.queue_depth(),
            "dlq_depth": queue.dlq_depth(),
        }

    @app.get("/", tags=["system"])
    async def root():
        return {
            "name": "Onboarding Orchestrator",
            "version": "1.0.0",
            "docs": "/docs",
        }

    return app


# Module-level app instance for uvicorn
app = create_app()
