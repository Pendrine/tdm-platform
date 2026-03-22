from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

from tdm_platform.core.models import SMTPSettings
from tdm_platform.storage.json_store import load_json_dict, save_json
from tdm_platform.storage.paths import SETTINGS_PATH

SMTP_DEFAULT_HOST = "mail.dpckorhaz.hu"
SMTP_DEFAULT_PORT = 587
SMTP_DEFAULT_USER = "visnyovszki.adam@dpckorhaz.hu"
SMTP_DEFAULT_FROM = "visnyovszki.adam@dpckorhaz.hu"
SMTP_DEFAULT_STARTTLS = True
SMTP_DEFAULT_SSL = False


class SMTPSettingsStore:
    def __init__(self, path=SETTINGS_PATH):
        self.path = path

    def load(self) -> SMTPSettings:
        data = load_json_dict(self.path)
        return SMTPSettings(
            host=str(data.get("smtp_host", SMTP_DEFAULT_HOST)).strip(),
            port=int(data.get("smtp_port", SMTP_DEFAULT_PORT) or SMTP_DEFAULT_PORT),
            smtp_user=str(data.get("smtp_user", SMTP_DEFAULT_USER)).strip(),
            smtp_pass=str(data.get("smtp_pass", "")).strip(),
            sender=str(data.get("smtp_from", SMTP_DEFAULT_FROM)).strip(),
            use_starttls=_to_bool(data.get("smtp_starttls", SMTP_DEFAULT_STARTTLS)),
            use_ssl=_to_bool(data.get("smtp_ssl", SMTP_DEFAULT_SSL)),
        )

    def save(self, settings: SMTPSettings) -> None:
        save_json(
            self.path,
            {
                "smtp_host": settings.host,
                "smtp_port": settings.port,
                "smtp_user": settings.smtp_user,
                "smtp_pass": settings.smtp_pass,
                "smtp_from": settings.sender,
                "smtp_starttls": settings.use_starttls,
                "smtp_ssl": settings.use_ssl,
            },
        )


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def get_smtp_settings() -> SMTPSettings:
    cfg = SMTPSettingsStore().load()
    return SMTPSettings(
        host=os.getenv("TDM_SMTP_HOST", cfg.host).strip(),
        port=int(os.getenv("TDM_SMTP_PORT", str(cfg.port)) or cfg.port),
        smtp_user=os.getenv("TDM_SMTP_USER", cfg.smtp_user).strip(),
        smtp_pass=os.getenv("TDM_SMTP_PASS", cfg.smtp_pass).strip(),
        sender=os.getenv("TDM_SMTP_FROM", cfg.sender).strip(),
        use_starttls=_to_bool(os.getenv("TDM_SMTP_STARTTLS", str(cfg.use_starttls))),
        use_ssl=_to_bool(os.getenv("TDM_SMTP_SSL", str(cfg.use_ssl))),
    )


def send_email(
    smtp: SMTPSettings,
    to: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
    attachments: list[tuple[str, bytes, str, str]] | None = None,
) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp.sender
    msg["To"] = to
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    for filename, content, maintype, subtype in attachments or []:
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

    context = ssl.create_default_context()
    if smtp.use_ssl:
        with smtplib.SMTP_SSL(smtp.host, smtp.port, timeout=20, context=context) as server:
            if smtp.smtp_user:
                server.login(smtp.smtp_user, smtp.smtp_pass)
            server.send_message(msg)
        return

    with smtplib.SMTP(smtp.host, smtp.port, timeout=20) as server:
        server.ehlo()
        if smtp.use_starttls:
            server.starttls(context=context)
            server.ehlo()
        if smtp.smtp_user:
            server.login(smtp.smtp_user, smtp.smtp_pass)
        server.send_message(msg)
