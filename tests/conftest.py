"""
Test fixtures — shared test DB, async client, and mock queue.
"""

import asyncio
import uuid
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.core.config import Settings


# ── Override settings for tests ──
def get_test_settings():
    return Settings(
        database_url="sqlite+aiosqlite:///./test.db",
        queue_backend="memory",
        admin_api_key="test-admin-key",
        log_level="DEBUG",
        kissflow_webhook_secret="test-kissflow-secret",
        remote_webhook_secret="test-remote-secret",
        slack_webhook_url="",
        remote_api_token="test-token",
        notion_api_token="test-token",
        notion_legal_db_id="test-db-id",
    )


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def test_db():
    """Create a fresh test database for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///./test.db", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client():
    """Create a test HTTP client with overridden settings."""
    from app.core.config import get_settings
    from app.dependencies import reset_queue
    from app.main import create_app

    # Reset singleton
    reset_queue()
    get_settings.cache_clear()

    # Override settings
    import app.core.config
    app.core.config.get_settings = get_test_settings

    test_app = create_app()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Restore
    reset_queue()


# ── Sample data factories ──

def make_kissflow_payload(
    employee_email: str = "jane.doe@example.com",
    employee_full_name: str = "Jane Doe",
    country: str = "US",
    start_date: str = "2026-05-01",
    **overrides,
) -> dict:
    """Generate a sample Kissflow webhook payload."""
    data = {
        "event_type": "hire_created",
        "event_id": str(uuid.uuid4()),
        "data": {
            "id": f"KF-{uuid.uuid4().hex[:8]}",
            "employee_email": employee_email,
            "employee_full_name": employee_full_name,
            "country": country,
            "start_date": start_date,
            "manager_email": "manager@example.com",
            "department": "Engineering",
            "job_title": "Software Engineer",
            "documents": [],
            "contract_edit_requested": False,
            **overrides,
        },
    }
    return data
