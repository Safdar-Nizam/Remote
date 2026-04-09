"""
Normalizer — converts external payloads into the canonical CanonicalHireRecord.
Each source system has its own mapping function.
"""

from datetime import date, datetime

from app.core.logging import get_logger
from app.models.onboarding_case import SourceSystem
from app.schemas.internal import CanonicalHireRecord
from app.schemas.kissflow import KissflowWebhookEvent
from app.schemas.remote import RemoteWebhookEvent

logger = get_logger(__name__)

# ──────────────────────────────────────────────
# Country code normalization helpers
# ──────────────────────────────────────────────

COUNTRY_NAME_TO_CODE: dict[str, str] = {
    "united states": "US", "usa": "US", "us": "US",
    "united kingdom": "GB", "uk": "GB", "gb": "GB",
    "canada": "CA", "ca": "CA",
    "germany": "DE", "de": "DE",
    "france": "FR", "fr": "FR",
    "australia": "AU", "au": "AU",
    "india": "IN", "in": "IN",
    "brazil": "BR", "br": "BR",
    "japan": "JP", "jp": "JP",
    "singapore": "SG", "sg": "SG",
    "netherlands": "NL", "nl": "NL",
    "ireland": "IE", "ie": "IE",
    "spain": "ES", "es": "ES",
    "portugal": "PT", "pt": "PT",
    "mexico": "MX", "mx": "MX",
    "philippines": "PH", "ph": "PH",
    "nigeria": "NG", "ng": "NG",
    "south africa": "ZA", "za": "ZA",
    "kenya": "KE", "ke": "KE",
    "colombia": "CO", "co": "CO",
    "argentina": "AR", "ar": "AR",
    "poland": "PL", "pl": "PL",
    "italy": "IT", "it": "IT",
}


def normalize_country_code(raw: str) -> str:
    """Convert a country name or code to ISO 3166-1 alpha-2. Returns uppercased input if no match."""
    cleaned = raw.strip().lower()
    if len(cleaned) == 2:
        return cleaned.upper()
    return COUNTRY_NAME_TO_CODE.get(cleaned, raw.strip().upper()[:2])


def parse_date_flexible(raw: str | None) -> date | None:
    """Try common date formats and return a date object, or None if unparseable."""
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    logger.warning("unparseable_date", raw_value=raw)
    return None


# ──────────────────────────────────────────────
# Normalizer: Kissflow → Canonical
# ──────────────────────────────────────────────

def normalize_kissflow_event(event: KissflowWebhookEvent) -> CanonicalHireRecord:
    """Map a Kissflow webhook event to the canonical hire record."""
    data = event.data
    return CanonicalHireRecord(
        external_hire_id=data.record_id,
        source_system=SourceSystem.KISSFLOW,
        employee_email=data.employee_email.strip().lower(),
        employee_full_name=data.employee_full_name.strip(),
        country_code=normalize_country_code(data.country),
        hiring_entity_type=data.hiring_entity_type,
        start_date=parse_date_flexible(data.start_date),
        manager_email=data.manager_email.strip().lower() if data.manager_email else None,
        department=data.department,
        job_title=data.job_title,
        document_refs=[doc.file_name for doc in data.documents],
        contract_edit_requested=data.contract_edit_requested,
        raw_payload=event.model_dump(),
    )


# ──────────────────────────────────────────────
# Normalizer: Remote → Canonical (for webhook-driven updates)
# ──────────────────────────────────────────────

def normalize_remote_webhook(event: RemoteWebhookEvent, employment_data: dict | None = None) -> CanonicalHireRecord | None:
    """
    Map a Remote webhook event to a canonical record.
    Remote webhooks only carry the resource_id, so full employment_data must be fetched separately.
    Returns None if employment_data is not provided (caller should fetch it first).
    """
    if not employment_data:
        logger.info("remote_webhook_needs_fetch", resource_id=event.resource_id)
        return None

    return CanonicalHireRecord(
        external_hire_id=event.resource_id,
        source_system=SourceSystem.REMOTE,
        employee_email=employment_data.get("personal_email", "").strip().lower(),
        employee_full_name=employment_data.get("full_name", ""),
        country_code=employment_data.get("country_code", "XX"),
        hiring_entity_type=employment_data.get("type"),
        start_date=parse_date_flexible(employment_data.get("provisional_start_date")),
        manager_email=None,  # Remote may not provide this directly
        department=employment_data.get("department"),
        job_title=employment_data.get("job_title"),
        raw_payload=employment_data,
    )
