from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any


logger = logging.getLogger(__name__)

# Secret handling: use env var in production; fallback is a local default to keep desktop mode simple.
USER_SIGNING_SECRET_ENV = "TDM_USER_SIGNING_SECRET"
DEFAULT_USER_SIGNING_SECRET = "tdm-platform-local-signing-secret-change-me"

_SIGNED_FIELDS = (
    "email",
    "username",
    "name",
    "role",
    "verified",
    "active",
    "password_hash",
    "verification_code",
)


def _get_signing_secret() -> str:
    secret = str(os.getenv(USER_SIGNING_SECRET_ENV, "")).strip()
    if secret:
        return secret
    logger.warning(
        "%s is not set; using default local signing secret. "
        "Set env var in production for stronger tamper resistance.",
        USER_SIGNING_SECRET_ENV,
    )
    return DEFAULT_USER_SIGNING_SECRET


def canonicalize_user_record(user: dict[str, Any]) -> str:
    payload = {
        "email": str(user.get("email", "")).strip().lower(),
        "username": str(user.get("username", "")).strip().lower(),
        "name": str(user.get("name", "")).strip(),
        "role": str(user.get("role", "")).strip().lower(),
        "verified": bool(user.get("verified", False)),
        "active": bool(user.get("active", True)),
        "password_hash": str(user.get("password_hash", "")).strip(),
        "verification_code": str(user.get("verification_code", "")).strip(),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sign_user_record(user: dict[str, Any]) -> str:
    message = canonicalize_user_record(user).encode("utf-8")
    secret = _get_signing_secret().encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def verify_user_record(user: dict[str, Any]) -> bool:
    signature = str(user.get("signature", "")).strip()
    if not signature:
        return False
    expected = sign_user_record(user)
    return hmac.compare_digest(signature, expected)


def attach_signature(user: dict[str, Any]) -> dict[str, Any]:
    signed = dict(user)
    for key in list(signed.keys()):
        if key.startswith("_"):
            signed.pop(key, None)
    signed["signature"] = sign_user_record(signed)
    return signed


def signed_field_names() -> tuple[str, ...]:
    return _SIGNED_FIELDS
