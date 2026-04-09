"""
Validation Engine — config-driven rule engine that checks canonical hire records.
Each rule returns a list of ValidationResult-ready dicts.
Rules are composable, severity-aware, and designed for easy extension.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.core.logging import get_logger
from app.schemas.internal import CanonicalHireRecord

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Validation result container
# ──────────────────────────────────────────────

@dataclass
class RuleResult:
    validation_type: str
    field_name: str | None
    severity: str      # "INFO", "WARN", "ERROR"
    result: str        # "pass" or "fail"
    message: str


@dataclass
class ValidationOutcome:
    """Aggregated outcome of running all rules on a hire record."""
    passed: bool
    results: list[RuleResult] = field(default_factory=list)
    blocking_errors: list[RuleResult] = field(default_factory=list)
    warnings: list[RuleResult] = field(default_factory=list)


# ──────────────────────────────────────────────
# Individual rules
# ──────────────────────────────────────────────

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

SUPPORTED_COUNTRIES: set[str] = {
    "US", "GB", "CA", "DE", "FR", "AU", "IN", "BR", "JP", "SG",
    "NL", "IE", "ES", "PT", "MX", "PH", "NG", "ZA", "KE", "CO",
    "AR", "PL", "IT",
}

# Document requirements by hire type (placeholder — make config-driven)
REQUIRED_DOCS_BY_TYPE: dict[str, list[str]] = {
    "default": [],  # No mandatory docs enforced until config is provided
}


def check_required_fields(record: CanonicalHireRecord) -> list[RuleResult]:
    """Check that all mandatory fields are present and non-empty."""
    results = []
    required = {
        "employee_email": record.employee_email,
        "employee_full_name": record.employee_full_name,
        "country_code": record.country_code,
    }
    for field_name, value in required.items():
        if not value or not str(value).strip():
            results.append(RuleResult(
                validation_type="required_fields",
                field_name=field_name,
                severity="ERROR",
                result="fail",
                message=f"Required field '{field_name}' is missing or empty",
            ))
    # start_date is a warning if missing, not a blocker
    if not record.start_date:
        results.append(RuleResult(
            validation_type="required_fields",
            field_name="start_date",
            severity="WARN",
            result="fail",
            message="Start date is missing — hire may proceed but date should be confirmed",
        ))
    return results


def check_email_format(record: CanonicalHireRecord) -> list[RuleResult]:
    """Validate email format for employee and manager."""
    results = []
    for field_name, email in [("employee_email", record.employee_email), ("manager_email", record.manager_email)]:
        if email and not EMAIL_REGEX.match(email):
            results.append(RuleResult(
                validation_type="email_format",
                field_name=field_name,
                severity="ERROR",
                result="fail",
                message=f"Invalid email format: '{email}'",
            ))
    return results


def check_start_date(record: CanonicalHireRecord, min_days: int = -7, max_days: int = 365) -> list[RuleResult]:
    """
    Validate that start_date is within an acceptable window.
    - Cannot be more than 7 days in the past (adjustable)
    - Cannot be more than 365 days in the future (adjustable)
    """
    results = []
    if not record.start_date:
        return results  # Already handled by required_fields

    today = date.today()
    earliest = today + timedelta(days=min_days)
    latest = today + timedelta(days=max_days)

    if record.start_date < earliest:
        results.append(RuleResult(
            validation_type="start_date",
            field_name="start_date",
            severity="ERROR",
            result="fail",
            message=f"Start date {record.start_date} is too far in the past (earliest allowed: {earliest})",
        ))
    elif record.start_date > latest:
        results.append(RuleResult(
            validation_type="start_date",
            field_name="start_date",
            severity="WARN",
            result="fail",
            message=f"Start date {record.start_date} is more than {max_days} days in the future",
        ))
    return results


def check_country_code(record: CanonicalHireRecord) -> list[RuleResult]:
    """Verify that the country code is in the supported set."""
    results = []
    if record.country_code and record.country_code not in SUPPORTED_COUNTRIES:
        results.append(RuleResult(
            validation_type="country_code",
            field_name="country_code",
            severity="ERROR",
            result="fail",
            message=f"Unsupported country code: '{record.country_code}'. Supported: {sorted(SUPPORTED_COUNTRIES)}",
        ))
    return results


def check_document_presence(record: CanonicalHireRecord) -> list[RuleResult]:
    """Check that required documents are present based on hire type."""
    results = []
    hire_type = record.hiring_entity_type or "default"
    required_docs = REQUIRED_DOCS_BY_TYPE.get(hire_type, REQUIRED_DOCS_BY_TYPE.get("default", []))

    for doc_type in required_docs:
        # Simple check: is there a document ref that matches the expected type?
        found = any(doc_type.lower() in ref.lower() for ref in record.document_refs)
        if not found:
            results.append(RuleResult(
                validation_type="document_presence",
                field_name="documents",
                severity="WARN",
                result="fail",
                message=f"Expected document type '{doc_type}' not found in uploaded files",
            ))
    return results


def check_duplicate(
    record: CanonicalHireRecord,
    existing_emails: set[str] | None = None,
) -> list[RuleResult]:
    """
    Check for duplicate active onboarding for the same employee email.
    The caller should provide a set of emails from active cases within a 30-day window.
    """
    results = []
    if existing_emails and record.employee_email.lower() in existing_emails:
        results.append(RuleResult(
            validation_type="duplicate_detection",
            field_name="employee_email",
            severity="ERROR",
            result="fail",
            message=f"Active onboarding case already exists for '{record.employee_email}'",
        ))
    return results


# ──────────────────────────────────────────────
# Validation engine orchestrator
# ──────────────────────────────────────────────

def validate_hire(
    record: CanonicalHireRecord,
    existing_emails: set[str] | None = None,
) -> ValidationOutcome:
    """
    Run all validation rules against a canonical hire record.
    Returns a ValidationOutcome with pass/fail status and detailed results.
    """
    all_results: list[RuleResult] = []

    # Run all rules
    all_results.extend(check_required_fields(record))
    all_results.extend(check_email_format(record))
    all_results.extend(check_start_date(record))
    all_results.extend(check_country_code(record))
    all_results.extend(check_document_presence(record))
    all_results.extend(check_duplicate(record, existing_emails))

    # Classify
    blocking = [r for r in all_results if r.severity == "ERROR" and r.result == "fail"]
    warnings = [r for r in all_results if r.severity == "WARN" and r.result == "fail"]

    passed = len(blocking) == 0

    logger.info(
        "validation_complete",
        employee_email=record.employee_email,
        passed=passed,
        total_rules=len(all_results),
        blocking_errors=len(blocking),
        warnings=len(warnings),
    )

    return ValidationOutcome(
        passed=passed,
        results=all_results,
        blocking_errors=blocking,
        warnings=warnings,
    )
