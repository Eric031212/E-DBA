"""Spec items b (review log detail) and c (status timeline) plus the review workflow."""

from helpers import PDF

from edba.models import ApplicationStatus, RegistrationApplication


def _apply(b, short="NEWU", email="boss@newu.example"):
    r = b.post_form(
        "/apply",
        {
            "org_full_name": "New University",
            "org_short_name": short,
            "convener_email": email,
            "convener_name": "Bo Ss",
        },
        files={"proof": ("proof.pdf", PDF, "application/pdf")},
        csrf_from="/apply",
    )
    assert r.status_code == 200, r.text
    app_id = int(r.url.path.split("/")[2])
    code = b.last_code(email)
    r = b.post_form(f"/apply/{app_id}/verify", {"code": code}, csrf_from=f"/apply/{app_id}/verify")
    assert "Application submitted" in r.text
    return app_id


def _review(make_browser, who, app_id, decision, notes=""):
    b = make_browser()
    b.login(who)
    return b.post_form(
        f"/admin/applications/{app_id}",
        {"decision": decision, "notes": notes},
        csrf_from=f"/admin/applications/{app_id}",
    )


def test_full_acceptance_creates_org_and_convener(make_browser):
    app_id = _apply(make_browser())
    _review(make_browser, "eadmin@edba.example", app_id, "approve")
    _review(make_browser, "senior@edba.example", app_id, "approve")
    b = make_browser()
    r = b.login("boss@newu.example")
    assert r.url.path == "/org" and "New University" in r.text


def test_senior_rejection_is_attributed_to_senior(make_browser):
    """v3 bug (spec c): after E-Admin approval a Senior rejection showed as 'E-Admin rejected'."""
    app_id = _apply(make_browser())
    _review(make_browser, "eadmin@edba.example", app_id, "approve")
    _review(make_browser, "senior@edba.example", app_id, "reject", "Proof is expired")
    b = make_browser()
    b.login("boss@newu.example")
    html = b.get("/application").text
    e_block = html.split("E-Admin Review</b>")[1].split("</li>")[0]
    s_block = html.split("Senior E-Admin Review</b>")[1].split("</li>")[0]
    assert "Approved" in e_block and "eadmin@edba.example" in e_block
    assert (
        "Rejected" in s_block and "senior@edba.example" in s_block and "Proof is expired" in s_block
    )


def test_review_log_names_org_and_convener(make_browser):
    """Spec b: the T-Admin's log must say which application, not just its id."""
    app_id = _apply(make_browser())
    _review(make_browser, "eadmin@edba.example", app_id, "approve", "ok")
    t = make_browser()
    t.login("tadmin@edba.example")
    html = t.get("/admin/logs?action=application.approved").text
    assert f"#{app_id} — New University (NEWU), O-Convener boss@newu.example, notes: ok" in html


def test_four_eyes_and_stage_permissions(make_browser):
    app_id = _apply(make_browser())
    # A Senior E-Admin may do the first review ...
    _review(make_browser, "senior@edba.example", app_id, "approve")
    # ... but not also the final one,
    r = _review(make_browser, "senior@edba.example", app_id, "approve")
    assert "Four-eyes" in r.text
    # and a regular E-Admin cannot do final reviews.
    r = _review(make_browser, "eadmin@edba.example", app_id, "approve")
    assert "Senior E-Admin" in r.text
    b = make_browser()
    with b.db.session() as s:
        assert s.get(RegistrationApplication, app_id).status is ApplicationStatus.FIRST_APPROVED


def test_reject_needs_reason(make_browser):
    app_id = _apply(make_browser())
    r = _review(make_browser, "eadmin@edba.example", app_id, "reject", "")
    assert "give a reason" in r.text


def test_duplicate_short_name_and_bad_proof(make_browser):
    b = make_browser()
    r = b.post_form(
        "/apply",
        {"org_full_name": "Copycat", "org_short_name": "HBU", "convener_email": "x@y.example"},
        files={"proof": ("p.pdf", PDF, "application/pdf")},
        csrf_from="/apply",
    )
    assert r.status_code == 400 and "already taken" in r.text
    r = b.post_form(
        "/apply",
        {"org_full_name": "Exe U", "org_short_name": "EXE", "convener_email": "x@y.example"},
        files={"proof": ("p.exe", b"MZ", "application/octet-stream")},
        csrf_from="/apply",
    )
    assert r.status_code == 400 and "Unsupported file type" in r.text
    r = b.post_form(
        "/apply",
        {"org_full_name": "Fake U", "org_short_name": "FAKE", "convener_email": "x@y.example"},
        files={"proof": ("p.pdf", b"not a pdf", "application/pdf")},
        csrf_from="/apply",
    )
    assert r.status_code == 400 and "not a valid PDF" in r.text
