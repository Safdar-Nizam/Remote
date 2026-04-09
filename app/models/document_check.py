"""
DocumentCheck — tracks document presence and status per case.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, func
from sqlmodel import Field, SQLModel


class DocumentCheck(SQLModel, table=True):
    __tablename__ = "document_check"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    case_id: uuid.UUID = Field(foreign_key="onboarding_case.id", index=True)

    document_type: str = Field(max_length=64)       # e.g. "passport", "work_permit", "tax_form"
    file_name: str | None = Field(default=None, max_length=512)
    file_present: bool = Field(default=False)
    file_category: str | None = Field(default=None, max_length=64)  # "identity", "tax", "contract"
    file_status: str = Field(default="pending", max_length=32)      # "pending", "verified", "missing", "rejected"

    checked_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
