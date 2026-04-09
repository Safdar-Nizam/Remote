"""
Main case processing worker.
Consumes messages from the queue and orchestrates:
  1. Normalization
  2. Validation
  3. State transitions
  4. Downstream task scheduling (Remote sync, Slack, Notion)
"""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import set_correlation_id
from app.core.idempotency import generate_idempotency_key, generate_workflow_id
from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.models.onboarding_case import CaseSeverity, CaseStatus, OnboardingCase, SourceSystem
from app.models.onboarding_event import OnboardingEvent
from app.models.sync_task import SyncTask, SyncTaskStatus, TargetSystem
from app.models.validation_result import ValidationResult
from app.schemas.internal import CanonicalHireRecord
from app.services.normalizer import normalize_kissflow_event
from app.services.slack_service import (
    build_case_created_notification,
    build_legal_review_notification,
    build_validation_blocked_notification,
    send_slack_notification,
)
from app.services.state_machine import transition_case, write_audit
from app.services.validator import validate_hire

logger = get_logger(__name__)


async def process_case_message(message_body: dict) -> None:
    """
    Main entry point for processing a queued onboarding message.
    Message body expected:
    {
        "action": "process_new_hire" | "revalidate" | "process_remote_event" | "process_notion_event",
        "source_system": "KISSFLOW" | "REMOTE" | "NOTION",
        "event_type": "hire_created" | "hire_updated" | ...,
        "event_id": "...",
        "correlation_id": "...",
        "payload": { ... raw event data ... }
    }
    """
    action = message_body.get("action", "process_new_hire")
    correlation_id = message_body.get("correlation_id", str(uuid.uuid4()))
    set_correlation_id(correlation_id)

    logger.info("worker_processing", action=action, source=message_body.get("source_system"))

    async with async_session_factory() as session:
        try:
            if action == "process_new_hire":
                await _handle_new_hire(session, message_body, correlation_id)
            elif action == "revalidate":
                await _handle_revalidate(session, message_body, correlation_id)
            elif action == "process_remote_event":
                await _handle_remote_event(session, message_body, correlation_id)
            elif action == "process_notion_event":
                await _handle_notion_event(session, message_body, correlation_id)
            else:
                logger.warning("unknown_action", action=action)

            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error("worker_error", action=action, error=str(e), exc_info=True)
            raise  # Re-raise so queue can retry / DLQ


