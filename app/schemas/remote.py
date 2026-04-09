"""
Remote API and webhook event schemas.
Based on Remote.com API documentation for employment lifecycle.
"""

from datetime import date

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────
# Webhook event schemas (inbound from Remote)
# ──────────────────────────────────────────────

class RemoteWebhookEvent(BaseModel):
    """
    Top-level webhook event from Remote.
    Remote sends the event type + resource ID; we fetch full details via API.
    """
    event_type: str                    # e.g. "employment.user_status.invited"
    resource_id: str                   # Employment ID
    resource_type: str = "employment"
    company_id: str | None = None
    timestamp: str | None = None


# ──────────────────────────────────────────────
# Remote API request/response schemas
# ──────────────────────────────────────────────

class RemoteEmploymentCreate(BaseModel):
    """Request body to create an employment in Remote."""
    country_code: str = Field(max_length=3)
    full_name: str
    job_title: str
    personal_email: str
    provisional_start_date: date | None = None
    type: str = "employee"  # "employee", "contractor"

    # Basic compensation (may expand by country)
    basic_salary: dict | None = None  # {"amount": 50000, "currency": "USD"}

    # Manager
    manager: dict | None = None  # {"id": "...", "email": "..."}


class RemoteEmploymentResponse(BaseModel):
    """Simplified response from Remote employment endpoints."""
    id: str                        # Remote employment UUID
    status: str                    # "created", "active", "inactive"
    user_status: str | None = None  # "invited", "active", "onboarding"
    country_code: str | None = None
    full_name: str | None = None
    personal_email: str | None = None
    provisional_start_date: date | None = None
    contract_status: str | None = None  # "pending_signature", "signed", etc.


class RemoteInviteRequest(BaseModel):
    """Optional fields when inviting an employee."""
    employment_id: str


class RemoteOnboardingTaskEvent(BaseModel):
    """Data from an onboarding task completion event."""
    employment_id: str
    task_name: str | None = None
    task_status: str = "completed"


class RemoteStartDateChangeEvent(BaseModel):
    """Data from a start date change event."""
    employment_id: str
    old_start_date: date | None = None
    new_start_date: date | None = None
