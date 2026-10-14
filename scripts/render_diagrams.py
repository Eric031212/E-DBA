"""Render the documentation figures in docs/figures/ as hand-laid-out SVG.

    python scripts/render_diagrams.py

No dependencies; every coordinate is chosen by hand so the figures stay crisp
and diff-able. Palette matches the web UI.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "figures"

INK = "#16191f"
MUTED = "#5d6573"
LINE = "#8a93a3"
BRAND = "#0f6e74"
BRAND_SOFT = "#e3f3f3"
ORANGE = "#c2410c"
ORANGE_SOFT = "#fdf0e9"
BLUE = "#1d4ed8"
BLUE_SOFT = "#e8efff"
GREEN = "#15803d"
GREEN_SOFT = "#e7f6ec"
RED = "#b42318"
RED_SOFT = "#fdecea"
GREY_SOFT = "#f0f2f5"
FONT = "ui-sans-serif,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,'SF Mono',Menlo,Consolas,monospace"


class Svg:
    def __init__(self, w: int, h: int, title: str) -> None:
        self.w, self.h = w, h
        self.parts: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'font-family="{FONT}" role="img" aria-label="{escape(title)}">',
            "<defs>"
            + "".join(
                f'<marker id="a-{n}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
                f'markerHeight="7" orient="auto-start-reverse"><path d="M0 0 10 5 0 10z" fill="{c}"/></marker>'
                for n, c in (("g", LINE), ("b", BRAND), ("o", ORANGE), ("bl", BLUE), ("gr", GREEN), ("r", RED))
            )
            + "</defs>",
            f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
        ]

    def add(self, s: str) -> None:
        self.parts.append(s)

    def text(self, x: float, y: float, s: str, size: float = 13, fill: str = INK, weight: int = 400,
             anchor: str = "start", mono: bool = False, italic: bool = False) -> None:
        fam = f' font-family="{MONO}"' if mono else ""
        st = ' font-style="italic"' if italic else ""
        self.add(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}" '
                 f'text-anchor="{anchor}"{fam}{st}>{escape(s)}</text>')

    def box(self, x: float, y: float, w: float, h: float, fill: str = "#fff", stroke: str = "#d5dae1",
            r: float = 10, dash: bool = False, sw: float = 1.4) -> None:
        d = ' stroke-dasharray="5 4"' if dash else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" '
                 f'stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def card(self, x: float, y: float, w: float, h: float, title: str, lines: list[str] = (),  # type: ignore[assignment]
             fill: str = "#fff", stroke: str = "#d5dae1", tcolor: str = INK, mono_lines: bool = False) -> None:
        self.box(x, y, w, h, fill, stroke)
        self.text(x + w / 2, y + 24, title, 14, tcolor, 700, "middle")
        for i, ln in enumerate(lines):
            self.text(x + w / 2, y + 44 + i * 17, ln, 11.5 if mono_lines else 12, MUTED, 400, "middle",
                      mono=mono_lines)

    def arrow(self, pts: list[tuple[float, float]], color: str = LINE, m: str = "g", dash: bool = False,
              both: bool = False, sw: float = 1.6) -> None:
        d = "M" + " L".join(f"{x} {y}" for x, y in pts)
        da = ' stroke-dasharray="6 5"' if dash else ""
        start = f' marker-start="url(#a-{m})"' if both else ""
        self.add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"{da}{start} '
                 f'marker-end="url(#a-{m})"/>')

    def pill(self, x: float, y: float, s: str, color: str, soft: str, size: float = 11.5) -> None:
        w = len(s) * size * 0.58 + 18
        self.add(f'<rect x="{x - w / 2}" y="{y - 12}" width="{w}" height="22" rx="11" fill="{soft}" '
                 f'stroke="{color}" stroke-width="1"/>')
        self.text(x, y + 3.5, s, size, color, 600, "middle")

    def save(self, name: str) -> None:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{name}.svg").write_text("\n".join([*self.parts, "</svg>"]) + "\n")
        print("wrote", OUT / f"{name}.svg")


# --------------------------------------------------------------------------- architecture


def architecture() -> None:
    s = Svg(1100, 700, "E-DBA v4 architecture")
    s.text(40, 44, "E-DBA v4 · system architecture", 20, INK, 700)
    s.text(40, 66, "One FastAPI process, layered: presentation → services → domain → persistence; outbound connectors to member systems.", 12.5, MUTED)

    # actors
    actors = [("Data users", "levels 1 · 2 · 3", 120), ("O-Conveners", "one per organization", 330),
              ("E-Admins", "review · policies · fees", 540), ("T-Admin", "accounts · logs · help", 750),
              ("Scripts / campus apps", "bearer-token JSON API", 960)]
    for name, sub, cx in actors:
        s.box(cx - 92, 92, 184, 48, GREY_SOFT, "#d5dae1")
        s.text(cx, 113, name, 13, INK, 700, "middle")
        s.text(cx, 130, sub, 11, MUTED, 400, "middle")
        s.arrow([(cx, 140), (cx, 176)], LINE, "g")

    # presentation
    s.box(30, 176, 1040, 92, BRAND_SOFT, BRAND, 12)
    s.text(48, 198, "PRESENTATION", 11, BRAND, 700)
    s.card(48, 206, 470, 52, "Web UI · Jinja2 templates + htmx", [], "#fff", BRAND)
    s.text(283, 250, "server-rendered pages, partial swaps, CSRF double-submit, signed session", 11, MUTED, 400, "middle")
    s.card(540, 206, 250, 52, "REST API /api/v1", [], "#fff", BRAND)
    s.text(665, 250, "JWT bearer · OpenAPI docs", 11, MUTED, 400, "middle")
    s.card(808, 206, 244, 52, "CLI · edba", [], "#fff", BRAND)
    s.text(930, 250, "init · seed · verify-audit · serve", 11, MUTED, 400, "middle")

    s.arrow([(550, 268), (550, 296)], BRAND, "b")

    # services
    s.box(30, 296, 1040, 160, "#fff", "#c9cfd8", 12)
    s.text(48, 318, "SERVICE LAYER (edba.services)", 11, MUTED, 700)
    svcs = [("auth", "emailed OTP, domain\nsign-in, fee gating"), ("registration", "apply → review ×2\nfour-eyes, timeline"),
            ("members", "xlsx/csv import\nwildcard domains"), ("catalog", "services, prices,\nconnector configs"),
            ("usage", "quota, batch,\nthesis, settlement"), ("billing", "bank accounts, fees,\nidempotent ledger"),
            ("courses", "catalogue CRUD\n+ search"), ("policies", "versioned PDFs"),
            ("helpdesk", "seek-help tickets"), ("audit", "SHA-256 hash chain\nsearch · verify")]
    for i, (name, desc) in enumerate(svcs):
        col, row = i % 5, i // 5
        x, y = 48 + col * 204, 328 + row * 62
        hot = name in ("audit", "usage", "billing")
        s.box(x, y, 192, 54, ORANGE_SOFT if hot else GREY_SOFT, ORANGE if hot else "#d5dae1", 8)
        s.text(x + 12, y + 20, name, 13, ORANGE if hot else INK, 700, mono=True)
        for j, ln in enumerate(desc.split("\n")):
            s.text(x + 12, y + 36 + j * 13, ln, 10.5, MUTED)

    # domain + authz
    s.arrow([(550, 456), (550, 482)], LINE, "g")
    s.box(30, 482, 510, 76, "#fff", "#c9cfd8", 12)
    s.text(48, 504, "DOMAIN", 11, MUTED, 700)
    s.text(48, 526, "authz.py — effective level = own level at home,", 12, INK)
    s.text(48, 543, "level 1 elsewhere; services carry a min level", 12, INK)
    s.box(560, 482, 510, 76, "#fff", "#c9cfd8", 12)
    s.text(578, 504, "MODELS (SQLAlchemy 2.0, typed)", 11, MUTED, 700)
    s.text(578, 526, "17 tables · money in integer cents · UTC timestamps", 12, INK)
    s.text(578, 543, "Alembic migrations · SQLite (dev) / PostgreSQL (prod)", 12, INK)

    # persistence + outbound
    s.arrow([(800, 558), (800, 590)], LINE, "g")
    s.box(640, 590, 320, 74, BLUE_SOFT, BLUE, 12)
    s.text(800, 618, "PostgreSQL 16 / SQLite", 14, BLUE, 700, "middle")
    s.text(800, 638, "audit_events chained by prev_hash", 11.5, MUTED, 400, "middle")
    s.text(800, 654, "bank secrets Fernet-encrypted at rest", 11.5, MUTED, 400, "middle")

    s.arrow([(250, 456), (250, 470), (16, 470), (16, 627), (40, 627)], ORANGE, "o", dash=True)
    s.box(40, 590, 560, 74, "#fff", ORANGE, 12, dash=True)
    s.text(320, 614, "Member organizations' own systems (via connectors)", 13.5, ORANGE, 700, "middle")
    s.text(320, 634, "student registry · GPA records · thesis repository — httpx, schema-driven,", 11.5, MUTED, 400, "middle")
    s.text(320, 650, "host allow-list, timeouts · bank gateway with Idempotency-Key", 11.5, MUTED, 400, "middle")
    s.save("architecture")


# --------------------------------------------------------------------------- registration state machine


def registration() -> None:
    s = Svg(1100, 430, "Organization registration state machine")
    s.text(40, 44, "Organization registration · state machine", 20, INK, 700)
    s.text(40, 66, "Each transition appends an ApplicationReview row; the applicant's timeline is derived from those rows, not from the final status.", 12.5, MUTED)

    def state(cx: float, cy: float, name: str, sub: str, color: str, soft: str, w: float = 190) -> None:
        s.box(cx - w / 2, cy - 34, w, 68, soft, color, 34, sw=1.8)
        s.text(cx, cy - 4, name, 15, color, 700, "middle", mono=True)
        s.text(cx, cy + 16, sub, 11.5, MUTED, 400, "middle")

    s.add(f'<circle cx="60" cy="200" r="10" fill="{INK}"/>')
    state(200, 200, "unverified", "form + proof uploaded", LINE, GREY_SOFT)
    state(450, 200, "pending", "waiting for an E-Admin", BLUE, BLUE_SOFT)
    state(720, 200, "first_approved", "waiting for a Senior", BLUE, BLUE_SOFT, 210)
    state(980, 200, "accepted", "org + O-Convener", GREEN, GREEN_SOFT, 170)
    state(585, 360, "rejected", "reason shown to applicant", RED, RED_SOFT, 220)

    s.arrow([(70, 200), (104, 200)], INK, "g")
    s.arrow([(296, 200), (354, 200)], BLUE, "bl")
    s.text(325, 186, "email OTP", 11.5, BLUE, 600, "middle")
    s.arrow([(546, 200), (614, 200)], BLUE, "bl")
    s.text(580, 178, "E-Admin", 11.5, BLUE, 700, "middle")
    s.text(580, 192, "approves", 11, MUTED, 400, "middle")
    s.arrow([(826, 200), (894, 200)], GREEN, "gr")
    s.text(860, 150, "Senior E-Admin", 11.5, GREEN, 700, "middle")
    s.text(860, 165, "approves", 11, MUTED, 400, "middle")
    s.text(860, 180, "(≠ first reviewer)", 11, MUTED, 400, "middle")
    s.arrow([(450, 234), (450, 290), (505, 330)], RED, "r")
    s.text(420, 300, "E-Admin rejects", 11.5, RED, 700, "end")
    s.arrow([(720, 234), (720, 290), (665, 330)], RED, "r")
    s.text(750, 300, "Senior rejects", 11.5, RED, 700, "start")
    s.text(750, 315, "(v3 showed this as an E-Admin rejection)", 11, MUTED, 400, "start", italic=True)
    s.box(40, 300, 300, 92, "#fff", "#d5dae1", 10, dash=True)
    s.text(56, 322, "Guards", 12.5, INK, 700)
    s.text(56, 342, "• short name unique across orgs", 11.5, MUTED)
    s.text(56, 359, "• rejection needs a written reason", 11.5, MUTED)
    s.text(56, 376, "• one review row per stage (unique)", 11.5, MUTED)
    s.save("registration_states")


# --------------------------------------------------------------------------- data model


def er() -> None:
    s = Svg(1100, 760, "E-DBA data model")
    s.text(40, 44, "Data model (17 tables, core relations)", 20, INK, 700)
    s.text(40, 66, "One users table with a role column replaces v3's five-way joined-table inheritance. ◆ = primary key, → = foreign key.", 12.5, MUTED)

    def table(x: float, y: float, name: str, cols: list[str], color: str = BRAND, soft: str = BRAND_SOFT,
              w: float = 230) -> tuple[float, float, float, float]:
        h = 34 + len(cols) * 18 + 10
        s.box(x, y, w, h, "#fff", color, 8, sw=1.5)
        s.add(f'<path d="M{x} {y + 8} a8 8 0 0 1 8 -8 h{w - 16} a8 8 0 0 1 8 8 v22 h{-w} z" fill="{soft}"/>')
        s.text(x + 12, y + 21, name, 13.5, color, 700, mono=True)
        for i, c in enumerate(cols):
            col = BRAND if c.startswith("◆") else (ORANGE if "→" in c else INK)
            s.text(x + 12, y + 50 + i * 18, c, 11.5, col, 400, mono=True)
        return x, y, w, h

    org = table(420, 96, "organizations", ["◆ id", "full_name", "short_name  (unique)", "level1_paid"])
    users = table(60, 96, "users", ["◆ id", "email  (unique)", "role  t_admin|e_admin|…", "org_id → organizations",
                                     "access_level  1..3", "quota_cents", "fee_paid"])
    rules = table(420, 250, "domain_rules", ["◆ id", "org_id → organizations", "domain  @mail.uic.edu.cn",
                                              "access_level · quota_cents"])
    apps = table(60, 360, "applications", ["◆ id", "org_short_name · convener_email", "proof_path · proof_sha256",
                                            "status  pending|first_approved|…", "org_id → organizations"], BLUE, BLUE_SOFT, 260)
    revs = table(60, 560, "application_reviews", ["◆ id", "application_id → applications", "stage  e_admin|senior",
                                                   "decision · reviewer_email · notes"], BLUE, BLUE_SOFT, 260)
    svc = table(780, 96, "org_services", ["◆ id", "org_id → organizations", "kind  course-info|thesis|…",
                                           "price_cents · thesis_mode", "unique(org_id, kind)"], ORANGE, ORANGE_SOFT, 270)
    eps = table(780, 260, "api_endpoints", ["◆ id", "org_id · kind · operation", "base_url · path · method",
                                             "input_schema · output_schema"], ORANGE, ORANGE_SOFT, 270)
    courses = table(780, 410, "courses", ["◆ id", "org_id → organizations", "code · title · units · active"], ORANGE, ORANGE_SOFT, 270)
    bank = table(420, 400, "bank_accounts", ["◆ id", "org_id → organizations (1:1)", "bank_name · account_no",
                                              "secret_enc  (Fernet)"], GREEN, GREEN_SOFT, 260)
    ledger = table(420, 560, "ledger", ["◆ id", "idempotency_key  (unique)", "payer_org_id → organizations",
                                         "payee_org_id → org | NULL=E-DBA", "amount_cents · status"], GREEN, GREEN_SOFT, 260)
    audit = table(780, 560, "audit_events", ["◆ id", "actor_email · org_id · action", "summary · details (JSON)",
                                              "prev_hash → hash of id-1", "hash = sha256(canonical)"], RED, RED_SOFT, 270)

    def edge(a: tuple[float, float, float, float], b: tuple[float, float, float, float], ay: float, by: float,
             side_a: str = "r", side_b: str = "l", color: str = LINE) -> None:
        ax = a[0] + (a[2] if side_a == "r" else 0)
        bx = b[0] + (b[2] if side_b == "r" else 0)
        mid = (ax + bx) / 2
        s.add(f'<path d="M{ax} {ay} C{mid} {ay} {mid} {by} {bx} {by}" fill="none" stroke="{color}" '
              f'stroke-width="1.4" marker-end="url(#a-g)"/>')

    edge(users, org, 172, 140)
    # domain_rules, bank_accounts and ledger hang off organizations through a bus on the left
    bus = 400
    s.add(f'<path d="M{bus} 650 L{bus} 160 L414 160" fill="none" stroke="{LINE}" stroke-width="1.4" '
          f'marker-end="url(#a-g)"/>')
    for yy in (290, 440, 620):
        s.add(f'<path d="M420 {yy} L{bus} {yy}" stroke="{LINE}" stroke-width="1.4"/>'
              f'<circle cx="{bus}" cy="{yy}" r="2.6" fill="{LINE}"/>')
    edge(apps, org, 470, 200)
    edge(revs, apps, 610, 420, "l", "l")
    edge(svc, org, 140, 130, "l", "r")
    edge(eps, svc, 300, 200, "r", "r")
    edge(courses, org, 450, 160, "l", "r")
    # hash chain self-link
    ax, ay, aw, ah = audit
    s.add(f'<path d="M{ax + aw} {ay + 140} C{ax + aw + 50} {ay + 140} {ax + aw + 50} {ay + 40} {ax + aw} {ay + 40}" '
          f'fill="none" stroke="{RED}" stroke-width="1.4" stroke-dasharray="4 3" marker-end="url(#a-r)"/>')
    s.text(ax + aw - 4, ay + ah + 18, "chained: editing or deleting any row breaks verification", 11, RED, 600, "end")
    s.text(40, 740, "Also: otp_challenges (hashed codes, attempt counter) · fee_schedule · policies + policy_versions · help_tickets · mail_messages",
           11.5, MUTED)
    s.save("data_model")


# --------------------------------------------------------------------------- settlement sequence


def settlement() -> None:
    s = Svg(1100, 620, "Cross-organization thesis download sequence")
    s.text(40, 44, "Cross-organization thesis download · sequence", 20, INK, 700)
    s.text(40, 66, "A Harbor (HBU) user downloads a Summit (SIT) thesis. Nothing is charged unless the PDF arrives and the transfer settles.", 12.5, MUTED)
    lanes = [("HBU data user", 110, BLUE), ("E-DBA usage service", 330, BRAND), ("SIT thesis API", 560, ORANGE),
             ("Bank gateway", 780, GREEN), ("Ledger + audit", 990, RED)]
    for name, x, c in lanes:
        s.box(x - 90, 88, 180, 38, "#fff", c, 8, sw=1.6)
        s.text(x, 112, name, 13, c, 700, "middle")
        s.add(f'<line x1="{x}" y1="126" x2="{x}" y2="596" stroke="#d5dae1" stroke-width="1.4" stroke-dasharray="4 4"/>')

    def msg(y: float, a: float, b: float, label: str, c: str = INK, m: str = "g", dash: bool = False,
            note: str = "") -> None:
        s.arrow([(a, y), (b + (-6 if b > a else 6), y)], c if c != INK else LINE, m, dash=dash)
        mx = (a + b) / 2
        s.text(mx, y - 7, label, 11.5, c, 600, "middle")
        if note:
            s.text(mx, y + 15, note, 10.5, MUTED, 400, "middle")

    msg(160, 110, 330, "POST /w/sit/thesis/download", BLUE, "bl")
    s.box(340, 178, 210, 92, BRAND_SOFT, BRAND, 6)
    for i, t in enumerate(["authz: level 1 in SIT ✓", "SIT mode = download ✓", "quota ≥ ¥8.00 (SIT price) ✓",
                           "HBU has a bank account ✓"]):
        s.text(352, 198 + i * 19, t, 11.5, BRAND, 500)
    msg(296, 330, 560, "GET /campus/summit/thesis/pdf?title=…", ORANGE, "o")
    msg(326, 560, 330, "200 application/pdf", ORANGE, "o", dash=True)
    msg(364, 330, 780, "POST /bank/transfer  HBU → SIT  ¥8.00", GREEN, "gr",
        note="Idempotency-Key: replays return the first result")
    msg(408, 780, 330, '{"status": "success"}', GREEN, "gr", dash=True)
    msg(446, 330, 990, "ledger row (settled) + audit events", RED, "r",
        note="payment.settled · thesis.downloaded — hash-chained")
    s.box(340, 476, 210, 34, BRAND_SOFT, BRAND, 6)
    s.text(445, 498, "quota −¥8.00 · commit", 12, BRAND, 700, "middle")
    msg(540, 330, 110, "PDF attachment", BLUE, "bl", dash=True)
    s.box(560, 470, 520, 120, "#fff", "#d5dae1", 10, dash=True)
    s.text(576, 492, "If anything fails", 12.5, INK, 700)
    for i, t in enumerate(["API error / not a PDF → no transfer, no quota taken",
                           "bank refuses → ledger row status=failed is kept, PDF withheld, quota untouched",
                           "same user's own organization → transfer HBU → HBU (quota only)",
                           "display-only theses → 403 before anything is called"]):
        s.text(576, 514 + i * 18, "• " + t, 11.5, MUTED)
    s.save("settlement_sequence")


# --------------------------------------------------------------------------- access matrix


def access() -> None:
    rows = [
        ("Course information · browse/search", ["●", "●", "●", "●", "", "", ""]),
        ("Thesis search · PDF if owner allows", ["●", "●", "●", "●", "", "", ""]),
        ("Student identity authentication", ["", "●", "●", "", "", "", ""]),
        ("Student GPA records (single + batch)", ["", "●", "●", "", "", "", ""]),
        ("Course configurations", ["", "", "●", "", "", "", ""]),
        ("API (connector) configurations", ["", "", "●", "", "", "", ""]),
        ("Bank account · members · services · prices", ["", "", "", "", "●", "", ""]),
        ("Pay membership fees · organization log", ["", "", "", "", "●", "", ""]),
        ("First-stage application review", ["", "", "", "", "", "●", ""]),
        ("Final review (Senior E-Admin, four-eyes)", ["", "", "", "", "", "◐", ""]),
        ("Policies (publish/version) · fee schedule", ["", "", "", "", "", "●", "view"]),
        ("E-Admin accounts · system logs · audit verify · help desk", ["", "", "", "", "", "", "●"]),
    ]
    cols = ["L1 home", "L2 home", "L3 home", "any level,\nother org", "O-Convener", "E-Admin", "T-Admin"]
    W, top, left, cw, rh = 1100, 130, 420, 92, 36
    s = Svg(W, top + rh * len(rows) + 90, "Access matrix")
    s.text(40, 44, "Who can do what", 20, INK, 700)
    s.text(40, 66, "Levels nest (3 ⊃ 2 ⊃ 1). In another organization's workspace everyone is clamped to level 1: public data only.", 12.5, MUTED)
    for j, c in enumerate(cols):
        cx = left + j * cw + cw / 2
        tint = BLUE_SOFT if j == 3 else (BRAND_SOFT if j < 3 else GREY_SOFT)
        s.box(left + j * cw + 3, top - 46, cw - 6, 40, tint, "none", 8)
        for k, ln in enumerate(c.split("\n")):
            s.text(cx, top - 28 + k * 14 - (6 if "\n" in c else -2), ln, 11.5, INK, 700, "middle")
    for i, (label, cells) in enumerate(rows):
        y = top + i * rh
        if i % 2 == 0:
            s.box(30, y, W - 60, rh, "#f8f9fb", "none", 6)
        s.text(44, y + 23, label, 12.5, INK)
        for j, v in enumerate(cells):
            cx, cy = left + j * cw + cw / 2, y + rh / 2
            if v == "●":
                s.add(f'<circle cx="{cx}" cy="{cy}" r="8" fill="{BLUE if j == 3 else BRAND}"/>')
            elif v == "◐":
                s.add(f'<circle cx="{cx}" cy="{cy}" r="8" fill="#fff" stroke="{BRAND}" stroke-width="2"/>'
                      f'<path d="M{cx} {cy - 8} a8 8 0 0 1 0 16 z" fill="{BRAND}"/>')
            elif v:
                s.text(cx, cy + 4, v, 11.5, MUTED, 600, "middle")
            else:
                s.add(f'<line x1="{cx - 5}" y1="{cy}" x2="{cx + 5}" y2="{cy}" stroke="#c9cfd8" stroke-width="1.5"/>')
    yb = top + rh * len(rows) + 30
    s.add(f'<circle cx="50" cy="{yb}" r="7" fill="{BRAND}"/>')
    s.text(64, yb + 4, "allowed", 12, MUTED)
    s.add(f'<circle cx="150" cy="{yb}" r="7" fill="#fff" stroke="{BRAND}" stroke-width="2"/><path d="M150 {yb - 7} a7 7 0 0 1 0 14 z" fill="{BRAND}"/>')
    s.text(164, yb + 4, "Senior E-Admins only", 12, MUTED)
    s.text(340, yb + 4, "Paid services also require quota; each service appears only after the O-Convener adds it and a level-3 provider configures its API.", 12, MUTED)
    s.save("access_matrix")


if __name__ == "__main__":
    architecture()
    registration()
    er()
    settlement()
    access()
