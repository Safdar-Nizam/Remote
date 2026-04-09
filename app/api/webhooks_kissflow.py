"""
Kissflow webhook endpoint.
Receives new hire created/updated events, validates signature,
persists raw payload, and enqueues for async processing.
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


@router.post("/kissflow", status_code=status.HTTP_202_ACCEPTED)
async def receive_kissflow_webhook(
    request: Request,
    x_kissflow_signature: str | None = Header(default=None, alias="X-Kissflow-Signature"),
    settings: Settings = Depends(get_settings),
    queue=Depends(get_queue),
):
    """
    Receive a Kissflow webhook event.
    - Verifies signature (if configured)
    - Returns 202 Accepted immediately
    - Enqueues payload for async processing
    """
    body = await request.body()
    payload = await request.json()

    # ── Signature verification ──
    if settings.kissflow_webhook_secret:
        if not verify_webhook_signature(body, x_kissflow_signature or "", settings.kissflow_webhook_secret):
            logger.warning("kissflow_invalid_signature")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    # ── Extract event metadata ──
    event_type = payload.get("event_type", "hire_created")
    event_id = payload.get("event_id") or str(uuid.uuid4())

    correlation_id = get_correlation_id()

    # ── Enqueue for async processing ──
    message = {
        "action": "process_new_hire",
        "source_system": "KISSFLOW",
        "event_type": event_type,
        "event_id": event_id,
        "correlation_id": correlation_id,
        "payload": payload.get("data", payload),
    }
    await queue.send_message(message, dedup_id=event_id)

    logger.info("kissflow_webhook_accepted", event_type=event_type, event_id=event_id)
    return {"status": "accepted", "event_id": event_id, "correlation_id": correlation_id}
