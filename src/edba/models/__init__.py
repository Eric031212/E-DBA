"""ORM models.

The original v3 schema used SQLAlchemy joined-table polymorphism with a status
discriminator (INVALID -> UNDER_REVIEW -> O-Convener ...), which meant deleting
and re-inserting user rows on every state change. v4 keeps the same domain but
models it explicitly: one ``users`` table with a ``role`` column, applications
with an append-only review trail, and money as integer cents.
"""

from edba.models.audit import AuditEvent
from edba.models.billing import BankAccount, FeeSchedule, LedgerEntry, LedgerKind, LedgerStatus
from edba.models.catalog import (
    SERVICES,
    ApiEndpoint,
    Course,
    OrgService,
    ServiceKind,
    ServiceSpec,
    ThesisMode,
)
from edba.models.content import HelpTicket, MailMessage, Policy, PolicyVersion
from edba.models.identity import (
    ACCESS_LEVELS,
    ApplicationReview,
    ApplicationStatus,
    DomainRule,
    Organization,
    OtpChallenge,
    RegistrationApplication,
    ReviewDecision,
    ReviewStage,
    Role,
    User,
)

__all__ = [
    "ACCESS_LEVELS",
    "SERVICES",
    "ApiEndpoint",
    "ApplicationReview",
    "ApplicationStatus",
    "AuditEvent",
    "BankAccount",
    "Course",
    "DomainRule",
    "FeeSchedule",
    "HelpTicket",
    "LedgerEntry",
    "LedgerKind",
    "LedgerStatus",
    "MailMessage",
    "OrgService",
    "Organization",
    "OtpChallenge",
    "Policy",
    "PolicyVersion",
    "RegistrationApplication",
    "ReviewDecision",
    "ReviewStage",
    "Role",
    "ServiceKind",
    "ServiceSpec",
    "ThesisMode",
    "User",
]
