"""Using services: quota checks, outbound calls and settlement.

Charging rules (from the v3 specification, unchanged):

* Identity authentication and GPA records cost ``price`` per successful record,
  taken from the user's quota; the user's organization then pays E-DBA.
* Searching theses is free. Downloading a PDF costs the *provider's* price; the
  user's organization pays the providing organization (so downloads inside your
  own organization are a transfer to yourself, i.e. free apart from quota).
* Nothing is charged when the organization's API fails, and results are only
  released once the transfer has settled.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from edba import authz
from edba.config import Settings
from edba.errors import DomainError, Forbidden, NotFound, PaymentRequired, UpstreamError
from edba.models import (
    SERVICES,
    LedgerKind,
    LedgerStatus,
    Organization,
    OrgService,
    ServiceKind,
    ThesisMode,
    User,
)
from edba.money import fmt
from edba.services import audit, billing, catalog, connector
from edba.services.connector import UploadedFile
from edba.services.sheets import read_table


def _service(db: Session, user: User, org: Organization, kind: ServiceKind) -> OrgService:
    svc = catalog.get_service(db, org, kind)
    if svc is None or not catalog.is_active(db, svc):
        raise NotFound(f"{SERVICES[kind].title} is not available in this workspace.")
    authz.require_use(user, org, kind)
    return svc


def _home(db: Session, user: User) -> Organization:
    org = db.get(Organization, user.org_id) if user.org_id else None
    if org is None:
        raise Forbidden("Only data users of an organization can use services.")
    return org


def _check_quota(user: User, cost: int) -> None:
    if cost > user.quota_cents:
        raise PaymentRequired(
            f"This needs {fmt(cost)} of quota but you have {fmt(user.quota_cents)} left."
        )


def _settle(
    db: Session,
    settings: Settings,
    user: User,
    payee: Organization | None,
    cost: int,
    memo: str,
    key: str | None,
) -> None:
    """Take quota and pay. Raises (and charges nothing) if the bank refuses."""
    if cost <= 0:
        return
    payer = _home(db, user)
    entry = billing.transfer(
        db,
        settings,
        kind=LedgerKind.SERVICE,
        payer=payer,
        payee=payee,
        amount_cents=cost,
        memo=memo,
        actor=user,
        idempotency_key=key,
    )
    if entry.status is not LedgerStatus.SETTLED:
        raise PaymentRequired(f"Settlement failed: {entry.gateway_reason}")
    user.quota_cents -= cost


@dataclass
class QueryResult:
    fields: list[str]
    rows: list[dict[str, Any]]
    charged_cents: int
    failures: list[tuple[int, str]] = field(default_factory=list)


def _rows_of(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [d if isinstance(d, dict) else {"value": d} for d in data]
    if isinstance(data, dict):
        return [data]
    return [{"value": data}]


def run_query(
    db: Session,
    settings: Settings,
    user: User,
    org: Organization,
    kind: ServiceKind,
    values: dict[str, str],
    files: dict[str, UploadedFile] | None = None,
    idempotency_key: str | None = None,
) -> QueryResult:
    if kind not in (ServiceKind.IDENTITY_AUTH, ServiceKind.GPA_RECORD):
        raise DomainError("This service does not take queries.")
    svc = _service(db, user, org, kind)
    ep = catalog.endpoints(db, org, kind)["query"]
    _home(db, user)
    _check_quota(user, svc.price_cents)
    data = connector.call_json(settings, ep, values, files)
    rows = _rows_of(data)
    _settle(db, settings, user, None, svc.price_cents, f"{svc.spec.title} ×1", idempotency_key)
    audit.record(
        db,
        "service.used",
        f"{svc.spec.title} in {org.short_name}: 1 record, {fmt(svc.price_cents)}",
        actor=user,
        provider_org=org.id,
        kind=kind.value,
        records=1,
        charged_cents=svc.price_cents,
    )
    return QueryResult(list(ep.output_schema) or list(rows[0]), rows, svc.price_cents)


def run_batch(
    db: Session,
    settings: Settings,
    user: User,
    org: Organization,
    kind: ServiceKind,
    filename: str,
    sheet: bytes,
) -> QueryResult:
    """One call per spreadsheet row; only successful rows are charged."""
    svc = _service(db, user, org, kind)
    if not svc.spec.batch:
        raise DomainError("This service does not accept batch uploads.")
    ep = catalog.endpoints(db, org, kind)["query"]
    header, rows = read_table(filename, sheet)
    needed = [k for k, t in ep.input_schema.items() if t != "file"]
    missing = [k for k in needed if k not in header]
    if missing:
        raise DomainError(f"The spreadsheet is missing column(s): {', '.join(missing)}.")
    if not rows:
        raise DomainError("The spreadsheet has no data rows.")
    _home(db, user)
    _check_quota(user, svc.price_cents * len(rows))

    out: list[dict[str, Any]] = []
    failures: list[tuple[int, str]] = []
    for i, row in enumerate(rows, start=2):
        values = dict(zip(header, row, strict=True))
        try:
            data = connector.call_json(settings, ep, values)
            for r in _rows_of(data):
                out.append({"#": i, **{k: values.get(k, "") for k in needed}, **r})
        except (DomainError, UpstreamError) as e:
            failures.append((i, e.message))
    ok = len(rows) - len(failures)
    cost = svc.price_cents * ok
    digest = hashlib.sha256(sheet).hexdigest()[:16]
    _settle(db, settings, user, None, cost, f"{svc.spec.title} ×{ok} (batch {digest})", None)
    audit.record(
        db,
        "service.used",
        f"{svc.spec.title} in {org.short_name}: batch of {len(rows)}, {ok} ok, {fmt(cost)}",
        actor=user,
        provider_org=org.id,
        kind=kind.value,
        records=ok,
        failed=len(failures),
        charged_cents=cost,
    )
    fields = ["#", *needed, *[k for k in ep.output_schema if k not in needed]]
    return QueryResult(fields, out, cost, failures)


def _single(schema: dict[str, str], value: str) -> dict[str, str]:
    """Thesis operations take one text input, whatever the provider named it."""
    return {k: value for k, t in schema.items() if t != "file"}


@dataclass
class ThesisHit:
    title: str
    abstract: str
    extra: dict[str, Any]


def thesis_search(
    db: Session, settings: Settings, user: User, org: Organization, keywords: str
) -> tuple[list[ThesisHit], OrgService]:
    svc = _service(db, user, org, ServiceKind.THESIS)
    if not keywords.strip():
        return [], svc
    ep = catalog.endpoints(db, org, ServiceKind.THESIS)["search"]
    data = connector.call_json(settings, ep, _single(ep.input_schema, keywords))
    hits = []
    for r in _rows_of(data):
        title = str(r.get("title", "")).strip()
        if title:
            extra = {k: v for k, v in r.items() if k not in ("title", "abstract")}
            hits.append(ThesisHit(title, str(r.get("abstract", "")), extra))
    audit.record(
        db,
        "thesis.searched",
        f"Searched theses of {org.short_name} for '{keywords[:60]}' "
        f"({len(hits)} hit{'' if len(hits) == 1 else 's'})",
        actor=user,
        provider_org=org.id,
    )
    return hits, svc


def thesis_download(
    db: Session,
    settings: Settings,
    user: User,
    org: Organization,
    title: str,
    idempotency_key: str | None = None,
) -> bytes:
    svc = _service(db, user, org, ServiceKind.THESIS)
    if svc.thesis_mode is not ThesisMode.DOWNLOAD:
        raise Forbidden(f"{org.short_name} shares its theses as display-only.")
    if not title.strip():
        raise DomainError("Which thesis?")
    home = _home(db, user)
    _check_quota(user, svc.price_cents)
    if svc.price_cents > 0 and billing.bank_account(db, home.id) is None:
        raise PaymentRequired(f"{home.short_name} has no settlement bank account yet.")
    ep = catalog.endpoints(db, org, ServiceKind.THESIS)["download"]
    pdf = connector.call_pdf(settings, ep, _single(ep.input_schema, title))
    _settle(
        db, settings, user, org, svc.price_cents, f"Thesis download: {title[:120]}", idempotency_key
    )
    audit.record(
        db,
        "thesis.downloaded",
        f"Downloaded '{title[:80]}' from {org.short_name} ({fmt(svc.price_cents)})",
        actor=user,
        provider_org=org.id,
        charged_cents=svc.price_cents,
    )
    return pdf
