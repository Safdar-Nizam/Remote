"""
Kissflow webhook event schemas.
These are placeholder schemas based on typical Kissflow HTTP connector payloads.
Adjust field names once real Kissflow payloads are available.
"""

from pydantic import BaseModel, Field


class KissflowDocument(BaseModel):
    """A document/file reference attached to a Kissflow hire record."""
    file_name: str
    file_url: str | None = None
    file_type: str | None = None  # e.g. "pdf", "docx"


class KissflowHirePayload(BaseModel):
    """
    Payload sent by Kissflow's HTTP connector when a new hire is created or updated.
    Field names are based on typical Kissflow process forms — rename to match actual schema.
    """
    # Kissflow record identifiers
    record_id: str = Field(alias="id")
    flow_name: str | None = Field(default=None, alias="flow_name")
    activity_name: str | None = Field(default=None, alias="activity_name")

    # Employee info
    employee_email: str
    employee_full_name: str
    country: str                                         # Could be code or full name
    hiring_entity_type: str | None = None                # "EOR", "direct", "contractor"
    start_date: str | None = None                        # Date string, format may vary
    manager_email: str | None = None
    department: str | None = None
    job_title: str | None = None

    # Documents
    documents: list[KissflowDocument] = Field(default_factory=list)

    # Contract edit flag
    contract_edit_requested: bool = False

    model_config = {"populate_by_name": True}


class KissflowWebhookEvent(BaseModel):
    """
    Top-level webhook event wrapper from Kissflow.
    The event_type distinguishes create vs update.
    """
    event_type: str             # "hire_created", "hire_updated"
    event_id: str | None = None  # Kissflow's own event/transaction ID for dedup
    data: KissflowHirePayload
