"""
Escalation — SLA tracking and escalation records per case.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, func
from sqlmodel import Field, SQLModel


class Escalation(SQLModel, table=True):
    __tablename__ = "escalation"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    case_id: uuid.UUID = Field(foreign_key="onboarding_case.id", index=True)

    escalation_type: str = Field(max_length=64)     # e.g. "sla_breach", "stuck_case", "missing_docs"
    channel: str = Field(max_length=128)              # Slack channel or email target
    target: str | None = Field(default=None, max_length=255)  # Person/group to escalate to
    severity: str = Field(max_length=16)              # LOW, MEDIUM, HIGH, CRITICAL

    sla_deadline: datetime | None = Field(default=None)

    triggered_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    acknowledged_at: datetime | None = Field(default=None)
    resolved_at: datetime | None = Field(default=None)