async def _handle_new_hire(session: AsyncSession, message: dict, correlation_id: str) -> None:
    """Process a new hire event from Kissflow."""
    from app.schemas.kissflow import KissflowWebhookEvent

    payload = message.get("payload", {})
    event_type = message.get("event_type", "hire_created")
    source_event_id = message.get("event_id")

    # ── Dedup: check if we already processed this source_event_id ──
    if source_event_id:
        existing = await session.execute(
            select(OnboardingEvent).where(
                OnboardingEvent.source_event_id == source_event_id,
                OnboardingEvent.processing_result == "success",
            )
        )
        if existing.scalar_one_or_none():
            logger.info("event_dedup_skipped", source_event_id=source_event_id)
            return

    # ── Parse and normalize ──
    try:
        event = KissflowWebhookEvent(
            event_type=event_type,
            event_id=source_event_id,
            data=payload,
        )
        canonical = normalize_kissflow_event(event)
    except Exception as e:
        logger.error("normalization_failed", error=str(e), payload=json.dumps(payload)[:500])
        raise

    # ── Check for existing case (update vs create) ──
    existing_case = None
    if canonical.external_hire_id:
        result = await session.execute(
            select(OnboardingCase).where(
                OnboardingCase.external_hire_id == canonical.external_hire_id,
                OnboardingCase.source_system == SourceSystem.KISSFLOW,
            )
        )
        existing_case = result.scalar_one_or_none()

    if existing_case and event_type == "hire_updated":
        case = existing_case
        # Update mutable fields
        case.employee_email = canonical.employee_email
        case.employee_full_name = canonical.employee_full_name
        case.country_code = canonical.country_code
        case.start_date = canonical.start_date
        case.manager_email = canonical.manager_email
        case.department = canonical.department
        case.job_title = canonical.job_title
        case.updated_at = datetime.now(timezone.utc)
        session.add(case)

        await write_audit(
            session, case.id, "case_updated",
            actor_type="webhook", actor_id="kissflow",
            after={"event_type": event_type, "fields_updated": "employee details"},
        )
        logger.info("case_updated", workflow_id=case.workflow_id)
    else:
        # ── Create new case ──
        case = OnboardingCase(
            id=uuid.uuid4(),
            workflow_id=generate_workflow_id(),
            correlation_id=uuid.UUID(correlation_id) if isinstance(correlation_id, str) else correlation_id,
            external_hire_id=canonical.external_hire_id,
            source_system=SourceSystem.KISSFLOW,
            employee_email=canonical.employee_email,
            employee_full_name=canonical.employee_full_name,
            country_code=canonical.country_code,
            hiring_entity_type=canonical.hiring_entity_type,
            start_date=canonical.start_date,
            manager_email=canonical.manager_email,
            department=canonical.department,
            job_title=canonical.job_title,
            status=CaseStatus.RECEIVED,
            severity=CaseSeverity.LOW,
        )
        session.add(case)
        await session.flush()  # Get the case.id

        await write_audit(
            session, case.id, "case_created",
            actor_type="webhook", actor_id="kissflow",
            after={"workflow_id": case.workflow_id, "source": "kissflow"},
        )
        logger.info("case_created", workflow_id=case.workflow_id, employee=canonical.employee_email)

    # ── Persist raw event ──
    event_record = OnboardingEvent(
        id=uuid.uuid4(),
        case_id=case.id,
        event_type=f"kissflow.{event_type}",
        source_system="KISSFLOW",
        source_event_id=source_event_id,
        payload_json=json.dumps(payload),
        received_at=datetime.now(timezone.utc),
    )
    session.add(event_record)

    # ── Transition: RECEIVED → VALIDATING ──
    if case.status == CaseStatus.RECEIVED:
        await transition_case(session, case, CaseStatus.VALIDATING, actor_type="system", reason="auto")

    # ── Run validation ──
    # Gather existing active emails for duplicate check
    active_result = await session.execute(
        select(OnboardingCase.employee_email).where(
            OnboardingCase.status.notin_([CaseStatus.COMPLETED, CaseStatus.CANCELLED, CaseStatus.FAILED_TERMINAL]),
            OnboardingCase.id != case.id,
        )
    )
    active_emails = {row[0].lower() for row in active_result.all()}

    outcome = validate_hire(canonical, existing_emails=active_emails)

    # ── Persist validation results ──
    for r in outcome.results:
        vr = ValidationResult(
            id=uuid.uuid4(),
            case_id=case.id,
            validation_type=r.validation_type,
            field_name=r.field_name,
            severity=r.severity,
            result=r.result,
            message=r.message,
        )
        session.add(vr)

    # ── Update event record ──
    event_record.processed_at = datetime.now(timezone.utc)
    event_record.processing_result = "success" if outcome.passed else "validation_failed"

    if outcome.passed:
        # ── Validation passed → READY_FOR_REMOTE ──
        await transition_case(session, case, CaseStatus.READY_FOR_REMOTE, actor_type="system", reason="validation_passed")

        # Schedule Remote sync task
        sync_task = SyncTask(
            id=uuid.uuid4(),
            case_id=case.id,
            task_type="remote_create_employment",
            target_system=TargetSystem.REMOTE,
            status=SyncTaskStatus.PENDING,
            idempotency_key=generate_idempotency_key("remote_create", case.workflow_id, canonical.employee_email),
        )
        session.add(sync_task)

        # Slack: case created
        notification = build_case_created_notification(
            case.workflow_id, canonical.employee_full_name,
            canonical.country_code, "Kissflow",
        )
        await send_slack_notification(notification)

    else:
        # ── Validation failed → BLOCKED_VALIDATION ──
        case.severity = CaseSeverity.HIGH
        await transition_case(
            session, case, CaseStatus.BLOCKED_VALIDATION,
            actor_type="system",
            reason=f"{len(outcome.blocking_errors)} blocking errors",
        )

        # Slack: validation blocked
        error_messages = [e.message for e in outcome.blocking_errors]
        notification = build_validation_blocked_notification(
            case.workflow_id, canonical.employee_full_name, error_messages,
        )
        await send_slack_notification(notification)

    # ── Legal review trigger ──
    if canonical.contract_edit_requested:
        if case.status not in (CaseStatus.BLOCKED_VALIDATION, CaseStatus.FAILED_TERMINAL):
            if case.status == CaseStatus.READY_FOR_REMOTE:
                # Also flag legal review
                pass  # Legal review will be created alongside Remote sync
            # Schedule Notion sync
            notion_task = SyncTask(
                id=uuid.uuid4(),
                case_id=case.id,
                task_type="notion_create_legal_item",
                target_system=TargetSystem.NOTION,
                status=SyncTaskStatus.PENDING,
                idempotency_key=generate_idempotency_key("notion_legal", case.workflow_id),
            )
            session.add(notion_task)

            legal_notification = build_legal_review_notification(
                case.workflow_id, canonical.employee_full_name, "contract_edit_requested",
            )
            await send_slack_notification(legal_notification)

    logger.info("new_hire_processed", workflow_id=case.workflow_id, passed=outcome.passed)


