"""
Watchdog sweep — scheduled job that scans for stuck, stalled, or SLA-breaching cases.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.models.escalation import Escalation
from app.models.onboarding_case import CaseSeverity, CaseStatus, OnboardingCase
from app.services.slack_service import build_escalation_notification, send_slack_notification
from app.services.state_machine import transition_case

logger = get_logger(__name__)

# States that should not be idle for too long
MONITORED_STATES = {
    CaseStatus.VALIDATING: ("validation_stuck", 10),              # 10 minutes
    CaseStatus.BLOCKED_VALIDATION: ("blocked_unresolved", 300),    # 5 hours
    CaseStatus.READY_FOR_REMOTE: ("remote_sync_not_started", 15), # 15 minutes
    CaseStatus.REMOTE_SYNC_IN_PROGRESS: ("sync_stuck", 30),      # 30 minutes
    CaseStatus.REMOTE_INVITED: ("invite_no_progress", 1440),      # 24 hours
    CaseStatus.PENDING_DOCUMENTS: ("docs_pending", 1440),         # 24 hours
    CaseStatus.LEGAL_REVIEW_REQUIRED: ("legal_review_pending", 480),  # 8 hours
    CaseStatus.WAITING_ON_EMPLOYEE: ("employee_pending", 2880),   # 48 hours
}


async def sweep_stuck_cases() -> int:
    """
    Scan for cases stuck in monitored states beyond their threshold.
    Creates escalation records and sends Slack alerts.
    Returns the count of cases escalated.
    """
    settings = get_settings()
    escalated_count = 0
    now = datetime.now(timezone.utc)

    async with async_session_factory() as session:
        for status, (escalation_type, threshold_minutes) in MONITORED_STATES.items():
            cutoff = now - timedelta(minutes=threshold_minutes)

            result = await session.execute(
                select(OnboardingCase).where(
                    OnboardingCase.status == status,
                    OnboardingCase.updated_at < cutoff,
                )
            )
            stuck_cases = result.scalars().all()

            for case in stuck_cases:
                # Check if we already escalated this case recently (avoid spam)
                existing_escalation = await session.execute(
                    select(Escalation).where(
                        Escalation.case_id == case.id,
                        Escalation.escalation_type == escalation_type,
                        Escalation.resolved_at.is_(None),
                    )
                )
                if existing_escalation.scalar_one_or_none():
                    continue  # Already escalated, skip

                # Determine severity based on how long it's been stuck
                time_stuck = now - case.updated_at
                if time_stuck > timedelta(minutes=threshold_minutes * 3):
                    severity = "critical"
                elif time_stuck > timedelta(minutes=threshold_minutes * 2):
                    severity = "high"
                else:
                    severity = "medium"

                # Create escalation record
                escalation = Escalation(
                    id=uuid.uuid4(),
                    case_id=case.id,
                    escalation_type=escalation_type,
                    channel="ops-onboarding",  # Default channel — configurable later
                    target=case.owner_user_id,
                    severity=severity,
                    sla_deadline=now + timedelta(hours=4),
                )
                session.add(escalation)

                # Update case severity if needed
                severity_map = {"medium": CaseSeverity.MEDIUM, "high": CaseSeverity.HIGH, "critical": CaseSeverity.CRITICAL}
                new_severity = severity_map.get(severity, CaseSeverity.MEDIUM)
                if case.severity.value < new_severity.value:  # type: ignore
                    case.severity = new_severity
                    session.add(case)

                # Send Slack alert
                notification = build_escalation_notification(
                    workflow_id=case.workflow_id,
                    employee_name=case.employee_full_name,
                    escalation_type=escalation_type,
                    owner=case.owner_user_id,
                    severity=severity,
                    sla_deadline=escalation.sla_deadline.isoformat() if escalation.sla_deadline else None,
                )
                await send_slack_notification(notification)

                escalated_count += 1
                logger.info(
                    "case_escalated",
                    workflow_id=case.workflow_id,
                    escalation_type=escalation_type,
                    severity=severity,
                    minutes_stuck=int(time_stuck.total_seconds() / 60),
                )

        await session.commit()

    logger.info("sweep_complete", escalated_count=escalated_count)
    return escalated_count
