"""Tamper-evident audit log."""

from sqlalchemy import select, text

from edba.models import AuditEvent
from edba.services import audit


def test_chain_verifies_after_activity(make_browser):
    b = make_browser()
    b.login("staff@harbor.example")
    b.post_form(
        "/w/hbu/s/gpa-record",
        {"name": "Ada Lin", "id": "H2021001"},
        csrf_from="/w/hbu/s/gpa-record",
    )
    with b.db.session() as s:
        r = audit.verify_chain(s)
        assert r.ok and r.checked > 20


def test_editing_a_past_event_is_detected(make_browser):
    t = make_browser()
    t.login("tadmin@edba.example")
    with t.db.session() as s:
        target = s.scalars(select(AuditEvent).order_by(AuditEvent.id)).all()[5]
        s.execute(
            text("UPDATE audit_events SET summary = 'nothing to see' WHERE id = :i"),
            {"i": target.id},
        )
    r = t.post_form("/admin/audit/verify", csrf_from="/admin")
    assert f"BROKEN at event #{target.id}: event content was modified" in r.text


def test_deleting_an_event_is_detected(seeded):
    with seeded.session() as s:
        ids = list(s.scalars(select(AuditEvent.id).order_by(AuditEvent.id)))
        s.execute(text("DELETE FROM audit_events WHERE id = :i"), {"i": ids[3]})
    with seeded.session() as s:
        r = audit.verify_chain(s)
        assert not r.ok and r.broken_at == ids[4] and "link" in r.reason


def test_cli_verify(seeded, settings, monkeypatch):
    from typer.testing import CliRunner

    from edba import cli

    monkeypatch.setattr(cli, "_db", lambda: seeded)
    out = CliRunner().invoke(cli.app, ["verify-audit"])
    assert out.exit_code == 0 and "events verified" in out.output


def test_org_logs_are_scoped(make_browser):
    c = make_browser()
    c.login("convener@summit.example")
    html = c.get("/org/logs").text
    assert "harbor.example" not in html


def test_t_admin_log_filters(make_browser):
    t = make_browser()
    t.login("tadmin@edba.example")
    html = t.get("/admin/logs?q=convener@summit.example", headers={"HX-Request": "true"}).text
    assert "convener@summit.example" in html and "<html" not in html
