"""Application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from edba import __version__
from edba.api import v1
from edba.config import Settings, get_settings
from edba.db import Database
from edba.errors import DomainError
from edba.web import admin, convener, public, workspace
from edba.web.deps import LoginRequired, csrf_protect, redirect, render

STATIC = Path(__file__).parent / "web" / "static"


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    settings = settings or get_settings()
    database = database or Database(settings.database_url)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title="E-DBA",
        version=__version__,
        summary="Education Data Bay Area: policy-driven data sharing for higher education.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.db = database

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="edba_session",
        same_site="lax",
        https_only=settings.env == "prod",
        max_age=8 * 3600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if not request.url.path.startswith(("/api/docs", "/gateway")):
            response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    web_deps = [Depends(csrf_protect)]
    for r in (public.router, admin.router, convener.router, workspace.router):
        app.include_router(r, dependencies=web_deps, include_in_schema=False)
    app.include_router(v1.router)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    if settings.mount_demo_gateway:
        from edba.gateway.app import app as gateway_app

        app.mount("/gateway", gateway_app)

    def wants_json(request: Request) -> bool:
        return request.url.path.startswith("/api/")

    @app.exception_handler(LoginRequired)
    async def login_required(request: Request, exc: LoginRequired):
        if wants_json(request):
            return JSONResponse({"detail": "Not signed in"}, status_code=401)
        return redirect("/login")

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        if wants_json(request):
            return JSONResponse({"detail": exc.message}, status_code=exc.status_code)
        return render(
            request,
            "error.html",
            status_code=exc.status_code,
            code=exc.status_code,
            message=exc.message,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        if wants_json(request):
            return JSONResponse(
                {"detail": exc.detail},
                status_code=exc.status_code,
                headers=getattr(exc, "headers", None),
            )
        msg = exc.detail if isinstance(exc.detail, str) else "Something went wrong."
        if exc.status_code == 404 and msg == "Not Found":
            msg = "We couldn't find that page."
        return render(
            request, "error.html", status_code=exc.status_code, code=exc.status_code, message=msg
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if wants_json(request):
            return JSONResponse({"detail": exc.errors()}, status_code=422)
        return render(
            request,
            "error.html",
            status_code=422,
            code=422,
            message="Some fields were missing or invalid.",
        )

    return app


def app_factory() -> FastAPI:
    """Entry point for ``uvicorn edba.main:app_factory --factory``."""
    from edba.services import connector

    settings = get_settings()
    app = create_app(settings)
    app.state.db.create_all()
    if settings.mount_demo_gateway and settings.bank_gateway_url.rstrip("/").endswith("/gateway"):
        # Serve the demo gateway in-process so a single uvicorn worker cannot deadlock on itself.
        connector.set_transport(gateway_transport(settings))
    return app


def gateway_transport(settings: Settings):
    """httpx transport that answers requests for the mounted demo gateway in-process."""
    import httpx
    from starlette.testclient import TestClient

    from edba.gateway.app import app as gateway_app

    prefix = settings.bank_gateway_url.rstrip("/")
    inner = TestClient(gateway_app)
    real = httpx.HTTPTransport()

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if not url.startswith(prefix):
            return real.handle_request(request)
        path = url[len(prefix) :] or "/"
        r = inner.request(
            request.method,
            path,
            content=request.read(),
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
        )
        return httpx.Response(r.status_code, headers=r.headers, content=r.content)

    return httpx.MockTransport(handle)
