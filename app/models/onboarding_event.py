"""
OnboardingEvent — raw inbound event log for every webhook received.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Text, func
from sqlmodel import Field, SQLModel


class OnboardingEvent(SQLModel, table=True):
    __tablename__ = "onboarding_event"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    case_id: uuid.UUID = Field(foreign_key="onboarding_case.id", index=True)

    event_type: str = Field(max_length=128, index=True)  # e.g. "kissflow.hire_created"
    source_system: str = Field(max_length=32)  # KISSFLOW, REMOTE, NOTION
    source_event_id: str | None = Field(default=None, max_length=256)  # External event ID for dedup
    payload_json: str = Field(sa_column=Column(Text, nullable=False))  # Raw JSON payload

    received_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    processed_at: datetime | None = Field(default=None)
    processing_result: str | None = Field(default=None, max_length=32)  # "success", "failed", "skipped"
    error_code: str | None = Field(default=None, max_length=64)
    attempt_count: int = Field(default=0)
