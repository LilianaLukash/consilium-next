"""Send or log verification / reset emails."""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger("consilium.email")


def send_verification_email(email: str, token: str) -> None:
    link = f"{settings.app_public_url.rstrip('/')}/auth.html?verify={token}"
    body = f"Подтвердите email: {link}"
    _dispatch(email, "Подтверждение Consilium", body)


def send_password_reset_email(email: str, token: str) -> None:
    link = f"{settings.app_public_url.rstrip('/')}/auth.html?reset={token}"
    body = f"Сброс пароля: {link}"
    _dispatch(email, "Сброс пароля Consilium", body)


def _dispatch(to: str, subject: str, body: str) -> None:
    if not settings.smtp_host:
        logger.warning("EMAIL (dev) to=%s subject=%s\n%s", to, subject, body)
        return
    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.email_from
    msg["To"] = to
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        if settings.smtp_user:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)
