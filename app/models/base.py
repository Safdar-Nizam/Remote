"""
Import all models here so Alembic can discover them via a single import.
"""

from app.models.audit_log import AuditLog  # noqa: F401
from app.models.document_check import DocumentCheck  # noqa: F401
from app.models.escalation import Escalation  # noqa: F401
from app.models.onboarding_case import CaseSeverity, CaseStatus, OnboardingCase, SourceSystem  # noqa: F401
from app.models.onboarding_event import OnboardingEvent  # noqa: F401
from app.models.sync_task import SyncTask, SyncTaskStatus, TargetSystem  # noqa: F401
from app.models.validation_result import ValidationResult, ValidationSeverity  # noqa: F401
