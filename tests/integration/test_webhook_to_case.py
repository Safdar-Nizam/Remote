"""
Integration tests for the webhook-to-case lifecycle.
Verifies the full path: HTTP Request -> Enqueue -> Worker -> DB -> Side Effects.
"""

import json
import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onboarding_case import CaseStatus, OnboardingCase
from app.models.onboarding_event import OnboardingEvent
from app.models.sync_task import SyncTask, SyncTaskStatus
from app.models.validation_result import ValidationResult
from app.workers.process_case import process_case_message


# ──────────────────────────────────────────────
# Test 1: Happy-path — full hire lifecycle
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_onboarding_flow(client: AsyncClient, test_db: AsyncSession):
    """
    Test the full onboarding flow from webhook to ready state.
    1. Send a Kissflow webhook
    2. Directly trigger the worker (to avoid reliance on async loop timing)
    3. Verify DB state
    """
    # ── 1. Mock Webhook Receipt ──
    external_id = f"KF-{uuid.uuid4().hex[:6]}"
    payload = {
        "event_type": "hire_created",
        "event_id": str(uuid.uuid4()),
        "data": {
            "id": external_id,
            "employee_email": "integration.test@example.com",
            "employee_full_name": "Integration Test User",
            "country": "US",
            "start_date": (date.today() + timedelta(days=14)).isoformat(),
            "manager_email": "manager@example.com",
            "job_title": "Quality Engineer",
            "contract_edit_requested": False,
        }
    }

    response = await client.post("/webhooks/kissflow", json=payload)
    assert response.status_code == 202

    # ── 2. Manually trigger worker ──
    # The webhook endpoint enqueues a message. We pick it up and process it.
    from app.dependencies import get_queue
    queue = get_queue()
    msg = await queue.receive_message()
    assert msg is not None

    await process_case_message(msg.body)

    # ── 3. Verify Database State ──
    # Check OnboardingCase existence
    result = await test_db.execute(
        select(OnboardingCase).where(OnboardingCase.external_hire_id == external_id)
    )
    case = result.scalar_one_or_none()
    assert case is not None
    assert case.status == CaseStatus.READY_FOR_REMOTE
    assert case.employee_full_name == "Integration Test User"

    # Check Remote Sync Task creation
    task_result = await test_db.execute(
        select(SyncTask).where(SyncTask.case_id == case.id)
    )
    task = task_result.scalar_one_or_none()
    assert task is not None
    assert task.task_type == "remote_create_employment"
    assert task.status == SyncTaskStatus.PENDING

    print(f"Integration test SUCCESS: Case {case.workflow_id} is READY_FOR_REMOTE")


# ──────────────────────────────────────────────
# Test 2: Validation failure — BLOCKED path
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_validation_failure_blocks_case(client: AsyncClient, test_db: AsyncSession):
    """
    When a hire arrives with missing required fields, the case should
    be BLOCKED_VALIDATION and no Remote sync task should be created.
    """
    external_id = f"KF-{uuid.uuid4().hex[:6]}"
    payload = {
        "event_type": "hire_created",
        "event_id": str(uuid.uuid4()),
        "data": {
            "id": external_id,
            "employee_email": "",              # Missing email → validation error
            "employee_full_name": "",          # Missing name → validation error
            "country": "US",
            "start_date": (date.today() + timedelta(days=14)).isoformat(),
            "manager_email": "manager@example.com",
            "job_title": "Engineer",
            "contract_edit_requested": False,
        }
    }

    response = await client.post("/webhooks/kissflow", json=payload)
    assert response.status_code == 202

    from app.dependencies import get_queue
    queue = get_queue()
    msg = await queue.receive_message()
    assert msg is not None

    await process_case_message(msg.body)

    result = await test_db.execute(
        select(OnboardingCase).where(OnboardingCase.external_hire_id == external_id)
    )
    case = result.scalar_one_or_none()
    assert case is not None
    assert case.status == CaseStatus.BLOCKED_VALIDATION

    # Should have NO Remote sync tasks
    task_result = await test_db.execute(
        select(SyncTask).where(
            SyncTask.case_id == case.id,
            SyncTask.task_type == "remote_create_employment",
        )
    )
    assert task_result.scalar_one_or_none() is None

    # Should have validation results persisted
    vr_result = await test_db.execute(
        select(ValidationResult).where(ValidationResult.case_id == case.id)
    )
    results = vr_result.scalars().all()
    assert len(results) > 0  # At least one validation failure

    print(f"Validation failure test SUCCESS: Case is BLOCKED_VALIDATION with {len(results)} validation results")


