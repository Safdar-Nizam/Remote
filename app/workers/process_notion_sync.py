"""
Notion sync worker — creates and updates legal tracker items in Notion.
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
from app.services.state_machine import transition_case, write_audit

logger = get_logger(__name__)


async def call_notion_api(method: str, path: str, body: dict | None = None) -> dict:
    """Make an authenticated call to the Notion API."""
    settings = get_settings()
    url = f"https://api.notion.com/v1{path}"

    headers = {
        "Authorization": f"Bearer {settings.notion_api_token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(method, url, json=body, headers=headers)
        if response.status_code >= 400:
            logger.error("notion_api_error", status=response.status_code, body=response.text[:500])
            response.raise_for_status()
        return response.json() if response.content else {}


async def create_legal_tracker_item(case: OnboardingCase, issue_summary: str = "") -> str | None:
    """
    Create a page in the Notion legal tracker database.
    Returns the Notion page ID on success.
    """
    settings = get_settings()
    if not settings.notion_api_token or not settings.notion_legal_db_id:
        logger.warning("notion_not_configured")
        return None

    properties = {
        "Employee Name": {"title": [{"text": {"content": case.employee_full_name}}]},
        "Email": {"email": case.employee_email},
        "Country": {"rich_text": [{"text": {"content": case.country_code}}]},
        "Issue Type": {"select": {"name": "Agreement Edit"}},
        "Status": {"select": {"name": "Open"}},
        "Priority": {"select": {"name": "Medium"}},
        "Case ID": {"rich_text": [{"text": {"content": case.workflow_id}}]},
    }

    if issue_summary:
        properties["Summary"] = {"rich_text": [{"text": {"content": issue_summary[:2000]}}]}

    body = {
        "parent": {"database_id": settings.notion_legal_db_id},
        "properties": properties,
    }

    response = await call_notion_api("POST", "/pages", body=body)
    page_id = response.get("id")
    logger.info("notion_page_created", page_id=page_id, workflow_id=case.workflow_id)
    return page_id


async def update_legal_tracker_status(page_id: str, status: str, notes: str | None = None) -> None:
    """Update the status of a Notion legal tracker page."""
    properties: dict = {
        "Status": {"select": {"name": status}},
    }
    if notes:
        properties["Legal Notes"] = {"rich_text": [{"text": {"content": notes[:2000]}}]}

    await call_notion_api("PATCH", f"/pages/{page_id}", body={"properties": properties})
    logger.info("notion_page_updated", page_id=page_id, status=status)


async def fetch_legal_tracker_status(page_id: str) -> dict:
    """Fetch the current state of a Notion legal tracker page."""
    response = await call_notion_api("GET", f"/pages/{page_id}")
    props = response.get("properties", {})

    status_prop = props.get("Status", {}).get("select", {})
    notes_prop = props.get("Legal Notes", {}).get("rich_text", [])

    return {
        "status": status_prop.get("name", "unknown"),
        "legal_notes": notes_prop[0].get("text", {}).get("content", "") if notes_prop else "",
        "last_edited": response.get("last_edited_time"),
    }


async def process_notion_sync(case_id: str, task_id: str) -> None:
    """Execute a Notion sync task — create or update legal tracker items."""
    async with async_session_factory() as session:
        try:
            case_result = await session.execute(
                select(OnboardingCase).where(OnboardingCase.id == uuid.UUID(case_id))
            )
            case = case_result.scalar_one_or_none()
            if not case:
                logger.error("notion_sync_case_not_found", case_id=case_id)
                return

            task_result = await session.execute(
                select(SyncTask).where(SyncTask.id == uuid.UUID(task_id))
            )
            task = task_result.scalar_one_or_none()
            if not task:
                return

            if task.status == SyncTaskStatus.COMPLETED:
                return

            task.status = SyncTaskStatus.IN_PROGRESS
            task.last_attempt_at = datetime.now(timezone.utc)
            session.add(task)

            if task.task_type == "notion_create_legal_item":
                page_id = await create_legal_tracker_item(case)
                if page_id:
                    case.notion_page_id = page_id
                    task.status = SyncTaskStatus.COMPLETED
                    task.target_object_id = page_id
                    session.add(case)

                    # Transition to LEGAL_REVIEW_REQUIRED if appropriate
                    if case.status in (
                        CaseStatus.READY_FOR_REMOTE,
                        CaseStatus.REMOTE_ONBOARDING_IN_PROGRESS,
                    ):
                        await transition_case(
                            session, case, CaseStatus.LEGAL_REVIEW_REQUIRED,
                            actor_type="system", reason="legal_tracker_created",
                        )
                else:
                    task.status = SyncTaskStatus.FAILED_RETRYABLE
                    task.last_error = "notion_not_configured_or_failed"

            elif task.task_type == "notion_fetch_status":
                if case.notion_page_id:
                    status_data = await fetch_legal_tracker_status(case.notion_page_id)
                    task.status = SyncTaskStatus.COMPLETED

                    await write_audit(
                        session, case.id, "notion_status_fetched",
                        actor_type="system",
                        after=status_data,
                    )

                    # If legal resolved, allow case to progress
                    if status_data.get("status", "").lower() in ("resolved", "approved", "done"):
                        if case.status in (CaseStatus.LEGAL_REVIEW_REQUIRED, CaseStatus.PENDING_CONTRACT_ACTION):
                            await transition_case(
                                session, case, CaseStatus.PENDING_CONTRACT_ACTION,
                                actor_type="system", reason="legal_review_resolved",
                            )

            session.add(task)
            await session.commit()
            logger.info("notion_sync_complete", workflow_id=case.workflow_id, task_type=task.task_type)

        except Exception as e:
            await session.rollback()
            logger.error("notion_sync_error", case_id=case_id, error=str(e), exc_info=True)
            raise
