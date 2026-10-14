"""Passwordless sign-in with emailed one-time codes, and who is allowed to sign in."""

from __future__ import annotations

from datetime import timedelta

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from edba.config import Settings
from edba.db import utcnow
from edba.errors import DomainError, Forbidden
from edba.models import DomainRule, Organization, OtpChallenge, Role, User
from edba.security.crypto import hash_otp, new_otp, otp_matches
from edba.services import audit, mail


def normalize_email(raw: str) -> str:
    try:
        return validate_email(raw.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as e:
        raise DomainError(f"Invalid email address: {e}") from e


def domain_of(email: str) -> str:
    return "@" + email.rsplit("@", 1)[1]


def issue_code(db: Session, settings: Settings, email: str, purpose: str) -> OtpChallenge:
    """Invalidate earlier codes for this email/purpose, store a new hashed one and mail it."""
    now = utcnow()
    db.execute(
        update(OtpChallenge)
        .where(
            OtpChallenge.email == email,
            OtpChallenge.purpose == purpose,
            OtpChallenge.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    ch = OtpChallenge(
        email=email,
        purpose=purpose,
        code_hash="",
        expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
    )
    db.add(ch)
    db.flush()
    code = new_otp()
    ch.code_hash = hash_otp(settings, ch.id, code)
    minutes = settings.otp_ttl_seconds // 60
    what = "sign in to E-DBA" if purpose == "login" else "confirm your E-DBA application"
    mail.send(
        db,
        settings,
        email,
        f"E-DBA verification code: {code}",
        f"Your code to {what} is {code}.\n\nIt expires in {minutes} minutes. "
        "If you did not request it, ignore this message.",
    )
    db.flush()
    return ch


def check_code(db: Session, settings: Settings, email: str, purpose: str, code: str) -> None:
    ch = db.scalar(
        select(OtpChallenge)
        .where(
            OtpChallenge.email == email,
            OtpChallenge.purpose == purpose,
            OtpChallenge.consumed_at.is_(None),
        )
        .order_by(OtpChallenge.created_at.desc())
        .limit(1)
    )
    if ch is None:
        raise DomainError("No active code for this email. Request a new one.")
    if utcnow() > ch.expires_at:
        ch.consumed_at = utcnow()
        raise DomainError("This code has expired. Request a new one.")
    if ch.attempts >= settings.otp_max_attempts:
        ch.consumed_at = utcnow()
        raise DomainError("Too many wrong attempts. Request a new code.")
    if not otp_matches(settings, ch.id, code, ch.code_hash):
        ch.attempts += 1
        raise DomainError("Wrong verification code.")
    ch.consumed_at = utcnow()


def resolve_sign_in(db: Session, email: str) -> User:
    """Find (or, via a domain rule, create) the account for ``email`` and check it may sign in.

    Rules carried over from the v3 specification:
      * unknown emails are refused unless an organization registered their domain
        (``*@mail.uic.edu.cn`` in its member list) *and* paid the level-1 fee;
      * data users whose membership fee is unpaid cannot sign in. Level 1 is a
        one-off organization fee; levels 2 and 3 are paid per person.
    """
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        rule = db.scalar(select(DomainRule).where(DomainRule.domain == domain_of(email)))
        if rule is None:
            raise Forbidden("This email is not registered with E-DBA.")
        org = rule.organization
        if not org.level1_paid:
            raise Forbidden(f"{org.short_name} has not activated domain sign-in yet.")
        user = User(
            email=email,
            role=Role.MEMBER,
            org_id=org.id,
            access_level=rule.access_level,
            quota_cents=rule.quota_cents,
            fee_paid=rule.access_level == 1,
        )
        db.add(user)
        db.flush()
        audit.record(
            db,
            "member.auto_provisioned",
            f"{email} joined {org.short_name} via domain rule {rule.domain}",
            actor_email=email,
            org_id=org.id,
            level=rule.access_level,
        )
    if not user.is_active:
        raise Forbidden("This account has been disabled.")
    if user.role is Role.MEMBER:
        home = user.organization
        assert home is not None
        paid = home.level1_paid if user.access_level == 1 else user.fee_paid
        if not paid:
            raise Forbidden(
                "Your organization has not paid the membership fee for your access level yet. "
                "Please contact your O-Convener."
            )
    return user


def request_login_code(db: Session, settings: Settings, raw_email: str) -> str:
    email = normalize_email(raw_email)
    resolve_sign_in(db, email)
    issue_code(db, settings, email, "login")
    return email


def complete_login(db: Session, settings: Settings, raw_email: str, code: str) -> User:
    email = normalize_email(raw_email)
    check_code(db, settings, email, "login", code)
    user = resolve_sign_in(db, email)
    user.last_login_at = utcnow()
    audit.record(db, "auth.login", f"{email} signed in", actor=user)
    return user


def org_of(db: Session, user: User) -> Organization | None:
    return db.get(Organization, user.org_id) if user.org_id else None
