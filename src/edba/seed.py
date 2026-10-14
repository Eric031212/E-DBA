"""Demo data: two registered universities wired to the demo gateway, admins, applications."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from edba.config import Settings
from edba.gateway.pdf import render_pdf
from edba.models import (
    ApplicationReview,
    ApplicationStatus,
    Course,
    DomainRule,
    HelpTicket,
    Organization,
    RegistrationApplication,
    ReviewDecision,
    ReviewStage,
    Role,
    ServiceKind,
    ThesisMode,
    User,
)
from edba.services import audit, billing, catalog, policies

T_ADMIN = "tadmin@edba.example"
E_ADMIN = "eadmin@edba.example"
SENIOR = "senior@edba.example"


def ensure_t_admin(db: Session, settings: Settings) -> User:
    u = db.scalar(select(User).where(User.email == settings.t_admin_email))
    if u is None:
        u = User(email=settings.t_admin_email, name="Technical Admin", role=Role.T_ADMIN)
        db.add(u)
        db.flush()
        audit.record(
            db, "system.bootstrap", f"Bootstrap T-Admin {u.email} created", actor_email="system"
        )
    billing.fee_schedule(db)
    return u


ORGS: list[dict[str, Any]] = [
    {
        "full": "Harbor University",
        "short": "HBU",
        "campus": "harbor",
        "convener": ("convener@harbor.example", "Grace Ho"),
        "bank": ("FutureLearn Federal Bank", "Utopia Credit Union", "670547811218584", "9978"),
        "members": [
            ("provider@harbor.example", "Priya Raman", 3, 500),
            ("staff@harbor.example", "Sam Wong", 2, 200),
            ("student@harbor.example", "Lily Chen", 1, 80),
        ],
        "rule": ("@students.harbor.example", 1, 50),
        "prices": {
            ServiceKind.IDENTITY_AUTH: "2",
            ServiceKind.GPA_RECORD: "3",
            ServiceKind.THESIS: "5",
        },
        "thesis_mode": ThesisMode.DOWNLOAD,
        "courses": [
            ("COMP3013", "Software Engineering", "Requirements, design, testing and teamwork.", 3),
            ("COMP3053", "Database Systems", "Relational design, SQL and transactions.", 3),
            ("DS2003", "Data Visualization", "Perception, charts and dashboards.", 3),
            ("COMP4093", "Advanced Workshop", "Capstone project with industry mentors.", 6),
            ("STAT2013", "Probability and Statistics", "Random variables and inference.", 3),
        ],
    },
    {
        "full": "Summit Institute of Technology",
        "short": "SIT",
        "campus": "summit",
        "convener": ("convener@summit.example", "Omar Diaz"),
        "bank": ("Global Education Bank", "Campus Cash Cooperative", "641387141765274", "8799"),
        "members": [
            ("provider@summit.example", "Ken Ito", 3, 300),
            ("researcher@summit.example", "Mia Rossi", 1, 120),
        ],
        "rule": None,
        "prices": {ServiceKind.THESIS: "8"},
        "thesis_mode": ThesisMode.DOWNLOAD,
        "courses": [
            ("CS101", "Introduction to Computing", "Programming fundamentals in Python.", 4),
            ("CS340", "Distributed Systems", "Consensus, replication and fault tolerance.", 4),
            ("EE210", "Signals and Systems", "Linear systems, Fourier analysis.", 3),
        ],
    },
]


def seed_demo(db: Session, settings: Settings) -> None:
    if db.scalar(select(Organization).limit(1)):
        return
    t_admin = ensure_t_admin(db, settings)
    e_admin = User(email=E_ADMIN, name="Erin Admin", role=Role.E_ADMIN)
    senior = User(email=SENIOR, name="Sophie Senior", role=Role.SENIOR_E_ADMIN)
    db.add_all([e_admin, senior])
    db.flush()
    gw = settings.bank_gateway_url.rstrip("/")

    for spec in ORGS:
        org = Organization(full_name=spec["full"], short_name=spec["short"], level1_paid=True)
        db.add(org)
        db.flush()
        cemail, cname = spec["convener"]
        app = RegistrationApplication(
            org_full_name=org.full_name,
            org_short_name=org.short_name,
            convener_email=cemail,
            convener_name=cname,
            proof_path="",
            proof_sha256="0" * 64,
            email_verified=True,
            status=ApplicationStatus.ACCEPTED,
            org_id=org.id,
        )
        app.reviews = [
            ApplicationReview(
                stage=ReviewStage.E_ADMIN,
                decision=ReviewDecision.APPROVE,
                reviewer_email=E_ADMIN,
                notes="Proof of registration checked.",
            ),
            ApplicationReview(
                stage=ReviewStage.SENIOR, decision=ReviewDecision.APPROVE, reviewer_email=SENIOR
            ),
        ]
        db.add(app)
        conv = User(email=cemail, name=cname, role=Role.CONVENER, org_id=org.id)
        db.add(conv)
        db.flush()
        audit.record(
            db,
            "application.approved",
            f"Seeded {org.full_name} ({org.short_name})",
            actor=senior,
            org_id=org.id,
        )
        bank, name, no, pw = spec["bank"]
        billing.set_bank_account(
            db, settings, conv, org, bank_name=bank, account_name=name, account_no=no, password=pw
        )
        for email, mname, level, quota in spec["members"]:
            db.add(
                User(
                    email=email,
                    name=mname,
                    role=Role.MEMBER,
                    org_id=org.id,
                    access_level=level,
                    quota_cents=quota * 100,
                    fee_paid=True,
                )
            )
        if spec["rule"]:
            dom, level, quota = spec["rule"]
            db.add(
                DomainRule(org_id=org.id, domain=dom, access_level=level, quota_cents=quota * 100)
            )

        catalog.add_service(db, conv, org, ServiceKind.COURSE_INFO)
        for kind, price in spec["prices"].items():
            mode = spec["thesis_mode"] if kind is ServiceKind.THESIS else ThesisMode.DISPLAY_ONLY
            catalog.add_service(db, conv, org, kind, price, mode)
        provider = db.scalar(
            select(User).where(
                User.org_id == org.id, User.access_level == 3, User.role == Role.MEMBER
            )
        )
        assert provider is not None
        base = f"{gw}/campus/{spec['campus']}"
        endpoints = {
            (ServiceKind.IDENTITY_AUTH, "query"): (
                "/student/authenticate",
                "POST",
                '{"name": "string", "id": "string", "photo": "file"}',
                '{"status": "string"}',
            ),
            (ServiceKind.GPA_RECORD, "query"): (
                "/student/record",
                "POST",
                '{"name": "string", "id": "string"}',
                '{"name": "string", "enroll_year": "string", "graduation_year": "string", "gpa": "float"}',
            ),
            (ServiceKind.THESIS, "search"): (
                "/thesis/search",
                "POST",
                '{"keywords": "string"}',
                '{"title": "string", "abstract": "string", "author": "string", "year": "string"}',
            ),
            (ServiceKind.THESIS, "download"): ("/thesis/pdf", "GET", '{"title": "string"}', ""),
        }
        for (kind, op), (path, method, ins, outs) in endpoints.items():
            if kind in spec["prices"]:
                catalog.save_endpoint(
                    db,
                    settings,
                    provider,
                    org,
                    kind,
                    op,
                    base_url=base,
                    path=path,
                    method=method,
                    input_schema=ins,
                    output_schema=outs,
                )
        for code, title, desc, units in spec["courses"]:
            db.add(Course(org_id=org.id, code=code, title=title, description=desc, units=units))

    # A third organization still going through review.
    pending = RegistrationApplication(
        org_full_name="Lakeside College",
        org_short_name="LSC",
        convener_email="dean@lakeside.example",
        convener_name="Noah Park",
        proof_path="",
        proof_sha256="0" * 64,
        email_verified=True,
        status=ApplicationStatus.FIRST_APPROVED,
    )
    pending.reviews = [
        ApplicationReview(
            stage=ReviewStage.E_ADMIN,
            decision=ReviewDecision.APPROVE,
            reviewer_email=E_ADMIN,
            notes="Documents look complete.",
        )
    ]
    db.add(pending)
    db.add(User(email="dean@lakeside.example", name="Noah Park", role=Role.APPLICANT))
    db.add(
        RegistrationApplication(
            org_full_name="Riverbend Polytechnic",
            org_short_name="RBP",
            convener_email="it@riverbend.example",
            convener_name="Ivy Tran",
            proof_path="",
            proof_sha256="0" * 64,
            email_verified=True,
        )
    )
    db.add(User(email="it@riverbend.example", name="Ivy Tran", role=Role.APPLICANT))

    pdf = render_pdf(
        "E-DBA Data Sharing Policy",
        [
            "1. Personal data leaves its home organization only through a configured E-DBA service.",
            "2. Every access is logged in the tamper-evident audit trail.",
            "3. Theses are shared display-only unless the owning organization enables download.",
            "4. Private services (identity, GPA) are never exposed to other organizations' users.",
        ],
    )
    policies.create(
        db,
        settings,
        e_admin,
        "Data Sharing Policy",
        "Baseline rules every member organization agrees to.",
        "policy.pdf",
        pdf,
    )
    pdf2 = render_pdf(
        "Acceptable Use of Student Records",
        [
            "Student identity and GPA services may only be used for admission and verification.",
            "Batch queries must be justified by an institutional purpose.",
        ],
    )
    policies.create(
        db,
        settings,
        e_admin,
        "Acceptable Use of Student Records",
        "Limits on identity and GPA lookups.",
        "aup.pdf",
        pdf2,
    )
    db.add(
        HelpTicket(
            author_email="staff@harbor.example",
            author_role="Data user",
            title="Batch upload template?",
            body="Which columns does the GPA batch spreadsheet need?",
        )
    )
    audit.record(db, "system.seeded", "Demo data loaded", actor=t_admin)
