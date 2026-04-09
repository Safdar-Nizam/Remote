"""
Unit tests for the validation engine.
"""

from datetime import date, timedelta

import pytest

from app.models.onboarding_case import SourceSystem
from app.schemas.internal import CanonicalHireRecord
from app.services.validator import (
    check_country_code,
    check_duplicate,
    check_email_format,
    check_required_fields,
    check_start_date,
    validate_hire,
)


def _make_record(**overrides) -> CanonicalHireRecord:
    defaults = {
        "external_hire_id": "KF-12345",
        "source_system": SourceSystem.KISSFLOW,
        "employee_email": "jane.doe@example.com",
        "employee_full_name": "Jane Doe",
        "country_code": "US",
        "start_date": date.today() + timedelta(days=14),
    }
    defaults.update(overrides)
    return CanonicalHireRecord(**defaults)


class TestRequiredFields:
    def test_all_present_passes(self):
        record = _make_record()
        results = check_required_fields(record)
        errors = [r for r in results if r.severity == "ERROR"]
        assert len(errors) == 0

    def test_missing_email_fails(self):
        record = _make_record(employee_email="")
        results = check_required_fields(record)
        errors = [r for r in results if r.severity == "ERROR"]
        assert len(errors) == 1
        assert "employee_email" in errors[0].field_name

    def test_missing_name_fails(self):
        record = _make_record(employee_full_name="")
        results = check_required_fields(record)
        errors = [r for r in results if r.severity == "ERROR"]
        assert len(errors) == 1

    def test_missing_start_date_warns(self):
        record = _make_record(start_date=None)
        results = check_required_fields(record)
        warnings = [r for r in results if r.severity == "WARN"]
        assert len(warnings) == 1


class TestEmailFormat:
    def test_valid_email(self):
        record = _make_record()
        results = check_email_format(record)
        assert len(results) == 0

    def test_invalid_email(self):
        record = _make_record(employee_email="not-an-email")
        results = check_email_format(record)
        assert len(results) == 1
        assert results[0].severity == "ERROR"

    def test_invalid_manager_email(self):
        record = _make_record(manager_email="bad@")
        results = check_email_format(record)
        assert len(results) == 1


class TestStartDate:
    def test_valid_date(self):
        record = _make_record(start_date=date.today() + timedelta(days=14))
        results = check_start_date(record)
        assert len(results) == 0

    def test_past_date_fails(self):
        record = _make_record(start_date=date.today() - timedelta(days=30))
        results = check_start_date(record)
        assert len(results) == 1
        assert results[0].severity == "ERROR"

    def test_far_future_warns(self):
        record = _make_record(start_date=date.today() + timedelta(days=400))
        results = check_start_date(record)
        assert len(results) == 1
        assert results[0].severity == "WARN"

    def test_none_date_skipped(self):
        record = _make_record(start_date=None)
        results = check_start_date(record)
        assert len(results) == 0


class TestCountryCode:
    def test_supported_country(self):
        record = _make_record(country_code="US")
        results = check_country_code(record)
        assert len(results) == 0

    def test_unsupported_country(self):
        record = _make_record(country_code="XX")
        results = check_country_code(record)
        assert len(results) == 1
        assert results[0].severity == "ERROR"


class TestDuplicateDetection:
    def test_no_duplicates(self):
        record = _make_record()
        results = check_duplicate(record, existing_emails=set())
        assert len(results) == 0

    def test_duplicate_found(self):
        record = _make_record()
        results = check_duplicate(record, existing_emails={"jane.doe@example.com"})
        assert len(results) == 1
        assert results[0].severity == "ERROR"


class TestValidateHire:
    def test_valid_hire_passes(self):
        record = _make_record()
        outcome = validate_hire(record)
        assert outcome.passed is True
        assert len(outcome.blocking_errors) == 0

    def test_invalid_hire_fails(self):
        record = _make_record(employee_email="", country_code="XX")
        outcome = validate_hire(record)
        assert outcome.passed is False
        assert len(outcome.blocking_errors) >= 2

    def test_warnings_dont_block(self):
        record = _make_record(start_date=None)
        outcome = validate_hire(record)
        assert outcome.passed is True
        assert len(outcome.warnings) >= 1
