"""Back office: T-Admin (accounts, logs, audit, help desk) and E-Admins (reviews, policies, fees)."""

from __future__ import annotations

from datetime import datetime, time

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from edba.models import (
    ApplicationStatus,
    HelpTicket,
    Organization,
    RegistrationApplication,
    ReviewDecision,
    Role,
    User,
)
from edba.services import admins, audit, billing, helpdesk, policies, registration
from edba.web.deps import Ctx, attempt, flash, redirect, role_ctx

router = APIRouter(prefix="/admin")

ANY_ADMIN = role_ctx(Role.T_ADMIN, Role.E_ADMIN, Role.SENIOR_E_ADMIN)
T_ADMIN = role_ctx(Role.T_ADMIN)
E_ADMIN = role_ctx(Role.E_ADMIN, Role.SENIOR_E_ADMIN)


def _count(c: Ctx, stmt) -> int:
    return c.db.scalar(stmt) or 0


@router.get("")
def home(c: Ctx = Depends(ANY_ADMIN)):
    db = c.db
    stats = {
        "orgs": _count(c, select(func.count()).select_from(Organization)),
        "members": _count(
            c, select(func.count()).select_from(User).where(User.role == Role.MEMBER)
        ),
        "queue": len(registration.queue(db, c.user)) if c.user.role.is_e_admin else 0,
        "pending_all": _count(
            c,
            select(func.count())
            .select_from(RegistrationApplication)
            .where(
                RegistrationApplication.email_verified.is_(True),
                RegistrationApplication.status.in_(
                    [ApplicationStatus.PENDING, ApplicationStatus.FIRST_APPROVED]
                ),
            ),
        ),
        "open_help": _count(
            c, select(func.count()).select_from(HelpTicket).where(HelpTicket.answer.is_(None))
        ),
    }
    chain = audit.verify_chain(db) if c.user.role is Role.T_ADMIN else None
    recent = audit.search(db, limit=8)
    return c.render("admin/home.html", stats=stats, chain=chain, recent=recent)


# ------------------------------------------------------------------ T-Admin


@router.get("/e-admins")
def e_admins(c: Ctx = Depends(T_ADMIN)):
    return c.render("admin/e_admins.html", admins=admins.listing(c.db))


@router.post("/e-admins")
def e_admin_create(
    c: Ctx = Depends(T_ADMIN),
    email: str = Form(...),
    name: str = Form(""),
    senior: bool = Form(False),
):
    with attempt(c.request):
        u = admins.create(c.db, c.user, email, name, senior)
        flash(c.request, f"{u.role.label} {u.email} created. They sign in with an emailed code.")
    return redirect("/admin/e-admins")


@router.post("/e-admins/{user_id}")
def e_admin_update(user_id: str, c: Ctx = Depends(T_ADMIN), op: str = Form(...)):
    with attempt(c.request):
        if op in ("promote", "demote"):
            admins.set_senior(c.db, c.user, user_id, op == "promote")
        elif op in ("enable", "disable"):
            admins.set_active(c.db, c.user, user_id, op == "enable")
        flash(c.request, "Account updated.")
    return redirect("/admin/e-admins")


def _day(s: str, end: bool = False) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return datetime.combine(d.date(), time.max if end else time.min).astimezone()


@router.get("/logs")
def logs(
    c: Ctx = Depends(T_ADMIN),
    q: str = "",
    action: str = "",
    org: str = "",
    date_from: str = "",
    date_to: str = "",
):
    orgs = list(c.db.scalars(select(Organization).order_by(Organization.short_name)))
    events = audit.search(
        c.db,
        org_id=org or None,
        q=q,
        action=action,
        date_from=_day(date_from),
        date_to=_day(date_to, end=True),
        limit=300,
    )
    names = {o.id: o.short_name for o in orgs}
    template = "admin/_log_rows.html" if c.request.headers.get("HX-Request") else "admin/logs.html"
    return c.render(
        template,
        events=events,
        actions=audit.actions(c.db),
        orgs=orgs,
        names=names,
        f={"q": q, "action": action, "org": org, "date_from": date_from, "date_to": date_to},
    )


@router.post("/audit/verify")
def audit_verify(c: Ctx = Depends(T_ADMIN)):
    rep = audit.verify_chain(c.db)
    if rep.ok:
        flash(c.request, f"Audit chain intact: {rep.checked} events verified.")
    else:
        flash(c.request, f"Audit chain BROKEN at event #{rep.broken_at}: {rep.reason}.", "error")
    return redirect("/admin")


