from __future__ import annotations

import hashlib
import secrets
from dataclasses import asdict
from datetime import datetime

from tdm_platform.core.models import User
from tdm_platform.storage.json_store import load_json_list, save_json
from tdm_platform.storage.paths import USERS_PATH

ALLOWED_EMAIL_DOMAIN = "dpckorhaz.hu"
ALLOWED_TEST_EMAILS = {"visnyo.adam@gmail.com"}
MAIN_MODERATOR_EMAIL = "visnyovszki.adam@dpckorhaz.hu"


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


def ensure_special_roles(users: list[dict]) -> list[dict]:
    found = False
    for user in users:
        email = normalize_email_value(user.get("email", ""))
        plaintext = str(user.pop("password", "")).strip()
        if plaintext and not str(user.get("password_hash", "")).strip():
            user["password_hash"] = hash_password_value(plaintext)
        if email == MAIN_MODERATOR_EMAIL:
            user["role"] = "moderator"
            found = True
        else:
            user.setdefault("role", "orvos")
    if not found:
        users.append(
            asdict(
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
        )
    return users


class UserStore:
    def __init__(self, path=USERS_PATH):
        self.path = path

    def load(self) -> list[dict]:
        return ensure_special_roles(load_json_list(self.path))

    def save(self, users: list[dict]) -> None:
        save_json(self.path, ensure_special_roles(users))
