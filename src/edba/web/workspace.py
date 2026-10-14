"""Data-user workspaces: dashboards, course info, connectors, student services, theses."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from starlette.datastructures import UploadFile as StarletteUpload

from edba import authz
from edba.errors import DomainError, Forbidden
from edba.models import SERVICES, Organization, Role, ServiceKind, ThesisMode
from edba.services import catalog, courses, usage, workspaces
from edba.services.connector import UploadedFile
from edba.web.deps import Ctx, attempt, ctx, flash, redirect, role_ctx

router = APIRouter()

MEMBER = role_ctx(Role.MEMBER)


@dataclass
class Tile:
    href: str
    title: str
    summary: str
    icon: str
    tag: str = ""


def _org(c: Ctx, slug: str) -> Organization:
    return workspaces.by_slug(c.db, slug)


def tiles(c: Ctx, org: Organization) -> list[Tile]:
    """The buttons in a workspace's "available services" area, per the v3 spec section f."""
    level = authz.effective_level(c.user, org)
    home = authz.is_home(c.user, org)
    out: list[Tile] = []
    for svc in catalog.active_services(c.db, org):
        spec = svc.spec
        if level < spec.min_level:
            continue
        price = (
            f"{svc.price_cents / 100:g} quota / use"
            if spec.charging and svc.price_cents
            else "free"
        )
        if svc.kind is ServiceKind.THESIS:
            price = (
                ("download " + price) if svc.thesis_mode is ThesisMode.DOWNLOAD else "display only"
            )
        icon = {
            "course-info": "book",
            "identity-auth": "id",
            "gpa-record": "chart",
            "thesis": "doc",
        }
        href = {
            ServiceKind.COURSE_INFO: f"/w/{org.slug}/courses",
            ServiceKind.THESIS: f"/w/{org.slug}/thesis",
        }.get(svc.kind, f"/w/{org.slug}/s/{svc.kind.value}")
        out.append(Tile(href, spec.title, spec.summary, icon[svc.kind.value], price))
        if svc.kind is ServiceKind.COURSE_INFO and home and level >= 3:
            out.append(
                Tile(
                    f"/w/{org.slug}/courses/manage",
                    "Course Configurations",
                    "Add, edit and retire courses.",
                    "edit",
                    "provider",
                )
            )
    if home and level >= 3:
        out.append(
            Tile(
                f"/w/{org.slug}/connectors",
                "API Configurations",
                "Connect services to your campus systems.",
                "plug",
                "provider",
            )
        )
    if home:
        out.append(
            Tile("/workspaces", "Workspaces", "Browse other organizations' public data.", "globe")
        )
    out.append(Tile("/help", "Seek Help", "Ask the E-DBA technical admins.", "help"))
    return out


@router.get("/workspaces")
def directory(c: Ctx = Depends(MEMBER), q: str = ""):
    orgs = workspaces.directory(c.db, q)
    template = (
        "ws/_directory_grid.html" if c.request.headers.get("HX-Request") else "ws/directory.html"
    )
    return c.render(template, orgs=orgs, q=q)


@router.get("/w/{slug}")
def dashboard(slug: str, c: Ctx = Depends(MEMBER)):
    org = _org(c, slug)
    return c.render(
        "ws/dashboard.html",
        org=org,
        tiles=tiles(c, org),
        level=authz.effective_level(c.user, org),
        home=authz.is_home(c.user, org),
    )


# ------------------------------------------------------------------ courses


@router.get("/w/{slug}/courses")
def course_list(slug: str, c: Ctx = Depends(MEMBER), q: str = ""):
    org = _org(c, slug)
    authz.require_use(c.user, org, ServiceKind.COURSE_INFO)
    svc = catalog.get_service(c.db, org, ServiceKind.COURSE_INFO)
    if svc is None:
        raise Forbidden("Course Information is not offered in this workspace.")
    rows = courses.search(c.db, org, q)
    template = "ws/_course_rows.html" if c.request.headers.get("HX-Request") else "ws/courses.html"
    return c.render(template, org=org, courses=rows, q=q)


