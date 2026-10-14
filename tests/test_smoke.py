import pytest

PAGES = {
    "tadmin@edba.example": [
        "/admin",
        "/admin/e-admins",
        "/admin/logs",
        "/admin/help",
        "/admin/applications",
        "/admin/policies",
    ],
    "senior@edba.example": [
        "/admin",
        "/admin/applications",
        "/admin/applications/3",
        "/admin/policies",
        "/admin/fees",
        "/help",
    ],
    "convener@harbor.example": [
        "/org",
        "/org/bank",
        "/org/members",
        "/org/services",
        "/org/fees",
        "/org/logs",
        "/policies",
    ],
    "provider@harbor.example": [
        "/w/hbu",
        "/w/hbu/courses",
        "/w/hbu/courses/manage",
        "/w/hbu/connectors",
        "/w/hbu/connectors/thesis",
        "/w/hbu/connectors/gpa-record",
        "/w/hbu/s/gpa-record",
        "/w/hbu/s/identity-auth",
        "/w/hbu/thesis?q=learning",
        "/workspaces",
        "/w/sit",
        "/me",
    ],
    "dean@lakeside.example": ["/application"],
}


@pytest.mark.parametrize("email", list(PAGES))
def test_every_page_renders(make_browser, email):
    b = make_browser()
    r = b.login(email)
    assert r.status_code == 200, r.text[:500]
    for path in PAGES[email]:
        r = b.get(path)
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:800]}"


def test_public_pages(browser):
    for path in [
        "/",
        "/login",
        "/apply",
        "/policies",
        "/dev/mailbox",
        "/api/docs",
        "/api/v1/healthz",
    ]:
        assert browser.get(path).status_code == 200, path
