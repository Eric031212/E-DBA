from __future__ import annotations

import os
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from edba.config import Settings
from edba.db import Base, Database
from edba.gateway import app as gateway
from edba.main import create_app, gateway_transport
from edba.models import MailMessage
from edba.seed import seed_demo
from edba.services import connector

# Run the suite against PostgreSQL with e.g.
#   EDBA_TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost/edba_test pytest
TEST_DB = os.environ.get("EDBA_TEST_DATABASE_URL", "sqlite://")


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        env="test",
        database_url=TEST_DB,
        secret_key="test-secret-key-0123456789-abcdefgh",
        upload_dir=tmp_path / "uploads",
        bank_gateway_url="http://gateway.test",
        mount_demo_gateway=False,
    )


@pytest.fixture
def database(settings) -> Iterator[Database]:
    gateway.reset()
    connector.set_transport(gateway_transport(settings))
    db = Database(settings.database_url)
    Base.metadata.drop_all(db.engine)
    db.create_all()
    yield db
    connector.set_transport(None)
    if not settings.database_url.startswith("sqlite"):
        Base.metadata.drop_all(db.engine)
    db.engine.dispose()


@pytest.fixture
def seeded(database, settings) -> Database:
    with database.session() as s:
        seed_demo(s, settings)
    return database


@pytest.fixture
def app(seeded, settings):
    return create_app(settings, seeded)


class Browser(TestClient):
    """TestClient that knows how to sign in through the emailed-code flow and submit forms."""

    db: Database

    def csrf(self, path: str = "/login") -> str:
        html = self.get(path).text
        m = re.search(r'name="_csrf" value="([^"]+)"', html)  # the real hidden form field
        assert m, f"no csrf token on {path}"
        return m.group(1)

    def post_form(
        self, path: str, data: dict | None = None, files=None, csrf_from: str = "/login", **kw
    ):
        data = dict(data or {})
        data["_csrf"] = self.csrf(csrf_from)
        return self.post(path, data=data, files=files, **kw)

    def last_code(self, email: str) -> str:
        with self.db.session() as s:
            from sqlalchemy import select

            m = s.scalar(
                select(MailMessage).where(MailMessage.to == email).order_by(MailMessage.id.desc())
            )
            assert m is not None, f"no mail for {email}"
            return re.search(r"\b(\d{6})\b", m.subject).group(1)  # type: ignore[union-attr]

    def login(self, email: str):
        r = self.post_form("/login", {"email": email})
        assert r.status_code in (200, 303), r.text
        code = self.last_code(email)
        return self.post_form("/login/verify", {"code": code}, csrf_from="/login/verify")


@pytest.fixture
def browser(app, seeded) -> Iterator[Browser]:
    with Browser(app, follow_redirects=True) as c:
        c.db = seeded
        yield c


@pytest.fixture
def make_browser(app, seeded):
    clients: list[Browser] = []

    def make() -> Browser:
        c = Browser(app, follow_redirects=True)
        c.__enter__()
        c.db = seeded
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.__exit__(None, None, None)