@router.get("/w/{slug}/courses/manage")
def course_manage(slug: str, c: Ctx = Depends(MEMBER), edit: int | None = None):
    org = _org(c, slug)
    authz.require_provider(c.user, org)
    rows = courses.search(c.db, org, include_inactive=True)
    current = courses.get(c.db, org, edit) if edit else None
    return c.render("ws/courses_manage.html", org=org, courses=rows, current=current)


@router.post("/w/{slug}/courses/manage")
def course_save(
    slug: str,
    c: Ctx = Depends(MEMBER),
    course_id: int | None = Form(None),
    op: str = Form("save"),
    code: str = Form(""),
    title: str = Form(""),
    description: str = Form(""),
    units: str = Form("3"),
    active: str = Form(""),
):
    org = _org(c, slug)
    authz.require_provider(c.user, org)
    is_active = active in ("on", "true", "1", "active")
    with attempt(c.request):
        if op == "delete" and course_id:
            courses.delete(c.db, c.user, org, course_id)
            flash(c.request, "Course deleted.")
        elif course_id:
            courses.update(
                c.db,
                c.user,
                org,
                course_id,
                code=code,
                title=title,
                description=description,
                units=units,
                active=is_active,
            )
            flash(c.request, "Course updated.")
        else:
            co = courses.create(
                c.db,
                c.user,
                org,
                code=code,
                title=title,
                description=description,
                units=units,
                active=is_active,
            )
            flash(c.request, f"Course {co.code} created ({'active' if co.active else 'inactive'}).")
    return redirect(f"/w/{slug}/courses/manage")


# ------------------------------------------------------------------ connectors


@router.get("/w/{slug}/connectors")
def connectors(slug: str, c: Ctx = Depends(MEMBER)):
    org = _org(c, slug)
    authz.require_provider(c.user, org)
    rows = []
    for svc in catalog.org_services(c.db, org):
        if svc.spec.operations:
            eps = catalog.endpoints(c.db, org, svc.kind)
            last = max((e.updated_at for e in eps.values()), default=None)
            rows.append((svc, catalog.is_active(c.db, svc), last))
    return c.render("ws/connectors.html", org=org, rows=rows)


DEFAULT_SCHEMAS = {
    (ServiceKind.IDENTITY_AUTH, "query"): (
        '{"name": "string", "id": "string", "photo": "file"}',
        '{"status": "string"}',
    ),
    (ServiceKind.GPA_RECORD, "query"): (
        '{"name": "string", "id": "string"}',
        '{"name": "string", "enroll_year": "string", "graduation_year": "string", "gpa": "float"}',
    ),
    (ServiceKind.THESIS, "search"): (
        '{"keywords": "string"}',
        '{"title": "string", "abstract": "string"}',
    ),
    (ServiceKind.THESIS, "download"): ('{"title": "string"}', ""),
}


@router.get("/w/{slug}/connectors/{kind}")
def connector_form(slug: str, kind: str, c: Ctx = Depends(MEMBER)):
    org = _org(c, slug)
    authz.require_provider(c.user, org)
    k = ServiceKind(kind)
    eps = catalog.endpoints(c.db, org, k)
    import json

    forms = []
    for op in SERVICES[k].operations:
        ep = eps.get(op)
        din, dout = DEFAULT_SCHEMAS[(k, op)]
        forms.append(
            {
                "op": op,
                "base_url": ep.base_url if ep else "",
                "path": ep.path if ep else "",
                "method": ep.method if ep else ("GET" if op == "download" else "POST"),
                "input": json.dumps(ep.input_schema) if ep else din,
                "output": (json.dumps(ep.output_schema) if ep.output_schema else "")
                if ep
                else dout,
                "configured": ep is not None,
            }
        )
    return c.render("ws/connector_form.html", org=org, spec=SERVICES[k], forms=forms)


@router.post("/w/{slug}/connectors/{kind}")
def connector_save(
    slug: str,
    kind: str,
    c: Ctx = Depends(MEMBER),
    operation: str = Form(...),
    base_url: str = Form(...),
    path: str = Form(...),
    method: str = Form("POST"),
    input_schema: str = Form(...),
    output_schema: str = Form(""),
):
    org = _org(c, slug)
    authz.require_provider(c.user, org)
    with attempt(c.request):
        catalog.save_endpoint(
            c.db,
            c.settings,
            c.user,
            org,
            ServiceKind(kind),
            operation,
            base_url=base_url,
            path=path,
            method=method,
            input_schema=input_schema,
            output_schema=output_schema,
        )
        flash(c.request, f"Saved the '{operation}' endpoint.")
    return redirect(f"/w/{slug}/connectors/{kind}")


