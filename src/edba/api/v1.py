"""JSON API (``/api/v1``) with bearer tokens, for scripts and other campus systems.

Sign in with the same emailed one-time codes as the web UI::

    POST /api/v1/auth/code   {"email": "..."}
    POST /api/v1/auth/token  {"email": "...", "code": "123456"}  -> {"access_token": ...}
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from edba import __version__, authz
from edba.config import Settings
from edba.db import utcnow
from edba.models import SERVICES, Role, ServiceKind, ThesisMode, User
from edba.services import audit, auth, catalog, courses, usage, workspaces
from edba.web.deps import get_db, get_settings

router = APIRouter(prefix="/api/v1", tags=["api"])
bearer = HTTPBearer(auto_error=False)


# ------------------------------------------------------------------ schemas


class CodeRequest(BaseModel):
    email: str


class TokenRequest(BaseModel):
    email: str
    code: str = Field(min_length=6, max_length=6)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int


class Me(BaseModel):
    email: str
    name: str
    role: str
    organization: str | None
    access_level: int | None
    quota: float | None


class WorkspaceOut(BaseModel):
    slug: str
    full_name: str
    short_name: str


class ServiceOut(BaseModel):
    kind: str
    title: str
    price: float
    thesis_mode: str | None
    input_schema: dict[str, str] | None


class CourseOut(BaseModel):
    code: str
    title: str
    description: str
    units: int


class QueryIn(BaseModel):
    values: dict[str, str]


class QueryOut(BaseModel):
    rows: list[dict[str, Any]]
    charged: float
    quota_left: float


class SearchIn(BaseModel):
    keywords: str


class ThesisOut(BaseModel):
    title: str
    abstract: str
    downloadable: bool
    price: float


class DownloadIn(BaseModel):
    title: str


class ChainOut(BaseModel):
    ok: bool
    checked: int
    broken_at: int | None
    reason: str


# ------------------------------------------------------------------ auth


def _issue(settings: Settings, user: User) -> Token:
    exp = utcnow() + timedelta(minutes=settings.token_ttl_minutes)
    tok = jwt.encode({"sub": user.id, "exp": exp, "aud": "edba-api"}, settings.secret_key, "HS256")
    return Token(access_token=tok, expires_in=settings.token_ttl_minutes * 60)


def api_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if creds is None:
        raise HTTPException(401, "Missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = jwt.decode(creds.credentials, settings.secret_key, ["HS256"], audience="edba-api")
    except jwt.PyJWTError as e:
        raise HTTPException(401, "Invalid or expired token") from e
    user = db.get(User, claims["sub"])
    if user is None or not user.is_active:
        raise HTTPException(401, "Unknown user")
    return user


@router.get("/healthz", tags=["meta"])
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.post("/auth/code", status_code=202)
def request_code(
    body: CodeRequest, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> dict[str, str]:
    email = auth.request_login_code(db, settings, body.email)
    return {"detail": f"Code sent to {email}"}


@router.post("/auth/token")
def token(
    body: TokenRequest, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> Token:
    user = auth.complete_login(db, settings, body.email, body.code)
    return _issue(settings, user)


@router.get("/me")
def me(user: User = Depends(api_user)) -> Me:
    member = user.role is Role.MEMBER
    return Me(
        email=user.email,
        name=user.name,
        role=user.role.value,
        organization=user.organization.short_name if user.organization else None,
        access_level=user.access_level if member else None,
        quota=user.quota_cents / 100 if member else None,
    )


# ------------------------------------------------------------------ workspaces


@router.get("/workspaces")
def list_workspaces(
    q: str = "", user: User = Depends(api_user), db: Session = Depends(get_db)
) -> list[WorkspaceOut]:
    return [
        WorkspaceOut(slug=o.slug, full_name=o.full_name, short_name=o.short_name)
        for o in workspaces.directory(db, q)
    ]


@router.get("/workspaces/{slug}/services")
def list_services(
    slug: str, user: User = Depends(api_user), db: Session = Depends(get_db)
) -> list[ServiceOut]:
    org = workspaces.by_slug(db, slug)
    out = []
    for svc in catalog.active_services(db, org):
        if not authz.may_use(user, org, svc.kind):
            continue
        eps = catalog.endpoints(db, org, svc.kind)
        q = eps.get("query")
        out.append(
            ServiceOut(
                kind=svc.kind.value,
                title=svc.spec.title,
                price=svc.price_cents / 100,
                thesis_mode=svc.thesis_mode.value if svc.kind is ServiceKind.THESIS else None,
                input_schema=q.input_schema if q else None,
            )
        )
    return out


@router.get("/workspaces/{slug}/courses")
def list_courses(
    slug: str, q: str = "", user: User = Depends(api_user), db: Session = Depends(get_db)
) -> list[CourseOut]:
    org = workspaces.by_slug(db, slug)
    authz.require_use(user, org, ServiceKind.COURSE_INFO)
    if catalog.get_service(db, org, ServiceKind.COURSE_INFO) is None:
        raise HTTPException(404, "Course Information is not offered here")
    return [
        CourseOut(code=c.code, title=c.title, description=c.description, units=c.units)
        for c in courses.search(db, org, q)
    ]


@router.post("/workspaces/{slug}/services/{kind}/query")
def query(
    slug: str,
    kind: ServiceKind,
    body: QueryIn,
    user: User = Depends(api_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    idempotency_key: str | None = Header(None),
) -> QueryOut:
    org = workspaces.by_slug(db, slug)
    r = usage.run_query(db, settings, user, org, kind, body.values, None, idempotency_key)
    return QueryOut(rows=r.rows, charged=r.charged_cents / 100, quota_left=user.quota_cents / 100)


@router.post("/workspaces/{slug}/thesis/search")
def thesis_search(
    slug: str,
    body: SearchIn,
    user: User = Depends(api_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[ThesisOut]:
    org = workspaces.by_slug(db, slug)
    hits, svc = usage.thesis_search(db, settings, user, org, body.keywords)
    dl = svc.thesis_mode is ThesisMode.DOWNLOAD
    return [
        ThesisOut(title=h.title, abstract=h.abstract, downloadable=dl, price=svc.price_cents / 100)
        for h in hits
    ]


@router.post(
    "/workspaces/{slug}/thesis/download",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def thesis_download(
    slug: str,
    body: DownloadIn,
    user: User = Depends(api_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    idempotency_key: str | None = Header(None),
) -> Response:
    org = workspaces.by_slug(db, slug)
    pdf = usage.thesis_download(db, settings, user, org, body.title, idempotency_key)
    return Response(pdf, media_type="application/pdf")


# ------------------------------------------------------------------ audit


@router.get("/audit/verify")
def audit_verify(user: User = Depends(api_user), db: Session = Depends(get_db)) -> ChainOut:
    authz.require_role(user, Role.T_ADMIN)
    r = audit.verify_chain(db)
    return ChainOut(ok=r.ok, checked=r.checked, broken_at=r.broken_at, reason=r.reason)


@router.get("/audit/events")
def audit_events(
    request: Request,
    q: str = "",
    action: str = "",
    limit: int = 100,
    user: User = Depends(api_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    if user.role is Role.T_ADMIN:
        org_id = None
    elif user.role is Role.CONVENER:
        org_id = user.org_id
    else:
        authz.require_role(user, Role.T_ADMIN, Role.CONVENER)
        org_id = None
    events = audit.search(db, org_id=org_id, q=q, action=action, limit=min(limit, 500))
    return [
        {
            "id": e.id,
            "at": e.at.isoformat(),
            "actor": e.actor_email,
            "action": e.action,
            "summary": e.summary,
            "org_id": e.org_id,
            "hash": e.hash,
        }
        for e in events
    ]


@router.get("/catalog", tags=["meta"])
def service_catalog() -> list[dict[str, Any]]:
    return [
        {
            "kind": s.kind.value,
            "title": s.title,
            "min_level": s.min_level,
            "charging": s.charging,
            "operations": list(s.operations),
            "public": s.public,
        }
        for s in SERVICES.values()
    ]
