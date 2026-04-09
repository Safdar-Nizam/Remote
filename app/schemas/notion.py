"""
Notion API schemas for the legal exception tracker database.
"""

from pydantic import BaseModel, Field


class NotionLegalItem(BaseModel):
    """
    Properties to write when creating/updating a Notion legal tracker page.
    Maps to database properties in the Notion legal redlining database.
    """
    employee_name: str
    employee_email: str
    country_code: str
    issue_type: str                          # e.g. "agreement_edit", "clause_change", "compensation_change"
    requested_change_summary: str
    owner: str | None = None                 # Legal ops person assigned
    priority: str = "medium"                 # "low", "medium", "high", "critical"
    sla_deadline: str | None = None          # ISO datetime string
    source_case_workflow_id: str             # Link back to orchestrator case
    status: str = "open"                     # "open", "in_review", "resolved", "rejected"
    legal_notes: str | None = None


class NotionWebhookEvent(BaseModel):
    """
    Inbound webhook event from Notion.
    Notion webhooks are change signals — we must fetch the latest page after receiving.
    """
    event_type: str                          # e.g. "page.updated", "page.created"
    page_id: str
    database_id: str | None = None
    timestamp: str | None = None


class NotionPageResponse(BaseModel):
    """Simplified representation of a Notion database page after fetch."""
    page_id: str
    status: str | None = None
    legal_notes: str | None = None
    owner: str | None = None
    last_edited_time: str | None = None
