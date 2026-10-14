"""Spec e-i: service selection, pricing, dashboards per access level, courses, connectors."""

import re

from helpers import org
from sqlalchemy import select

from edba.models import Course, OrgService, ServiceKind, ThesisMode


def tiles(html: str) -> list[str]:
    return re.findall(
        r'<a class="tile" href="[^"]+"><span class="ic">.*?</span><b>(.*?)</b>', html, re.S
    )


def test_dashboard_buttons_by_level(make_browser):
    """Spec f: tiles depend on the level and on what the convener added *and* a provider configured."""
    expect = {
        "student@harbor.example": [
            "Course Information",
            "Thesis Sharing",
            "Workspaces",
            "Seek Help",
        ],
        "staff@harbor.example": [
            "Course Information",
            "Student Identity Authentication",
            "Student GPA Record Access",
            "Thesis Sharing",
            "Workspaces",
            "Seek Help",
        ],
        "provider@harbor.example": [
            "Course Information",
            "Course Configurations",
            "Student Identity Authentication",
            "Student GPA Record Access",
            "Thesis Sharing",
            "API Configurations",
            "Workspaces",
            "Seek Help",
        ],
    }
    for email, want in expect.items():
        b = make_browser()
        assert tiles(b.login(email).text) == want, email


def test_services_need_configured_api(make_browser):
    """Spec h-3: a freshly added API-backed service stays hidden until a level-3 user configures it."""
    c = make_browser()
    c.login("convener@summit.example")
    r = c.post_form(
        "/org/services", {"kind": "gpa-record", "price": "4"}, csrf_from="/org/services"
    )
    assert "must now configure its API" in r.text
    assert "Needs API" in c.get("/org/services").text

    # Summit's level-3 provider is the only one with a level >= 2 there; check its dashboard.
    p = make_browser()
    assert "Student GPA Record Access" not in tiles(p.login("provider@summit.example").text)
    p.post_form(
        "/w/sit/connectors/gpa-record",
        {
            "operation": "query",
            "base_url": "http://gateway.test/campus/summit",
            "path": "/student/record",
            "method": "POST",
            "input_schema": '{"name": "string", "id": "string"}',
            "output_schema": '{"name": "string", "gpa": "float"}',
        },
        csrf_from="/w/sit/connectors/gpa-record",
    )
    assert "Student GPA Record Access" in tiles(p.get("/w/sit").text)


def test_each_service_once_and_removable(make_browser):
    """Spec e changes 1 and 2."""
    c = make_browser()
    c.login("convener@harbor.example")
    r = c.post_form("/org/services", {"kind": "thesis", "price": "1"}, csrf_from="/org/services")
    assert "already in your workspace" in r.text
    c.post_form("/org/services/gpa-record", {"op": "remove"}, csrf_from="/org/services")
    hbu = org(c.db, "HBU")
    with c.db.session() as s:
        kinds = set(s.scalars(select(OrgService.kind).where(OrgService.org_id == hbu.id)))
    assert ServiceKind.GPA_RECORD not in kinds and ServiceKind.THESIS in kinds
    p = make_browser()
    assert "Student GPA Record Access" not in tiles(p.login("provider@harbor.example").text)


def test_paid_service_needs_bank_account(make_browser, seeded, settings):
    from helpers import PDF

    # Register a new organization without a bank account.
    a = make_browser()
    r = a.post_form(
        "/apply",
        {"org_full_name": "Bankless U", "org_short_name": "BLU", "convener_email": "c@blu.example"},
        files={"proof": ("p.pdf", PDF)},
        csrf_from="/apply",
    )
    app_id = int(r.url.path.split("/")[2])
    a.post_form(
        f"/apply/{app_id}/verify",
        {"code": a.last_code("c@blu.example")},
        csrf_from=f"/apply/{app_id}/verify",
    )
    for who in ("eadmin@edba.example", "senior@edba.example"):
        b = make_browser()
        b.login(who)
        b.post_form(
            f"/admin/applications/{app_id}",
            {"decision": "approve"},
            csrf_from=f"/admin/applications/{app_id}",
        )
    c = make_browser()
    c.login("c@blu.example")
    r = c.post_form(
        "/org/services", {"kind": "identity-auth", "price": "2"}, csrf_from="/org/services"
    )
    assert "bank account before adding paid services" in r.text
    r = c.post_form("/org/services", {"kind": "course-info"}, csrf_from="/org/services")
    assert "Course Information added" in r.text  # free services need no bank


def test_price_and_thesis_mode(make_browser):
    """Spec g and i."""
    c = make_browser()
    c.login("convener@harbor.example")
    c.post_form(
        "/org/services/thesis",
        {"op": "update", "price": "7.5", "thesis_mode": "display_only"},
        csrf_from="/org/services",
    )
    with c.db.session() as s:
        svc = s.scalar(
            select(OrgService).where(
                OrgService.kind == ServiceKind.THESIS, OrgService.price_cents == 750
            )
        )
        assert svc is not None and svc.thesis_mode is ThesisMode.DISPLAY_ONLY
    u = make_browser()
    u.login("student@harbor.example")
    html = u.get("/w/hbu/thesis?q=learning").text
    assert "Federated Learning" in html and "display only" in html and "thesis/download" not in html


def test_course_status_and_permissions(make_browser):
    """Spec e: a course created as active must stay active; only level 3 may configure courses."""
    p = make_browser()
    p.login("provider@harbor.example")
    r = p.post_form(
        "/w/hbu/courses/manage",
        {"code": "comp9999", "title": "Capstone", "units": "6", "active": "active"},
        csrf_from="/w/hbu/courses/manage",
    )
    assert "COMP9999 created (active)" in r.text
    with p.db.session() as s:
        c = s.scalar(select(Course).where(Course.code == "COMP9999"))
        assert c.active
        cid = c.id
    p.post_form(
        "/w/hbu/courses/manage",
        {"course_id": cid, "code": "COMP9999", "title": "Capstone II", "units": "6", "active": ""},
        csrf_from="/w/hbu/courses/manage",
    )
    s_ = make_browser()
    s_.login("staff@harbor.example")
    assert "COMP9999" not in s_.get("/w/hbu/courses?q=capstone").text  # inactive -> hidden
    assert s_.get("/w/hbu/courses/manage").status_code == 403
    c = make_browser()
    c.login("convener@harbor.example")
    assert c.get("/w/hbu/courses/manage").status_code == 403


def test_course_search(make_browser):
    b = make_browser()
    b.login("student@harbor.example")
    html = b.get("/w/hbu/courses?q=database", headers={"HX-Request": "true"}).text
    assert "COMP3053" in html and "COMP3013" not in html


def test_connector_validation(make_browser):
    p = make_browser()
    p.login("provider@harbor.example")
    base = {
        "operation": "query",
        "base_url": "http://gateway.test/campus/harbor",
        "path": "/x",
        "method": "POST",
        "output_schema": '{"ok": "string"}',
    }
    for schema, msg in [
        ("{not json", "not valid JSON"),
        ('{"a": "date"}', "type must be one of"),
        ('["a"]', "must be a JSON object"),
    ]:
        r = p.post_form(
            "/w/hbu/connectors/gpa-record",
            {**base, "input_schema": schema},
            csrf_from="/w/hbu/connectors/gpa-record",
        )
        assert msg in r.text
    r = p.post_form(
        "/w/hbu/connectors/gpa-record",
        {**base, "base_url": "ftp://x", "input_schema": '{"a": "string"}'},
        csrf_from="/w/hbu/connectors/gpa-record",
    )
    assert "http(s) URL" in r.text
