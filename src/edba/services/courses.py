"""Course information sharing: public catalogue, maintained by level-3 providers."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from edba.errors import Conflict, DomainError, NotFound
from edba.models import Course, Organization, ServiceKind, User
from edba.services import audit, catalog


def search(
    db: Session, org: Organization, q: str = "", *, include_inactive: bool = False
) -> list[Course]:
    stmt = select(Course).where(Course.org_id == org.id).order_by(Course.code)
    if not include_inactive:
        stmt = stmt.where(Course.active.is_(True))
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(Course.code.ilike(like), Course.title.ilike(like), Course.description.ilike(like))
        )
    return list(db.scalars(stmt))


def _validate(code: str, title: str, units: str) -> tuple[str, str, int]:
    code, title = code.strip().upper(), title.strip()
    if not code or len(code) > 20:
        raise DomainError("Course code is required (max 20 characters).")
    if not title:
        raise DomainError("Course title is required.")
    try:
        n = int(units)
    except ValueError as e:
        raise DomainError("Units must be a whole number.") from e
    if not 0 <= n <= 30:
        raise DomainError("Units must be between 0 and 30.")
    return code, title, n


def _require_service(db: Session, org: Organization) -> None:
    if catalog.get_service(db, org, ServiceKind.COURSE_INFO) is None:
        raise DomainError("Course Information is not enabled for this workspace.")


def create(
    db: Session,
    provider: User,
    org: Organization,
    *,
    code: str,
    title: str,
    description: str = "",
    units: str = "3",
    active: bool = True,
) -> Course:
    _require_service(db, org)
    code, title, n = _validate(code, title, units)
    if db.scalar(select(Course).where(Course.org_id == org.id, Course.code == code)):
        raise Conflict(f"A course with code {code} already exists.")
    c = Course(
        org_id=org.id,
        code=code,
        title=title,
        description=description.strip(),
        units=n,
        active=active,
    )
    db.add(c)
    db.flush()
    audit.record(db, "course.created", f"Created course {code} {title}", actor=provider)
    return c


def get(db: Session, org: Organization, course_id: int) -> Course:
    c = db.get(Course, course_id)
    if c is None or c.org_id != org.id:
        raise NotFound("Course not found.")
    return c


def update(
    db: Session,
    provider: User,
    org: Organization,
    course_id: int,
    *,
    code: str,
    title: str,
    description: str,
    units: str,
    active: bool,
) -> Course:
    c = get(db, org, course_id)
    code, title, n = _validate(code, title, units)
    clash = db.scalar(select(Course).where(Course.org_id == org.id, Course.code == code))
    if clash and clash.id != c.id:
        raise Conflict(f"A course with code {code} already exists.")
    c.code, c.title, c.description, c.units, c.active = code, title, description.strip(), n, active
    audit.record(db, "course.updated", f"Updated course {code}", actor=provider)
    return c


def delete(db: Session, provider: User, org: Organization, course_id: int) -> None:
    c = get(db, org, course_id)
    audit.record(db, "course.deleted", f"Deleted course {c.code}", actor=provider)
    db.delete(c)
