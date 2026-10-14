"""Organization registration: apply -> verify email -> E-Admin -> Senior E-Admin."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edba.config import Settings
from edba.errors import Conflict, DomainError, Forbidden, NotFound
from edba.models import (
    ApplicationReview,
    ApplicationStatus,
    Organization,
    RegistrationApplication,
    ReviewDecision,
    ReviewStage,
    Role,
    User,
)
from edba.security.crypto import sha256_bytes
from edba.services import audit, auth, mail

PROOF_TYPES = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_UPLOAD = 10 * 1024 * 1024
SHORT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9-]{1,19}$")


def save_upload(settings: Settings, sub: str, filename: str, data: bytes, allowed: set[str]) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in allowed:
        raise DomainError(
            f"Unsupported file type {ext or '(none)'}; use {', '.join(sorted(allowed))}."
        )
    if not data:
        raise DomainError("The uploaded file is empty.")
    if len(data) > MAX_UPLOAD:
        raise DomainError("Files must be 10 MB or smaller.")
    if ext == ".pdf" and not data.startswith(b"%PDF"):
        raise DomainError("That file is not a valid PDF.")
    folder = settings.upload_dir / sub
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    (folder / name).write_bytes(data)
    return f"{sub}/{name}"


def apply(
    db: Session,
    settings: Settings,
    *,
    org_full_name: str,
    org_short_name: str,
    convener_email: str,
    convener_name: str,
    proof_filename: str,
    proof: bytes,
) -> RegistrationApplication:
    full = org_full_name.strip()
    short = org_short_name.strip()
    if len(full) < 3:
        raise DomainError("Please enter the organization's full name.")
    if not SHORT_NAME.match(short):
        raise DomainError("Short name: 2-20 letters, digits or dashes, starting with a letter.")
    email = auth.normalize_email(convener_email)

    if db.scalar(select(Organization).where(func.lower(Organization.short_name) == short.lower())):
        raise Conflict(f"The short name {short} is already taken.")
    existing = db.scalar(select(User).where(User.email == email))
    if existing and existing.role is not Role.APPLICANT:
        raise Conflict("An E-DBA account with this email already exists.")
    open_app = db.scalar(
        select(RegistrationApplication).where(
            RegistrationApplication.convener_email == email,
            RegistrationApplication.email_verified.is_(True),
            RegistrationApplication.status.in_(
                [ApplicationStatus.PENDING, ApplicationStatus.FIRST_APPROVED]
            ),
        )
    )
    if open_app:
        raise Conflict("This email already has an application under review.")

    path = save_upload(settings, "proofs", proof_filename, proof, PROOF_TYPES)
    app = RegistrationApplication(
        org_full_name=full,
        org_short_name=short,
        convener_email=email,
        convener_name=convener_name.strip(),
        proof_path=path,
        proof_sha256=sha256_bytes(proof),
    )
    db.add(app)
    db.flush()
    auth.issue_code(db, settings, email, "apply")
    return app


def confirm_email(
    db: Session, settings: Settings, app_id: int, code: str
) -> RegistrationApplication:
    app = get(db, app_id)
    if app.email_verified:
        return app
    auth.check_code(db, settings, app.convener_email, "apply", code)
    app.email_verified = True
    user = db.scalar(select(User).where(User.email == app.convener_email))
    if user is None:
        user = User(email=app.convener_email, name=app.convener_name, role=Role.APPLICANT)
        db.add(user)
    audit.record(
        db,
        "application.submitted",
        f"Application #{app.id} for {app.org_full_name} ({app.org_short_name}) submitted",
        actor_email=app.convener_email,
        application_id=app.id,
        org_name=app.org_full_name,
    )
    mail.send(
        db,
        settings,
        app.convener_email,
        "E-DBA application received",
        f"Your application for {app.org_full_name} is now waiting for review. "
        "Sign in with this email to follow its status.",
    )
    return app


def get(db: Session, app_id: int) -> RegistrationApplication:
    app = db.get(RegistrationApplication, app_id)
    if app is None:
        raise NotFound("Application not found.")
    return app


def queue(db: Session, reviewer: User) -> list[RegistrationApplication]:
    """Applications the reviewer can act on now."""
    states = [ApplicationStatus.PENDING]
    if reviewer.role is Role.SENIOR_E_ADMIN:
        states.append(ApplicationStatus.FIRST_APPROVED)
    return list(
        db.scalars(
            select(RegistrationApplication)
            .where(
                RegistrationApplication.email_verified.is_(True),
                RegistrationApplication.status.in_(states),
            )
            .order_by(RegistrationApplication.submitted_at)
        )
    )


def all_verified(db: Session) -> list[RegistrationApplication]:
    return list(
        db.scalars(
            select(RegistrationApplication)
            .where(RegistrationApplication.email_verified.is_(True))
            .order_by(RegistrationApplication.id.desc())
        )
    )


def review(
    db: Session,
    settings: Settings,
    reviewer: User,
    app_id: int,
    decision: ReviewDecision,
    notes: str = "",
) -> RegistrationApplication:
    app = get(db, app_id)
    if not app.email_verified:
        raise DomainError("This application has not been confirmed by email yet.")
    if app.status is ApplicationStatus.PENDING:
        stage = ReviewStage.E_ADMIN
        if not reviewer.role.is_e_admin:
            raise Forbidden("Only E-Admins can review applications.")
    elif app.status is ApplicationStatus.FIRST_APPROVED:
        stage = ReviewStage.SENIOR
        if reviewer.role is not Role.SENIOR_E_ADMIN:
            raise Forbidden("The final review needs a Senior E-Admin.")
        if any(r.reviewer_email == reviewer.email for r in app.reviews):
            raise Forbidden("Four-eyes rule: the final review must be done by a different admin.")
    else:
        raise Conflict(f"Application already {app.status.value}.")
    if decision is ReviewDecision.REJECT and not notes.strip():
        raise DomainError("Please give a reason when rejecting.")
    final = stage is ReviewStage.SENIOR and decision is ReviewDecision.APPROVE
    if final and db.scalar(
        select(Organization).where(
            func.lower(Organization.short_name) == app.org_short_name.lower()
        )
    ):
        raise Conflict(f"The short name {app.org_short_name} was taken in the meantime.")

    app.reviews.append(
        ApplicationReview(
            stage=stage, decision=decision, reviewer_email=reviewer.email, notes=notes.strip()
        )
    )
    if decision is ReviewDecision.REJECT:
        app.status = ApplicationStatus.REJECTED
        subject = "E-DBA application rejected"
        body = f"Your application for {app.org_full_name} was rejected at the {stage.label}.\n\n{notes}"
    elif stage is ReviewStage.E_ADMIN:
        app.status = ApplicationStatus.FIRST_APPROVED
        subject = "E-DBA application passed first review"
        body = f"Your application for {app.org_full_name} is now with a Senior E-Admin."
    else:
        app.status = ApplicationStatus.ACCEPTED
        _provision(db, app)
        subject = "Welcome to E-DBA"
        body = (
            f"{app.org_full_name} is now registered. Sign in as O-Convener to set up the "
            "bank account, upload your member list and choose services."
        )
    audit.record(
        db,
        f"application.{decision.value}d",
        f"{stage.label}: {decision.value}d application #{app.id} — {app.org_full_name} "
        f"({app.org_short_name}), O-Convener {app.convener_email}"
        + (f", notes: {notes.strip()}" if notes.strip() else ""),
        actor=reviewer,
        org_id=app.org_id,
        application_id=app.id,
        org_name=app.org_full_name,
        convener=app.convener_email,
        stage=stage.value,
    )
    mail.send(db, settings, app.convener_email, subject, body)
    return app


def _provision(db: Session, app: RegistrationApplication) -> None:
    org = Organization(full_name=app.org_full_name, short_name=app.org_short_name)
    db.add(org)
    db.flush()
    user = db.scalar(select(User).where(User.email == app.convener_email))
    if user is None:
        user = User(email=app.convener_email, name=app.convener_name, role=Role.CONVENER)
        db.add(user)
    user.role = Role.CONVENER
    user.org_id = org.id
    app.org_id = org.id
    db.flush()


@dataclass
class Step:
    title: str
    state: str  # done | approved | rejected | waiting | upcoming | skipped
    actor: str = ""
    at: datetime | None = None
    notes: str = ""


def timeline(app: RegistrationApplication) -> list[Step]:
    """Status steps for the applicant, derived from the review trail.

    v3 inferred the rejecting stage from the final status and showed
    "E-Admin rejected" when a Senior E-Admin rejected after a first approval.
    Deriving it from the stored reviews makes that impossible.
    """
    steps = [Step("Application submitted", "done", app.convener_email, app.submitted_at)]
    by_stage = {r.stage: r for r in app.reviews}
    halted = waiting = False
    for stage in (ReviewStage.E_ADMIN, ReviewStage.SENIOR):
        r = by_stage.get(stage)
        if r is not None:
            state = "approved" if r.decision is ReviewDecision.APPROVE else "rejected"
            steps.append(Step(stage.label, state, r.reviewer_email, r.created_at, r.notes))
            halted = halted or r.decision is ReviewDecision.REJECT
        elif halted:
            steps.append(Step(stage.label, "skipped"))
        elif not waiting:
            steps.append(Step(stage.label, "waiting"))
            waiting = True
        else:
            steps.append(Step(stage.label, "upcoming"))
    return steps


def latest_for(db: Session, email: str) -> RegistrationApplication | None:
    return db.scalar(
        select(RegistrationApplication)
        .where(
            RegistrationApplication.convener_email == email,
            RegistrationApplication.email_verified.is_(True),
        )
        .order_by(RegistrationApplication.id.desc())
        .limit(1)
    )
