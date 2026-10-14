"""T-Admin management of E-Admin accounts."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from edba.errors import Conflict, NotFound
from edba.models import Role, User
from edba.services import audit, auth

ADMIN_ROLES = (Role.E_ADMIN, Role.SENIOR_E_ADMIN)


def listing(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.role.in_(ADMIN_ROLES)).order_by(User.email)))


def create(db: Session, t_admin: User, email: str, name: str, senior: bool) -> User:
    email = auth.normalize_email(email)
    if db.scalar(select(User).where(User.email == email)):
        raise Conflict("That email already has an account.")
    u = User(email=email, name=name.strip(), role=Role.SENIOR_E_ADMIN if senior else Role.E_ADMIN)
    db.add(u)
    db.flush()
    audit.record(db, "admin.created", f"Created {u.role.label} {email}", actor=t_admin)
    return u


def _get(db: Session, user_id: str) -> User:
    u = db.get(User, user_id)
    if u is None or u.role not in ADMIN_ROLES:
        raise NotFound("Admin not found.")
    return u


def set_senior(db: Session, t_admin: User, user_id: str, senior: bool) -> User:
    u = _get(db, user_id)
    u.role = Role.SENIOR_E_ADMIN if senior else Role.E_ADMIN
    audit.record(db, "admin.updated", f"{u.email} is now {u.role.label}", actor=t_admin)
    return u


def set_active(db: Session, t_admin: User, user_id: str, active: bool) -> User:
    u = _get(db, user_id)
    u.is_active = active
    audit.record(
        db, "admin.updated", f"{u.email} {'enabled' if active else 'disabled'}", actor=t_admin
    )
    return u
