"""Initial schema — all onboarding orchestrator tables.

Revision ID: 001
Revises: (none)
Create Date: 2026-04-09
"""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── onboarding_case ──
    op.create_table(
        "onboarding_case",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workflow_id", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=True, index=True),
        sa.Column("external_hire_id", sa.String(128), nullable=True, index=True),
        sa.Column(
            "source_system",
            sa.Enum("KISSFLOW", "REMOTE", "NOTION", "MANUAL", name="source_system_enum"),
            nullable=False,
        ),
        sa.Column("employee_email", sa.String(255), nullable=False, index=True),
        sa.Column("employee_full_name", sa.String(255), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("hiring_entity_type", sa.String(64), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("manager_email", sa.String(255), nullable=True),
        sa.Column("department", sa.String(128), nullable=True),
        sa.Column("job_title", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "RECEIVED", "NORMALIZING", "VALIDATING", "BLOCKED_VALIDATION",
                "READY_FOR_REMOTE", "REMOTE_SYNC_IN_PROGRESS", "REMOTE_INVITED",
                "REMOTE_ONBOARDING_IN_PROGRESS", "PENDING_DOCUMENTS",
                "PENDING_CONTRACT_ACTION", "LEGAL_REVIEW_REQUIRED",
                "WAITING_ON_EMPLOYEE", "WAITING_ON_INTERNAL_OWNER",
                "ESCALATED", "COMPLETED", "CANCELLED", "FAILED_TERMINAL",
                name="case_status_enum",
            ),
            nullable=False,
            index=True,
        ),
        sa.Column("substatus", sa.String(128), nullable=True),
        sa.Column("owner_user_id", sa.String(128), nullable=True),
        sa.Column(
            "severity",
            sa.Enum("LOW", "MEDIUM", "HIGH", "CRITICAL", name="case_severity_enum"),
            nullable=False,
        ),
        sa.Column("remote_employment_id", sa.String(128), nullable=True),
        sa.Column("notion_page_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── onboarding_event ──
    op.create_table(
        "onboarding_event",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("onboarding_case.id"), nullable=False, index=True),
        sa.Column("event_type", sa.String(128), nullable=False, index=True),
        sa.Column("source_system", sa.String(32), nullable=False),
        sa.Column("source_event_id", sa.String(256), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_result", sa.String(32), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )

    # ── validation_result ──
    op.create_table(
        "validation_result",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("onboarding_case.id"), nullable=False, index=True),
        sa.Column("validation_type", sa.String(64), nullable=False),
        sa.Column("field_name", sa.String(128), nullable=True),
        sa.Column(
            "severity",
            sa.Enum("INFO", "WARN", "ERROR", name="validation_severity_enum"),
            nullable=False,
        ),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("message", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── document_check ──
    op.create_table(
        "document_check",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("onboarding_case.id"), nullable=False, index=True),
        sa.Column("document_type", sa.String(64), nullable=False),
        sa.Column("file_name", sa.String(512), nullable=True),
        sa.Column("file_present", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("file_category", sa.String(64), nullable=True),
        sa.Column("file_status", sa.String(32), nullable=False, server_default="'pending'"),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── sync_task ──
    op.create_table(
        "sync_task",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("onboarding_case.id"), nullable=False, index=True),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column(
            "target_system",
            sa.Enum("REMOTE", "SLACK", "NOTION", "KISSFLOW", name="target_system_enum"),
            nullable=False,
        ),
        sa.Column("target_object_id", sa.String(256), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "IN_PROGRESS", "COMPLETED",
                "FAILED_RETRYABLE", "FAILED_TERMINAL", "SKIPPED",
                name="sync_task_status_enum",
            ),
            nullable=False,
            index=True,
        ),
        sa.Column("idempotency_key", sa.String(64), nullable=False, index=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── escalation ──
    op.create_table(
        "escalation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("onboarding_case.id"), nullable=False, index=True),
        sa.Column("escalation_type", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(128), nullable=False),
        sa.Column("target", sa.String(255), nullable=True),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("sla_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("triggered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── audit_log ──
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("onboarding_case.id"), nullable=False, index=True),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("before_json", sa.Text(), nullable=True),
        sa.Column("after_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("escalation")
    op.drop_table("sync_task")
    op.drop_table("document_check")
    op.drop_table("validation_result")
    op.drop_table("onboarding_event")
    op.drop_table("onboarding_case")