async def _handle_revalidate(session: AsyncSession, message: dict, correlation_id: str) -> None:
    """Re-run validation on an existing blocked case (after data correction)."""
    case_id = message.get("case_id")
    if not case_id:
        logger.error("revalidate_missing_case_id")
        return

    result = await session.execute(
        select(OnboardingCase).where(OnboardingCase.id == uuid.UUID(case_id))
    )
    case = result.scalar_one_or_none()
    if not case:
        logger.error("revalidate_case_not_found", case_id=case_id)
        return

    if case.status != CaseStatus.BLOCKED_VALIDATION:
        logger.warning("revalidate_wrong_status", status=case.status.value)
        return

    # Transition back to VALIDATING
    await transition_case(session, case, CaseStatus.VALIDATING, actor_type="system", reason="revalidation_requested")

    # Re-build canonical record from case fields
    canonical = CanonicalHireRecord(
        external_hire_id=case.external_hire_id or "",
        source_system=case.source_system,
        employee_email=case.employee_email,
        employee_full_name=case.employee_full_name,
        country_code=case.country_code,
        hiring_entity_type=case.hiring_entity_type,
        start_date=case.start_date,
        manager_email=case.manager_email,
        department=case.department,
        job_title=case.job_title,
    )

    outcome = validate_hire(canonical)

    for r in outcome.results:
        vr = ValidationResult(
            id=uuid.uuid4(),
            case_id=case.id,
            validation_type=r.validation_type,
            field_name=r.field_name,
            severity=r.severity,
            result=r.result,
            message=r.message,
        )
        session.add(vr)

    if outcome.passed:
        await transition_case(session, case, CaseStatus.READY_FOR_REMOTE, actor_type="system", reason="revalidation_passed")
        sync_task = SyncTask(
            id=uuid.uuid4(),
            case_id=case.id,
            task_type="remote_create_employment",
            target_system=TargetSystem.REMOTE,
            status=SyncTaskStatus.PENDING,
            idempotency_key=generate_idempotency_key("remote_create", case.workflow_id, canonical.employee_email),
        )
        session.add(sync_task)
    else:
        await transition_case(session, case, CaseStatus.BLOCKED_VALIDATION, actor_type="system", reason="revalidation_still_failing")

    logger.info("revalidation_complete", workflow_id=case.workflow_id, passed=outcome.passed)


