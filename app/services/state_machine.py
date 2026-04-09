"""
State Machine — defines valid transitions, guards, and audit hooks for the onboarding workflow.
This is the ONLY way case status should ever change.
"""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.audit_log import AuditLog
from app.models.onboarding_case import CaseStatus, OnboardingCase

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Transition definitions
# ──────────────────────────────────────────────

# Map: (from_status) → set of allowed (to_status) values
ALLOWED_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.RECEIVED: {
        CaseStatus.NORMALIZING,
        CaseStatus.VALIDATING,
        CaseStatus.CANCELLED,
    },
    CaseStatus.NORMALIZING: {
        CaseStatus.VALIDATING,
        CaseStatus.BLOCKED_VALIDATION,
        CaseStatus.FAILED_TERMINAL,
    },
    CaseStatus.VALIDATING: {
        CaseStatus.BLOCKED_VALIDATION,
        CaseStatus.READY_FOR_REMOTE,
        CaseStatus.FAILED_TERMINAL,
    },
    CaseStatus.BLOCKED_VALIDATION: {
        CaseStatus.VALIDATING,      # Re-validate after data correction
        CaseStatus.CANCELLED,
        CaseStatus.ESCALATED,
    },
    CaseStatus.READY_FOR_REMOTE: {
        CaseStatus.REMOTE_SYNC_IN_PROGRESS,
        CaseStatus.CANCELLED,
    },
    CaseStatus.REMOTE_SYNC_IN_PROGRESS: {
        CaseStatus.REMOTE_INVITED,
        CaseStatus.BLOCKED_VALIDATION,   # Non-retryable sync error
        CaseStatus.FAILED_TERMINAL,
        CaseStatus.ESCALATED,
    },
    CaseStatus.REMOTE_INVITED: {
        CaseStatus.REMOTE_ONBOARDING_IN_PROGRESS,
        CaseStatus.WAITING_ON_EMPLOYEE,
        CaseStatus.ESCALATED,
    },
    CaseStatus.REMOTE_ONBOARDING_IN_PROGRESS: {
        CaseStatus.WAITING_ON_EMPLOYEE,
        CaseStatus.LEGAL_REVIEW_REQUIRED,
        CaseStatus.PENDING_DOCUMENTS,
        CaseStatus.COMPLETED,
        CaseStatus.ESCALATED,
    },
    CaseStatus.PENDING_DOCUMENTS: {
        CaseStatus.REMOTE_ONBOARDING_IN_PROGRESS,
        CaseStatus.ESCALATED,
    },
    CaseStatus.PENDING_CONTRACT_ACTION: {
        CaseStatus.REMOTE_ONBOARDING_IN_PROGRESS,
        CaseStatus.WAITING_ON_EMPLOYEE,
        CaseStatus.ESCALATED,
    },
    CaseStatus.LEGAL_REVIEW_REQUIRED: {
        CaseStatus.PENDING_CONTRACT_ACTION,
        CaseStatus.ESCALATED,
    },
    CaseStatus.WAITING_ON_EMPLOYEE: {
        CaseStatus.COMPLETED,
        CaseStatus.REMOTE_ONBOARDING_IN_PROGRESS,
        CaseStatus.ESCALATED,
    },
    CaseStatus.WAITING_ON_INTERNAL_OWNER: {
        CaseStatus.VALIDATING,
        CaseStatus.REMOTE_SYNC_IN_PROGRESS,
        CaseStatus.CANCELLED,
        CaseStatus.ESCALATED,
    },
    CaseStatus.ESCALATED: {
        # Escalated cases can return to most operational states after resolution
        CaseStatus.VALIDATING,
        CaseStatus.READY_FOR_REMOTE,
        CaseStatus.REMOTE_SYNC_IN_PROGRESS,
        CaseStatus.REMOTE_ONBOARDING_IN_PROGRESS,
        CaseStatus.CANCELLED,
        CaseStatus.FAILED_TERMINAL,
    },
}

# Terminal states — no further transitions allowed
TERMINAL_STATES: set[CaseStatus] = {
    CaseStatus.COMPLETED,
    CaseStatus.CANCELLED,
    CaseStatus.FAILED_TERMINAL,
}


# ──────────────────────────────────────────────
# Transition logic
# ──────────────────────────────────────────────

class TransitionError(Exception):
    """Raised when a state transition is invalid."""
    def __init__(self, from_status: CaseStatus, to_status: CaseStatus, reason: str):
        self.from_status = from_status
        self.to_status = to_status
        self.reason = reason
        super().__init__(f"Cannot transition from {from_status} to {to_status}: {reason}")


def can_transition(from_status: CaseStatus, to_status: CaseStatus) -> bool:
    """Check whether a transition is allowed."""
    if from_status in TERMINAL_STATES:
        return False
    allowed = ALLOWED_TRANSITIONS.get(from_status, set())
    return to_status in allowed


async def transition_case(
    session: AsyncSession,
    case: OnboardingCase,
    new_status: CaseStatus,
    actor_type: str = "system",
    actor_id: str | None = None,
    reason: str = "",
    substatus: str | None = None,
) -> OnboardingCase:
    """
    Execute a state transition on a case.
    - Validates the transition is allowed
    - Updates case status
    - Writes an immutable audit log entry
    - Sets completed_at if entering a terminal state
    
    This is the ONLY function that should change case.status.
    """
    old_status = case.status

    if not can_transition(old_status, new_status):
        raise TransitionError(
            old_status,
            new_status,
            f"Transition not defined. Allowed from {old_status}: {ALLOWED_TRANSITIONS.get(old_status, set())}",
        )

    # Capture before state for audit
    before_snapshot = {
        "status": old_status.value,
        "substatus": case.substatus,
        "owner_user_id": case.owner_user_id,
    }

    # Update case
    case.status = new_status
    if substatus is not None:
        case.substatus = substatus
    case.updated_at = datetime.now(timezone.utc)

    # Set completion timestamp for terminal states
    if new_status in TERMINAL_STATES:
        case.completed_at = datetime.now(timezone.utc)

    # Capture after state
    after_snapshot = {
        "status": new_status.value,
        "substatus": case.substatus,
        "owner_user_id": case.owner_user_id,
    }

    # Write audit log
    audit = AuditLog(
        id=uuid.uuid4(),
        case_id=case.id,
        actor_type=actor_type,
        actor_id=actor_id,
        action="state_transition",
        before_json=json.dumps(before_snapshot),
        after_json=json.dumps({**after_snapshot, "reason": reason}),
    )
    session.add(audit)
    session.add(case)

    logger.info(
        "state_transition",
        workflow_id=case.workflow_id,
        from_status=old_status.value,
        to_status=new_status.value,
        actor_type=actor_type,
        actor_id=actor_id,
        reason=reason,
    )

    return case


async def write_audit(
    session: AsyncSession,
    case_id: uuid.UUID,
    action: str,
    actor_type: str = "system",
    actor_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> AuditLog:
    """Write a generic audit log entry (not just state transitions)."""
    audit = AuditLog(
        id=uuid.uuid4(),
        case_id=case_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        before_json=json.dumps(before) if before else None,
        after_json=json.dumps(after) if after else None,
    )
    session.add(audit)
    return audit
