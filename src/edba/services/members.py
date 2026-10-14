"""O-Convener member management: member-list import, domain rules, quotas."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from edba.errors import DomainError, NotFound
from edba.models import DomainRule, Organization, Role, User
from edba.money import to_cents
from edba.services import audit, auth
from edba.services.sheets import read_table

COLUMNS = ["name", "email", "access_right", "quota"]


@dataclass
class ImportReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _level(raw: str) -> int:
    try:
        level = int(float(raw))
    except ValueError as e:
        raise DomainError(f"access_right must be 1, 2 or 3 (got {raw!r})") from e
    if level not in (1, 2, 3):
        raise DomainError(f"access_right must be 1, 2 or 3 (got {raw!r})")
    return level


def import_member_list(
    db: Session, convener: User, org: Organization, filename: str, data: bytes
) -> ImportReport:
    """All-or-nothing import of a 4-column list: name, email, access_right, quota.

    A row with an empty name and an email like ``*@mail.uic.edu.cn`` registers
    the whole domain: anyone with such an address can later sign in and join
    this organization with that row's access right and quota.
    """
    header, rows = read_table(filename, data)
    if header != COLUMNS:
        raise DomainError(
            "The member list needs exactly these four columns: name, email, access_right, quota "
            f"(found: {', '.join(header) or 'nothing'})."
        )
    report = ImportReport()
    seen: set[str] = set()
    plan: list[tuple[str, str, int, int]] = []  # kind, key, level, quota  (kind: member|rule)
    names: dict[str, str] = {}
    for i, (name, email_raw, level_raw, quota_raw) in enumerate(rows, start=2):
        try:
            level = _level(level_raw)
            quota = to_cents(quota_raw or "0")
            if email_raw.startswith("*@"):
                if name:
                    raise DomainError("wildcard rows must leave the name empty")
                domain = email_raw[1:].lower()
                auth.normalize_email("x" + domain)  # validates the domain part
                key = domain
                kind = "rule"
            else:
                key = auth.normalize_email(email_raw)
                kind = "member"
            if key in seen:
                raise DomainError(f"{key} appears more than once")
            if kind == "rule":
                owner = db.scalar(select(DomainRule).where(DomainRule.domain == key))
                if owner and owner.org_id != org.id:
                    raise DomainError(f"{key} is already claimed by another organization")
            else:
                other = db.scalar(select(User).where(User.email == key))
                if other and not (other.role is Role.MEMBER and other.org_id == org.id):
                    raise DomainError(f"{key} already has an E-DBA account elsewhere")
            seen.add(key)
            plan.append((kind, key, level, quota))
            names[key] = name
        except DomainError as e:
            report.errors.append((i, e.message))
    if report.errors:
        return report

    for kind, key, level, quota in plan:
        if kind == "rule":
            rule = db.scalar(select(DomainRule).where(DomainRule.domain == key))
            if rule is None:
                rule = DomainRule(org_id=org.id, domain=key)
                db.add(rule)
            rule.access_level, rule.quota_cents = level, quota
            report.rules.append(key)
            continue
        user = db.scalar(select(User).where(User.email == key))
        if user is None:
            db.add(
                User(
                    email=key,
                    name=names[key],
                    role=Role.MEMBER,
                    org_id=org.id,
                    access_level=level,
                    quota_cents=quota,
                    fee_paid=level == 1,
                )
            )
            report.added.append(key)
        else:
            if level > user.access_level and level >= 2:
                user.fee_paid = False  # upgraded: the higher level's fee is due
            user.access_level, user.quota_cents = level, quota
            user.name = names[key] or user.name
            report.updated.append(key)
    audit.record(
        db,
        "members.imported",
        f"Member list imported: {len(report.added)} added, {len(report.updated)} updated, "
        f"{len(report.rules)} domain rule(s)",
        actor=convener,
        org_id=org.id,
        added=report.added,
        updated=report.updated,
        rules=report.rules,
    )
    return report


def members(db: Session, org: Organization) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .where(User.org_id == org.id, User.role == Role.MEMBER)
            .order_by(User.access_level.desc(), User.email)
        )
    )


def rules(db: Session, org: Organization) -> list[DomainRule]:
    return list(db.scalars(select(DomainRule).where(DomainRule.org_id == org.id)))


def _member(db: Session, org: Organization, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None or user.org_id != org.id or user.role is not Role.MEMBER:
        raise NotFound("Member not found.")
    return user


def remove_member(db: Session, convener: User, org: Organization, user_id: str) -> None:
    user = _member(db, org, user_id)
    audit.record(
        db, "member.removed", f"Removed member {user.email}", actor=convener, org_id=org.id
    )
    db.delete(user)


def set_quota(db: Session, convener: User, org: Organization, user_id: str, amount: str) -> User:
    user = _member(db, org, user_id)
    before = user.quota_cents
    user.quota_cents = to_cents(amount)
    audit.record(
        db,
        "member.quota_set",
        f"Quota of {user.email} set to {user.quota_cents / 100:.2f}",
        actor=convener,
        org_id=org.id,
        before=before,
        after=user.quota_cents,
    )
    return user


def remove_rule(db: Session, convener: User, org: Organization, rule_id: int) -> None:
    rule = db.get(DomainRule, rule_id)
    if rule is None or rule.org_id != org.id:
        raise NotFound("Domain rule not found.")
    audit.record(db, "domain_rule.removed", f"Removed domain rule {rule.domain}", actor=convener)
    db.delete(rule)
