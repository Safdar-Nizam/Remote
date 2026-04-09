"""
Seed realistic test data for live demo purposes.
Run: python scripts/seed_test_data.py

Creates 12 onboarding cases across various states to demonstrate
the dashboard, case list, and detail views with meaningful data.
"""

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.models.onboarding_case import CaseStatus, CaseSeverity, OnboardingCase
from app.models.onboarding_event import OnboardingEvent
from app.models.validation_result import ValidationResult
from app.models.sync_task import SyncTask, SyncTaskStatus
from app.models.escalation import Escalation
from app.models.audit_log import AuditLog

settings = get_settings()

DEMO_CASES = [
    # ── Active / Happy Path ──
    {
        "employee_email": "maria.garcia@example.com",
        "employee_full_name": "Maria Garcia",
        "country_code": "ES",
        "job_title": "Senior Product Designer",
        "department": "Design",
        "manager_email": "alex.chen@remote.com",
        "start_date": date.today() + timedelta(days=12),
        "status": CaseStatus.REMOTE_ONBOARDING_IN_PROGRESS,
        "severity": CaseSeverity.LOW,
        "remote_employment_id": "emp-a1b2c3d4",
    },
    {
        "employee_email": "james.okonkwo@example.com",
        "employee_full_name": "James Okonkwo",
        "country_code": "NG",
        "job_title": "Backend Engineer",
        "department": "Engineering",
        "manager_email": "sarah.kim@remote.com",
        "start_date": date.today() + timedelta(days=21),
        "status": CaseStatus.READY_FOR_REMOTE,
        "severity": CaseSeverity.LOW,
    },
    {
        "employee_email": "priya.sharma@example.com",
        "employee_full_name": "Priya Sharma",
        "country_code": "IN",
        "job_title": "Data Analyst",
        "department": "Analytics",
        "manager_email": "tom.wilson@remote.com",
        "start_date": date.today() + timedelta(days=7),
        "status": CaseStatus.REMOTE_INVITED,
        "severity": CaseSeverity.LOW,
        "remote_employment_id": "emp-e5f6g7h8",
    },
    {
        "employee_email": "lucas.mueller@example.com",
        "employee_full_name": "Lucas Müller",
        "country_code": "DE",
        "job_title": "Engineering Manager",
        "department": "Engineering",
        "manager_email": "anna.berg@remote.com",
        "start_date": date.today() + timedelta(days=30),
        "status": CaseStatus.VALIDATING,
        "severity": CaseSeverity.LOW,
    },
    # ── Blocked / Needs Attention ──
    {
        "employee_email": "yuki.tanaka@example.com",
        "employee_full_name": "Yuki Tanaka",
        "country_code": "JP",
        "job_title": "QA Lead",
        "department": "Quality",
        "manager_email": "david.park@remote.com",
        "start_date": date.today() + timedelta(days=5),
        "status": CaseStatus.BLOCKED_VALIDATION,
        "severity": CaseSeverity.HIGH,
        "substatus": "Missing manager email verification",
    },
    {
        "employee_email": "sofia.rossi@example.com",
        "employee_full_name": "Sofia Rossi",
        "country_code": "IT",
        "job_title": "Legal Counsel",
        "department": "Legal",
        "manager_email": "emma.jones@remote.com",
        "start_date": date.today() + timedelta(days=18),
        "status": CaseStatus.LEGAL_REVIEW_REQUIRED,
        "severity": CaseSeverity.MEDIUM,
        "notion_page_id": "notion-pg-x9y0z1",
    },
    {
        "employee_email": "ahmed.hassan@example.com",
        "employee_full_name": "Ahmed Hassan",
        "country_code": "AE",
        "job_title": "Sales Director",
        "department": "Sales",
        "manager_email": "lisa.chen@remote.com",
        "start_date": date.today() + timedelta(days=3),
        "status": CaseStatus.PENDING_DOCUMENTS,
        "severity": CaseSeverity.HIGH,
        "substatus": "Awaiting work permit documents",
    },
    {
        "employee_email": "elena.petrova@example.com",
        "employee_full_name": "Elena Petrova",
        "country_code": "PL",
        "job_title": "Customer Success Manager",
        "department": "CS",
        "manager_email": "mark.taylor@remote.com",
        "start_date": date.today() - timedelta(days=2),
        "status": CaseStatus.ESCALATED,
        "severity": CaseSeverity.CRITICAL,
        "substatus": "Start date passed — SLA breached",
    },
    # ── Completed ──
    {
        "employee_email": "chen.wei@example.com",
        "employee_full_name": "Chen Wei",
        "country_code": "SG",
        "job_title": "DevOps Engineer",
        "department": "Infrastructure",
        "manager_email": "rachel.green@remote.com",
        "start_date": date.today() - timedelta(days=14),
        "status": CaseStatus.COMPLETED,
        "severity": CaseSeverity.LOW,
        "remote_employment_id": "emp-m3n4o5p6",
    },
    {
        "employee_email": "isabelle.dupont@example.com",
        "employee_full_name": "Isabelle Dupont",
        "country_code": "FR",
        "job_title": "Marketing Lead",
        "department": "Marketing",
        "manager_email": "james.Brown@remote.com",
        "start_date": date.today() - timedelta(days=7),
        "status": CaseStatus.COMPLETED,
        "severity": CaseSeverity.LOW,
        "remote_employment_id": "emp-q7r8s9t0",
    },
    # ── Edge Cases ──
    {
        "employee_email": "raj.patel@example.com",
        "employee_full_name": "Raj Patel",
        "country_code": "GB",
        "job_title": "Finance Analyst",
        "department": "Finance",
        "manager_email": "kate.williams@remote.com",
        "start_date": date.today() + timedelta(days=45),
        "status": CaseStatus.PENDING_CONTRACT_ACTION,
        "severity": CaseSeverity.MEDIUM,
        "substatus": "Contract edit requested by employee",
    },
    {
        "employee_email": "ana.santos@example.com",
        "employee_full_name": "Ana Santos",
        "country_code": "BR",
        "job_title": "Recruiter",
        "department": "People",
        "manager_email": "carlos.rivera@remote.com",
        "start_date": date.today() + timedelta(days=10),
        "status": CaseStatus.RECEIVED,
        "severity": CaseSeverity.LOW,
    },
]


