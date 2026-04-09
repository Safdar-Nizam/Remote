"""
OnboardingCase — the primary workflow record for each hire.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Column, DateTime, Enum, String, Text, func
from sqlmodel import Field, SQLModel


class CaseStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    NORMALIZING = "NORMALIZING"
    VALIDATING = "VALIDATING"
    BLOCKED_VALIDATION = "BLOCKED_VALIDATION"
    READY_FOR_REMOTE = "READY_FOR_REMOTE"
    REMOTE_SYNC_IN_PROGRESS = "REMOTE_SYNC_IN_PROGRESS"
    REMOTE_INVITED = "REMOTE_INVITED"
    REMOTE_ONBOARDING_IN_PROGRESS = "REMOTE_ONBOARDING_IN_PROGRESS"
    PENDING_DOCUMENTS = "PENDING_DOCUMENTS"
    PENDING_CONTRACT_ACTION = "PENDING_CONTRACT_ACTION"
    LEGAL_REVIEW_REQUIRED = "LEGAL_REVIEW_REQUIRED"
    WAITING_ON_EMPLOYEE = "WAITING_ON_EMPLOYEE"
    WAITING_ON_INTERNAL_OWNER = "WAITING_ON_INTERNAL_OWNER"
    ESCALATED = "ESCALATED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED_TERMINAL = "FAILED_TERMINAL"


class SourceSystem(str, enum.Enum):
    KISSFLOW = "KISSFLOW"
    REMOTE = "REMOTE"
    NOTION = "NOTION"
    MANUAL = "MANUAL"


class CaseSeverity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class OnboardingCase(SQLModel, table=True):
    __tablename__ = "onboarding_case"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_id: str = Field(sa_column=Column(String(64), unique=True, nullable=False, index=True))
    correlation_id: uuid.UUID = Field(default_factory=uuid.uuid4, index=True)

    # Source
    external_hire_id: str | None = Field(default=None, max_length=128, index=True)
    source_system: SourceSystem = Field(
        sa_column=Column(Enum(SourceSystem, name="source_system_enum"), nullable=False)
    )

    # Employee details
    employee_email: str = Field(max_length=255, index=True)
    employee_full_name: str = Field(max_length=255)
    country_code: str = Field(max_length=2)
    hiring_entity_type: str | None = Field(default=None, max_length=64)
    start_date: date | None = Field(default=None)
    manager_email: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=128)
    job_title: str | None = Field(default=None, max_length=255)

    # Workflow state
    status: CaseStatus = Field(
        default=CaseStatus.RECEIVED,
        sa_column=Column(Enum(CaseStatus, name="case_status_enum"), nullable=False, index=True),
    )
    substatus: str | None = Field(default=None, max_length=128)
    owner_user_id: str | None = Field(default=None, max_length=128)
    severity: CaseSeverity = Field(
        default=CaseSeverity.LOW,
        sa_column=Column(Enum(CaseSeverity, name="case_severity_enum"), nullable=False),
    )

    # External references
    remote_employment_id: str | None = Field(default=None, max_length=128)
    notion_page_id: str | None = Field(default=None, max_length=128)

    # Timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )
    completed_at: datetime | None = Field(default=None)
