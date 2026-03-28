from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import asdict
from datetime import datetime

from tdm_platform.core.models import User
from tdm_platform.core.roles import resolve_user_role
from tdm_platform.security.user_signing import attach_signature, verify_user_record
from tdm_platform.storage.json_store import load_json_list, save_json
from tdm_platform.storage.paths import USERS_PATH

ALLOWED_EMAIL_DOMAIN = "dpckorhaz.hu"
ALLOWED_TEST_EMAILS = {"visnyo.adam@gmail.com"}
MAIN_MODERATOR_EMAIL = "visnyovszki.adam@dpckorhaz.hu"
logger = logging.getLogger(__name__)


def normalize_email_value(email: str) -> str:
    return str(email or "").strip().lower()


def validate_doctor_email_value(email: str) -> str:
    normalized = normalize_email_value(email)
    if not normalized or "@" not in normalized:
        raise ValueError("Adj meg egy érvényes e-mail címet.")
    if normalized in ALLOWED_TEST_EMAILS:
        return normalized
    if not normalized.endswith(f"@{ALLOWED_EMAIL_DOMAIN}"):
        allowed_extra = ", ".join(sorted(ALLOWED_TEST_EMAILS))
        raise ValueError(
            f"Csak @{ALLOWED_EMAIL_DOMAIN} e-mail címmel lehet regisztrálni és belépni. "
            f"Teszt kivétel: {allowed_extra}"
        )
    return normalized


def hash_password_value(password: str) -> str:
    return hashlib.sha256(str(password).encode("utf-8")).hexdigest()


def generate_temp_password(length: int = 12) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def user_is_active(user: dict | None) -> bool:
    return bool(user) and user.get("active", True) is not False


def ensure_special_roles(users: list[dict], enforce_signature: bool = True) -> list[dict]:
    found = False
    for user in users:
        signature_ok = verify_user_record(user) if enforce_signature else bool(user.get("_signature_valid", True))
        if enforce_signature and not signature_ok:
            logger.warning(
                "Invalid or missing user signature for %s. Record marked inactive.",
                normalize_email_value(user.get("email", "")) or "unknown-user",
            )
            user["active"] = False
            user["_signature_valid"] = False
        else:
            user["_signature_valid"] = True

        email = normalize_email_value(user.get("email", ""))
        plaintext = str(user.pop("password", "")).strip()
        if plaintext and not str(user.get("password_hash", "")).strip():
            user["password_hash"] = hash_password_value(plaintext)
        expected_role = resolve_user_role(user)
        original_role = str(user.get("role", "")).strip().lower()
        if original_role and original_role != expected_role:
            logger.warning(
                "JSON role mismatch for %s: stored=%s resolved=%s",
                email or "unknown-user",
                original_role,
                expected_role,
            )
        user["role"] = expected_role
        if email == MAIN_MODERATOR_EMAIL:
            found = bool(user.get("_signature_valid", False))
    if not found:
        bootstrap = asdict(
            User(
                name="Dr. Visnyovszki Ádám",
                email=MAIN_MODERATOR_EMAIL,
                username=MAIN_MODERATOR_EMAIL.split("@")[0],
                password_hash=hash_password_value("ChangeMe123!"),
                role="moderator",
                verified=True,
                verified_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        )
        users.append(attach_signature(bootstrap))
    return users


class UserStore:
    def __init__(self, path=USERS_PATH):
        self.path = path

    def load(self) -> list[dict]:
        return ensure_special_roles(load_json_list(self.path), enforce_signature=True)

    def save(self, users: list[dict]) -> None:
        normalized = ensure_special_roles(users, enforce_signature=False)
        save_json(self.path, [attach_signature(user) for user in normalized])
