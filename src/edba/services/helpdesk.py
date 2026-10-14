"""Seek-help tickets, answered by T-Admins."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from edba.config import Settings
from edba.db import utcnow
from edba.errors import DomainError, NotFound
from edba.models import HelpTicket, User
from edba.services import audit, mail


def ask(db: Session, user: User, title: str, body: str) -> HelpTicket:
    if not title.strip() or not body.strip():
        raise DomainError("Please fill in both the subject and the question.")
    t = HelpTicket(
        author_email=user.email,
        author_role=user.role.label,
        title=title.strip()[:200],
        body=body.strip(),
    )
    db.add(t)
    db.flush()
    audit.record(db, "help.asked", f"Help request #{t.id}: {t.title}", actor=user)
    return t


def mine(db: Session, user: User) -> list[HelpTicket]:
    return list(
        db.scalars(
            select(HelpTicket)
            .where(HelpTicket.author_email == user.email)
            .order_by(HelpTicket.id.desc())
        )
    )


def queue(db: Session) -> list[HelpTicket]:
    return list(
        db.scalars(
            select(HelpTicket).order_by(HelpTicket.answer.is_not(None), HelpTicket.id.desc())
        )
    )


def answer(db: Session, settings: Settings, admin: User, ticket_id: int, text: str) -> HelpTicket:
    t = db.get(HelpTicket, ticket_id)
    if t is None:
        raise NotFound("Ticket not found.")
    if not text.strip():
        raise DomainError("The answer is empty.")
    t.answer, t.answered_by, t.answered_at = text.strip(), admin.email, utcnow()
    mail.send(db, settings, t.author_email, f"Re: {t.title}", t.answer)
    audit.record(db, "help.answered", f"Answered help request #{t.id}", actor=admin)
    return t
