"""Service catalog, per-organization service subscriptions, connectors and courses."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from edba.db import Base, utcnow


class ServiceKind(enum.StrEnum):
    COURSE_INFO = "course-info"
    IDENTITY_AUTH = "identity-auth"
    GPA_RECORD = "gpa-record"
    THESIS = "thesis"


class ThesisMode(enum.StrEnum):
    DISPLAY_ONLY = "display_only"
    DOWNLOAD = "download"


@dataclass(frozen=True)
class ServiceSpec:
    kind: ServiceKind
    title: str
    summary: str
    min_level: int  # lowest access level that may use it inside the home workspace
    charging: bool
    operations: tuple[str, ...]  # connector operations that must be configured; () = built in
    batch: bool  # accepts spreadsheet batch input

    @property
    def public(self) -> bool:
        """Public data is visible from other organizations' workspaces (level 1)."""
        return self.min_level == 1


SERVICES: dict[ServiceKind, ServiceSpec] = {
    s.kind: s
    for s in (
        ServiceSpec(
            ServiceKind.COURSE_INFO,
            "Course Information",
            "Browse and search the courses an organization publishes.",
            min_level=1,
            charging=False,
            operations=(),
            batch=False,
        ),
        ServiceSpec(
            ServiceKind.IDENTITY_AUTH,
            "Student Identity Authentication",
            "Yes/no check of a student's identity against the campus registry.",
            min_level=2,
            charging=True,
            operations=("query",),
            batch=True,
        ),
        ServiceSpec(
            ServiceKind.GPA_RECORD,
            "Student GPA Record Access",
            "Enrollment years and GPA of a student, per record.",
            min_level=2,
            charging=True,
            operations=("query",),
            batch=True,
        ),
        ServiceSpec(
            ServiceKind.THESIS,
            "Thesis Sharing",
            "Search theses by keyword; download the PDF when the owner allows it.",
            min_level=1,
            charging=True,
            operations=("search", "download"),
            batch=False,
        ),
    )
}


class OrgService(Base):
    """A catalog service an O-Convener has added to their workspace."""

    __tablename__ = "org_services"
    __table_args__ = (UniqueConstraint("org_id", "kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    kind: Mapped[ServiceKind] = mapped_column(Enum(ServiceKind, native_enum=False, length=20))
    price_cents: Mapped[int] = mapped_column(default=0)
    thesis_mode: Mapped[ThesisMode] = mapped_column(
        Enum(ThesisMode, native_enum=False, length=20), default=ThesisMode.DISPLAY_ONLY
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    @property
    def spec(self) -> ServiceSpec:
        return SERVICES[self.kind]


class ApiEndpoint(Base):
    """How to reach an organization's own system for one service operation.

    ``input_schema`` / ``output_schema`` are flat ``{"field": "type"}`` maps
    (types: string, int, float, bool, file). The service pages are generated
    from them, so a level-3 provider can wire up a new backend without code.
    """

    __tablename__ = "api_endpoints"
    __table_args__ = (UniqueConstraint("org_id", "kind", "operation"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    kind: Mapped[ServiceKind] = mapped_column(Enum(ServiceKind, native_enum=False, length=20))
    operation: Mapped[str] = mapped_column(String(20))
    base_url: Mapped[str] = mapped_column(String(300))
    path: Mapped[str] = mapped_column(String(300))
    method: Mapped[str] = mapped_column(String(8), default="POST")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_by: Mapped[str] = mapped_column(String(254), default="")
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    @property
    def url(self) -> str:
        return self.base_url.rstrip("/") + "/" + self.path.lstrip("/")


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (UniqueConstraint("org_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    units: Mapped[int] = mapped_column(default=3)
    active: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
