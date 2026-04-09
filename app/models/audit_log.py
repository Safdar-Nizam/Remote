"""
AuditLog — immutable record of every state change and significant action.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Text, func
from sqlmodel import Field, SQLModel


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    case_id: uuid.UUID = Field(foreign_key="onboarding_case.id", index=True)

    actor_type: str = Field(max_length=32)    # "system", "user", "webhook", "scheduler"
    actor_id: str | None = Field(default=None, max_length=128)  # User email or system component name

    action: str = Field(max_length=128)       # e.g. "state_transition", "validation_run", "manual_replay"

    before_json: str | None = Field(sa_column=Column(Text, nullable=True))  # Snapshot before change
    after_json: str | None = Field(sa_column=Column(Text, nullable=True))   # Snapshot after change

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
