"""
Unit tests for the normalizer service.
"""

from datetime import date

import pytest

from app.schemas.kissflow import KissflowDocument, KissflowHirePayload, KissflowWebhookEvent
from app.services.normalizer import (
    normalize_country_code,
    normalize_kissflow_event,
    parse_date_flexible,
)


class TestNormalizeCountryCode:
    def test_two_letter_code(self):
        assert normalize_country_code("US") == "US"
        assert normalize_country_code("us") == "US"
        assert normalize_country_code("gb") == "GB"

    def test_full_name(self):
        assert normalize_country_code("United States") == "US"
        assert normalize_country_code("united kingdom") == "GB"
        assert normalize_country_code("Canada") == "CA"
        assert normalize_country_code("Germany") == "DE"

    def test_unknown_defaults_to_uppercase(self):
        result = normalize_country_code("Atlantis")
        assert result == "AT"  # Takes first 2 chars uppercased


class TestParseDateFlexible:
    def test_iso_format(self):
        assert parse_date_flexible("2026-05-01") == date(2026, 5, 1)

    def test_us_format(self):
        assert parse_date_flexible("05/01/2026") == date(2026, 5, 1)

    def test_iso_with_time(self):
        assert parse_date_flexible("2026-05-01T00:00:00") == date(2026, 5, 1)

    def test_none_returns_none(self):
        assert parse_date_flexible(None) is None

    def test_empty_returns_none(self):
        assert parse_date_flexible("") is None

    def test_garbage_returns_none(self):
        assert parse_date_flexible("not-a-date") is None


class TestNormalizeKissflowEvent:
    def _make_event(self, **data_overrides) -> KissflowWebhookEvent:
        data = {
            "id": "KF-123",
            "employee_email": "test@example.com",
            "employee_full_name": "Test User",
            "country": "United States",
            "start_date": "2026-06-01",
            "manager_email": "manager@example.com",
            "department": "Engineering",
            "job_title": "Developer",
            "documents": [],
            "contract_edit_requested": False,
        }
        data.update(data_overrides)
        return KissflowWebhookEvent(
            event_type="hire_created",
            event_id="evt-001",
            data=KissflowHirePayload(**data),
        )

    def test_basic_normalization(self):
        event = self._make_event()
        record = normalize_kissflow_event(event)

        assert record.employee_email == "test@example.com"
        assert record.employee_full_name == "Test User"
        assert record.country_code == "US"
        assert record.start_date == date(2026, 6, 1)
        assert record.external_hire_id == "KF-123"
        assert record.source_system.value == "KISSFLOW"

    def test_email_lowercased(self):
        event = self._make_event(employee_email="TEST@EXAMPLE.COM")
        record = normalize_kissflow_event(event)
        assert record.employee_email == "test@example.com"

    def test_country_name_to_code(self):
        event = self._make_event(country="Germany")
        record = normalize_kissflow_event(event)
        assert record.country_code == "DE"

    def test_document_refs(self):
        docs = [
            {"file_name": "passport.pdf", "file_url": "https://example.com/passport.pdf"},
            {"file_name": "offer_letter.docx"},
        ]
        event = self._make_event(documents=docs)
        record = normalize_kissflow_event(event)
        assert len(record.document_refs) == 2
        assert "passport.pdf" in record.document_refs

    def test_contract_edit_flag(self):
        event = self._make_event(contract_edit_requested=True)
        record = normalize_kissflow_event(event)
        assert record.contract_edit_requested is True

    def test_raw_payload_preserved(self):
        event = self._make_event()
        record = normalize_kissflow_event(event)
        assert record.raw_payload is not None
