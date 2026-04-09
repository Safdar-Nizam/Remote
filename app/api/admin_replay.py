"""
Admin replay endpoint — allows manual reprocessing of failed or blocked cases.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import require_admin_api_key
from app.db.session import get_db
from app.dependencies import get_queue
from app.models.onboarding_case import CaseStatus, OnboardingCase
from app.models.sync_task import SyncTask, SyncTaskStatus
from app.schemas.internal import ReplayCaseRequest
from app.services.state_machine import write_audit

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_api_key)])
logger = get_logger(__name__)


@router.post("/cases/{case_id}/replay")
async def replay_case(
    case_id: uuid.UUID,
    body: ReplayCaseRequest,
    db: AsyncSession = Depends(get_db),
    queue=Depends(get_queue),
):
    """
    Replay (reprocess) a case from a specific step.
    - Revalidation: re-runs validation on a BLOCKED_VALIDATION case
    - Remote sync: re-attempts Remote sync on a failed sync task
    - Full replay: re-processes the case from the beginning
    
    Preserves audit trail and uses idempotency to avoid duplicate side effects.
    """
    result = await db.execute(select(OnboardingCase).where(OnboardingCase.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    replay_step = body.replay_from_step or "auto"

    # ── Determine replay action ──
    if replay_step == "validation" or (replay_step == "auto" and case.status == CaseStatus.BLOCKED_VALIDATION):
        # Re-run validation
        message = {
            "action": "revalidate",
            "case_id": str(case.id),
            "correlation_id": str(case.correlation_id),
        }
        await queue.send_message(message)

        await write_audit(
            db, case.id, "manual_replay_validation",
            actor_type="user",
            after={"reason": body.reason, "replay_step": "validation"},
        )

        logger.info("replay_validation", workflow_id=case.workflow_id)
        return {"status": "replaying", "step": "validation", "workflow_id": case.workflow_id}

    elif replay_step == "remote_sync" or (replay_step == "auto" and case.status in (CaseStatus.READY_FOR_REMOTE, CaseStatus.REMOTE_SYNC_IN_PROGRESS)):
        # Find the failed sync task and reset it
        task_result = await db.execute(
            select(SyncTask).where(
                SyncTask.case_id == case_id,
                SyncTask.target_system == "REMOTE",
                SyncTask.status.in_([SyncTaskStatus.FAILED_RETRYABLE, SyncTaskStatus.FAILED_TERMINAL]),
            ).order_by(SyncTask.created_at.desc())
        )
        task = task_result.scalar_one_or_none()

        if task:
            task.status = SyncTaskStatus.PENDING
            task.retry_count = 0
            task.last_error = None
            db.add(task)

        await write_audit(
            db, case.id, "manual_replay_remote_sync",
            actor_type="user",
            after={"reason": body.reason, "replay_step": "remote_sync", "task_id": str(task.id) if task else None},
        )

        logger.info("replay_remote_sync", workflow_id=case.workflow_id)
        return {"status": "replaying", "step": "remote_sync", "workflow_id": case.workflow_id}

    elif replay_step == "full" or replay_step == "auto":
        # Full replay — re-enqueue as new hire
        message = {
            "action": "process_new_hire",
            "source_system": case.source_system.value,
            "event_type": "hire_updated",
            "event_id": f"replay-{uuid.uuid4().hex[:8]}",
            "correlation_id": str(case.correlation_id),
            "payload": {
                "id": case.external_hire_id or str(case.id),
                "employee_email": case.employee_email,
                "employee_full_name": case.employee_full_name,
                "country": case.country_code,
                "start_date": case.start_date.isoformat() if case.start_date else None,
                "manager_email": case.manager_email,
                "department": case.department,
                "job_title": case.job_title,
                "hiring_entity_type": case.hiring_entity_type,
            },
        }
        await queue.send_message(message)

        await write_audit(
            db, case.id, "manual_replay_full",
            actor_type="user",
            after={"reason": body.reason, "replay_step": "full"},
        )

        logger.info("replay_full", workflow_id=case.workflow_id)
        return {"status": "replaying", "step": "full", "workflow_id": case.workflow_id}

    raise HTTPException(status_code=400, detail=f"Unknown replay step: {replay_step}")


@router.post("/cases/{case_id}/cancel")
async def cancel_case(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a case. Only non-terminal cases can be cancelled."""
    from app.services.state_machine import TERMINAL_STATES, transition_case

    result = await db.execute(select(OnboardingCase).where(OnboardingCase.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if case.status in TERMINAL_STATES:
        raise HTTPException(status_code=400, detail=f"Case is already in terminal state: {case.status.value}")

    await transition_case(
        db, case, CaseStatus.CANCELLED,
        actor_type="user",
        reason="manual_cancellation",
    )

    logger.info("case_cancelled", workflow_id=case.workflow_id)
    return {"status": "cancelled", "workflow_id": case.workflow_id}
