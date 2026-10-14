"""O-Convener console: bank account, members, services, membership fees, organization logs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response

from edba.models import SERVICES, Organization, ServiceKind, ThesisMode
from edba.services import audit, billing, catalog, members
from edba.web.deps import Ctx, attempt, convener_ctx, flash, redirect

router = APIRouter(prefix="/org")

Conv = tuple[Ctx, Organization]


@router.get("")
def overview(cv: Conv = Depends(convener_ctx)):
    c, org = cv
    services = catalog.org_services(c.db, org)
    return c.render(
        "org/overview.html",
        org=org,
        bank=billing.bank_account(c.db, org.id),
        members=members.members(c.db, org),
        rules=members.rules(c.db, org),
        services=[(s, catalog.is_active(c.db, s)) for s in services],
        quote=billing.membership_quote(c.db, org),
        recent=audit.search(c.db, org_id=org.id, limit=6),
    )


# ------------------------------------------------------------------ bank


@router.get("/bank")
def bank(cv: Conv = Depends(convener_ctx)):
    c, org = cv
    return c.render("org/bank.html", org=org, bank=billing.bank_account(c.db, org.id))


@router.post("/bank")
def bank_save(
    cv: Conv = Depends(convener_ctx),
    bank_name: str = Form(...),
    account_name: str = Form(...),
    account_no: str = Form(...),
    password: str = Form(...),
):
    c, org = cv
    with attempt(c.request):
        acct = billing.set_bank_account(
            c.db,
            c.settings,
            c.user,
            org,
            bank_name=bank_name,
            account_name=account_name,
            account_no=account_no,
            password=password,
        )
        flash(c.request, f"Verified with {acct.bank_name}. This account now settles all payments.")
    return redirect("/org/bank")


# ------------------------------------------------------------------ members


@router.get("/members")
def member_page(cv: Conv = Depends(convener_ctx)):
    c, org = cv
    return c.render(
        "org/members.html",
        org=org,
        members=members.members(c.db, org),
        rules=members.rules(c.db, org),
        report=None,
    )


@router.post("/members/upload")
async def member_upload(cv: Conv = Depends(convener_ctx), file: UploadFile = File(...)):
    c, org = cv
    data = await file.read()
    with attempt(c.request):
        report = members.import_member_list(c.db, c.user, org, file.filename or "", data)
        if report.ok:
            flash(
                c.request,
                f"Imported: {len(report.added)} added, {len(report.updated)} updated, "
                f"{len(report.rules)} domain rule(s).",
            )
        else:
            return c.render(
                "org/members.html",
                org=org,
                members=members.members(c.db, org),
                rules=members.rules(c.db, org),
                report=report,
            )
    return redirect("/org/members")


@router.get("/members/template.csv")
def member_template(cv: Conv = Depends(convener_ctx)):
    body = (
        "name,email,access_right,quota\n"
        "Alice Huang,alice@example.edu,3,500\n"
        "John Chow,john@example.edu,2,200\n"
        ",*@students.example.edu,1,50\n"
    )
    return Response(
        body,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=member_list_template.csv"},
    )


@router.post("/members/{user_id}")
def member_update(
    user_id: str, cv: Conv = Depends(convener_ctx), op: str = Form(...), quota: str = Form("")
):
    c, org = cv
    with attempt(c.request):
        if op == "remove":
            members.remove_member(c.db, c.user, org, user_id)
            flash(c.request, "Member removed.")
        elif op == "quota":
            u = members.set_quota(c.db, c.user, org, user_id, quota)
            flash(c.request, f"Quota for {u.email} updated.")
    return redirect("/org/members")


@router.post("/rules/{rule_id}/delete")
def rule_delete(rule_id: int, cv: Conv = Depends(convener_ctx)):
    c, org = cv
    with attempt(c.request):
        members.remove_rule(c.db, c.user, org, rule_id)
        flash(c.request, "Domain rule removed.")
    return redirect("/org/members")


# ------------------------------------------------------------------ services


@router.get("/services")
def services(cv: Conv = Depends(convener_ctx)):
    c, org = cv
    mine = catalog.org_services(c.db, org)
    added = {s.kind for s in mine}
    return c.render(
        "org/services.html",
        org=org,
        mine=[(s, catalog.is_active(c.db, s)) for s in mine],
        available=[spec for k, spec in SERVICES.items() if k not in added],
        has_bank=billing.bank_account(c.db, org.id) is not None,
    )


@router.post("/services")
def service_add(
    cv: Conv = Depends(convener_ctx),
    kind: str = Form(...),
    price: str = Form("0"),
    thesis_mode: str = Form(ThesisMode.DISPLAY_ONLY.value),
):
    c, org = cv
    with attempt(c.request):
        svc = catalog.add_service(
            c.db, c.user, org, ServiceKind(kind), price, ThesisMode(thesis_mode)
        )
        hint = "" if not svc.spec.operations else " A level-3 provider must now configure its API."
        flash(c.request, f"{svc.spec.title} added.{hint}")
    return redirect("/org/services")


@router.post("/services/{kind}")
def service_update(
    kind: str,
    cv: Conv = Depends(convener_ctx),
    op: str = Form("update"),
    price: str | None = Form(None),
    thesis_mode: str | None = Form(None),
):
    c, org = cv
    with attempt(c.request):
        if op == "remove":
            catalog.remove_service(c.db, c.user, org, ServiceKind(kind))
            flash(c.request, "Service removed.")
        else:
            catalog.update_service(
                c.db,
                c.user,
                org,
                ServiceKind(kind),
                price,
                ThesisMode(thesis_mode) if thesis_mode else None,
            )
            flash(c.request, "Service updated.")
    return redirect("/org/services")


# ------------------------------------------------------------------ fees


@router.get("/fees")
def fees(cv: Conv = Depends(convener_ctx)):
    c, org = cv
    return c.render(
        "org/fees.html",
        org=org,
        quote=billing.membership_quote(c.db, org),
        bank=billing.bank_account(c.db, org.id),
        ledger=billing.ledger(c.db, org),
    )


@router.post("/fees/{level}")
def fees_pay(level: int, cv: Conv = Depends(convener_ctx), idem: str = Form("")):
    c, org = cv
    with attempt(c.request):
        billing.pay_membership(c.db, c.settings, c.user, org, level, idem or None)
        flash(c.request, f"Level {level} membership fee paid.")
    return redirect("/org/fees")


# ------------------------------------------------------------------ logs


@router.get("/logs")
def logs(cv: Conv = Depends(convener_ctx), q: str = "", action: str = ""):
    c, org = cv
    events = audit.search(c.db, org_id=org.id, q=q, action=action)
    template = "admin/_log_rows.html" if c.request.headers.get("HX-Request") else "org/logs.html"
    return c.render(
        template,
        org=org,
        events=events,
        actions=audit.actions(c.db, org.id),
        names={org.id: org.short_name},
        f={"q": q, "action": action},
    )
