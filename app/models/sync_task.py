"""
SyncTask — tracks every outbound integration call with retry and idempotency metadata.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, Text, func
from sqlmodel import Field, SQLModel


class TargetSystem(str, enum.Enum):
    REMOTE = "REMOTE"
    SLACK = "SLACK"
    NOTION = "NOTION"
    KISSFLOW = "KISSFLOW"


class SyncTaskStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    SKIPPED = "SKIPPED"  # Idempotency: already completed in a prior run


class SyncTask(SQLModel, table=True):
    __tablename__ = "sync_task"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    case_id: uuid.UUID = Field(foreign_key="onboarding_case.id", index=True)

    task_type: str = Field(max_length=64)       # e.g. "remote_create_employment", "slack_notify_blocked"
    target_system: TargetSystem = Field(
        sa_column=Column(Enum(TargetSystem, name="target_system_enum"), nullable=False)
    )
    target_object_id: str | None = Field(default=None, max_length=256)  # ID of created object in target

    status: SyncTaskStatus = Field(
        default=SyncTaskStatus.PENDING,
        sa_column=Column(Enum(SyncTaskStatus, name="sync_task_status_enum"), nullable=False, index=True),
    )
    idempotency_key: str = Field(max_length=64, index=True)

    retry_count: int = Field(default=0)
    last_attempt_at: datetime | None = Field(default=None)
    next_attempt_at: datetime | None = Field(default=None)
    last_error: str | None = Field(sa_column=Column(Text, nullable=True))

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )
