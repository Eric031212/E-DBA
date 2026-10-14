"""Spec j (bank account), k (membership fees) and login gating by payment."""

from helpers import balance, org, xlsx
from sqlalchemy import select

from edba.models import LedgerEntry, Organization, User


def test_bank_account_verified_with_bank_and_encrypted(make_browser):
    c = make_browser()
    c.login("convener@summit.example")
    r = c.post_form(
        "/org/bank",
        {
            "bank_name": "Global Education Bank",
            "account_name": "Campus Cash Cooperative",
            "account_no": "641387141765274",
            "password": "wrong",
        },
        csrf_from="/org/bank",
    )
    assert "could not verify" in r.text
    r = c.post_form(
        "/org/bank",
        {
            "bank_name": "Global Education Bank",
            "account_name": "Campus Cash Cooperative",
            "account_no": "641387141765274",
            "password": "8799",
        },
        csrf_from="/org/bank",
    )
    assert "Verified with Global Education Bank" in r.text
    from edba.models import BankAccount

    with c.db.session() as s:
        acct = s.scalar(select(BankAccount).where(BankAccount.account_no == "641387141765274"))
        assert "8799" not in acct.secret_enc and acct.secret_enc.startswith("gAAAA")  # Fernet token


def test_membership_fees_per_level(make_browser):
    c = make_browser()
    c.login("convener@harbor.example")
    rows = [
        ["name", "email", "access_right", "quota"],
        ["A", "a@harbor.example", 2, 1],
        ["B", "b@harbor.example", 2, 1],
        ["C", "c@harbor.example", 3, 1],
    ]
    c.post_form(
        "/org/members/upload", files={"file": ("m.xlsx", xlsx(rows))}, csrf_from="/org/members"
    )
    html = c.get("/org/fees").text
    assert "2 unpaid members · due <b>¥200.00</b>" in html
    assert "1 unpaid member · due <b>¥0.00</b>" in html

    # Unpaid level-2 members cannot sign in yet.
    m = make_browser()
    r = m.post_form("/login", {"email": "a@harbor.example"})
    assert "has not paid the membership fee" in r.text

    before_org, before_edba = balance("Utopia Credit Union"), balance("E-DBA account")
    r = c.post_form("/org/fees/2", {"idem": "fee-test-l2"}, csrf_from="/org/fees")
    assert "Level 2 membership fee paid" in r.text
    assert balance("Utopia Credit Union") == before_org - 200
    assert balance("E-DBA account") == before_edba + 200
    # Level 3 costs 0 by default: marking paid needs no transfer.
    c.post_form("/org/fees/3", csrf_from="/org/fees")
    assert m.login("a@harbor.example").url.path == "/w/hbu"
    assert make_browser().login("c@harbor.example").url.path == "/w/hbu"


def test_payment_is_idempotent(make_browser, settings):
    from edba.services import billing

    c = make_browser()
    hbu = org(c.db, "HBU")
    with c.db.session() as s:
        conv = s.scalar(select(User).where(User.email == "convener@harbor.example"))
        o = s.get(Organization, hbu.id)
        before = balance("Utopia Credit Union")
        e1 = billing.transfer(
            s,
            settings,
            kind=billing.LedgerKind.SERVICE,
            payer=o,
            payee=None,
            amount_cents=1234,
            memo="x",
            actor=conv,
            idempotency_key="same-key",
        )
        e2 = billing.transfer(
            s,
            settings,
            kind=billing.LedgerKind.SERVICE,
            payer=o,
            payee=None,
            amount_cents=1234,
            memo="x",
            actor=conv,
            idempotency_key="same-key",
        )
        assert e1.id == e2.id
        assert balance("Utopia Credit Union") == before - 12.34
        assert (
            s.scalar(select(LedgerEntry).where(LedgerEntry.idempotency_key == "same-key"))
            is not None
        )


def test_insufficient_funds_is_reported_and_logged(make_browser):
    c = make_browser()
    c.login("convener@summit.example")
    # Switch Summit to the nearly empty demo account (balance 300) and raise the level-1 fee.
    c.post_form(
        "/org/bank",
        {
            "bank_name": "Pearl River Savings",
            "account_name": "Lakeside Scholars Fund",
            "account_no": "622848000123456",
            "password": "4321",
        },
        csrf_from="/org/bank",
    )
    sit = org(c.db, "SIT")
    with c.db.session() as s:
        s.get(Organization, sit.id).level1_paid = False
    r = c.post_form("/org/fees/1", csrf_from="/org/fees")
    assert "Payment failed: insufficient funds" in r.text
    with c.db.session() as s:
        assert not s.get(Organization, sit.id).level1_paid
        failed = s.scalars(select(LedgerEntry).where(LedgerEntry.payer_org_id == sit.id)).all()
        assert [e.status.value for e in failed] == ["failed"]  # kept although the request "failed"


def test_e_admin_sets_fees(make_browser):
    a = make_browser()
    a.login("eadmin@edba.example")
    a.post_form(
        "/admin/fees",
        {"level1": "1500", "level2": "120.50", "level3": "5"},
        csrf_from="/admin/fees",
    )
    c = make_browser()
    c.login("convener@harbor.example")
    html = c.get("/org/fees").text
    assert "¥1,500.00" in html and "¥120.50" in html and "¥5.00" in html
    t = make_browser()
    t.login("staff@harbor.example")
    assert t.get("/admin/fees").status_code == 403
