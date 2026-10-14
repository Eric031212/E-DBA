"""Landing page, sign-in, organization applications, policies, help and profile."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edba.config import Settings
from edba.errors import DomainError
from edba.models import Organization, OrgService, Role, User
from edba.services import auth, helpdesk, mail, policies, registration
from edba.web.deps import (
    Ctx,
    attempt,
    ctx,
    current_user,
    flash,
    get_db,
    get_settings,
    home_url,
    redirect,
    render,
)

router = APIRouter()


@router.get("/")
def landing(
    request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)
):
    stats = {
        "orgs": db.scalar(select(func.count()).select_from(Organization)) or 0,
        "members": db.scalar(select(func.count()).select_from(User).where(User.role == Role.MEMBER))
        or 0,
        "services": db.scalar(select(func.count()).select_from(OrgService)) or 0,
    }
    return render(request, "landing.html", user=user, stats=stats)


@router.get("/dashboard")
def dashboard(c: Ctx = Depends(ctx)):
    return redirect(home_url(c.user))


# ------------------------------------------------------------------ sign-in


@router.get("/login")
def login_form(request: Request, user: User | None = Depends(current_user)):
    if user:
        return redirect(home_url(user))
    return render(request, "auth/login.html")


@router.post("/login")
def login_send(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        normalized = auth.request_login_code(db, settings, email)
    except DomainError as e:
        flash(request, e.message, "error")
        return render(request, "auth/login.html", email=email, status_code=400)
    request.session["pending_email"] = normalized
    flash(request, f"We sent a 6-digit code to {normalized}. It expires in 5 minutes.", "info")
    return redirect("/login/verify")


@router.get("/login/verify")
def login_verify_form(request: Request):
    email = request.session.get("pending_email")
    if not email:
        return redirect("/login")
    return render(request, "auth/verify.html", email=email, action="/login/verify")


@router.post("/login/verify")
def login_verify(
    request: Request,
    code: str = Form(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    email = request.session.get("pending_email")
    if not email:
        return redirect("/login")
    try:
        user = auth.complete_login(db, settings, email, code)
    except DomainError as e:
        flash(request, e.message, "error")
        return redirect("/login/verify")
    request.session.clear()
    request.session["uid"] = user.id
    return redirect(home_url(user))


@router.post("/logout")
def logout(
    request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)
):
    if user:
        from edba.services import audit

        audit.record(db, "auth.logout", f"{user.email} signed out", actor=user)
    request.session.clear()
    return redirect("/")


# ------------------------------------------------------------------ applications


@router.get("/apply")
def apply_form(request: Request, user: User | None = Depends(current_user)):
    return render(request, "auth/apply.html", user=user, form={})


@router.post("/apply")
async def apply_submit(
    request: Request,
    org_full_name: str = Form(...),
    org_short_name: str = Form(...),
    convener_name: str = Form(""),
    convener_email: str = Form(...),
    proof: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    data = await proof.read()
    try:
        app = registration.apply(
            db,
            settings,
            org_full_name=org_full_name,
            org_short_name=org_short_name,
            convener_email=convener_email,
            convener_name=convener_name,
            proof_filename=proof.filename or "",
            proof=data,
        )
    except DomainError as e:
        flash(request, e.message, "error")
        form = {
            "org_full_name": org_full_name,
            "org_short_name": org_short_name,
            "convener_name": convener_name,
            "convener_email": convener_email,
        }
        return render(request, "auth/apply.html", form=form, status_code=400)
    request.session["pending_app"] = app.id
    flash(request, f"We sent a code to {app.convener_email} to confirm the application.", "info")
    return redirect(f"/apply/{app.id}/verify")


@router.get("/apply/{app_id}/verify")
def apply_verify_form(request: Request, app_id: int, db: Session = Depends(get_db)):
    if request.session.get("pending_app") != app_id:
        return redirect("/apply")
    app = registration.get(db, app_id)
    return render(
        request,
        "auth/verify.html",
        email=app.convener_email,
        action=f"/apply/{app_id}/verify",
        purpose="apply",
    )


@router.post("/apply/{app_id}/verify")
def apply_verify(
    request: Request,
    app_id: int,
    code: str = Form(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if request.session.get("pending_app") != app_id:
        return redirect("/apply")
    try:
        app = registration.confirm_email(db, settings, app_id, code)
    except DomainError as e:
        flash(request, e.message, "error")
        return redirect(f"/apply/{app_id}/verify")
    request.session.pop("pending_app", None)
    return render(request, "auth/applied.html", app=app)


@router.get("/application")
def application_status(c: Ctx = Depends(ctx)):
    app = registration.latest_for(c.db, c.user.email)
    steps = registration.timeline(app) if app else []
    return c.render("auth/application_status.html", app=app, steps=steps)


# ------------------------------------------------------------------ policies


@router.get("/policies")
def policy_list(
    request: Request, db: Session = Depends(get_db), user: User | None = Depends(current_user)
):
    return render(request, "policies.html", user=user, policies=policies.listing(db))


@router.get("/policies/file/{version_id}")
def policy_file(
    version_id: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
):
    v = policies.version(db, version_id)
    path = settings.upload_dir / v.file_path
    if not path.is_file():
        raise HTTPException(404, "File missing")
    return FileResponse(
        path,
        media_type="application/pdf",
        content_disposition_type="inline",
        filename=f"{v.policy.title} v{v.version}.pdf",
    )


# ------------------------------------------------------------------ help & profile


@router.get("/help")
def help_page(c: Ctx = Depends(ctx)):
    return c.render("help.html", tickets=helpdesk.mine(c.db, c.user))


@router.post("/help")
def help_ask(c: Ctx = Depends(ctx), title: str = Form(...), body: str = Form(...)):
    with attempt(c.request):
        helpdesk.ask(c.db, c.user, title, body)
        flash(c.request, "Your question was sent to the technical admins.")
    return redirect("/help")


@router.get("/me")
def profile(c: Ctx = Depends(ctx)):
    return c.render("profile.html")


@router.post("/me")
def profile_save(c: Ctx = Depends(ctx), name: str = Form(""), contact: str = Form("")):
    c.user.name, c.user.contact = name.strip()[:120], contact.strip()[:200]
    flash(c.request, "Profile saved.")
    return redirect("/me")


# ------------------------------------------------------------------ dev mailbox


@router.get("/dev/mailbox")
def mailbox(
    request: Request,
    to: str = "",
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User | None = Depends(current_user),
):
    if settings.env == "prod" or settings.mail_backend != "inbox":
        raise HTTPException(404)
    return render(request, "mailbox.html", user=user, messages=mail.inbox(db, to or None), to=to)