async def _handle_remote_event(session: AsyncSession, message: dict, correlation_id: str) -> None:
    """Process a Remote webhook event — update internal state based on lifecycle changes."""
    event_type = message.get("event_type", "")
    resource_id = message.get("resource_id", "")

    result = await session.execute(
        select(OnboardingCase).where(OnboardingCase.remote_employment_id == resource_id)
    )
    case = result.scalar_one_or_none()
    if not case:
        logger.warning("remote_event_no_case", resource_id=resource_id, event_type=event_type)
        return

    # Map Remote events to state transitions
    if event_type == "employment.user_status.invited":
        if case.status == CaseStatus.REMOTE_SYNC_IN_PROGRESS:
            await transition_case(session, case, CaseStatus.REMOTE_INVITED, actor_type="webhook", actor_id="remote", reason=event_type)

    elif event_type == "employment.onboarding_task.completed":
        if case.status in (CaseStatus.REMOTE_INVITED, CaseStatus.WAITING_ON_EMPLOYEE):
            await transition_case(session, case, CaseStatus.REMOTE_ONBOARDING_IN_PROGRESS, actor_type="webhook", actor_id="remote", reason=event_type)

    elif event_type == "employment.onboarding.completed":
        if case.status in (CaseStatus.REMOTE_ONBOARDING_IN_PROGRESS, CaseStatus.WAITING_ON_EMPLOYEE):
            await transition_case(session, case, CaseStatus.COMPLETED, actor_type="webhook", actor_id="remote", reason=event_type)

    elif event_type == "employment.start_date.changed":
        new_date = message.get("payload", {}).get("new_start_date")
        if new_date:
            from app.services.normalizer import parse_date_flexible
            case.start_date = parse_date_flexible(new_date)
            session.add(case)
            await write_audit(
                session, case.id, "start_date_changed",
                actor_type="webhook", actor_id="remote",
                after={"new_start_date": new_date},
            )

    # Persist the raw event
    event_record = OnboardingEvent(
        id=uuid.uuid4(),
        case_id=case.id,
        event_type=f"remote.{event_type}",
        source_system="REMOTE",
        source_event_id=message.get("event_id"),
        payload_json=json.dumps(message.get("payload", {})),
        received_at=datetime.now(timezone.utc),
        processed_at=datetime.now(timezone.utc),
        processing_result="success",
    )
    session.add(event_record)

    logger.info("remote_event_processed", workflow_id=case.workflow_id, event_type=event_type)


async def _handle_notion_event(session: AsyncSession, message: dict, correlation_id: str) -> None:
    """Process a Notion webhook event — update legal review status."""
    page_id = message.get("page_id", "")

    result = await session.execute(
        select(OnboardingCase).where(OnboardingCase.notion_page_id == page_id)
    )
    case = result.scalar_one_or_none()
    if not case:
        logger.warning("notion_event_no_case", page_id=page_id)
        return

    # Notion webhooks are change signals — the actual status should be fetched via API
    # For now, log the event and mark for follow-up
    event_record = OnboardingEvent(
        id=uuid.uuid4(),
        case_id=case.id,
        event_type="notion.page_updated",
        source_system="NOTION",
        payload_json=json.dumps(message.get("payload", {})),
        received_at=datetime.now(timezone.utc),
        processed_at=datetime.now(timezone.utc),
        processing_result="success",
    )
    session.add(event_record)

    # Schedule a Notion fetch task to get the latest status
    fetch_task = SyncTask(
        id=uuid.uuid4(),
        case_id=case.id,
        task_type="notion_fetch_status",
        target_system=TargetSystem.NOTION,
        status=SyncTaskStatus.PENDING,
        idempotency_key=generate_idempotency_key("notion_fetch", case.workflow_id, page_id),
    )
    session.add(fetch_task)

    logger.info("notion_event_processed", workflow_id=case.workflow_id, page_id=page_id)
