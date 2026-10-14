"""Bank accounts, the membership-fee schedule and the settlement ledger."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from edba.db import Base, utcnow


class BankAccount(Base):
    """An organization's verified settlement account. The password is encrypted at rest."""

    __tablename__ = "bank_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), unique=True
    )
    bank_name: Mapped[str] = mapped_column(String(120))
    account_name: Mapped[str] = mapped_column(String(120))
    account_no: Mapped[str] = mapped_column(String(64))
    secret_enc: Mapped[str] = mapped_column(Text)
    verified_at: Mapped[datetime] = mapped_column(default=utcnow)

    @property
    def masked_no(self) -> str:
        return "•••• " + self.account_no[-4:]


class FeeSchedule(Base):
    """Membership fees, editable by E-Admins. Single row (id = 1)."""

    __tablename__ = "fee_schedule"

    id: Mapped[int] = mapped_column(primary_key=True)
    level1_cents: Mapped[int] = mapped_column(default=1000_00)  # once per organization
    level2_cents: Mapped[int] = mapped_column(default=100_00)  # per level-2 member
    level3_cents: Mapped[int] = mapped_column(default=0)  # per level-3 member
    updated_by: Mapped[str] = mapped_column(String(254), default="system")
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    def for_level(self, level: int) -> int:
        return {1: self.level1_cents, 2: self.level2_cents, 3: self.level3_cents}[level]


class LedgerKind(enum.StrEnum):
    MEMBERSHIP = "membership"
    SERVICE = "service"


class LedgerStatus(enum.StrEnum):
    SETTLED = "settled"
    FAILED = "failed"


class LedgerEntry(Base):
    """Every transfer E-DBA asks the bank to make, keyed by an idempotency key.

    Replaying a request with the same key returns the stored entry instead of
    moving money twice.
    """

    __tablename__ = "ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[LedgerKind] = mapped_column(Enum(LedgerKind, native_enum=False, length=20))
    payer_org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    payee_org_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL")
    )  # None = the E-DBA system account
    amount_cents: Mapped[int]
    status: Mapped[LedgerStatus] = mapped_column(Enum(LedgerStatus, native_enum=False, length=10))
    memo: Mapped[str] = mapped_column(String(300), default="")
    gateway_reason: Mapped[str] = mapped_column(String(300), default="")
    actor_email: Mapped[str] = mapped_column(String(254), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
