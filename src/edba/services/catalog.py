"""Which services an organization offers, at what price, and how they are wired up."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edba.config import Settings
from edba.errors import Conflict, DomainError, NotFound
from edba.models import (
    SERVICES,
    ApiEndpoint,
    Organization,
    OrgService,
    ServiceKind,
    ThesisMode,
    User,
)
from edba.money import fmt, to_cents
from edba.services import audit, billing, connector


def org_services(db: Session, org: Organization) -> list[OrgService]:
    rows = db.scalars(select(OrgService).where(OrgService.org_id == org.id))
    order = list(SERVICES)
    return sorted(rows, key=lambda s: order.index(s.kind))


def get_service(db: Session, org: Organization, kind: ServiceKind) -> OrgService | None:
    return db.scalar(select(OrgService).where(OrgService.org_id == org.id, OrgService.kind == kind))


def endpoints(db: Session, org: Organization, kind: ServiceKind) -> dict[str, ApiEndpoint]:
    rows = db.scalars(
        select(ApiEndpoint).where(ApiEndpoint.org_id == org.id, ApiEndpoint.kind == kind)
    )
    return {e.operation: e for e in rows}


def is_active(db: Session, svc: OrgService) -> bool:
    """Services backed by an external API stay inactive until a level-3 provider configures it."""
    ops = svc.spec.operations
    if not ops:
        return True
    have = endpoints(db, db.get(Organization, svc.org_id), svc.kind)  # type: ignore[arg-type]
    return all(op in have for op in ops)


def active_services(db: Session, org: Organization) -> list[OrgService]:
    return [s for s in org_services(db, org) if is_active(db, s)]


def add_service(
    db: Session,
    convener: User,
    org: Organization,
    kind: ServiceKind,
    price: str = "0",
    thesis_mode: ThesisMode = ThesisMode.DISPLAY_ONLY,
) -> OrgService:
    spec = SERVICES[kind]
    if get_service(db, org, kind):
        raise Conflict(f"{spec.title} is already in your workspace.")
    if spec.charging and billing.bank_account(db, org.id) is None:
        raise DomainError("Set up your organization's bank account before adding paid services.")
    svc = OrgService(
        org_id=org.id,
        kind=kind,
        price_cents=to_cents(price) if spec.charging else 0,
        thesis_mode=thesis_mode,
    )
    db.add(svc)
    db.flush()
    audit.record(
        db,
        "service.added",
        f"Added {spec.title}" + (f" at {fmt(svc.price_cents)} per use" if spec.charging else ""),
        actor=convener,
        kind=kind.value,
    )
    return svc


def update_service(
    db: Session,
    convener: User,
    org: Organization,
    kind: ServiceKind,
    price: str | None,
    thesis_mode: ThesisMode | None,
) -> OrgService:
    svc = get_service(db, org, kind)
    if svc is None:
        raise NotFound("Service not found.")
    if price is not None and svc.spec.charging:
        svc.price_cents = to_cents(price)
    if thesis_mode is not None and kind is ServiceKind.THESIS:
        svc.thesis_mode = thesis_mode
    audit.record(
        db,
        "service.updated",
        f"Updated {svc.spec.title}: price {fmt(svc.price_cents)}"
        + (f", {svc.thesis_mode.value.replace('_', ' ')}" if kind is ServiceKind.THESIS else ""),
        actor=convener,
        kind=kind.value,
    )
    return svc


def remove_service(db: Session, convener: User, org: Organization, kind: ServiceKind) -> None:
    svc = get_service(db, org, kind)
    if svc is None:
        raise NotFound("Service not found.")
    for ep in endpoints(db, org, kind).values():
        db.delete(ep)
    db.delete(svc)
    audit.record(db, "service.removed", f"Removed {svc.spec.title}", actor=convener)


def save_endpoint(
    db: Session,
    settings: Settings,
    provider: User,
    org: Organization,
    kind: ServiceKind,
    operation: str,
    *,
    base_url: str,
    path: str,
    method: str,
    input_schema: str,
    output_schema: str,
) -> ApiEndpoint:
    spec = SERVICES[kind]
    if get_service(db, org, kind) is None:
        raise DomainError(f"{spec.title} has not been added by your O-Convener.")
    if operation not in spec.operations:
        raise DomainError(f"{spec.title} has no '{operation}' operation.")
    method = method.upper()
    if method not in ("GET", "POST"):
        raise DomainError("Method must be GET or POST.")
    base_url = base_url.strip()
    connector.check_url(settings, base_url)
    path = "/" + path.strip().lstrip("/")
    ins = connector.parse_schema(input_schema)
    outs = connector.parse_schema(output_schema, allow_empty=operation == "download")
    ep = endpoints(db, org, kind).get(operation)
    if ep is None:
        ep = ApiEndpoint(org_id=org.id, kind=kind, operation=operation, base_url="", path="")
        db.add(ep)
    ep.base_url, ep.path, ep.method = base_url, path, method
    ep.input_schema, ep.output_schema = ins, outs
    ep.updated_by = provider.email
    db.flush()
    audit.record(
        db,
        "connector.saved",
        f"{spec.title} / {operation}: {method} {ep.url}",
        actor=provider,
        kind=kind.value,
        operation=operation,
    )
    return ep


def provider_counts(db: Session) -> dict[str, int]:
    """Number of organizations offering each service (for the landing page)."""
    rows = db.execute(select(OrgService.kind, func.count()).group_by(OrgService.kind))
    return {k.value: n for k, n in rows}
