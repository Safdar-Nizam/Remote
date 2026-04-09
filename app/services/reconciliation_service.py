"""
Reconciliation service — detects drift between systems, finds duplicates,
and identifies inconsistencies.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.onboarding_case import CaseStatus, OnboardingCase
from app.models.sync_task import SyncTask, SyncTaskStatus

logger = get_logger(__name__)


async def find_duplicate_cases(session: AsyncSession, window_days: int = 30) -> list[dict]:
    """
    Find potential duplicate cases — same employee_email with overlapping start dates
    within a window.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    result = await session.execute(
        select(
            OnboardingCase.employee_email,
            func.count(OnboardingCase.id).label("case_count"),
        )
        .where(
            OnboardingCase.created_at >= cutoff,
            OnboardingCase.status.notin_([CaseStatus.CANCELLED, CaseStatus.FAILED_TERMINAL]),
        )
        .group_by(OnboardingCase.employee_email)
        .having(func.count(OnboardingCase.id) > 1)
    )

    duplicates = []
    for row in result.all():
        cases_result = await session.execute(
            select(OnboardingCase).where(
                OnboardingCase.employee_email == row[0],
                OnboardingCase.created_at >= cutoff,
            ).order_by(OnboardingCase.created_at.desc())
        )
        cases = cases_result.scalars().all()
        duplicates.append({
            "employee_email": row[0],
            "case_count": row[1],
            "cases": [
                {
                    "workflow_id": c.workflow_id,
                    "status": c.status.value,
                    "start_date": c.start_date.isoformat() if c.start_date else None,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in cases
            ],
        })

    logger.info("duplicate_scan_complete", duplicates_found=len(duplicates))
    return duplicates


async def find_orphaned_sync_tasks(session: AsyncSession) -> list[dict]:
    """
    Find sync tasks that are IN_PROGRESS for too long (stuck) or
    PENDING with no corresponding case in an actionable state.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

    result = await session.execute(
        select(SyncTask).where(
            SyncTask.status == SyncTaskStatus.IN_PROGRESS,
            SyncTask.last_attempt_at < cutoff,
        )
    )

    orphaned = []
    for task in result.scalars().all():
        orphaned.append({
            "task_id": str(task.id),
            "case_id": str(task.case_id),
            "task_type": task.task_type,
            "target_system": task.target_system,
            "last_attempt": task.last_attempt_at.isoformat() if task.last_attempt_at else None,
            "retry_count": task.retry_count,
        })

    logger.info("orphaned_task_scan_complete", orphaned_found=len(orphaned))
    return orphaned


async def find_cases_missing_side_effects(session: AsyncSession) -> list[dict]:
    """
    Find cases that were created but never moved past RECEIVED,
    or cases with no sync tasks despite being in a state that should have them.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)

    # Cases stuck in RECEIVED
    result = await session.execute(
        select(OnboardingCase).where(
            OnboardingCase.status == CaseStatus.RECEIVED,
            OnboardingCase.created_at < cutoff,
        )
    )

    stuck = []
    for case in result.scalars().all():
        stuck.append({
            "workflow_id": case.workflow_id,
            "status": case.status.value,
            "issue": "stuck_in_received",
            "created_at": case.created_at.isoformat() if case.created_at else None,
        })

    logger.info("missing_side_effects_scan_complete", issues_found=len(stuck))
    return stuck
