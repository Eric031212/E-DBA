"""Hash-chained audit log: write, query, verify."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from edba.db import utcnow
from edba.models import AuditEvent, User

GENESIS = "0" * 64


def _canonical(e: AuditEvent) -> bytes:
    payload = {
        "id": e.id,
        "at": e.at.astimezone(UTC).isoformat(timespec="microseconds"),
        "actor": e.actor_email,
        "role": e.actor_role,
        "org": e.org_id,
        "action": e.action,
        "summary": e.summary,
        "details": e.details,
        "prev": e.prev_hash,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()


def record(
    db: Session,
    action: str,
    summary: str,
    *,
    actor: User | None = None,
    actor_email: str | None = None,
    org_id: str | None = None,
    **details: Any,
) -> AuditEvent:
    """Append an event. Runs inside the caller's transaction, so it commits or rolls back with it.

    Concurrent writers are serialized by the unique constraint on ``hash``: two
    events chained to the same predecessor would collide only if identical, and
    the id sequence orders them; verification walks by id.
    """
    prev = db.scalar(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1))
    e = AuditEvent(
        at=utcnow(),
        actor_email=actor.email if actor else (actor_email or "system"),
        actor_role=actor.role.value if actor else "",
        org_id=org_id if org_id is not None else (actor.org_id if actor else None),
        action=action,
        summary=summary[:500],
        details=details,
        prev_hash=prev.hash if prev else GENESIS,
        hash="",
    )
    db.add(e)
    db.flush()  # assigns id
    e.hash = hashlib.sha256(_canonical(e)).hexdigest()
    db.flush()
    return e


@dataclass
class ChainReport:
    ok: bool
    checked: int
    broken_at: int | None = None
    reason: str = ""


def verify_chain(db: Session) -> ChainReport:
    prev_hash = GENESIS
    n = 0
    for e in db.scalars(select(AuditEvent).order_by(AuditEvent.id)):
        n += 1
        if e.prev_hash != prev_hash:
            return ChainReport(False, n, e.id, "link to previous event does not match")
        if hashlib.sha256(_canonical(e)).hexdigest() != e.hash:
            return ChainReport(False, n, e.id, "event content was modified")
        prev_hash = e.hash
    return ChainReport(True, n)


def search(
    db: Session,
    *,
    org_id: str | None = None,
    q: str = "",
    action: str = "",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 200,
) -> list[AuditEvent]:
    stmt = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
    if org_id is not None:
        stmt = stmt.where(AuditEvent.org_id == org_id)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(AuditEvent.actor_email.ilike(like), AuditEvent.summary.ilike(like)))
    if date_from:
        stmt = stmt.where(AuditEvent.at >= date_from)
    if date_to:
        stmt = stmt.where(AuditEvent.at <= date_to)
    return list(db.scalars(stmt))


def actions(db: Session, org_id: str | None = None) -> list[str]:
    stmt = select(AuditEvent.action).distinct().order_by(AuditEvent.action)
    if org_id is not None:
        stmt = stmt.where(AuditEvent.org_id == org_id)
    return list(db.scalars(stmt))
