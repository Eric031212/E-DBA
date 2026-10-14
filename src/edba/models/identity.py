"""Organizations, users, sign-in challenges and the registration workflow."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from edba.db import Base, utcnow


def new_id() -> str:
    return uuid.uuid4().hex


class Role(enum.StrEnum):
    T_ADMIN = "t_admin"  # technical admin: help desk, E-Admin accounts, system logs
    E_ADMIN = "e_admin"  # business admin: first-stage review, policies, fees
    SENIOR_E_ADMIN = "senior_e_admin"  # final-stage review (+ everything an E-Admin does)
    CONVENER = "convener"  # organization owner
    MEMBER = "member"  # data user, access level 1..3
    APPLICANT = "applicant"  # has a pending / rejected application, no organization yet

    @property
    def label(self) -> str:
        return {
            "t_admin": "T-Admin",
            "e_admin": "E-Admin",
            "senior_e_admin": "Senior E-Admin",
            "convener": "O-Convener",
            "member": "Data user",
            "applicant": "Applicant",
        }[self.value]

    @property
    def is_e_admin(self) -> bool:
        return self in (Role.E_ADMIN, Role.SENIOR_E_ADMIN)


ACCESS_LEVELS = {
    1: "Public data access",
    2: "Private data consumption",
    3: "Private data provision",
}


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    full_name: Mapped[str] = mapped_column(String(200))
    short_name: Mapped[str] = mapped_column(String(50), unique=True)
    level1_paid: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    members: Mapped[list[User]] = relationship(back_populates="organization")
    domain_rules: Mapped[list[DomainRule]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )

    @property
    def slug(self) -> str:
        return self.short_name.lower()


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    contact: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=20))
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    access_level: Mapped[int] = mapped_column(Integer, default=1)
    quota_cents: Mapped[int] = mapped_column(Integer, default=0)
    fee_paid: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_login_at: Mapped[datetime | None]

    organization: Mapped[Organization | None] = relationship(back_populates="members")

    @property
    def display_name(self) -> str:
        return self.name or self.email.split("@")[0]


class DomainRule(Base):
    """A wildcard member-list row (``*@mail.uic.edu.cn``) that admits a whole email domain."""

    __tablename__ = "domain_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    domain: Mapped[str] = mapped_column(String(200), unique=True)  # stored as "@mail.uic.edu.cn"
    access_level: Mapped[int] = mapped_column(default=1)
    quota_cents: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    organization: Mapped[Organization] = relationship(back_populates="domain_rules")


class OtpChallenge(Base):
    """A one-time sign-in / verification code. Only a salted hash of the code is stored."""

    __tablename__ = "otp_challenges"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), index=True)
    purpose: Mapped[str] = mapped_column(String(20))  # "login" | "apply"
    code_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime]
    attempts: Mapped[int] = mapped_column(default=0)
    consumed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ApplicationStatus(enum.StrEnum):
    PENDING = "pending"  # waiting for an E-Admin
    FIRST_APPROVED = "first_approved"  # waiting for a Senior E-Admin
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ReviewStage(enum.StrEnum):
    E_ADMIN = "e_admin"
    SENIOR = "senior"

    @property
    def label(self) -> str:
        return "E-Admin Review" if self is ReviewStage.E_ADMIN else "Senior E-Admin Review"


class ReviewDecision(enum.StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class RegistrationApplication(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_full_name: Mapped[str] = mapped_column(String(200))
    org_short_name: Mapped[str] = mapped_column(String(50))
    convener_email: Mapped[str] = mapped_column(String(254), index=True)
    convener_name: Mapped[str] = mapped_column(String(120), default="")
    proof_path: Mapped[str] = mapped_column(String(400))
    proof_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, native_enum=False, length=20), default=ApplicationStatus.PENDING
    )
    email_verified: Mapped[bool] = mapped_column(default=False)
    submitted_at: Mapped[datetime] = mapped_column(default=utcnow)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"))

    reviews: Mapped[list[ApplicationReview]] = relationship(
        back_populates="application", order_by="ApplicationReview.id", cascade="all, delete-orphan"
    )


class ApplicationReview(Base):
    """Append-only review trail; the applicant's status timeline is derived from it."""

    __tablename__ = "application_reviews"
    __table_args__ = (UniqueConstraint("application_id", "stage"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    stage: Mapped[ReviewStage] = mapped_column(Enum(ReviewStage, native_enum=False, length=20))
    decision: Mapped[ReviewDecision] = mapped_column(
        Enum(ReviewDecision, native_enum=False, length=10)
    )
    reviewer_email: Mapped[str] = mapped_column(String(254))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    application: Mapped[RegistrationApplication] = relationship(back_populates="reviews")
