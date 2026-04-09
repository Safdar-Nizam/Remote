"""
Admin API — case listing, detail view, and filtering.
Protected by API key authentication.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import require_admin_api_key
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.escalation import Escalation
from app.models.onboarding_case import CaseSeverity, CaseStatus, OnboardingCase
from app.models.onboarding_event import OnboardingEvent
from app.models.sync_task import SyncTask
from app.models.validation_result import ValidationResult
from app.schemas.internal import CaseDetailResponse, CaseListResponse, CaseSummaryResponse, ReassignOwnerRequest, AddNoteRequest
from app.services.state_machine import write_audit

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_api_key)])
logger = get_logger(__name__)


@router.get("/cases", response_model=CaseListResponse)
async def list_cases(
    status_filter: CaseStatus | None = Query(default=None, alias="status"),
    severity: CaseSeverity | None = None,
    owner_user_id: str | None = None,
    country_code: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List onboarding cases with optional filtering and pagination."""
    query = select(OnboardingCase)

    if status_filter:
        query = query.where(OnboardingCase.status == status_filter)
    if severity:
        query = query.where(OnboardingCase.severity == severity)
    if owner_user_id:
        query = query.where(OnboardingCase.owner_user_id == owner_user_id)
    if country_code:
        query = query.where(OnboardingCase.country_code == country_code)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Fetch page
    query = query.order_by(OnboardingCase.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    cases = result.scalars().all()

    return CaseListResponse(
        cases=[CaseSummaryResponse.model_validate(c) for c in cases],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/cases/{case_id}", response_model=CaseDetailResponse)
async def get_case(case_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get detailed view of a single onboarding case."""
    result = await db.execute(select(OnboardingCase).where(OnboardingCase.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseDetailResponse.model_validate(case)


@router.get("/cases/{case_id}/events")
async def get_case_events(case_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get all events for a case, ordered chronologically."""
    result = await db.execute(
        select(OnboardingEvent)
        .where(OnboardingEvent.case_id == case_id)
        .order_by(OnboardingEvent.received_at.asc())
    )
    events = result.scalars().all()
    return [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "source_system": e.source_system,
            "received_at": e.received_at.isoformat() if e.received_at else None,
            "processing_result": e.processing_result,
            "error_code": e.error_code,
            "attempt_count": e.attempt_count,
        }
        for e in events
    ]


@router.get("/cases/{case_id}/validations")
async def get_case_validations(case_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get all validation results for a case."""
    result = await db.execute(
        select(ValidationResult)
        .where(ValidationResult.case_id == case_id)
        .order_by(ValidationResult.created_at.desc())
    )
    return [
        {
            "id": str(v.id),
            "validation_type": v.validation_type,
            "field_name": v.field_name,
            "severity": v.severity,
            "result": v.result,
            "message": v.message,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in result.scalars().all()
    ]


@router.get("/cases/{case_id}/tasks")
async def get_case_tasks(case_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get all sync tasks for a case."""
    result = await db.execute(
        select(SyncTask)
        .where(SyncTask.case_id == case_id)
        .order_by(SyncTask.created_at.desc())
    )
    return [
        {
            "id": str(t.id),
            "task_type": t.task_type,
            "target_system": t.target_system,
            "status": t.status,
            "retry_count": t.retry_count,
            "last_error": t.last_error,
            "idempotency_key": t.idempotency_key,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in result.scalars().all()
    ]


@router.get("/cases/{case_id}/audit")
async def get_case_audit(case_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get the complete audit trail for a case."""
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.case_id == case_id)
        .order_by(AuditLog.created_at.asc())
    )
    return [
        {
            "id": str(a.id),
            "action": a.action,
            "actor_type": a.actor_type,
            "actor_id": a.actor_id,
            "before": a.before_json,
            "after": a.after_json,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in result.scalars().all()
    ]


@router.get("/cases/{case_id}/escalations")
async def get_case_escalations(case_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get all escalations for a case."""
    result = await db.execute(
        select(Escalation)
        .where(Escalation.case_id == case_id)
        .order_by(Escalation.triggered_at.desc())
    )
    return [
        {
            "id": str(e.id),
            "escalation_type": e.escalation_type,
            "severity": e.severity,
            "channel": e.channel,
            "target": e.target,
            "sla_deadline": e.sla_deadline.isoformat() if e.sla_deadline else None,
            "triggered_at": e.triggered_at.isoformat() if e.triggered_at else None,
            "acknowledged_at": e.acknowledged_at.isoformat() if e.acknowledged_at else None,
            "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
        }
        for e in result.scalars().all()
    ]


@router.patch("/cases/{case_id}/reassign")
async def reassign_case_owner(
    case_id: uuid.UUID,
    body: ReassignOwnerRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reassign the owner of a case."""
    result = await db.execute(select(OnboardingCase).where(OnboardingCase.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    old_owner = case.owner_user_id
    case.owner_user_id = body.new_owner_user_id
    case.updated_at = datetime.now(timezone.utc)
    db.add(case)

    await write_audit(
        db, case.id, "owner_reassigned",
        actor_type="user",
        before={"owner_user_id": old_owner},
        after={"owner_user_id": body.new_owner_user_id, "reason": body.reason},
    )

    logger.info("case_reassigned", workflow_id=case.workflow_id, new_owner=body.new_owner_user_id)
    return {"status": "reassigned", "new_owner": body.new_owner_user_id}


@router.post("/cases/{case_id}/note")
async def add_case_note(
    case_id: uuid.UUID,
    body: AddNoteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Add an operator note to a case's audit trail."""
    result = await db.execute(select(OnboardingCase).where(OnboardingCase.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    await write_audit(
        db, case.id, "operator_note",
        actor_type="user",
        after={"note": body.note},
    )

    return {"status": "note_added"}


@router.get("/dashboard/stats")
async def dashboard_stats(db: AsyncSession = Depends(get_db)):
    """Quick stats for the operations dashboard."""
    status_counts = {}
    for s in CaseStatus:
        count_result = await db.execute(
            select(func.count()).where(OnboardingCase.status == s)
        )
        cnt = count_result.scalar() or 0
        if cnt > 0:
            status_counts[s.value] = cnt

    total = sum(status_counts.values())
    blocked = status_counts.get("BLOCKED_VALIDATION", 0) + status_counts.get("ESCALATED", 0)

    return {
        "total_cases": total,
        "blocked_cases": blocked,
        "by_status": status_counts,
    }
