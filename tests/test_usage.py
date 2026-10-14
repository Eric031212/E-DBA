"""Spec l (charging) and m (cross-workspace access) with real settlement through the demo bank."""

from helpers import balance, user, xlsx
from sqlalchemy import select

from edba.models import LedgerEntry, User


def quota(b, email):
    return user(b.db, email).quota_cents


def test_identity_check_charges_quota_and_pays_edba(make_browser):
    b = make_browser()
    b.login("staff@harbor.example")
    q0, org0, edba0 = (
        quota(b, "staff@harbor.example"),
        balance("Utopia Credit Union"),
        balance("E-DBA account"),
    )
    r = b.post_form(
        "/w/hbu/s/identity-auth",
        {"name": "Ada Lin", "id": "H2021001"},
        files={"photo": ("me.jpg", b"\xff\xd8fake", "image/jpeg")},
        csrf_from="/w/hbu/s/identity-auth",
    )
    assert "verified" in r.text and "charged ¥2.00" in r.text
    assert quota(b, "staff@harbor.example") == q0 - 200
    assert balance("Utopia Credit Union") == org0 - 2 and balance("E-DBA account") == edba0 + 2


def test_failed_lookup_is_free(make_browser):
    b = make_browser()
    b.login("staff@harbor.example")
    q0 = quota(b, "staff@harbor.example")
    r = b.post_form(
        "/w/hbu/s/gpa-record", {"name": "Nobody", "id": "X"}, csrf_from="/w/hbu/s/gpa-record"
    )
    assert "no such student" in r.text
    assert quota(b, "staff@harbor.example") == q0


def test_gpa_batch_charges_successful_rows_only(make_browser):
    b = make_browser()
    b.login("staff@harbor.example")
    q0 = quota(b, "staff@harbor.example")
    sheet = xlsx(
        [["name", "id"], ["Ada Lin", "H2021001"], ["Ben Okafor", "H2021002"], ["Ghost", "H0000000"]]
    )
    r = b.post_form(
        "/w/hbu/s/gpa-record/batch",
        files={"file": ("batch.xlsx", sheet)},
        csrf_from="/w/hbu/s/gpa-record",
    )
    assert "2 records · charged ¥6.00" in r.text and "1 row(s) failed" in r.text
    assert "3.82" in r.text and "3.41" in r.text
    assert quota(b, "staff@harbor.example") == q0 - 600


def test_batch_needs_quota_up_front(make_browser):
    b = make_browser()
    b.login("staff@harbor.example")
    with b.db.session() as s:
        s.scalar(select(User).where(User.email == "staff@harbor.example")).quota_cents = 500
    sheet = xlsx([["name", "id"], *[["Ada Lin", "H2021001"]] * 3])
    r = b.post_form(
        "/w/hbu/s/gpa-record/batch",
        files={"file": ("b.xlsx", sheet)},
        csrf_from="/w/hbu/s/gpa-record",
    )
    assert "needs ¥9.00 of quota but you have ¥5.00" in r.text
    assert quota(b, "staff@harbor.example") == 500


def test_level1_cannot_use_private_services(make_browser):
    b = make_browser()
    b.login("student@harbor.example")
    assert b.get("/w/hbu/s/gpa-record").status_code == 403


def test_thesis_search_free_download_own_org_is_self_transfer(make_browser):
    b = make_browser()
    b.login("student@harbor.example")
    q0, bal0 = quota(b, "student@harbor.example"), balance("Utopia Credit Union")
    html = b.get("/w/hbu/thesis?q=federated learning").text
    assert "Federated Learning for Privacy-Preserving Learning Analytics" in html
    assert quota(b, "student@harbor.example") == q0  # search is free
    r = b.post_form(
        "/w/hbu/thesis/download",
        {"title": "Federated Learning for Privacy-Preserving Learning Analytics"},
        csrf_from="/w/hbu/thesis?q=federated",
    )
    assert r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert quota(b, "student@harbor.example") == q0 - 500
    assert balance("Utopia Credit Union") == bal0  # paid to itself
    with b.db.session() as s:
        e = s.scalars(select(LedgerEntry).order_by(LedgerEntry.id.desc())).first()
        assert e.payer_org_id == e.payee_org_id and e.amount_cents == 500


def test_cross_org_download_pays_the_provider(make_browser):
    """Spec m: visiting SIT at level 1, the download is paid by HBU to SIT at SIT's price."""
    b = make_browser()
    b.login("staff@harbor.example")
    q0, hbu0, sit0 = (
        quota(b, "staff@harbor.example"),
        balance("Utopia Credit Union"),
        balance("Campus Cash Cooperative"),
    )
    dash = b.get("/w/sit").text
    assert "Visiting as a guest" in dash
    assert "Student Identity" not in dash  # private services never visible across organizations
    r = b.post_form(
        "/w/sit/thesis/download",
        {"title": "Tamper-Evident Audit Logs with Hash Chains"},
        csrf_from="/w/sit/thesis?q=hash",
    )
    assert r.content.startswith(b"%PDF")
    assert quota(b, "staff@harbor.example") == q0 - 800
    assert (
        balance("Utopia Credit Union") == hbu0 - 8
        and balance("Campus Cash Cooperative") == sit0 + 8
    )


def test_cross_org_is_clamped_to_level1(make_browser):
    b = make_browser()
    b.login("provider@harbor.example")
    assert b.get("/w/sit/connectors").status_code == 403
    assert b.get("/w/sit/courses/manage").status_code == 403
    assert b.get("/w/sit/courses").status_code == 200


def test_display_only_blocks_download_everywhere(make_browser):
    c = make_browser()
    c.login("convener@summit.example")
    c.post_form(
        "/org/services/thesis",
        {"op": "update", "price": "8", "thesis_mode": "display_only"},
        csrf_from="/org/services",
    )
    b = make_browser()
    b.login("staff@harbor.example")
    assert "thesis/download" not in b.get("/w/sit/thesis?q=hash").text
    r = b.post_form(
        "/w/sit/thesis/download",
        {"title": "Tamper-Evident Audit Logs with Hash Chains"},
        csrf_from="/w/sit/thesis?q=hash",
    )
    assert "display-only" in r.text


def test_usage_is_logged(make_browser):
    b = make_browser()
    b.login("staff@harbor.example")
    b.post_form(
        "/w/hbu/s/gpa-record",
        {"name": "Ada Lin", "id": "H2021001"},
        csrf_from="/w/hbu/s/gpa-record",
    )
    c = make_browser()
    c.login("convener@harbor.example")
    html = c.get("/org/logs?action=service.used").text
    assert (
        "Student GPA Record Access in HBU: 1 record, ¥3.00" in html
        and "staff@harbor.example" in html
    )
