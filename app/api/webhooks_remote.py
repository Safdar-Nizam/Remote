"""
Remote webhook endpoint.
Receives employment lifecycle events from Remote.
"""

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.core.config import Settings, get_settings
from app.core.correlation import get_correlation_id
from app.core.logging import get_logger
from app.core.security import verify_webhook_signature
from app.dependencies import get_queue

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = get_logger(__name__)


@router.post("/remote", status_code=status.HTTP_202_ACCEPTED)
async def receive_remote_webhook(
    request: Request,
    x_remote_signature: str | None = Header(default=None, alias="X-Remote-Signature"),
    settings: Settings = Depends(get_settings),
    queue=Depends(get_queue),
):
    """
    Receive a Remote webhook event.
    Remote sends event_type + resource_id; full data is fetched later via API.
    """
    body = await request.body()
    payload = await request.json()

    # Signature verification
    if settings.remote_webhook_secret:
        if not verify_webhook_signature(body, x_remote_signature or "", settings.remote_webhook_secret):
            logger.warning("remote_invalid_signature")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    event_type = payload.get("event_type", "")
    resource_id = payload.get("resource_id", "")
    correlation_id = get_correlation_id()

    message = {
        "action": "process_remote_event",
        "source_system": "REMOTE",
        "event_type": event_type,
        "resource_id": resource_id,
        "event_id": str(uuid.uuid4()),
        "correlation_id": correlation_id,
        "payload": payload,
    }
    await queue.send_message(message)

    logger.info("remote_webhook_accepted", event_type=event_type, resource_id=resource_id)
    return {"status": "accepted", "correlation_id": correlation_id}
