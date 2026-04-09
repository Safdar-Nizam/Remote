"""
Internal canonical schemas — the normalized representation that all external
payloads get mapped into before validation and processing.
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.onboarding_case import CaseSeverity, CaseStatus, SourceSystem


# ──────────────────────────────────────────────
# Canonical hire record (normalizer output)
# ──────────────────────────────────────────────

class CanonicalHireRecord(BaseModel):
    """Unified representation of a new hire, regardless of source system."""
    external_hire_id: str
    source_system: SourceSystem

    employee_email: str
    employee_full_name: str
    country_code: str
    hiring_entity_type: str | None = None
    start_date: date | None = None
    manager_email: str | None = None
    department: str | None = None
    job_title: str | None = None

    # Document references (file names / paths, not contents)
    document_refs: list[str] = Field(default_factory=list)

    # Flags
    contract_edit_requested: bool = False

    # Source metadata
    raw_payload: dict | None = None


# ──────────────────────────────────────────────
# Case DTOs (API responses)
# ──────────────────────────────────────────────

class CaseSummaryResponse(BaseModel):
    id: uuid.UUID
    workflow_id: str
    employee_full_name: str
    employee_email: str
    country_code: str
    status: CaseStatus
    severity: CaseSeverity
    owner_user_id: str | None
    start_date: date | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CaseDetailResponse(CaseSummaryResponse):
    correlation_id: uuid.UUID
    external_hire_id: str | None
    source_system: SourceSystem
    hiring_entity_type: str | None
    manager_email: str | None
    department: str | None
    job_title: str | None
    substatus: str | None
    remote_employment_id: str | None
    notion_page_id: str | None
    completed_at: datetime | None


class CaseListResponse(BaseModel):
    cases: list[CaseSummaryResponse]
    total: int
    page: int
    page_size: int


# ──────────────────────────────────────────────
# Admin action schemas
# ──────────────────────────────────────────────

class ReplayCaseRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    replay_from_step: str | None = None  # e.g. "validation", "remote_sync"


class ReassignOwnerRequest(BaseModel):
    new_owner_user_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)


class AddNoteRequest(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class CaseFilterParams(BaseModel):
    status: CaseStatus | None = None
    severity: CaseSeverity | None = None
    owner_user_id: str | None = None
    country_code: str | None = None
    page: int = 1
    page_size: int = 25
