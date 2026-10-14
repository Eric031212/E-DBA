import pytest
from helpers import xlsx

from edba.errors import DomainError
from edba.money import fmt, to_cents
from edba.services import connector
from edba.services.sheets import read_table


def test_money():
    assert to_cents("12.345") == 1235 and to_cents(3) == 300 and to_cents("") == 0
    assert fmt(123456) == "¥1,234.56" and fmt(-5) == "-¥0.05"
    for bad in ["abc", "-1"]:
        with pytest.raises(DomainError):
            to_cents(bad)


def test_schema_and_coercion():
    s = connector.parse_schema(
        '{"n": "int", "x": "float", "ok": "bool", "name": "string", "f": "file"}'
    )
    assert connector.coerce(s, {"n": "4", "x": "2.5", "ok": "yes", "name": " a "}) == {
        "n": 4,
        "x": 2.5,
        "ok": True,
        "name": "a",
    }
    with pytest.raises(DomainError, match="n must be of type int"):
        connector.coerce(s, {"n": "four", "x": "1", "ok": "1", "name": "a"})
    with pytest.raises(DomainError, match="name is required"):
        connector.coerce({"name": "string"}, {})
    assert connector.parse_schema('""', allow_empty=True) == {}
    for bad in ['{"bad key": "string"}', "{}"]:
        with pytest.raises(DomainError):
            connector.parse_schema(bad)


def test_allow_list(settings):
    s = settings.model_copy(update={"connector_allowed_hosts": "registry.edu, gateway.test"})
    connector.check_url(s, "https://registry.edu/x")
    with pytest.raises(DomainError, match="allow-list"):
        connector.check_url(s, "http://169.254.169.254/latest")


def test_read_table():
    header, rows = read_table(
        "a.xlsx", xlsx([["Name", "E mail"], ["x", 1.0], [None, None], ["y", 2]])
    )
    assert header == ["name", "e_mail"] and rows == [["x", "1"], ["y", "2"]]
    header, rows = read_table("a.csv", "name,id\nÅsa,1\n".encode())
    assert rows == [["Åsa", "1"]]
    for name, data in [("a.csv", b""), ("a.xlsx", b"junk"), ("a.csv", b"\xff\xfe\x00bad")]:
        with pytest.raises(DomainError):
            read_table(name, data)


def test_cli_init_and_seed(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from edba import cli
    from edba.config import get_settings

    monkeypatch.setenv("EDBA_DATABASE_URL", f"sqlite:///{tmp_path}/cli.db")
    monkeypatch.setenv("EDBA_UPLOAD_DIR", str(tmp_path / "up"))
    get_settings.cache_clear()
    try:
        r = CliRunner()
        out = r.invoke(cli.app, ["init"])
        assert out.exit_code == 0 and "tadmin@edba.example" in out.output
        out = r.invoke(cli.app, ["seed"])
        assert out.exit_code == 0, out.output
        out = r.invoke(cli.app, ["verify-audit"])
        assert out.exit_code == 0 and "OK" in out.output
    finally:
        from edba.services import connector as c

        c.set_transport(None)
        get_settings.cache_clear()


def test_app_factory_serves_gateway_in_process(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from edba.config import get_settings
    from edba.main import app_factory
    from edba.services import connector as c

    monkeypatch.setenv("EDBA_DATABASE_URL", f"sqlite:///{tmp_path}/f.db")
    monkeypatch.setenv("EDBA_UPLOAD_DIR", str(tmp_path / "up"))
    get_settings.cache_clear()
    try:
        app = app_factory()
        with TestClient(app) as client:
            assert client.get("/gateway/bank/balances").status_code == 200
            assert client.get("/").headers["x-frame-options"] == "DENY"
        s = get_settings()
        assert c.bank_authenticate(s, "E-DBA Bank", "E-DBA account", "596117071864958", "edba123")
    finally:
        c.set_transport(None)
        get_settings.cache_clear()
