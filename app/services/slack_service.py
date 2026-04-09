"""
Slack Service — sends structured notifications via Slack incoming webhooks.
Handles deduplication, threading, and severity-based formatting.
"""

import hashlib

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.slack import SlackNotification, build_slack_blocks

logger = get_logger(__name__)

# Track recently sent notification hashes to avoid duplicates within a session
_recent_hashes: set[str] = set()
MAX_HASH_CACHE = 500


def _notification_hash(notification: SlackNotification) -> str:
    """Generate a hash of the notification content for deduplication."""
    content = f"{notification.case_workflow_id}|{notification.notification_type}|{notification.summary}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


async def send_slack_notification(notification: SlackNotification) -> bool:
    """
    Send a Slack notification via incoming webhook.
    Returns True if sent successfully, False otherwise.
    Deduplicates within the current process lifetime.
    """
    settings = get_settings()

    if not settings.slack_webhook_url:
        logger.warning("slack_not_configured", case=notification.case_workflow_id)
        return False

    # Dedup check
    msg_hash = _notification_hash(notification)
    if msg_hash in _recent_hashes:
        logger.info("slack_dedup_skipped", case=notification.case_workflow_id, type=notification.notification_type)
        return True

    # Build payload
    payload = build_slack_blocks(notification)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(settings.slack_webhook_url, json=payload)
            response.raise_for_status()

        # Track for dedup
        _recent_hashes.add(msg_hash)
        if len(_recent_hashes) > MAX_HASH_CACHE:
            _recent_hashes.clear()

        logger.info(
            "slack_sent",
            case=notification.case_workflow_id,
            type=notification.notification_type,
            severity=notification.severity,
        )
        return True

    except httpx.HTTPStatusError as e:
        logger.error("slack_http_error", status=e.response.status_code, detail=str(e))
        return False
    except httpx.RequestError as e:
        logger.error("slack_request_error", error=str(e))
        return False


# ──────────────────────────────────────────────
# Convenience builders for common notification types
# ──────────────────────────────────────────────

def build_case_created_notification(
    workflow_id: str,
    employee_name: str,
    country_code: str,
    source_system: str,
) -> SlackNotification:
    return SlackNotification(
        notification_type="case_created",
        case_workflow_id=workflow_id,
        employee_name=employee_name,
        summary=f"New onboarding case received from {source_system}",
        details=[
            f"Country: {country_code}",
            f"Source: {source_system}",
        ],
        severity="low",
    )


def build_validation_blocked_notification(
    workflow_id: str,
    employee_name: str,
    errors: list[str],
    owner: str | None = None,
    sla_deadline: str | None = None,
) -> SlackNotification:
    return SlackNotification(
        notification_type="validation_blocked",
        case_workflow_id=workflow_id,
        employee_name=employee_name,
        summary="⚠️ Validation failed — manual review required",
        details=errors[:10],  # Cap at 10 error lines
        severity="high",
        owner=owner,
        sla_deadline=sla_deadline,
    )


def build_remote_sync_failed_notification(
    workflow_id: str,
    employee_name: str,
    error: str,
) -> SlackNotification:
    return SlackNotification(
        notification_type="remote_sync_failed",
        case_workflow_id=workflow_id,
        employee_name=employee_name,
        summary="Remote sync failed",
        details=[error],
        severity="high",
    )


def build_case_completed_notification(
    workflow_id: str,
    employee_name: str,
    country_code: str,
) -> SlackNotification:
    return SlackNotification(
        notification_type="case_completed",
        case_workflow_id=workflow_id,
        employee_name=employee_name,
        summary=f"✅ Onboarding complete for {employee_name} ({country_code})",
        severity="low",
    )


def build_legal_review_notification(
    workflow_id: str,
    employee_name: str,
    issue_type: str,
    sla_deadline: str | None = None,
) -> SlackNotification:
    return SlackNotification(
        notification_type="legal_review_required",
        case_workflow_id=workflow_id,
        employee_name=employee_name,
        summary=f"📋 Legal review needed: {issue_type}",
        details=[f"Issue: {issue_type}", "A Notion legal tracker item has been created."],
        severity="medium",
        sla_deadline=sla_deadline,
    )


def build_escalation_notification(
    workflow_id: str,
    employee_name: str,
    escalation_type: str,
    owner: str | None = None,
    severity: str = "high",
    sla_deadline: str | None = None,
) -> SlackNotification:
    return SlackNotification(
        notification_type="escalation",
        case_workflow_id=workflow_id,
        employee_name=employee_name,
        summary=f"🚨 Escalation: {escalation_type}",
        details=[f"Type: {escalation_type}"],
        severity=severity,
        owner=owner,
        sla_deadline=sla_deadline,
    )
