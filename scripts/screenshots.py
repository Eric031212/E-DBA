"""Capture README screenshots from a running, seeded instance.

    uv run edba init && uv run edba seed && uv run edba serve &
    python scripts/screenshots.py http://127.0.0.1:8000 docs/screenshots

Needs ``pip install playwright && playwright install chromium``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "docs/screenshots")
OUT.mkdir(parents=True, exist_ok=True)


def login(page: Page, email: str) -> None:
    page.goto(f"{BASE}/login")
    page.fill("input[name=email]", email)
    page.click("button:has-text('Send code')")
    page.wait_for_url("**/login/verify")
    mail = page.context.new_page()
    mail.goto(f"{BASE}/dev/mailbox?to={email}")
    code = re.search(r"verification code: (\d{6})", mail.content()).group(1)  # type: ignore[union-attr]
    mail.close()
    page.fill("input[name=code]", code)
    page.click("button:has-text('Sign in')")
    page.wait_for_load_state("networkidle")


def shot(page: Page, name: str, full: bool = False) -> None:
    page.wait_for_load_state("networkidle")
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
    print("saved", name)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()

        def ctx(dark: bool = False):  # type: ignore[no-untyped-def]
            return browser.new_context(viewport={"width": 1360, "height": 860}, device_scale_factor=2,
                                       color_scheme="dark" if dark else "light")

        page = ctx().new_page()
        page.goto(BASE)
        shot(page, "landing")

        # Level-2 data user: dashboard, GPA batch, theses across organizations
        page = ctx().new_page()
        login(page, "staff@harbor.example")
        shot(page, "workspace_level2")
        page.goto(f"{BASE}/w/hbu/s/gpa-record")
        csv = OUT / "_batch.csv"
        csv.write_text("name,id\nAda Lin,H2021001\nChen Yu,H2022003\nEli Novak,H2023005\nGhost,H0000000\n")
        page.set_input_files("input[name=file]", str(csv))
        page.click("button:has-text('Run batch')")
        page.wait_for_selector("#result table")
        shot(page, "gpa_batch", full=True)
        csv.unlink()
        page.goto(f"{BASE}/w/sit/thesis?q=learning")
        shot(page, "thesis_cross_org")
        page.goto(f"{BASE}/workspaces")
        shot(page, "workspaces")

        # Level-3 provider: connector configuration
        page = ctx().new_page()
        login(page, "provider@harbor.example")
        shot(page, "workspace_level3")
        page.goto(f"{BASE}/w/hbu/connectors/thesis")
        shot(page, "connector_thesis", full=True)

        # O-Convener
        page = ctx().new_page()
        login(page, "convener@harbor.example")
        shot(page, "convener_overview")
        page.goto(f"{BASE}/org/services")
        shot(page, "convener_services", full=True)
        page.goto(f"{BASE}/org/fees")
        shot(page, "convener_fees", full=True)

        # Senior E-Admin reviewing; T-Admin logs (dark theme)
        page = ctx().new_page()
        login(page, "senior@edba.example")
        page.goto(f"{BASE}/admin/applications/3")
        shot(page, "review_application")
        page = ctx(dark=True).new_page()
        login(page, "tadmin@edba.example")
        shot(page, "tadmin_overview_dark")
        page.goto(f"{BASE}/admin/logs")
        shot(page, "system_logs_dark")
        browser.close()


if __name__ == "__main__":
    main()
