"""
Webhook signature verification and admin API key authentication.
"""

import hashlib
import hmac
import secrets

from fastapi import Depends, Header, HTTPException, status

from app.core.config import Settings, get_settings


def verify_webhook_signature(
    payload_body: bytes,
    signature_header: str,
    secret: str,
    algorithm: str = "sha256",
) -> bool:
    """
    Verify an HMAC webhook signature.
    Returns True if valid, False otherwise.
    """
    if not signature_header or not secret:
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        payload_body,
        getattr(hashlib, algorithm),
    ).hexdigest()

    # Compare with or without algorithm prefix (e.g., "sha256=abc123")
    actual = signature_header.split("=", 1)[-1] if "=" in signature_header else signature_header
    return secrets.compare_digest(expected, actual)


async def require_admin_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> str:
    """
    FastAPI dependency that validates the admin API key.
    Returns the key on success, raises 401 on failure.
    """
    if not secrets.compare_digest(x_api_key, settings.admin_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return x_api_key
