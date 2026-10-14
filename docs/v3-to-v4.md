# From v3 to v4

E-DBA v3 was the 2025 course build: a Flask app (~15k lines of Python and templates, including one 2,600-line controller and 53 templates) on MySQL, talking to a lab server at `172.16.160.88:8001` that no longer exists. v4 is a rewrite of the same product. The domain, the roles and every rule in the final *E-DBA Update Requirement* document (sections a–m) are kept. The code, the data model and the infrastructure are new.

## What changed and why

| Area | v3 | v4 |
|---|---|---|
| Framework | Flask blueprints, logic inside route functions | FastAPI; routes are thin, rules live in `edba/services/*`, permissions in `edba/authz.py` |
| ORM / schema | Flask-SQLAlchemy, joined-table inheritance (`InvalidUser → UnderReviewUser → OConvener …`); state changes deleted and re-inserted user rows | SQLAlchemy 2.0 typed models; one `users` table with a `role` column; Alembic migrations |
| Database | MySQL only, hand-written `reset_database.py`, `fix_log_tables.py`, … | SQLite for development, PostgreSQL 16 in production; same test suite runs on both |
| Sign-in | 6-digit code stored in plain text on the user row, `random.randint`, no attempt limit | `secrets`-generated code, HMAC-hashed in its own table, single use, 5-minute expiry, 5-attempt lock-out |
| Simulated email | Separate mailbox accounts with passwords (default `12345678`) | Pluggable mail backend: `inbox` (dev mailbox page) or real SMTP |
| Money | Float RMB and integer "cents" mixed between tables | Integer cents everywhere, formatted only at the edge |
| Payments | Direct calls to the bank API, no record of failures | Ledger table with a unique idempotency key per transfer; failed transfers are kept; results are only released after settlement |
| Bank passwords | Stored in plain text (the spec explicitly allowed it) | Fernet-encrypted at rest |
| Logs | Four log tables, free-text details | One append-only `audit_events` table, SHA-256 hash-chained, verifiable from the UI, the API and the CLI |
| External services | Hard-coded lab URLs | Demo gateway shipped in the repo (`edba.gateway`) with the same contract; connectors validated, host allow-list, timeouts |
| Security | No CSRF protection, 27 `DEBUG` prints left in request handlers | CSRF double-submit on every form/htmx call, signed session cookie, security headers, upload type/size/PDF-magic checks |
| UI | Bootstrap pages, mixed Chinese/English messages | One CSS design system with light/dark themes, htmx partial updates, English throughout |
| API | none | `/api/v1` with bearer tokens and OpenAPI docs |
| Tests | none | 69 tests (93 % line coverage) on SQLite and PostgreSQL; CI with lint, type check, migrations and a Docker smoke test |

## Requirement traceability

Every section of the v3 update-requirement document, where it lives now, and the test that proves it.

| § | Requirement | Implementation | Test |
|---|---|---|---|
| a | T-Admin can view (not edit) policies; drop "System Backups" | `web/admin.py::policy_admin` (`can_edit` only for E-Admins) | `test_admin.py::test_policies_versioned_and_read_only_for_t_admin` |
| b | Review log entries name the application, organization and convener | `services/registration.py::review` audit summary | `test_registration.py::test_review_log_names_org_and_convener` |
| c | A Senior E-Admin rejection after E-Admin approval must show as such | Timeline derived from `application_reviews`, `registration.timeline` | `test_registration.py::test_senior_rejection_is_attributed_to_senior` |
| d | `*@domain` rows in the member list admit a whole email domain | `services/members.py`, `services/auth.py::resolve_sign_in` | `test_members.py::test_domain_sign_in_matches_exact_domain` (+ 4 more) |
| e | Each service added at most once, removable; course created as *active* stays active; English messages | `services/catalog.py::add_service`, `services/courses.py` | `test_services.py::test_each_service_once_and_removable`, `::test_course_status_and_permissions` |
| f | Dashboard buttons depend on access level and on the services added | `web/workspace.py::tiles` | `test_services.py::test_dashboard_buttons_by_level` |
| g | O-Convener sets a price for the three paid services | `OrgService.price_cents`, `catalog.update_service` | `test_services.py::test_price_and_thesis_mode` |
| h | Course info vs. course configuration pages; API configuration by level 3 only; services inactive until configured; pages generated from the API schema | `catalog.is_active`, `web/workspace.py::connector_*`, `templates/ws/service.html` | `test_services.py::test_services_need_configured_api`, `::test_connector_validation` |
| i | Thesis *display only* vs *download* | `ThesisMode`, `usage.thesis_download` | `test_usage.py::test_display_only_blocks_download_everywhere` |
| j | Bank account verified by the bank before it is stored; required before paid services | `billing.set_bank_account`, `catalog.add_service` | `test_billing.py::test_bank_account_verified_with_bank_and_encrypted`, `test_services.py::test_paid_service_needs_bank_account` |
| k | Membership fees: level 1 once per organization, levels 2/3 per person; unpaid users cannot sign in; E-Admin edits the fees | `billing.membership_quote`, `billing.pay_membership`, `auth.resolve_sign_in` | `test_billing.py::test_membership_fees_per_level`, `::test_e_admin_sets_fees`, `::test_insufficient_funds_is_reported_and_logged` |
| l | Charging: per record for identity/GPA (incl. batch upload), per PDF for theses; transfers to E-DBA or to the providing organization; everything logged | `services/usage.py` | `test_usage.py` (8 tests) |
| m | Users can visit other workspaces, where they act as level 1 | `authz.effective_level`, `web/workspace.py::directory` | `test_usage.py::test_cross_org_download_pays_the_provider`, `::test_cross_org_is_clamped_to_level1` |

## Decisions the specification left open

* **Domain rules with level 2 or 3.** The spec only described level-1 wildcard rows. v4 creates the account on first sign-in for any level, but a level-2/3 account then needs its per-person fee like any other member.
* **Upgrading a member's level** in a later member-list import marks the higher fee as due again.
* **Failed lookups are free.** For batch uploads only the rows the organization's API answered successfully are charged, and the user's quota must cover the whole batch up front.
* **Four-eyes rule.** A Senior E-Admin may do the first review, but then a different Senior must do the final one.
* **Settlement before release.** If the bank refuses a transfer the PDF / lookup result is withheld and no quota is taken; the failed transfer stays in the ledger.
