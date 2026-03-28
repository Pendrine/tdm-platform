from __future__ import annotations

import smtplib

from typing import Optional

from PySide6.QtWidgets import QLabel

from tdm_platform.core.auth import UserStore, generate_temp_password, hash_password_value, user_is_active, validate_doctor_email_value
from tdm_platform.core.models import SMTPSettings
from tdm_platform.services.smtp_service import get_smtp_settings, send_email

from legacy import tdm_platform_v0_9_3_beta_fixed as legacy_ui


def _smtp_as_legacy_dict(settings: SMTPSettings) -> dict[str, object]:
    return {
        "host": settings.host,
        "port": settings.port,
        "smtp_user": settings.smtp_user,
        "smtp_pass": settings.smtp_pass,
        "sender": settings.sender,
        "use_starttls": settings.use_starttls,
        "use_ssl": settings.use_ssl,
    }


class AuthDialog(legacy_ui.AuthDialog):
    """Modular auth dialog wrapper that keeps the legacy UI stable."""

    def __init__(self, parent=None):
        self._user_store = UserStore()
        self._smtp_store = get_smtp_settings
        self.current_user: Optional[dict] = None
        super().__init__(parent)
        if hasattr(self, "login_identifier_combo") and self.login_identifier_combo.lineEdit():
            self.login_identifier_combo.lineEdit().setPlaceholderText("kórházi e-mail")
        for label in self.findChildren(QLabel):
            if label.text().strip().lower() == "felhasználónév / e-mail":
                label.setText("Kórházi e-mail")

    def _load_users_data(self) -> list[dict]:
        users = self._user_store.load()
        for user in users:
            user.setdefault("active", True)
            user.setdefault("username", str(user.get("email", "")).split("@")[0] if user.get("email") else "")
        return users

    def save_users(self):
        self._user_store.save(self.users_data)

    def _login_candidates(self) -> list[str]:
        candidates: list[str] = []
        for user in self.users_data:
            email = str(user.get("email", "")).strip()
            if email and email not in candidates:
                candidates.append(email)
        return candidates

    def resolve_login_identifier(self, raw_value: str) -> str:
        value = (raw_value or "").strip()
        if not value:
            raise ValueError("Add meg a kórházi e-mail címet.")
        return validate_doctor_email_value(value)

    def register_user(self):
        super().register_user()
        email = str(getattr(self, "reg_email_edit", None).text() if hasattr(self, "reg_email_edit") else "").strip().lower()
        if "@" in email and hasattr(self, "login_identifier_combo"):
            self.login_identifier_combo.setEditText(email)

    def find_user(self, email: str) -> Optional[dict]:
        return super().find_user(email)

    def validate_doctor_email(self, email: str) -> str:
        return validate_doctor_email_value(email)

    @staticmethod
    def hash_password(password: str) -> str:
        return hash_password_value(password)

    def send_verification_email(self, email: str, code: str):
        smtp = self._smtp_store()
        if not smtp.host or not smtp.sender or not smtp.smtp_pass:
            return False, f"Fejlesztői mód: SMTP jelszó nincs beállítva. Ellenőrző kód: {code}"
        try:
            send_email(
                smtp,
                to=email,
                subject="Klinikai TDM Platform – e-mail visszaigazolás",
                text_body=(
                    "Kedves Kolléga!\n\n"
                    f"A Klinikai TDM Platform regisztrációjához használd ezt az ellenőrző kódot: {code}\n\n"
                    "Ha nem te indítottad a regisztrációt, hagyd figyelmen kívül ezt az üzenetet.\n"
                ),
            )
            return True, f"Visszaigazoló e-mail elküldve: {email}"
        except smtplib.SMTPAuthenticationError as exc:
            return False, (
                "Az SMTP hitelesítés sikertelen. Ellenőrizd az SMTP felhasználónevet, jelszót, "
                f"STARTTLS/SSL beállítást. Fejlesztői fallback ellenőrző kód: {code}. SMTP hiba: {exc}"
            )
        except Exception as exc:
            return False, f"Az e-mail küldése nem sikerült ({exc}). Ellenőrző kód: {code}"

    def send_password_reset_email(self, email: str, temp_password: str):
        smtp = self._smtp_store()
        if not smtp.host or not smtp.sender or not smtp.smtp_pass:
            return False, f"Az SMTP nincs teljesen beállítva. Ideiglenes jelszó: {temp_password}"
        try:
            send_email(
                smtp,
                to=email,
                subject="Klinikai TDM Platform – ideiglenes jelszó",
                text_body=(
                    "Ideiglenes jelszó kérés történt a Klinikai TDM Platformhoz.\n\n"
                    f"Ideiglenes jelszó: {temp_password}\n\n"
                    "Belépés után a Beállításoknál javasolt azonnal új jelszót megadni.\n"
                ),
            )
            return True, f"Az ideiglenes jelszó elküldve: {email}"
        except smtplib.SMTPAuthenticationError as exc:
            return False, (
                "Az SMTP hitelesítés sikertelen. Ellenőrizd az SMTP felhasználónevet, jelszót, "
                f"STARTTLS/SSL beállítást. Fejlesztői fallback ideiglenes jelszó: {temp_password}. SMTP hiba: {exc}"
            )
        except Exception as exc:
            return False, f"Az e-mail küldése nem sikerült ({exc}). Ideiglenes jelszó: {temp_password}"


legacy_ui.generate_temp_password = generate_temp_password
legacy_ui.user_is_active = user_is_active
legacy_ui.validate_doctor_email_value = validate_doctor_email_value
legacy_ui.hash_password_value = hash_password_value
legacy_ui.load_users_file = lambda: UserStore().load()
legacy_ui.save_users_file = lambda users: UserStore().save(users)
legacy_ui.get_smtp_settings = lambda: _smtp_as_legacy_dict(get_smtp_settings())
