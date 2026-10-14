"""Policies, help desk tickets and the development mailbox."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from edba.db import Base, utcnow


class Policy(Base):
    """A data-sharing policy document. Each upload adds a version; nothing is overwritten."""

    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    archived: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    versions: Mapped[list[PolicyVersion]] = relationship(
        back_populates="policy", order_by="PolicyVersion.version", cascade="all, delete-orphan"
    )

    @property
    def current(self) -> PolicyVersion | None:
        return self.versions[-1] if self.versions else None


class PolicyVersion(Base):
    __tablename__ = "policy_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id", ondelete="CASCADE"))
    version: Mapped[int]
    file_path: Mapped[str] = mapped_column(String(400))
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_by: Mapped[str] = mapped_column(String(254))
    uploaded_at: Mapped[datetime] = mapped_column(default=utcnow)

    policy: Mapped[Policy] = relationship(back_populates="versions")


class HelpTicket(Base):
    __tablename__ = "help_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    author_email: Mapped[str] = mapped_column(String(254), index=True)
    author_role: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    answered_by: Mapped[str | None] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    answered_at: Mapped[datetime | None]


class MailMessage(Base):
    """Outgoing mail when ``EDBA_MAIL_BACKEND=inbox`` (development and tests)."""

    __tablename__ = "mail_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    to: Mapped[str] = mapped_column(String(254), index=True)
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
