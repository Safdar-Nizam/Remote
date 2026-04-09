"""
Notion webhook endpoint.
Receives change signals from Notion database automations.
"""

import uuid

from fastapi import APIRouter, Depends, Request, status

from app.core.correlation import get_correlation_id
from app.core.logging import get_logger
from app.dependencies import get_queue

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = get_logger(__name__)


@router.post("/notion", status_code=status.HTTP_202_ACCEPTED)
async def receive_notion_webhook(
    request: Request,
    queue=Depends(get_queue),
):
    """
    Receive a Notion webhook event (change signal).
    Notion's webhooks only signal that something changed —
    the worker must fetch the full page via API after receiving this.
    """
    payload = await request.json()
    correlation_id = get_correlation_id()

    page_id = payload.get("page_id", "")
    event_type = payload.get("event_type", "page.updated")

    message = {
        "action": "process_notion_event",
        "source_system": "NOTION",
        "event_type": event_type,
        "page_id": page_id,
        "event_id": str(uuid.uuid4()),
        "correlation_id": correlation_id,
        "payload": payload,
    }
    await queue.send_message(message)

    logger.info("notion_webhook_accepted", event_type=event_type, page_id=page_id)
    return {"status": "accepted", "correlation_id": correlation_id}
