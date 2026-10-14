"""Spec d: member lists with wildcard domain rows, and domain-based sign-in."""

from helpers import org, xlsx
from sqlalchemy import select

from edba.models import DomainRule, User

HEADER = ["name", "email", "access_right", "quota"]


def _upload(b, rows, name="members.xlsx"):
    data = xlsx([HEADER, *rows]) if name.endswith(".xlsx") else rows
    return b.post_form(
        "/org/members/upload", files={"file": (name, data)}, csrf_from="/org/members"
    )


def test_import_members_and_wildcard_rule(make_browser):
    b = make_browser()
    b.login("convener@harbor.example")
    r = _upload(
        b,
        [
            ["Alice Huang", "alice@harbor.example", 3, 100],
            ["John Chow", "john@harbor.example", 2, 100],
            [None, "*@mail.uic.edu.cn", 1, 100],
        ],
    )
    assert "2 added" in r.text and "1 domain rule" in r.text
    with b.db.session() as s:
        rule = s.scalar(select(DomainRule).where(DomainRule.domain == "@mail.uic.edu.cn"))
        assert (
            rule is not None and rule.access_level == 1 and rule.quota_cents == 100_00
        )  # "*" not stored
        alice = s.scalar(select(User).where(User.email == "alice@harbor.example"))
        assert alice.access_level == 3 and alice.quota_cents == 100_00 and not alice.fee_paid


def test_domain_sign_in_matches_exact_domain(make_browser):
    b = make_browser()
    b.login("convener@harbor.example")
    _upload(b, [[None, "*@mail.uic.edu.cn", 1, 100]])
    hbu = org(b.db, "HBU")
    for good in ["abc@mail.uic.edu.cn", "s230012345@mail.uic.edu.cn"]:
        u = make_browser()
        r = u.login(good)
        assert r.url.path == "/w/hbu", good
        with u.db.session() as s:
            created = s.scalar(select(User).where(User.email == good))
            assert (
                created.org_id == hbu.id
                and created.access_level == 1
                and created.quota_cents == 100_00
            )
    for bad in ["abc@mail.uic.edu.com", "abc@uic.edu.cn"]:
        u = make_browser()
        r = u.post_form("/login", {"email": bad})
        assert "not registered" in r.text, bad


def test_domain_sign_in_requires_level1_fee(make_browser):
    """An organization that has not paid the one-off level-1 fee cannot admit a domain."""
    b = make_browser()
    b.login("convener@harbor.example")
    _upload(b, [[None, "*@uni.example", 1, 10]])
    with b.db.session() as s:
        s.get(type(org(b.db, "HBU")), org(b.db, "HBU").id).level1_paid = False
    r = make_browser().post_form("/login", {"email": "kid@uni.example"})
    assert "has not activated domain sign-in" in r.text


def test_bad_files_import_nothing(make_browser):
    b = make_browser()
    b.login("convener@harbor.example")
    r = b.post_form(
        "/org/members/upload",
        files={"file": ("m.xlsx", xlsx([["name", "email", "level"]]))},
        csrf_from="/org/members",
    )
    assert "exactly these four columns" in r.text
    r = b.post_form(
        "/org/members/upload", files={"file": ("m.txt", b"hello")}, csrf_from="/org/members"
    )
    assert "Excel (.xlsx) or CSV" in r.text
    r = _upload(
        b,
        [
            ["Ok", "ok@harbor.example", 1, 5],
            ["Bad", "bad@harbor.example", 7, 5],
            ["Mail", "not-an-email", 1, 5],
        ],
    )
    assert "Nothing was imported" in r.text and "Row 3" in r.text and "Row 4" in r.text
    with b.db.session() as s:
        assert s.scalar(select(User).where(User.email == "ok@harbor.example")) is None


def test_csv_upload_and_conflicts(make_browser):
    b = make_browser()
    b.login("convener@harbor.example")
    csv = b"name,email,access_right,quota\nZed,zed@harbor.example,2,12.5\n,*@summit-students.example,1,0\n"
    r = _upload(b, csv, name="m.csv")
    assert "1 added" in r.text
    # Another organization's member, or a domain someone else claimed, is refused.
    s = make_browser()
    s.login("convener@summit.example")
    r = s.post_form(
        "/org/members/upload",
        files={
            "file": (
                "m.csv",
                b"name,email,access_right,quota\n"
                b"Zed,zed@harbor.example,1,1\n,*@summit-students.example,1,0\n",
            )
        },
        csrf_from="/org/members",
    )
    assert "already has an E-DBA account elsewhere" in r.text
    assert "already claimed by another organization" in r.text


def test_quota_and_removal(make_browser):
    b = make_browser()
    b.login("convener@harbor.example")
    with b.db.session() as s:
        uid = s.scalar(select(User.id).where(User.email == "student@harbor.example"))
    b.post_form(f"/org/members/{uid}", {"op": "quota", "quota": "42.50"}, csrf_from="/org/members")
    with b.db.session() as s:
        assert s.get(User, uid).quota_cents == 4250
    b.post_form(f"/org/members/{uid}", {"op": "remove"}, csrf_from="/org/members")
    with b.db.session() as s:
        assert s.get(User, uid) is None
