"""
Idempotency key generation and tracking.
Ensures that replayed or retried operations do not cause duplicate side effects.
"""

import hashlib
import uuid


def generate_idempotency_key(*parts: str) -> str:
    """
    Generate a deterministic idempotency key from component parts.
    Example: generate_idempotency_key("remote_create", case.workflow_id, case.employee_email)
    """
    combined = "|".join(str(p) for p in parts)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:32]


def generate_workflow_id(sequence: int | None = None) -> str:
    """
    Generate a human-friendly workflow ID.
    Format: ONB-{short_uuid} or ONB-{sequence} if sequence counter is available.
    """
    if sequence is not None:
        return f"ONB-{sequence:06d}"
    short = uuid.uuid4().hex[:8].upper()
    return f"ONB-{short}"
