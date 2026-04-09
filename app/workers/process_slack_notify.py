"""
Slack notification worker — sends queued Slack messages.
Thin wrapper used when notifications are dispatched via the queue.
"""

from app.core.logging import get_logger
from app.schemas.slack import SlackNotification
from app.services.slack_service import send_slack_notification

logger = get_logger(__name__)


async def process_slack_notify(message_body: dict) -> None:
    """
    Process a queued Slack notification message.
    Message body should contain all fields needed to build a SlackNotification.
    """
    try:
        notification = SlackNotification(**message_body)
        success = await send_slack_notification(notification)
        if not success:
            logger.warning("slack_notify_failed", case=notification.case_workflow_id)
    except Exception as e:
        logger.error("slack_notify_error", error=str(e), exc_info=True)
        raise
