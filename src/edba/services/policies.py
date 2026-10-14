"""Data-sharing policies: PDF documents with a version history, managed by E-Admins."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from edba.config import Settings
from edba.errors import DomainError, NotFound
from edba.models import Policy, PolicyVersion, User
from edba.security.crypto import sha256_bytes
from edba.services import audit
from edba.services.registration import save_upload


def listing(db: Session, *, include_archived: bool = False) -> list[Policy]:
    stmt = select(Policy).order_by(Policy.title)
    if not include_archived:
        stmt = stmt.where(Policy.archived.is_(False))
    return list(db.scalars(stmt))


def get(db: Session, policy_id: int) -> Policy:
    p = db.get(Policy, policy_id)
    if p is None:
        raise NotFound("Policy not found.")
    return p


def _add_version(db: Session, admin: User, p: Policy, path: str, pdf: bytes) -> PolicyVersion:
    v = PolicyVersion(
        version=(p.versions[-1].version + 1) if p.versions else 1,
        file_path=path,
        sha256=sha256_bytes(pdf),
        uploaded_by=admin.email,
    )
    p.versions.append(v)
    db.flush()
    return v


def create(
    db: Session,
    settings: Settings,
    admin: User,
    title: str,
    summary: str,
    filename: str,
    pdf: bytes,
) -> Policy:
    if not title.strip():
        raise DomainError("Policy title is required.")
    path = save_upload(settings, "policies", filename, pdf, {".pdf"})
    p = Policy(title=title.strip(), summary=summary.strip())
    db.add(p)
    _add_version(db, admin, p, path, pdf)
    audit.record(
        db, "policy.created", f"Published policy '{p.title}' v1", actor=admin, policy_id=p.id
    )
    return p


def revise(
    db: Session,
    settings: Settings,
    admin: User,
    policy_id: int,
    title: str,
    summary: str,
    filename: str | None,
    pdf: bytes | None,
) -> Policy:
    p = get(db, policy_id)
    path = (
        save_upload(settings, "policies", filename or "policy.pdf", pdf, {".pdf"}) if pdf else None
    )
    if title.strip():
        p.title = title.strip()
    p.summary = summary.strip()
    note = "details"
    if path and pdf:
        v = _add_version(db, admin, p, path, pdf)
        note = f"v{v.version}"
    audit.record(
        db, "policy.revised", f"Updated policy '{p.title}' ({note})", actor=admin, policy_id=p.id
    )
    return p


def archive(db: Session, admin: User, policy_id: int) -> None:
    p = get(db, policy_id)
    p.archived = True
    audit.record(db, "policy.archived", f"Archived policy '{p.title}'", actor=admin, policy_id=p.id)


def version(db: Session, version_id: int) -> PolicyVersion:
    v = db.get(PolicyVersion, version_id)
    if v is None:
        raise NotFound("Policy version not found.")
    return v
