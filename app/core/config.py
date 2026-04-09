"""
Application configuration via Pydantic BaseSettings.
All env vars are loaded from .env or the system environment.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Database ──
    database_url: str = "postgresql+asyncpg://orchestrator:orchestrator_dev@localhost:5432/onboarding"

    # ── Queue ──
    queue_backend: str = "memory"  # "memory" | "sqs"
    sqs_queue_url: str = ""
    sqs_dlq_url: str = ""
    aws_region: str = "us-east-1"

    # ── Logging ──
    log_level: str = "INFO"

    # ── Admin ──
    admin_api_key: str = "dev-admin-key-change-me"

    # ── Slack ──
    slack_webhook_url: str = ""

    # ── Remote ──
    remote_api_token: str = ""
    remote_api_base_url: str = "https://gateway.remote.com/v1"

    # ── Notion ──
    notion_api_token: str = ""
    notion_legal_db_id: str = ""

    # ── Webhook Secrets ──
    kissflow_webhook_secret: str = ""
    remote_webhook_secret: str = ""

    # ── Retry Policy ──
    max_retry_attempts: int = 5
    retry_base_delay_seconds: float = 1.0
    retry_max_delay_seconds: float = 60.0

    # ── SLA Defaults (minutes) ──
    sla_validation_blocked_minutes: int = 5
    sla_missing_docs_hours: int = 24
    sla_legal_review_minutes: int = 5
    sla_idle_case_hours: int = 4

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
