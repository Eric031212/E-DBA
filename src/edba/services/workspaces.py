"""The directory of registered organizations' workspaces."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from edba.errors import NotFound
from edba.models import Organization


def directory(db: Session, q: str = "") -> list[Organization]:
    stmt = select(Organization).order_by(Organization.full_name)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(Organization.full_name.ilike(like), Organization.short_name.ilike(like))
        )
    return list(db.scalars(stmt))


def by_slug(db: Session, slug: str) -> Organization:
    org = db.scalar(select(Organization).where(func.lower(Organization.short_name) == slug.lower()))
    if org is None:
        raise NotFound("Workspace not found.")
    return org