async def seed():
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        now = datetime.now(timezone.utc)

        for i, data in enumerate(DEMO_CASES, start=1):
            case_id = uuid.uuid4()
            wf_id = f"ONB-2026-{i:05d}"

            case = OnboardingCase(
                id=case_id,
                workflow_id=wf_id,
                correlation_id=uuid.uuid4(),
                external_hire_id=f"KF-{uuid.uuid4().hex[:8]}",
                source_system="KISSFLOW",
                employee_email=data["employee_email"],
                employee_full_name=data["employee_full_name"],
                country_code=data["country_code"],
                job_title=data.get("job_title"),
                department=data.get("department"),
                manager_email=data.get("manager_email"),
                start_date=data.get("start_date"),
                status=data["status"],
                substatus=data.get("substatus"),
                severity=data.get("severity", CaseSeverity.LOW),
                remote_employment_id=data.get("remote_employment_id"),
                notion_page_id=data.get("notion_page_id"),
                created_at=now - timedelta(hours=24 - i),
                updated_at=now - timedelta(hours=max(0, 12 - i)),
                completed_at=now if data["status"] == CaseStatus.COMPLETED else None,
            )
            session.add(case)

            # Add an initial event for each case
            event = OnboardingEvent(
                id=uuid.uuid4(),
                case_id=case_id,
                event_type="hire_created",
                source_system="KISSFLOW",
                source_event_id=str(uuid.uuid4()),
                payload_json='{"source": "seed_data"}',
                received_at=case.created_at,
                processed_at=case.created_at + timedelta(seconds=2),
                processing_result="success",
            )
            session.add(event)

            # Add audit log entry
            audit = AuditLog(
                id=uuid.uuid4(),
                case_id=case_id,
                actor_type="system",
                actor_id="orchestrator",
                action=f"case_created → {data['status'].value}",
                after_json=f'{{"status": "{data["status"].value}"}}',
                created_at=case.created_at,
            )
            session.add(audit)

            # Add validation results for blocked cases
            if data["status"] == CaseStatus.BLOCKED_VALIDATION:
                vr = ValidationResult(
                    id=uuid.uuid4(),
                    case_id=case_id,
                    validation_type="required_fields",
                    field_name="manager_email",
                    severity="ERROR",
                    result="FAIL",
                    message="Manager email could not be verified against company directory",
                    created_at=case.created_at + timedelta(seconds=1),
                )
                session.add(vr)

            # Add sync tasks for cases past validation
            if data["status"] in (
                CaseStatus.READY_FOR_REMOTE,
                CaseStatus.REMOTE_SYNC_IN_PROGRESS,
                CaseStatus.REMOTE_INVITED,
                CaseStatus.REMOTE_ONBOARDING_IN_PROGRESS,
                CaseStatus.COMPLETED,
            ):
                task = SyncTask(
                    id=uuid.uuid4(),
                    case_id=case_id,
                    task_type="remote_create_employment",
                    target_system="REMOTE",
                    status=(
                        SyncTaskStatus.COMPLETED
                        if data["status"] in (CaseStatus.REMOTE_INVITED, CaseStatus.REMOTE_ONBOARDING_IN_PROGRESS, CaseStatus.COMPLETED)
                        else SyncTaskStatus.PENDING
                    ),
                    idempotency_key=f"remote-create-{wf_id}",
                    created_at=case.created_at + timedelta(seconds=3),
                    updated_at=case.updated_at,
                )
                session.add(task)

            # Add escalation for escalated cases
            if data["status"] == CaseStatus.ESCALATED:
                esc = Escalation(
                    id=uuid.uuid4(),
                    case_id=case_id,
                    escalation_type="sla_breach",
                    channel="slack",
                    target="#onboarding-ops",
                    severity="CRITICAL",
                    sla_deadline=now - timedelta(hours=2),
                    triggered_at=now - timedelta(hours=1),
                )
                session.add(esc)

            print(f"  ✓ {wf_id}  {data['employee_full_name']:30s}  {data['status'].value}")

        await session.commit()
        print(f"\n✅ Seeded {len(DEMO_CASES)} demo cases with events, audit logs, and related records.")

    await engine.dispose()


if __name__ == "__main__":
    print("🌱 Seeding demo data...\n")
    asyncio.run(seed())
