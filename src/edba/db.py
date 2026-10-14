"""Engine, session factory and declarative base."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware datetimes that round-trip through SQLite as UTC."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {datetime: UTCDateTime()}


class Database:
    def __init__(self, url: str) -> None:
        kwargs: dict[str, object] = {"future": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if url in ("sqlite://", "sqlite:///:memory:"):
                from sqlalchemy.pool import StaticPool

                kwargs["poolclass"] = StaticPool
        self.engine: Engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", _sqlite_pragmas)
        self.sessionmaker = sessionmaker(self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        from edba import models  # noqa: F401  (register mappers)

        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Unit of work. A ``DomainError`` (a business refusal) still commits: services
        validate before they mutate, and what they did write before refusing is
        deliberate (failed sign-in attempts, failed-payment ledger rows). Any
        other exception rolls back."""
        from edba.errors import DomainError

        with self.sessionmaker() as s:
            try:
                yield s
                s.commit()
            except DomainError:
                s.commit()
                raise
            except Exception:
                s.rollback()
                raise


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()
