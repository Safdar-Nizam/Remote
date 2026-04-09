"""
ValidationResult — stores each validation rule outcome per case.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, func
from sqlmodel import Field, SQLModel


class ValidationSeverity(str, enum.Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


class ValidationResult(SQLModel, table=True):
    __tablename__ = "validation_result"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    case_id: uuid.UUID = Field(foreign_key="onboarding_case.id", index=True)

    validation_type: str = Field(max_length=64)   # e.g. "required_fields", "start_date", "duplicate"
    field_name: str | None = Field(default=None, max_length=128)
    severity: ValidationSeverity = Field(
        sa_column=Column(Enum(ValidationSeverity, name="validation_severity_enum"), nullable=False)
    )
    result: str = Field(max_length=16)   # "pass" or "fail"
    message: str = Field(max_length=512)

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
