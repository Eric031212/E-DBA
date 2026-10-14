"""Request context for the server-rendered UI: DB session, signed-in user, flashes, CSRF."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from edba import authz
from edba.config import Settings
from edba.db import Database
from edba.errors import DomainError
from edba.models import ACCESS_LEVELS, SERVICES, Organization, Role, User
from edba.money import fmt, plain

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _dt(value: datetime | None, short: bool = False) -> str:
    if value is None:
        return "—"
    local = value.astimezone()
    return local.strftime("%b %d, %H:%M" if short else "%Y-%m-%d %H:%M")


TEMPLATES.env.filters["money"] = fmt
TEMPLATES.env.filters["plain"] = plain
TEMPLATES.env.filters["dt"] = _dt
TEMPLATES.env.globals.update(SERVICES=SERVICES, ACCESS_LEVELS=ACCESS_LEVELS, Role=Role)


class LoginRequired(Exception):
    pass


def get_db(request: Request) -> Iterator[Session]:
    database: Database = request.app.state.db
    with database.session() as s:
        yield s


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    user = db.get(User, uid)
    if user is None or not user.is_active:
        request.session.pop("uid", None)
        return None
    return user


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise LoginRequired()
    return user


@dataclass
class Ctx:
    request: Request
    db: Session
    settings: Settings
    user: User

    def render(self, template: str, **kw: Any) -> Any:
        return render(self.request, template, user=self.user, **kw)


def ctx(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    settings: Settings = Depends(get_settings),
) -> Ctx:
    return Ctx(request, db, settings, user)


def role_ctx(*roles: Role):
    def dep(c: Ctx = Depends(ctx)) -> Ctx:
        if c.user.role not in roles:
            raise HTTPException(403, "You do not have access to this page.")
        return c

    return dep


def convener_ctx(c: Ctx = Depends(role_ctx(Role.CONVENER))) -> tuple[Ctx, Organization]:
    return c, authz.require_convener(c.user)


# ------------------------------------------------------------------ helpers


def flash(request: Request, message: str, kind: str = "success") -> None:
    request.session.setdefault("_flashes", []).append({"kind": kind, "message": message})


def pop_flashes(request: Request) -> list[dict[str, str]]:
    return request.session.pop("_flashes", [])


def csrf_token(request: Request) -> str:
    tok = request.session.get("_csrf")
    if not tok:
        tok = secrets.token_urlsafe(24)
        request.session["_csrf"] = tok
    return tok


def render(request: Request, template: str, status_code: int = 200, **kw: Any) -> Any:
    kw.setdefault("user", None)
    return TEMPLATES.TemplateResponse(
        request,
        template,
        {
            "flashes": pop_flashes(request),
            "csrf": csrf_token(request),
            "settings": request.app.state.settings,
            **kw,
        },
        status_code=status_code,
    )


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


@contextmanager
def attempt(request: Request) -> Iterator[None]:
    """Turn domain errors into an error flash; the caller then redirects as usual."""
    try:
        yield
    except DomainError as e:
        flash(request, e.message, "error")


def home_url(user: User) -> str:
    if user.role is Role.T_ADMIN or user.role.is_e_admin:
        return "/admin"
    if user.role is Role.CONVENER:
        return "/org"
    if user.role is Role.APPLICANT:
        return "/application"
    org = user.organization
    return f"/w/{org.slug}" if org else "/"


async def csrf_protect(request: Request) -> None:
    """Double-submit check for every state-changing request of the web UI."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    expected = request.session.get("_csrf")
    sent = request.headers.get("X-CSRF-Token")
    if not sent:
        form = await request.form()
        sent = str(form.get("_csrf") or "")
    if not expected or not secrets.compare_digest(str(expected), sent):
        raise HTTPException(403, "Your session expired or the form is stale. Reload and try again.")
