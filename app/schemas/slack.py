"""
Slack message schemas — Block Kit message builders for different notification types.
"""

from pydantic import BaseModel, Field


class SlackNotification(BaseModel):
    """
    A structured Slack notification ready to be posted via incoming webhook.
    """
    channel: str | None = None             # Override channel (optional with incoming webhooks)
    thread_ts: str | None = None           # Reply in thread if set
    notification_type: str                 # e.g. "case_created", "validation_blocked", "escalation"
    case_workflow_id: str
    employee_name: str
    summary: str                           # One-line summary
    details: list[str] = Field(default_factory=list)  # Bullet points
    severity: str = "low"                  # "low", "medium", "high", "critical"
    owner: str | None = None
    sla_deadline: str | None = None
    action_url: str | None = None          # Link to admin console


def build_slack_blocks(notification: SlackNotification) -> dict:
    """
    Build a Slack Block Kit message payload from a SlackNotification.
    Returns the JSON body to POST to a Slack webhook URL.
    """
    severity_emoji = {
        "low": "🟢",
        "medium": "🟡",
        "high": "🟠",
        "critical": "🔴",
    }

    emoji = severity_emoji.get(notification.severity, "⚪")

    header_text = f"{emoji}  *{notification.notification_type.replace('_', ' ').title()}*  |  `{notification.case_workflow_id}`"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{emoji} {notification.notification_type.replace('_', ' ').title()}", "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Employee:*\n{notification.employee_name}"},
                {"type": "mrkdwn", "text": f"*Case:*\n`{notification.case_workflow_id}`"},
                {"type": "mrkdwn", "text": f"*Severity:*\n{emoji} {notification.severity.upper()}"},
                {"type": "mrkdwn", "text": f"*Owner:*\n{notification.owner or '_unassigned_'}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": notification.summary},
        },
    ]

    # Add detail bullets if present
    if notification.details:
        detail_text = "\n".join(f"• {d}" for d in notification.details)
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": detail_text},
        })

    # SLA deadline
    if notification.sla_deadline:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"⏰ *SLA Deadline:* {notification.sla_deadline}"}],
        })

    # Action button
    if notification.action_url:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Case", "emoji": True},
                    "url": notification.action_url,
                    "style": "primary",
                },
            ],
        })

    blocks.append({"type": "divider"})

    payload: dict = {"blocks": blocks}
    if notification.channel:
        payload["channel"] = notification.channel
    if notification.thread_ts:
        payload["thread_ts"] = notification.thread_ts

    return payload