@router.get("/help")
def help_queue(c: Ctx = Depends(T_ADMIN)):
    return c.render("admin/help.html", tickets=helpdesk.queue(c.db))


@router.post("/help/{ticket_id}")
def help_answer(ticket_id: int, c: Ctx = Depends(T_ADMIN), answer: str = Form(...)):
    with attempt(c.request):
        helpdesk.answer(c.db, c.settings, c.user, ticket_id, answer)
        flash(c.request, "Answer sent.")
    return redirect("/admin/help")


# ------------------------------------------------------------------ E-Admins


@router.get("/applications")
def applications(c: Ctx = Depends(ANY_ADMIN)):
    queue = registration.queue(c.db, c.user) if c.user.role.is_e_admin else []
    return c.render("admin/applications.html", queue=queue, all=registration.all_verified(c.db))


@router.get("/applications/{app_id}")
def application_detail(app_id: int, c: Ctx = Depends(ANY_ADMIN)):
    app = registration.get(c.db, app_id)
    if not app.email_verified:
        raise HTTPException(404)
    can_review = (app.status is ApplicationStatus.PENDING and c.user.role.is_e_admin) or (
        app.status is ApplicationStatus.FIRST_APPROVED
        and c.user.role is Role.SENIOR_E_ADMIN
        and all(r.reviewer_email != c.user.email for r in app.reviews)
    )
    return c.render(
        "admin/application.html", app=app, steps=registration.timeline(app), can_review=can_review
    )


@router.get("/applications/{app_id}/proof")
def application_proof(app_id: int, c: Ctx = Depends(ANY_ADMIN)):
    app = registration.get(c.db, app_id)
    path = c.settings.upload_dir / app.proof_path
    if not path.is_file():
        raise HTTPException(404, "File missing")
    return FileResponse(path, content_disposition_type="inline")


@router.post("/applications/{app_id}")
def application_review(
    app_id: int, c: Ctx = Depends(E_ADMIN), decision: str = Form(...), notes: str = Form("")
):
    with attempt(c.request):
        app = registration.review(c.db, c.settings, c.user, app_id, ReviewDecision(decision), notes)
        flash(c.request, f"Application #{app.id} is now {app.status.value.replace('_', ' ')}.")
        return redirect("/admin/applications")
    return redirect(f"/admin/applications/{app_id}")


@router.get("/policies")
def policy_admin(c: Ctx = Depends(ANY_ADMIN)):
    return c.render(
        "admin/policies.html", policies=policies.listing(c.db), can_edit=c.user.role.is_e_admin
    )


@router.post("/policies")
async def policy_create(
    c: Ctx = Depends(E_ADMIN),
    title: str = Form(...),
    summary: str = Form(""),
    file: UploadFile = File(...),
):
    data = await file.read()
    with attempt(c.request):
        p = policies.create(c.db, c.settings, c.user, title, summary, file.filename or "", data)
        flash(c.request, f"Published '{p.title}'.")
    return redirect("/admin/policies")


@router.post("/policies/{policy_id}")
async def policy_update(
    policy_id: int,
    c: Ctx = Depends(E_ADMIN),
    op: str = Form("revise"),
    title: str = Form(""),
    summary: str = Form(""),
    file: UploadFile | None = File(None),
):
    with attempt(c.request):
        if op == "archive":
            policies.archive(c.db, c.user, policy_id)
            flash(c.request, "Policy archived.")
        else:
            data = await file.read() if file and file.filename else None
            p = policies.revise(
                c.db,
                c.settings,
                c.user,
                policy_id,
                title,
                summary,
                file.filename if file else None,
                data,
            )
            flash(c.request, f"Updated '{p.title}'.")
    return redirect("/admin/policies")


@router.get("/policies/file/{version_id}")
def policy_file(version_id: int, c: Ctx = Depends(ANY_ADMIN)):
    v = policies.version(c.db, version_id)
    return FileResponse(
        c.settings.upload_dir / v.file_path,
        media_type="application/pdf",
        content_disposition_type="inline",
    )


@router.get("/fees")
def fees(c: Ctx = Depends(E_ADMIN)):
    return c.render(
        "admin/fees.html", fs=billing.fee_schedule(c.db), ledger=billing.ledger(c.db, limit=50)
    )


@router.post("/fees")
def fees_save(
    c: Ctx = Depends(E_ADMIN),
    level1: str = Form(...),
    level2: str = Form(...),
    level3: str = Form(...),
):
    with attempt(c.request):
        billing.update_fees(c.db, c.user, level1, level2, level3)
        flash(c.request, "Membership fees updated.")
    return redirect("/admin/fees")
