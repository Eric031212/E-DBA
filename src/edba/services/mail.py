"""Outgoing mail. In dev/test messages land in the ``mail_messages`` table."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from edba.config import Settings
from edba.models import MailMessage


def send(db: Session, settings: Settings, to: str, subject: str, body: str) -> None:
    if settings.mail_backend == "inbox":
        db.add(MailMessage(to=to.lower(), subject=subject, body=body))
        db.flush()
        return
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


def inbox(db: Session, to: str | None = None, limit: int = 100) -> list[MailMessage]:
    stmt = select(MailMessage).order_by(MailMessage.id.desc()).limit(limit)
    if to:
        stmt = stmt.where(MailMessage.to == to.lower())
    return list(db.scalars(stmt))
