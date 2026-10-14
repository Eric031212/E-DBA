"""``edba`` command line: database setup, demo data, dev server."""

from __future__ import annotations

import typer

from edba.config import get_settings
from edba.db import Database

app = typer.Typer(no_args_is_help=True, help="E-DBA administration")


def _db() -> Database:
    return Database(get_settings().database_url)


@app.command()
def init() -> None:
    """Create tables and the bootstrap T-Admin."""
    from edba.seed import ensure_t_admin

    s = get_settings()
    db = _db()
    db.create_all()
    with db.session() as session:
        u = ensure_t_admin(session, s)
    typer.echo(f"Database ready. T-Admin: {u.email} (sign in with an emailed code).")


@app.command()
def seed() -> None:
    """Load the demo organizations, members, services and applications."""
    from edba.main import gateway_transport
    from edba.seed import seed_demo
    from edba.services import connector

    s = get_settings()
    connector.set_transport(gateway_transport(s))
    db = _db()
    db.create_all()
    with db.session() as session:
        seed_demo(session, s)
    typer.echo("Demo data loaded. Open /dev/mailbox to read sign-in codes.")


@app.command("verify-audit")
def verify_audit() -> None:
    """Check the audit hash chain; exits non-zero if it was tampered with."""
    from edba.services.audit import verify_chain

    with _db().session() as session:
        r = verify_chain(session)
    if r.ok:
        typer.echo(f"OK: {r.checked} events verified.")
    else:
        typer.echo(f"BROKEN at event {r.broken_at}: {r.reason}", err=True)
        raise typer.Exit(1)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Run the web app (and the mounted demo gateway)."""
    import uvicorn

    uvicorn.run("edba.main:app_factory", factory=True, host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
