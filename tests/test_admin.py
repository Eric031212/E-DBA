"""T-Admin account management, help desk, policies (incl. spec a: T-Admin can view policies)."""

from helpers import PDF


def test_t_admin_manages_e_admins(make_browser):
    t = make_browser()
    t.login("tadmin@edba.example")
    r = t.post_form(
        "/admin/e-admins",
        {"email": "new@edba.example", "name": "New", "senior": "true"},
        csrf_from="/admin/e-admins",
    )
    assert "Senior E-Admin new@edba.example created" in r.text
    n = make_browser()
    assert n.login("new@edba.example").url.path == "/admin"
    from sqlalchemy import select

    from edba.models import User

    with t.db.session() as s:
        uid = s.scalar(select(User.id).where(User.email == "new@edba.example"))
    t.post_form(f"/admin/e-admins/{uid}", {"op": "disable"}, csrf_from="/admin/e-admins")
    assert "disabled" in make_browser().post_form("/login", {"email": "new@edba.example"}).text
    e = make_browser()
    e.login("eadmin@edba.example")
    assert e.get("/admin/e-admins").status_code == 403


def test_help_desk_round_trip(make_browser):
    u = make_browser()
    u.login("student@harbor.example")
    u.post_form("/help", {"title": "Quota?", "body": "How do I get more quota?"}, csrf_from="/help")
    t = make_browser()
    t.login("tadmin@edba.example")
    html = t.get("/admin/help").text
    assert "How do I get more quota?" in html
    import re

    tid = re.search(r"#(\d+) Quota\?", html).group(1)
    t.post_form(f"/admin/help/{tid}", {"answer": "Ask your O-Convener."}, csrf_from="/admin/help")
    assert "Ask your O-Convener." in u.get("/help").text
    assert "Re: Quota?" in u.get("/dev/mailbox?to=student@harbor.example").text


def test_policies_versioned_and_read_only_for_t_admin(make_browser):
    e = make_browser()
    e.login("eadmin@edba.example")
    r = e.post_form(
        "/admin/policies",
        {"title": "Retention", "summary": "Keep logs 7 years"},
        files={"file": ("r.pdf", PDF, "application/pdf")},
        csrf_from="/admin/policies",
    )
    assert "Published &#39;Retention&#39;" in r.text
    import re

    pid = re.findall(r'action="/admin/policies/(\d+)"', r.text)
    pid = pid[-1]
    e.post_form(
        f"/admin/policies/{pid}",
        {"op": "revise", "title": "Retention", "summary": "Keep logs 10 years"},
        files={"file": ("r2.pdf", PDF, "application/pdf")},
        csrf_from="/admin/policies",
    )
    t = make_browser()
    t.login("tadmin@edba.example")
    html = t.get("/admin/policies").text
    assert "Keep logs 10 years" in html and "v2" in html
    assert "New policy" not in html and "Archive policy" not in html  # view only (spec a)
    r = t.post_form(
        "/admin/policies",
        {"title": "X"},
        files={"file": ("x.pdf", PDF)},
        csrf_from="/admin/policies",
    )
    assert r.status_code == 403
    # Anyone can read the current PDF.
    v = re.search(r'href="/admin/policies/file/(\d+)"', html).group(1)
    assert make_browser().get(f"/policies/file/{v}").content.startswith(b"%PDF")