# ──────────────────────────────────────────────
# Test 3: Idempotency — duplicate event dedup
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_event_is_ignored(client: AsyncClient, test_db: AsyncSession):
    """
    Sending the same event_id twice should result in the second
    invocation being a no-op (dedup skipped).
    """
    event_id = str(uuid.uuid4())
    external_id = f"KF-{uuid.uuid4().hex[:6]}"
    payload = {
        "event_type": "hire_created",
        "event_id": event_id,
        "data": {
            "id": external_id,
            "employee_email": "dedup.test@example.com",
            "employee_full_name": "Dedup Test User",
            "country": "GB",
            "start_date": (date.today() + timedelta(days=30)).isoformat(),
            "manager_email": "manager@example.com",
            "job_title": "Analyst",
            "contract_edit_requested": False,
        }
    }

    # First submission
    response = await client.post("/webhooks/kissflow", json=payload)
    assert response.status_code == 202

    from app.dependencies import get_queue
    queue = get_queue()
    msg = await queue.receive_message()
    await process_case_message(msg.body)

    # Second submission with same event_id
    response2 = await client.post("/webhooks/kissflow", json=payload)
    assert response2.status_code == 202

    msg2 = await queue.receive_message()
    # This should be a no-op due to dedup
    await process_case_message(msg2.body)

    # Should still have only ONE case for this external_hire_id
    result = await test_db.execute(
        select(OnboardingCase).where(OnboardingCase.external_hire_id == external_id)
    )
    cases = result.scalars().all()
    assert len(cases) == 1

    print("Dedup test SUCCESS: Duplicate event was ignored")


# ──────────────────────────────────────────────
# Test 4: Revalidation — unblock a stuck case
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_revalidation_unblocks_case(test_db: AsyncSession):
    """
    A case stuck in BLOCKED_VALIDATION should transition to
    READY_FOR_REMOTE when revalidated with corrected data.
    """
    # Create a blocked case directly in the DB
    case = OnboardingCase(
        id=uuid.uuid4(),
        workflow_id=f"WF-{uuid.uuid4().hex[:8]}",
        external_hire_id=f"KF-{uuid.uuid4().hex[:6]}",
        source_system="KISSFLOW",
        employee_email="blocked.user@example.com",
        employee_full_name="Blocked User",
        country_code="US",
        job_title="Engineer",
        start_date=date.today() + timedelta(days=14),
        manager_email="manager@example.com",
        status=CaseStatus.BLOCKED_VALIDATION,
    )
    test_db.add(case)
    await test_db.commit()
    await test_db.refresh(case)

    # Trigger revalidation
    message = {
        "action": "revalidate",
        "case_id": str(case.id),
        "correlation_id": str(uuid.uuid4()),
    }

    await process_case_message(message)

    # Refresh from DB
    await test_db.refresh(case)
    assert case.status == CaseStatus.READY_FOR_REMOTE

    print(f"Revalidation test SUCCESS: Case {case.workflow_id} unblocked")


# ──────────────────────────────────────────────
# Test 5: Remote webhook — state transition
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remote_webhook_transitions_state(test_db: AsyncSession):
    """
    A Remote 'employment.user_status.invited' event should transition
    a case from REMOTE_SYNC_IN_PROGRESS to REMOTE_INVITED.
    """
    remote_id = f"remote-{uuid.uuid4().hex[:8]}"
    case = OnboardingCase(
        id=uuid.uuid4(),
        workflow_id=f"WF-{uuid.uuid4().hex[:8]}",
        external_hire_id=f"KF-{uuid.uuid4().hex[:6]}",
        source_system="KISSFLOW",
        employee_email="remote.test@example.com",
        employee_full_name="Remote Test User",
        country_code="DE",
        job_title="Product Manager",
        start_date=date.today() + timedelta(days=21),
        remote_employment_id=remote_id,
        status=CaseStatus.REMOTE_SYNC_IN_PROGRESS,
    )
    test_db.add(case)
    await test_db.commit()
    await test_db.refresh(case)

    # Simulate Remote webhook
    message = {
        "action": "process_remote_event",
        "source_system": "REMOTE",
        "event_type": "employment.user_status.invited",
        "event_id": str(uuid.uuid4()),
        "resource_id": remote_id,
        "correlation_id": str(uuid.uuid4()),
        "payload": {},
    }

    await process_case_message(message)

    await test_db.refresh(case)
    assert case.status == CaseStatus.REMOTE_INVITED

    # Verify event was persisted
    event_result = await test_db.execute(
        select(OnboardingEvent).where(OnboardingEvent.case_id == case.id)
    )
    events = event_result.scalars().all()
    assert len(events) >= 1
    assert any("remote.employment.user_status.invited" in e.event_type for e in events)

    print(f"Remote webhook test SUCCESS: Case transitioned to REMOTE_INVITED")


# ──────────────────────────────────────────────
# Test 6: Admin API — case listing
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_cases_api(client: AsyncClient, test_db: AsyncSession):
    """
    Verify the admin API returns cases with correct structure.
    """
    # Create a case
    case = OnboardingCase(
        id=uuid.uuid4(),
        workflow_id=f"WF-{uuid.uuid4().hex[:8]}",
        source_system="KISSFLOW",
        employee_email="admin.api@example.com",
        employee_full_name="Admin API Test",
        country_code="FR",
        job_title="Designer",
        status=CaseStatus.RECEIVED,
    )
    test_db.add(case)
    await test_db.commit()

    response = await client.get(
        "/admin/cases",
        headers={"X-API-Key": "test-admin-key"},
    )
    assert response.status_code == 200

    data = response.json()
    assert "cases" in data
    assert data["total"] >= 1

    print(f"Admin API test SUCCESS: {data['total']} cases returned")
