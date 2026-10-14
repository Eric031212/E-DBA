"""Tamper-evident audit trail.

Every event stores the SHA-256 of its own canonical form chained to the hash of
the previous event, so editing or deleting any past row breaks verification of
everything after it. This is the "traceability" item the v3 poster listed as
future work, done with a hash chain instead of a blockchain.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from edba.db import Base, utcnow


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    actor_email: Mapped[str] = mapped_column(String(254), index=True)
    actor_role: Mapped[str] = mapped_column(String(30), default="")
    org_id: Mapped[str | None] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(50), index=True)
    summary: Mapped[str] = mapped_column(String(500), default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
