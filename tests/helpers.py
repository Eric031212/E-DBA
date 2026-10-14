from __future__ import annotations

import io

from openpyxl import Workbook
from sqlalchemy import select

from edba.db import Database
from edba.gateway import app as gateway
from edba.models import Organization, User


def xlsx(rows: list[list[object]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def balance(name: str) -> float:
    return next(a["balance"] for a in gateway.balances() if a["name"] == name)


def user(db: Database, email: str) -> User:
    with db.session() as s:
        u = s.scalar(select(User).where(User.email == email))
        assert u is not None
        s.expunge(u)
        return u


def org(db: Database, short: str) -> Organization:
    with db.session() as s:
        o = s.scalar(select(Organization).where(Organization.short_name == short))
        assert o is not None
        s.expunge(o)
        return o


PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
