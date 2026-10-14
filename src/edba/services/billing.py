"""Settlement accounts, membership fees and idempotent transfers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edba.config import Settings
from edba.errors import DomainError, PaymentRequired
from edba.models import (
    BankAccount,
    FeeSchedule,
    LedgerEntry,
    LedgerKind,
    LedgerStatus,
    Organization,
    Role,
    User,
)
from edba.money import fmt, to_cents
from edba.security.crypto import decrypt, encrypt
from edba.services import audit, connector


def fee_schedule(db: Session) -> FeeSchedule:
    fs = db.get(FeeSchedule, 1)
    if fs is None:
        fs = FeeSchedule(id=1)
        db.add(fs)
        db.flush()
    return fs


def update_fees(db: Session, admin: User, level1: str, level2: str, level3: str) -> FeeSchedule:
    fs = fee_schedule(db)
    before = (fs.level1_cents, fs.level2_cents, fs.level3_cents)
    fs.level1_cents, fs.level2_cents, fs.level3_cents = (
        to_cents(level1),
        to_cents(level2),
        to_cents(level3),
    )
    fs.updated_by = admin.email
    audit.record(
        db,
        "fees.updated",
        f"Membership fees set to {fmt(fs.level1_cents)} / {fmt(fs.level2_cents)} per person / "
        f"{fmt(fs.level3_cents)} per person",
        actor=admin,
        before=list(before),
    )
    return fs


def bank_account(db: Session, org_id: str) -> BankAccount | None:
    return db.scalar(select(BankAccount).where(BankAccount.org_id == org_id))


def set_bank_account(
    db: Session,
    settings: Settings,
    convener: User,
    org: Organization,
    *,
    bank_name: str,
    account_name: str,
    account_no: str,
    password: str,
) -> BankAccount:
    fields = [bank_name.strip(), account_name.strip(), account_no.strip(), password]
    if not all(fields):
        raise DomainError("All four bank fields are required.")
    if not connector.bank_authenticate(settings, *fields):
        audit.record(db, "bank.rejected", "Bank account verification failed", actor=convener)
        raise DomainError("The bank could not verify these account details.")
    acct = bank_account(db, org.id)
    if acct is None:
        acct = BankAccount(org_id=org.id, secret_enc="")
        db.add(acct)
    acct.bank_name, acct.account_name, acct.account_no = fields[:3]
    acct.secret_enc = encrypt(settings, password)
    audit.record(
        db,
        "bank.verified",
        f"Settlement account set: {acct.bank_name}, {acct.account_name}, {acct.masked_no}",
        actor=convener,
    )
    db.flush()
    return acct


def _party(settings: Settings, acct: BankAccount | None) -> dict[str, str]:
    if acct is None:
        return {
            "bank": settings.system_bank_name,
            "name": settings.system_account_name,
            "account": settings.system_account_no,
        }
    return {"bank": acct.bank_name, "name": acct.account_name, "account": acct.account_no}


def transfer(
    db: Session,
    settings: Settings,
    *,
    kind: LedgerKind,
    payer: Organization,
    payee: Organization | None,
    amount_cents: int,
    memo: str,
    actor: User,
    idempotency_key: str | None = None,
) -> LedgerEntry:
    """Ask the bank to move money from ``payer`` to ``payee`` (None = E-DBA) exactly once."""
    key = idempotency_key or uuid.uuid4().hex
    done = db.scalar(select(LedgerEntry).where(LedgerEntry.idempotency_key == key))
    if done is not None:
        return done
    src = bank_account(db, payer.id)
    if src is None:
        raise PaymentRequired(f"{payer.short_name} has no settlement bank account yet.")
    dst = bank_account(db, payee.id) if payee else None
    if payee is not None and dst is None:
        raise PaymentRequired(f"{payee.short_name} has no settlement bank account yet.")
    s, d = _party(settings, src), _party(settings, dst)
    body = {
        "from_bank": s["bank"],
        "from_name": s["name"],
        "from_account": s["account"],
        "password": decrypt(settings, src.secret_enc),
        "to_bank": d["bank"],
        "to_name": d["name"],
        "to_account": d["account"],
        "amount": amount_cents / 100,
    }
    ok, reason = connector.bank_transfer(settings, body, key)
    entry = LedgerEntry(
        idempotency_key=key,
        kind=kind,
        payer_org_id=payer.id,
        payee_org_id=payee.id if payee else None,
        amount_cents=amount_cents,
        status=LedgerStatus.SETTLED if ok else LedgerStatus.FAILED,
        memo=memo[:300],
        gateway_reason=reason[:300],
        actor_email=actor.email,
    )
    db.add(entry)
    db.flush()
    audit.record(
        db,
        "payment.settled" if ok else "payment.failed",
        f"{fmt(amount_cents)} {payer.short_name} → {payee.short_name if payee else 'E-DBA'}: {memo}"
        + ("" if ok else f" (failed: {reason})"),
        actor=actor,
        org_id=payer.id,
        ledger_id=entry.id,
        amount_cents=amount_cents,
        payee=payee.id if payee else "e-dba",
    )
    return entry


@dataclass
class FeeLine:
    level: int
    unit_cents: int
    per_person: bool
    unpaid: int
    due_cents: int
    paid: bool


def membership_quote(db: Session, org: Organization) -> list[FeeLine]:
    fs = fee_schedule(db)

    def unpaid(level: int) -> int:
        return (
            db.scalar(
                select(func.count())
                .select_from(User)
                .where(
                    User.org_id == org.id,
                    User.role == Role.MEMBER,
                    User.access_level == level,
                    User.fee_paid.is_(False),
                )
            )
            or 0
        )

    lines = [
        FeeLine(
            1, fs.level1_cents, False, 0, 0 if org.level1_paid else fs.level1_cents, org.level1_paid
        )
    ]
    for level in (2, 3):
        n = unpaid(level)
        unit = fs.for_level(level)
        lines.append(FeeLine(level, unit, True, n, n * unit, n == 0))
    return lines


def pay_membership(
    db: Session,
    settings: Settings,
    convener: User,
    org: Organization,
    level: int,
    idempotency_key: str | None = None,
) -> LedgerEntry | None:
    line = next((x for x in membership_quote(db, org) if x.level == level), None)
    if line is None:
        raise DomainError("Unknown access level.")
    if line.paid:
        raise DomainError(f"Nothing to pay for level {level}.")
    entry = None
    if line.due_cents > 0:
        entry = transfer(
            db,
            settings,
            kind=LedgerKind.MEMBERSHIP,
            payer=org,
            payee=None,
            amount_cents=line.due_cents,
            memo=f"Membership fee, access level {level}"
            + (f", {line.unpaid} member(s)" if line.per_person else ""),
            actor=convener,
            idempotency_key=idempotency_key,
        )
        if entry.status is not LedgerStatus.SETTLED:
            raise PaymentRequired(f"Payment failed: {entry.gateway_reason}")
    if level == 1:
        org.level1_paid = True
        for u in db.scalars(
            select(User).where(
                User.org_id == org.id, User.access_level == 1, User.role == Role.MEMBER
            )
        ):
            u.fee_paid = True
    else:
        for u in db.scalars(
            select(User).where(
                User.org_id == org.id,
                User.role == Role.MEMBER,
                User.access_level == level,
                User.fee_paid.is_(False),
            )
        ):
            u.fee_paid = True
    audit.record(
        db,
        "fees.paid",
        f"Level {level} membership fee paid ({fmt(line.due_cents)})",
        actor=convener,
        level=level,
        amount_cents=line.due_cents,
    )
    return entry


def ledger(db: Session, org: Organization | None = None, limit: int = 100) -> list[LedgerEntry]:
    stmt = select(LedgerEntry).order_by(LedgerEntry.id.desc()).limit(limit)
    if org is not None:
        stmt = stmt.where(
            (LedgerEntry.payer_org_id == org.id) | (LedgerEntry.payee_org_id == org.id)
        )
    return list(db.scalars(stmt))
