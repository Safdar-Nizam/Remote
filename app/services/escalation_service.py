"""
Escalation service — SLA monitoring, severity routing, and escalation triggers.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.escalation import Escalation
from app.models.onboarding_case import CaseSeverity, OnboardingCase

logger = get_logger(__name__)

# Severity → Slack channel routing
SEVERITY_CHANNEL_MAP: dict[str, str] = {
    "LOW": "#ops-onboarding",
    "MEDIUM": "#ops-onboarding",
    "HIGH": "#ops-onboarding-urgent",
    "CRITICAL": "#ops-leadership",
}


def get_sla_deadline(escalation_type: str) -> datetime:
    """Calculate SLA deadline based on escalation type."""
    settings = get_settings()
    now = datetime.now(timezone.utc)

    sla_map = {
        "validation_blocked": timedelta(minutes=settings.sla_validation_blocked_minutes),
        "missing_docs": timedelta(hours=settings.sla_missing_docs_hours),
        "legal_review": timedelta(minutes=settings.sla_legal_review_minutes),
        "idle_case": timedelta(hours=settings.sla_idle_case_hours),
        "blocked_unresolved": timedelta(hours=settings.sla_idle_case_hours),
        "remote_sync_not_started": timedelta(minutes=15),
        "sync_stuck": timedelta(minutes=30),
        "invite_no_progress": timedelta(hours=24),
        "employee_pending": timedelta(hours=48),
    }

    delta = sla_map.get(escalation_type, timedelta(hours=4))
    return now + delta


def route_escalation_channel(severity: str) -> str:
    """Get the Slack channel for a given severity level."""
    return SEVERITY_CHANNEL_MAP.get(severity.upper(), "#ops-onboarding")


async def create_escalation(
    session: AsyncSession,
    case: OnboardingCase,
    escalation_type: str,
    severity: str = "MEDIUM",
    target: str | None = None,
) -> Escalation:
    """Create an escalation record and return it."""
    channel = route_escalation_channel(severity)
    deadline = get_sla_deadline(escalation_type)

    escalation = Escalation(
        id=uuid.uuid4(),
        case_id=case.id,
        escalation_type=escalation_type,
        channel=channel,
        target=target or case.owner_user_id,
        severity=severity,
        sla_deadline=deadline,
    )
    session.add(escalation)

    logger.info(
        "escalation_created",
        workflow_id=case.workflow_id,
        type=escalation_type,
        severity=severity,
        deadline=deadline.isoformat(),
    )
    return escalation


async def acknowledge_escalation(
    session: AsyncSession,
    escalation_id: uuid.UUID,
) -> Escalation | None:
    """Mark an escalation as acknowledged."""
    result = await session.execute(
        select(Escalation).where(Escalation.id == escalation_id)
    )
    esc = result.scalar_one_or_none()
    if esc:
        esc.acknowledged_at = datetime.now(timezone.utc)
        session.add(esc)
    return esc


async def resolve_escalation(
    session: AsyncSession,
    escalation_id: uuid.UUID,
) -> Escalation | None:
    """Mark an escalation as resolved."""
    result = await session.execute(
        select(Escalation).where(Escalation.id == escalation_id)
    )
    esc = result.scalar_one_or_none()
    if esc:
        esc.resolved_at = datetime.now(timezone.utc)
        session.add(esc)
    return esc
