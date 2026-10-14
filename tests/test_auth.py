from datetime import timedelta

from sqlalchemy import select, update

from edba.db import utcnow
from edba.models import OtpChallenge


def test_login_with_emailed_code(browser):
    r = browser.login("provider@harbor.example")
    assert r.url.path == "/w/hbu"
    assert "Priya Raman" in r.text


def test_code_is_stored_hashed(browser):
    browser.post_form("/login", {"email": "staff@harbor.example"})
    code = browser.last_code("staff@harbor.example")
    with browser.db.session() as s:
        ch = s.scalar(select(OtpChallenge).where(OtpChallenge.email == "staff@harbor.example"))
        assert code not in ch.code_hash and len(ch.code_hash) == 64


def test_wrong_code_then_lockout(browser, settings):
    browser.post_form("/login", {"email": "staff@harbor.example"})
    code = browser.last_code("staff@harbor.example")
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(settings.otp_max_attempts):
        r = browser.post_form("/login/verify", {"code": wrong}, csrf_from="/login/verify")
        assert "Wrong verification code" in r.text
    r = browser.post_form("/login/verify", {"code": code}, csrf_from="/login/verify")
    assert "Too many wrong attempts" in r.text  # attempts persisted although each try raised


def test_expired_code(browser):
    browser.post_form("/login", {"email": "staff@harbor.example"})
    code = browser.last_code("staff@harbor.example")
    with browser.db.session() as s:
        s.execute(update(OtpChallenge).values(expires_at=utcnow() - timedelta(seconds=1)))
    r = browser.post_form("/login/verify", {"code": code}, csrf_from="/login/verify")
    assert "expired" in r.text


def test_new_code_invalidates_old(browser):
    browser.post_form("/login", {"email": "staff@harbor.example"})
    old = browser.last_code("staff@harbor.example")
    browser.post_form("/login", {"email": "staff@harbor.example"})
    new = browser.last_code("staff@harbor.example")
    if old != new:
        r = browser.post_form("/login/verify", {"code": old}, csrf_from="/login/verify")
        assert "Wrong verification code" in r.text
    r = browser.post_form("/login/verify", {"code": new}, csrf_from="/login/verify")
    assert r.url.path == "/w/hbu"


def test_unregistered_email_refused(browser):
    r = browser.post_form("/login", {"email": "nobody@nowhere.example"})
    assert r.status_code == 400 and "not registered" in r.text


def test_csrf_required(browser):
    r = browser.post("/login", data={"email": "staff@harbor.example"})
    assert r.status_code == 403


def test_role_pages_are_protected(make_browser):
    b = make_browser()
    assert b.get("/org").url.path == "/login"  # anonymous -> sign in
    b.login("student@harbor.example")
    assert b.get("/admin").status_code == 403
    assert b.get("/org").status_code == 403
    assert b.get("/w/hbu/connectors").status_code == 403  # level 1 is not a provider


def test_logout(browser):
    browser.login("staff@harbor.example")
    r = browser.post_form("/logout", csrf_from="/me")
    assert r.url.path == "/"
    assert browser.get("/me").url.path == "/login"
