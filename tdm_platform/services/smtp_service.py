import smtplib
import ssl
from email.message import EmailMessage
from tdm_platform.core.models import SMTPSettings

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

    ctx = ssl.create_default_context()
    if smtp.use_ssl:
        with smtplib.SMTP_SSL(smtp.host, smtp.port, timeout=20, context=ctx) as server:
            if smtp.smtp_user:
                server.login(smtp.smtp_user, smtp.smtp_pass)
            server.send_message(msg)
    else:
        with smtplib.SMTP(smtp.host, smtp.port, timeout=20) as server:
            server.ehlo()
            if smtp.use_starttls:
                server.starttls(context=ctx)
                server.ehlo()
            if smtp.smtp_user:
                server.login(smtp.smtp_user, smtp.smtp_pass)
            server.send_message(msg)
