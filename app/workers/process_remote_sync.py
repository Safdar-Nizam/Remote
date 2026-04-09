"""
Remote sync worker — handles creating/updating employments in Remote
and triggering invites when records are validation-clean.
"""

import json
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.models.onboarding_case import CaseStatus, OnboardingCase
from app.models.sync_task import SyncTask, SyncTaskStatus
from app.services.slack_service import build_remote_sync_failed_notification, send_slack_notification
from app.services.state_machine import transition_case, write_audit

logger = get_logger(__name__)


class RemoteAPIError(Exception):
    """Error from Remote API."""
    def __init__(self, status_code: int, detail: str, retryable: bool = True):
        self.status_code = status_code
        self.detail = detail
        self.retryable = retryable
        super().__init__(f"Remote API {status_code}: {detail}")


async def call_remote_api(
    method: str,
    path: str,
    body: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Make an authenticated call to the Remote API."""
    settings = get_settings()
    url = f"{settings.remote_api_base_url}{path}"

    headers = {
        "Authorization": f"Bearer {settings.remote_api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(method, url, json=body, headers=headers)

        if response.status_code == 429:
            raise RemoteAPIError(429, "Rate limited", retryable=True)
        elif response.status_code >= 500:
            raise RemoteAPIError(response.status_code, response.text[:500], retryable=True)
        elif response.status_code >= 400:
            raise RemoteAPIError(response.status_code, response.text[:500], retryable=False)

        return response.json() if response.content else {}


async def process_remote_sync(case_id: str, task_id: str) -> None:
    """
    Execute a Remote sync task.
    Called by the worker when a remote sync task is pending.
    """
    async with async_session_factory() as session:
        try:
            case_result = await session.execute(
                select(OnboardingCase).where(OnboardingCase.id == uuid.UUID(case_id))
            )
            case = case_result.scalar_one_or_none()
            if not case:
                logger.error("remote_sync_case_not_found", case_id=case_id)
                return

            task_result = await session.execute(
                select(SyncTask).where(SyncTask.id == uuid.UUID(task_id))
            )
            task = task_result.scalar_one_or_none()
            if not task:
                logger.error("remote_sync_task_not_found", task_id=task_id)
                return

            # Skip if already completed (idempotency)
            if task.status == SyncTaskStatus.COMPLETED:
                logger.info("remote_sync_already_completed", task_id=task_id)
                return

            task.status = SyncTaskStatus.IN_PROGRESS
            task.last_attempt_at = datetime.now(timezone.utc)
            session.add(task)

            # Transition case to REMOTE_SYNC_IN_PROGRESS
            if case.status == CaseStatus.READY_FOR_REMOTE:
                await transition_case(
                    session, case, CaseStatus.REMOTE_SYNC_IN_PROGRESS,
                    actor_type="system", reason="remote_sync_started",
                )

            # ── Create employment in Remote ──
            employment_body = {
                "country_code": case.country_code,
                "full_name": case.employee_full_name,
                "job_title": case.job_title or "TBD",
                "personal_email": case.employee_email,
                "type": "employee",
            }
            if case.start_date:
                employment_body["provisional_start_date"] = case.start_date.isoformat()

            response = await call_remote_api(
                "POST", "/employments",
                body=employment_body,
                idempotency_key=task.idempotency_key,
            )

            remote_id = response.get("data", {}).get("id") or response.get("id", "")

            # Update case with Remote employment ID
            case.remote_employment_id = remote_id
            session.add(case)

            # Mark task complete
            task.status = SyncTaskStatus.COMPLETED
            task.target_object_id = remote_id
            session.add(task)

            await write_audit(
                session, case.id, "remote_employment_created",
                actor_type="system",
                after={"remote_employment_id": remote_id},
            )

            # Transition to REMOTE_INVITED (Remote auto-invites in many flows)
            await transition_case(
                session, case, CaseStatus.REMOTE_INVITED,
                actor_type="system", reason="employment_created_in_remote",
            )

            await session.commit()
            logger.info("remote_sync_success", workflow_id=case.workflow_id, remote_id=remote_id)

        except RemoteAPIError as e:
            await session.rollback()
            async with async_session_factory() as err_session:
                task_r = await err_session.execute(select(SyncTask).where(SyncTask.id == uuid.UUID(task_id)))
                task = task_r.scalar_one_or_none()
                case_r = await err_session.execute(select(OnboardingCase).where(OnboardingCase.id == uuid.UUID(case_id)))
                case = case_r.scalar_one_or_none()

                if task:
                    task.retry_count += 1
                    task.last_error = str(e)
                    task.status = SyncTaskStatus.FAILED_RETRYABLE if e.retryable else SyncTaskStatus.FAILED_TERMINAL
                    err_session.add(task)

                if case and not e.retryable:
                    notification = build_remote_sync_failed_notification(
                        case.workflow_id, case.employee_full_name, str(e),
                    )
                    await send_slack_notification(notification)

                await err_session.commit()

            logger.error("remote_sync_failed", case_id=case_id, error=str(e), retryable=e.retryable)
            if e.retryable:
                raise  # Let queue retry

        except Exception as e:
            await session.rollback()
            logger.error("remote_sync_unexpected_error", case_id=case_id, error=str(e), exc_info=True)
            raise
