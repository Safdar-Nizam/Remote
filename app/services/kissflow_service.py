"""
Kissflow outbound service — pushes milestone status updates back to Kissflow.
"""

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


async def push_status_to_kissflow(
    external_hire_id: str,
    status: str,
    substatus: str | None = None,
    owner: str | None = None,
    notes: str | None = None,
    validation_errors: list[str] | None = None,
) -> bool:
    """
    Push a status update back to Kissflow via HTTP connector.
    This would typically POST to a Kissflow webhook or API endpoint
    configured to update the hire record.
    
    Returns True if the update was acknowledged, False otherwise.
    """
    settings = get_settings()

    # Kissflow outbound URL would be configured per deployment
    # Placeholder: in production, this would be the Kissflow API or webhook URL
    kissflow_update_url = f"https://your-kissflow-instance.kissflow.com/api/1/update"

    payload = {
        "record_id": external_hire_id,
        "orchestrator_status": status,
        "orchestrator_substatus": substatus,
        "assigned_owner": owner,
        "notes": notes,
    }

    if validation_errors:
        payload["validation_errors"] = "; ".join(validation_errors[:5])

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                kissflow_update_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()

        logger.info("kissflow_status_pushed", hire_id=external_hire_id, status=status)
        return True

    except httpx.HTTPStatusError as e:
        logger.error("kissflow_push_http_error", status=e.response.status_code, hire_id=external_hire_id)
        return False
    except httpx.RequestError as e:
        logger.error("kissflow_push_error", error=str(e), hire_id=external_hire_id)
        return False