# ------------------------------------------------------------------ student services


@router.get("/w/{slug}/s/{kind}")
def service_page(slug: str, kind: str, c: Ctx = Depends(MEMBER)):
    org = _org(c, slug)
    k = ServiceKind(kind)
    if k not in (ServiceKind.IDENTITY_AUTH, ServiceKind.GPA_RECORD):
        return redirect(f"/w/{slug}")
    authz.require_use(c.user, org, k)
    svc = catalog.get_service(c.db, org, k)
    if svc is None or not catalog.is_active(c.db, svc):
        raise Forbidden("This service is not available yet.")
    ep = catalog.endpoints(c.db, org, k)["query"]
    return c.render("ws/service.html", org=org, svc=svc, ep=ep, idem=uuid.uuid4().hex)


async def _files(
    request: Request, schema: dict[str, str]
) -> tuple[dict[str, str], dict[str, UploadedFile]]:
    form = await request.form()
    values: dict[str, str] = {}
    files: dict[str, UploadedFile] = {}
    for name, typ in schema.items():
        v = form.get(name)
        if typ == "file":
            if isinstance(v, StarletteUpload):
                data = await v.read()
                if data:
                    ctype = v.content_type or "application/octet-stream"
                    files[name] = UploadedFile(v.filename or name, data, ctype)
        else:
            values[name] = str(v or "")
    return values, files


@router.post("/w/{slug}/s/{kind}")
async def service_run(slug: str, kind: str, request: Request, c: Ctx = Depends(MEMBER)):
    org = _org(c, slug)
    k = ServiceKind(kind)
    ep = catalog.endpoints(c.db, org, k).get("query")
    error, result = None, None
    if ep is None:
        error = "This service is not configured."
    else:
        values, files = await _files(request, ep.input_schema)
        idem = str((await request.form()).get("idem") or "") or None
        try:
            result = usage.run_query(c.db, c.settings, c.user, org, k, values, files, idem)
        except DomainError as e:
            error = e.message
    return c.render("ws/_result.html", result=result, error=error)


@router.post("/w/{slug}/s/{kind}/batch")
async def service_batch(
    slug: str, kind: str, c: Ctx = Depends(MEMBER), file: UploadFile = File(...)
):
    org = _org(c, slug)
    data = await file.read()
    error, result = None, None
    try:
        result = usage.run_batch(
            c.db, c.settings, c.user, org, ServiceKind(kind), file.filename or "", data
        )
    except DomainError as e:
        error = e.message
    return c.render("ws/_result.html", result=result, error=error)


# ------------------------------------------------------------------ theses


@router.get("/w/{slug}/thesis")
def thesis(slug: str, c: Ctx = Depends(MEMBER), q: str = ""):
    org = _org(c, slug)
    error: str | None = None
    hits: list[usage.ThesisHit] = []
    svc = catalog.get_service(c.db, org, ServiceKind.THESIS)
    try:
        hits, svc = usage.thesis_search(c.db, c.settings, c.user, org, q)
    except DomainError as e:
        error = e.message
    template = "ws/_thesis_hits.html" if c.request.headers.get("HX-Request") else "ws/thesis.html"
    return c.render(
        template, org=org, svc=svc, hits=hits, q=q, error=error, home=authz.is_home(c.user, org)
    )


@router.post("/w/{slug}/thesis/download")
def thesis_download(slug: str, c: Ctx = Depends(MEMBER), title: str = Form(...), q: str = Form("")):
    org = _org(c, slug)
    try:
        pdf = usage.thesis_download(c.db, c.settings, c.user, org, title)
    except DomainError as e:
        flash(c.request, e.message, "error")
        return redirect(f"/w/{slug}/thesis?q={quote(q)}")
    fname = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in title)[:80] + ".pdf"
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/quota")
def quota(c: Ctx = Depends(ctx)):
    return c.render("ws/_quota.html")
